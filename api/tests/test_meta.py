"""Bounded tests for C4 metadata assembly from synthetic C2/C6 artifacts."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import api.main as api_main
import api.metadata as metadata
from api.data import APIData, DataPaths

ROOT = Path(__file__).resolve().parents[2]
MOCK_C2 = ROOT / "contracts" / "mock" / "ward_summary.json"
CONFIGS = ROOT / "configs"
META_PATH = "/api/v1/meta"
EXPECTED_FIELDS = {
    "city", "data_vintage", "generated_utc", "engine_version", "params",
    "weights", "n_wards", "n_ranked", "default_mode", "contract_versions",
}
EXPECTED_VERSIONS = {f"C{number}": "1.0" for number in range(7)}


class FakeDataStore:
    def __init__(self, document: dict) -> None:
        self.document = document

    def load_ward_summary(self) -> dict:
        return deepcopy(self.document)


@pytest.fixture
def meta_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    shutil.copyfile(CONFIGS / "delhi.yaml", config_dir / "delhi.yaml")
    shutil.copyfile(CONFIGS / "chennai.yaml", config_dir / "chennai.yaml")
    monkeypatch.setattr(metadata, "CONFIGS_DIR", config_dir)
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.delenv("AUTHORITY_TOKEN", raising=False)

    document = json.loads(MOCK_C2.read_text(encoding="utf-8"))
    store = FakeDataStore(document)
    monkeypatch.setattr(api_main, "data_store", store)
    return TestClient(api_main.app), store, config_dir


@pytest.mark.parametrize("city", ["delhi", "chennai"])
def test_meta_maps_c2_and_validated_c6_without_authentication(meta_env, city: str) -> None:
    client, store, _ = meta_env
    store.document["meta"]["city"] = city

    response = client.get(META_PATH)

    assert response.status_code == 200
    body = response.json()
    c2_meta = store.document["meta"]
    assert set(body) == EXPECTED_FIELDS
    for field in (
        "city", "data_vintage", "generated_utc", "engine_version", "params",
        "weights", "n_wards", "n_ranked",
    ):
        assert body[field] == c2_meta[field]
    assert body["default_mode"] == "public"
    assert body["contract_versions"] == EXPECTED_VERSIONS
    assert type(body["city"]) is str
    assert type(body["data_vintage"]) is str
    assert type(body["generated_utc"]) is str
    assert type(body["engine_version"]) is str
    assert type(body["params"]) is dict
    assert type(body["weights"]) is dict
    assert type(body["n_wards"]) is int
    assert type(body["n_ranked"]) is int
    assert body["default_mode"] in {"public", "authority"}
    assert response.headers["ETag"]
    assert response.headers["ETag"] == client.get(META_PATH).headers["ETag"]
    assert store.document["contract"] == "C2@1.0"


def _assert_generic_internal(response) -> None:
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal",
            "message": "Unexpected failure",
            "details": {},
        }
    }


def test_missing_c2_metadata_and_invalid_c2_schema_fail_generically(meta_env) -> None:
    client, store, _ = meta_env
    store.document.pop("meta")
    _assert_generic_internal(client.get(META_PATH))

    store.document = json.loads(MOCK_C2.read_text(encoding="utf-8"))
    store.document["meta"].pop("n_ranked")
    _assert_generic_internal(client.get(META_PATH))


def test_missing_configured_c2_file_does_not_fall_back_to_mock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_summary = tmp_path / "configured-but-missing.json"
    store = APIData(
        DataPaths(
            ward_summary=missing_summary,
            cell_scores=tmp_path / "unused-cells.geojson",
            building_metrics=tmp_path / "unused-buildings.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )
    )
    monkeypatch.setattr(api_main, "data_store", store)

    response = TestClient(api_main.app).get(META_PATH)

    _assert_generic_internal(response)
    assert str(missing_summary) not in response.text


def test_malformed_configured_c2_json_fails_generically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    malformed_summary = tmp_path / "malformed-summary.json"
    malformed_summary.write_text("{ invalid json", encoding="utf-8")
    store = APIData(
        DataPaths(
            ward_summary=malformed_summary,
            cell_scores=tmp_path / "unused-cells.geojson",
            building_metrics=tmp_path / "unused-buildings.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )
    )
    monkeypatch.setattr(api_main, "data_store", store)

    response = TestClient(api_main.app).get(META_PATH)

    _assert_generic_internal(response)
    assert str(malformed_summary) not in response.text


def test_wrong_c2_contract_declaration_fails_generically(meta_env) -> None:
    client, store, _ = meta_env
    store.document["contract"] = "C2@9.9"
    response = client.get(META_PATH)
    _assert_generic_internal(response)
    assert "C2@9.9" not in response.text


@pytest.mark.parametrize("city", ["", "../delhi", r"..\delhi", "delhi/../chennai"])
def test_unsafe_city_identifiers_are_rejected(meta_env, city: str) -> None:
    client, store, _ = meta_env
    store.document["meta"]["city"] = city

    response = client.get(META_PATH)

    _assert_generic_internal(response)
    assert "delhi" not in response.text


def test_missing_city_configuration_fails_generically(meta_env) -> None:
    client, store, _ = meta_env
    store.document["meta"]["city"] = "mumbai"
    _assert_generic_internal(client.get(META_PATH))


def test_default_mode_is_taken_from_c6_configuration(meta_env) -> None:
    client, store, config_dir = meta_env
    store.document["meta"]["city"] = "chennai"
    config_path = config_dir / "chennai.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["mode"] = "authority"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    response = client.get(META_PATH)

    assert response.status_code == 200
    assert response.json()["default_mode"] == "authority"


def test_invalid_yaml_and_invalid_c6_schema_fail_generically(meta_env) -> None:
    client, _, config_dir = meta_env
    config_path = config_dir / "delhi.yaml"
    config_path.write_text("contract: [invalid", encoding="utf-8")
    _assert_generic_internal(client.get(META_PATH))

    source_config = yaml.safe_load((CONFIGS / "delhi.yaml").read_text(encoding="utf-8"))
    source_config.pop("params")
    config_path.write_text(yaml.safe_dump(source_config), encoding="utf-8")
    _assert_generic_internal(client.get(META_PATH))


@pytest.mark.parametrize(
    "change",
    [
        {"city": "chennai"},
        {"contract": "C6@9.9"},
        {"mode": "private"},
    ],
)
def test_mismatched_or_invalid_c6_values_fail_generically(meta_env, change: dict) -> None:
    client, _, config_dir = meta_env
    config_path = config_dir / "delhi.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config.update(change)
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    _assert_generic_internal(client.get(META_PATH))


def test_meta_openapi_matches_c4_and_buildings_remains_protected(meta_env) -> None:
    client, _, _ = meta_env
    schema = client.get("/api/v1/openapi.json").json()
    operation = schema["paths"][META_PATH]["get"]
    assert set(operation["responses"]) == {"200", "429", "500"}
    assert set(operation["responses"]["200"]["content"]) == {"application/json"}
    assert "security" not in operation
    model_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    model_name = model_ref.rsplit("/", 1)[-1]
    meta_schema = schema["components"]["schemas"][model_name]
    assert set(meta_schema["required"]) == EXPECTED_FIELDS
    assert meta_schema["properties"]["generated_utc"]["format"] == "date-time"
    versions_ref = meta_schema["properties"]["contract_versions"]["$ref"]
    versions_name = versions_ref.rsplit("/", 1)[-1]
    versions_schema = schema["components"]["schemas"][versions_name]
    assert set(versions_schema["required"]) == set(EXPECTED_VERSIONS)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/buildings", params={"bbox": "77,28,78,29"}).status_code == 401
