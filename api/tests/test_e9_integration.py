"""End-to-end E9 building API coverage using temporary synthetic artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.data import APIData, DataPaths, json_etag

TOKEN = "synthetic-e9-authority-token"
BUILDINGS_PATH = "/api/v1/buildings"


def _write_synthetic_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    duckdb = pytest.importorskip("duckdb")
    c0_path = tmp_path / "synthetic_c0.parquet"
    c1_path = tmp_path / "synthetic_c1.parquet"
    connection = duckdb.connect(database=":memory:")
    connection.execute("LOAD spatial")
    connection.execute(
        """
        CREATE TABLE c0 (
            bldg_id VARCHAR,
            footprint_m2 DOUBLE,
            source VARCHAR,
            ward_id VARCHAR,
            cell_id VARCHAR,
            geometry GEOMETRY
        )
        """
    )
    c0_rows = [
        (
            "synthetic-matched-building",
            120.0,
            "osm",
            "ward-synthetic",
            "cell-synthetic",
            (
                "POLYGON ((77.01 28.60, 77.02 28.60, 77.02 28.61, "
                "77.01 28.61, 77.01 28.60))"
            ),
        ),
        (
            "synthetic-unmatched-building",
            95.0,
            "osm",
            "ward-synthetic",
            "cell-synthetic",
            (
                "POLYGON ((77.10 28.60, 77.11 28.60, 77.11 28.61, "
                "77.10 28.61, 77.10 28.60))"
            ),
        ),
    ]
    for row in c0_rows:
        connection.execute(
            "INSERT INTO c0 VALUES (?, ?, ?, ?, ?, ST_GeomFromText(?))", row
        )
    connection.execute(
        """
        CREATE TABLE c1 (
            bldg_id VARCHAR,
            ward_id VARCHAR,
            cell_id VARCHAR,
            n_points INTEGER,
            vlm_mm_yr FLOAT,
            vlm_iqr_mm_yr FLOAT,
            n_pairs INTEGER,
            beta_rate_per_yr FLOAT,
            beta_horizon FLOAT,
            beta_ratio_horizon VARCHAR,
            beta_class VARCHAR,
            sparse BOOLEAN,
            vt_risk_insar TINYINT,
            engine_version VARCHAR,
            params_hash VARCHAR
        )
        """
    )
    connection.execute(
        """
        INSERT INTO c1 VALUES
            ('synthetic-matched-building', 'ward-synthetic', 'cell-synthetic',
             8, -3.5, 0.4, 4, NULL, NULL, NULL, NULL, false, NULL,
             'synthetic-engine', 'synthetic-hash')
        """
    )
    connection.execute(
        f"COPY c0 TO '{c0_path.as_posix()}' (FORMAT PARQUET)"
    )
    connection.execute(
        f"COPY c1 TO '{c1_path.as_posix()}' (FORMAT PARQUET)"
    )
    connection.close()
    return c0_path, c1_path


def test_authenticated_buildings_joins_synthetic_c0_c1_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    c0_path, c1_path = _write_synthetic_artifacts(tmp_path)
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TOKEN)

    store = APIData(
        DataPaths(
            ward_summary=None,
            cell_scores=None,
            building_metrics=c1_path,
            validation_summary=None,
            buildings_geometry=c0_path,
        )
    )

    class CountingStore:
        calls = 0

        def get_buildings(self, **kwargs):
            self.calls += 1
            return store.get_buildings(**kwargs)

    counting_store = CountingStore()
    monkeypatch.setattr(api_main, "data_store", counting_store)
    client = TestClient(api_main.app)
    bbox = "77.0,28.55,77.05,28.65"

    unauthorized = client.get(
        BUILDINGS_PATH, params={"bbox": bbox, "limit": 1}
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "authority_required"
    assert counting_store.calls == 0

    response = client.get(
        BUILDINGS_PATH,
        params={"bbox": bbox, "limit": 1},
        headers={"X-Authority-Token": TOKEN},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["ETag"] == json_etag(response.json())
    assert counting_store.calls == 1
    feature = response.json()["features"][0]
    assert feature["properties"]["bldg_id"] == "synthetic-matched-building"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["beta_ratio_horizon"] is None
    assert feature["properties"]["beta_class"] is None
    assert feature["properties"]["sparse"] is False

    unmatched_included = client.get(
        BUILDINGS_PATH,
        params={"bbox": "77.0,28.55,77.2,28.65", "limit": 2},
        headers={"X-Authority-Token": TOKEN},
    )
    assert unmatched_included.status_code == 500
    assert unmatched_included.json() == {
        "error": {
            "code": "internal",
            "message": "Unexpected failure",
            "details": {},
        }
    }
    assert "features" not in unmatched_included.json()
    assert "synthetic-matched-building" not in unmatched_included.text
    assert "synthetic-unmatched-building" not in unmatched_included.text
    assert unmatched_included.headers["Cache-Control"] == "no-store"
    assert counting_store.calls == 2
