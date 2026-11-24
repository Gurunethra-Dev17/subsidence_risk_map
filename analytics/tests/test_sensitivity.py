import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from analytics.index import D3Error, compute_index, merge_groundwater
from analytics.sensitivity import (
    D4Error,
    _rank_scores,
    _variant_indicators,
    aggregate_variant,
    calculate_kendall,
    compute_weight_sensitivity,
    sample_weight_draws,
)

WEIGHTS = {"i1": 0.30, "i2": 0.35, "i3": 0.20, "i4": 0.15}
CONFIG = {
    "contract": "C6@1.0",
    "city": "delhi",
    "seed": 42,
    "params": {
        "coverage_min": 0.5,
        "sens_draws": 500,
        "sens_concentration": 50,
        "sinking_threshold_mm_yr": -4,
    },
    "weights": WEIGHTS,
}


def _inputs():
    d1 = pd.DataFrame(
        {
            "ward_id": ["w1", "w2", "w3", "w4"],
            "ward_name": ["Alpha", "Beta", "Gamma", "Low"],
            "status": ["ranked", "ranked", "ranked", "insufficient_data"],
            "n_buildings": [10, 10, 10, 10],
            "n_buildings_with_data": [8, 7, 9, 2],
            "coverage_pct": [80, 70, 90, 20],
            "share_sinking_gt4": [0.1, 0.3, 0.2, 0.5],
            "vlm_median_mm_yr": [-2.0, -5.0, -4.0, -8.0],
            "beta_p90_horizon": [0.001, 0.003, 0.002, 0.004],
            "gw_stage_pct": [None] * 4,
            "gw_category": [None] * 4,
            "flags": [[], [], [], ["low_coverage"]],
        }
    )
    groundwater = pd.DataFrame(
        {
            "ward_id": d1.ward_id,
            "gw_stage_pct": [None] * 4,
            "gw_category": [None] * 4,
        }
    )
    return d1, groundwater


def _baseline():
    d1, groundwater = _inputs()
    return compute_index(merge_groundwater(d1, groundwater), CONFIG)


def test_dirichlet_draws_are_seeded_valid_and_sum_to_one():
    first = sample_weight_draws(WEIGHTS)
    second = sample_weight_draws(WEIGHTS)
    assert first.shape == (500, 4)
    assert np.array_equal(first, second)
    assert np.isfinite(first).all()
    assert (first >= 0).all()
    assert np.allclose(first.sum(axis=1), 1)


def test_weight_sensitivity_preserves_groundwater_fallback_and_all_wards():
    baseline = _baseline()
    output, qa = compute_weight_sensitivity(baseline, WEIGHTS)
    assert len(output) == 4
    assert output.ward_id.tolist() == baseline.ward_id.tolist()
    assert qa["draws_completed"] == 500
    assert qa["dirichlet_alpha"] == pytest.approx({"i1": 15, "i2": 17.5, "i3": 10, "i4": 7.5})
    assert "I4 remains unavailable" in qa["groundwater_fallback"]
    assert output.loc[output.status.eq("ranked"), "rank_p05"].notna().all()
    assert output.loc[output.status.eq("ranked"), "rank_p95"].notna().all()
    assert output.loc[output.status.eq("insufficient_data"), "rank_p05"].isna().all()
    assert output.loc[output.status.eq("insufficient_data"), "rank_p95"].isna().all()


def test_intervals_are_integer_outward_rounded_and_include_baseline_rank():
    baseline = _baseline()
    output, _ = compute_weight_sensitivity(baseline, WEIGHTS, draws=40, seed=19)
    ranked = output.loc[output.status.eq("ranked")]
    for row in ranked.itertuples():
        assert isinstance(row.rank_p05, (int, np.integer))
        assert isinstance(row.rank_p95, (int, np.integer))
        assert row.rank_p05 <= row.rank <= row.rank_p95
        assert 1 <= row.rank_p05 <= row.rank_p95 <= len(ranked)
    assert ranked.rank_p05_empirical_linear.notna().all()
    assert ranked.rank_p95_empirical_linear.notna().all()


def test_tied_scores_use_stable_ward_id_order_without_score_perturbation():
    assert _rank_scores(np.array([10.0, 10.0, 20.0]), ["w2", "w1", "w3"]).tolist() == [3, 2, 1]


def test_weight_draw_reproduces_unperturbed_baseline_when_weights_equal_center():
    baseline = _baseline()
    eligible = baseline.loc[baseline.status.eq("ranked")].copy()
    matrix = eligible[
        ["i1_percentile", "i2_percentile", "i3_percentile", "i4_percentile"]
    ].to_numpy(dtype=float)
    weights = np.asarray([WEIGHTS[key] for key in ("i1", "i2", "i3", "i4")])
    available = np.isfinite(matrix)
    score = np.nansum(matrix * weights, axis=1) / (available * weights).sum(axis=1)
    ranks = _rank_scores(score, eligible.ward_id.astype(str).tolist())
    assert score == pytest.approx(eligible.score.to_numpy(dtype=float))
    assert ranks.tolist() == eligible["rank"].astype(int).tolist()


def test_kendall_uses_common_population_and_marks_too_small_as_unavailable():
    assert calculate_kendall(pd.Series([1, 2, 3]), pd.Series([1, 2, 3])) == pytest.approx(1)
    assert calculate_kendall(pd.Series([1]), pd.Series([1])) is None
    assert calculate_kendall(pd.Series([], dtype=float), pd.Series([], dtype=float)) is None
    assert calculate_kendall(pd.Series([1, np.nan]), pd.Series([1, 2])) is None


def test_sensitivity_rejects_missing_or_noncontiguous_baseline_ranks():
    baseline = _baseline()
    baseline.loc[baseline.ward_id.eq("w1"), "rank"] = 8
    with pytest.raises(D4Error, match="contiguous"):
        compute_weight_sensitivity(baseline, WEIGHTS)


def test_sensitivity_rejects_duplicate_ward_ids():
    baseline = pd.concat([_baseline(), _baseline().iloc[[0]]], ignore_index=True)
    with pytest.raises(D4Error, match="unique"):
        compute_weight_sensitivity(baseline, WEIGHTS)


def test_a7_duckdb_aggregate_is_bounded_and_reports_variant_measurements(tmp_path):
    source = tmp_path / "variant.parquet"
    pq.write_table(
        pa.table(
            {
                "bldg_id": ["a", "b", "c", "d"],
                "ward_id": ["w1", "w1", "w2", None],
                "vlm_mm_yr": [-5.0, None, -2.0, -8.0],
                "beta_horizon": [0.001, 0.003, None, 0.004],
            }
        ),
        source,
    )
    grouped, totals = aggregate_variant(source, -4)
    result = grouped.set_index("ward_id")
    assert result.loc["w1", "n_buildings"] == 2
    assert result.loc["w1", "n_buildings_with_data"] == 1
    assert result.loc["w1", "sinking_count"] == 1
    assert result.loc["w1", "beta_p90_horizon"] == pytest.approx(0.0028)
    assert totals == {
        "rows": 4,
        "unassigned_ward_rows": 1,
        "non_null_vlm": 3,
        "non_null_beta": 3,
    }


@pytest.mark.parametrize("building_ids", [["a", "a"], ["a", None]])
def test_variant_aggregate_rejects_duplicate_or_null_building_ids(tmp_path, building_ids):
    source = tmp_path / "duplicate.parquet"
    pq.write_table(
        pa.table(
            {
                "bldg_id": building_ids,
                "ward_id": ["w1", "w2"],
                "vlm_mm_yr": [-1.0, -2.0],
                "beta_horizon": [None, None],
            }
        ),
        source,
    )
    with pytest.raises(D4Error, match="non-null and unique"):
        aggregate_variant(source, -4)


def test_variant_aggregate_rejects_missing_required_columns(tmp_path):
    source = tmp_path / "incomplete.parquet"
    pq.write_table(pa.table({"bldg_id": ["a"], "ward_id": ["w1"]}), source)
    with pytest.raises(D4Error, match="lacks required"):
        aggregate_variant(source, -4)


def test_variant_coverage_is_recomputed_from_each_variants_measurements():
    ward_base = pd.DataFrame(
        {
            "ward_id": ["w1", "w2"],
            "ward_name": ["Alpha", "Beta"],
            "n_buildings": [10, 10],
        }
    )
    groundwater = pd.DataFrame(
        {
            "ward_id": ["w1", "w2"],
            "gw_stage_pct": [None, None],
            "gw_category": [None, None],
        }
    )
    grouped = pd.DataFrame(
        {
            "ward_id": ["w1", "w2"],
            "n_buildings": [10, 10],
            "n_buildings_with_data": [4, 8],
            "sinking_count": [1, 2],
            "n_buildings_with_beta": [2, 5],
            "vlm_median_mm_yr": [-3.0, -5.0],
            "beta_p90_horizon": [0.001, 0.003],
        }
    )
    result = _variant_indicators(grouped, ward_base, groundwater, CONFIG).set_index("ward_id")
    assert result.loc["w1", "coverage_pct"] == pytest.approx(40)
    assert result.loc["w1", "status"] == "insufficient_data"
    assert result.loc["w2", "coverage_pct"] == pytest.approx(80)
    assert result.loc["w2", "status"] == "ranked"


def test_variant_indicators_reject_unknown_or_duplicate_wards():
    ward_base = pd.DataFrame({"ward_id": ["w1"], "ward_name": ["Alpha"], "n_buildings": [2]})
    groundwater = pd.DataFrame({"ward_id": ["w1"], "gw_stage_pct": [None], "gw_category": [None]})
    grouped = pd.DataFrame(
        {
            "ward_id": ["unknown"],
            "n_buildings": [1],
            "n_buildings_with_data": [1],
            "sinking_count": [0],
            "n_buildings_with_beta": [0],
            "vlm_median_mm_yr": [-1.0],
            "beta_p90_horizon": [None],
        }
    )
    with pytest.raises(D4Error, match="unknown ward IDs"):
        _variant_indicators(grouped, ward_base, groundwater, CONFIG)
    duplicate = pd.concat(
        [grouped.assign(ward_id="w1"), grouped.assign(ward_id="w1")], ignore_index=True
    )
    with pytest.raises(D4Error, match="duplicate or unknown"):
        _variant_indicators(duplicate, ward_base, groundwater, CONFIG)


def test_baseline_id_set_mismatch_is_rejected_by_shared_groundwater_join():
    d1, groundwater = _inputs()
    with pytest.raises(D3Error, match="sets differ"):
        merge_groundwater(d1, groundwater.iloc[:-1])
