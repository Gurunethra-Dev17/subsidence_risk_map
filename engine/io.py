"""C6 configuration and C0 vertical land motion point loading."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any
import warnings

import yaml
from jsonschema import Draft202012Validator


class InputError(ValueError):
    """Raised when project configuration or source points violate their contract."""


@dataclass(frozen=True)
class Config:
    """Parsed C6 city configuration with paths resolved from the repository root."""

    contract: str
    city: str
    display_name: str
    utm_epsg: int
    bbox: tuple[float, float, float, float]
    seed: int
    paths: dict[str, Path]
    params: dict[str, Any]
    weights: dict[str, float]
    mode: str

    @property
    def pack_dir(self) -> Path:
        return self.paths["pack_dir"]

    @property
    def out_dir(self) -> Path:
        return self.paths["out_dir"]


@dataclass(frozen=True)
class PointLoadStats:
    """Compact audit statistics attached to a loaded GeoDataFrame."""

    rows_read: int
    rows_in_bbox: int
    rows_clipped: int
    n_sinking: int
    n_rising: int
    vlm_min_mm_yr: float | None
    vlm_max_mm_yr: float | None
    bbox_area_km2: float
    points_per_km2: float
    source_unit: str
    utm_epsg: int


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "contracts" / "schemas" / "config.schema.json"


def _repo_root(config_path: Path) -> Path:
    # The shared C6 files live in configs/. For custom config locations, paths
    # are relative to the config's parent directory.
    return config_path.parent.parent if config_path.parent.name == "configs" else config_path.parent


def _normalize_vlm_values(values, source_column: str):
    """Convert supported source columns into finite mm/yr values."""
    try:
        import numpy as np
        numeric = np.asarray(values, dtype=float)
    except (ImportError, TypeError, ValueError) as exc:
        raise InputError("VLM coordinates and rates must be numeric") from exc
    if source_column == "vlm_mm_yr":
        source_unit, multiplier = "mm/yr", 1.0
    elif source_column in {"vlm_cm_yr", "vlm"}:
        source_unit, multiplier = "cm/yr", 10.0
    else:
        raise InputError(f"Unsupported VLM rate column {source_column!r}")
    normalized = numeric * multiplier
    if not np.isfinite(normalized).all():
        raise InputError("VLM rates must be finite numbers")
    return normalized, source_unit


def _bbox_mask(lon, lat, bbox):
    """Return the inclusive lon/lat bounding-box mask for point coordinates."""
    import numpy as np

    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        np.isfinite(lon) & np.isfinite(lat)
        & (lon >= min_lon) & (lon <= max_lon)
        & (lat >= min_lat) & (lat <= max_lat)
    )


def load_config(path: str) -> Config:
    """Load and validate a C6 YAML file; resolve configured paths consistently."""
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"Cannot read config file {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise InputError(f"Invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise InputError("C6 config must be a YAML mapping")

    try:
        schema = yaml.safe_load(_schema_path().read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"Cannot read C6 schema: {exc}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        message = "; ".join(f"{'.'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        raise InputError(f"C6 config is invalid: {message}")

    required_params = {
        "radius_m", "min_points", "pair_min_m", "pair_max_m", "footprint_buffer_m",
        "horizon_years", "class_edges_ratio", "sinking_threshold_mm_yr", "coverage_min",
        "grid_m", "cell_min_buildings", "sens_draws", "sens_concentration", "radius_variants_m",
    }
    missing = sorted(required_params - raw["params"].keys())
    if missing:
        raise InputError(f"C6 params missing required values: {', '.join(missing)}")
    min_lon, min_lat, max_lon, max_lat = map(float, raw["bbox"])
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise InputError("C6 bbox must be [min_lon, min_lat, max_lon, max_lat] in EPSG:4326")
    if raw["weights"] and not math.isclose(sum(raw["weights"].values()), 1.0, abs_tol=1e-6):
        raise InputError("C6 weights must sum to 1.0")

    root = _repo_root(config_path)
    paths = {
        name: (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        for name, value in raw["paths"].items()
    }
    return Config(
        contract=raw["contract"], city=raw["city"], display_name=raw["display_name"],
        utm_epsg=int(raw["utm_epsg"]), bbox=(min_lon, min_lat, max_lon, max_lat),
        seed=int(raw["seed"]), paths=paths, params=dict(raw["params"]),
        weights={key: float(value) for key, value in raw["weights"].items()}, mode=raw["mode"],
    )


def _read_points(path: Path):
    """Read C0 Parquet or lightweight CSV/JSON development fixtures."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depends on optional geo extra
        raise InputError("Point loading requires the 'geo' dependencies; install with pip install -e '.[geo]'") from exc
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise InputError(f"Unsupported point file format {suffix!r}; expected .parquet, .csv, or .json")


def load_vlm_points(cfg: Config, path: str | None = None):
    """Load, normalize and bbox-clip C0 VLM points.

    Output columns include ``pt_id``, ``vlm_mm_yr``, ``source`` and point
    geometry in EPSG:4326. Source ``vlm_cm_yr`` or generic ``vlm`` values are
    interpreted as cm/yr; the contract column ``vlm_mm_yr`` is retained as
    mm/yr. No sign inversion is applied: negative values mean sinking.
    Density statistics are available as ``result.attrs['load_stats']``.
    """
    source_path = Path(path).expanduser().resolve() if path else cfg.pack_dir / "vlm_points.parquet"
    if not source_path.exists() and path is None:
        # The committed H0 mock deliberately uses a readable CSV stand-in.
        csv_fixture = cfg.pack_dir / "vlm_points.csv"
        if csv_fixture.exists():
            source_path = csv_fixture
    if not source_path.is_file():
        raise InputError(f"VLM points file does not exist: {source_path}")

    frame = _read_points(source_path)
    if "vlm_mm_yr" in frame.columns:
        value_col = "vlm_mm_yr"
    elif "vlm_cm_yr" in frame.columns:
        value_col = "vlm_cm_yr"
    elif "vlm" in frame.columns:
        value_col = "vlm"
    else:
        raise InputError("VLM points need vlm_mm_yr, vlm_cm_yr, or vlm values")
    for column in ("lon", "lat"):
        if column not in frame.columns:
            raise InputError(f"VLM points are missing required {column!r} coordinate column")
    if "pt_id" not in frame.columns:
        raise InputError("VLM points are missing required 'pt_id' column")

    try:
        import numpy as np
        lon = frame["lon"].astype(float)
        lat = frame["lat"].astype(float)
        values, source_unit = _normalize_vlm_values(frame[value_col], value_col)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("VLM coordinates and rates must be numeric") from exc
    valid = lon.map(math.isfinite) & lat.map(math.isfinite) & np.isfinite(values)
    valid &= lon.between(-180, 180) & lat.between(-90, 90)
    if not valid.all():
        raise InputError(f"VLM input has {int((~valid).sum())} missing, non-finite, or invalid coordinate/rate row(s)")
    if (frame["pt_id"].isna() | frame["pt_id"].astype(str).str.strip().eq("")).any():
        raise InputError("VLM point IDs must be present and non-empty")
    if frame["pt_id"].astype(str).duplicated().any():
        raise InputError("VLM point IDs must be unique")

    min_lon, min_lat, max_lon, max_lat = cfg.bbox
    inside = _bbox_mask(lon.to_numpy(), lat.to_numpy(), cfg.bbox)
    clipped = frame.loc[inside].copy()
    clipped["lon"] = lon.loc[inside].to_numpy()
    clipped["lat"] = lat.loc[inside].to_numpy()
    clipped["pt_id"] = clipped["pt_id"].astype(str)
    clipped["vlm_mm_yr"] = values[inside]
    if "source" not in clipped.columns:
        clipped["source"] = "vt-in-v2"

    try:
        import geopandas as gpd
        from shapely.geometry import box, points_from_xy
    except ImportError as exc:  # pragma: no cover - optional geospatial dependencies
        raise InputError("GeoDataFrame output requires the 'geo' dependencies; install with pip install -e '.[geo]'") from exc
    result = gpd.GeoDataFrame(
        clipped[["pt_id", "vlm_mm_yr", "source", "lon", "lat"]].reset_index(drop=True),
        geometry=points_from_xy(clipped["lon"], clipped["lat"]), crs="EPSG:4326",
    )

    # Project for metric area/density calculations while preserving the public
    # point geometry in the C0 storage CRS (EPSG:4326).
    bbox_frame = gpd.GeoDataFrame(
        geometry=[box(min_lon, min_lat, max_lon, max_lat)], crs="EPSG:4326"
    ).to_crs(epsg=cfg.utm_epsg)
    bbox_area_km2 = float(bbox_frame.geometry.area.iloc[0] / 1_000_000)
    in_bbox_rates = clipped["vlm_mm_yr"]
    density = len(result) / bbox_area_km2 if bbox_area_km2 > 0 else 0.0
    stats = PointLoadStats(
        rows_read=len(frame), rows_in_bbox=len(result), rows_clipped=len(frame) - len(result),
        n_sinking=int((in_bbox_rates < 0).sum()), n_rising=int((in_bbox_rates > 0).sum()),
        vlm_min_mm_yr=float(in_bbox_rates.min()) if len(in_bbox_rates) else None,
        vlm_max_mm_yr=float(in_bbox_rates.max()) if len(in_bbox_rates) else None,
        bbox_area_km2=bbox_area_km2, points_per_km2=density,
        source_unit=source_unit, utm_epsg=cfg.utm_epsg,
    )
    result.attrs["load_stats"] = stats
    result.attrs["sign_convention"] = "negative = sinking; positive = rising; no sign inversion applied"
    if stats.n_rising == 0 and stats.n_sinking == 0 and stats.rows_in_bbox:
        warnings.warn("All VLM values are zero; check source units and sign convention", stacklevel=2)
    return result
