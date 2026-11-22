from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.data import APIData, DataPaths, json_etag
from api.insar_status import validation_with_insar_status

MOCKS = Path(__file__).resolve().parents[2] / "contracts" / "mock"


def _manifest() -> dict:
    return {
        "generated_utc": "2026-11-22T05:56:28Z",
        "source_pair_report": "pair-report.json",
        "reference_scene_id": "synthetic-reference-scene",
        "reference_acquisition_time": "2026-09-05T12:54:49Z",
        "secondary_scene_id": "synthetic-secondary-scene",
        "secondary_acquisition_time": "2026-09-17T12:54:49Z",
        "full_burst_id": "027_056012_IW2",
        "polarization": "VV",
        "relative_orbit": 27,
        "flight_direction": "ASCENDING",
        "temporal_separation_days": 12.0,
        "processing_status": "not_submitted",
        "hyp3_eligibility": "unverified",
        "displacement_product": "not_available",
        "data_provenance": "Real ASF catalog metadata; not processed InSAR measurements.",
    }


def _c3_summary() -> dict:
    return json.loads((MOCKS / "validation_summary.json").read_text(encoding="utf-8"))


def test_valid_manifest_adapts_only_fresh_data_check(tmp_path: Path) -> None:
    manifest_path = tmp_path / "dry-run.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    summary = _c3_summary()
    other_fields = {key: value for key, value in summary.items() if key != "fresh_data_check"}

    result = validation_with_insar_status(summary, manifest_path)

    assert result["fresh_data_check"] == {
        "status": "not_submitted",
        "note": (
            "ASF catalog metadata contains a repeat-pass VV shortlist; no HyP3 job was "
            "submitted and no displacement product is available."
        ),
    }
    assert {
        key: value for key, value in result.items() if key != "fresh_data_check"
    } == other_fields
    assert summary["fresh_data_check"]["status"] == "not_run"


@pytest.mark.parametrize("manifest_kind", ["absent", "malformed", "contradictory"])
def test_unavailable_or_invalid_manifest_falls_back_to_not_run(
    tmp_path: Path, manifest_kind: str
) -> None:
    manifest_path = tmp_path / "manifest.json"
    if manifest_kind == "malformed":
        manifest_path.write_text("not JSON", encoding="utf-8")
    elif manifest_kind == "contradictory":
        manifest = _manifest()
        manifest["displacement_product"] = "available"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = validation_with_insar_status(_c3_summary(), manifest_path)

    assert result["fresh_data_check"]["status"] == "not_run"
    assert "no displacement product is available" in result["fresh_data_check"]["note"]


def test_validation_endpoint_is_public_preserves_c3_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "dry-run.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setenv("API_INSAR_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(
            DataPaths(
                ward_summary=MOCKS / "ward_summary.json",
                cell_scores=MOCKS / "cell_scores.geojson",
                building_metrics=None,
                validation_summary=MOCKS / "validation_summary.json",
                buildings_geometry=None,
            )
        ),
    )
    response = TestClient(api_main.app).get("/api/v1/validation")

    assert response.status_code == 200
    assert response.json()["contract"] == "C3@1.0"
    assert response.json()["fresh_data_check"]["status"] == "not_submitted"
    assert response.headers["ETag"] == json_etag(response.json())
