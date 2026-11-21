"""Deterministic C1 building-metrics Parquet export."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile


class ExportError(ValueError):
    """Raised when computed building metrics cannot satisfy the C1 contract."""


C1_COLUMNS = [
    "bldg_id", "ward_id", "cell_id", "n_points", "vlm_mm_yr",
    "vlm_iqr_mm_yr", "n_pairs", "beta_rate_per_yr", "beta_horizon",
    "beta_ratio_horizon", "beta_class", "sparse", "vt_risk_insar",
    "engine_version", "params_hash",
]


def params_hash(params: dict) -> str:
    """Return SHA-256 of the C6 params mapping in canonical JSON form."""
    try:
        canonical = json.dumps(
            params, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExportError("C6 params must contain only finite JSON values") from exc
    return hashlib.sha256(canonical).hexdigest()


def _validate_ids(frame, label: str):
    if "bldg_id" not in frame.columns:
        raise ExportError(f"{label} is missing required 'bldg_id' column")
    ids = frame["bldg_id"]
    if ids.isna().any() or ids.astype(str).str.strip().eq("").any():
        raise ExportError(f"{label} bldg_id values must be present and non-empty")
    normalized = ids.astype(str)
    if normalized.duplicated().any():
        raise ExportError(f"{label} bldg_id values must be unique")
    return normalized


def export_building_metrics(
    buildings,
    assignments,
    distortions,
    cfg,
    output_path: str | Path,
    *,
    engine_version: str,
) -> dict:
    """Join calculated metrics and write one deterministic C1 Parquet file.

    ``buildings`` must include C0 ``bldg_id``, ``ward_id`` and ``cell_id``;
    optional ``vt_risk_insar`` is copied through when available. Assignment
    and distortion result rows are joined strictly by ``bldg_id``. Their row
    order may differ from the C0 input without changing the output order.

    Returns a small export summary including row count and the non-null share
    of ``vlm_mm_yr``.
    """
    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional geo dependencies
        raise ExportError(
            "C1 Parquet export requires the 'geo' dependencies; "
            "install with pip install -e '.[geo]'"
        ) from exc

    if not isinstance(engine_version, str) or not engine_version.strip():
        raise ExportError("engine_version must be a non-empty string")
    for attribute in ("params", "seed"):
        if not hasattr(cfg, attribute):
            raise ExportError(f"cfg is missing required C6 {attribute}")
    if "horizon_years" not in cfg.params:
        raise ExportError("C6 params must define horizon_years")
    try:
        horizon_years = float(cfg.params["horizon_years"])
        seed = int(cfg.seed)
        config_hash = params_hash(cfg.params)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExportError("C6 horizon_years and seed must be valid numeric values") from exc
    if not math.isfinite(horizon_years) or horizon_years <= 0:
        raise ExportError("C6 horizon_years must be finite and positive")

    building_ids = _validate_ids(buildings, "buildings")
    assignment_ids = _validate_ids(assignments, "assignments")
    distortion_ids = _validate_ids(distortions, "distortions")
    required_building = {"ward_id", "cell_id"}
    missing_building = sorted(required_building - set(buildings.columns))
    if missing_building:
        raise ExportError(f"buildings are missing C0 columns: {', '.join(missing_building)}")
    missing_assignment = sorted({"n_points", "vlm_mm_yr", "vlm_iqr_mm_yr", "sparse"} - set(assignments.columns))
    if missing_assignment:
        raise ExportError(f"assignments are missing C1 fields: {', '.join(missing_assignment)}")
    missing_distortion = sorted({
        "n_pairs", "beta_rate_per_yr", "beta_horizon", "beta_ratio_horizon", "beta_class",
    } - set(distortions.columns))
    if missing_distortion:
        raise ExportError(f"distortions are missing C1 fields: {', '.join(missing_distortion)}")

    expected = set(building_ids)
    if set(assignment_ids) != expected:
        raise ExportError("assignment bldg_id values must exactly match the C0 buildings")
    if set(distortion_ids) != expected:
        raise ExportError("distortion bldg_id values must exactly match the C0 buildings")

    base = pd.DataFrame({
        "bldg_id": building_ids,
        "ward_id": buildings["ward_id"].to_numpy(),
        "cell_id": buildings["cell_id"].to_numpy(),
        "vt_risk_insar": (
            buildings["vt_risk_insar"].to_numpy()
            if "vt_risk_insar" in buildings.columns else None
        ),
    })
    assignment_fields = ["n_points", "vlm_mm_yr", "vlm_iqr_mm_yr", "sparse"]
    distortion_fields = [
        "n_pairs", "beta_rate_per_yr", "beta_horizon", "beta_ratio_horizon", "beta_class",
    ]
    assignment_frame = assignments[["bldg_id", *assignment_fields]].copy()
    assignment_frame["bldg_id"] = assignment_ids.to_numpy()
    distortion_frame = distortions[["bldg_id", *distortion_fields]].copy()
    distortion_frame["bldg_id"] = distortion_ids.to_numpy()
    result = base.merge(assignment_frame, on="bldg_id", how="left", validate="one_to_one", sort=False)
    result = result.merge(distortion_frame, on="bldg_id", how="left", validate="one_to_one", sort=False)
    result["engine_version"] = engine_version.strip()
    result["params_hash"] = config_hash
    result = result[C1_COLUMNS]

    for column in ("n_points", "n_pairs"):
        numeric = pd.to_numeric(result[column], errors="coerce")
        if numeric.isna().any() or (numeric < 0).any() or (numeric % 1 != 0).any():
            raise ExportError(f"{column} must contain non-negative integers")
        result[column] = numeric.astype("int32")
    if result["sparse"].isna().any():
        raise ExportError("sparse must be present for every building")
    if not result["sparse"].isin([True, False]).all():
        raise ExportError("sparse must contain booleans")
    result["sparse"] = result["sparse"].astype("bool")
    if (result["sparse"] != result["vlm_mm_yr"].isna()).any():
        raise ExportError("sparse must be true exactly when vlm_mm_yr is null")
    result["bldg_id"] = result["bldg_id"].astype("string")
    for column in ("ward_id", "cell_id", "beta_ratio_horizon", "beta_class"):
        result[column] = result[column].astype("string")
    for column in ("vlm_mm_yr", "vlm_iqr_mm_yr", "beta_rate_per_yr", "beta_horizon"):
        result[column] = pd.to_numeric(result[column], errors="coerce").astype("float32")
    risk = pd.to_numeric(result["vt_risk_insar"], errors="coerce")
    if ((risk.dropna() % 1) != 0).any() or ((risk.dropna() < -128) | (risk.dropna() > 127)).any():
        raise ExportError("vt_risk_insar must contain nullable int8 values")
    result["vt_risk_insar"] = risk.astype("Int8")
    result["engine_version"] = result["engine_version"].astype("string")
    result["params_hash"] = result["params_hash"].astype("string")

    schema = pa.schema([
        pa.field("bldg_id", pa.string(), nullable=False),
        pa.field("ward_id", pa.string()), pa.field("cell_id", pa.string()),
        pa.field("n_points", pa.int32(), nullable=False),
        pa.field("vlm_mm_yr", pa.float32()), pa.field("vlm_iqr_mm_yr", pa.float32()),
        pa.field("n_pairs", pa.int32(), nullable=False),
        pa.field("beta_rate_per_yr", pa.float32()), pa.field("beta_horizon", pa.float32()),
        pa.field("beta_ratio_horizon", pa.string()),
        pa.field("beta_class", pa.string()),
        pa.field("sparse", pa.bool_(), nullable=False),
        pa.field("vt_risk_insar", pa.int8()),
        pa.field("engine_version", pa.string(), nullable=False),
        pa.field("params_hash", pa.string(), nullable=False),
    ])
    table = pa.Table.from_pandas(result, schema=schema, preserve_index=False, safe=True)
    metadata = {
        b"contract": b"C1@1.0",
        b"horizon_years": format(horizon_years, ".17g").encode("ascii"),
        b"seed": str(seed).encode("ascii"),
        b"engine_version": engine_version.strip().encode("utf-8"),
        b"params_hash": config_hash.encode("ascii"),
    }
    table = table.replace_schema_metadata(metadata)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False,
        ) as temp_file:
            temp_name = temp_file.name
        pq.write_table(
            table, temp_name, compression="zstd", version="2.6",
            use_dictionary=False, write_statistics=True, row_group_size=65536,
        )
        os.replace(temp_name, destination)
    except (OSError, pa.ArrowException) as exc:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        raise ExportError(f"could not write C1 Parquet file {destination}: {exc}") from exc

    return {
        "path": destination,
        "rows": len(result),
        "non_null_vlm_share": float(result["vlm_mm_yr"].notna().mean()) if len(result) else 0.0,
        "params_hash": config_hash,
        "engine_version": engine_version.strip(),
        "horizon_years": horizon_years,
        "seed": seed,
    }
