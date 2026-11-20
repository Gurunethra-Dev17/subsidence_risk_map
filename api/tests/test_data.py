"""Focused tests for E2's fixture-backed API data access."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from api.data import (
    APIData,
    DataPaths,
    SpatialDataUnavailableError,
    json_etag,
    parse_bbox,
)

MOCKS = Path(__file__).resolve().parents[2] / "contracts" / "mock"
PARQUET_FIXTURE = MOCKS / "building_metrics.parquet"


@pytest.fixture
def data_store(tmp_path: Path) -> APIData:
    return APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=tmp_path / "building_metrics.parquet",
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )


def test_loads_c2_ward_summary(data_store: APIData) -> None:
    summary = data_store.load_ward_summary()
    assert summary["contract"] == "C2@1.0"
    assert len(summary["wards"]) == 3


@pytest.mark.parametrize(
    ("status", "ward_ids"),
    [
        ("ranked", ["ward-001", "ward-002"]),
        ("insufficient_data", ["ward-003"]),
    ],
)
def test_status_filter(data_store: APIData, status: str, ward_ids: list[str]) -> None:
    result = data_store.list_wards(status=status)
    assert [ward["ward_id"] for ward in result["items"]] == ward_ids
    assert result["total"] == len(ward_ids)


def test_name_search_is_case_insensitive(data_store: APIData) -> None:
    result = data_store.list_wards(q="sOuTh")
    assert [ward["ward_id"] for ward in result["items"]] == ["ward-002"]


@pytest.mark.parametrize(
    ("sort", "order", "ward_ids"),
    [
        ("rank", "asc", ["ward-001", "ward-002", "ward-003"]),
        ("rank", "desc", ["ward-002", "ward-001", "ward-003"]),
        ("score", "asc", ["ward-002", "ward-001", "ward-003"]),
        ("score", "desc", ["ward-001", "ward-002", "ward-003"]),
        ("name", "asc", ["ward-003", "ward-001", "ward-002"]),
        ("name", "desc", ["ward-002", "ward-001", "ward-003"]),
    ],
)
def test_sort_order(data_store: APIData, sort: str, order: str, ward_ids: list[str]) -> None:
    result = data_store.list_wards(sort=sort, order=order)
    assert [ward["ward_id"] for ward in result["items"]] == ward_ids


def test_pagination_and_limit_boundaries(data_store: APIData) -> None:
    page = data_store.list_wards(limit=1, offset=1)
    assert page == {
        "items": [data_store.get_ward("ward-002")],
        "total": 3,
        "limit": 1,
        "offset": 1,
    }
    assert data_store.list_wards()["limit"] == 50
    assert len(data_store.list_wards(limit=500)["items"]) == 3
    assert data_store.list_wards(limit=0)["items"] == []
    with pytest.raises(ValueError, match="0 and 500"):
        data_store.list_wards(limit=501)
    with pytest.raises(ValueError, match="non-negative"):
        data_store.list_wards(offset=-1)


def test_get_known_and_unknown_ward(data_store: APIData) -> None:
    assert data_store.get_ward("ward-001")["ward_name"] == "Demo North"
    assert data_store.get_ward("missing") is None


def test_loads_and_filters_c2_cells(data_store: APIData) -> None:
    cells = data_store.load_cell_scores()
    assert cells["type"] == "FeatureCollection"
    result = data_store.get_cells("ward-001")
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["cell_id"] == "cell-001"
    assert data_store.get_cells("unknown")["features"] == []


def test_suppressed_cell_metrics_are_hidden(tmp_path: Path) -> None:
    cells_path = tmp_path / "cells.geojson"
    fixture = json.loads((MOCKS / "cell_scores.geojson").read_text(encoding="utf-8"))
    suppressed = fixture["features"][1]["properties"]
    suppressed.update(
        vlm_median_mm_yr=-4,
        beta_p90_horizon=0.01,
        share_sinking_gt4=0.5,
        cell_score=90,
        cell_rank_in_ward=1,
    )
    cells_path.write_text(json.dumps(fixture), encoding="utf-8")
    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=cells_path,
            building_metrics=PARQUET_FIXTURE,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )
    properties = store.get_cells("ward-002")["features"][0]["properties"]
    assert properties["n_buildings"] == 2
    assert properties["suppressed"] is True
    assert all(properties[key] is None for key in (
        "vlm_median_mm_yr", "beta_p90_horizon", "share_sinking_gt4",
        "cell_score", "cell_rank_in_ward",
    ))


@pytest.mark.parametrize(
    "bbox",
    ["77,28.6,77.1", "x,28.6,77.1,28.7", "181,0,182,1", "0,91,1,92", "2,1,1,2"],
)
def test_rejects_malformed_or_out_of_range_bbox(bbox: str) -> None:
    with pytest.raises(ValueError):
        parse_bbox(bbox)


def test_bbox_parser_returns_epsg4326_order() -> None:
    assert parse_bbox("77,28.6,77.1,28.7") == (77.0, 28.6, 77.1, 28.7)


def test_etag_is_deterministic_and_changes_with_data() -> None:
    assert json_etag({"b": 2, "a": 1}) == json_etag({"a": 1, "b": 2})
    assert json_etag({"value": 1}) != json_etag({"value": 2})


def test_etag_changes_when_loaded_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "ward_summary.json"
    shutil.copyfile(MOCKS / "ward_summary.json", source)
    store = APIData(
        DataPaths(
            ward_summary=source,
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=PARQUET_FIXTURE,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )
    original = store.load_ward_summary()
    original_etag = json_etag(original)
    original["wards"][0]["ward_name"] = "Changed Demo North"
    source.write_text(json.dumps(original), encoding="utf-8")
    assert json_etag(store.load_ward_summary()) != original_etag


def test_missing_parquet_fixture_is_reported(tmp_path: Path) -> None:
    missing_parquet = tmp_path / "definitely_missing.parquet"
    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=missing_parquet,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )
    with pytest.raises(FileNotFoundError, match="C1 Parquet fixture not found"):
        store.get_buildings()


def test_data_paths_reads_optional_c0_geometry_path(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = Path("data") / "buildings.parquet"
    monkeypatch.setenv("API_BUILDINGS_GEOMETRY_PATH", str(configured))

    assert DataPaths().buildings_geometry == configured


def test_duckdb_reads_temporary_c1_parquet_and_filters_bbox(tmp_path: Path) -> None:
    """Exercise the query contract using temporary data, not a committed fixture."""
    duckdb = pytest.importorskip("duckdb")
    parquet_path = tmp_path / "temporary_c1.parquet"
    connection = duckdb.connect(database=":memory:")
    connection.execute(
        """
        CREATE TABLE c1 (
            bldg_id VARCHAR, ward_id VARCHAR, cell_id VARCHAR,
            n_points INTEGER, vlm_mm_yr DOUBLE, vlm_iqr_mm_yr DOUBLE,
            n_pairs INTEGER, beta_rate_per_yr DOUBLE, beta_horizon DOUBLE,
            beta_ratio_horizon VARCHAR, beta_class VARCHAR, sparse BOOLEAN,
            vt_risk_insar INTEGER, engine_version VARCHAR, params_hash VARCHAR,
            lon DOUBLE, lat DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO c1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("b-1", "ward-1", "cell-1", 3, -5, 1, 3, .0002, .002, "1/500", "inspect", False, 3, "test", "hash", 77.01, 28.61),
            ("b-2", "ward-1", "cell-1", 1, None, None, 0, None, None, None, None, True, None, "test", "hash", 78.0, 29.0),
            ("b-3", "ward-2", "cell-2", 2, -2, .5, 1, .0001, .001, "1/1000", "watch", False, 1, "test", "hash", 77.5, 28.8),
        ],
    )
    connection.execute(f"COPY c1 TO '{parquet_path.as_posix()}' (FORMAT PARQUET)")
    connection.close()

    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=parquet_path,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )
    all_buildings = store.get_buildings()
    assert [feature["properties"]["bldg_id"] for feature in all_buildings["features"]] == [
        "b-1", "b-2", "b-3"
    ]
    assert all_buildings["features"][0]["geometry"] == {
        "type": "Point", "coordinates": [77.01, 28.61]
    }
    ward_buildings = store.get_buildings(ward_id="ward-1")
    assert [feature["properties"]["bldg_id"] for feature in ward_buildings["features"]] == [
        "b-1", "b-2"
    ]
    bbox_buildings = store.get_buildings(bbox="77,28.5,77.1,28.7")
    assert [feature["properties"]["bldg_id"] for feature in bbox_buildings["features"]] == [
        "b-1"
    ]
    assert store.get_buildings(limit=0)["features"] == []
    assert len(store.get_buildings(limit=5000)["features"]) == 3
    with pytest.raises(ValueError, match="0 and 5000"):
        store.get_buildings(limit=5001)
    with pytest.raises(ValueError, match="bbox"):
        store.get_buildings(bbox="bad-bbox")


@pytest.mark.parametrize("geometry_storage", ["BLOB", "GEOMETRY"])
def test_c0_geometry_left_join_bbox_and_ward_filters(
    tmp_path: Path, geometry_storage: str
) -> None:
    duckdb = pytest.importorskip("duckdb")
    c0_path = tmp_path / "c0_buildings.parquet"
    c1_path = tmp_path / "c1_metrics.parquet"
    connection = duckdb.connect(database=":memory:")
    connection.execute("LOAD spatial")
    connection.execute(
        """
        CREATE TABLE c0 (
            bldg_id VARCHAR, ward_id VARCHAR, cell_id VARCHAR,
            geometry {geometry_storage}
        )
        """.format(geometry_storage=geometry_storage)
    )
    geometry_value = (
        "ST_AsWKB(ST_GeomFromText(?))"
        if geometry_storage == "BLOB"
        else "ST_GeomFromText(?)"
    )
    c0_rows = [
        (
            "b-poly", "ward-1", "cell-1",
            "POLYGON ((77.00 28.60, 77.10 28.60, 77.10 28.70, 77.00 28.70, 77.00 28.60))",
        ),
        (
            "b-multi", "ward-1", "cell-1",
            "MULTIPOLYGON (((77.20 28.60, 77.21 28.60, 77.21 28.61, 77.20 28.61, 77.20 28.60)), "
            "((77.28 28.68, 77.30 28.68, 77.30 28.70, 77.28 28.70, 77.28 28.68)))",
        ),
        (
            "b-unmatched", "ward-2", "cell-2",
            "POLYGON ((77.40 28.60, 77.41 28.60, 77.41 28.61, 77.40 28.61, 77.40 28.60))",
        ),
    ]
    for bldg_id, ward_id, cell_id, wkt in c0_rows:
        connection.execute(
            "INSERT INTO c0 VALUES (?, ?, ?, " + geometry_value + ")",
            [bldg_id, ward_id, cell_id, wkt],
        )
    connection.execute(
        """
        CREATE TABLE c1 (
            bldg_id VARCHAR, ward_id VARCHAR, cell_id VARCHAR,
            vlm_mm_yr DOUBLE, beta_ratio_horizon VARCHAR,
            beta_class VARCHAR, sparse BOOLEAN
        )
        """
    )
    connection.execute(
        """
        INSERT INTO c1 VALUES
        ('b-poly', 'ward-1', 'cell-1', -5.0, '1/500', 'inspect', false),
        ('b-multi', 'ward-1', 'cell-1', NULL, NULL, NULL, true)
        """
    )
    connection.execute(f"COPY c0 TO '{c0_path.as_posix()}' (FORMAT PARQUET)")
    connection.execute(f"COPY c1 TO '{c1_path.as_posix()}' (FORMAT PARQUET)")
    connection.close()

    missing_geometry_store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=c1_path,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=tmp_path / "missing_c0.parquet",
        )
    )
    with pytest.raises(FileNotFoundError, match="C0 building geometry Parquet not found"):
        missing_geometry_store.get_buildings()

    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=c1_path,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=c0_path,
        )
    )
    all_buildings = store.get_buildings(limit=10)
    by_id = {feature["properties"]["bldg_id"]: feature for feature in all_buildings["features"]}

    assert set(by_id) == {"b-poly", "b-multi", "b-unmatched"}
    assert by_id["b-poly"]["geometry"]["type"] == "Polygon"
    assert by_id["b-poly"]["properties"] == {
        "bldg_id": "b-poly",
        "vlm_mm_yr": -5.0,
        "beta_ratio_horizon": "1/500",
        "beta_class": "inspect",
        "sparse": False,
    }
    assert by_id["b-multi"]["geometry"]["type"] == "MultiPolygon"
    assert by_id["b-multi"]["properties"]["vlm_mm_yr"] is None
    assert by_id["b-multi"]["properties"]["sparse"] is True
    assert by_id["b-unmatched"]["geometry"]["type"] == "Polygon"
    assert all(
        by_id["b-unmatched"]["properties"][field] is None
        for field in ("vlm_mm_yr", "beta_ratio_horizon", "beta_class", "sparse")
    )

    # This bbox cuts across the polygon edge but does not contain its centroid.
    intersecting = store.get_buildings(bbox="77.095,28.64,77.11,28.66")
    assert [feature["properties"]["bldg_id"] for feature in intersecting["features"]] == [
        "b-poly"
    ]
    multipolygon_intersection = store.get_buildings(bbox="77.28,28.68,77.29,28.69")
    assert [
        feature["properties"]["bldg_id"]
        for feature in multipolygon_intersection["features"]
    ] == ["b-multi"]
    ward_buildings = store.get_buildings(ward_id="ward-2")
    assert [feature["properties"]["bldg_id"] for feature in ward_buildings["features"]] == [
        "b-unmatched"
    ]


@pytest.mark.skipif(
    not PARQUET_FIXTURE.is_file() or importlib.util.find_spec("duckdb") is None,
    reason="C1 Parquet fixture and DuckDB are absent from the repository environment",
)
def test_reads_c1_building_parquet() -> None:
    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=PARQUET_FIXTURE,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )
    result = store.get_buildings()
    assert result["type"] == "FeatureCollection"
    assert all(set(feature["properties"]) == {
        "bldg_id", "vlm_mm_yr", "beta_ratio_horizon", "beta_class", "sparse"
    } for feature in result["features"])


@pytest.mark.skipif(
    not PARQUET_FIXTURE.is_file() or importlib.util.find_spec("duckdb") is None,
    reason="C1 Parquet fixture and DuckDB are absent from the repository environment",
)
def test_bbox_filters_parquet_rows_when_spatial_columns_exist() -> None:
    store = APIData(
        DataPaths(
            ward_summary=MOCKS / "ward_summary.json",
            cell_scores=MOCKS / "cell_scores.geojson",
            building_metrics=PARQUET_FIXTURE,
            validation_summary=MOCKS / "validation_summary.json",
            buildings_geometry=None,
        )
    )
    try:
        result = store.get_buildings(bbox="76.8,28.4,77.4,28.9")
    except SpatialDataUnavailableError:
        pytest.skip("C1 Parquet has no coordinate columns for bbox filtering")
    assert result["type"] == "FeatureCollection"
