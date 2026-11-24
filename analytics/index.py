"""D3 ward Inspection Index with configured weights and deterministic ranking."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class D3Error(ValueError):
    """Invalid D3 input or output operation."""


INDICATORS = {
    "i1": "share_sinking_gt4",
    "i2": "beta_p90_horizon",
    "i3": "n_buildings",
    "i4": "gw_stage_pct",
}
ALLOWED_FLAGS = {
    "sparse_points",
    "groundwater_missing",
    "small_ward",
    "low_coverage",
    "boundary_vintage",
}


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise D3Error(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise D3Error(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise D3Error(f"{field} must be a finite number")
    return number


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise D3Error(f"Cannot read C6 configuration: {path}") from exc
    if not isinstance(value, dict) or value.get("contract") != "C6@1.0":
        raise D3Error("Configuration must declare contract C6@1.0")
    return value


def _config_values(cfg: dict[str, Any]) -> tuple[dict[str, float], float, float]:
    if not isinstance(cfg, dict):
        raise D3Error("Configuration must be an object")
    params = cfg.get("params", {})
    weights = cfg.get("weights")
    if not isinstance(params, dict) or not isinstance(weights, dict):
        raise D3Error("Configuration must contain params and weights objects")
    required = set(INDICATORS)
    if set(weights) < required:
        raise D3Error("Configuration weights must define i1, i2, i3 and i4")
    clean_weights = {key: _finite_number(weights[key], f"weights.{key}") for key in INDICATORS}
    if any(value < 0 for value in clean_weights.values()) or sum(clean_weights.values()) <= 0:
        raise D3Error("Indicator weights must be non-negative with a positive total")
    coverage_min = _finite_number(params.get("coverage_min"), "params.coverage_min")
    if 0 < coverage_min <= 1:
        coverage_min *= 100
    if not 0 <= coverage_min <= 100:
        raise D3Error("params.coverage_min must represent a percentage from 0 to 100")
    threshold = _finite_number(
        params.get("sinking_threshold_mm_yr", -4), "params.sinking_threshold_mm_yr"
    )
    return clean_weights, coverage_min, threshold


def merge_groundwater(ward_rows: pd.DataFrame, groundwater: pd.DataFrame) -> pd.DataFrame:
    """Join D2 by ward_id, requiring an exact, unique ID set and preserving nulls."""
    required = {"ward_id", "gw_stage_pct", "gw_category"}
    missing = required - set(groundwater.columns)
    if missing:
        raise D3Error(f"Groundwater input is missing columns: {sorted(missing)}")
    wards = ward_rows.copy()
    water = groundwater[["ward_id", "gw_stage_pct", "gw_category"]].copy()
    for frame, name in ((wards, "ward indicators"), (water, "groundwater")):
        if frame["ward_id"].isna().any():
            raise D3Error(f"{name} contains null ward_id values")
        frame["ward_id"] = frame["ward_id"].astype(str).str.strip()
        if frame["ward_id"].eq("").any() or frame["ward_id"].duplicated().any():
            raise D3Error(f"{name} ward_id values must be non-empty and unique")
    ward_ids, water_ids = set(wards.ward_id), set(water.ward_id)
    if ward_ids != water_ids:
        raise D3Error(
            "D1 and D2 ward_id sets differ "
            f"({len(ward_ids - water_ids)} missing, {len(water_ids - ward_ids)} extra)"
        )
    result = wards.drop(columns=["gw_stage_pct", "gw_category"], errors="ignore")
    return result.merge(water, on="ward_id", how="left", validate="one_to_one")


def _flags(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        parsed: Any = []
    elif isinstance(value, list):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError) as exc:
                raise D3Error("Ward flags must contain a list") from exc
    else:
        raise D3Error("Ward flags must contain a list")
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise D3Error("Ward flags must contain a list of strings")
    unknown = set(parsed) - ALLOWED_FLAGS - {"i2_unavailable_provisional"}
    if unknown:
        raise D3Error(f"Unsupported ward flags: {sorted(unknown)}")
    return sorted(set(parsed) & ALLOWED_FLAGS)


def compute_index(indicators: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Compute percentile indicators and score; rank eligible wards contiguously.

    Percentiles use average ranks among eligible wards with a non-null value. Larger
    values have higher priority for all four agreed indicators. Available configured
    weights are renormalized per ward; null groundwater is never replaced by zero.
    """
    if cfg is None:
        raise D3Error("The matching C6 configuration is required")
    weights, coverage_min, _ = _config_values(cfg)
    required = {
        "ward_id",
        "ward_name",
        "n_buildings",
        "n_buildings_with_data",
        "coverage_pct",
        "status",
        *INDICATORS.values(),
    }
    missing = required - set(indicators.columns)
    if missing:
        raise D3Error(f"Ward indicators are missing columns: {sorted(missing)}")
    result = indicators.copy().reset_index(drop=True)
    if result.ward_id.isna().any():
        raise D3Error("Ward IDs must be non-null")
    result["ward_id"] = result.ward_id.astype(str).str.strip()
    if result.ward_id.eq("").any() or result.ward_id.duplicated().any():
        raise D3Error("Ward IDs must be non-empty and unique")
    if result.ward_name.isna().any() or result.ward_name.astype(str).str.strip().eq("").any():
        raise D3Error("Ward names must be non-empty")
    for column in ("n_buildings", "n_buildings_with_data"):
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or (values < 0).any() or (values % 1 != 0).any():
            raise D3Error(f"{column} must contain non-negative integers")
        result[column] = values.astype("int64")
    if (result.n_buildings_with_data > result.n_buildings).any():
        raise D3Error("n_buildings_with_data cannot exceed n_buildings")
    expected_coverage = (
        100 * result.n_buildings_with_data / result.n_buildings.where(result.n_buildings > 0, 1)
    )
    supplied_coverage = pd.to_numeric(result.coverage_pct, errors="coerce")
    if supplied_coverage.isna().any() or not supplied_coverage.between(0, 100).all():
        raise D3Error("coverage_pct must be a percentage from 0 to 100")
    if ((supplied_coverage - expected_coverage).abs() > 0.11).any():
        raise D3Error("coverage_pct does not agree with building counts")
    result["coverage_pct"] = expected_coverage
    eligible = result.n_buildings.gt(0) & expected_coverage.ge(coverage_min)
    expected_status = eligible.map({True: "ranked", False: "insufficient_data"})
    if not result.status.astype(str).eq(expected_status).all():
        raise D3Error("D1 status disagrees with configured coverage eligibility")

    numeric: dict[str, pd.Series] = {}
    for key, column in INDICATORS.items():
        values = pd.to_numeric(result[column], errors="coerce")
        finite = values.dropna().map(math.isfinite)
        if not finite.all():
            raise D3Error(f"{column} contains a non-finite value")
        numeric[key] = values
        result[f"{key}_percentile"] = float("nan")
        valid = eligible & values.notna()
        result.loc[valid, f"{key}_percentile"] = (
            values.loc[valid].rank(method="average", pct=True) * 100
        )

    available_weight = pd.Series(0.0, index=result.index)
    weighted_total = pd.Series(0.0, index=result.index)
    for key in INDICATORS:
        values = pd.to_numeric(result[f"{key}_percentile"], errors="coerce")
        valid = eligible & values.notna()
        weighted_total.loc[valid] += values.loc[valid] * weights[key]
        available_weight.loc[valid] += weights[key]
        result[f"effective_weight_{key}"] = 0.0
    can_score = eligible & available_weight.gt(0)
    result["score"] = float("nan")
    result.loc[can_score, "score"] = weighted_total.loc[can_score] / available_weight.loc[can_score]
    if not result.loc[can_score, "score"].between(-1e-10, 100 + 1e-10).all():
        raise D3Error("Computed ward scores are outside 0..100")
    result.loc[can_score, "score"] = result.loc[can_score, "score"].clip(0, 100)
    for key in INDICATORS:
        percentile = pd.to_numeric(result[f"{key}_percentile"], errors="coerce")
        valid = can_score & percentile.notna()
        result.loc[valid, f"effective_weight_{key}"] = weights[key] / available_weight.loc[valid]
    result["available_indicator_weight"] = available_weight

    flags_input = result["flags"] if "flags" in result else pd.Series([[] for _ in result])
    result["flags"] = [_flags(value) for value in flags_input]
    # Make unavailable groundwater visible on every affected ward, without assigning a value.
    if result.gw_stage_pct.isna().any():
        result["flags"] = [
            sorted(set(flags) | ({"groundwater_missing"} if pd.isna(stage) else set()))
            for flags, stage in zip(result["flags"], result.gw_stage_pct, strict=True)
        ]
    result["flags"] = [
        sorted(set(flags) | ({"low_coverage"} if not is_eligible else set()))
        for flags, is_eligible in zip(result["flags"], eligible, strict=True)
    ]
    result["rank"] = pd.Series([pd.NA] * len(result), dtype="Int64")
    ranked_ids = (
        result.loc[can_score]
        .sort_values(["score", "ward_id"], ascending=[False, True], kind="mergesort")
        .index
    )
    result.loc[ranked_ids, "rank"] = pd.Series(
        range(1, len(ranked_ids) + 1), index=ranked_ids, dtype="Int64"
    )
    result.loc[~can_score, "score"] = pd.NA
    result["status"] = expected_status
    result["rank_p05"] = pd.NA
    result["rank_p95"] = pd.NA
    if "histogram" not in result:
        result["histogram"] = None
    result.attrs["original_weights"] = weights
    available = {key for key, column in INDICATORS.items() if result[column].notna().any()}
    total = sum(weights[key] for key in available)
    result.attrs["effective_weights"] = {
        key: weights[key] / total if key in available and total else 0.0 for key in INDICATORS
    }
    result.attrs["coverage_min_pct"] = coverage_min
    result.attrs["used_indicators"] = sorted(available)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_csv(path: Path, frame: pd.DataFrame, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D3Error(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, na_rep="")
    os.replace(temporary, path)


def _write_json(path: Path, payload: dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D3Error(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    d1 = pd.read_csv(args.d1_csv)
    d2 = pd.read_csv(args.groundwater_csv)
    cfg = _read_config(args.config)
    try:
        ward_document = json.loads(args.ward_geojson.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise D3Error("Cannot read ward GeoJSON") from exc
    features = ward_document.get("features") if isinstance(ward_document, dict) else None
    if (
        not isinstance(ward_document, dict)
        or ward_document.get("type") != "FeatureCollection"
        or not isinstance(features, list)
    ):
        raise D3Error("Ward geometry must be a GeoJSON FeatureCollection")
    geometry_ids = [
        feature.get("properties", {}).get("ward_id")
        for feature in features
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
    ]
    if len(features) != 250 or len(geometry_ids) != 250 or len(set(map(str, geometry_ids))) != 250:
        raise D3Error("Ward GeoJSON must contain exactly 250 unique ward_id features")
    if set(map(str, geometry_ids)) != set(d1.ward_id.astype(str).str.strip()):
        raise D3Error("D1 ward IDs do not exactly match the supplied ward geometry")
    merged = merge_groundwater(d1, d2)
    result = compute_index(merged, cfg)
    _write_csv(args.output, result, args.overwrite)
    weights = result.attrs["original_weights"]
    effective = result.attrs["effective_weights"]
    ranked = result.loc[result.status.eq("ranked")]
    ranks = sorted(ranked["rank"].dropna().astype(int).tolist())
    qa = {
        "report_type": "D3 ward inspection index QA",
        "method": {
            "percentile": "Average rank percentile among eligible wards with non-null indicator; higher is higher priority.",
            "score": "Configured weights renormalized over each ward's available indicators; score is 0..100.",
            "ranking": "Score descending, then ward_id ascending; unique contiguous ranks.",
            "coverage_min_pct": result.attrs["coverage_min_pct"],
            "original_weights": weights,
            "globally_effective_weights": effective,
            "groundwater": "All-null D2 values are unavailable; I4 excluded and never imputed.",
        },
        "inputs": {
            str(path): {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for path in (args.d1_csv, args.groundwater_csv, args.config, args.ward_geojson)
        },
        "summary": {
            "wards": len(result),
            "ranked": int(result.status.eq("ranked").sum()),
            "unranked": int(result.status.eq("insufficient_data").sum()),
            "rank_contiguous_unique": ranks == list(range(1, len(ranks) + 1)),
            "distinct_scores": int(ranked.score.nunique()),
            "tied_score_groups": int((ranked.score.value_counts() > 1).sum()),
            "score_min": float(ranked.score.min()) if len(ranked) else None,
            "score_median": float(ranked.score.median()) if len(ranked) else None,
            "score_max": float(ranked.score.max()) if len(ranked) else None,
            "groundwater_missing_wards": int(result.gw_stage_pct.isna().sum()),
            "unranked_reasons": {
                "insufficient_coverage_or_no_buildings": int((~result.status.eq("ranked")).sum())
            },
            "top_10": ranked.sort_values("rank")
            .head(10)[["ward_id", "ward_name", "score", "rank", "coverage_pct"]]
            .to_dict("records"),
        },
        "output": {
            "path": str(args.output),
            "sha256": _sha256(args.output),
            "size_bytes": args.output.stat().st_size,
        },
        "limitations": [
            "Inspection index is a prioritization index, not a calibrated collapse probability or structural safety assessment.",
            "I4 is unavailable because CGWB assessment-unit boundary correspondence is unverified.",
            "rank_p05 and rank_p95 remain null pending D4 sensitivity analysis.",
        ],
    }
    _write_json(args.qa_output, qa, args.overwrite)
    return qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d1-csv", type=Path, required=True)
    parser.add_argument("--groundwater-csv", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ward-geojson", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qa-output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
