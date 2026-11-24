import csv
import json
from argparse import Namespace

import pytest

from analytics.export import (
    ExportError,
    _make_figures,
    build_cell_scores,
    build_validation_summary,
    build_ward_summary,
    export_artifacts,
)

FIXED_TIME = "2026-11-24T12:00:00Z"


def ward_rows():
    return [
        {
            "ward_id": "w1",
            "ward_name": "Synthetic North",
            "status": "ranked",
            "n_buildings": "10",
            "n_buildings_with_data": "8",
            "coverage_pct": "80",
            "share_sinking_gt4": "0.25",
            "vlm_median_mm_yr": "-4.5",
            "beta_p90_horizon": "0.002",
            "beta_p90_ratio_horizon": "1/500",
            "gw_stage_pct": "75",
            "gw_category": "safe",
            "score": "80",
            "rank": "1",
            "flags": "[]",
            "histogram": '{"bin_edges":[0,1],"counts":[8]}',
        },
        {
            "ward_id": "w2",
            "ward_name": "Synthetic South",
            "status": "ranked",
            "n_buildings": "10",
            "n_buildings_with_data": "7",
            "coverage_pct": "70",
            "share_sinking_gt4": "0.1",
            "vlm_median_mm_yr": "-2.0",
            "beta_p90_horizon": "0.001",
            "beta_p90_ratio_horizon": "1/1000",
            "gw_stage_pct": "",
            "gw_category": "",
            "score": "50",
            "rank": "2",
            "flags": "['groundwater_missing']",
            "histogram": "",
        },
        {
            "ward_id": "w3",
            "ward_name": "Synthetic Low Coverage",
            "status": "insufficient_data",
            "n_buildings": "10",
            "n_buildings_with_data": "2",
            "coverage_pct": "20",
            "share_sinking_gt4": "",
            "vlm_median_mm_yr": "",
            "beta_p90_horizon": "",
            "beta_p90_ratio_horizon": "",
            "gw_stage_pct": "",
            "gw_category": "",
            "score": "",
            "rank": "",
            "flags": "['low_coverage']",
            "histogram": "",
        },
    ]


def sensitivity_rows():
    return [
        {"ward_id": "w1", "rank_p05": "1", "rank_p95": "2", "rank_min": "1", "rank_max": "2"},
        {"ward_id": "w2", "rank_p05": "1", "rank_p95": "2", "rank_min": "1", "rank_max": "2"},
        {"ward_id": "w3", "rank_p05": "", "rank_p95": "", "rank_min": "", "rank_max": ""},
    ]


def meta():
    return {
        "city": "synthetic-test-city",
        "data_vintage": "synthetic fixture",
        "generated_utc": FIXED_TIME,
        "engine_version": "synthetic",
        "params": {"coverage_min": 0.5, "horizon_years": 10},
        "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15},
    }


def cells():
    return [
        {
            "cell_id": "c1",
            "ward_id": "w1",
            "n_buildings": "7",
            "suppressed": "false",
            "vlm_median_mm_yr": "-5",
            "beta_p90_horizon": "0.002",
            "share_sinking_gt4": "0.4",
            "cell_score": "75",
            "cell_rank_in_ward": "1",
        },
        {
            "cell_id": "c2",
            "ward_id": "w2",
            "n_buildings": "3",
            "suppressed": "true",
            "vlm_median_mm_yr": "",
            "beta_p90_horizon": "",
            "share_sinking_gt4": "",
            "cell_score": "",
            "cell_rank_in_ward": "",
        },
    ]


def geometry():
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"cell_id": "c1"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[77, 28], [77.01, 28], [77.01, 28.01], [77, 28.01], [77, 28]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"cell_id": "c2"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[77.02, 28], [77.03, 28], [77.03, 28.01], [77.02, 28.01], [77.02, 28]]
                    ],
                },
            },
        ],
    }


def test_synthetic_c2_c3_and_cells_are_contract_compatible():
    c2 = build_ward_summary(ward_rows(), sensitivity_rows(), meta())
    cells_out = build_cell_scores(cells(), geometry())
    c3 = build_validation_summary(None, FIXED_TIME)

    assert c2["contract"] == "C2@1.0"
    assert [ward["rank"] for ward in c2["wards"] if ward["status"] == "ranked"] == [1, 2]
    assert c2["wards"][2]["score"] is None
    assert c2["wards"][2]["rank"] is None
    assert set(cells_out["features"][1]["properties"]) == {
        "cell_id",
        "ward_id",
        "n_buildings",
        "suppressed",
        "vlm_median_mm_yr",
        "beta_p90_horizon",
        "share_sinking_gt4",
        "cell_score",
        "cell_rank_in_ward",
    }
    assert all(
        value is None
        for key, value in cells_out["features"][1]["properties"].items()
        if key
        in {
            "vlm_median_mm_yr",
            "beta_p90_horizon",
            "share_sinking_gt4",
            "cell_score",
            "cell_rank_in_ward",
        }
    )
    assert c3["vt_consistency"]["spearman_rho"] is None
    assert "not performed" in c3["vt_consistency"]["note"]
    assert c3["collapse_check"]["by_published_risk"] == {}
    assert "No hotspot comparison" in c3["vt_consistency"]["note"]
    assert "Robustness comparisons were not supplied" in c3["vt_consistency"]["note"]


def test_duplicate_and_non_contiguous_ranks_are_rejected():
    rows = ward_rows()
    rows[1]["rank"] = "1"
    with pytest.raises(ExportError, match="unique and contiguous"):
        build_ward_summary(rows, sensitivity_rows(), meta())
    rows[1]["rank"] = "3"
    ranges = sensitivity_rows()
    ranges[1]["rank_p95"] = "3"
    with pytest.raises(ExportError, match="unique and contiguous"):
        build_ward_summary(rows, ranges, meta())


def test_rank_range_must_bracket_rank():
    ranges = sensitivity_rows()
    ranges[0]["rank_p05"] = "2"
    with pytest.raises(ExportError, match="does not bracket"):
        build_ward_summary(ward_rows(), ranges, meta())


def test_only_frozen_coverage_flags_are_accepted():
    rows = ward_rows()
    rows[0]["flags"] = "['beta_missing']"
    with pytest.raises(ExportError, match="Unsupported C2 coverage flag"):
        build_ward_summary(rows, sensitivity_rows(), meta())


def test_insufficient_coverage_requires_null_score_rank_range_and_flag():
    rows = ward_rows()
    rows[2]["flags"] = "[]"
    with pytest.raises(ExportError, match="flagged low_coverage"):
        build_ward_summary(rows, sensitivity_rows(), meta())
    rows[2]["flags"] = "['low_coverage']"
    rows[2]["rank"] = "3"
    with pytest.raises(ExportError, match="cannot have score or rank"):
        build_ward_summary(rows, sensitivity_rows(), meta())


def test_suppressed_cells_cannot_expose_metrics():
    rows = cells()
    rows[1]["cell_score"] = "12"
    with pytest.raises(ExportError, match="exposes restricted metrics"):
        build_cell_scores(rows, geometry())


def test_missing_or_invalid_cell_geometry_is_rejected():
    geo = geometry()
    geo["features"].pop()
    with pytest.raises(ExportError, match="lacks matching geometry"):
        build_cell_scores(cells(), geo)
    geo = geometry()
    geo["crs"]["properties"]["name"] = "EPSG:3857"
    with pytest.raises(ExportError, match="CRS must be"):
        build_cell_scores(cells(), geo)
    geo = geometry()
    geo["features"][0]["geometry"] = {"type": "Point", "coordinates": [77, 28]}
    with pytest.raises(ExportError, match="Polygon/MultiPolygon"):
        build_cell_scores(cells(), geo)


def test_unavailable_validation_sections_have_explanatory_notes():
    result = build_validation_summary(None, FIXED_TIME)
    assert result["vt_consistency"]["n_buildings"] == 0
    assert "not a zero result" in result["vt_consistency"]["note"]
    assert "Robustness comparisons were not supplied" in result["vt_consistency"]["note"]
    assert result["collapse_check"]["n_incidents_total"] == 0
    assert "no validation is implied" in result["collapse_check"]["note"]
    assert result["fresh_data_check"]["status"] == "not_run"


def test_missing_required_intermediate_fields_are_rejected():
    rows = ward_rows()
    del rows[0]["beta_p90_horizon"]
    with pytest.raises(ExportError, match="missing required columns"):
        build_ward_summary(rows, sensitivity_rows(), meta())


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _cli_args(root, suffix):
    root.mkdir(parents=True, exist_ok=True)
    wards_path = root / "wards.csv"
    sensitivity_path = root / "sensitivity.csv"
    cells_path = root / "cells.csv"
    geometry_path = root / "cells.geojson"
    meta_path = root / "meta.json"
    _write_csv(wards_path, ward_rows())
    _write_csv(sensitivity_path, sensitivity_rows())
    _write_csv(cells_path, cells())
    geometry_path.write_text(json.dumps(geometry()), encoding="utf-8")
    meta_path.write_text(json.dumps(meta()), encoding="utf-8")
    return Namespace(
        wards_csv=wards_path,
        sensitivity_csv=sensitivity_path,
        meta_json=meta_path,
        cells_csv=cells_path,
        geometry_geojson=geometry_path,
        validation_json=None,
        ward_output=root / f"ward-{suffix}.json",
        cell_output=root / f"cells-{suffix}.geojson",
        validation_output=root / f"validation-{suffix}.json",
        figure_dir=root / f"figures-{suffix}",
        generated_utc=FIXED_TIME,
        overwrite=False,
        figure_data_json=None,
    )


def test_exporter_generates_repeatable_outputs_and_figures(tmp_path):
    first = _cli_args(tmp_path / "first", "one")
    export_artifacts(first)
    before = [
        path.read_bytes()
        for path in (first.ward_output, first.cell_output, first.validation_output)
    ]
    first.overwrite = True
    export_artifacts(first)
    after = [
        path.read_bytes()
        for path in (first.ward_output, first.cell_output, first.validation_output)
    ]
    assert before == after
    assert sorted(path.name for path in first.figure_dir.glob("*.png")) == [
        "sensitivity_rank_range_width.png",
        "top_priority_ward_ranges.png",
        "ward_rank_ranges.png",
        "ward_score_distribution.png",
    ]
    assert json.loads(first.cell_output.read_text())["type"] == "FeatureCollection"
    validation = json.loads(first.validation_output.read_text(encoding="utf-8"))
    assert all("Synthetic-Test-City" in item["caption"] for item in validation["figures"])


def test_supplemental_figures_use_only_supplied_robustness_and_availability_summaries(tmp_path):
    args = _cli_args(tmp_path, "supplemental")
    args.figure_data_json = tmp_path / "figure_data.json"
    args.figure_data_json.write_text(
        json.dumps(
            {
                "weight_sensitivity": {
                    "draws_completed": 10,
                    "kendall_tau_vs_baseline": {
                        "minimum": 0.7,
                        "median": 0.9,
                        "mean": 0.88,
                        "maximum": 1.0,
                    },
                },
                "a7_variants": [
                    {
                        "radius_m": 50,
                        "pair_min_m": 80,
                        "pair_max_m": 120,
                        "kendall_tau_vs_baseline": None,
                    },
                    {
                        "radius_m": 100,
                        "pair_min_m": 80,
                        "pair_max_m": 120,
                        "kendall_tau_vs_baseline": 0.99,
                    },
                ],
                "c1_availability": {
                    "total_buildings": 10,
                    "vlm_nonnull": 8,
                    "beta_horizon_nonnull": 4,
                },
            }
        ),
        encoding="utf-8",
    )
    args.validation_json = tmp_path / "validation.json"
    args.validation_json.write_text(
        json.dumps(
            {
                "hotspot_check": [
                    {
                        "name": "Example",
                        "source": "Study",
                        "ward_id": "w1",
                        "rank": 1,
                        "percentile": 100,
                    },
                    {
                        "name": "Outside",
                        "source": "Study",
                        "ward_id": None,
                        "rank": None,
                        "percentile": None,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    export_artifacts(args)

    validation = json.loads(args.validation_output.read_text(encoding="utf-8"))
    figure_ids = {item["id"] for item in validation["figures"]}
    assert {
        "weight_perturbation_rank_stability",
        "a7_radius_pair_sensitivity",
        "c1_metric_availability",
        "literature_hotspot_reference_ranks",
    } <= figure_ids
    assert len(list(args.figure_dir.glob("*.png"))) == len(validation["figures"])
    assert (
        "approximate reference points"
        in next(
            item["caption"]
            for item in validation["figures"]
            if item["id"] == "literature_hotspot_reference_ranks"
        ).lower()
    )


def test_figures_are_omitted_when_data_cannot_support_them(tmp_path):
    insufficient = [
        {
            "status": "insufficient_data",
            "score": None,
            "rank": None,
            "rank_p05": None,
            "rank_p95": None,
        }
    ]
    assert _make_figures(insufficient, [], tmp_path / "no_figures", city="Delhi") == []


def test_existing_outputs_are_not_overwritten_without_flag(tmp_path):
    args = _cli_args(tmp_path, "existing")
    args.ward_output.write_text("keep", encoding="utf-8")
    with pytest.raises(ExportError, match="Output exists"):
        export_artifacts(args)
