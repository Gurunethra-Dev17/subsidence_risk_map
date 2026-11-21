"""Assign VLM points to buildings and estimate building-level motion."""
from __future__ import annotations

import math


class AssignmentError(ValueError):
    """Raised when building or point inputs do not meet the assignment contract."""


def _weighted_quantile(values, weights, quantile: float) -> float:
    """Return a linearly interpolated weighted quantile for finite observations."""
    import numpy as np

    order = np.argsort(values, kind="stable")
    sorted_values = np.asarray(values, dtype=float)[order]
    sorted_weights = np.asarray(weights, dtype=float)[order]
    total = sorted_weights.sum()
    if not math.isfinite(float(total)) or total <= 0:
        raise AssignmentError("Weighted quantile received invalid weights")
    # Midpoint plotting positions preserve ordinary linear quantiles when the
    # observations have equal weights and behave smoothly for IDW weights.
    positions = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / total
    return float(np.interp(quantile, positions, sorted_values,
                           left=sorted_values[0], right=sorted_values[-1]))


def _assign_projected(building_coords, point_coords, rates, radius_m: float,
                      min_points: int, chunk_size: int):
    """Core radius assignment over already projected coordinate arrays."""
    import numpy as np
    from scipy.spatial import cKDTree

    building_coords = np.asarray(building_coords, dtype=float).reshape((-1, 2))
    point_coords = np.asarray(point_coords, dtype=float).reshape((-1, 2))
    rates = np.asarray(rates, dtype=float)
    if len(point_coords) != len(rates):
        raise AssignmentError("each point coordinate must have one VLM rate")
    if not np.isfinite(point_coords).all() or not np.isfinite(rates).all():
        raise AssignmentError("point coordinates and VLM rates must be finite")

    n_buildings = len(building_coords)
    counts = np.zeros(n_buildings, dtype=np.int32)
    estimates = np.full(n_buildings, np.nan, dtype=np.float64)
    iqrs = np.full(n_buildings, np.nan, dtype=np.float64)
    if len(point_coords) == 0:
        return counts, estimates, iqrs

    tree = cKDTree(point_coords)
    valid_centroids = np.isfinite(building_coords).all(axis=1)
    for start in range(0, n_buildings, chunk_size):
        stop = min(start + chunk_size, n_buildings)
        coords = building_coords[start:stop]
        valid_positions = np.flatnonzero(valid_centroids[start:stop])
        if not len(valid_positions):
            continue
        neighbors = tree.query_ball_point(coords[valid_positions], r=radius_m)
        for local_position, indices in zip(valid_positions, neighbors):
            row = start + int(local_position)
            counts[row] = len(indices)
            if len(indices) < min_points:
                continue
            idx = np.asarray(indices, dtype=np.intp)
            distances = np.linalg.norm(point_coords[idx] - coords[local_position], axis=1)
            exact = distances <= np.finfo(float).eps
            if exact.any():
                values = rates[idx[exact]]
                weights = np.ones(len(values), dtype=float)
            else:
                values = rates[idx]
                weights = 1.0 / distances
            estimates[row] = _weighted_quantile(values, weights, 0.5)
            iqrs[row] = (
                _weighted_quantile(values, weights, 0.75)
                - _weighted_quantile(values, weights, 0.25)
            )
    return counts, estimates, iqrs


def assign_points_to_buildings(buildings, points, cfg, chunk_size: int = 50_000):
    """Estimate VLM for each building from points within the configured radius.

    Buildings and point geometries are projected to the configured UTM CRS for
    centroid and distance calculations. A building is sparse when fewer than
    ``min_points`` points fall within ``radius_m``. Its VLM estimate and IQR are
    null in that case. Otherwise, both are inverse-distance weighted; exact
    coincident observations share weight equally and dominate non-coincident
    observations.

    The building array is processed in chunks so the spatial query result does
    not need to hold all buildings' neighbor lists at once. The returned
    DataFrame retains building input order and contains the C1 assignment
    columns: ``bldg_id``, ``n_points``, ``vlm_mm_yr``, ``vlm_iqr_mm_yr`` and
    ``sparse``.
    """
    try:
        import geopandas as gpd
        import numpy as np
        import pandas as pd
        import scipy  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on optional geo extra
        raise AssignmentError(
            "Building assignment requires the 'geo' dependencies; "
            "install with pip install -e '.[geo]'"
        ) from exc

    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise AssignmentError("chunk_size must be a positive integer")
    if not hasattr(cfg, "params") or not hasattr(cfg, "utm_epsg"):
        raise AssignmentError("cfg must be a parsed C6 Config")
    try:
        radius_m = float(cfg.params["radius_m"])
        min_points = int(cfg.params["min_points"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AssignmentError("C6 params must define numeric radius_m and integer min_points") from exc
    if not math.isfinite(radius_m) or radius_m <= 0:
        raise AssignmentError("radius_m must be a finite positive distance in metres")
    if min_points < 1:
        raise AssignmentError("min_points must be at least 1")

    if not isinstance(buildings, gpd.GeoDataFrame):
        raise AssignmentError("buildings must be a GeoDataFrame")
    if not isinstance(points, gpd.GeoDataFrame):
        raise AssignmentError("points must be a GeoDataFrame")
    for frame, label in ((buildings, "buildings"), (points, "points")):
        if frame.crs is None:
            raise AssignmentError(f"{label} must declare a CRS")
    if "bldg_id" not in buildings.columns:
        raise AssignmentError("buildings are missing required 'bldg_id' column")
    if "vlm_mm_yr" not in points.columns:
        raise AssignmentError("points are missing required 'vlm_mm_yr' column")
    if buildings["bldg_id"].isna().any() or buildings["bldg_id"].astype(str).str.strip().eq("").any():
        raise AssignmentError("building IDs must be present and non-empty")
    if buildings["bldg_id"].astype(str).duplicated().any():
        raise AssignmentError("building IDs must be unique")

    rates = pd.to_numeric(points["vlm_mm_yr"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(rates).all():
        raise AssignmentError("point vlm_mm_yr values must be finite numbers")
    if points.geometry.isna().any() or points.geometry.is_empty.any():
        raise AssignmentError("point geometries must be present and non-empty")
    if not points.geometry.geom_type.eq("Point").all():
        raise AssignmentError("points geometry must contain Point features")

    target_crs = f"EPSG:{int(cfg.utm_epsg)}"
    try:
        point_xy = points.to_crs(target_crs).geometry
        projected_buildings = buildings.to_crs(target_crs)
        centroids = projected_buildings.geometry.centroid
    except Exception as exc:
        raise AssignmentError(f"Could not project inputs to {target_crs}: {exc}") from exc

    point_coords = np.column_stack((point_xy.x.to_numpy(), point_xy.y.to_numpy()))
    if not np.isfinite(point_coords).all():
        raise AssignmentError("point geometries must project to finite UTM coordinates")
    building_ids = buildings["bldg_id"].astype(str).to_numpy()
    n_buildings = len(buildings)
    centroid_coords = np.column_stack((centroids.x.to_numpy(dtype=float), centroids.y.to_numpy(dtype=float)))
    counts, estimates, iqrs = _assign_projected(
        centroid_coords, point_coords, rates, radius_m, min_points, chunk_size,
    )

    sparse = counts < min_points
    result = pd.DataFrame({
        "bldg_id": building_ids,
        "n_points": counts,
        "vlm_mm_yr": estimates,
        "vlm_iqr_mm_yr": iqrs,
        "sparse": sparse,
    })
    # Pandas represents null numeric values as NaN in memory; the C1 exporter
    # should write these as Parquet nulls (and never replace them with zero).
    result.attrs["utm_epsg"] = int(cfg.utm_epsg)
    result.attrs["radius_m"] = radius_m
    result.attrs["min_points"] = min_points
    return result
