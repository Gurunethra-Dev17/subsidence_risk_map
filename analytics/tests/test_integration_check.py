import csv
import hashlib
import json
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from analytics import integration_check


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _ward_rows() -> list[dict[str, str]]:
    base = {
        "n_buildings": "10",
        "flags": "[]",
        "histogram": "",
        "share_sinking_gt4": "0.2",
        "vlm_median_mm_yr": "-3.0",
        "beta_p90_horizon": "0.001",
        "beta_p90_ratio_horizon": "1/1000",
        "gw_stage_pct": "60",
        "gw_category": "safe",
    }
    return [
        {
            **base,
            "ward_id": "w1",
            "ward_name": "Synthetic One",
            "status": "ranked",
            "n_buildings_with_data": "8",
            "coverage_pct": "80",
            "score": "90",
            "rank": "1",
            "flags": "[]",
        },
        {
            **base,
            "ward_id": "w2",
            "ward_name": "Synthetic Two",
            "status": "ranked",
            "n_buildings_with_data": "7",
            "coverage_pct": "70",
            "score": "70",
            "rank": "2",
            "flags": "[]",
        },
        {
            **base,
            "ward_id": "w3",
            "ward_name": "Synthetic Three",
            "status": "insufficient_data",
            "n_buildings_with_data": "4",
            "coverage_pct": "40",
            "score": "",
            "rank": "",
            "flags": "['low_coverage']",
            "beta_p90_horizon": "",
            "beta_p90_ratio_horizon": "",
        },
    ]


def _sensitivity_rows() -> list[dict[str, str]]:
    return [
        {"ward_id": "w1", "rank_p05": "1", "rank_p95": "2"},
        {"ward_id": "w2", "rank_p05": "1", "rank_p95": "2"},
        {"ward_id": "w3", "rank_p05": "", "rank_p95": ""},
    ]


def _cell_rows() -> list[dict[str, str]]:
    return [
        {
            "cell_id": "c1",
            "ward_id": "w1",
            "n_buildings": "4",
            "suppressed": "true",
            "vlm_median_mm_yr": "",
            "beta_p90_horizon": "",
            "share_sinking_gt4": "",
            "cell_score": "",
            "cell_rank_in_ward": "",
        },
        {
            "cell_id": "c2",
            "ward_id": "w1",
            "n_buildings": "6",
            "suppressed": "false",
            "vlm_median_mm_yr": "-2.5",
            "beta_p90_horizon": "0.001",
            "share_sinking_gt4": "0.2",
            "cell_score": "55",
            "cell_rank_in_ward": "1",
        },
    ]


def _geometry() -> dict:
    def square(x: int) -> dict:
        return {
            "type": "Polygon",
            "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]],
        }

    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"cell_id": "c1"}, "geometry": square(0)},
            {"type": "Feature", "properties": {"cell_id": "c2"}, "geometry": square(2)},
        ],
    }


def _config() -> dict:
    return {
        "contract": "C6@1.0",
        "city": "delhi",
        "display_name": "Delhi",
        "utm_epsg": 32643,
        "bbox": [76.8, 28.3, 77.4, 28.9],
        "seed": 42,
        "paths": {"pack_dir": "data/pack/delhi", "out_dir": "out/delhi"},
        "params": {"coverage_min": 0.5, "pair_min_m": 80, "pair_max_m": 120},
        "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15},
        "mode": "public",
    }


def _write_inputs(directory: Path, *, manifest: bool = False) -> Namespace:
    directory.mkdir(parents=True, exist_ok=True)
    wards = _write_csv(directory / "wards.csv", _ward_rows())
    sensitivity = _write_csv(directory / "sensitivity.csv", _sensitivity_rows())
    cells = _write_csv(directory / "cells.csv", _cell_rows())
    geometry = directory / "cells.geojson"
    geometry.write_text(json.dumps(_geometry()), encoding="utf-8")
    config = _config()
    meta = {
        "city": "delhi",
        "data_vintage": "synthetic-pack-v1",
        "engine_version": "synthetic-engine",
        "params": config["params"],
        "weights": config["weights"],
    }
    meta_path = directory / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    ward_geo = directory / "wards.geojson"
    ward_geo.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"ward_id": f"w{i}"}, "geometry": None}
                    for i in range(1, 4)
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = None
    if manifest:
        source_c1 = directory / "source-c1.parquet"
        source_c1.write_bytes(b"synthetic source marker")
        params_hash = hashlib.sha256(
            json.dumps(
                config["params"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        config_path = directory / "delhi.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        manifest_path = directory / "integration-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "c0_candidate": {
                        "pack_version": "synthetic-pack-v1",
                        "c0_manifest_complete": True,
                    },
                    "c1_candidate": {
                        "path": str(source_c1),
                        "sha256": hashlib.sha256(source_c1.read_bytes()).hexdigest(),
                        "engine_version": "synthetic-engine",
                        "params_hash": params_hash,
                        "c6_reference_config_path": str(config_path),
                    },
                }
            ),
            encoding="utf-8",
        )
    return Namespace(
        wards_csv=wards,
        sensitivity_csv=sensitivity,
        meta_json=meta_path,
        cells_csv=cells,
        geometry_geojson=geometry,
        validation_json=None,
        d6_validation_json=None,
        ward_geometry_geojson=ward_geo,
        integration_manifest=manifest_path,
    )


def test_valid_synthetic_inputs_are_ready_and_hashes_are_recorded(tmp_path):
    args = _write_inputs(tmp_path, manifest=True)

    report = integration_check.check_readiness(args)

    assert report["status"] == "ready"
    assert report["summary"]["ranked_wards"] == 2
    assert report["summary"]["suppressed_cells"] == 1
    assert report["inputs"]["meta_json"]["sha256"]
    assert {check["name"] for check in report["checks"]} >= {
        "c1_manifest_hash",
        "c6_c1_params_hash",
        "ward_geometry_ids",
        "cell_geometry_ids",
        "c2_input_contract",
        "cell_input_contract",
        "c3_input_contract",
    }


def test_missing_intermediate_is_fatal(tmp_path):
    args = _write_inputs(tmp_path)
    args.sensitivity_csv = tmp_path / "missing.csv"

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert "missing_sensitivity_csv" in {error["code"] for error in report["errors"]}


def test_missing_required_field_is_fatal(tmp_path):
    args = _write_inputs(tmp_path)
    rows = _cell_rows()
    for row in rows:
        row.pop("cell_score")
    args.cells_csv = _write_csv(tmp_path / "cells-missing-field.csv", rows)

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert any("cell_score" in error["message"] for error in report["errors"])


def test_incompatible_source_metadata_is_fatal(tmp_path):
    args = _write_inputs(tmp_path, manifest=True)
    metadata = json.loads(args.meta_json.read_text(encoding="utf-8"))
    metadata["engine_version"] = "different-engine"
    args.meta_json.write_text(json.dumps(metadata), encoding="utf-8")

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert "engine_version_mismatch" in {error["code"] for error in report["errors"]}


@pytest.mark.parametrize(
    ("first_rank", "second_rank", "expected_code"),
    [("1", "1", "duplicate_ward_ranks"), ("1", "3", "noncontiguous_ward_ranks")],
)
def test_duplicate_or_gapped_ward_ranks_are_fatal(tmp_path, first_rank, second_rank, expected_code):
    args = _write_inputs(tmp_path)
    rows = _ward_rows()
    rows[0]["rank"] = first_rank
    rows[1]["rank"] = second_rank
    args.wards_csv = _write_csv(tmp_path / "wards-bad-ranks.csv", rows)

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert expected_code in {error["code"] for error in report["errors"]}


def test_invalid_rank_range_is_fatal(tmp_path):
    args = _write_inputs(tmp_path)
    rows = _sensitivity_rows()
    rows[1]["rank_p05"] = "3"
    rows[1]["rank_p95"] = "3"
    args.sensitivity_csv = _write_csv(tmp_path / "ranges-bad.csv", rows)

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert any("bracket" in error["message"].lower() for error in report["errors"])


def test_cell_geometry_mismatch_is_fatal(tmp_path):
    args = _write_inputs(tmp_path)
    geometry = _geometry()
    geometry["features"].pop()
    args.geometry_geojson.write_text(json.dumps(geometry), encoding="utf-8")

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert "cell_geometry_id_mismatch" in {error["code"] for error in report["errors"]}


def test_suppression_violation_is_fatal(tmp_path):
    args = _write_inputs(tmp_path)
    rows = _cell_rows()
    rows[0]["suppressed"] = "false"
    args.cells_csv = _write_csv(tmp_path / "cells-unsuppressed.csv", rows)

    report = integration_check.check_readiness(args)

    assert report["status"] == "not_ready"
    assert any("Suppression" in error["message"] for error in report["errors"])


def test_absent_validation_comparisons_are_explicitly_unavailable(tmp_path):
    args = _write_inputs(tmp_path)

    report = integration_check.check_readiness(args)

    assert report["status"] == "ready"
    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert "validation_comparisons_not_supplied" in warning_codes
    assert "d6_fragment_not_supplied" in warning_codes


def test_valid_d6_fragment_is_accepted_and_bad_fragment_rejected(tmp_path):
    args = _write_inputs(tmp_path)
    fragment = {
        "n_incidents_total": 0,
        "n_in_city": 0,
        "by_published_risk": {},
        "by_rank_band": {},
        "note": "Comparison unavailable; no incidents were processed.",
    }
    args.d6_validation_json = tmp_path / "d6.json"
    args.d6_validation_json.write_text(json.dumps(fragment), encoding="utf-8")
    assert integration_check.check_readiness(args)["status"] == "ready"
    fragment["extra"] = "not in C3"
    args.d6_validation_json.write_text(json.dumps(fragment), encoding="utf-8")
    report = integration_check.check_readiness(args)
    assert report["status"] == "not_ready"


def test_run_invokes_existing_exporter_and_records_output_hashes(tmp_path):
    args = _write_inputs(tmp_path)
    args.ward_output = tmp_path / "outputs" / "ward_summary.json"
    args.cell_output = tmp_path / "outputs" / "cell_scores.geojson"
    args.validation_output = tmp_path / "outputs" / "validation_summary.json"
    args.figure_dir = tmp_path / "outputs" / "figures"
    args.provenance_output = tmp_path / "outputs" / "integration_provenance.json"
    args.generated_utc = "2026-11-24T12:00:00Z"
    args.overwrite = False

    report = integration_check.run_workflow(args)

    assert report["status"] == "ready"
    assert args.ward_output.is_file()
    assert args.cell_output.is_file()
    assert args.validation_output.is_file()
    provenance = json.loads(args.provenance_output.read_text(encoding="utf-8"))
    assert len(provenance["outputs"]) >= 3
    assert all(item["sha256"] for item in provenance["outputs"])


def test_run_does_not_call_exporter_when_readiness_fails(tmp_path, monkeypatch):
    args = _write_inputs(tmp_path)
    args.wards_csv = tmp_path / "absent-wards.csv"
    args.ward_output = tmp_path / "outputs" / "ward.json"
    args.cell_output = tmp_path / "outputs" / "cells.geojson"
    args.validation_output = tmp_path / "outputs" / "validation.json"
    args.figure_dir = tmp_path / "outputs" / "figures"
    args.provenance_output = tmp_path / "outputs" / "provenance.json"
    args.generated_utc = "2026-11-24T12:00:00Z"
    args.overwrite = False

    def unexpected_export(_args):
        raise AssertionError("exporter must not run after readiness failure")

    monkeypatch.setattr(integration_check.d8, "export_artifacts", unexpected_export)
    report = integration_check.run_workflow(args)

    assert report["status"] == "not_ready"
    assert not args.ward_output.exists()
    assert not args.provenance_output.exists()
