"""Conservative collapse-incident comparison against published risk and ward ranks.

Coordinates are used only when they are present and geographically valid in the
incident CSV. The module never geocodes addresses or interprets free-text notes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_INCIDENT_COLUMNS = {"incident_id", "lon", "lat", "city", "date", "note"}
_RISK_FIELD_ALIASES = {
    "riskinsar": "risk_insar",
    "risk10yrs": "risk_10yrs",
    "risk30yrs": "risk_30yrs",
    "risk50yrs": "risk_50yrs",
}
_C3_NOTE = (
    "Any risk overlay is a spatial association, not a building-level match or causal "
    "validation. This descriptive cross-check supports no statistical claim, and collapse "
    "causes are not attributed to subsidence."
)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _coordinate_status(row: dict[str, str]) -> tuple[str, tuple[float, float] | None]:
    lon_text = (row.get("lon") or "").strip()
    lat_text = (row.get("lat") or "").strip()
    if not lon_text and not lat_text:
        return "missing", None
    if not lon_text or not lat_text:
        return "invalid", None
    try:
        lon, lat = float(lon_text), float(lat_text)
    except (TypeError, ValueError, OverflowError):
        return "invalid", None
    if not math.isfinite(lon) or not math.isfinite(lat):
        return "invalid", None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return "invalid", None
    return "valid", (lon, lat)


def _read_incidents(path: Path, pilot_city: str) -> tuple[list[dict[str, str]], dict[str, int]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or ())
        missing = _INCIDENT_COLUMNS - columns
        if missing:
            raise ValueError("incident_csv_missing_required_columns")
        rows = [dict(row) for row in reader]

    city_key = pilot_city.strip().casefold()
    selected = [row for row in rows if (row.get("city") or "").strip().casefold() == city_key]
    all_coordinate_counts = Counter(_coordinate_status(row)[0] for row in rows)
    coordinate_counts = Counter(_coordinate_status(row)[0] for row in selected)
    qa = {
        "n_incidents_total": len(rows),
        "n_in_city_by_source_label": len(selected),
        "n_all_coordinates_valid": all_coordinate_counts["valid"],
        "n_all_coordinates_missing": all_coordinate_counts["missing"],
        "n_all_coordinates_invalid": all_coordinate_counts["invalid"],
        "n_in_city_coordinates_valid": coordinate_counts["valid"],
        "n_in_city_coordinates_missing": coordinate_counts["missing"],
        "n_in_city_coordinates_invalid": coordinate_counts["invalid"],
    }
    return selected, qa


def _load_shapely() -> tuple[Any, Any, Any, Any]:
    try:
        from shapely import wkb
        from shapely.errors import GEOSException
        from shapely.geometry import Point, shape
    except ImportError as exc:  # pragma: no cover - depends on the optional geo extra
        raise RuntimeError("Spatial comparison requires the project geo dependencies") from exc
    return wkb, Point, shape, GEOSException


def _check_crs4326(crs: Any) -> bool:
    if not isinstance(crs, dict):
        return False
    identifier = crs.get("id")
    if isinstance(identifier, dict):
        return (
            str(identifier.get("authority", "")).casefold() == "epsg"
            and str(identifier.get("code", "")) == "4326"
        )
    name = str(crs.get("name", "")).casefold()
    return name in {"epsg:4326", "urn:ogc:def:crs:epsg::4326", "ogc:crs84"}


def _geoparquet_crs(path: Path, geometry_column: str, *, polygonal_only: bool = False) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on the optional geo extra
        raise RuntimeError("GeoParquet comparison requires the project geo dependencies") from exc
    metadata = pq.ParquetFile(path).schema_arrow.metadata or {}
    try:
        geo = json.loads(metadata[b"geo"].decode("utf-8"))
        primary = geo["primary_column"]
        geometry = geo["columns"][primary]
        crs = geometry["crs"]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("geoparquet_metadata_invalid") from exc
    if primary.casefold() != geometry_column.casefold() or not _check_crs4326(crs):
        raise ValueError("geometry_input_must_declare_epsg4326")
    if polygonal_only:
        geometry_types = geometry.get("geometry_types")
        allowed_types = {"Polygon", "MultiPolygon"}
        if isinstance(geometry_types, list) and any(
            geometry_type not in allowed_types for geometry_type in geometry_types
        ):
            raise ValueError("published_risk_geometry_must_contain_only_polygonal_geometries")


def _iter_geoparquet(
    path: Path, property_name: str, geometry_column: str, *, polygonal_only: bool = False
) -> Iterable[tuple[Any, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on the optional geo extra
        raise RuntimeError("GeoParquet comparison requires the project geo dependencies") from exc

    parquet = pq.ParquetFile(path)
    _geoparquet_crs(path, geometry_column, polygonal_only=polygonal_only)
    names = {_key(name): name for name in parquet.schema_arrow.names}
    geometry_name = names.get(_key(geometry_column))
    property_actual = names.get(_key(property_name))
    if geometry_name is None:
        raise ValueError("geometry_column_missing")
    if property_actual is None:
        raise ValueError("spatial_property_column_missing")
    wkb, _, _, geos_exception = _load_shapely()
    for batch in parquet.iter_batches(batch_size=1024, columns=[geometry_name, property_actual]):
        geometries = batch.column(0).to_pylist()
        properties = batch.column(1).to_pylist()
        for encoded, value in zip(geometries, properties, strict=True):
            if encoded is None:
                yield None, value
            else:
                try:
                    yield wkb.loads(bytes(encoded)), value
                except (geos_exception, ValueError, TypeError):
                    yield "__invalid_geometry__", value


def _iter_geojson(
    path: Path, property_name: str, geometry_column: str = "geometry"
) -> Iterable[tuple[Any, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("geojson_root_must_be_an_object")
    if document.get("type") != "FeatureCollection":
        raise ValueError("geojson_root_must_be_a_feature_collection")
    crs_spec = document.get("crs")
    # RFC 7946 GeoJSON without a crs member is WGS84 longitude/latitude.
    if crs_spec is not None:
        try:
            crs_name = crs_spec["properties"]["name"]
        except (KeyError, TypeError) as exc:
            raise ValueError("geojson_crs_invalid") from exc
        if not _check_crs4326({"name": crs_name}):
            raise ValueError("geometry_input_must_declare_epsg4326")
    features = document.get("features")
    if not isinstance(features, list):
        raise TypeError("geojson_features_must_be_an_array")
    _, _, shape, geos_exception = _load_shapely()
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("geojson_feature_must_be_a_feature_object")
        properties = feature.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise ValueError("geojson_feature_properties_must_be_an_object")
        geometry = feature.get(geometry_column)
        value = None
        if isinstance(properties, dict):
            value = next(
                (item for key, item in properties.items() if _key(key) == _key(property_name)),
                None,
            )
        if geometry is None:
            yield None, value
            continue
        if not isinstance(geometry, dict):
            raise TypeError("geojson_feature_geometry_must_be_an_object_or_null")
        try:
            yield shape(geometry), value
        except (geos_exception, ValueError, TypeError):
            yield "__invalid_geometry__", value


def _geometry_records(path: Path, property_name: str) -> Iterable[tuple[Any, Any]]:
    suffix = path.suffix.casefold()
    if suffix == ".parquet":
        yield from _iter_geoparquet(path, property_name, "geometry")
    elif suffix in {".json", ".geojson"}:
        yield from _iter_geojson(path, property_name)
    else:
        raise ValueError("geometry_input_must_be_geoparquet_or_geojson")


def _category(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not number.is_integer() or not 0 <= number <= 4:
        return None
    return str(int(number))


def _valid_incident_points(
    incidents: list[dict[str, str]],
) -> tuple[list[tuple[int, Any, tuple[float, float]]], Any, int]:
    _, Point, _, _ = _load_shapely()
    points = []
    invalid_count = 0
    for index, row in enumerate(incidents):
        status, coordinates = _coordinate_status(row)
        if status == "invalid":
            invalid_count += 1
        elif coordinates is not None:
            points.append((index, Point(*coordinates), coordinates))
    return points, Point, invalid_count


def _assign_risk(
    incidents: list[dict[str, str]], risk_geometry: Path, risk_field: str
) -> tuple[Counter[str], dict[str, int]]:
    if risk_geometry.suffix.casefold() != ".parquet":
        raise ValueError("published_risk_geometry_must_be_geoparquet")
    points, _, invalid_coordinates = _valid_incident_points(incidents)
    state = {
        index: {"matches": 0, "category": None, "bad_category": False, "boundary": False}
        for index, _, _ in points
    }
    qa = {
        "risk_geometry_features": 0,
        "risk_invalid_geometries": 0,
        "risk_invalid_categories": 0,
        "risk_unmatched_locations": 0,
        "risk_boundary_or_overlap_ambiguous": 0,
        "risk_missing_category_locations": 0,
        "risk_coordinates_invalid": invalid_coordinates,
    }
    for geometry, value in _iter_geoparquet(
        risk_geometry, risk_field, "geometry", polygonal_only=True
    ):
        qa["risk_geometry_features"] += 1
        if geometry is None or geometry == "__invalid_geometry__":
            qa["risk_invalid_geometries"] += 1
            continue
        if geometry.is_empty:
            qa["risk_empty_geometries"] = qa.get("risk_empty_geometries", 0) + 1
            continue
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("published_risk_geometry_must_contain_only_polygonal_geometries")
        if not geometry.is_valid:
            qa["risk_invalid_geometries"] += 1
            continue
        category = _category(value)
        if value is not None and category is None:
            qa["risk_invalid_categories"] += 1
        min_x, min_y, max_x, max_y = geometry.bounds
        for index, point, (lon, lat) in points:
            if min_x <= lon <= max_x and min_y <= lat <= max_y and geometry.covers(point):
                state[index]["matches"] += 1
                state[index]["category"] = category
                state[index]["bad_category"] = category is None
                state[index]["boundary"] = state[index]["boundary"] or geometry.boundary.covers(
                    point
                )

    counts: Counter[str] = Counter()
    for item in state.values():
        if item["matches"] == 0:
            qa["risk_unmatched_locations"] += 1
        elif item["matches"] > 1 or item["boundary"]:
            qa["risk_boundary_or_overlap_ambiguous"] += 1
        elif item["bad_category"]:
            qa["risk_missing_category_locations"] += 1
        else:
            counts[item["category"]] += 1
    return counts, qa


def _read_rank_bands(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"ward_id", "rank_band"}.issubset(reader.fieldnames or []):
            raise ValueError("ward_rank_csv_requires_ward_id_and_rank_band")
        result: dict[str, str] = {}
        for row in reader:
            ward_id = (row.get("ward_id") or "").strip()
            rank_band = (row.get("rank_band") or "").strip()
            if not ward_id or not rank_band or ward_id in result:
                raise ValueError("ward_rank_csv_has_invalid_or_duplicate_rows")
            result[ward_id] = rank_band
    return result


def _assign_rank_bands(
    incidents: list[dict[str, str]], ward_geometry: Path, ward_ranks: Path
) -> tuple[Counter[str], dict[str, int]]:
    points, _, invalid_coordinates = _valid_incident_points(incidents)
    bands = _read_rank_bands(ward_ranks)
    state = {index: {"matches": 0, "ward_id": None, "boundary": False} for index, _, _ in points}
    qa = {
        "ward_geometry_features": 0,
        "ward_invalid_geometries": 0,
        "ward_unmatched_locations": 0,
        "ward_boundary_ambiguous": 0,
        "ward_rank_band_missing": 0,
        "ward_coordinates_invalid": invalid_coordinates,
    }
    for geometry, ward_id_value in _geometry_records(ward_geometry, "ward_id"):
        qa["ward_geometry_features"] += 1
        if geometry is None or geometry == "__invalid_geometry__":
            qa["ward_invalid_geometries"] += 1
            continue
        if geometry.is_empty:
            qa["ward_empty_geometries"] = qa.get("ward_empty_geometries", 0) + 1
            continue
        if not geometry.is_valid:
            qa["ward_invalid_geometries"] += 1
            continue
        ward_id = str(ward_id_value).strip() if ward_id_value is not None else ""
        min_x, min_y, max_x, max_y = geometry.bounds
        for index, point, (lon, lat) in points:
            if min_x <= lon <= max_x and min_y <= lat <= max_y and geometry.covers(point):
                state[index]["matches"] += 1
                state[index]["ward_id"] = ward_id
                state[index]["boundary"] = state[index]["boundary"] or geometry.boundary.covers(
                    point
                )

    counts: Counter[str] = Counter()
    for item in state.values():
        if item["matches"] == 0:
            qa["ward_unmatched_locations"] += 1
        elif item["matches"] > 1 or item["boundary"]:
            qa["ward_boundary_ambiguous"] += 1
        elif item["ward_id"] not in bands:
            qa["ward_rank_band_missing"] += 1
        else:
            counts[bands[item["ward_id"]]] += 1
    return counts, qa


def analyze_collapse_incidents(
    incidents_path: str | Path,
    *,
    pilot_city: str = "Delhi",
    risk_geometry_path: str | Path | None = None,
    risk_field: str = "risk_insar",
    ward_geometry_path: str | Path | None = None,
    ward_ranks_path: str | Path | None = None,
    coordinates_independently_verified: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the exact C3 ``collapse_check`` object and separate aggregate QA."""
    incidents, qa = _read_incidents(Path(incidents_path), pilot_city)
    risk_counts: Counter[str] = Counter()
    rank_counts: Counter[str] = Counter()
    if risk_geometry_path is not None and coordinates_independently_verified:
        risk_counts, risk_qa = _assign_risk(incidents, Path(risk_geometry_path), risk_field)
        qa.update(risk_qa)
        qa["risk_assigned_locations"] = sum(risk_counts.values())
        qa["risk_unresolved_valid_coordinate_locations"] = max(
            0, qa["n_in_city_coordinates_valid"] - qa["risk_assigned_locations"]
        )
    else:
        qa["risk_comparison_status"] = (
            "not_performed_coordinates_not_independently_verified"
            if not coordinates_independently_verified
            else "not_performed_no_risk_geometry"
        )
        qa["risk_assigned_locations"] = 0
        qa["risk_unresolved_valid_coordinate_locations"] = qa["n_in_city_coordinates_valid"]

    if (
        ward_geometry_path is not None
        and ward_ranks_path is not None
        and coordinates_independently_verified
    ):
        rank_counts, rank_qa = _assign_rank_bands(
            incidents, Path(ward_geometry_path), Path(ward_ranks_path)
        )
        qa.update(rank_qa)
        qa["rank_band_assigned_locations"] = sum(rank_counts.values())
        qa["rank_band_unresolved_valid_coordinate_locations"] = max(
            0, qa["n_in_city_coordinates_valid"] - qa["rank_band_assigned_locations"]
        )
    else:
        qa["rank_comparison_status"] = (
            "not_performed_coordinates_not_independently_verified"
            if not coordinates_independently_verified
            else "not_performed_missing_ward_geometry_or_rank_bands"
        )
        qa["rank_band_assigned_locations"] = 0
        qa["rank_band_unresolved_valid_coordinate_locations"] = qa["n_in_city_coordinates_valid"]

    note_parts = [
        f"Filtered by source city label {pilot_city!r}; n_in_city is label-based, not spatially confirmed."
    ]
    note_parts.append(
        "Coordinate QA for in-city rows: "
        f"{qa['n_in_city_coordinates_valid']} valid, "
        f"{qa['n_in_city_coordinates_missing']} missing, "
        f"{qa['n_in_city_coordinates_invalid']} invalid."
    )
    note_parts.append(
        "Incident totals count CSV data rows, and in-city totals use the source city label; "
        "differences from externally reported source counts are not reconciled without input provenance."
    )
    if not coordinates_independently_verified:
        note_parts.append(
            "Numeric coordinate validity does not verify location provenance; spatial "
            "comparisons remain unresolved unless the operator explicitly attests that "
            "coordinates were independently verified. No geocoding or location inference is performed."
        )
    else:
        note_parts.append(
            "The operator attested to independent coordinate verification; this tool checks "
            "numeric syntax and geographic range only and does not verify provenance itself."
        )
    if not coordinates_independently_verified:
        note_parts.append(
            "Published-risk comparison was not performed because coordinate provenance was "
            "not attested; "
            f"{qa['risk_unresolved_valid_coordinate_locations']} valid-coordinate rows remain unevaluated."
        )
    elif risk_geometry_path is None:
        note_parts.append(
            "Published-risk comparison was not performed because risk geometry was not supplied; "
            f"{qa['risk_unresolved_valid_coordinate_locations']} valid-coordinate rows remain unevaluated."
        )
    else:
        note_parts.append(
            f"Published-risk comparison using field {risk_field!r} assigned "
            f"{qa['risk_assigned_locations']} valid-coordinate "
            f"rows; {qa['risk_unresolved_valid_coordinate_locations']} remain unresolved due to "
            "unmatched, invalid, missing-category, or boundary/overlap-ambiguous locations."
        )
    if not coordinates_independently_verified:
        note_parts.append(
            "Rank-band comparison was not performed because coordinate provenance was "
            "not attested; "
            f"{qa['rank_band_unresolved_valid_coordinate_locations']} valid-coordinate rows remain unevaluated."
        )
    elif ward_geometry_path is None or ward_ranks_path is None:
        note_parts.append(
            "Rank-band comparison was not performed because ward geometry and rank bands were "
            "not both supplied; "
            f"{qa['rank_band_unresolved_valid_coordinate_locations']} valid-coordinate rows "
            "remain unevaluated."
        )
    else:
        note_parts.append(
            f"Rank-band comparison assigned {qa['rank_band_assigned_locations']} "
            f"valid-coordinate rows; {qa['rank_band_unresolved_valid_coordinate_locations']} "
            "remain unresolved due to unmatched or boundary-ambiguous locations."
        )
    note_parts.append(_C3_NOTE)

    collapse_check = {
        "n_incidents_total": qa["n_incidents_total"],
        "n_in_city": qa["n_in_city_by_source_label"],
        "by_published_risk": dict(sorted(risk_counts.items())),
        "by_rank_band": dict(sorted(rank_counts.items())),
        "note": " ".join(note_parts),
    }
    return collapse_check, qa


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a conservative C3 collapse_check. Numeric coordinate validity is not "
            "independent location verification; spatial comparison requires the explicit "
            "--coordinates-independently-verified operator attestation. No geocoding is performed."
        )
    )
    parser.add_argument("--incidents", type=Path, required=True, help="C0 collapse_incidents.csv")
    parser.add_argument("--risk-geometry", type=Path, help="Published-risk GeoParquet")
    parser.add_argument(
        "--risk-field",
        default="risk_insar",
        help="Published risk category field (default: risk_insar)",
    )
    parser.add_argument("--ward-geometry", type=Path, help="EPSG:4326 ward GeoJSON or GeoParquet")
    parser.add_argument("--ward-ranks", type=Path, help="CSV with ward_id,rank_band columns")
    parser.add_argument(
        "--pilot-city", default="Delhi", help="Source city label to include (default: Delhi)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSON containing only C3 collapse_check fields",
    )
    parser.add_argument(
        "--qa-output", type=Path, help="Optional aggregate-only coordinate/spatial QA JSON"
    )
    parser.add_argument(
        "--coordinates-independently-verified",
        action="store_true",
        help=(
            "Attest that source coordinates were independently verified; required before "
            "spatial comparison. This does not geocode or verify locations itself."
        ),
    )
    args = parser.parse_args(argv)

    try:
        result, qa = analyze_collapse_incidents(
            args.incidents,
            pilot_city=args.pilot_city,
            risk_geometry_path=args.risk_geometry,
            risk_field=args.risk_field,
            ward_geometry_path=args.ward_geometry,
            ward_ranks_path=args.ward_ranks,
            coordinates_independently_verified=args.coordinates_independently_verified,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if args.qa_output is not None:
            args.qa_output.parent.mkdir(parents=True, exist_ok=True)
            args.qa_output.write_text(
                json.dumps(qa, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Wrote C3 collapse_check output: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI tests
    sys.exit(main())
