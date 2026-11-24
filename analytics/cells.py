"""D3 cell scoring using bounded DuckDB aggregates and supplied grid geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from analytics.index import D3Error, _finite_number, _write_csv, _write_json

CELL_FIELDS = [
    "cell_id",
    "ward_id",
    "n_buildings",
    "suppressed",
    "vlm_median_mm_yr",
    "beta_p90_horizon",
    "share_sinking_gt4",
    "cell_score",
    "cell_rank_in_ward",
]


def _weights(cfg: dict[str, Any]) -> tuple[dict[str, float], float]:
    if not isinstance(cfg, dict) or cfg.get("contract") != "C6@1.0":
        raise D3Error("Configuration must declare contract C6@1.0")
    params, weights = cfg.get("params"), cfg.get("weights")
    if not isinstance(params, dict) or not isinstance(weights, dict):
        raise D3Error("Configuration must contain params and weights objects")
    if params.get("cell_min_buildings") != 5:
        raise D3Error("D8 contract requires params.cell_min_buildings = 5")
    try:
        values = {key: _finite_number(weights[key], f"weights.{key}") for key in ("i1", "i2", "i3")}
        threshold = _finite_number(
            params.get("sinking_threshold_mm_yr", -4), "params.sinking_threshold_mm_yr"
        )
    except KeyError as exc:
        raise D3Error("Configuration weights must define i1, i2 and i3") from exc
    if any(value < 0 for value in values.values()) or sum(values.values()) <= 0:
        raise D3Error("Cell indicator weights must be non-negative with a positive total")
    return values, threshold


def compute_cell_index(
    cell_metrics: pd.DataFrame,
    grid_document: dict[str, Any],
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Return one D8-compatible row per supplied cell, retaining empty cells."""
    weights, _threshold = _weights(cfg)
    if not isinstance(grid_document, dict) or grid_document.get("type") != "FeatureCollection":
        raise D3Error("Grid geometry must be a GeoJSON FeatureCollection")
    features = grid_document.get("features")
    if not isinstance(features, list):
        raise D3Error("Grid geometry features must be an array")
    grid_rows = []
    for feature in features:
        props = feature.get("properties") if isinstance(feature, dict) else None
        cell_id = props.get("cell_id") if isinstance(props, dict) else None
        ward_id = props.get("ward_id") if isinstance(props, dict) else None
        if not isinstance(cell_id, str) or not cell_id.strip():
            raise D3Error("Every grid feature must have a non-empty string cell_id")
        if ward_id is not None and (not isinstance(ward_id, str | int) or not str(ward_id).strip()):
            raise D3Error(f"Grid ward_id must be a non-empty string or null for {cell_id}")
        grid_rows.append(
            {"cell_id": cell_id, "ward_id": str(ward_id) if ward_id is not None else None}
        )
    grid = pd.DataFrame(grid_rows)
    if grid.empty or grid.cell_id.duplicated().any():
        raise D3Error("Grid must contain unique cell IDs")

    required = {
        "cell_id",
        "n_buildings",
        "n_buildings_with_data",
        "sinking_count",
        "vlm_median_mm_yr",
        "beta_p90_horizon",
    }
    missing = required - set(cell_metrics.columns)
    if missing:
        raise D3Error(f"Cell aggregates are missing columns: {sorted(missing)}")
    metrics = cell_metrics.copy()
    if metrics.cell_id.isna().any() or metrics.cell_id.astype(str).str.strip().eq("").any():
        raise D3Error("Cell aggregates contain null or empty cell IDs")
    metrics["cell_id"] = metrics.cell_id.astype(str)
    if metrics.cell_id.duplicated().any():
        raise D3Error("Cell aggregates contain duplicate cell IDs")
    unknown = set(metrics.cell_id) - set(grid.cell_id)
    if unknown:
        raise D3Error(f"C1 contains {len(unknown)} cell IDs absent from supplied grid geometry")

    result = grid.merge(metrics, on="cell_id", how="left", validate="one_to_one")
    count_columns = ("n_buildings", "n_buildings_with_data", "sinking_count")
    for column in count_columns:
        values = pd.to_numeric(result[column], errors="coerce").fillna(0)
        if (values < 0).any() or (values % 1 != 0).any():
            raise D3Error(f"{column} must contain non-negative integers")
        result[column] = values.astype("int64")
    if (result.n_buildings_with_data > result.n_buildings).any():
        raise D3Error("n_buildings_with_data cannot exceed n_buildings")
    if (result.sinking_count > result.n_buildings_with_data).any():
        raise D3Error("sinking_count cannot exceed n_buildings_with_data")
    for column in ("vlm_median_mm_yr", "beta_p90_horizon"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
        if not result[column].dropna().map(math.isfinite).all():
            raise D3Error(f"{column} contains non-finite values")
    if (result.beta_p90_horizon.dropna() < 0).any():
        raise D3Error("beta_p90_horizon cannot be negative")

    result["suppressed"] = result.n_buildings.lt(5)
    result["share_sinking_gt4"] = result.sinking_count / result.n_buildings_with_data.where(
        result.n_buildings_with_data.gt(0), float("nan")
    )
    eligible = ~result.suppressed
    indicators = {
        "i1": result.share_sinking_gt4,
        "i2": result.beta_p90_horizon,
        "i3": result.n_buildings.astype(float),
    }
    percentiles: dict[str, pd.Series] = {}
    for key, values in indicators.items():
        valid = eligible & values.notna()
        percentile = pd.Series(float("nan"), index=result.index)
        percentile.loc[valid] = values.loc[valid].rank(method="average", pct=True) * 100
        percentiles[key] = percentile

    denominator = pd.Series(0.0, index=result.index)
    weighted = pd.Series(0.0, index=result.index)
    for key, percentile in percentiles.items():
        valid = eligible & percentile.notna()
        denominator.loc[valid] += weights[key]
        weighted.loc[valid] += percentile.loc[valid] * weights[key]
    result["cell_score"] = float("nan")
    scoreable = eligible & denominator.gt(0)
    result.loc[scoreable, "cell_score"] = weighted.loc[scoreable] / denominator.loc[scoreable]
    if not result.loc[scoreable, "cell_score"].between(0, 100).all():
        raise D3Error("Computed cell scores are outside 0..100")

    # Contract suppression removes every statistic for small cells.
    restricted = ["vlm_median_mm_yr", "beta_p90_horizon", "share_sinking_gt4", "cell_score"]
    result.loc[result.suppressed, restricted] = float("nan")
    result["cell_rank_in_ward"] = pd.Series([pd.NA] * len(result), dtype="Int64")
    rankable = result.loc[scoreable & result.ward_id.notna()].sort_values(
        ["ward_id", "cell_score", "cell_id"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    ranks = rankable.groupby("ward_id", sort=False).cumcount() + 1
    result.loc[rankable.index, "cell_rank_in_ward"] = ranks.astype("Int64")

    output = result[CELL_FIELDS].copy()
    output["n_buildings"] = output.n_buildings.astype("int64")
    output["suppressed"] = output.suppressed.astype(bool)
    output["cell_rank_in_ward"] = output.cell_rank_in_ward.astype("Int64")
    return output


def aggregate_c1(c1_path: Path, threshold: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate C1 with DuckDB; only per-cell summary rows enter Python memory."""
    connection = duckdb.connect(database=":memory:")
    try:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(c1_path)]
        ).fetchall()
        columns = {row[0] for row in description}
        required = {"bldg_id", "cell_id", "ward_id", "vlm_mm_yr", "beta_horizon"}
        if not required.issubset(columns):
            raise D3Error(f"C1 is missing required columns: {sorted(required - columns)}")
        totals = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE cell_id IS NULL), "
            "count(*) FILTER (WHERE bldg_id IS NULL), "
            "count(*) - count(DISTINCT bldg_id) FROM read_parquet(?)",
            [str(c1_path)],
        ).fetchone()
        if totals[2] or totals[3]:
            raise D3Error("C1 building IDs must be non-null and unique")
        query = """SELECT cell_id, count(bldg_id) AS n_buildings,
            count(vlm_mm_yr) AS n_buildings_with_data,
            count(*) FILTER (WHERE vlm_mm_yr <= ?) AS sinking_count,
            count(beta_horizon) AS n_beta_values,
            median(vlm_mm_yr) AS vlm_median_mm_yr,
            quantile_cont(beta_horizon, 0.9) AS beta_p90_horizon,
            count(DISTINCT ward_id) AS c1_ward_id_count,
            any_value(ward_id) AS c1_ward_id
            FROM read_parquet(?) WHERE cell_id IS NOT NULL GROUP BY cell_id"""
        rows = connection.execute(query, [threshold, str(c1_path)]).fetchdf()
        return rows, {
            "c1_rows": int(totals[0]),
            "unassigned_cell_rows": int(totals[1]),
            "assigned_cell_rows": int(totals[0] - totals[1]),
            "aggregated_cells": len(rows),
            "rows_with_vlm": int(rows.n_buildings_with_data.sum()),
            "rows_with_beta": int(rows.n_beta_values.sum()),
            "grouping": "DuckDB GROUP BY cell_id; no full building-row materialization in Python.",
        }
    finally:
        connection.close()


def audit_cell_ward_assignments(c1_path: Path, grid_wards: dict[str, str | None]) -> dict[str, Any]:
    """Compare C1 building ward assignments with supplied grid ward IDs for QA only."""
    connection = duckdb.connect(database=":memory:")
    try:
        pairs = connection.execute(
            "SELECT cell_id, ward_id, count(*) AS n FROM read_parquet(?) "
            "WHERE cell_id IS NOT NULL GROUP BY cell_id, ward_id",
            [str(c1_path)],
        ).fetchdf()
    finally:
        connection.close()
    if not set(pairs.cell_id.astype(str)).issubset(grid_wards):
        raise D3Error("C1 contains cell IDs absent from the supplied grid")
    nonmatching_cells: set[str] = set()
    mismatching_buildings = 0
    by_cell: dict[str, list[tuple[str | None, int]]] = {}
    for row in pairs.itertuples(index=False):
        cell_id = str(row.cell_id)
        assigned_ward = None if pd.isna(row.ward_id) else str(row.ward_id)
        raw_grid_ward = grid_wards[cell_id]
        grid_ward = str(raw_grid_ward) if raw_grid_ward is not None else None
        count = int(row.n)
        by_cell.setdefault(cell_id, []).append((assigned_ward, count))
        if assigned_ward is not None and grid_ward is not None and assigned_ward != grid_ward:
            nonmatching_cells.add(cell_id)
            mismatching_buildings += count
    majority_mismatches = 0
    for cell_id, ward_counts in by_cell.items():
        assigned = [(ward, count) for ward, count in ward_counts if ward is not None]
        if assigned and grid_wards[cell_id] is not None:
            dominant_ward = min(assigned, key=lambda item: (-item[1], item[0]))[0]
            majority_mismatches += dominant_ward != str(grid_wards[cell_id])
    return {
        "cells_with_any_non_grid_ward_assignment": len(nonmatching_cells),
        "building_rows_assigned_to_non_grid_ward": mismatching_buildings,
        "cells_where_largest_c1_ward_group_differs_from_grid": majority_mismatches,
        "interpretation": "Diagnostic only; output ward_id remains the supplied grid feature ward_id.",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise D3Error(f"Cannot read GeoJSON input: {path}") from exc
    if not isinstance(value, dict):
        raise D3Error("GeoJSON root must be an object")
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise D3Error("Cannot read C6 configuration") from exc
    weights, threshold = _weights(cfg)
    grid = _read_document(args.grid_geojson)
    aggregates, aggregate_qa = aggregate_c1(args.c1_parquet, threshold)
    import pyarrow.parquet as pq

    schema_metadata = pq.ParquetFile(args.c1_parquet).schema_arrow.metadata or {}
    metadata = {key.decode(): value.decode() for key, value in schema_metadata.items()}
    if metadata.get("contract") != "C1@1.0":
        raise D3Error("C1 Parquet metadata must declare C1@1.0")
    if cfg.get("city") != "delhi":
        raise D3Error("The matching C6 configuration must declare city delhi")
    canonical_params = json.dumps(
        cfg.get("params"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    expected_params_hash = hashlib.sha256(canonical_params.encode("utf-8")).hexdigest()
    if metadata.get("params_hash") != expected_params_hash:
        raise D3Error("C1 params_hash does not match the complete selected C6 params mapping")
    output = compute_cell_index(
        aggregates.drop(columns=["c1_ward_id_count", "c1_ward_id", "n_beta_values"]), grid, cfg
    )
    grid_wards = {
        feature["properties"]["cell_id"]: (
            str(feature["properties"]["ward_id"])
            if feature["properties"].get("ward_id") is not None
            else None
        )
        for feature in grid.get("features", [])
    }
    aggregate_qa.update(audit_cell_ward_assignments(args.c1_parquet, grid_wards))
    from analytics import export

    cell_rows = output.astype(object).where(pd.notna(output), "").to_dict("records")
    export.build_cell_scores(cell_rows, grid)
    _write_csv(args.output, output, args.overwrite)
    qa = {
        "report_type": "D3 cell inspection index QA",
        "method": {
            "percentile": "Average rank percentile among unsuppressed cells with non-null indicator; higher is higher priority.",
            "score": "C6 i1/i2/i3 weights renormalized per unsuppressed cell over available indicators; score is 0..100.",
            "ranking": "Within ward, score descending then cell_id ascending; contiguous ranks.",
            "coverage": "Indicator coverage uses non-null C1 values; no additional threshold is specified for cells.",
            "suppression": "Exactly n_buildings < params.cell_min_buildings (configured minimum is verified as 5 below).",
            "original_weights": weights,
            "effective_weights_when_all_available": {
                key: value / sum(weights.values()) for key, value in weights.items()
            },
        },
        "inputs": {
            str(path): {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for path in (args.c1_parquet, args.grid_geojson, args.config)
        },
        "c1_metadata": metadata,
        "aggregation": aggregate_qa,
        "summary": {
            "expected_grid_cells": len(grid.get("features", [])),
            "output_cells": len(output),
            "cells_with_buildings": int(output.n_buildings.gt(0).sum()),
            "empty_cells": int(output.n_buildings.eq(0).sum()),
            "suppressed_cells": int(output.suppressed.sum()),
            "suppressed_empty_cells": int((output.suppressed & output.n_buildings.eq(0)).sum()),
            "suppressed_populated_under_five": int(
                (output.suppressed & output.n_buildings.gt(0)).sum()
            ),
            "unsuppressed_cells": int((~output.suppressed).sum()),
            "scored_cells": int(output.cell_score.notna().sum()),
            "cells_with_vlm": int(output.vlm_median_mm_yr.notna().sum()),
            "cells_with_beta": int(output.beta_p90_horizon.notna().sum()),
            "vlm_metric_coverage_pct": (
                100 * aggregate_qa["rows_with_vlm"] / aggregate_qa["assigned_cell_rows"]
                if aggregate_qa["assigned_cell_rows"]
                else None
            ),
            "beta_metric_coverage_pct": (
                100 * aggregate_qa["rows_with_beta"] / aggregate_qa["assigned_cell_rows"]
                if aggregate_qa["assigned_cell_rows"]
                else None
            ),
            "ranked_cells": int(output.cell_rank_in_ward.notna().sum()),
            "unrankable_ward_cells": int((output.cell_score.notna() & output.ward_id.isna()).sum()),
            "missing_cell_ids": 0,
            "duplicate_cell_ids": int(output.cell_id.duplicated().sum()),
            "building_count_reconciliation": aggregate_qa["assigned_cell_rows"],
            "suppressed_restricted_null": bool(
                output.loc[
                    output.suppressed,
                    [
                        "vlm_median_mm_yr",
                        "beta_p90_horizon",
                        "share_sinking_gt4",
                        "cell_score",
                        "cell_rank_in_ward",
                    ],
                ]
                .isna()
                .all()
                .all()
            ),
            "score_min": float(output.cell_score.min())
            if output.cell_score.notna().any()
            else None,
            "score_median": float(output.cell_score.median())
            if output.cell_score.notna().any()
            else None,
            "score_max": float(output.cell_score.max())
            if output.cell_score.notna().any()
            else None,
            "c1_cells_with_multiple_ward_ids": int(aggregates.c1_ward_id_count.gt(1).sum()),
        },
        "output": {
            "path": str(args.output),
            "sha256": _sha256(args.output),
            "size_bytes": args.output.stat().st_size,
        },
        "limitations": [
            "C1 ward assignments are aggregated to cell IDs, while the supplied grid ward_id defines the exported cell-to-ward relationship.",
            "Null metrics remain unavailable; counts are exposure indicators, not structural condition measurements.",
        ],
    }
    if args.ward_csv is not None:
        qa["ward_output"] = {
            "path": str(args.ward_csv),
            "sha256": _sha256(args.ward_csv),
            "size_bytes": args.ward_csv.stat().st_size,
        }
    if args.ward_qa is not None:
        try:
            qa["ward"] = json.loads(args.ward_qa.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise D3Error("Cannot read ward QA report for combined D3 QA") from exc
        qa["inputs"][str(args.ward_qa)] = {
            "sha256": _sha256(args.ward_qa),
            "size_bytes": args.ward_qa.stat().st_size,
        }
    _write_json(args.qa_output, qa, args.overwrite)
    return qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c1-parquet", type=Path, required=True)
    parser.add_argument("--grid-geojson", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qa-output", type=Path, required=True)
    parser.add_argument("--ward-csv", type=Path)
    parser.add_argument("--ward-qa", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
