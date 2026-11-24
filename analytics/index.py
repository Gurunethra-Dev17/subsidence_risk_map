
import pandas as pd


def compute_index(indicators, cfg=None):
    """
    Calculate the four-indicator Ward Inspection Index.

    I1: Share of buildings sinking faster than 4 mm/year.
    I2: Ward 90th percentile of beta_horizon.
    I3: Building exposure (number of buildings).
    I4: Groundwater extraction stage.

    Missing indicators are excluded and remaining weights
    are renormalized for each ward.
    """

    cfg = cfg or {}
    result = indicators.copy()

    required = [
        "ward_id",
        "status",
        "share_sinking_gt4",
        "beta_p90_horizon",
        "n_buildings",
        "gw_stage_pct"
    ]

    for col in required:
        if col not in result.columns:
            raise ValueError(f"Missing required column: {col}")

    if result["ward_id"].duplicated().any():
        raise ValueError("Duplicate ward IDs found")

    weights = {
        "I1": 0.30,
        "I2": 0.35,
        "I3": 0.20,
        "I4": 0.15
    }

    indicators_map = {
        "I1": "share_sinking_gt4",
        "I2": "beta_p90_horizon",
        "I3": "n_buildings",
        "I4": "gw_stage_pct"
    }

    eligible = result["status"].eq("ranked")

    # Convert each indicator into a percentile score.
    for name, column in indicators_map.items():
        result[f"{name}_percentile"] = pd.NA

        values = pd.to_numeric(result[column], errors="coerce")
        valid = eligible & values.notna()

        result.loc[valid, f"{name}_percentile"] = (
            values.loc[valid]
            .rank(method="average", pct=True) * 100
        )

    # Calculate weighted scores using available indicators.
    weighted_total = pd.Series(0.0, index=result.index)
    available_weight = pd.Series(0.0, index=result.index)

    for name, weight in weights.items():
        values = pd.to_numeric(
            result[f"{name}_percentile"],
            errors="coerce"
        )

        valid = eligible & values.notna()

        weighted_total.loc[valid] += values.loc[valid] * weight
        available_weight.loc[valid] += weight

    result["available_indicator_weight"] = available_weight

    result["score"] = pd.NA

    can_score = eligible & (available_weight > 0)

    result.loc[can_score, "score"] = (
        weighted_total.loc[can_score]
        / available_weight.loc[can_score]
    )

    # Rank highest-risk wards first.
    result["rank"] = pd.NA

    result.loc[can_score, "rank"] = (
        result.loc[can_score, "score"]
        .rank(method="min", ascending=False)
        .astype("Int64")
    )

    # Remove obsolete provisional flags.
    if "flags" in result.columns:
        result["flags"] = result["flags"].apply(
            lambda x: list(x) if isinstance(x, list) else []
        )

        result["flags"] = result["flags"].apply(
            lambda x: [
                flag for flag in x
                if flag != "i2_unavailable_provisional"
            ]
        )

    result["rank_p05"] = pd.NA
    result["rank_p95"] = pd.NA

    result.attrs["index_type"] = "four_indicator"
    result.attrs["used_indicators"] = ["I1", "I2", "I3", "I4"]
    result.attrs["weights"] = weights

    return result


if __name__ == "__main__":
    from pathlib import Path
    import ast

    input_path = Path("out/d1_revised/ward_indicators.csv")
    output_path = Path("out/d3_revised/ward_inspection_index.csv")

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    indicators = pd.read_csv(input_path)

    if "flags" in indicators.columns:
        indicators["flags"] = indicators["flags"].apply(
            lambda x: ast.literal_eval(x)
            if isinstance(x, str) and x.startswith("[")
            else []
        )

    result = compute_index(indicators)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)

    print("D3 Ward Inspection Index completed.")
    print("Index type: FOUR-INDICATOR")
    print("Weights:", result.attrs["weights"])
    print("Total wards:", len(result))
    print("Ranked wards:", result["rank"].notna().sum())
    print("Unranked wards:", result["rank"].isna().sum())

    print("\nIndicator availability:")
    for name in ["I1", "I2", "I3", "I4"]:
        print(name, ":", result[f"{name}_percentile"].notna().sum())

    print("\nTop 10 wards:")
    print(
        result[result["rank"].notna()]
        .sort_values("rank")[
            ["ward_id", "ward_name", "score", "rank"]
        ]
        .head(10).to_string(index=False)
    )

    print("\nSaved:", output_path)
    print("Original D3 output was not modified.")
