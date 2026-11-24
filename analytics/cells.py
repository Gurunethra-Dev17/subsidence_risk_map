
import pandas as pd
from pathlib import Path


def compute_cell_index(metrics):
    """
    Calculate a provisional 250m Cell Inspection Index.

    I1: Share of buildings sinking faster than 4 mm/year (weight 0.30).
    I2: Unavailable; excluded.
    I3: Building count (weight 0.20).

    Original weights are renormalised using available indicators.
    Cells with fewer than 5 buildings are suppressed.
    Cells with dominant ward share below 50% are marked ambiguous.
    Cell ranks are calculated within each ward.
    """

    required = ["bldg_id", "cell_id", "ward_id", "vlm_mm_yr"]

    for col in required:
        if col not in metrics.columns:
            raise ValueError(f"Missing required column: {col}")

    df = metrics[metrics["cell_id"].notna()].copy()

    # Aggregate building metrics by cell.
    cells = df.groupby("cell_id").agg(
        n_buildings=("bldg_id", "count"),
        n_buildings_with_data=("vlm_mm_yr", "count"),
        sinking_count=("vlm_mm_yr", lambda x: (x < -4).sum())
    ).reset_index()

    # Calculate I1.
    cells["share_sinking_gt4"] = (
        cells["sinking_count"] / cells["n_buildings_with_data"]
    ).where(cells["n_buildings_with_data"] > 0)

    # Find the dominant ward for every cell.
    ward_counts = (
        df[df["ward_id"].notna()]
        .groupby(["cell_id", "ward_id"])
        .size()
        .reset_index(name="ward_buildings")
    )

    ward_counts["total_assigned"] = (
        ward_counts.groupby("cell_id")["ward_buildings"]
        .transform("sum")
    )

    ward_counts["dominant_ward_share"] = (
        ward_counts["ward_buildings"] /
        ward_counts["total_assigned"]
    )

    dominant = (
        ward_counts.sort_values(
            ["cell_id", "ward_buildings", "ward_id"],
            ascending=[True, False, True]
        )
        .drop_duplicates("cell_id")
        [["cell_id", "ward_id", "dominant_ward_share"]]
    )

    cells = cells.merge(dominant, on="cell_id", how="left")

    # Determine cell eligibility.
    cells["status"] = "eligible"

    cells.loc[
        cells["n_buildings"] < 5, "status"
    ] = "suppressed_low_buildings"

    cells.loc[
        (cells["n_buildings"] >= 5) &
        (cells["dominant_ward_share"] < 0.50),
        "status"
    ] = "ambiguous_ward"

    # Calculate percentile indicators among eligible cells.
    eligible = cells["status"].eq("eligible")

    cells["I1_percentile"] = pd.NA
    cells["I3_percentile"] = pd.NA

    valid_i1 = eligible & cells["share_sinking_gt4"].notna()

    cells.loc[valid_i1, "I1_percentile"] = (
        cells.loc[valid_i1, "share_sinking_gt4"]
        .rank(method="average", pct=True) * 100
    )

    cells.loc[eligible, "I3_percentile"] = (
        cells.loc[eligible, "n_buildings"]
        .rank(method="average", pct=True) * 100
    )

    # Calculate provisional scores with available indicators.
    weights = {"I1_percentile": 0.30, "I3_percentile": 0.20}

    weighted_total = pd.Series(0.0, index=cells.index)
    available_weight = pd.Series(0.0, index=cells.index)

    for column, weight in weights.items():
        values = pd.to_numeric(cells[column], errors="coerce")
        valid = eligible & values.notna()

        weighted_total.loc[valid] += values.loc[valid] * weight
        available_weight.loc[valid] += weight

    cells["score"] = pd.NA

    can_score = eligible & (available_weight > 0)

    cells.loc[can_score, "score"] = (
        weighted_total.loc[can_score] /
        available_weight.loc[can_score]
    )

    # Rank cells within their dominant ward.
    cells["cell_rank_in_ward"] = pd.NA

    ranked = cells[can_score].copy()

    ranked["cell_rank_in_ward"] = (
        ranked.groupby("ward_id")["score"]
        .rank(method="min", ascending=False)
        .astype("Int64")
    )

    cells.loc[
        ranked.index, "cell_rank_in_ward"
    ] = ranked["cell_rank_in_ward"]

    # Explicitly identify provisional results.
    cells["index_type"] = "provisional"
    cells["excluded_indicator"] = "I2"
    cells["used_indicators"] = "I1,I3"

    cells["flags"] = ""

    cells.loc[
        cells["status"] == "suppressed_low_buildings", "flags"
    ] = "fewer_than_5_buildings"

    cells.loc[
        cells["status"] == "ambiguous_ward", "flags"
    ] = "dominant_ward_share_below_50_percent"

    cells.loc[
        cells["status"] == "eligible", "flags"
    ] = "i2_unavailable_provisional"

    return cells


if __name__ == "__main__":

    input_path = Path("data/building_metrics.parquet")
    output_path = Path("out/d3/cell_inspection_index.csv")

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    metrics = pd.read_parquet(input_path)

    result = compute_cell_index(metrics)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)

    print("\nD3 Cell Inspection Index completed.")
    print("Index type: PROVISIONAL (I2 unavailable)")
    print("Total cells:", len(result))
    print("Eligible cells:", (result["status"] == "eligible").sum())
    print("Suppressed cells:",
          (result["status"] == "suppressed_low_buildings").sum())
    print("Ambiguous cells:",
          (result["status"] == "ambiguous_ward").sum())
    print("Ranked cells:", result["cell_rank_in_ward"].notna().sum())
    print("Output:", output_path)

    print("\nTop 10 ranked cells:")
    print(
        result[result["cell_rank_in_ward"].notna()]
        .sort_values(["ward_id", "cell_rank_in_ward"])
        [["cell_id", "ward_id", "score", "cell_rank_in_ward"]]
        .head(10)
        .to_string(index=False)
    )
