"""Estimate building-scale angular distortion from nearby VLM point pairs."""
from __future__ import annotations

import math


class DistortionError(ValueError):
    """Raised when distortion inputs or C6 parameters are invalid."""


def _read_parameters(cfg):
    if not hasattr(cfg, "params") or not hasattr(cfg, "utm_epsg"):
        raise DistortionError("cfg must be a parsed C6 Config")

    try:
        params = cfg.params
        pair_min_m = float(params["pair_min_m"])
        pair_max_m = float(params["pair_max_m"])
        footprint_buffer_m = float(params["footprint_buffer_m"])
        horizon_years = float(params["horizon_years"])
        class_edges_ratio = tuple(float(value) for value in params["class_edges_ratio"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DistortionError(
            "C6 params must define numeric pair_min_m, pair_max_m, "
            "footprint_buffer_m, horizon_years, and class_edges_ratio"
        ) from exc

    numeric_params = (pair_min_m, pair_max_m, footprint_buffer_m, horizon_years)
    if not all(math.isfinite(value) for value in numeric_params):
        raise DistortionError("distortion parameters must be finite")
    if pair_min_m <= 0 or pair_max_m < pair_min_m:
        raise DistortionError("pair distances must satisfy 0 < pair_min_m <= pair_max_m")
    if footprint_buffer_m < 0:
        raise DistortionError("footprint_buffer_m must be non-negative")
    if horizon_years <= 0:
        raise DistortionError("horizon_years must be positive")
    if len(class_edges_ratio) != 2:
        raise DistortionError("class_edges_ratio must contain two denominator thresholds")
    if (not all(math.isfinite(value) and value > 0 for value in class_edges_ratio)
            or class_edges_ratio[0] <= class_edges_ratio[1]):
        raise DistortionError("class_edges_ratio must be two positive descending values")
    return pair_min_m, pair_max_m, footprint_buffer_m, horizon_years, class_edges_ratio


def _ratio_string(beta_horizon: float) -> str:
    """Format cumulative distortion as the nearest 1/N ratio.

    Zero distortion is represented as ``1/inf`` because it has no finite
    denominator.
    """
    if not math.isfinite(beta_horizon) or beta_horizon < 0:
        raise DistortionError("horizon distortion must be finite and non-negative")
    if beta_horizon == 0:
        return "1/inf"
    denominator = max(1, round(1.0 / beta_horizon))
    return f"1/{denominator}"


def _classify(beta_horizon: float, class_edges_ratio: tuple[float, float]) -> str:
    """Map cumulative distortion to the configured low/watch/inspect bands."""
    watch_edge, inspect_edge = class_edges_ratio
    if beta_horizon >= 1.0 / inspect_edge:
        return "inspect"
    if beta_horizon >= 1.0 / watch_edge:
        return "watch"
    return "low"


def _pair_distortion(rate_i_mm_yr: float, rate_j_mm_yr: float, distance_m: float) -> float:
    """Compute absolute differential settlement per year for one point pair."""
    if not math.isfinite(distance_m) or distance_m <= 0:
        raise DistortionError("point-pair distance must be finite and positive")
    beta_rate = abs(rate_i_mm_yr - rate_j_mm_yr) * 1e-3 / distance_m
    if not math.isfinite(beta_rate):
        raise DistortionError("point-pair distortion must be finite")
    return beta_rate


def _pair_rates_for_building(
    anchor_indices,
    point_coords,
    rates_mm_yr,
    point_tree,
    pair_min_m: float,
    pair_max_m: float,
):
    """Return distinct pair rates touching this building's buffered footprint.

    Every point inside the buffered footprint is an anchor. Its neighbors may
    be anywhere within ``pair_max_m``; this includes pairs with exactly one
    endpoint in the footprint. A pair whose two endpoints are both anchors is
    counted once.
    """
    import numpy as np

    anchors = np.unique(np.asarray(anchor_indices, dtype=np.intp))
    anchor_set = set(anchors.tolist())
    pair_rates = []
    n_pairs = 0

    for first in anchors:
        candidates = point_tree.query_ball_point(point_coords[first], r=pair_max_m)
        for second in candidates:
            if second == first:
                continue
            # If both endpoints are anchors, the pair was or will be visited
            # from the lower-index endpoint. Outside endpoints have no anchor
            # iteration of their own for this building.
            if second in anchor_set and second < first:
                continue
            distance_m = float(np.linalg.norm(point_coords[first] - point_coords[second]))
            if distance_m < pair_min_m or distance_m > pair_max_m:
                continue
            n_pairs += 1
            pair_rates.append(_pair_distortion(
                float(rates_mm_yr[first]), float(rates_mm_yr[second]), distance_m,
            ))
    return n_pairs, np.asarray(pair_rates, dtype=float)


def compute_building_distortion(buildings, points, cfg):
    """Compute C1 angular-distortion fields for each building.

    For each building, the function uses distinct point pairs at distances
    between ``pair_min_m`` and ``pair_max_m`` where at least one endpoint lies
    inside the building footprint buffered by ``footprint_buffer_m``. Pair
    distortion is ``abs(v_i - v_j) * 1e-3 / distance_m`` per year, with rates
    in mm/year. The building rate is the 90th percentile of pair rates, but is
    null when fewer than three pairs are available. The configured horizon is
    a scenario multiplier, not a forecast.

    Returns a DataFrame in building input order with columns ``bldg_id``,
    ``n_pairs``, ``beta_rate_per_yr``, ``beta_horizon``,
    ``beta_ratio_horizon``, and ``beta_class``.
    """
    try:
        import geopandas as gpd
        import numpy as np
        import pandas as pd
        from scipy.spatial import cKDTree
    except ImportError as exc:  # pragma: no cover - optional geo dependencies
        raise DistortionError(
            "Building distortion requires the 'geo' dependencies; "
            "install with pip install -e '.[geo]'"
        ) from exc

    pair_min_m, pair_max_m, buffer_m, horizon_years, class_edges_ratio = _read_parameters(cfg)
    if not isinstance(buildings, gpd.GeoDataFrame):
        raise DistortionError("buildings must be a GeoDataFrame")
    if not isinstance(points, gpd.GeoDataFrame):
        raise DistortionError("points must be a GeoDataFrame")
    if buildings.crs is None or points.crs is None:
        raise DistortionError("buildings and points must declare a CRS")
    if "bldg_id" not in buildings.columns:
        raise DistortionError("buildings are missing required 'bldg_id' column")
    if "vlm_mm_yr" not in points.columns:
        raise DistortionError("points are missing required 'vlm_mm_yr' column")
    if (buildings["bldg_id"].isna().any()
            or buildings["bldg_id"].astype(str).str.strip().eq("").any()):
        raise DistortionError("building IDs must be present and non-empty")
    if buildings["bldg_id"].astype(str).duplicated().any():
        raise DistortionError("building IDs must be unique")
    if buildings.geometry.isna().any() or buildings.geometry.is_empty.any():
        raise DistortionError("building geometries must be present and non-empty")
    if not buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise DistortionError("building geometry must contain Polygon or MultiPolygon features")
    if not buildings.geometry.is_valid.all():
        raise DistortionError("building geometries must be valid")
    if points.geometry.isna().any() or points.geometry.is_empty.any():
        raise DistortionError("point geometries must be present and non-empty")
    if not points.geometry.geom_type.eq("Point").all():
        raise DistortionError("points geometry must contain Point features")

    rates_mm_yr = pd.to_numeric(points["vlm_mm_yr"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(rates_mm_yr).all():
        raise DistortionError("point vlm_mm_yr values must be finite numbers")

    target_crs = f"EPSG:{int(cfg.utm_epsg)}"
    try:
        projected_buildings = buildings.to_crs(target_crs).reset_index(drop=True)
        projected_points = points.to_crs(target_crs).reset_index(drop=True)
    except Exception as exc:
        raise DistortionError(f"Could not project inputs to {target_crs}: {exc}") from exc

    building_ids = buildings["bldg_id"].astype(str).to_numpy()
    n_buildings = len(buildings)
    pair_counts = np.zeros(n_buildings, dtype=np.int32)
    beta_rates = np.full(n_buildings, np.nan, dtype=float)
    beta_horizons = np.full(n_buildings, np.nan, dtype=float)
    ratios = np.full(n_buildings, None, dtype=object)
    classes = np.full(n_buildings, None, dtype=object)

    if n_buildings and len(points):
        point_coords = np.column_stack((
            projected_points.geometry.x.to_numpy(dtype=float),
            projected_points.geometry.y.to_numpy(dtype=float),
        ))
        if not np.isfinite(point_coords).all():
            raise DistortionError("point geometries must project to finite UTM coordinates")
        point_tree = cKDTree(point_coords)

        point_frame = gpd.GeoDataFrame(
            {"point_pos": np.arange(len(points), dtype=np.int64)},
            geometry=projected_points.geometry,
            crs=target_crs,
        )
        buffered_buildings = gpd.GeoDataFrame(
            {"building_pos": np.arange(n_buildings, dtype=np.int64)},
            geometry=projected_buildings.geometry.buffer(buffer_m),
            crs=target_crs,
        )
        try:
            matches = gpd.sjoin(
                point_frame, buffered_buildings, how="inner", predicate="intersects",
            )
        except Exception as exc:
            raise DistortionError(f"Could not match points to buffered buildings: {exc}") from exc

        anchors_by_building = [[] for _ in range(n_buildings)]
        for building_pos, point_pos in zip(matches["building_pos"], matches["point_pos"]):
            anchors_by_building[int(building_pos)].append(int(point_pos))

        for building_pos, anchor_indices in enumerate(anchors_by_building):
            if not anchor_indices:
                continue
            n_pairs, pair_rates = _pair_rates_for_building(
                anchor_indices,
                point_coords,
                rates_mm_yr,
                point_tree,
                pair_min_m,
                pair_max_m,
            )
            pair_counts[building_pos] = n_pairs
            if n_pairs < 3:
                continue
            beta_rate = float(np.percentile(pair_rates, 90))
            beta_horizon = beta_rate * horizon_years
            if not math.isfinite(beta_horizon):
                raise DistortionError("horizon distortion must be finite")
            beta_rates[building_pos] = beta_rate
            beta_horizons[building_pos] = beta_horizon
            ratios[building_pos] = _ratio_string(beta_horizon)
            classes[building_pos] = _classify(beta_horizon, class_edges_ratio)

    result = pd.DataFrame({
        "bldg_id": building_ids,
        "n_pairs": pair_counts,
        "beta_rate_per_yr": beta_rates,
        "beta_horizon": beta_horizons,
        "beta_ratio_horizon": ratios,
        "beta_class": classes,
    })
    result.attrs["utm_epsg"] = int(cfg.utm_epsg)
    result.attrs["pair_min_m"] = pair_min_m
    result.attrs["pair_max_m"] = pair_max_m
    result.attrs["footprint_buffer_m"] = buffer_m
    result.attrs["horizon_years"] = horizon_years
    result.attrs["class_edges_ratio"] = class_edges_ratio
    result.attrs["rate_sign_convention"] = "negative = sinking; pair rates use absolute differences"
    return result
