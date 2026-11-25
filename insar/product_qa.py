"""Offline QA and frontend handoff artifacts for an ASF HyP3 burst InSAR product.

This module reports one-pair relative line-of-sight (LOS) observations. It does
not estimate vertical subsidence, annual velocity, damage probability, or
independent validation against the historical Inspection Index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_COHERENCE_THRESHOLD = 0.30
SENSITIVITY_THRESHOLDS = (0.20, 0.30, 0.40, 0.50)
LOS_CM_PER_2PI = 2.8
MAX_OVERLAY_DIMENSION = 3000


class ProductQAError(ValueError):
    """Raised when a product or spatial input cannot be safely interpreted."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _one_file(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1 or not matches[0].is_file():
        raise ProductQAError(f"expected exactly one product file matching {pattern}")
    return matches[0]


def _parse_parameter_text(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _acquisition_date(granule: str) -> str | None:
    match = re.search(r"_(\d{8})T\d{6}_", granule)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()


def _stats(values: np.ndarray) -> dict[str, float | int] | None:
    flat = np.asarray(values, dtype=np.float64).reshape(-1)
    flat = flat[np.isfinite(flat)]
    if not flat.size:
        return None
    p = np.percentile(flat, [1, 5, 25, 50, 75, 95, 99])
    return {
        "count": int(flat.size),
        "min": float(flat.min()),
        "max": float(flat.max()),
        "mean": float(flat.mean()),
        "median": float(np.median(flat)),
        "p01": float(p[0]),
        "p05": float(p[1]),
        "p25": float(p[2]),
        "p50": float(p[3]),
        "p75": float(p[4]),
        "p95": float(p[5]),
        "p99": float(p[6]),
    }


def _geometry_inputs(wards_path: Path, c2_path: Path, raster_crs):
    import shapely
    from pyproj import CRS, Transformer
    from shapely.geometry import shape

    try:
        wards_doc = json.loads(wards_path.read_text(encoding="utf-8"))
        c2_doc = json.loads(c2_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductQAError("ward geometry or C2 summary is unreadable JSON") from exc
    if (
        not isinstance(wards_doc, dict)
        or wards_doc.get("type") != "FeatureCollection"
        or not isinstance(wards_doc.get("features"), list)
    ):
        raise ProductQAError("ward geometry must be a GeoJSON FeatureCollection")
    if not isinstance(c2_doc, dict) or c2_doc.get("contract") != "C2@1.0":
        raise ProductQAError("C2 ward summary must declare C2@1.0")
    ward_crs_value = (wards_doc.get("crs") or {}).get("properties", {}).get("name")
    try:
        source_crs = CRS.from_user_input(ward_crs_value or "OGC:CRS84")
        transformer = Transformer.from_crs(source_crs, raster_crs, always_xy=True)
    except Exception as exc:
        raise ProductQAError("ward geometry CRS cannot be transformed to product CRS") from exc
    c2_wards = c2_doc.get("wards")
    if not isinstance(c2_wards, list):
        raise ProductQAError("C2 summary has no wards list")
    c2_by_id = {str(item.get("ward_id")): item for item in c2_wards if isinstance(item, dict)}

    wards = []
    seen_ids: set[str] = set()
    for feature in wards_doc["features"]:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise ProductQAError("ward feature or properties are malformed")
        properties = feature["properties"]
        ward_id = str(properties.get("ward_id", ""))
        if not ward_id or ward_id in seen_ids:
            raise ProductQAError("ward geometry has a missing or duplicate ward_id")
        seen_ids.add(ward_id)
        try:
            geom = shape(feature.get("geometry"))
        except Exception as exc:
            raise ProductQAError("ward geometry cannot be decoded") from exc
        if geom.is_empty or not geom.is_valid or geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ProductQAError("ward geometries must be valid non-empty polygons")
        projected = shapely.transform(geom, transformer.transform, interleaved=False)
        c2_ward = c2_by_id.get(ward_id, {})
        wards.append(
            {
                "ward_id": ward_id,
                "ward_name": str(properties.get("ward_name") or c2_ward.get("ward_name") or ""),
                "geometry": projected,
                "c2_status": c2_ward.get("status"),
                "c2_rank": c2_ward.get("rank"),
            }
        )
    if not wards:
        raise ProductQAError("ward geometry has no polygon features")
    return wards, c2_doc


def _geometry_raster_window(geometry, raster_shape, transform):
    height, width = raster_shape
    if transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
        raise ProductQAError("coverage area requires a north-up projected raster grid")
    minx, miny, maxx, maxy = geometry.bounds
    col0 = min(width, max(0, math.floor((minx - transform.c) / transform.a)))
    col1 = min(width, max(0, math.ceil((maxx - transform.c) / transform.a)))
    row0 = min(height, max(0, math.floor((transform.f - maxy) / -transform.e)))
    row1 = min(height, max(0, math.ceil((transform.f - miny) / -transform.e)))
    return row0, row1, col0, col1


def _geometry_pixel_intersection_areas(geometry, raster_shape, transform):
    """Return raster row/column indices and exact pixel intersection areas."""
    import shapely

    row0, row1, col0, col1 = _geometry_raster_window(geometry, raster_shape, transform)
    if col0 >= col1 or row0 >= row1:
        return np.empty(0, dtype=int), np.empty(0, dtype=int), np.empty(0, dtype=float)

    rows, cols = np.indices((row1 - row0, col1 - col0))
    rows = (rows + row0).reshape(-1)
    cols = (cols + col0).reshape(-1)
    x0 = transform.c + cols * transform.a
    x1 = x0 + transform.a
    y1 = transform.f + rows * transform.e
    y0 = y1 + transform.e
    pixels = shapely.box(x0, y0, x1, y1)
    areas = np.asarray(shapely.area(shapely.intersection(geometry, pixels)), dtype=float)
    positive = areas > 0
    return rows[positive], cols[positive], areas[positive]


def _coverage_percent(area: float, geometry_area: float) -> float:
    if geometry_area <= 0:
        raise ProductQAError("ward geometry must have positive area")
    if area < 0:
        raise ProductQAError("usable pixel intersection area is negative")
    overrun = area - geometry_area
    if overrun > geometry_area * 1e-12:
        raise ProductQAError("usable pixel intersection area exceeds its ward geometry")
    # GEOS overlay arithmetic can exceed a partition's known area by a few
    # floating-point ulps. That correction is explicitly measured in QA output.
    return min(area, geometry_area) / geometry_area * 100


def _ward_chart_rows(wards: list[dict[str, Any]], limit: int = 15) -> list[dict[str, Any]]:
    ranked = sorted(
        wards,
        key=lambda row: (
            -row["usable_pixel_intersection_area_pct_of_full_ward"],
            str(row["ward_id"]),
        ),
    )
    selected_ids = {row["ward_id"] for row in ranked[:limit]}
    selected_ids.update(row["ward_id"] for row in wards if row["ward_id"] in {"131", "133"})
    return [row for row in ranked if row["ward_id"] in selected_ids]


def _render_figures(
    output_dir: Path,
    profile,
    coherence,
    phase_cm,
    components,
    valid_mask,
    wards,
    threshold: float,
    reference_date: str,
    secondary_date: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.lines import Line2D

    extent = (
        profile["bounds"][0],
        profile["bounds"][2],
        profile["bounds"][1],
        profile["bounds"][3],
    )
    fig, axes = plt.subplots(1, 3, figsize=(17, 6))
    fig.subplots_adjust(left=0.055, right=0.97, bottom=0.18, top=0.80, wspace=0.34)
    coh = np.ma.masked_where(~np.isfinite(coherence) | (coherence <= 0), coherence)
    image = axes[0].imshow(coh, extent=extent, origin="upper", cmap="viridis", vmin=0, vmax=1)
    fig.colorbar(image, ax=axes[0], shrink=0.75, label="Normalized coherence (0-1)")
    axes[0].set_title("Coherence; zero/nodata omitted")

    disp = np.ma.masked_where(~valid_mask, phase_cm)
    vals = phase_cm[valid_mask]
    limit = float(np.percentile(np.abs(vals), 98)) if vals.size else 1.0
    limit = max(limit, 1e-6)
    image = axes[1].imshow(
        disp,
        extent=extent,
        origin="upper",
        cmap="coolwarm",
        norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit),
    )
    fig.colorbar(
        image,
        ax=axes[1],
        shrink=0.75,
        label="Relative LOS displacement (cm); + toward, - away from sensor",
    )
    axes[1].set_title(f"Phase-derived LOS; coherence >= {threshold:.2f}")

    axes[2].imshow(
        np.ma.masked_where(~valid_mask, np.ones_like(coherence)),
        extent=extent,
        origin="upper",
        cmap="Greys",
        vmin=0,
        vmax=1,
    )
    axes[2].set_title("Usable coverage mask")

    target_colors = {"131": "#00a6a6", "133": "#d946ef"}
    for ward in wards:
        if ward["ward_id"] not in target_colors:
            continue
        geom = ward["geometry"]
        geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        color = target_colors.get(ward["ward_id"])
        for polygon in geoms:
            for ax, base_color in zip(axes, ("white", "#222222", "#777777"), strict=True):
                bx, by = polygon.exterior.xy
                ax.plot(
                    bx,
                    by,
                    color=color or base_color,
                    linewidth=1.35 if color else 0.25,
                    alpha=0.95 if color else 0.45,
                    zorder=4 if color else 2,
                )
    for ax in axes:
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("UTM easting (m)")
        ax.set_ylabel("UTM northing (m)")
    fig.legend(
        handles=[
            Line2D([0], [0], color=target_colors["131"], lw=2, label="BIJWASAN (131)"),
            Line2D([0], [0], color=target_colors["133"], lw=2, label="MAHIPALPUR (133)"),
        ],
        loc="lower center",
        ncol=2,
        frameon=False,
    )
    fig.suptitle(
        f"ASF HyP3 single-pair QA: {reference_date} to {secondary_date}\n"
        "Relative LOS displacement; + toward / - away from sensor; not a validated risk layer",
        y=0.97,
    )
    fig.savefig(output_dir / "qa_overview.png", dpi=150)
    plt.close(fig)

    ranked = _ward_chart_rows(wards)
    fig, ax = plt.subplots(figsize=(11, 8))
    names = [f"{row['ward_id']} {row['ward_name']}" for row in ranked]
    coverage = [row["usable_pixel_intersection_area_pct_of_full_ward"] for row in ranked]
    colors = [target_colors.get(row["ward_id"], "#577590") for row in ranked]
    bars = ax.barh(names, coverage, color=colors)
    ax.invert_yaxis()
    ax.set_xlim(0, 105)
    ax.set_xlabel(f"Usable pixel intersection area (% of ward), coherence >= {threshold:.2f}")
    ax.set_title("Top 15 wards by usable coverage, plus BIJWASAN and MAHIPALPUR")
    ax.grid(axis="x", alpha=0.2)
    for bar, value in zip(bars, coverage, strict=True):
        ax.text(value + 0.7, bar.get_y() + bar.get_height() / 2, f"{value:.1f}%", va="center")
    ax.legend(
        handles=[
            Line2D([0], [0], color="#577590", lw=7, label="Other selected wards"),
            Line2D([0], [0], color=target_colors["131"], lw=7, label="BIJWASAN (131)"),
            Line2D([0], [0], color=target_colors["133"], lw=7, label="MAHIPALPUR (133)"),
        ],
        loc="lower right",
    )
    usable_wards = sum(row["usable_pixel_intersection_area_km2"] > 0 for row in wards)
    fig.text(
        0.5,
        0.025,
        f"Total wards: {len(wards)} | With usable observations: {usable_wards} | "
        f"Without usable observations: {len(wards) - usable_wards}",
        ha="center",
    )
    fig.subplots_adjust(left=0.31, right=0.97, bottom=0.12, top=0.91)
    fig.savefig(output_dir / "ward_coverage.png", dpi=150)
    plt.close(fig)


def _write_overlay(
    output_dir: Path, profile, los_cm, valid_mask, threshold: float
) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    src_crs = profile["crs"]
    left, bottom, right, top = profile["bounds"]
    try:
        dst_transform, width, height = calculate_default_transform(
            src_crs,
            "EPSG:4326",
            profile["width"],
            profile["height"],
            left,
            bottom,
            right,
            top,
        )
    except Exception as exc:
        raise ProductQAError("cannot reproject visualization overlay to EPSG:4326") from exc
    if width <= 0 or height <= 0 or max(width, height) > MAX_OVERLAY_DIMENSION:
        raise ProductQAError("reprojected overlay dimensions exceed the safe limit")
    source = np.where(valid_mask, los_cm, np.nan).astype(np.float32)
    destination = np.full((height, width), np.nan, dtype=np.float32)
    reproject(
        source=source,
        destination=destination,
        src_transform=profile["transform"],
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )
    valid = np.isfinite(destination)
    if not valid.any():
        raise ProductQAError("reprojected overlay contains no valid coherent pixels")
    limit = max(float(np.percentile(np.abs(destination[valid]), 98)), 1e-6)
    below_display = valid & (destination < -limit)
    above_display = valid & (destination > limit)
    normalized = np.clip((destination + limit) / (2 * limit), 0, 1)
    rgba = (plt.get_cmap("coolwarm")(normalized) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 210, 0).astype(np.uint8)
    plt.imsave(output_dir / "los_overlay.png", rgba)
    west, south, east, north = array_bounds(height, width, dst_transform)
    bounds = [float(west), float(south), float(east), float(north)]
    return {
        "file": "los_overlay.png",
        "crs": "EPSG:4326",
        "bbox_west_south_east_north": bounds,
        "maplibre_corners_lon_lat": [
            [bounds[0], bounds[3]],
            [bounds[2], bounds[3]],
            [bounds[2], bounds[1]],
            [bounds[0], bounds[1]],
        ],
        "width": int(width),
        "height": int(height),
        "transparent_pixels": int((~valid).sum()),
        "valid_pixels": int(valid.sum()),
        "coherence_threshold": threshold,
        "color_scale_los_cm": [-limit, limit],
        "measured_los_range_cm": [float(destination[valid].min()), float(destination[valid].max())],
        "display_saturation": {
            "lower_limit_cm": -limit,
            "upper_limit_cm": limit,
            "pixels_below_lower_limit": int(below_display.sum()),
            "pixels_above_upper_limit": int(above_display.sum()),
            "color_behavior": "values outside display limits use saturated endpoint colors; source masked GeoTIFF values are not clipped",
        },
        "frontend_legend_recommendation": (
            "Use a symmetric diverging legend in cm with negative values away from sensor, "
            "0 at the midpoint, positive values toward sensor, and endpoint labels <= lower "
            "limit / >= upper limit to communicate saturated colors."
        ),
        "resampling": "nearest",
        "limitations": [
            "Alpha 0 indicates nodata, zero coherence, coherence below threshold, or no connected component.",
            "Color is phase-derived relative LOS displacement, not vertical motion; colors saturate outside the display range while raster values remain unchanged.",
            "No water mask was applied during unwrapping; this overlay is for a limited demonstration only.",
        ],
    }


def analyze_product(
    *,
    product_dir: str | Path,
    wards_path: str | Path,
    c2_path: str | Path,
    output_dir: str | Path,
    archive_path: str | Path | None = None,
    coherence_threshold: float = DEFAULT_COHERENCE_THRESHOLD,
) -> dict[str, Any]:
    """Analyze a local HyP3 burst product and write QA figures/overlay artifacts."""
    import rasterio
    from rasterio.features import geometry_mask
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union

    if (
        isinstance(coherence_threshold, bool)
        or not isinstance(coherence_threshold, int | float)
        or not math.isfinite(coherence_threshold)
        or not 0 < coherence_threshold <= 1
    ):
        raise ProductQAError("coherence threshold must be in (0, 1]")
    product = Path(product_dir)
    output = Path(output_dir)
    archive = Path(archive_path) if archive_path is not None else None
    if not product.is_dir():
        raise ProductQAError("product directory does not exist")
    if archive is not None and not archive.is_file():
        raise ProductQAError("source archive does not exist")
    if output.exists() and any(output.iterdir()):
        raise ProductQAError("refusing to overwrite a non-empty QA output directory")
    output.mkdir(parents=True, exist_ok=True)

    parameter_file = product / f"{product.name}.txt"
    if not parameter_file.is_file():
        raise ProductQAError("product parameter metadata file is missing")
    readme_file = _one_file(product, "*_README.md.txt")
    parameters = _parse_parameter_text(parameter_file)
    corr_path = _one_file(product, "*_corr.tif")
    phase_path = _one_file(product, "*_unw_phase.tif")
    component_path = _one_file(product, "*_conncomp.tif")
    with (
        rasterio.open(corr_path) as corr_ds,
        rasterio.open(phase_path) as phase_ds,
        rasterio.open(component_path) as comp_ds,
    ):
        if any(
            (ds.width, ds.height, ds.transform, ds.crs)
            != (corr_ds.width, corr_ds.height, corr_ds.transform, corr_ds.crs)
            for ds in (phase_ds, comp_ds)
        ):
            raise ProductQAError("coherence, phase, and component rasters must share a grid")
        if corr_ds.count != 1 or phase_ds.count != 1 or comp_ds.count != 1:
            raise ProductQAError("QA rasters must each contain exactly one band")
        coherence = corr_ds.read(1).astype(np.float32)
        phase = phase_ds.read(1).astype(np.float32)
        components = comp_ds.read(1).astype(np.float32)
        profile = {
            "width": corr_ds.width,
            "height": corr_ds.height,
            "transform": corr_ds.transform,
            "crs": corr_ds.crs,
            "bounds": tuple(corr_ds.bounds),
            "resolution": tuple(corr_ds.res),
            "nodata_coherence": corr_ds.nodata,
            "nodata_phase": phase_ds.nodata,
            "nodata_components": comp_ds.nodata,
            "dtype_coherence": corr_ds.dtypes[0],
            "dtype_phase": phase_ds.dtypes[0],
            "dtype_components": comp_ds.dtypes[0],
        }
    if profile["crs"] is None or not profile["crs"].is_projected:
        raise ProductQAError("geocoded QA rasters must have a projected CRS")
    unit_factor = profile["crs"].linear_units_factor
    if not math.isclose(float(unit_factor[1]), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ProductQAError("coverage area requires a projected CRS measured in metres")

    finite_coh = np.isfinite(coherence)
    finite_phase = np.isfinite(phase)
    finite_comp = np.isfinite(components)
    coherence_valid = finite_coh & (coherence > 0) & (coherence <= 1)
    phase_valid = finite_phase
    if profile["nodata_phase"] is not None:
        phase_valid &= phase != profile["nodata_phase"]
    phase_base = coherence_valid & phase_valid & finite_comp & (components > 0)
    if not phase_base.any():
        raise ProductQAError("product has no pixels with coherence and connected-component support")
    component_labels, component_counts = np.unique(components[components > 0], return_counts=True)
    thresholds: dict[str, Any] = {}
    # ASF's unwrapped-phase sign is opposite to its LOS-displacement convention.
    # Convert phase to LOS displacement (toward is positive) using the minus sign.
    phase_cm = -phase * (LOS_CM_PER_2PI / (2 * math.pi))
    for level in sorted({*SENSITIVITY_THRESHOLDS, float(coherence_threshold)}):
        valid = phase_base & (coherence >= level)
        values = phase_cm[valid]
        thresholds[f"{level:.2f}"] = {
            "usable_pixels": int(valid.sum()),
            "share_of_raster_grid_pct": float(valid.mean() * 100),
            "relative_los_displacement_cm": _stats(values),
        }
    valid_mask = phase_base & (coherence >= coherence_threshold)
    coherence_stats = _stats(coherence[coherence_valid])

    wards, c2 = _geometry_inputs(Path(wards_path), Path(c2_path), profile["crs"])
    union = unary_union([ward["geometry"] for ward in wards])
    footprint = box(*profile["bounds"])
    overlap_area = union.intersection(footprint).area
    delhi_area = union.area
    inside_delhi = geometry_mask(
        [mapping(union)],
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        invert=True,
        all_touched=False,
    )
    delhi_inside_pixels = int(inside_delhi.sum())
    ward_rows = []
    coverage_roundoff_overruns: list[float] = []
    from rasterio.transform import Affine

    for ward in wards:
        geom = ward["geometry"]
        row0, row1, col0, col1 = _geometry_raster_window(
            geom, (profile["height"], profile["width"]), profile["transform"]
        )
        window_shape = (max(0, row1 - row0), max(0, col1 - col0))
        if not all(window_shape):
            inside = np.zeros(window_shape, dtype=bool)
        else:
            inside = geometry_mask(
                [mapping(geom)],
                out_shape=window_shape,
                transform=profile["transform"] * Affine.translation(col0, row0),
                invert=True,
                all_touched=False,
            )
        inside_count = int(inside.sum())
        overlap = geom.intersection(footprint).area
        pixel_rows, pixel_cols, pixel_areas = _geometry_pixel_intersection_areas(
            geom, (profile["height"], profile["width"]), profile["transform"]
        )
        threshold_counts = {
            f"{level:.2f}": int(
                (
                    inside
                    & phase_base[row0:row1, col0:col1]
                    & (coherence[row0:row1, col0:col1] >= level)
                ).sum()
            )
            for level in sorted({*SENSITIVITY_THRESHOLDS, float(coherence_threshold)})
        }
        intersection_area_by_threshold = {}
        intersection_pct_by_threshold = {}
        for level in sorted({*SENSITIVITY_THRESHOLDS, float(coherence_threshold)}):
            key = f"{level:.2f}"
            eligible = phase_base[pixel_rows, pixel_cols] & (
                coherence[pixel_rows, pixel_cols] >= level
            )
            usable_area = math.fsum(pixel_areas[eligible].tolist())
            if usable_area > geom.area:
                coverage_roundoff_overruns.append(usable_area - geom.area)
            intersection_area_by_threshold[key] = float(usable_area / 1e6)
            intersection_pct_by_threshold[key] = _coverage_percent(usable_area, geom.area)
        selected_key = f"{coherence_threshold:.2f}"
        selected_usable_area = intersection_area_by_threshold[selected_key]
        denominator = geom.area
        row = {
            "ward_id": ward["ward_id"],
            "ward_name": ward["ward_name"],
            "c2_status": ward["c2_status"],
            "c2_rank": ward["c2_rank"],
            "area_km2": float(denominator / 1e6),
            "nominal_footprint_overlap_km2": float(overlap / 1e6),
            "nominal_footprint_overlap_pct": float(overlap / denominator * 100)
            if denominator
            else 0.0,
            "pixel_centers_in_raster": inside_count,
            "usable_pixels_by_coherence_threshold": threshold_counts,
            "usable_pixel_intersection_area_km2_by_coherence_threshold": intersection_area_by_threshold,
            "usable_pixel_intersection_area_pct_of_full_ward_by_coherence_threshold": intersection_pct_by_threshold,
            "usable_pixel_intersection_area_km2": selected_usable_area,
            "usable_pixel_intersection_area_pct_of_full_ward": intersection_pct_by_threshold[
                selected_key
            ],
            "usable_pct_of_rasterized_ward_centers": float(
                threshold_counts[selected_key] / inside_count * 100
            )
            if inside_count
            else 0.0,
        }
        ward_rows.append(row)

    whole_delhi_thresholds = {
        f"{level:.2f}": int((inside_delhi & phase_base & (coherence >= level)).sum())
        for level in sorted({*SENSITIVITY_THRESHOLDS, float(coherence_threshold)})
    }
    union_rows, union_cols, union_pixel_areas = _geometry_pixel_intersection_areas(
        union, (profile["height"], profile["width"]), profile["transform"]
    )
    union_area_by_threshold = {}
    union_pct_by_threshold = {}
    for level in sorted({*SENSITIVITY_THRESHOLDS, float(coherence_threshold)}):
        key = f"{level:.2f}"
        eligible = phase_base[union_rows, union_cols] & (coherence[union_rows, union_cols] >= level)
        usable_area = math.fsum(union_pixel_areas[eligible].tolist())
        if usable_area > delhi_area:
            coverage_roundoff_overruns.append(usable_area - delhi_area)
        union_area_by_threshold[key] = float(usable_area / 1e6)
        union_pct_by_threshold[key] = _coverage_percent(usable_area, delhi_area)
    targets = {}
    for target_name in ("BIJWASAN", "MAHIPALPUR"):
        match = next((row for row in ward_rows if row["ward_name"].upper() == target_name), None)
        if match is not None:
            targets[match["ward_id"]] = match

    metadata_text = readme_file.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"plugin version\s+([^\s]+).*?ISCE release\s+([^\s]+)", metadata_text, re.DOTALL
    )
    reference = parameters.get("Reference Granule", "")
    secondary = parameters.get("Secondary Granule", "")
    reference_date = _acquisition_date(reference)
    secondary_date = _acquisition_date(secondary)
    if not reference_date or not secondary_date:
        raise ProductQAError("acquisition dates are not parseable from parameter granule metadata")
    product_id = product.name
    archive_info = None
    if archive is not None:
        archive_info = {
            "filename": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": _sha256(archive),
        }

    output_profile = {
        "driver": "GTiff",
        "height": profile["height"],
        "width": profile["width"],
        "count": 1,
        "dtype": "float32",
        "crs": profile["crs"],
        "transform": profile["transform"],
        "nodata": float("nan"),
        "compress": "deflate",
        "predictor": 3,
    }
    masked_los = np.where(valid_mask, phase_cm, np.nan).astype(np.float32)
    with rasterio.open(output / "los_relative_cm_masked.tif", "w", **output_profile) as out_ds:
        out_ds.write(masked_los, 1)
        out_ds.update_tags(
            units="cm relative LOS displacement",
            sign_convention="positive toward sensor; negative away from sensor",
            derived_from="negative unwrapped phase * 2.8 cm / (2*pi); ASF LOS sign convention",
            coherence_threshold=str(coherence_threshold),
            fresh_data_status="processed_not_validated",
            vertical_motion="not estimated",
        )

    overlay = _write_overlay(output, profile, phase_cm, valid_mask, coherence_threshold)
    overlay["sha256"] = _sha256(output / overlay["file"])
    ward_figure_rows = [
        {**ward, **next(row for row in ward_rows if row["ward_id"] == ward["ward_id"])}
        for ward in wards
    ]
    _render_figures(
        output,
        profile,
        coherence,
        phase_cm,
        components,
        valid_mask,
        ward_figure_rows,
        coherence_threshold,
        reference_date,
        secondary_date,
    )
    product_metadata = {
        "product_id": product_id,
        "reference_granule": reference,
        "secondary_granule": secondary,
        "reference_acquisition_date": reference_date,
        "secondary_acquisition_date": secondary_date,
        "reference_pass_direction": parameters.get("Reference Pass Direction"),
        "secondary_pass_direction": parameters.get("Secondary Pass Direction"),
        "reference_orbit_number": parameters.get("Reference Orbit Number"),
        "secondary_orbit_number": parameters.get("Secondary Orbit Number"),
        "polarization": "VV" if "_VV_" in product_id else None,
        "range_looks": parameters.get("Range looks"),
        "azimuth_looks": parameters.get("Azimuth looks"),
        "multilook_range_pixel_size_m": parameters.get("Multilook range pixel size"),
        "baseline_parameter_value": parameters.get("Baseline"),
        "baseline_definition_or_unit": None,
        "water_mask_applied": parameters.get("Water mask") == "yes",
        "processing_software": {
            "hyp3_isce2_plugin": match.group(1).rstrip(".,") if match else None,
            "isce_release": match.group(2).rstrip(".,") if match else None,
        },
        "processing_time_utc": re.search(r"Processing Date/Time:\s*(.+)", metadata_text)
        .group(1)
        .strip()
        if re.search(r"Processing Date/Time:\s*(.+)", metadata_text)
        else None,
        "source_dem": parameters.get("DEM source"),
        "reference_orbit_relative": None,
        "perpendicular_baseline_m": None,
        "crs": profile["crs"].to_string(),
        "raster": {
            "width": profile["width"],
            "height": profile["height"],
            "pixel_spacing_m": list(profile["resolution"]),
            "bounds_native_crs": list(profile["bounds"]),
            "phase_nodata_tag": profile["nodata_phase"],
            "coherence_nodata_tag": profile["nodata_coherence"],
            "connected_components_dtype": profile["dtype_components"],
            "connected_components_nodata_tag": profile["nodata_components"],
            "unwrapped_phase_units_tag": None,
        },
    }
    thresholds_dict = {
        "exploratory_thresholds": thresholds,
        "selected_threshold": coherence_threshold,
        "selected_threshold_is_universal_standard": False,
        "valid_pixel_definition": "finite phase and coherence in (0,1], coherence >= selected threshold, finite connected-component label > 0; no water mask",
    }
    summary = {
        "schema": "E7_PRODUCT_QA@1.0",
        "created_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "processing_status": "processed",
        "fresh_data_check": "not_run",
        "api_fresh_data_status": "processed_not_validated",
        "product": product_metadata,
        "source_archive": archive_info,
        "raster_quality": {
            "grid_pixels": int(coherence.size),
            "coherence_zero_nodata_or_noncoherent_pixels": int((~coherence_valid).sum()),
            "coherence_stats_nonzero_finite": coherence_stats,
            "phase_nonfinite_pixels": int((~finite_phase).sum()),
            "phase_nodata_tag_pixels": int(
                (finite_phase & (phase == profile["nodata_phase"])).sum()
            )
            if profile["nodata_phase"] is not None
            else 0,
            "phase_zero_values_retained_when_component_and_coherence_valid": int(
                np.count_nonzero(phase_base & (phase == 0))
            ),
            "connected_component_zero_pixels": int(np.count_nonzero(components == 0)),
            "positive_component_count": len(component_labels),
            "largest_component_pixels": int(component_counts.max()) if len(component_counts) else 0,
            "largest_component_share_pct": float(
                component_counts.max() / component_counts.sum() * 100
            )
            if len(component_counts)
            else 0.0,
            "relative_los_displacement_conversion": "-unwrapped_phase * 2.8 cm / (2*pi); ASF HyP3 LOS displacement sign convention; relative LOS only",
        },
        "thresholds": thresholds_dict,
        "geographic_coverage": {
            "ward_source": Path(wards_path).name,
            "ward_source_vintage": 2022,
            "ward_count": len(ward_rows),
            "c2_contract": c2.get("contract"),
            "c2_data_vintage": c2.get("meta", {}).get("data_vintage"),
            "delhi_ward_union_area_km2": float(delhi_area / 1e6),
            "nominal_footprint_overlap_area_km2": float(overlap_area / 1e6),
            "nominal_footprint_overlap_pct_of_ward_union": float(overlap_area / delhi_area * 100)
            if delhi_area
            else 0.0,
            "pixel_centers_inside_delhi_and_product": delhi_inside_pixels,
            "usable_pixels_inside_delhi_by_threshold": whole_delhi_thresholds,
            "usable_pixel_intersection_area_km2_of_ward_union_by_coherence_threshold": union_area_by_threshold,
            "usable_pixel_intersection_area_pct_of_ward_union_by_coherence_threshold": union_pct_by_threshold,
            "usable_pixel_intersection_area_km2_of_ward_union_at_selected_threshold": union_area_by_threshold[
                f"{coherence_threshold:.2f}"
            ],
            "usable_pixel_intersection_area_pct_of_ward_union_at_selected_threshold": union_pct_by_threshold[
                f"{coherence_threshold:.2f}"
            ],
            "intersection_area_numeric_roundoff": {
                "adjusted_overrun_count": len(coverage_roundoff_overruns),
                "maximum_raw_overrun_m2": max(coverage_roundoff_overruns, default=0.0),
                "policy": "Only overrun <= 1e-12 of the polygon area is treated as floating-point overlay roundoff and bounded to the known polygon area; larger overrun fails analysis.",
            },
            "targets": targets,
            "wards": ward_rows,
        },
        "overlay": overlay,
        "scientific_limitations": [
            "Single ascending 12-day interferogram measures relative line-of-sight motion, not vertical subsidence.",
            "No annualization, historical velocity comparison, risk-score modification, or independent ground-truth validation was performed.",
            "Phase reference is internal to processing and not independently relocated to a verified stable site.",
            "No atmospheric correction was applied; the water mask was disabled during unwrapping.",
            "Coherence threshold is exploratory and threshold sensitivity is reported; it is not a universal quality standard.",
            "Perpendicular baseline is not named or unit-qualified in the supplied parameter file; the printed Baseline value is preserved without interpretation.",
            "Product metadata does not report the relative orbit; no value is inferred from the filename or external catalog.",
            "No dedicated LOS-displacement or vertical-displacement raster was supplied; LOS centimeters are derived from unwrapped phase using the documented 2pi conversion.",
        ],
        "attribution": "ASF DAAC HyP3 2026 using hyp3_isce2 3.0.2 / ISCE 2.6.5. Contains modified Copernicus Sentinel data 2026, processed by ESA.",
        "distribution": "Internal prototype artifact; verify source terms before redistribution or public hosting.",
    }
    selected_ward_coverage = {
        row["ward_name"].upper(): {
            "ward_id": row["ward_id"],
            "usable_pixel_intersection_area_pct": row[
                "usable_pixel_intersection_area_pct_of_full_ward"
            ],
        }
        for row in ward_rows
        if row["ward_name"].upper() in {"BIJWASAN", "MAHIPALPUR"}
    }
    overlay.update(
        {
            "product_id": product_id,
            "reference_acquisition_date": reference_date,
            "secondary_acquisition_date": secondary_date,
            "temporal_separation_days": (
                datetime.fromisoformat(secondary_date) - datetime.fromisoformat(reference_date)
            ).days,
            "polarization": product_metadata["polarization"],
            "flight_direction": product_metadata["reference_pass_direction"],
            "units": "cm relative line-of-sight displacement derived from unwrapped phase",
            "sign_convention": "positive toward sensor; negative away from sensor",
            "coherence_threshold": coherence_threshold,
            "nominal_footprint_overlap_pct_of_ward_union": summary["geographic_coverage"][
                "nominal_footprint_overlap_pct_of_ward_union"
            ],
            "usable_pixel_intersection_area_pct_of_ward_union": summary["geographic_coverage"][
                "usable_pixel_intersection_area_pct_of_ward_union_at_selected_threshold"
            ],
            "target_ward_coverage": {
                name: row["usable_pixel_intersection_area_pct"]
                for name, row in selected_ward_coverage.items()
            },
            "attribution": summary["attribution"],
            "source_archive": archive_info,
            "limitations": summary["scientific_limitations"],
        }
    )
    (output / "overlay_manifest.json").write_text(
        json.dumps(overlay, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporal_days = (
        datetime.fromisoformat(secondary_date) - datetime.fromisoformat(reference_date)
    ).days
    status_note = (
        f"A single ASF HyP3 VV pair was processed for {reference_date} to {secondary_date}. "
        "Footprint and coherence coverage were measured; no historical pattern/sign "
        "comparison or independent validation was performed. This is relative LOS "
        "phase-derived motion, not vertical subsidence or an updated risk score."
    )
    api_status = {
        "schema": "E7_PRODUCT_STATUS@1.0",
        "processing_status": "processed",
        "fresh_data_check_status": "not_run",
        "api_status": "processed_not_validated",
        "product_id": product_id,
        "reference_acquisition_date": reference_date,
        "secondary_acquisition_date": secondary_date,
        "temporal_separation_days": temporal_days,
        "polarization": product_metadata["polarization"],
        "flight_direction": product_metadata["reference_pass_direction"],
        "coherence_threshold": coherence_threshold,
        "usable_pixel_intersection_area_pct_of_ward_union": summary["geographic_coverage"][
            "usable_pixel_intersection_area_pct_of_ward_union_at_selected_threshold"
        ],
        "target_ward_coverage": selected_ward_coverage,
        "note": status_note,
    }
    (output / "api_fresh_data_status.json").write_text(
        json.dumps(api_status, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    summary_path = output / "qa_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    handoff = _handoff_markdown(summary)
    (output / "PERSON_C_HANDOFF.md").write_text(handoff, encoding="utf-8")
    checksum_paths = sorted(
        p for p in output.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_paths), encoding="utf-8"
    )
    return summary


def _handoff_markdown(summary: dict[str, Any]) -> str:
    coverage = summary["geographic_coverage"]
    targets = coverage["targets"]
    threshold = summary["thresholds"]["selected_threshold"]
    threshold_key = f"{threshold:.2f}"
    target_lines = []
    for ward_id, row in targets.items():
        target_lines.append(
            f"- {row['ward_name']} (ward {ward_id}): "
            f"{row['usable_pixel_intersection_area_pct_of_full_ward']:.1f}% pixel-intersection area coverage "
            f"at coherence >= {threshold:.2f}; "
            f"{row['usable_pixels_by_coherence_threshold'][threshold_key]} usable pixels."
        )
    corners = summary["overlay"]["maplibre_corners_lon_lat"]
    return (
        "# Person C — Fresh InSAR overlay handoff\n\n"
        f"Product `{summary['product']['product_id']}`: {summary['product']['reference_acquisition_date']} "
        f"to {summary['product']['secondary_acquisition_date']}, {summary['product']['polarization']}, "
        f"80 m product spacing, ascending pass. This is one relative LOS interferogram, not vertical motion.\n\n"
        "## Local files\n\n"
        "- `los_overlay.png`: transparent RGBA image, EPSG:4326 map placement.\n"
        "- `overlay_manifest.json`: coordinates, units, threshold, scale and MapLibre corner order.\n"
        "- `los_relative_cm_masked.tif`: thresholded relative LOS derivative in the source UTM CRS.\n"
        "- `qa_overview.png` and `ward_coverage.png`: QA figures.\n"
        "- `qa_summary.json`: raster statistics and ward coverage.\n"
        "- `api_fresh_data_status.json`: compact optional C3 status adapter input.\n\n"
        "## MapLibre placement\n\n"
        "Use an image source with `los_overlay.png` and the four `maplibre_corners_lon_lat` "
        "coordinates in `overlay_manifest.json`, ordered top-left, top-right, bottom-right, bottom-left. "
        "Use the manifest's symmetric relative-LOS color scale and coherence threshold. The scale uses "
        "the 98th percentile; values beyond the limits saturate to endpoint colors, while the masked "
        "GeoTIFF retains the un-clipped derived values. Recommended legend: relative LOS displacement "
        "(cm), negative away from sensor, zero midpoint, positive toward sensor, with <=/>= endpoint "
        "labels. Do not blend this "
        "layer into C2 scores or describe it as collapse probability.\n\n"
        "```json\n" + json.dumps(corners, indent=2) + "\n```\n\n"
        "## Coverage summary\n\n"
        f"Nominal footprint overlap is {coverage['nominal_footprint_overlap_pct_of_ward_union']:.1f}% of the "
        f"2022 Delhi ward-union area; selected-threshold usable pixel intersection area is "
        f"{coverage['usable_pixel_intersection_area_pct_of_ward_union_at_selected_threshold']:.1f}% of the ward union.\n\n"
        + "\n".join(target_lines)
        + "\n\n## Interpretation and access\n\n"
        "Positive relative LOS values are toward the sensor; negative values are away, matching the ASF LOS-displacement sign convention (opposite to unwrapped-phase sign). "
        "The image is masked below the selected coherence threshold and where connected-component support "
        "is absent. No water mask or atmospheric correction was applied, phase unwrapping may contain errors, "
        "and no independent validation was performed. When `API_INSAR_MANIFEST_PATH` is explicitly set to "
        "`api_fresh_data_status.json`, the existing C3 endpoint reports `processed_not_validated`; it does "
        "not serve this PNG. Do not annualize the 12-day result or compare it directly with historical "
        "vertical rates. Keep these ignored local artifacts internal until licensing and redistribution terms "
        "are confirmed. Attribution: "
        f"{summary['attribution']} The frozen "
        "C4 API does not serve this PNG, so distribute the overlay through the project's authorized internal "
        "artifact handoff.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline QA and overlay export for an ASF HyP3 burst product"
    )
    parser.add_argument("--product-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--wards", type=Path, required=True)
    parser.add_argument("--c2-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--coherence-threshold", type=float, default=DEFAULT_COHERENCE_THRESHOLD)
    args = parser.parse_args(argv)
    try:
        analyze_product(
            product_dir=args.product_dir,
            archive_path=args.archive,
            wards_path=args.wards,
            c2_path=args.c2_summary,
            output_dir=args.output_dir,
            coherence_threshold=args.coherence_threshold,
        )
    except (ProductQAError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
