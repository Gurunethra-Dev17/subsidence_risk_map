
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau


# ==================================================
# 1. CONFIGURATION
# ==================================================

BASE_WEIGHTS = np.array([0.30, 0.35, 0.20, 0.15])

INDICATOR_NAMES = ["I1", "I2", "I3", "I4"]

DRAWS = 500
CONCENTRATION = 50
SEED = 42

COVERAGE_MIN = 50.0
SINKING_THRESHOLD = -4.0

D1_PATH = Path("out/d1_revised/ward_indicators.csv")
D3_PATH = Path("out/d3_revised/ward_inspection_index.csv")

A7_ROOT = Path("data/team_handoff/A7/robustness")
A7_SUMMARY = A7_ROOT / "robustness_summary.json"

OUTPUT_DIR = Path("out/d4")


# ==================================================
# 2. COMMON HELPER FUNCTIONS
# ==================================================

def calculate_percentiles(data):
    """
    Calculate indicator percentile scores.

    All indicators are oriented so that a higher
    percentile represents higher inspection risk.
    """

    result = data.copy()

    indicator_columns = {
        "I1": "share_sinking_gt4",
        "I2": "beta_p90_horizon",
        "I3": "n_buildings",
        "I4": "gw_stage_pct",
    }

    for indicator, column in indicator_columns.items():

        values = pd.to_numeric(
            result[column],
            errors="coerce"
        )

        result[f"{indicator}_percentile"] = (
            values.rank(
                method="average",
                pct=True
            ) * 100
        )

    return result


def calculate_index_scores(data):
    """
    Calculate the weighted index.

    Missing indicators are excluded and the
    remaining weights are renormalized.
    """

    result = data.copy()

    percentile_columns = [
        f"{name}_percentile"
        for name in INDICATOR_NAMES
    ]

    values = result[percentile_columns].apply(
        pd.to_numeric,
        errors="coerce"
    )

    weighted_total = (
        values.fillna(0)
        .mul(BASE_WEIGHTS, axis=1)
        .sum(axis=1)
    )

    available_weight = (
        values.notna()
        .mul(BASE_WEIGHTS, axis=1)
        .sum(axis=1)
    )

    result["available_indicator_weight"] = (
        available_weight
    )

    result["score"] = np.where(
        available_weight > 0,
        weighted_total / available_weight,
        np.nan
    )

    result["rank"] = (
        result["score"]
        .rank(
            method="min",
            ascending=False
        )
    )

    return result


def calculate_kendall(first, second):
    """Calculate Kendall rank correlation."""

    first = pd.to_numeric(
        first,
        errors="coerce"
    )

    second = pd.to_numeric(
        second,
        errors="coerce"
    )

    valid = first.notna() & second.notna()

    if valid.sum() < 2:
        return np.nan

    result = kendalltau(
        first.loc[valid],
        second.loc[valid]
    )

    return float(result.statistic)


# ==================================================
# 3. PART A: WEIGHT SENSITIVITY
# ==================================================

def run_weight_sensitivity():

    print("\n" + "=" * 55)
    print("D4 PART A: WEIGHT SENSITIVITY")
    print("=" * 55)

    baseline = pd.read_csv(D3_PATH)

    baseline["ward_id"] = (
        baseline["ward_id"].astype("string")
    )

    baseline = baseline[
        baseline["status"].eq("ranked")
    ].copy()

    percentile_columns = [
        f"{name}_percentile"
        for name in INDICATOR_NAMES
    ]

    baseline[percentile_columns] = (
        baseline[percentile_columns].apply(
            pd.to_numeric,
            errors="coerce"
        )
    )

    if baseline[percentile_columns].isna().any().any():
        raise ValueError(
            "Missing indicator percentiles in baseline."
        )

    baseline["baseline_rank"] = pd.to_numeric(
        baseline["rank"],
        errors="coerce"
    )

    # Reproducible Dirichlet simulations.
    rng = np.random.default_rng(SEED)

    alpha = BASE_WEIGHTS * CONCENTRATION

    weight_draws = rng.dirichlet(
        alpha,
        size=DRAWS
    )

    percentile_matrix = baseline[
        percentile_columns
    ].to_numpy(dtype=float)

    number_of_wards = len(baseline)

    rank_matrix = np.zeros(
        (DRAWS, number_of_wards),
        dtype=float
    )

    draw_records = []

    for draw_number, weights in enumerate(
        weight_draws,
        start=1
    ):

        scores = percentile_matrix @ weights

        ranks = (
            pd.Series(scores)
            .rank(
                method="min",
                ascending=False
            )
            .to_numpy()
        )

        rank_matrix[draw_number - 1] = ranks

        tau = calculate_kendall(
            baseline["baseline_rank"],
            pd.Series(
                ranks,
                index=baseline.index
            )
        )

        draw_records.append({
            "draw": draw_number,
            "I1_weight": weights[0],
            "I2_weight": weights[1],
            "I3_weight": weights[2],
            "I4_weight": weights[3],
            "kendall_tau_vs_baseline": tau,
        })

    # Summarize each ward's rank distribution.
    rank_summary = baseline[
        [
            "ward_id",
            "ward_name",
            "baseline_rank"
        ]
    ].copy()

    rank_summary["rank_min"] = (
        rank_matrix.min(axis=0)
    )

    rank_summary["rank_p05"] = (
        np.percentile(
            rank_matrix,
            5,
            axis=0
        )
    )

    rank_summary["rank_median"] = (
        np.median(
            rank_matrix,
            axis=0
        )
    )

    rank_summary["rank_p95"] = (
        np.percentile(
            rank_matrix,
            95,
            axis=0
        )
    )

    rank_summary["rank_max"] = (
        rank_matrix.max(axis=0)
    )

    rank_summary["mean_rank"] = (
        rank_matrix.mean(axis=0)
    )

    rank_summary["top_10_frequency_pct"] = (
        (rank_matrix <= 10).mean(axis=0) * 100
    )

    rank_summary.to_csv(
        OUTPUT_DIR / "weight_sensitivity.csv",
        index=False
    )

    pd.DataFrame(draw_records).to_csv(
        OUTPUT_DIR / "weight_draws.csv",
        index=False
    )

    tau_values = [
        row["kendall_tau_vs_baseline"]
        for row in draw_records
    ]

    print("Baseline ranked wards:", number_of_wards)
    print("Simulations:", DRAWS)
    print("Dirichlet alpha:", alpha.tolist())

    print(
        "Mean Kendall tau:",
        round(float(np.nanmean(tau_values)), 6)
    )

    print(
        "Minimum Kendall tau:",
        round(float(np.nanmin(tau_values)), 6)
    )

    print(
        "Maximum Kendall tau:",
        round(float(np.nanmax(tau_values)), 6)
    )

    print(
        "Saved:",
        OUTPUT_DIR / "weight_sensitivity.csv"
    )

    return baseline


# ==================================================
# 4. PART B: A7 PARAMETER SENSITIVITY
# ==================================================

def run_a7_sensitivity(baseline):

    print("\n" + "=" * 55)
    print("D4 PART B: A7 PARAMETER SENSITIVITY")
    print("=" * 55)

    d1 = pd.read_csv(D1_PATH)

    d1["ward_id"] = (
        d1["ward_id"].astype("string")
    )

    baseline = baseline.copy()

    baseline["ward_id"] = (
        baseline["ward_id"].astype("string")
    )

    # Fixed comparison population:
    # the 245 wards in the baseline D3 index.
    baseline_ids = set(
        baseline["ward_id"].dropna()
    )

    base_columns = [
        "ward_id",
        "ward_name",
        "n_buildings",
        "gw_stage_pct",
    ]

    ward_base = d1[base_columns].copy()

    ward_base["n_buildings"] = pd.to_numeric(
        ward_base["n_buildings"],
        errors="coerce"
    )

    ward_base["gw_stage_pct"] = pd.to_numeric(
        ward_base["gw_stage_pct"],
        errors="coerce"
    )

    with open(
        A7_SUMMARY,
        "r",
        encoding="utf-8"
    ) as file:

        summary = json.load(file)

    experiments = summary.get("experiments", [])

    if len(experiments) != 9:
        raise ValueError(
            f"Expected 9 A7 experiments, found {len(experiments)}."
        )

    variant_summaries = []
    all_variant_ranks = []

    for experiment in experiments:

        relative_path = experiment["output"]

        parquet_path = A7_ROOT / relative_path

        print("\nProcessing:", relative_path)

        if not parquet_path.exists():
            raise FileNotFoundError(parquet_path)

        metrics = pd.read_parquet(
            parquet_path,
            columns=[
                "bldg_id",
                "ward_id",
                "vlm_mm_yr",
                "beta_horizon",
            ]
        )

        metrics["ward_id"] = (
            metrics["ward_id"].astype("string")
        )

        assigned = metrics[
            metrics["ward_id"].notna()
        ].copy()

        # Aggregate building-level measurements.
        grouped = assigned.groupby(
            "ward_id",
            observed=True
        ).agg(

            n_buildings_with_data=(
                "vlm_mm_yr",
                "count"
            ),

            sinking_count=(
                "vlm_mm_yr",
                lambda x: (
                    x < SINKING_THRESHOLD
                ).sum()
            ),

            n_buildings_with_beta=(
                "beta_horizon",
                "count"
            ),

            beta_p90_horizon=(
                "beta_horizon",
                lambda x: x.quantile(0.90)
            ),

        ).reset_index()

        ward_data = ward_base.merge(
            grouped,
            on="ward_id",
            how="left",
            validate="one_to_one"
        )

        count_columns = [
            "n_buildings_with_data",
            "sinking_count",
            "n_buildings_with_beta",
        ]

        ward_data[count_columns] = (
            ward_data[count_columns]
            .fillna(0)
        )

        # VLM coverage.
        ward_data["coverage_pct"] = np.where(
            ward_data["n_buildings"] > 0,

            ward_data["n_buildings_with_data"]
            / ward_data["n_buildings"] * 100,

            0
        )

        # Beta coverage.
        ward_data["beta_coverage_pct"] = np.where(
            ward_data["n_buildings"] > 0,

            ward_data["n_buildings_with_beta"]
            / ward_data["n_buildings"] * 100,

            0
        )

        # I1.
        ward_data["share_sinking_gt4"] = np.where(
            ward_data["n_buildings_with_data"] > 0,

            ward_data["sinking_count"]
            / ward_data["n_buildings_with_data"],

            np.nan
        )

        # Preserve the official VLM eligibility rule.
        ward_data["status"] = np.where(

            (ward_data["n_buildings"] > 0)
            & (
                ward_data["coverage_pct"]
                >= COVERAGE_MIN
            ),

            "ranked",
            "insufficient_data"
        )

        # Count every eligible ward before restricting
        # the comparison to the baseline population.
        eligible_all = ward_data[
            ward_data["status"].eq("ranked")
        ].copy()

        eligible_count = len(eligible_all)

        # Restrict comparison to identical baseline wards.
        eligible = eligible_all[
            eligible_all["ward_id"].isin(
                baseline_ids
            )
        ].copy()

        # Percentiles must be calculated on the same
        # 245-ward comparison population for every variant.
        if len(eligible) > 0:

            eligible = calculate_percentiles(
                eligible
            )

            eligible = calculate_index_scores(
                eligible
            )

            eligible["radius_m"] = (
                experiment["radius_m"]
            )

            eligible["pair_min_m"] = (
                experiment["pair_min_m"]
            )

            eligible["pair_max_m"] = (
                experiment["pair_max_m"]
            )

            eligible["params_hash"] = (
                experiment["params_hash"]
            )

            all_variant_ranks.append(eligible)

        # Common comparison population.
        common_ids = set(
            eligible["ward_id"]
        ) & baseline_ids

        # Baseline and variant scores are compared
        # on exactly the same ward IDs.
        if len(common_ids) >= 2:

            base_common = baseline[
                baseline["ward_id"].isin(common_ids)
            ].copy()

            variant_common = eligible[
                eligible["ward_id"].isin(common_ids)
            ].copy()

            base_common = base_common.sort_values(
                "ward_id"
            )

            variant_common = variant_common.sort_values(
                "ward_id"
            )

            tau = calculate_kendall(
                base_common["score"],
                variant_common["score"]
            )

        else:
            tau = np.nan

        # Check the baseline-equivalent A7 configuration.
        is_baseline_variant = (
            experiment["radius_m"] == 100
            and experiment["pair_min_m"] == 80
            and experiment["pair_max_m"] == 120
        )

        max_score_difference = np.nan

        if is_baseline_variant and len(eligible):

            check = baseline[
                ["ward_id", "score"]
            ].merge(
                eligible[
                    ["ward_id", "score"]
                ],
                on="ward_id",
                how="inner",
                suffixes=("_baseline", "_variant")
            )

            if len(check):

                max_score_difference = (
                    check["score_baseline"]
                    - check["score_variant"]
                ).abs().max()

        variant_summaries.append({

            "radius_m": experiment["radius_m"],

            "pair_min_m": experiment["pair_min_m"],

            "pair_max_m": experiment["pair_max_m"],

            "rows": experiment["rows"],

            "citywide_vlm_share": (
                experiment["non_null_vlm_share"]
            ),

            "ranked_wards": eligible_count,

            "insufficient_wards": (
                len(ward_data) - eligible_count
            ),

            "comparison_wards": len(eligible),

            "common_wards_vs_baseline": len(common_ids),

            "kendall_tau_vs_baseline": tau,

            "baseline_score_max_abs_difference": (
                max_score_difference
            ),

            "params_hash": experiment["params_hash"],

        })

        print("Eligible wards:", eligible_count)

        print(
            "Wards in common comparison:",
            len(eligible)
        )

        print(
            "Kendall tau:",
            tau
        )

        if is_baseline_variant:

            print(
                "Baseline maximum score difference:",
                max_score_difference
            )

    # Save A7 summary.
    pd.DataFrame(
        variant_summaries
    ).to_csv(
        OUTPUT_DIR / "a7_variant_summary.csv",
        index=False
    )

    # Save ward-level ranks for every comparable variant.
    if all_variant_ranks:

        combined = pd.concat(
            all_variant_ranks,
            ignore_index=True
        )

        combined.to_csv(
            OUTPUT_DIR / "a7_variant_ward_ranks.csv",
            index=False
        )

    return variant_summaries


# ==================================================
# 5. MAIN EXECUTION
# ==================================================

def main():

    print("\n" + "=" * 55)
    print("DELHI D4 SENSITIVITY ANALYSIS")
    print("=" * 55)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    required_paths = [
        D1_PATH,
        D3_PATH,
        A7_SUMMARY,
    ]

    for path in required_paths:

        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    # Part A.
    baseline = run_weight_sensitivity()

    # Part B.
    variant_summaries = run_a7_sensitivity(
        baseline
    )

    # Final report.
    report = {

        "analysis": "D4 sensitivity analysis",

        "draws": DRAWS,

        "dirichlet_concentration": CONCENTRATION,

        "seed": SEED,

        "baseline_weights": {
            name: float(weight)
            for name, weight in zip(
                INDICATOR_NAMES,
                BASE_WEIGHTS
            )
        },

        "coverage_min_pct": COVERAGE_MIN,

        "baseline_wards": len(baseline),

        "a7_experiment_count": len(
            variant_summaries
        ),

        "comparison_method": (
            "A7 variant percentiles and Kendall correlations "
            "are calculated using the same baseline-eligible "
            "ward population."
        ),

        "outputs": [

            "weight_sensitivity.csv",

            "weight_draws.csv",

            "a7_variant_summary.csv",

            "a7_variant_ward_ranks.csv",

            "d4_summary.json",

        ],

        "limitations": [

            "A7 variants are parameter sensitivity experiments, "
            "not independent observations or confidence intervals.",

            "Variants with insufficient VLM coverage are not ranked.",

            "The 50m variants may have no eligible wards.",

            "A7 results are restricted to the baseline-eligible "
            "ward population for comparable ranking.",

            "Beta coverage is reported separately and missing "
            "beta measurements are not replaced with zero.",

        ],

    }

    with open(
        OUTPUT_DIR / "d4_summary.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            report,
            file,
            indent=2
        )

    print("\n" + "=" * 55)
    print("D4 SENSITIVITY ANALYSIS COMPLETED")
    print("=" * 55)

    print(
        "Output directory:",
        OUTPUT_DIR.resolve()
    )

    print("\nGenerated files:")

    for path in sorted(OUTPUT_DIR.iterdir()):

        if path.is_file():
            print(
                path.name,
                "-",
                path.stat().st_size,
                "bytes"
            )


if __name__ == "__main__":
    main()
