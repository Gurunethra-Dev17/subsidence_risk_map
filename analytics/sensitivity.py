"""Reproducible D4 weight and A7 engine-parameter sensitivity analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml
from scipy.stats import kendalltau

from analytics.index import D3Error, compute_index, merge_groundwater

DRAWS = 500
SEED = 42
CONCENTRATION = 50.0
INDICATOR_KEYS = ("i1", "i2", "i3", "i4")
INDICATOR_COLUMNS = (
    "i1_percentile",
    "i2_percentile",
    "i3_percentile",
    "i4_percentile",
)
EXPECTED_VARIANTS = {
    (radius, pair_min, pair_max)
    for radius in (50, 100, 150)
    for pair_min, pair_max in ((80, 100), (80, 120), (80, 160))
}


class D4Error(ValueError):
    """Invalid D4 input or output operation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_text(path: Path, content: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D4Error(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_csv(path: Path, frame: pd.DataFrame, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D4Error(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, na_rep="")
    os.replace(temporary, path)


def _write_json(path: Path, value: dict[str, Any], overwrite: bool) -> None:
    _write_text(path, json.dumps(value, indent=2, allow_nan=False) + "\n", overwrite)


def calculate_kendall(first: pd.Series, second: pd.Series) -> float | None:
    """Kendall tau-b over a paired, explicitly common population."""
    left = pd.to_numeric(first, errors="coerce")
    right = pd.to_numeric(second, errors="coerce")
    valid = left.notna() & right.notna()
    if int(valid.sum()) < 2:
        return None
    value = kendalltau(left.loc[valid], right.loc[valid], variant="b").statistic
    return float(value) if math.isfinite(float(value)) else None


def _rank_scores(scores: np.ndarray, ward_ids: list[str]) -> np.ndarray:
    """Rank descending with D3's deterministic ward_id tie breaker."""
    order = sorted(range(len(ward_ids)), key=lambda index: (-scores[index], ward_ids[index]))
    ranks = np.empty(len(order), dtype=np.int64)
    ranks[np.asarray(order, dtype=np.int64)] = np.arange(1, len(order) + 1)
    return ranks


def sample_weight_draws(
    base_weights: dict[str, float], draws: int = DRAWS, seed: int = SEED
) -> np.ndarray:
    """Draw weights from the agreed Dirichlet centered on configured C6 weights."""
    if draws < 1:
        raise D4Error("draws must be positive")
    weights = np.asarray([base_weights[key] for key in INDICATOR_KEYS], dtype=np.float64)
    if not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
        raise D4Error("Configured indicator weights must be finite, non-negative and nonzero")
    draws_array = np.random.default_rng(seed).dirichlet(
        weights / weights.sum() * CONCENTRATION, draws
    )
    if draws_array.shape != (draws, 4) or not np.isfinite(draws_array).all():
        raise D4Error("Dirichlet sampling returned invalid weights")
    if not np.allclose(draws_array.sum(axis=1), 1.0, rtol=0, atol=1e-12):
        raise D4Error("Each Dirichlet weight draw must sum to one")
    return draws_array


def compute_weight_sensitivity(
    baseline: pd.DataFrame,
    base_weights: dict[str, float],
    draws: int = DRAWS,
    seed: int = SEED,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute rank intervals over D3 percentiles with per-ward available-weight fallback."""
    required = {"ward_id", "ward_name", "status", "rank", *INDICATOR_COLUMNS}
    missing = required - set(baseline.columns)
    if missing:
        raise D4Error(f"Baseline is missing fields: {sorted(missing)}")
    if baseline.ward_id.isna().any() or baseline.ward_id.astype(str).duplicated().any():
        raise D4Error("Baseline ward IDs must be non-null and unique")
    eligible = baseline.loc[baseline.status.eq("ranked")].copy().reset_index(drop=True)
    if eligible.empty:
        raise D4Error("Baseline has no ranked wards")
    eligible["ward_id"] = eligible.ward_id.astype(str)
    ids = eligible.ward_id.tolist()
    base_ranks = pd.to_numeric(eligible["rank"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(base_ranks).all() or sorted(base_ranks.astype(int)) != list(
        range(1, len(ids) + 1)
    ):
        raise D4Error("Baseline ranked wards must have unique contiguous integer ranks")
    percentile_matrix = (
        eligible.loc[:, INDICATOR_COLUMNS]
        .apply(pd.to_numeric, errors="coerce")
        .to_numpy(dtype=np.float64)
    )
    if np.isinf(percentile_matrix).any():
        raise D4Error("Baseline indicator percentiles contain infinite values")

    sampled = sample_weight_draws(base_weights, draws, seed)
    available = np.isfinite(percentile_matrix)
    effective_draw_weights = available[np.newaxis, :, :] * sampled[:, np.newaxis, :]
    effective_draw_weights /= effective_draw_weights.sum(axis=2, keepdims=True)
    ranks_by_draw = np.empty((draws, len(ids)), dtype=np.int64)
    taus: list[float] = []
    for draw_index, sampled_weights in enumerate(sampled):
        draw_effective = available * sampled_weights[np.newaxis, :]
        denominator = draw_effective.sum(axis=1)
        if (denominator <= 0).any():
            raise D4Error("A baseline-ranked ward has no available indicator in a weight draw")
        scores = np.nansum(percentile_matrix * sampled_weights[np.newaxis, :], axis=1) / denominator
        ranks = _rank_scores(scores, ids)
        ranks_by_draw[draw_index] = ranks
        taus.append(float(kendalltau(base_ranks, ranks, variant="b").statistic))

    raw_p05 = np.percentile(ranks_by_draw, 5, axis=0)
    raw_p95 = np.percentile(ranks_by_draw, 95, axis=0)
    # C2 requires integer ranges that bracket the baseline rank. Empirical linear
    # quantiles are outward-rounded, then widened only if needed to contain baseline.
    p05 = np.minimum(np.floor(raw_p05), base_ranks).astype(np.int64)
    p95 = np.maximum(np.ceil(raw_p95), base_ranks).astype(np.int64)
    output = baseline[["ward_id", "ward_name", "status", "rank"]].copy()
    output["rank_p05"] = pd.Series([pd.NA] * len(output), dtype="Int64")
    output["rank_p95"] = pd.Series([pd.NA] * len(output), dtype="Int64")
    output["rank_min"] = pd.Series([pd.NA] * len(output), dtype="Int64")
    output["rank_max"] = pd.Series([pd.NA] * len(output), dtype="Int64")
    output["rank_p05_empirical_linear"] = pd.NA
    output["rank_p95_empirical_linear"] = pd.NA
    output["rank_median"] = pd.NA
    output["top_10_frequency_pct"] = pd.NA
    positions = {ward_id: idx for idx, ward_id in enumerate(ids)}
    for row_index, ward_id in enumerate(output.ward_id.astype(str)):
        if ward_id not in positions:
            continue
        index = positions[ward_id]
        output.loc[output.index[row_index], "rank_p05"] = int(p05[index])
        output.loc[output.index[row_index], "rank_p95"] = int(p95[index])
        output.loc[output.index[row_index], "rank_min"] = int(ranks_by_draw[:, index].min())
        output.loc[output.index[row_index], "rank_max"] = int(ranks_by_draw[:, index].max())
        output.loc[output.index[row_index], "rank_p05_empirical_linear"] = float(raw_p05[index])
        output.loc[output.index[row_index], "rank_p95_empirical_linear"] = float(raw_p95[index])
        output.loc[output.index[row_index], "rank_median"] = float(
            np.median(ranks_by_draw[:, index])
        )
        output.loc[output.index[row_index], "top_10_frequency_pct"] = float(
            (ranks_by_draw[:, index] <= 10).mean() * 100
        )
    widths = p95 - p05
    tau_array = np.asarray(taus, dtype=np.float64)
    ranked_output = output.loc[output.status.eq("ranked")].copy()
    ranked_output["rank_interval_width"] = ranked_output.rank_p95.astype(
        int
    ) - ranked_output.rank_p05.astype(int)
    stable = ranked_output.sort_values(["rank_interval_width", "ward_id"], kind="mergesort").head(5)
    sensitive = ranked_output.sort_values(
        ["rank_interval_width", "ward_id"], ascending=[False, True], kind="mergesort"
    ).head(5)
    top_ten = ranked_output.sort_values("rank").head(10)
    globally_available = available.any(axis=0)
    global_weight_total = sum(
        base_weights[key] for index, key in enumerate(INDICATOR_KEYS) if globally_available[index]
    )
    qa = {
        "draws_completed": draws,
        "seed": seed,
        "dirichlet_concentration": CONCENTRATION,
        "dirichlet_alpha": {
            key: float(base_weights[key] / sum(base_weights.values()) * CONCENTRATION)
            for key in INDICATOR_KEYS
        },
        "configured_base_weights": {key: float(base_weights[key]) for key in INDICATOR_KEYS},
        "baseline_effective_weights_global": {
            key: float(base_weights[key] / global_weight_total)
            if globally_available[index]
            else 0.0
            for index, key in enumerate(INDICATOR_KEYS)
        },
        "effective_draw_weight_summary": {
            key: {
                "minimum": float(effective_draw_weights[:, :, index].min()),
                "median": float(np.median(effective_draw_weights[:, :, index])),
                "maximum": float(effective_draw_weights[:, :, index].max()),
            }
            for index, key in enumerate(INDICATOR_KEYS)
        },
        "weight_draw_min": sampled.min(axis=0).tolist(),
        "weight_draw_median": np.median(sampled, axis=0).tolist(),
        "weight_draw_max": sampled.max(axis=0).tolist(),
        "baseline_ranked_wards": len(ids),
        "baseline_unranked_wards": int(len(baseline) - len(ids)),
        "kendall_tau_vs_baseline": {
            "minimum": float(tau_array.min()),
            "median": float(np.median(tau_array)),
            "mean": float(tau_array.mean()),
            "maximum": float(tau_array.max()),
        },
        "rank_interval_width": {
            "minimum": int(widths.min()),
            "p25": float(np.percentile(widths, 25)),
            "median": float(np.median(widths)),
            "p75": float(np.percentile(widths, 75)),
            "maximum": int(widths.max()),
        },
        "top_ten_baseline_wards": [
            {
                "ward_id": str(row.ward_id),
                "ward_name": str(row.ward_name),
                "baseline_rank": int(row.rank),
                "rank_p05": int(row.rank_p05),
                "rank_p95": int(row.rank_p95),
                "top_10_frequency_pct": float(row.top_10_frequency_pct),
            }
            for row in top_ten.itertuples(index=False)
        ],
        "most_stable_wards_by_interval_width": [
            {
                "ward_id": str(row.ward_id),
                "ward_name": str(row.ward_name),
                "baseline_rank": int(row.rank),
                "interval_width": int(row.rank_interval_width),
            }
            for row in stable.itertuples(index=False)
        ],
        "most_sensitive_wards_by_interval_width": [
            {
                "ward_id": str(row.ward_id),
                "ward_name": str(row.ward_name),
                "baseline_rank": int(row.rank),
                "rank_p05": int(row.rank_p05),
                "rank_p95": int(row.rank_p95),
                "interval_width": int(row.rank_interval_width),
            }
            for row in sensitive.itertuples(index=False)
        ],
        "interval_method": (
            "NumPy linear empirical p05/p95; p05 floor and p95 ceil for integer contract, "
            "then widened only where needed to contain the unperturbed baseline rank. "
            "Raw linear quantiles are preserved in ward_sensitivity.csv."
        ),
        "groundwater_fallback": (
            "I4 remains unavailable in every draw; the original four-component Dirichlet "
            "draw is renormalized per ward over its non-null indicators, matching D3."
        ),
        "tie_breaker": "Score descending, then ward_id ascending; no score perturbation.",
        "kendall_method": "Kendall tau-b between baseline and simulated deterministic ranks.",
    }
    return output, qa


def aggregate_variant(path: Path, sinking_threshold: float) -> tuple[pd.DataFrame, dict[str, int]]:
    """Aggregate a variant with DuckDB; only ward-level rows enter Python memory."""
    connection = duckdb.connect(database=":memory:")
    try:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()
        columns = {row[0] for row in description}
        if not {"bldg_id", "ward_id", "vlm_mm_yr", "beta_horizon"}.issubset(columns):
            raise D4Error("A7 C1 artifact lacks required building metrics columns")
        result = connection.execute(
            "SELECT grouping(ward_id) AS is_summary, "
            "CAST(ward_id AS VARCHAR) AS ward_id, count(*) AS n_buildings, "
            "count(vlm_mm_yr) AS n_buildings_with_data, "
            "count(*) FILTER (WHERE vlm_mm_yr <= ?) AS sinking_count, "
            "count(beta_horizon) AS n_buildings_with_beta, "
            "median(vlm_mm_yr) AS vlm_median_mm_yr, "
            "quantile_cont(beta_horizon, 0.9) AS beta_p90_horizon, "
            "count(*) FILTER (WHERE ward_id IS NULL) AS unassigned_ward_rows, "
            "count(bldg_id) AS non_null_ids, count(DISTINCT bldg_id) AS unique_ids, "
            "count(vlm_mm_yr) AS total_non_null_vlm, "
            "count(beta_horizon) AS total_non_null_beta "
            "FROM read_parquet(?) GROUP BY GROUPING SETS ((ward_id), ())",
            [sinking_threshold, str(path)],
        ).fetchdf()
        summary_rows = result.loc[result.is_summary.eq(1)]
        if len(summary_rows) != 1:
            raise D4Error("Could not compute A7 artifact-level integrity totals")
        totals = summary_rows.iloc[0]
        rows = int(totals.n_buildings)
        non_null_ids = int(totals.non_null_ids)
        unique_ids = int(totals.unique_ids)
        if rows != non_null_ids or rows != unique_ids:
            raise D4Error("A7 building IDs must be non-null and unique")
        grouped = result.loc[result.is_summary.eq(0)].drop(
            columns=[
                "is_summary",
                "unassigned_ward_rows",
                "non_null_ids",
                "unique_ids",
                "total_non_null_vlm",
                "total_non_null_beta",
            ]
        )
        grouped = grouped.loc[grouped.ward_id.notna()].reset_index(drop=True)
        return grouped, {
            "rows": int(rows),
            "unassigned_ward_rows": int(totals.unassigned_ward_rows),
            "non_null_vlm": int(totals.total_non_null_vlm),
            "non_null_beta": int(totals.total_non_null_beta),
        }
    finally:
        connection.close()


def _variant_catalog(
    summary_path: Path, integration_manifest_path: Path, root: Path
) -> list[dict[str, Any]]:
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        manifest = json.loads(integration_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise D4Error("Cannot read A7 summary or integration manifest") from exc
    if not isinstance(summary, dict) or not isinstance(manifest, dict):
        raise D4Error("A7 summary and integration manifest must be JSON objects")
    experiments = summary.get("experiments") if isinstance(summary, dict) else None
    staged = manifest.get("a7_variants") if isinstance(manifest, dict) else None
    if (
        summary.get("contract") != "C1@1.0"
        or summary.get("city") != "delhi"
        or summary.get("experiment_count") != 9
        or summary.get("seed") != SEED
    ):
        raise D4Error("A7 summary must identify the Delhi C1@1.0 run with seed 42")
    if not isinstance(experiments, list) or len(experiments) != 9:
        raise D4Error("A7 robustness summary must contain exactly nine experiments")
    if not isinstance(staged, list) or len(staged) != 9:
        raise D4Error("Integration manifest must contain nine verified A7 artifacts")
    staged_by_path = {item.get("path"): item for item in staged if isinstance(item, dict)}
    if len(staged_by_path) != 9:
        raise D4Error("Integration manifest A7 paths must be unique")
    catalog = []
    seen: set[tuple[int, int, int]] = set()
    for experiment in experiments:
        if not isinstance(experiment, dict):
            raise D4Error("A7 experiment entry must be an object")
        key = (
            experiment.get("radius_m"),
            experiment.get("pair_min_m"),
            experiment.get("pair_max_m"),
        )
        if (
            any(isinstance(value, bool) or not isinstance(value, int) for value in key)
            or key not in EXPECTED_VARIANTS
            or key in seen
        ):
            raise D4Error("A7 summary has a missing, duplicate or unexpected parameter variant")
        seen.add(key)
        relative = experiment.get("output")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise D4Error("A7 artifact path must be a relative path")
        staged_item = staged_by_path.get(str(root / relative).replace("\\", "/"))
        if staged_item is None:
            # Manifest paths are repository-relative; use the A7 relative artifact path.
            staged_item = staged_by_path.get((root / relative).as_posix())
        if staged_item is None:
            candidate = [
                item
                for item in staged
                if isinstance(item, dict)
                and item.get("path", "").endswith(str(relative).replace("\\", "/"))
            ]
            if len(candidate) != 1:
                raise D4Error(
                    "A7 summary artifact cannot be reconciled with the integration manifest"
                )
            staged_item = candidate[0]
        for field in ("radius_m", "pair_min_m", "pair_max_m", "params_hash", "rows"):
            if experiment.get(field) != staged_item.get(field):
                raise D4Error(f"A7 summary and manifest disagree on {field}")
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise D4Error("A7 output path escapes the configured variant directory")
        if experiment.get("engine_version", staged_item.get("engine_version")) != staged_item.get(
            "engine_version"
        ):
            raise D4Error("A7 summary and manifest disagree on engine_version")
        catalog.append(
            {
                **experiment,
                "engine_version": staged_item.get("engine_version"),
                "path": path,
                "manifest": staged_item,
            }
        )
    if seen != EXPECTED_VARIANTS:
        raise D4Error("A7 summary does not contain all nine required parameter variants")
    return sorted(
        catalog, key=lambda item: (item["radius_m"], item["pair_min_m"], item["pair_max_m"])
    )


def _validate_variant_artifact(item: dict[str, Any]) -> tuple[str, dict[str, str]]:
    path: Path = item["path"]
    manifest = item["manifest"]
    if not path.is_file():
        raise D4Error(f"A7 artifact is missing: {path}")
    actual_hash = _sha256(path)
    if actual_hash != manifest.get("sha256"):
        raise D4Error(f"A7 artifact checksum differs from the integration manifest: {path}")
    parquet = pq.ParquetFile(path)
    metadata = {
        key.decode("utf-8"): value.decode("utf-8")
        for key, value in (parquet.schema_arrow.metadata or {}).items()
    }
    expected = {
        "contract": "C1@1.0",
        "engine_version": str(item["engine_version"]),
        "params_hash": str(item["params_hash"]),
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise D4Error(f"A7 Parquet metadata does not match its recorded experiment: {path}")
    if parquet.metadata.num_rows != int(item["rows"]):
        raise D4Error(f"A7 Parquet row count does not match its recorded experiment: {path}")
    return actual_hash, metadata


def _variant_indicators(
    grouped: pd.DataFrame,
    ward_base: pd.DataFrame,
    groundwater: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    result = ward_base[["ward_id", "ward_name"]].copy()
    grouped = grouped.copy()
    grouped["ward_id"] = grouped.ward_id.astype(str)
    if grouped.ward_id.duplicated().any() or not set(grouped.ward_id).issubset(set(result.ward_id)):
        raise D4Error("A7 aggregates contain duplicate or unknown ward IDs")
    result = result.merge(grouped, on="ward_id", how="left", validate="one_to_one")
    for column in (
        "n_buildings",
        "n_buildings_with_data",
        "sinking_count",
        "n_buildings_with_beta",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype("int64")
    if not result.n_buildings.equals(ward_base.n_buildings.astype("int64")):
        raise D4Error(
            "A7 ward building assignment counts differ from the authoritative D1 baseline"
        )
    if (result.n_buildings_with_data > result.n_buildings).any():
        raise D4Error("A7 VLM counts exceed assigned buildings")
    threshold = cfg["params"]["coverage_min"]
    threshold_pct = float(threshold) * 100 if 0 < float(threshold) <= 1 else float(threshold)
    result["coverage_pct"] = np.where(
        result.n_buildings.gt(0), result.n_buildings_with_data / result.n_buildings * 100, 0.0
    )
    result["status"] = np.where(
        result.n_buildings.gt(0) & result.coverage_pct.ge(threshold_pct),
        "ranked",
        "insufficient_data",
    )
    result["share_sinking_gt4"] = result.sinking_count / result.n_buildings_with_data.where(
        result.n_buildings_with_data.gt(0)
    )
    result["flags"] = [[] for _ in range(len(result))]
    result["vlm_median_mm_yr"] = pd.to_numeric(result.vlm_median_mm_yr, errors="coerce")
    result["beta_p90_horizon"] = pd.to_numeric(result.beta_p90_horizon, errors="coerce")
    return merge_groundwater(result, groundwater)


def compute_variant_robustness(
    catalog: list[dict[str, Any]],
    ward_base: pd.DataFrame,
    groundwater: pd.DataFrame,
    cfg: dict[str, Any],
    baseline_result: pd.DataFrame,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    baseline_ranked = baseline_result.loc[baseline_result.status.eq("ranked")].copy()
    baseline_ids = set(baseline_ranked.ward_id.astype(str))
    baseline_rank_lookup = dict(
        zip(baseline_ranked.ward_id.astype(str), baseline_ranked["rank"].astype(int), strict=True)
    )
    summaries: list[dict[str, Any]] = []
    all_ranks: list[pd.DataFrame] = []
    threshold = float(cfg["params"].get("sinking_threshold_mm_yr", -4))
    for item in catalog:
        input_hash, metadata = _validate_variant_artifact(item)
        grouped, counts = aggregate_variant(item["path"], threshold)
        indicators = _variant_indicators(grouped, ward_base, groundwater, cfg)
        result = compute_index(indicators, cfg)
        ranked = result.loc[result.status.eq("ranked")].copy()
        ranked = ranked.sort_values(["score", "ward_id"], ascending=[False, True], kind="mergesort")
        variant_ids = set(ranked.ward_id.astype(str))
        common = sorted(variant_ids & baseline_ids)
        tau: float | None = None
        reason = None
        movements: list[int] = []
        if len(common) >= 2:
            base_common = pd.Series([baseline_rank_lookup[ward_id] for ward_id in common])
            variant_lookup = dict(
                zip(ranked.ward_id.astype(str), ranked["rank"].astype(int), strict=True)
            )
            variant_common = pd.Series([variant_lookup[ward_id] for ward_id in common])
            base_common_ranks = base_common.rank(method="min").astype(int)
            variant_common_ranks = variant_common.rank(method="min").astype(int)
            tau = calculate_kendall(base_common_ranks, variant_common_ranks)
            movements = (
                np.abs(base_common_ranks.to_numpy() - variant_common_ranks.to_numpy())
                .astype(int)
                .tolist()
            )
        else:
            reason = "Fewer than two wards are jointly ranked with the D3 baseline."
        baseline_top = set(baseline_ranked.sort_values("rank").head(10).ward_id.astype(str))
        variant_top = set(ranked.head(10).ward_id.astype(str))
        summary = {
            "radius_m": int(item["radius_m"]),
            "pair_min_m": int(item["pair_min_m"]),
            "pair_max_m": int(item["pair_max_m"]),
            "input_path": str(item["path"]),
            "input_sha256": input_hash,
            "params_hash": metadata["params_hash"],
            "engine_version": metadata["engine_version"],
            "rows": counts["rows"],
            "unassigned_ward_rows": counts["unassigned_ward_rows"],
            "vlm_nonnull": counts["non_null_vlm"],
            "beta_nonnull": counts["non_null_beta"],
            "ranked_wards": int(result.status.eq("ranked").sum()),
            "unranked_wards": int(result.status.eq("insufficient_data").sum()),
            "baseline_ranked_wards": len(baseline_ids),
            "common_ranked_wards": len(common),
            "kendall_tau_vs_baseline": tau,
            "correlation_unavailable_reason": reason,
            "top_ten_overlap_count": len(baseline_top & variant_top) if len(ranked) >= 10 else None,
            "rank_movement_abs": {
                "median": float(np.median(movements)) if movements else None,
                "mean": float(np.mean(movements)) if movements else None,
                "maximum": int(max(movements)) if movements else None,
            },
        }
        summaries.append(summary)
        if not ranked.empty:
            selected = ranked[["ward_id", "ward_name", "status", "score", "rank"]].copy()
            selected["radius_m"] = summary["radius_m"]
            selected["pair_min_m"] = summary["pair_min_m"]
            selected["pair_max_m"] = summary["pair_max_m"]
            selected["params_hash"] = summary["params_hash"]
            all_ranks.append(selected)
    rank_frame = pd.concat(all_ranks, ignore_index=True) if all_ranks else pd.DataFrame()
    return summaries, rank_frame


def _load_csv(path: Path, label: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise D4Error(f"Cannot read {label}: {path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise D4Error(f"Cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise D4Error(f"{label} must be a JSON object")
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise D4Error("Cannot read matching C6 configuration") from exc
    if not isinstance(cfg, dict) or cfg.get("contract") != "C6@1.0" or cfg.get("city") != "delhi":
        raise D4Error("Configuration must be the validated Delhi C6@1.0 reference")
    params, weights = cfg.get("params"), cfg.get("weights")
    if not isinstance(params, dict) or not isinstance(weights, dict):
        raise D4Error("C6 configuration must contain params and weights objects")
    required_params = {
        "coverage_min",
        "sens_draws",
        "sens_concentration",
        "pair_min_m",
        "pair_max_m",
    }
    if required_params - set(params) or set(INDICATOR_KEYS) - set(weights):
        raise D4Error("C6 configuration is missing required D4 parameters or weights")
    if int(params["sens_draws"]) != DRAWS or float(params["sens_concentration"]) != CONCENTRATION:
        raise D4Error(
            "C6 sensitivity settings must match the agreed 500 draws and concentration 50"
        )
    seed = int(cfg.get("seed", SEED))
    if seed != SEED:
        raise D4Error("C6 seed must match the agreed reproducibility seed 42")

    d1 = _load_csv(args.d1_csv, "D1 ward indicators")
    groundwater = _load_csv(args.groundwater_csv, "D2 groundwater context")
    baseline_csv = _load_csv(args.baseline_csv, "D3 baseline ward index")
    baseline_qc = _load_json(args.baseline_qa, "D3 ward QA")
    d3_qc = _load_json(args.d3_qa, "D3 QA")
    manifest = _load_json(args.integration_manifest, "integration manifest")
    required_d1 = {
        "ward_id",
        "ward_name",
        "n_buildings",
        "n_buildings_with_data",
        "coverage_pct",
        "share_sinking_gt4",
        "vlm_median_mm_yr",
        "beta_p90_horizon",
        "status",
        "flags",
    }
    if required_d1 - set(d1.columns):
        raise D4Error(f"D1 indicators are missing fields: {sorted(required_d1 - set(d1.columns))}")
    for label, frame in (("D1", d1), ("D2", groundwater), ("D3", baseline_csv)):
        if (
            "ward_id" not in frame
            or frame.ward_id.isna().any()
            or frame.ward_id.astype(str).duplicated().any()
        ):
            raise D4Error(f"{label} input must have non-null unique ward IDs")
        frame["ward_id"] = frame.ward_id.astype(str)
    if set(d1.ward_id) != set(groundwater.ward_id) or set(d1.ward_id) != set(baseline_csv.ward_id):
        raise D4Error("D1, D2 and D3 ward ID sets must match exactly")
    if not groundwater.gw_stage_pct.isna().all():
        raise D4Error("This approved D3 baseline uses unavailable groundwater I4; values changed")

    def recorded_hash(document: dict[str, Any], path: Path, label: str) -> str:
        inputs = document.get("inputs")
        if not isinstance(inputs, dict):
            raise D4Error(f"{label} has no input provenance")
        matching = [
            value
            for name, value in inputs.items()
            if isinstance(value, dict)
            and Path(name.replace("\\", "/")).name.casefold() == path.name.casefold()
        ]
        if len(matching) != 1 or matching[0].get("sha256") != _sha256(path):
            raise D4Error(f"{label} provenance does not match selected input {path.name}")
        return str(matching[0]["sha256"])

    recorded_hash(baseline_qc, args.d1_csv, "D3 ward QA")
    recorded_hash(baseline_qc, args.groundwater_csv, "D3 ward QA")
    recorded_hash(baseline_qc, args.config, "D3 ward QA")
    recorded_hash(d3_qc, args.c1_parquet, "D3 QA")
    recorded_hash(d3_qc, args.config, "D3 QA")
    c1_manifest = manifest.get("c1_candidate")
    if not isinstance(c1_manifest, dict) or c1_manifest.get("sha256") != _sha256(args.c1_parquet):
        raise D4Error("Selected baseline C1 hash does not match the integration manifest")
    c1_metadata = {
        key.decode(): value.decode()
        for key, value in (pq.ParquetFile(args.c1_parquet).schema_arrow.metadata or {}).items()
    }
    canonical_params = json.dumps(
        params, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    expected_params_hash = hashlib.sha256(canonical_params.encode("utf-8")).hexdigest()
    if (
        c1_metadata.get("contract") != "C1@1.0"
        or c1_metadata.get("params_hash") != expected_params_hash
        or c1_metadata.get("horizon_years") != str(params["horizon_years"])
        or c1_metadata.get("seed") != str(seed)
    ):
        raise D4Error("Selected baseline C1 metadata does not match the complete C6 params mapping")
    if c1_metadata.get("engine_version") != c1_manifest.get("engine_version"):
        raise D4Error("Selected baseline C1 engine version differs from the integration manifest")
    merged = merge_groundwater(d1, groundwater)
    baseline_result = compute_index(merged, cfg)
    check = baseline_result.merge(
        baseline_csv[["ward_id", "score", "rank", "status"]],
        on="ward_id",
        how="outer",
        validate="one_to_one",
        suffixes=("_computed", "_saved"),
        indicator=True,
    )
    if not check._merge.eq("both").all():
        raise D4Error("Recomputed D3 baseline ward set differs from saved D3 output")
    ranked_check = check.status_computed.eq("ranked")
    saved_score = pd.to_numeric(check.loc[ranked_check, "score_saved"], errors="coerce")
    computed_score = pd.to_numeric(check.loc[ranked_check, "score_computed"], errors="coerce")
    saved_rank = pd.to_numeric(check.loc[ranked_check, "rank_saved"], errors="coerce")
    computed_rank = pd.to_numeric(check.loc[ranked_check, "rank_computed"], errors="coerce")
    score_difference = (
        float((saved_score - computed_score).abs().max()) if len(saved_score) else 0.0
    )
    if (
        not np.allclose(saved_score, computed_score, rtol=0, atol=1e-8)
        or not np.array_equal(saved_rank.to_numpy(dtype=int), computed_rank.to_numpy(dtype=int))
        or not check.status_computed.eq(check.status_saved).all()
    ):
        raise D4Error("Recomputed D3 baseline does not reproduce saved scores and ranks")

    sensitivity, weight_qa = compute_weight_sensitivity(baseline_result, weights, DRAWS, seed)
    if len(sensitivity) != len(baseline_result):
        raise D4Error("Sensitivity output must include every ward, including unranked wards")
    if (
        not sensitivity.loc[sensitivity.status.eq("ranked"), "rank_p05"]
        .le(sensitivity.loc[sensitivity.status.eq("ranked"), "rank"])
        .all()
        or not sensitivity.loc[sensitivity.status.eq("ranked"), "rank_p95"]
        .ge(sensitivity.loc[sensitivity.status.eq("ranked"), "rank"])
        .all()
    ):
        raise D4Error("D4 rank intervals must bracket each baseline rank")

    variants = _variant_catalog(args.a7_summary, args.integration_manifest, args.a7_root)
    ward_base = d1[["ward_id", "ward_name", "n_buildings"]].copy()
    variant_summaries, variant_ranks = compute_variant_robustness(
        variants, ward_base, groundwater, cfg, baseline_result
    )
    selected = [
        item for item in variant_summaries if item["pair_min_m"] == 80 and item["pair_max_m"] == 120
    ]
    selected.sort(key=lambda item: item["radius_m"])
    if len(selected) != 3:
        raise D4Error("Could not select the agreed 80–120 m pair window for C3 radius results")
    widths = pd.to_numeric(
        sensitivity.loc[sensitivity.status.eq("ranked"), "rank_p95"], errors="coerce"
    ) - pd.to_numeric(sensitivity.loc[sensitivity.status.eq("ranked"), "rank_p05"], errors="coerce")
    c3_robustness = {
        "kendall_tau_weights_mean": weight_qa["kendall_tau_vs_baseline"]["mean"],
        "rank_range_width_median": float(widths.median()),
        "radius_variants": [
            {
                "radius_m": item["radius_m"],
                "kendall_tau_vs_baseline": item["kendall_tau_vs_baseline"],
            }
            for item in selected
        ],
    }
    input_paths = {
        "d1_ward_indicators": args.d1_csv,
        "d2_groundwater_context": args.groundwater_csv,
        "d3_ward_index": args.baseline_csv,
        "d3_ward_qa": args.baseline_qa,
        "d3_qa": args.d3_qa,
        "c6_config": args.config,
        "a7_summary": args.a7_summary,
        "integration_manifest": args.integration_manifest,
    }
    input_provenance = {
        key: {"path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
        for key, path in input_paths.items()
    }
    diagnostic = args.sensitivity_output.parent / "a7_variant_ward_ranks.csv"
    output_paths = (args.sensitivity_output, args.robustness_output, args.qa_output)
    if not variant_ranks.empty:
        output_paths += (diagnostic,)
    if not args.overwrite and any(path.exists() for path in output_paths):
        raise D4Error("One or more output files already exist; pass --overwrite to replace them")
    _write_csv(args.sensitivity_output, sensitivity, args.overwrite)
    robustness_summary = {
        "report_type": "D4 weight sensitivity and A7 engine-parameter robustness",
        "baseline": {
            "c1_path": str(args.c1_parquet),
            "c1_sha256": _sha256(args.c1_parquet),
            "recomputed_d3_max_abs_score_difference": score_difference,
            "recomputed_d3_ranks_match": True,
            "ranked_wards": int(baseline_result.status.eq("ranked").sum()),
            "unranked_wards": int(baseline_result.status.eq("insufficient_data").sum()),
        },
        "weight_sensitivity": weight_qa,
        "a7_variants": variant_summaries,
        "c3_robustness": c3_robustness,
        "limitations": [
            "A7 parameter variants are sensitivity experiments, not independent observations or confidence intervals.",
            "Groundwater I4 is unavailable for all Delhi wards; each draw retains the D3 available-weight fallback.",
            "The nominal 100m/80–120m A7 artifact has a distinct parameter hash from baseline C1 and is not claimed equivalent.",
            "Ward assignment provenance from D3 is reused; this command does not repeat polygon spatial validation.",
            "No causal interpretation or calibrated collapse probability is provided.",
        ],
    }
    _write_json(args.robustness_output, robustness_summary, args.overwrite)
    if not variant_ranks.empty:
        _write_csv(diagnostic, variant_ranks, args.overwrite)
    outputs = {
        str(path): {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
        for path in (args.sensitivity_output, args.robustness_output, diagnostic)
        if path.is_file()
    }
    outputs[str(args.qa_output)] = {"sha256": None, "hash_note": "Self-hash is not embedded."}
    qa = {
        "report_type": "D4 reproducibility and contract QA",
        "inputs": input_provenance,
        "c1_baseline": {
            "path": str(args.c1_parquet),
            "sha256": _sha256(args.c1_parquet),
            "metadata": {
                key.decode(): value.decode()
                for key, value in (
                    pq.ParquetFile(args.c1_parquet).schema_arrow.metadata or {}
                ).items()
            },
        },
        "weight_sensitivity": weight_qa,
        "baseline_reproduction": {
            "max_absolute_score_difference": score_difference,
            "ranks_match_exactly": True,
        },
        "a7_variant_count": len(variant_summaries),
        "a7_variant_hashes_verified": True,
        "c3_pair_window_selected": "80–120 m",
        "outputs": outputs,
        "checks_not_performed": [
            "Full C0/C1 geometry audit was not repeated; validated D3 spatial assignment provenance was reused.",
            "No engine processing was rerun.",
        ],
        "reused_d3_spatial_assignment_reconciliation": d3_qc.get(
            "cell_assignment_reconciliation", {}
        ).get("status"),
    }
    _write_json(args.qa_output, qa, args.overwrite)
    return robustness_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d1-csv", type=Path, required=True)
    parser.add_argument("--groundwater-csv", type=Path, required=True)
    parser.add_argument("--baseline-csv", type=Path, required=True)
    parser.add_argument("--baseline-qa", type=Path, required=True)
    parser.add_argument("--d3-qa", type=Path, required=True)
    parser.add_argument("--c1-parquet", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--a7-summary", type=Path, required=True)
    parser.add_argument("--a7-root", type=Path, required=True)
    parser.add_argument("--integration-manifest", type=Path, required=True)
    parser.add_argument("--sensitivity-output", type=Path, required=True)
    parser.add_argument("--robustness-output", type=Path, required=True)
    parser.add_argument("--qa-output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args)
    except (D4Error, D3Error, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {"c3_robustness": report["c3_robustness"], "variants": len(report["a7_variants"])},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
