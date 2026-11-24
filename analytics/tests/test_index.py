import pandas as pd
import pytest

from analytics.index import D3Error, compute_index, merge_groundwater


def _config():
    return {
        "contract": "C6@1.0",
        "params": {"coverage_min": 0.5, "sinking_threshold_mm_yr": -4},
        "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15},
    }


def _rows():
    return pd.DataFrame(
        {
            "ward_id": ["w3", "w1", "w2", "w4"],
            "ward_name": ["Gamma", "Alpha", "Beta", "Low"],
            "status": ["ranked", "ranked", "ranked", "insufficient_data"],
            "n_buildings": [30, 10, 20, 10],
            "n_buildings_with_data": [30, 10, 20, 4],
            "coverage_pct": [100, 100, 100, 40],
            "share_sinking_gt4": [0.3, 0.1, 0.2, 0.0],
            "beta_p90_horizon": [0.003, 0.001, 0.002, 0.004],
            "gw_stage_pct": [None, None, None, None],
            "gw_category": [None, None, None, None],
            "flags": ["[]", "[]", "[]", "[]"],
        }
    )


def test_percentiles_weights_fallback_and_score_bounds():
    result = compute_index(_rows(), _config()).set_index("ward_id")
    assert result.loc["w1", "i1_percentile"] == pytest.approx(100 / 3)
    assert result.loc["w3", "i2_percentile"] == 100
    assert result.loc["w1", "score"] == pytest.approx(100 / 3)
    assert result.loc["w1", "gw_stage_pct"] is None or pd.isna(result.loc["w1", "gw_stage_pct"])
    assert result.loc["w1", "effective_weight_i4"] == 0
    assert result.loc["w1", "flags"] == ["groundwater_missing"]
    assert result.loc["w4", "score"] is pd.NA or pd.isna(result.loc["w4", "score"])
    assert result.score.dropna().between(0, 100).all()


def test_equal_scores_receive_unique_contiguous_stable_ranks():
    rows = _rows().iloc[:3].copy()
    rows[["share_sinking_gt4", "beta_p90_horizon", "n_buildings"]] = [0.5, 0.001, 10]
    rows["n_buildings_with_data"] = 10
    rows["coverage_pct"] = 100
    result = compute_index(rows, _config()).sort_values("rank")
    assert result.ward_id.tolist() == ["w1", "w2", "w3"]
    assert result["rank"].astype(int).tolist() == [1, 2, 3]
    shuffled = compute_index(rows.sample(frac=1, random_state=7), _config()).sort_values("rank")
    assert shuffled.ward_id.tolist() == result.ward_id.tolist()


def test_coverage_threshold_keeps_ineligible_score_and_rank_null():
    result = compute_index(_rows(), _config()).set_index("ward_id")
    assert result.loc["w4", "status"] == "insufficient_data"
    assert pd.isna(result.loc["w4", "score"])
    assert pd.isna(result.loc["w4", "rank"])
    assert "low_coverage" in result.loc["w4", "flags"]


def test_duplicate_wards_and_bad_coverage_are_rejected():
    rows = _rows()
    rows.loc[1, "ward_id"] = rows.loc[0, "ward_id"]
    with pytest.raises(D3Error, match="unique"):
        compute_index(rows, _config())
    rows = _rows()
    rows.loc[0, "coverage_pct"] = 55
    with pytest.raises(D3Error, match="does not agree"):
        compute_index(rows, _config())


def test_groundwater_join_requires_exact_unique_ward_set_and_preserves_nulls():
    wards = _rows().drop(columns=["gw_stage_pct", "gw_category"])
    groundwater = pd.DataFrame(
        {
            "ward_id": wards.ward_id,
            "gw_stage_pct": [None] * len(wards),
            "gw_category": [None] * len(wards),
        }
    )
    result = merge_groundwater(wards, groundwater)
    assert result.gw_stage_pct.isna().all()
    with pytest.raises(D3Error, match="sets differ"):
        merge_groundwater(wards, groundwater.iloc[:-1])
    duplicate = pd.concat([groundwater, groundwater.iloc[[0]]], ignore_index=True)
    with pytest.raises(D3Error, match="unique"):
        merge_groundwater(wards, duplicate)


def test_missing_indicator_is_excluded_and_remaining_weights_renormalize():
    rows = _rows().iloc[:3].copy()
    rows["share_sinking_gt4"] = None
    result = compute_index(rows, _config())
    assert result.i1_percentile.isna().all()
    assert result.effective_weight_i1.eq(0).all()
    assert result.effective_weight_i2.add(result.effective_weight_i3).tolist() == pytest.approx(
        [1] * len(result)
    )
