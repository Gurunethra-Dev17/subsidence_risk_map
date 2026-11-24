"""Synthetic tests for D6 incident validation; no real incident data is read."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
import pytest

from analytics.collapse_check import analyze_collapse_incidents, main


def _write_incidents(path: Path, rows: list[dict[str, str]]) -> Path:
    fields = ["incident_id", "lon", "lat", "city", "date", "note"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _incident(
    incident_id: str,
    lon: str,
    lat: str,
    city: str = "Delhi",
    note: str = "",
) -> dict[str, str]:
    return {
        "incident_id": incident_id,
        "lon": lon,
        "lat": lat,
        "city": city,
        "date": "2025-01-01",
        "note": note,
    }


def _write_risk_parquet(
    path: Path,
    geometries: list[object],
    categories: list[int | None],
    *,
    epsg: int = 4326,
    declared_geometry_types: list[str] | None = None,
) -> Path:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    shapely = pytest.importorskip("shapely")
    table = pa.table(
        {
            "geometry": pa.array([shapely.to_wkb(g) for g in geometries], type=pa.binary()),
            "risk_insar": pa.array(categories, type=pa.int8()),
        }
    )
    geo = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": declared_geometry_types
                if declared_geometry_types is not None
                else sorted({geometry.geom_type for geometry in geometries}),
                "crs": {"id": {"authority": "EPSG", "code": epsg}},
            }
        },
    }
    pq.write_table(table.replace_schema_metadata({b"geo": json.dumps(geo).encode()}), path)
    return path


def _write_ward_geojson(path: Path, features: list[dict]) -> Path:
    document = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _ward_feature(ward_id: str, coordinates: list) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "properties": {"ward_id": ward_id},
    }


def test_city_filter_spatial_assignment_and_c3_schema_compatibility(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(
        tmp_path / "incidents.csv",
        [
            _incident("i-1", "0.5", "0.5"),
            _incident("i-2", "2", "2"),
            _incident("i-3", "0.5", "0.5", city="Other"),
        ],
    )
    risk = _write_risk_parquet(tmp_path / "risk.parquet", [shapely.geometry.box(0, 0, 1, 1)], [2])
    ward = _write_ward_geojson(
        tmp_path / "wards.geojson",
        [_ward_feature("W1", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])],
    )
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW1,upper\n", encoding="utf-8")

    result, qa = analyze_collapse_incidents(
        incidents,
        risk_geometry_path=risk,
        ward_geometry_path=ward,
        ward_ranks_path=ranks,
        coordinates_independently_verified=True,
    )

    assert set(result) == {
        "n_incidents_total",
        "n_in_city",
        "by_published_risk",
        "by_rank_band",
        "note",
    }
    assert result["n_incidents_total"] == 3
    assert result["n_in_city"] == 2
    assert result["by_published_risk"] == {"2": 1}
    assert result["by_rank_band"] == {"upper": 1}
    assert qa["n_in_city_coordinates_valid"] == 2
    assert qa["risk_unmatched_locations"] == 1
    assert "label-based" in result["note"]
    assert "no statistical claim" in result["note"]

    root = Path(__file__).parents[2]
    c3 = json.loads((root / "contracts/mock/validation_summary.json").read_text())
    c3["collapse_check"] = result
    schema = json.loads((root / "contracts/schemas/validation_summary.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(c3)


def test_missing_and_invalid_coordinates_are_counted_not_inferred(tmp_path: Path) -> None:
    incidents = _write_incidents(
        tmp_path / "incidents.csv",
        [
            _incident("missing", "", "", note="address text includes 0.5,0.5"),
            _incident("partial", "0.5", ""),
            _incident("nonnumeric", "west", "0.5"),
            _incident("out-of-range", "181", "0.5"),
            _incident("valid-no-data", "5", "5"),
        ],
    )
    result, qa = analyze_collapse_incidents(incidents)

    assert result["n_incidents_total"] == result["n_in_city"] == 5
    assert result["by_published_risk"] == {}
    assert result["by_rank_band"] == {}
    assert qa["n_in_city_coordinates_missing"] == 1
    assert qa["n_in_city_coordinates_invalid"] == 3
    assert qa["n_in_city_coordinates_valid"] == 1
    assert qa["risk_comparison_status"] == "not_performed_coordinates_not_independently_verified"
    assert "not performed" in result["note"]
    assert "1 valid-coordinate rows remain unevaluated" in result["note"]


def test_boundary_matches_are_ambiguous_for_risk_and_ward(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(
        tmp_path / "incidents.csv",
        [_incident("shared-edge", "1", "0.5"), _incident("outer-edge", "0", "0.5")],
    )
    risk = _write_risk_parquet(
        tmp_path / "risk.parquet",
        [shapely.geometry.box(0, 0, 1, 1), shapely.geometry.box(1, 0, 2, 1)],
        [1, 2],
    )
    ward = _write_ward_geojson(
        tmp_path / "wards.geojson",
        [
            _ward_feature("W1", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]),
            _ward_feature("W2", [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]),
        ],
    )
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW1,upper\nW2,lower\n", encoding="utf-8")

    result, qa = analyze_collapse_incidents(
        incidents,
        risk_geometry_path=risk,
        ward_geometry_path=ward,
        ward_ranks_path=ranks,
        coordinates_independently_verified=True,
    )

    assert result["by_published_risk"] == {}
    assert result["by_rank_band"] == {}
    assert qa["risk_boundary_or_overlap_ambiguous"] == 2
    assert qa["ward_boundary_ambiguous"] == 2


def test_invalid_geometry_is_excluded_and_counted(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    invalid_polygon = shapely.geometry.Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    assert not invalid_polygon.is_valid
    risk = _write_risk_parquet(tmp_path / "risk.parquet", [invalid_polygon], [1])

    result, qa = analyze_collapse_incidents(
        incidents, risk_geometry_path=risk, coordinates_independently_verified=True
    )

    assert result["by_published_risk"] == {}
    assert qa["risk_invalid_geometries"] == 1
    assert qa["risk_unmatched_locations"] == 1


def test_non_wgs84_geoparquet_is_rejected(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    risk = _write_risk_parquet(
        tmp_path / "risk.parquet", [shapely.geometry.box(0, 0, 1, 1)], [1], epsg=3857
    )

    with pytest.raises(ValueError, match="epsg4326"):
        analyze_collapse_incidents(
            incidents, risk_geometry_path=risk, coordinates_independently_verified=True
        )


@pytest.mark.parametrize(
    ("geometry_type", "geometry"),
    [
        pytest.param("Point", "point", id="point"),
        pytest.param("LineString", "line", id="linestring"),
    ],
)
def test_non_polygonal_risk_geometry_is_rejected(
    tmp_path: Path, geometry_type: str, geometry: str
) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    unsupported = (
        shapely.geometry.Point(0.5, 0.5)
        if geometry == "point"
        else shapely.geometry.LineString([(0, 0), (1, 1)])
    )
    risk = _write_risk_parquet(
        tmp_path / "risk.parquet",
        [unsupported],
        [1],
        # Exercise decoded-geometry validation even if metadata is misleading.
        declared_geometry_types=["Polygon"],
    )

    with pytest.raises(ValueError, match="only_polygonal_geometries"):
        analyze_collapse_incidents(
            incidents,
            risk_geometry_path=risk,
            coordinates_independently_verified=True,
        )


def test_non_polygonal_risk_geoparquet_metadata_is_rejected(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    risk = _write_risk_parquet(
        tmp_path / "risk.parquet",
        [shapely.geometry.box(0, 0, 1, 1)],
        [1],
        declared_geometry_types=["Polygon", "Point"],
    )

    with pytest.raises(ValueError, match="only_polygonal_geometries"):
        analyze_collapse_incidents(
            incidents,
            risk_geometry_path=risk,
            coordinates_independently_verified=True,
        )


@pytest.mark.parametrize(
    ("geometry_type", "coordinates"),
    [("Polygon", []), ("MultiPolygon", [])],
)
def test_empty_risk_geometries_are_skipped(
    tmp_path: Path, geometry_type: str, coordinates: list
) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    empty_geometry = shapely.geometry.shape({"type": geometry_type, "coordinates": coordinates})
    assert empty_geometry.is_empty
    risk = _write_risk_parquet(
        tmp_path / "risk.parquet", [empty_geometry], [1], declared_geometry_types=[geometry_type]
    )

    result, qa = analyze_collapse_incidents(
        incidents,
        risk_geometry_path=risk,
        coordinates_independently_verified=True,
    )

    assert result["by_published_risk"] == {}
    assert qa["risk_empty_geometries"] == 1
    assert qa["risk_unmatched_locations"] == 1


@pytest.mark.parametrize(
    ("geometry_type", "coordinates"),
    [("Polygon", []), ("MultiPolygon", [])],
)
def test_empty_ward_geometries_are_skipped(
    tmp_path: Path, geometry_type: str, coordinates: list
) -> None:
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    ward = tmp_path / "wards.geojson"
    _write_ward_geojson(
        ward,
        [
            {
                "type": "Feature",
                "geometry": {"type": geometry_type, "coordinates": coordinates},
                "properties": {"ward_id": "W1"},
            }
        ],
    )
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW1,upper\n", encoding="utf-8")

    result, qa = analyze_collapse_incidents(
        incidents,
        ward_geometry_path=ward,
        ward_ranks_path=ranks,
        coordinates_independently_verified=True,
    )

    assert result["by_rank_band"] == {}
    assert qa["ward_empty_geometries"] == 1
    assert qa["ward_unmatched_locations"] == 1


@pytest.mark.parametrize("root", [None, [], "not an object"])
def test_geojson_non_object_roots_fail_with_controlled_error(tmp_path: Path, root) -> None:
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    ward = tmp_path / "wards.geojson"
    ward.write_text(json.dumps(root), encoding="utf-8")
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW1,upper\n", encoding="utf-8")

    with pytest.raises((TypeError, ValueError), match="geojson_root"):
        analyze_collapse_incidents(
            incidents,
            ward_geometry_path=ward,
            ward_ranks_path=ranks,
            coordinates_independently_verified=True,
        )


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"type": "FeatureCollection", "features": None},
        {"type": "FeatureCollection", "features": [None]},
        {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": [], "properties": {}}],
        },
    ],
)
def test_malformed_geojson_feature_collections_fail_safely(tmp_path: Path, document: dict) -> None:
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    ward = tmp_path / "wards.geojson"
    ward.write_text(json.dumps(document), encoding="utf-8")
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW1,upper\n", encoding="utf-8")

    with pytest.raises((TypeError, ValueError), match="geojson"):
        analyze_collapse_incidents(
            incidents,
            ward_geometry_path=ward,
            ward_ranks_path=ranks,
            coordinates_independently_verified=True,
        )


def test_invalid_geojson_syntax_fails_with_controlled_parse_error(tmp_path: Path) -> None:
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    ward = tmp_path / "wards.geojson"
    ward.write_text('{"type": "FeatureCollection",', encoding="utf-8")
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW1,upper\n", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        analyze_collapse_incidents(
            incidents,
            ward_geometry_path=ward,
            ward_ranks_path=ranks,
            coordinates_independently_verified=True,
        )


def test_missing_risk_category_and_rank_mapping_remain_unassigned(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    risk = _write_risk_parquet(
        tmp_path / "risk.parquet", [shapely.geometry.box(0, 0, 1, 1)], [None]
    )
    ward = _write_ward_geojson(
        tmp_path / "wards.geojson",
        [_ward_feature("W-unmapped", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])],
    )
    ranks = tmp_path / "ranks.csv"
    ranks.write_text("ward_id,rank_band\nW-other,lower\n", encoding="utf-8")

    result, qa = analyze_collapse_incidents(
        incidents,
        risk_geometry_path=risk,
        ward_geometry_path=ward,
        ward_ranks_path=ranks,
        coordinates_independently_verified=True,
    )

    assert result["by_published_risk"] == result["by_rank_band"] == {}
    assert qa["risk_missing_category_locations"] == 1
    assert qa["ward_rank_band_missing"] == 1


def test_spatial_comparison_is_gated_on_coordinate_provenance(tmp_path: Path) -> None:
    shapely = pytest.importorskip("shapely")
    incidents = _write_incidents(tmp_path / "incidents.csv", [_incident("i-1", "0.5", "0.5")])
    risk = _write_risk_parquet(tmp_path / "risk.parquet", [shapely.geometry.box(0, 0, 1, 1)], [1])

    result, qa = analyze_collapse_incidents(incidents, risk_geometry_path=risk)

    assert result["by_published_risk"] == {}
    assert qa["n_in_city_coordinates_valid"] == 1
    assert qa["risk_comparison_status"] == "not_performed_coordinates_not_independently_verified"
    assert qa["risk_unresolved_valid_coordinate_locations"] == 1
    assert "Numeric coordinate validity does not verify location provenance" in result["note"]
    assert "not attested" in result["note"]
    assert "No geocoding or location inference" in result["note"]


def test_cli_writes_exact_c3_object_and_separate_qa(tmp_path: Path) -> None:
    incidents = _write_incidents(
        tmp_path / "incidents.csv", [_incident("i-1", "77.1", "28.6", city="Delhi")]
    )
    output = tmp_path / "nested" / "collapse_check.json"
    qa_output = tmp_path / "nested" / "collapse_qa.json"

    assert (
        main(
            [
                "--incidents",
                str(incidents),
                "--pilot-city",
                "Delhi",
                "--output",
                str(output),
                "--qa-output",
                str(qa_output),
            ]
        )
        == 0
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    qa = json.loads(qa_output.read_text(encoding="utf-8"))
    assert set(result) == {
        "n_incidents_total",
        "n_in_city",
        "by_published_risk",
        "by_rank_band",
        "note",
    }
    assert result["n_in_city"] == 1
    assert result["by_published_risk"] == result["by_rank_band"] == {}
    assert qa["n_in_city_coordinates_valid"] == 1
    assert qa["risk_comparison_status"] == "not_performed_coordinates_not_independently_verified"
    assert "not attested" in result["note"]
