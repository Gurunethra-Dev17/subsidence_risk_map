"""Validate completed C0 data packs for the B10 quality gate."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pipeline.manifest import REQUIRED_PACK_FILES, row_count, sha256_file
from pipeline.paths import pack_destination

WARD_FILE = "wards.geojson"
BUILDINGS_FILE = "buildings.parquet"
VLM_FILE = "vlm_points.parquet"
VT_RISK_FILE = "vt_building_risk.parquet"
GRID_FILE = "grid_250m.geojson"
INCIDENTS_FILE = "collapse_incidents.csv"
MANIFEST_FILE = "PACK_MANIFEST.json"


REQUIRED_COLUMNS = {
    WARD_FILE: {"ward_id", "ward_name", "city", "source", "source_year"},
    BUILDINGS_FILE: {"bldg_id", "footprint_m2", "source", "ward_id", "cell_id"},
    VLM_FILE: {"pt_id", "lon", "lat", "vlm_mm_yr", "source"},
    VT_RISK_FILE: {"bldg_id", "risk_insar", "risk_10yrs", "risk_30yrs", "risk_50yrs"},
    GRID_FILE: {"cell_id", "ward_id"},
    INCIDENTS_FILE: {"incident_id", "lon", "lat", "city", "date", "note"},
}


def _load_geo(path: Path) -> Any:
    import geopandas as gpd

    return gpd.read_parquet(path) if path.suffix.lower() == ".parquet" else gpd.read_file(path)


def _id_errors(label: str, values: Any, errors: list[str]) -> None:
    if values.isna().any():
        errors.append(f"{label}: contains null IDs")
    if values.duplicated().any():
        errors.append(f"{label}: contains duplicate IDs")


def _manifest_findings(pack_dir: Path, errors: list[str], warnings: list[str]) -> None:
    manifest_path = pack_dir / MANIFEST_FILE
    if not manifest_path.exists():
        errors.append(f"Missing {MANIFEST_FILE}")
        return
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    schema_path = Path(__file__).resolve().parents[1] / "contracts" / "schemas" / "pack_manifest.schema.json"
    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    schema_errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: list(error.path),
    )
    errors.extend(
        f"{MANIFEST_FILE} {'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
        for error in schema_errors
    )
    entries = {item.get("name"): item for item in manifest.get("files", []) if isinstance(item, dict)}
    for name in sorted(REQUIRED_PACK_FILES):
        path, entry = pack_dir / name, entries.get(name)
        if not path.exists() or entry is None:
            continue
        if sha256_file(path) != entry.get("sha256"):
            errors.append(f"{name}: SHA-256 does not match {MANIFEST_FILE}")
        try:
            actual_rows = row_count(path)
            if actual_rows != entry.get("rows"):
                errors.append(f"{name}: manifest row count {entry.get('rows')} != actual {actual_rows}")
        except (ValueError, RuntimeError) as exc:
            errors.append(f"{name}: cannot count rows ({exc})")
    warnings.extend(
        f"Manifest includes a file outside the C0 v1.0 pack list: {filename}"
        for filename in entries if filename not in REQUIRED_PACK_FILES
    )


def _row_findings(pack_dir: Path, errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for filename in sorted(REQUIRED_PACK_FILES):
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            counts[filename] = row_count(path)
            if counts[filename] == 0:
                errors.append(f"{filename}: required C0 data file is empty")
        except (ValueError, RuntimeError) as exc:
            errors.append(f"{filename}: cannot count rows ({exc})")
    return counts


def _geo_findings(pack_dir: Path, expected_wards: int | None, errors: list[str]) -> None:
    filenames = (WARD_FILE, BUILDINGS_FILE, VT_RISK_FILE, GRID_FILE)
    for filename in filenames:
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            frame = _load_geo(path)
        except Exception as exc:
            errors.append(f"{filename}: cannot read geospatial layer ({exc})")
            continue
        _geo_structure_findings(filename, frame, errors)
        _geo_content_findings(filename, frame, expected_wards, errors)


def _geo_structure_findings(filename: str, frame: Any, errors: list[str]) -> None:
    missing = sorted(REQUIRED_COLUMNS[filename] - set(frame.columns))
    if missing:
        errors.append(f"{filename}: missing required columns: {', '.join(missing)}")
    if frame.crs is None:
        errors.append(f"{filename}: missing CRS")
    elif frame.crs.to_epsg() != 4326:
        errors.append(f"{filename}: CRS must be EPSG:4326, found {frame.crs}")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        errors.append(f"{filename}: contains null or empty geometry")
    if not frame.geometry.is_valid.all():
        errors.append(f"{filename}: contains invalid geometry")
    if filename in {WARD_FILE, BUILDINGS_FILE} and not frame.geometry.geom_type.isin(
        {"Polygon", "MultiPolygon"}
    ).all():
        errors.append(f"{filename}: geometry must contain only polygons or multipolygons")


def _geo_content_findings(filename: str, frame: Any, expected_wards: int | None, errors: list[str]) -> None:
    if filename == WARD_FILE:
        _ward_content_findings(frame, expected_wards, errors)
    elif filename == BUILDINGS_FILE:
        _building_content_findings(frame, errors)
    elif filename == GRID_FILE:
        _grid_content_findings(frame, errors)
    elif filename == VT_RISK_FILE:
        _risk_value_findings(frame, errors)


def _ward_content_findings(frame: Any, expected_wards: int | None, errors: list[str]) -> None:
    if "ward_id" not in frame:
        return
    _id_errors(f"{WARD_FILE} ward_id", frame["ward_id"], errors)
    if expected_wards is not None and len(frame) != expected_wards:
        errors.append(f"{WARD_FILE}: expected {expected_wards} rows, found {len(frame)}")


def _building_content_findings(frame: Any, errors: list[str]) -> None:
    if "bldg_id" not in frame:
        return
    _id_errors(f"{BUILDINGS_FILE} bldg_id", frame["bldg_id"], errors)
    _building_source_findings(frame, errors)
    _building_area_findings(frame, errors)


def _building_source_findings(frame: Any, errors: list[str]) -> None:
    allowed = {"osm", "google", "microsoft", "esri", "vt"}
    if "source" in frame and not frame["source"].isin(allowed).all():
        errors.append(f"{BUILDINGS_FILE}: source contains values outside the C0 source enum")


def _building_area_findings(frame: Any, errors: list[str]) -> None:
    if "footprint_m2" not in frame:
        return
    invalid_area = (frame["footprint_m2"] <= 0).any() or frame["footprint_m2"].isna().any()
    if invalid_area:
        errors.append(f"{BUILDINGS_FILE}: footprint_m2 must be positive and non-null")


def _grid_content_findings(frame: Any, errors: list[str]) -> None:
    if "cell_id" in frame:
        _id_errors(f"{GRID_FILE} cell_id", frame["cell_id"], errors)


def _risk_value_findings(frame: Any, errors: list[str]) -> None:
    for column in ("risk_insar", "risk_10yrs", "risk_30yrs", "risk_50yrs"):
        if column in frame:
            values = frame[column].dropna()
            if not values.isin({0, 1, 2, 3, 4}).all():
                errors.append(f"{VT_RISK_FILE}: {column} values must be 0-4 or null")


def _table_findings(pack_dir: Path, errors: list[str]) -> None:
    import pandas as pd

    for filename in (VLM_FILE, INCIDENTS_FILE):
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            table = pd.read_csv(path) if filename == INCIDENTS_FILE else pd.read_parquet(path)
        except Exception as exc:
            errors.append(f"{filename}: cannot read table ({exc})")
            continue
        missing = sorted(REQUIRED_COLUMNS[filename] - set(table.columns))
        if missing:
            errors.append(f"{filename}: missing required columns: {', '.join(missing)}")
            continue
        id_column = "pt_id" if filename == VLM_FILE else "incident_id"
        _id_errors(f"{filename} {id_column}", table[id_column], errors)
        if filename == VLM_FILE:
            _vlm_findings(table, pd, errors)
        else:
            _incident_findings(table, pd, errors)


def _vlm_findings(table: Any, pd: Any, errors: list[str]) -> None:
    for column in ("lon", "lat", "vlm_mm_yr"):
        values = pd.to_numeric(table[column], errors="coerce")
        if not values.map(lambda value: math.isfinite(float(value))).all():
            errors.append(f"{VLM_FILE}: {column} must contain finite numbers")
    lon = pd.to_numeric(table["lon"], errors="coerce")
    lat = pd.to_numeric(table["lat"], errors="coerce")
    if lon.between(-180, 180).eq(False).any() or lat.between(-90, 90).eq(False).any():
        errors.append(f"{VLM_FILE}: longitude/latitude outside geographic bounds")
    if not table["source"].eq("vt-in-v2").all():
        errors.append(f"{VLM_FILE}: source must be vt-in-v2")


def _incident_findings(table: Any, pd: Any, errors: list[str]) -> None:
    lon_null, lat_null = table["lon"].isna(), table["lat"].isna()
    if (lon_null ^ lat_null).any():
        errors.append(f"{INCIDENTS_FILE}: lon and lat must both be null or both present")
    present = ~lon_null & ~lat_null
    lon = pd.to_numeric(table.loc[present, "lon"], errors="coerce")
    lat = pd.to_numeric(table.loc[present, "lat"], errors="coerce")
    if not lon.between(-180, 180).all() or not lat.between(-90, 90).all():
        errors.append(f"{INCIDENTS_FILE}: longitude/latitude outside geographic bounds")


def validate_pack(pack_dir: Path, expected_wards: int | None = None) -> dict[str, Any]:
    """Return a structured C0 quality report; raise no error for data findings."""
    pack_dir = pack_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not pack_dir.is_dir():
        raise FileNotFoundError(pack_dir)
    present = {path.name for path in pack_dir.iterdir() if path.is_file() and path.name != MANIFEST_FILE}
    errors.extend(f"Missing required C0 file: {name}" for name in sorted(REQUIRED_PACK_FILES - present))
    _manifest_findings(pack_dir, errors, warnings)
    row_counts = _row_findings(pack_dir, errors)
    _geo_findings(pack_dir, expected_wards, errors)
    _table_findings(pack_dir, errors)

    return {
        "contract": "C0@1.0",
        "pack_dir": str(pack_dir),
        "status": "fail" if errors else "pass",
        "rows": row_counts,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a completed C0 data pack.")
    parser.add_argument("pack_dir", type=Path)
    parser.add_argument("--expected-wards", type=int)
    parser.add_argument("--report", type=Path, help="Optional JSON report path inside pack_dir")
    args = parser.parse_args()

    report = validate_pack(args.pack_dir, expected_wards=args.expected_wards)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        report_path = pack_destination(args.pack_dir, args.report, "quality-report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
