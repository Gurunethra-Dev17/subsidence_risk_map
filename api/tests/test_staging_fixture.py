"""Tests for the explicit-output synthetic C1 staging fixture generator."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.data import APIData, DataPaths
from api.staging_fixture import generate_synthetic_c1

_BBOX = "76.84,28.40,77.35,28.89"


def _read_fixture(
    path: Path,
) -> tuple[list[tuple], list[str], dict[str, str]]:
    with duckdb.connect(database=":memory:") as connection:
        schema = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()
        rows = connection.execute(
            "SELECT * FROM read_parquet(?) ORDER BY bldg_id", [str(path)]
        ).fetchall()
        columns = [column[0] for column in connection.description]
        metadata_rows = connection.execute(
            "SELECT key, value FROM parquet_kv_metadata(?)", [str(path)]
        ).fetchall()
    metadata = {key.decode("utf-8"): value.decode("utf-8") for key, value in metadata_rows}
    assert columns == [
        "bldg_id",
        "ward_id",
        "cell_id",
        "n_points",
        "vlm_mm_yr",
        "vlm_iqr_mm_yr",
        "n_pairs",
        "beta_rate_per_yr",
        "beta_horizon",
        "beta_ratio_horizon",
        "beta_class",
        "sparse",
        "vt_risk_insar",
        "engine_version",
        "params_hash",
        "lon",
        "lat",
    ]
    return rows, [column[1] for column in schema], metadata


def test_fixture_is_c1_shaped_and_declares_synthetic_metadata(tmp_path: Path) -> None:
    output = tmp_path / "synthetic" / "building_metrics.parquet"
    generated = generate_synthetic_c1(output)

    rows, types, metadata = _read_fixture(generated)
    assert len(rows) == 3
    assert types == [
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "INTEGER",
        "FLOAT",
        "FLOAT",
        "INTEGER",
        "FLOAT",
        "FLOAT",
        "VARCHAR",
        "VARCHAR",
        "BOOLEAN",
        "TINYINT",
        "VARCHAR",
        "VARCHAR",
        "DOUBLE",
        "DOUBLE",
    ]
    assert all(row[0].startswith("SYNTH-") for row in rows)
    assert metadata["contract"] == "C1@1.0"
    assert metadata["horizon_years"] == "10"
    assert metadata["seed"] == "0"
    assert metadata["engine_version"] == "synthetic-staging-v1"
    assert len(metadata["params_hash"]) == 64
    assert all(row[index] is not None for row in rows for index in (0, 3, 6, 11, 13, 14, 15, 16))
    assert all(row[11] is (row[4] is None) for row in rows)


def test_fixture_generation_is_reproducible_and_requires_new_output(
    tmp_path: Path,
) -> None:
    first = generate_synthetic_c1(tmp_path / "first.parquet")
    second = generate_synthetic_c1(tmp_path / "second.parquet")

    assert first.read_bytes() == second.read_bytes()
    assert _read_fixture(first) == _read_fixture(second)
    with pytest.raises(FileExistsError):
        generate_synthetic_c1(first)


def test_fixture_supports_authenticated_bbox_buildings_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_path = generate_synthetic_c1(tmp_path / "synthetic.parquet")
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", "synthetic-test-token")
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(
            DataPaths(
                ward_summary=None,
                cell_scores=None,
                building_metrics=fixture_path,
                validation_summary=None,
                buildings_geometry=None,
            )
        ),
    )
    client = TestClient(api_main.app)

    unauthorized = client.get("/api/v1/buildings", params={"bbox": _BBOX})
    assert unauthorized.status_code == 401
    assert unauthorized.headers["Cache-Control"] == "no-store"

    response = client.get(
        "/api/v1/buildings",
        params={"bbox": _BBOX, "limit": 10},
        headers={"X-Authority-Token": "synthetic-test-token"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert [feature["properties"]["bldg_id"] for feature in payload["features"]] == [
        "SYNTH-DEMO-001",
        "SYNTH-DEMO-002",
    ]
    assert all(isinstance(feature["properties"]["sparse"], bool) for feature in payload["features"])
