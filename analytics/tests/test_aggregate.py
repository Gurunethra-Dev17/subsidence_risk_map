import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely
from shapely.geometry import Point, Polygon, box

from analytics import aggregate


def _metrics() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bldg_id": ["a1", "a2", "a3", "a4", "b1", "outside"],
            "ward_id": ["w1", "w1", "w1", "w1", "w2", None],
            "vlm_mm_yr": [-4.0, -3.0, None, -6.0, None, -8.0],
            "beta_horizon": [0.001, None, 0.002, None, None, 0.004],
            "sparse": [False, False, True, False, True, False],
        }
    )


def _wards() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ward_id": ["w1", "w2", "w3"],
            "ward_name": ["Alpha", "Beta", "Empty"],
        }
    )


def _config() -> dict:
    return {"params": {"coverage_min": 0.5, "sinking_threshold_mm_yr": -4}}


def test_normal_aggregation_uses_valid_vlm_denominator_and_inclusive_threshold():
    result = aggregate.build_ward_indicators(_metrics(), _wards(), cfg=_config()).set_index(
        "ward_id"
    )

    assert len(result) == 3
    assert result.loc["w1", "n_buildings"] == 4
    assert result.loc["w1", "n_buildings_with_data"] == 3
    assert result.loc["w1", "coverage_pct"] == 75
    assert result.loc["w1", "share_sinking_gt4"] == pytest.approx(2 / 3)
    assert result.loc["w1", "vlm_median_mm_yr"] == -4
    assert result.loc["w1", "beta_p90_horizon"] == pytest.approx(0.0019)
    assert result.loc["w1", "status"] == "ranked"


def test_missing_vlm_beta_and_sparse_are_not_fabricated():
    result = aggregate.build_ward_indicators(_metrics(), _wards(), cfg=_config()).set_index(
        "ward_id"
    )

    assert result.loc["w1", "n_buildings_with_beta"] == 2
    assert result.loc["w1", "beta_coverage_pct"] == 50
    assert result.loc["w1", "n_sparse"] == 1
    assert result.loc["w1", "sparse_pct"] == 25
    assert result.loc["w1", "share_sinking_gt4"] == pytest.approx(2 / 3)
    assert pd.isna(result.loc["w2", "share_sinking_gt4"])
    assert pd.isna(result.loc["w2", "beta_p90_horizon"])
    assert pd.isna(result.loc["w2", "vlm_median_mm_yr"])
    assert "sparse_points" in result.loc["w2", "flags"]
    assert "beta_missing" not in result.loc["w2", "flags"]


def test_empty_ward_and_insufficient_coverage_remain_unranked():
    result = aggregate.build_ward_indicators(_metrics(), _wards(), cfg=_config()).set_index(
        "ward_id"
    )

    assert result.loc["w2", "status"] == "insufficient_data"
    assert result.loc["w2", "coverage_pct"] == 0
    assert "low_coverage" in result.loc["w2", "flags"]
    assert result.loc["w3", "n_buildings"] == 0
    assert result.loc["w3", "status"] == "insufficient_data"
    assert result.loc["w3", "coverage_pct"] == 0
    assert pd.isna(result.loc["w3", "beta_coverage_pct"])
    assert "low_coverage" in result.loc["w3", "flags"]
    assert all(
        set(flags) <= {"sparse_points", "groundwater_missing", "low_coverage"}
        for flags in result["flags"]
    )


def test_unassigned_rows_are_excluded_from_ward_denominators_and_reconciled():
    result = aggregate.build_ward_indicators(_metrics(), _wards(), cfg=_config())

    assert result["n_buildings"].sum() == 5
    assert result.attrs["unassigned_buildings"] == 1
    assert result["n_buildings"].sum() + result.attrs["unassigned_buildings"] == len(_metrics())


def test_duplicate_building_ids_and_inconsistent_sparse_are_rejected():
    duplicate = _metrics()
    duplicate.loc[1, "bldg_id"] = duplicate.loc[0, "bldg_id"]
    with pytest.raises(aggregate.D1Error, match="Duplicate bldg_id"):
        aggregate.build_ward_indicators(duplicate, _wards(), cfg=_config())

    bad_sparse = _metrics()
    bad_sparse.loc[0, "sparse"] = True
    with pytest.raises(aggregate.D1Error, match="sparse values"):
        aggregate.build_ward_indicators(bad_sparse, _wards(), cfg=_config())


def test_duplicate_or_unknown_ward_ids_are_rejected():
    duplicate_wards = pd.concat([_wards(), _wards().iloc[[0]]], ignore_index=True)
    with pytest.raises(aggregate.D1Error, match="Duplicate ward_id"):
        aggregate.build_ward_indicators(_metrics(), duplicate_wards, cfg=_config())

    bad = _metrics()
    bad.loc[0, "ward_id"] = "unknown"
    with pytest.raises(aggregate.D1Error, match="absent from supplied boundaries"):
        aggregate.build_ward_indicators(bad, _wards(), cfg=_config())


def test_groundwater_values_and_missing_flag_are_preserved():
    groundwater = pd.DataFrame(
        {"ward_id": ["w1"], "gw_stage_pct": [71.5], "gw_category": ["Semi-Critical"]}
    )
    result = aggregate.build_ward_indicators(
        _metrics(), _wards(), groundwater=groundwater, cfg=_config()
    ).set_index("ward_id")

    assert result.loc["w1", "gw_stage_pct"] == 71.5
    assert result.loc["w1", "gw_category"] == "Semi-Critical"
    assert "groundwater_missing" not in result.loc["w1", "flags"]
    assert "groundwater_missing" in result.loc["w2", "flags"]


def test_results_are_deterministic_and_coverage_flags_are_contract_values():
    first = aggregate.build_ward_indicators(_metrics(), _wards(), cfg=_config())
    second = aggregate.build_ward_indicators(_metrics(), _wards(), cfg=_config())

    pd.testing.assert_frame_equal(first, second)
    allowed = {
        "sparse_points",
        "groundwater_missing",
        "small_ward",
        "low_coverage",
        "boundary_vintage",
    }
    assert all(set(flags) <= allowed for flags in first["flags"])
    assert first["rank"].isna().all()
    assert first["score"].isna().all()


def test_spatial_audit_separates_matches_mismatches_boundary_outside_and_unassigned(tmp_path):
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1", "w2"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:4326",
    )
    geometries = [
        box(0.2, 0.2, 0.4, 0.4),  # w1 assigned to w1
        box(1.2, 0.2, 1.4, 0.4),  # w2 centroid incorrectly assigned to w1
        box(0.6, 0.2, 0.8, 0.4),  # no stored ward, uniquely inside w1
        box(0.9, 0.4, 1.1, 0.6),  # centroid on shared boundary
        box(4.0, 0.2, 4.2, 0.4),  # outside coverage
        Polygon(),  # empty geometry
        Polygon([(0.2, 0.2), (0.4, 0.4), (0.2, 0.4), (0.4, 0.2), (0.2, 0.2)]),  # invalid
        Point(0.3, 0.3),  # unsupported non-polygon geometry
        None,  # missing geometry
    ]
    frame = gpd.GeoDataFrame(
        {
            "bldg_id": [f"b{i}" for i in range(len(geometries))],
            "ward_id": ["w1", "w1", None, None, None, None, None, None, None],
        },
        geometry=geometries,
        crs="EPSG:4326",
    )
    path = tmp_path / "buildings.parquet"
    frame.to_parquet(path, index=False)

    result = aggregate._audit_spatial_assignments(path, wards)

    assert result["total_buildings"] == 9
    assert result["assigned_centroid_matches_ward"] == 1
    assert result["assigned_centroid_mismatch"] == 1
    assert result["unassigned_inside_unique_ward"] == 1
    assert result["unassigned_boundary_intersection"] == 1
    assert result["unassigned_outside_ward_coverage"] == 1
    assert result["geometry_empty"] == 1
    assert result["geometry_invalid"] == 1
    assert result["geometry_non_polygon"] == 1
    assert result["geometry_missing"] == 1
    assert result["derived_assignments_applied"] is False


def test_spatial_audit_marks_centroids_inside_overlapping_wards_ambiguous(tmp_path):
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1", "w2"]},
        geometry=[box(0, 0, 2, 2), box(1, 0, 3, 2)],
        crs="EPSG:4326",
    )
    path = tmp_path / "overlap.parquet"
    gpd.GeoDataFrame(
        {"bldg_id": ["b1"], "ward_id": [None]},
        geometry=[box(1.4, 0.5, 1.6, 0.7)],
        crs="EPSG:4326",
    ).to_parquet(path, index=False)

    result = aggregate._audit_spatial_assignments(path, wards)

    assert result["unassigned_overlapping_wards"] == 1
    assert result["unassigned_inside_unique_ward"] == 0


def _config_doc() -> dict:
    return {
        "contract": "C6@1.0",
        "city": "delhi",
        "display_name": "Delhi",
        "utm_epsg": 32643,
        "bbox": [76.8, 28.3, 77.4, 28.9],
        "seed": 42,
        "paths": {"pack_dir": "data/pack/delhi", "out_dir": "out/delhi"},
        "params": {
            "coverage_min": 0.5,
            "sinking_threshold_mm_yr": -4,
            "horizon_years": 10,
            "pair_min_m": 80,
            "pair_max_m": 120,
        },
        "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15},
        "mode": "public",
    }


def _write_cli_inputs(tmp_path: Path) -> dict[str, Path]:
    import yaml

    source = tmp_path / "inputs"
    source.mkdir()
    config = _config_doc()
    config_path = source / "delhi.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    params_hash = hashlib.sha256(
        json.dumps(
            config["params"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    c1 = pd.DataFrame(
        {
            "bldg_id": ["b1", "b2"],
            "ward_id": ["w0", None],
            "cell_id": ["c0", None],
            "vlm_mm_yr": [-4.0, None],
            "beta_horizon": [0.001, None],
            "sparse": [False, True],
            "engine_version": ["fixture-engine"] * 2,
            "params_hash": [params_hash] * 2,
        }
    )
    c0 = gpd.GeoDataFrame(
        {
            "bldg_id": ["b1", "b2"],
            "ward_id": ["w0", None],
            "cell_id": ["c0", None],
        },
        geometry=[box(0.2, 0.2, 0.4, 0.4), box(2.2, 0.2, 2.4, 0.4)],
        crs="EPSG:4326",
    )
    buildings_path = source / "buildings.parquet"
    metrics_path = source / "metrics.parquet"
    c0.to_parquet(buildings_path, index=False)
    c1.to_parquet(metrics_path, index=False)
    summary = {
        "contract": "C1@1.0",
        "city": "delhi",
        "buildings_processed": 2,
        "engine_version": "fixture-engine",
        "params_hash": params_hash,
        "params": config["params"],
        "seed": 42,
    }
    summary_path = source / "run.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    integration = {
        "c0_candidate": {
            "pack_version": "fixture-pack",
            "files": [
                {
                    "path": "out/delhi/buildings.parquet",
                    "actual_sha256": hashlib.sha256(buildings_path.read_bytes()).hexdigest(),
                }
            ],
        },
        "c1_candidate": {
            "sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
            "engine_version": "fixture-engine",
            "params_hash": params_hash,
        },
    }
    manifest_path = source / "integration.json"
    manifest_path.write_text(json.dumps(integration), encoding="utf-8")
    ward_features = []
    for i in range(250):
        x = i * 2
        ward_features.append(
            {
                "type": "Feature",
                "properties": {"ward_id": f"w{i}", "ward_name": f"Ward {i}"},
                "geometry": shapely.geometry.mapping(box(x, 0, x + 1, 1)),
            }
        )
    wards_path = source / "wards.geojson"
    gpd.GeoDataFrame.from_features(ward_features, crs="EPSG:4326").to_file(
        wards_path, driver="GeoJSON"
    )
    return {
        "buildings": buildings_path,
        "metrics": metrics_path,
        "summary": summary_path,
        "config": config_path,
        "wards": wards_path,
        "manifest": manifest_path,
    }


def test_explicit_cli_inputs_write_aggregates_and_qa_without_spatial_reassignment(tmp_path):
    files = _write_cli_inputs(tmp_path)
    from argparse import Namespace

    args = Namespace(
        buildings_parquet=files["buildings"],
        metrics_parquet=files["metrics"],
        run_summary=files["summary"],
        config_yaml=files["config"],
        wards_geojson=files["wards"],
        integration_manifest=files["manifest"],
        ward_output=tmp_path / "out" / "d1" / "ward_indicators.csv",
        qa_output=tmp_path / "out" / "d1" / "d1_qa.json",
        overwrite=False,
    )
    qa = aggregate.run_d1(args)
    output = pd.read_csv(args.ward_output)

    assert len(output) == 250
    assert output["ward_id"].nunique() == 250
    assert qa["assignment_audit"]["unassigned_inside_unique_ward"] == 1
    assert qa["assignment_audit"]["derived_assignments_applied"] is False
    assert qa["aggregation"]["building_count_reconciliation"] == 2
    assert output.loc[output["ward_id"] == "w0", "n_buildings"].iloc[0] == 1
    assert qa["c0_pack_completeness"]["manifest_complete"] is False
