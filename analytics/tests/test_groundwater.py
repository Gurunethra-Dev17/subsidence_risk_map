import json
from argparse import Namespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from analytics.groundwater import (
    D2Error,
    allocate_groundwater,
    audit_proxy_boundaries,
    main,
    missing_groundwater_context,
    validate_assessment_table,
)


def _wards(geometries=None):
    geometries = geometries or [box(0, 0, 10, 10)]
    return gpd.GeoDataFrame(
        {
            "ward_id": [str(i + 1) for i in range(len(geometries))],
            "ward_name": [f"Ward {i + 1}" for i in range(len(geometries))],
        },
        geometry=geometries,
        crs="EPSG:32643",
    ).to_crs("EPSG:4326")


def _units(rows):
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32643")


def _assessment_table(path):
    categories = ["safe"] * 7 + ["semi critical"] * 6 + ["critical"] * 11 + ["overexploited"] * 10
    pd.DataFrame(
        {
            "district": ["District"] * 34,
            "assessment_unit_name": [f"Unit {index}" for index in range(34)],
            "total_area_of_assessment_unit_ha": [100.0] * 34,
            "stage_of_groundwater_extraction_pct": [float(index) for index in range(34)],
            "categorization": categories,
        }
    ).to_csv(path, index=False)
    return path


def test_area_weighted_mean_for_multiple_units_in_one_ward():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:32643"
    )
    units = _units(
        [
            {
                "SUB_DIST": "West",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 20.0,
                "categorization": "safe",
                "geometry": box(0, 0, 5, 10),
            },
            {
                "SUB_DIST": "East",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 80.0,
                "categorization": "critical",
                "geometry": box(5, 0, 10, 10),
            },
        ]
    )

    result = allocate_groundwater(wards, units)

    assert result.loc[0, "gw_stage_pct"] == 50
    assert result.loc[0, "gw_coverage_pct"] == 100
    assert result.loc[0, "gw_stage_coverage_pct"] == 100
    assert result.loc[0, "gw_category"] == "critical"  # deterministic tie break
    assert result.loc[0, "gw_assessment_units"] == "East;West"


def test_missing_unit_stage_is_not_zero_and_stage_coverage_is_separate():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:32643"
    )
    units = _units(
        [
            {
                "SUB_DIST": "A",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": pd.NA,
                "categorization": pd.NA,
                "geometry": box(0, 0, 10, 5),
            }
        ]
    )
    result = allocate_groundwater(wards, units)
    assert pd.isna(result.loc[0, "gw_stage_pct"])
    assert pd.isna(result.loc[0, "gw_category"])
    assert result.loc[0, "gw_coverage_pct"] == 50
    assert result.loc[0, "gw_stage_coverage_pct"] == 0


def test_partial_coverage_uses_ward_area_denominator():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:32643"
    )
    units = _units(
        [
            {
                "SUB_DIST": "A",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 40.0,
                "categorization": "safe",
                "geometry": box(0, 0, 5, 10),
            }
        ]
    )
    result = allocate_groundwater(wards, units)
    assert result.loc[0, "gw_stage_pct"] == 40
    assert result.loc[0, "gw_coverage_pct"] == 50
    assert result.loc[0, "gw_stage_coverage_pct"] == 50


def test_missing_boundary_fallback_has_every_ward_once_and_all_values_null():
    wards = _wards([box(76.8, 28.5, 76.9, 28.6), box(77.0, 28.5, 77.1, 28.6)])
    result = missing_groundwater_context(wards)
    assert len(result) == 2
    assert result["ward_id"].is_unique
    assert result["ward_id"].tolist() == ["1", "2"]
    assert result["ward_name"].tolist() == ["Ward 1", "Ward 2"]
    assert result.iloc[:, 2:].isna().all().all()


def test_proxy_audit_reports_name_and_district_mismatches_without_claiming_authority():
    assessment = pd.DataFrame(
        {
            "district": ["Expected"],
            "assessment_unit_name": ["North Unit"],
            "total_area_of_assessment_unit_ha": [0.5],
            "stage_of_groundwater_extraction_pct": [50.0],
            "categorization": ["safe"],
        }
    )
    proxy = _units(
        [{"SUB_DIST": "North Unit", "DISTRICT": "Different", "geometry": box(0, 0, 100, 100)}]
    )
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]}, geometry=[box(0, 0, 100, 100)], crs="EPSG:32643"
    ).to_crs("EPSG:4326")
    _, report = audit_proxy_boundaries(assessment, proxy, wards)
    assert report["status"] == "exploratory_proxy_only"
    assert report["name_correspondence"]["matched"] == 1
    assert len(report["name_correspondence"]["district_mismatches"]) == 1
    assert report["area_comparison"]["units_over_threshold"] == ["North Unit"]
    assert report["boundary_authority"] == "not established as CGWB assessment-unit boundaries"


def test_unmatched_and_ambiguous_proxy_correspondence_is_reported_or_rejected():
    assessment = pd.DataFrame(
        {
            "district": ["D"],
            "assessment_unit_name": ["A"],
            "total_area_of_assessment_unit_ha": [1.0],
            "stage_of_groundwater_extraction_pct": [10.0],
            "categorization": ["safe"],
        }
    )
    proxy = _units([{"SUB_DIST": "B", "DISTRICT": "D", "geometry": box(0, 0, 10, 10)}])
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w"], "ward_name": ["W"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:32643"
    ).to_crs("EPSG:4326")
    _, report = audit_proxy_boundaries(assessment, proxy, wards)
    assert report["name_correspondence"]["unmatched_cgwb_units"] == ["A"]
    assert report["name_correspondence"]["unmatched_proxy_units"] == ["B"]
    duplicate_proxy = _units(
        [
            {"SUB_DIST": "A", "DISTRICT": "D", "geometry": box(0, 0, 5, 10)},
            {"SUB_DIST": "A", "DISTRICT": "D", "geometry": box(5, 0, 10, 10)},
        ]
    )
    with pytest.raises(D2Error, match="ambiguous"):
        audit_proxy_boundaries(assessment, duplicate_proxy, wards)


def test_invalid_geometry_is_rejected_without_repair():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]},
        geometry=[box(0, 0, 10, 10).difference(box(4, 4, 6, 6))],
        crs="EPSG:32643",
    )
    units = _units(
        [
            {
                "SUB_DIST": "A",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 10.0,
                "categorization": "safe",
                "geometry": box(0, 0, 10, 10),
            }
        ]
    )
    # The polygon with a hole is valid; use a self-crossing bow-tie to exercise rejection.
    from shapely.geometry import Polygon

    wards.geometry = [Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])]
    with pytest.raises(D2Error, match="invalid"):
        allocate_groundwater(wards, units)


def test_overlapping_units_are_rejected_before_area_weighting():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:32643"
    )
    units = _units(
        [
            {
                "SUB_DIST": "A",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 10.0,
                "categorization": "safe",
                "geometry": box(0, 0, 6, 10),
            },
            {
                "SUB_DIST": "B",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 90.0,
                "categorization": "critical",
                "geometry": box(4, 0, 10, 10),
            },
        ]
    )
    with pytest.raises(D2Error, match="overlap"):
        allocate_groundwater(wards, units)


def test_area_analysis_rejects_nonmetric_crs():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w1"], "ward_name": ["Ward"]},
        geometry=[box(0, 0, 10, 10)],
        crs="EPSG:32643",
    )
    units = _units(
        [
            {
                "SUB_DIST": "A",
                "DISTRICT": "D",
                "stage_of_groundwater_extraction_pct": 10.0,
                "categorization": "safe",
                "geometry": box(0, 0, 10, 10),
            }
        ]
    )
    with pytest.raises(D2Error, match="projected"):
        allocate_groundwater(wards, units, area_crs="EPSG:4326")


def test_assessment_input_hash_structure_and_category_counts(tmp_path):
    path = _assessment_table(tmp_path / "assessment.csv")
    table, report = validate_assessment_table(path)
    assert len(table) == 34
    assert report["rows"] == 34
    assert report["category_counts_match"] is True
    assert report["sha256"]


def test_missing_required_assessment_column_is_actionable(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"assessment_unit_name": ["A"]}).to_csv(path, index=False)
    with pytest.raises(D2Error, match="missing required columns"):
        validate_assessment_table(path)


def test_proxy_layer_requires_all_matching_attributes_and_declared_crs():
    assessment = pd.DataFrame(
        {
            "district": ["D"],
            "assessment_unit_name": ["A"],
            "total_area_of_assessment_unit_ha": [1.0],
            "stage_of_groundwater_extraction_pct": [10.0],
            "categorization": ["safe"],
        }
    )
    wards = gpd.GeoDataFrame(
        {"ward_id": ["w"], "ward_name": ["Ward"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:32643"
    ).to_crs("EPSG:4326")
    missing_attribute = _units([{"SUB_DIST": "A", "geometry": box(0, 0, 10, 10)}])
    with pytest.raises(D2Error, match="missing columns"):
        audit_proxy_boundaries(assessment, missing_attribute, wards)
    no_crs = _units([{"SUB_DIST": "A", "DISTRICT": "D", "geometry": box(0, 0, 10, 10)}])
    no_crs = no_crs.set_crs(None, allow_override=True)
    with pytest.raises(D2Error, match="declared CRS"):
        audit_proxy_boundaries(assessment, no_crs, wards)


def test_cli_writes_truthful_missing_data_fallback(tmp_path):
    assessment = _assessment_table(tmp_path / "assessment.csv")
    wards = _wards([box(76.8, 28.5, 76.9, 28.6), box(77.0, 28.5, 77.1, 28.6)])
    ward_path = tmp_path / "wards.geojson"
    wards.to_file(ward_path, driver="GeoJSON")
    context_path = tmp_path / "groundwater_context.csv"
    qa_path = tmp_path / "groundwater_qa.json"

    exit_code = main(
        [
            "--assessment-csv",
            str(assessment),
            "--wards-geojson",
            str(ward_path),
            "--output-csv",
            str(context_path),
            "--qa-json",
            str(qa_path),
            "--expected-wards",
            "2",
        ]
    )

    context = pd.read_csv(context_path)
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert len(context) == 2
    assert context["ward_id"].is_unique
    assert context["gw_stage_pct"].isna().all()
    assert context["gw_category"].isna().all()
    assert qa["ward_output"]["stage_values_available"] == 0
    assert qa["proxy_boundary_audit"]["status"] == "unavailable"


def test_output_overwrite_requires_explicit_flag(tmp_path):
    assessment = _assessment_table(tmp_path / "assessment.csv")
    wards = _wards()
    ward_path = tmp_path / "wards.geojson"
    wards.to_file(ward_path, driver="GeoJSON")
    context_path = tmp_path / "context.csv"
    qa_path = tmp_path / "qa.json"
    args = Namespace(
        assessment_csv=assessment,
        wards_geojson=ward_path,
        output_csv=context_path,
        qa_json=qa_path,
        proxy_boundaries=None,
        exploratory_proxy_output=None,
        expected_wards=1,
        area_crs="EPSG:32643",
        overwrite=False,
    )
    from analytics.groundwater import run_d2

    run_d2(args)
    with pytest.raises(D2Error, match="exists"):
        run_d2(args)
