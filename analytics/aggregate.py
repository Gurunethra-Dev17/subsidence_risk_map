
import pandas as pd


def build_ward_indicators(metrics, wards, groundwater=None, cfg=None):
    """
    Aggregate building-level metrics into ward-level indicators.

    I1: Share of valid VLM observations sinking faster than threshold.
    I2: 90th percentile of available beta_horizon values.
    I3: Number of assigned buildings.
    I4: Groundwater extraction stage.

    Missing measurements are never replaced with zero.
    """

    cfg = cfg or {}

    min_coverage_pct = cfg.get("min_coverage_pct", 50.0)
    sinking_threshold = cfg.get("sinking_threshold_mm_yr", -4.0)

    required_metrics = [
        "bldg_id", "ward_id", "vlm_mm_yr", "beta_horizon", "sparse"
    ]
    required_wards = ["ward_id", "ward_name"]

    for col in required_metrics:
        if col not in metrics.columns:
            raise ValueError(f"Missing metrics column: {col}")

    for col in required_wards:
        if col not in wards.columns:
            raise ValueError(f"Missing wards column: {col}")

    if metrics["bldg_id"].duplicated().any():
        raise ValueError("Duplicate bldg_id values found in metrics")

    if wards["ward_id"].duplicated().any():
        raise ValueError("Duplicate ward_id values found in wards")

    metrics = metrics.copy()
    wards = wards[["ward_id", "ward_name"]].copy()

    metrics["ward_id"] = metrics["ward_id"].astype("string")
    wards["ward_id"] = wards["ward_id"].astype("string")

    assigned = metrics[metrics["ward_id"].notna()].copy()

    invalid_wards = (
        set(assigned["ward_id"].unique())
        - set(wards["ward_id"].unique())
    )

    if invalid_wards:
        raise ValueError(
            f"Building metrics contain unknown ward IDs: {sorted(invalid_wards)}"
        )

    grouped = assigned.groupby("ward_id", observed=True).agg(
        n_buildings=("bldg_id", "size"),
        n_buildings_with_data=("vlm_mm_yr", "count"),
        vlm_median_mm_yr=("vlm_mm_yr", "median"),
        sparse_count=("sparse", "sum"),
        sinking_count=(
            "vlm_mm_yr",
            lambda x: (x < sinking_threshold).sum()
        ),
        n_buildings_with_beta=("beta_horizon", "count"),
        beta_p90_horizon=(
            "beta_horizon",
            lambda x: x.quantile(0.90)
        )
    ).reset_index()

    result = wards.merge(
        grouped,
        on="ward_id",
        how="left",
        validate="one_to_one"
    )

    count_columns = [
        "n_buildings",
        "n_buildings_with_data",
        "sparse_count",
        "sinking_count",
        "n_buildings_with_beta"
    ]

    result[count_columns] = result[count_columns].fillna(0).astype(int)

    has_buildings = result["n_buildings"] > 0

    result["coverage_pct"] = 0.0
    result.loc[has_buildings, "coverage_pct"] = (
        result.loc[has_buildings, "n_buildings_with_data"]
        / result.loc[has_buildings, "n_buildings"] * 100
    )

    result["beta_coverage_pct"] = pd.NA
    result.loc[has_buildings, "beta_coverage_pct"] = (
        result.loc[has_buildings, "n_buildings_with_beta"]
        / result.loc[has_buildings, "n_buildings"] * 100
    )

    result["share_sinking_gt4"] = pd.NA
    has_valid_data = result["n_buildings_with_data"] > 0

    result.loc[has_valid_data, "share_sinking_gt4"] = (
        result.loc[has_valid_data, "sinking_count"]
        / result.loc[has_valid_data, "n_buildings_with_data"]
    )

    result["beta_p90_ratio_horizon"] = pd.NA

    # Retain the existing VLM-based eligibility rule.
    result["status"] = "insufficient_data"
    sufficient = has_buildings & (
        result["coverage_pct"] >= min_coverage_pct
    )
    result.loc[sufficient, "status"] = "ranked"

    flags = []
    for row in result.itertuples():
        row_flags = []

        if row.coverage_pct < min_coverage_pct:
            row_flags.append("low_vlm_coverage")

        if row.sparse_count > 0:
            row_flags.append("sparse_points")

        if row.n_buildings_with_beta == 0:
            row_flags.append("beta_missing")
        

        flags.append(row_flags)

    result["flags"] = flags

    result["gw_stage_pct"] = pd.NA
    result["gw_category"] = pd.NA

    if groundwater is not None:
        required_gw = ["ward_id", "gw_stage_pct", "gw_category"]

        for col in required_gw:
            if col not in groundwater.columns:
                raise ValueError(f"Missing groundwater column: {col}")

        gw = groundwater[required_gw].copy()
        gw["ward_id"] = gw["ward_id"].astype("string")

        if gw["ward_id"].duplicated().any():
            raise ValueError("Duplicate ward IDs in groundwater data")

        result = result.merge(
            gw,
            on="ward_id",
            how="left",
            suffixes=("", "_gw"),
            validate="one_to_one"
        )

        result["gw_stage_pct"] = result["gw_stage_pct_gw"]
        result["gw_category"] = result["gw_category_gw"]
        result = result.drop(
            columns=["gw_stage_pct_gw", "gw_category_gw"]
        )

    for i, row in result.iterrows():
        if pd.isna(row["gw_stage_pct"]):
            result.at[i, "flags"] = (
                row["flags"] + ["groundwater_missing"]
            )

    result["score"] = pd.NA
    result["rank"] = pd.NA
    result["rank_p05"] = pd.NA
    result["rank_p95"] = pd.NA
    result["histogram"] = None

    output_columns = [
        "ward_id", "ward_name", "status",
        "n_buildings", "n_buildings_with_data", "coverage_pct",
        "share_sinking_gt4", "vlm_median_mm_yr",
        "n_buildings_with_beta", "beta_coverage_pct",
        "beta_p90_horizon", "beta_p90_ratio_horizon",
        "gw_stage_pct", "gw_category",
        "score", "rank", "rank_p05", "rank_p95",
        "flags", "histogram"
    ]

    output = result[output_columns].copy()

    output.attrs["unassigned_buildings"] = int(
        metrics["ward_id"].isna().sum()
    )

    return output
