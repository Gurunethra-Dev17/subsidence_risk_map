"""HTTP tests for the public C4 endpoints implemented by E3."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.data import APIData, DataPaths, json_etag

MOCKS = Path(__file__).resolve().parents[2] / "contracts" / "mock"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    validation_summary = tmp_path / "validation_summary.json"
    shutil.copyfile(MOCKS / "validation_summary.json", validation_summary)
    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=tmp_path / "unused_building_metrics.parquet",
            validation_summary=validation_summary,
            buildings_geometry=None,
        )
    )
    monkeypatch.setattr(api_main, "data_store", store)
    return TestClient(api_main.app)


def assert_etag_matches(response) -> None:
    assert response.headers["ETag"] == json_etag(response.json())


def test_health_preserves_body_and_adds_etag(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": api_main.settings.api_version}
    assert_etag_matches(response)


def test_list_wards_filters_sorts_paginates_and_sets_cache_headers(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/wards",
        params={
            "status": "ranked",
            "sort": "score",
            "order": "desc",
            "q": "demo",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["limit"] == 1
    assert response.json()["offset"] == 0
    assert [item["ward_id"] for item in response.json()["items"]] == ["ward-001"]
    assert response.headers["Cache-Control"] == "public, max-age=300"
    assert_etag_matches(response)


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=501",
        "offset=-1",
        "status=unknown",
        "sort=unknown",
        "order=sideways",
    ],
)
def test_list_wards_rejects_invalid_query_parameters(
    client: TestClient, query: str
) -> None:
    response = client.get(f"/api/v1/wards?{query}")

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_param",
            "message": "Invalid request parameters",
            "details": {},
        }
    }
    assert_etag_matches(response)


def test_get_known_ward_and_unknown_ward(client: TestClient) -> None:
    known = client.get("/api/v1/wards/ward-001")
    assert known.status_code == 200
    assert known.json()["ward_id"] == "ward-001"
    assert known.headers["Cache-Control"] == "public, max-age=300"
    assert_etag_matches(known)

    unknown = client.get("/api/v1/wards/missing")
    assert unknown.status_code == 404
    assert unknown.json() == {
        "error": {"code": "not_found", "message": "Unknown ward_id", "details": {}}
    }
    assert_etag_matches(unknown)


def test_get_ward_cells_handles_suppression_empty_wards_and_unknown_wards(
    client: TestClient,
) -> None:
    suppressed = client.get("/api/v1/wards/ward-002/cells")
    assert suppressed.status_code == 200
    assert suppressed.headers["content-type"].startswith("application/geo+json")
    assert suppressed.headers["Cache-Control"] == "public, max-age=300"
    suppressed_properties = suppressed.json()["features"][0]["properties"]
    assert suppressed_properties["suppressed"] is True
    assert all(
        suppressed_properties[field] is None
        for field in (
            "vlm_median_mm_yr",
            "beta_p90_horizon",
            "share_sinking_gt4",
            "cell_score",
            "cell_rank_in_ward",
        )
    )
    assert_etag_matches(suppressed)

    empty = client.get("/api/v1/wards/ward-003/cells")
    assert empty.status_code == 200
    assert empty.json()["type"] == "FeatureCollection"
    assert empty.json()["features"] == []

    unknown = client.get("/api/v1/wards/missing/cells")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"
    assert_etag_matches(unknown)


def test_validation_uses_configured_c3_path_and_sets_etag(client: TestClient) -> None:
    response = client.get("/api/v1/validation")

    assert response.status_code == 200
    assert response.json()["contract"] == "C3@1.0"
    assert response.headers["content-type"].startswith("application/json")
    assert_etag_matches(response)


def test_generated_openapi_documents_c4_status_codes_and_response_media(
    client: TestClient,
) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    paths = schema["paths"]

    expected_statuses = {
        "/api/v1/health": {"200", "429", "500"},
        "/api/v1/wards": {"200", "400", "429", "500"},
        "/api/v1/wards/{ward_id}": {"200", "404", "429", "500"},
        "/api/v1/wards/{ward_id}/cells": {"200", "404", "429", "500"},
        "/api/v1/validation": {"200", "429", "500"},
    }
    for path, statuses in expected_statuses.items():
        operation = paths[path]["get"]
        assert set(operation["responses"]) == statuses
        assert "422" not in operation["responses"]

    cell_content = paths["/api/v1/wards/{ward_id}/cells"]["get"]["responses"]["200"]["content"]
    assert set(cell_content) == {"application/json", "application/geo+json"}
    assert "/api/v1/meta" not in paths
    assert "/api/v1/wards/{ward_id}/brief.pdf" not in paths
    assert "/api/v1/buildings" not in paths


@pytest.mark.parametrize(
    "path",
    ["/api/v1/meta", "/api/v1/wards/ward-001/brief.pdf", "/api/v1/buildings"],
)
def test_out_of_scope_routes_are_not_exposed(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
