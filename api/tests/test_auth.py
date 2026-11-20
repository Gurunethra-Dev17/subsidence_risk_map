"""Bounded tests for the reusable authority-token dependency."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

import api.main as api_main
from api.auth import require_authority

TEST_AUTHORITY_TOKEN = "test-only-authority-secret"


def _auth_test_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, api_main.http_exception_handler)

    @app.get("/protected", dependencies=[Depends(require_authority)])
    async def protected_resource() -> dict[str, bool]:
        return {"authorized": True}

    return app


def _client() -> TestClient:
    return TestClient(_auth_test_app())


def _assert_unauthorized(response) -> None:
    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "authority_required",
            "message": "Authority token required",
            "details": {},
        }
    }


def test_missing_empty_and_incorrect_tokens_are_rejected(
    monkeypatch,
) -> None:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TEST_AUTHORITY_TOKEN)
    client = _client()

    _assert_unauthorized(client.get("/protected"))
    _assert_unauthorized(client.get("/protected", headers={"X-Authority-Token": ""}))
    wrong = "wrong-test-token"
    response = client.get("/protected", headers={"X-Authority-Token": wrong})
    _assert_unauthorized(response)
    assert TEST_AUTHORITY_TOKEN not in response.text
    assert wrong not in response.text


def test_configured_token_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TEST_AUTHORITY_TOKEN)

    response = _client().get(
        "/protected", headers={"X-Authority-Token": TEST_AUTHORITY_TOKEN}
    )

    assert response.status_code == 200
    assert response.json() == {"authorized": True}


def test_development_fallback_requires_explicit_dev_environment(monkeypatch) -> None:
    monkeypatch.setenv("API_ENV", "dev")
    monkeypatch.delenv("AUTHORITY_TOKEN", raising=False)
    dev_client = _client()
    accepted = dev_client.get("/protected", headers={"X-Authority-Token": "demo-authority"})
    assert accepted.status_code == 200

    monkeypatch.setenv("API_ENV", "production")
    denied = _client().get("/protected", headers={"X-Authority-Token": "demo-authority"})
    _assert_unauthorized(denied)


def test_configured_secret_takes_precedence_over_development_fallback(monkeypatch) -> None:
    monkeypatch.setenv("API_ENV", "dev")
    monkeypatch.setenv("AUTHORITY_TOKEN", TEST_AUTHORITY_TOKEN)
    client = _client()

    accepted = client.get(
        "/protected", headers={"X-Authority-Token": TEST_AUTHORITY_TOKEN}
    )
    rejected_fallback = client.get(
        "/protected", headers={"X-Authority-Token": "demo-authority"}
    )

    assert accepted.status_code == 200
    _assert_unauthorized(rejected_fallback)


def test_missing_or_empty_secret_fails_closed_outside_dev(monkeypatch) -> None:
    monkeypatch.delenv("API_ENV", raising=False)
    monkeypatch.delenv("AUTHORITY_TOKEN", raising=False)
    assert api_main.Settings().api_env == "production"
    _assert_unauthorized(
        _client().get("/protected", headers={"X-Authority-Token": "demo-authority"})
    )

    monkeypatch.setenv("API_ENV", "production")
    _assert_unauthorized(
        _client().get("/protected", headers={"X-Authority-Token": "demo-authority"})
    )

    monkeypatch.setenv("AUTHORITY_TOKEN", "")
    _assert_unauthorized(
        _client().get("/protected", headers={"X-Authority-Token": "demo-authority"})
    )

    monkeypatch.setenv("API_ENV", "dev")
    _assert_unauthorized(
        _client().get("/protected", headers={"X-Authority-Token": "demo-authority"})
    )


def test_credentials_are_read_per_request(monkeypatch) -> None:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TEST_AUTHORITY_TOKEN)
    client = _client()

    accepted = client.get("/protected", headers={"X-Authority-Token": TEST_AUTHORITY_TOKEN})
    monkeypatch.setenv("AUTHORITY_TOKEN", "rotated-test-only-secret")
    old_secret = client.get("/protected", headers={"X-Authority-Token": TEST_AUTHORITY_TOKEN})
    new_secret = client.get("/protected", headers={"X-Authority-Token": "rotated-test-only-secret"})

    assert accepted.status_code == 200
    _assert_unauthorized(old_secret)
    assert new_secret.status_code == 200


def test_openapi_advertises_header_without_exposing_secret(monkeypatch) -> None:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TEST_AUTHORITY_TOKEN)
    schema = _client().get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["AuthorityToken"] == {
        "type": "apiKey",
        "description": "Authority access token supplied by the deployment.",
        "in": "header",
        "name": "X-Authority-Token",
    }
    assert schema["paths"]["/protected"]["get"]["security"] == [
        {"AuthorityToken": []}
    ]
    assert TEST_AUTHORITY_TOKEN not in str(schema)


def test_public_routes_remain_available_and_buildings_stay_unmounted() -> None:
    client = TestClient(api_main.app)

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/wards", params={"limit": 1}).status_code == 200
    assert "/api/v1/buildings" not in client.get("/api/v1/openapi.json").json()["paths"]
    assert client.get("/api/v1/buildings").status_code == 404
