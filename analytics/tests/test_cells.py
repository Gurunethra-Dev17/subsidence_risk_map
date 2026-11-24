import pandas as pd
import pytest
from shapely.geometry import box, mapping

from analytics import export
from analytics.cells import D3Error, compute_cell_index


def _config():
    return {
        "contract": "C6@1.0",
        "params": {"cell_min_buildings": 5, "sinking_threshold_mm_yr": -4},
        "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15},
    }


def _grid():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"cell_id": f"c{i}", "ward_id": "w1"},
                "geometry": mapping(box(i, 0, i + 1, 1)),
            }
            for i in range(4)
        ]
        + [
            {
                "type": "Feature",
                "properties": {"cell_id": "c4", "ward_id": None},
                "geometry": mapping(box(4, 0, 5, 1)),
            }
        ],
    }


def _aggregates():
    return pd.DataFrame(
        {
            "cell_id": ["c0", "c1", "c2", "c3"],
            "n_buildings": [5, 5, 4, 7],
            "n_buildings_with_data": [5, 4, 3, 7],
            "sinking_count": [1, 2, 1, 3],
            "vlm_median_mm_yr": [-1.0, -2.0, -3.0, -4.0],
            "beta_p90_horizon": [0.001, 0.002, 0.003, None],
        }
    )


def test_complete_grid_empty_cells_suppression_and_d8_contract():
    result = compute_cell_index(_aggregates(), _grid(), _config())
    assert len(result) == 5
    assert set(result.cell_id) == {f"c{i}" for i in range(5)}
    assert result.cell_id.is_unique
    indexed = result.set_index("cell_id")
    assert indexed.loc["c4", "n_buildings"] == 0
    assert bool(indexed.loc["c4", "suppressed"])
    assert indexed.loc["c2", "vlm_median_mm_yr"] != indexed.loc["c2", "vlm_median_mm_yr"]
    assert indexed.loc["c0", "beta_p90_horizon"] == 0.001
    assert indexed.loc["c0", "cell_rank_in_ward"] == 3
    assert indexed.loc["c1", "cell_rank_in_ward"] == 1
    rows = result.astype(object).where(pd.notna(result), "").to_dict("records")
    payload = export.build_cell_scores(rows, _grid())
    assert len(payload["features"]) == 5
    suppressed = [
        feature["properties"]
        for feature in payload["features"]
        if feature["properties"]["suppressed"]
    ]
    assert all(
        all(
            item[field] is None
            for field in (
                "vlm_median_mm_yr",
                "beta_p90_horizon",
                "share_sinking_gt4",
                "cell_score",
                "cell_rank_in_ward",
            )
        )
        for item in suppressed
    )


def test_cell_ranks_are_contiguous_with_stable_tie_break_and_order_independent():
    rows = _aggregates().iloc[:2].copy()
    rows.loc[:, "n_buildings"] = 5
    rows.loc[:, "n_buildings_with_data"] = 5
    rows.loc[:, "sinking_count"] = 2
    rows.loc[:, "vlm_median_mm_yr"] = -1
    rows.loc[:, "beta_p90_horizon"] = 0.001
    grid = {"type": "FeatureCollection", "features": _grid()["features"][:2]}
    expected = compute_cell_index(rows, grid, _config()).sort_values("cell_rank_in_ward")
    assert expected.cell_id.tolist() == ["c0", "c1"]
    assert expected.cell_rank_in_ward.astype(int).tolist() == [1, 2]
    actual = compute_cell_index(rows.iloc[::-1], grid, _config()).sort_values("cell_rank_in_ward")
    assert actual.cell_id.tolist() == expected.cell_id.tolist()


def test_unknown_duplicate_or_malformed_cell_ids_are_rejected():
    with pytest.raises(D3Error, match="duplicate cell IDs"):
        compute_cell_index(
            pd.concat([_aggregates(), _aggregates().iloc[[0]]], ignore_index=True),
            _grid(),
            _config(),
        )
    duplicate_grid = _grid()
    duplicate_grid["features"].append(duplicate_grid["features"][0])
    with pytest.raises(D3Error, match="unique cell IDs"):
        compute_cell_index(_aggregates(), duplicate_grid, _config())
    with pytest.raises(D3Error, match="FeatureCollection"):
        compute_cell_index(_aggregates(), {"type": "Feature"}, _config())


def test_configured_suppression_threshold_must_match_frozen_requirement():
    cfg = _config()
    cfg["params"]["cell_min_buildings"] = 4
    with pytest.raises(D3Error, match="requires params.cell_min_buildings = 5"):
        compute_cell_index(_aggregates(), _grid(), cfg)


def test_duckdb_aggregate_uses_synthetic_parquet_without_python_row_materialization(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from analytics.cells import aggregate_c1, audit_cell_ward_assignments

    path = tmp_path / "synthetic-c1.parquet"
    table = pa.table(
        {
            "bldg_id": ["a", "b", "c", "d"],
            "ward_id": ["w1", "w1", "w1", None],
            "cell_id": ["c0", "c0", "c1", None],
            "vlm_mm_yr": [-5.0, None, -2.0, -8.0],
            "beta_horizon": [0.001, 0.003, None, 0.004],
        }
    )
    pq.write_table(table, path)
    result, qa = aggregate_c1(path, -4)
    values = result.set_index("cell_id")
    assert values.loc["c0", "n_buildings"] == 2
    assert values.loc["c0", "n_buildings_with_data"] == 1
    assert values.loc["c0", "sinking_count"] == 1
    assert values.loc["c0", "beta_p90_horizon"] == pytest.approx(0.0028)
    assert qa["unassigned_cell_rows"] == 1
    assert qa["c1_rows"] == 4
    ward_qa = audit_cell_ward_assignments(path, {"c0": "w2", "c1": "w1"})
    assert ward_qa["cells_with_any_non_grid_ward_assignment"] == 1
    assert ward_qa["building_rows_assigned_to_non_grid_ward"] == 2
    assert ward_qa["cells_where_largest_c1_ward_group_differs_from_grid"] == 1
