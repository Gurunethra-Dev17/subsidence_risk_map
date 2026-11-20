"""Bounded endpoint tests using synthetic building responses."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import api.main as api_main

TOKEN = "synthetic-authority-token"
PATH = "/api/v1/buildings"
BBOX = "77.0,28.5,77.2,28.7"


def _feature(*, sparse: object = False) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [77.1, 28.6]},
        "properties": {
            "bldg_id": "synthetic-building-1",
            "vlm_mm_yr": None,
            "beta_ratio_horizon": None,
            "beta_class": None,
            "sparse": sparse,
        },
    }


class FakeBuildingStore:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or {"type": "FeatureCollection", "features": [_feature()]}
        self.calls: list[dict] = []

    def get_buildings(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return deepcopy(self.result)

    def list_wards(self, **kwargs) -> dict:
        return {
            "items": [],
            "total": 0,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TOKEN)
    store = FakeBuildingStore()
    monkeypatch.setattr(api_main, "data_store", store)
    return TestClient(api_main.app), store


def _headers() -> dict[str, str]:
    return {"X-Authority-Token": TOKEN}


def test_authorization_precedes_building_data_access(client) -> None:
    test_client, store = client

    missing = test_client.get(PATH, params={"bbox": BBOX})
    missing_bbox = test_client.get(PATH)
    wrong = test_client.get(
        PATH, params={"bbox": BBOX}, headers={"X-Authority-Token": "wrong"}
    )

    for response in (missing, missing_bbox, wrong):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authority_required"
        assert response.headers["Cache-Control"] == "no-store"
    assert store.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"bbox": "bad"},
        {"bbox": "181,0,182,1"},
        {"bbox": "77,91,78,92"},
        {"bbox": "10,5,9,6"},
        {"bbox": "10,7,11,6"},
        {"bbox": BBOX, "limit": "0"},
        {"bbox": BBOX, "limit": "5001"},
    ],
)
def test_invalid_query_parameters_are_c4_400(client, params: dict) -> None:
    test_client, store = client
    response = test_client.get(PATH, params=params, headers=_headers())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_param"
    assert response.headers["Cache-Control"] == "no-store"
    assert store.calls == []


def test_success_is_geojson_no_store_and_forwards_query_defaults(client) -> None:
    test_client, store = client
    response = test_client.get(PATH, params={"bbox": BBOX}, headers=_headers())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "type": "FeatureCollection",
        "features": [_feature()],
    }
    assert response.json()["features"][0]["properties"]["sparse"] is False
    assert store.calls == [{"ward_id": None, "bbox": BBOX, "limit": 500}]


def test_ward_filter_and_explicit_limit_are_forwarded(client) -> None:
    test_client, store = client
    response = test_client.get(
        PATH,
        params={"bbox": BBOX, "ward_id": "ward-synthetic", "limit": "12"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert store.calls == [{"ward_id": "ward-synthetic", "bbox": BBOX, "limit": 12}]


def test_unmatched_c1_sparse_value_fails_generically_without_fabrication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TOKEN)
    store = FakeBuildingStore(
        {"type": "FeatureCollection", "features": [_feature(sparse=None)]}
    )
    monkeypatch.setattr(api_main, "data_store", store)

    response = TestClient(api_main.app).get(
        PATH, params={"bbox": BBOX}, headers=_headers()
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal",
            "message": "Unexpected failure",
            "details": {},
        }
    }
    assert "synthetic-building-1" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_data_layer_failure_is_generic_and_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenStore:
        def get_buildings(self, **kwargs):
            raise RuntimeError("private path and SQL details")

    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TOKEN)
    monkeypatch.setattr(api_main, "data_store", BrokenStore())

    response = TestClient(api_main.app).get(
        PATH, params={"bbox": BBOX}, headers=_headers()
    )

    assert response.status_code == 500
    assert "private path" not in response.text
    assert "SQL" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_public_endpoints_and_openapi_security(client) -> None:
    test_client, _ = client
    assert test_client.get("/api/v1/health").status_code == 200
    assert test_client.get("/api/v1/wards", params={"limit": 1}).status_code == 200

    schema = test_client.get("/api/v1/openapi.json").json()
    operation = schema["paths"][PATH]["get"]
    assert schema["components"]["securitySchemes"]["AuthorityToken"] == {
        "type": "apiKey",
        "description": "Authority access token supplied by the deployment.",
        "in": "header",
        "name": "X-Authority-Token",
    }
    assert operation["security"] == [{"AuthorityToken": []}]
    assert set(operation["responses"]) == {"200", "400", "401", "429", "500"}
    assert set(operation["responses"]["200"]["content"]) == {
        "application/json", "application/geo+json"
    }
    assert TOKEN not in str(schema)
    assert operation["responses"]["200"]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
    for status in ("400", "401", "429", "500"):
        assert operation["responses"][status]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"


def test_correct_token_required_for_valid_response(client) -> None:
    test_client, store = client
    response = test_client.get(PATH, params={"bbox": BBOX}, headers=_headers())
    assert response.status_code == 200
    assert len(store.calls) == 1
