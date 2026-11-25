"""Focused C4 checks against FastAPI's generated OpenAPI and synthetic data."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.data import APIData, DataPaths

_ROOT = Path(__file__).resolve().parents[2]
_MOCKS = _ROOT / "contracts" / "mock"
_TOKEN = "synthetic-c4-authority-token"
_PREFIX = "/api/v1"
_BUILDINGS = f"{_PREFIX}/buildings"


class SyntheticStore:
    """Delegate public fixture reads to committed mocks and fake buildings."""

    def __init__(self) -> None:
        self.public = APIData(
            DataPaths(
                ward_summary=_MOCKS / "ward_summary.json",
                cell_scores=_MOCKS / "cell_scores.geojson",
                building_metrics=None,
                validation_summary=_MOCKS / "validation_summary.json",
                buildings_geometry=None,
            )
        )

    def __getattr__(self, name: str):
        return getattr(self.public, name)

    def get_buildings(self, **kwargs) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [77.1, 28.6]},
                "properties": {
                    "bldg_id": "synthetic-building-1",
                    "vlm_mm_yr": None,
                    "beta_ratio_horizon": None,
                    "beta_class": None,
                    "sparse": True,
                },
            }],
        }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", _TOKEN)
    monkeypatch.setattr(api_main, "data_store", SyntheticStore())
    monkeypatch.setattr(api_main, "generate_brief_pdf", lambda *args: b"%PDF-1.4 synthetic")
    return TestClient(api_main.app)


def _authority_headers() -> dict[str, str]:
    return {"X-Authority-Token": _TOKEN}


def test_all_c4_get_routes_are_present(client: TestClient) -> None:
    openapi = client.get(f"{_PREFIX}/openapi.json").json()
    expected = {
        f"{_PREFIX}/meta",
        f"{_PREFIX}/wards",
        f"{_PREFIX}/wards/{{ward_id}}",
        f"{_PREFIX}/wards/{{ward_id}}/cells",
        f"{_PREFIX}/wards/{{ward_id}}/brief.pdf",
        _BUILDINGS,
        f"{_PREFIX}/validation",
        f"{_PREFIX}/health",
    }
    assert expected.issubset(openapi["paths"])
    assert all("get" in openapi["paths"][path] for path in expected)


def test_buildings_declares_required_bbox_and_authority_security(client: TestClient) -> None:
    openapi = client.get(f"{_PREFIX}/openapi.json").json()
    operation = openapi["paths"][_BUILDINGS]["get"]
    bbox = next(parameter for parameter in operation["parameters"] if parameter["name"] == "bbox")
    assert bbox["in"] == "query"
    assert bbox["required"] is True
    assert operation["security"] == [{"AuthorityToken": []}]
    assert openapi["components"]["securitySchemes"]["AuthorityToken"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Authority-Token",
        "description": "Authority access token supplied by the deployment.",
    }


def test_authorized_missing_bbox_is_c4_400_and_unauthorized_is_c4_401(
    client: TestClient,
) -> None:
    authorized = client.get(_BUILDINGS, headers=_authority_headers())
    assert authorized.status_code == 400
    assert authorized.json()["error"]["code"] == "invalid_param"
    assert authorized.headers["Cache-Control"] == "no-store"

    unauthorized = client.get(_BUILDINGS)
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "authority_required"
    assert unauthorized.headers["Cache-Control"] == "no-store"


def test_buildings_geojson_and_no_store_response(client: TestClient) -> None:
    response = client.get(
        _BUILDINGS,
        params={"bbox": "77.0,28.5,77.2,28.7"},
        headers=_authority_headers(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["type"] == "FeatureCollection"


def test_pdf_and_cell_geojson_response_media_and_cache_headers(client: TestClient) -> None:
    pdf = client.get(f"{_PREFIX}/wards/ward-001/brief.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.headers["Cache-Control"] == "no-store"

    cells = client.get(f"{_PREFIX}/wards/ward-002/cells")
    assert cells.status_code == 200
    assert cells.headers["content-type"].startswith("application/geo+json")


def test_api_errors_use_c4_error_envelope(client: TestClient) -> None:
    response = client.get(f"{_PREFIX}/wards/no-such-ward")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Unknown ward_id",
            "details": {},
        }
    }


def test_generated_response_media_types_match_authoritative_c4(client: TestClient) -> None:
    # Compared with origin/main C4: cells/buildings permit JSON and GeoJSON;
    # briefs are PDF; all other successful API responses are JSON.
    openapi = client.get(f"{_PREFIX}/openapi.json").json()
    expected = {
        f"{_PREFIX}/meta": {"application/json"},
        f"{_PREFIX}/wards": {"application/json"},
        f"{_PREFIX}/wards/{{ward_id}}": {"application/json"},
        f"{_PREFIX}/wards/{{ward_id}}/cells": {"application/json", "application/geo+json"},
        f"{_PREFIX}/wards/{{ward_id}}/brief.pdf": {"application/pdf"},
        _BUILDINGS: {"application/json", "application/geo+json"},
        f"{_PREFIX}/validation": {"application/json"},
        f"{_PREFIX}/health": {"application/json"},
    }
    for path, media_types in expected.items():
        actual = set(openapi["paths"][path]["get"]["responses"]["200"]["content"])
        assert actual == media_types

    error = openapi["paths"][_BUILDINGS]["get"]["responses"]["401"]
    assert set(error["content"]) == {"application/json"}
