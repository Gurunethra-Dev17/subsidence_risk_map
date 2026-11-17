"""Validate completed C0 data packs for the B10 quality gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pipeline.manifest import REQUIRED_PACK_FILES, row_count


REQUIRED_COLUMNS = {
    "wards.geojson": {"ward_id", "ward_name", "city", "source", "source_year"},
    "buildings.parquet": {"bldg_id", "footprint_m2", "source", "ward_id", "cell_id"},
    "vlm_points.parquet": {"pt_id", "lon", "lat", "vlm_mm_yr", "source"},
    "vt_building_risk.parquet": {"bldg_id", "risk_insar", "risk_10yrs", "risk_30yrs", "risk_50yrs"},
    "grid_250m.geojson": {"cell_id", "ward_id"},
    "collapse_incidents.csv": {"incident_id", "lon", "lat", "city", "date", "note"},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_geo(path: Path) -> Any:
    import geopandas as gpd

    return gpd.read_parquet(path) if path.suffix.lower() == ".parquet" else gpd.read_file(path)


def _id_errors(label: str, values: Any, errors: list[str]) -> None:
    if values.isna().any():
        errors.append(f"{label}: contains null IDs")
    if values.duplicated().any():
        errors.append(f"{label}: contains duplicate IDs")


def validate_pack(pack_dir: Path, expected_wards: int | None = None) -> dict[str, Any]:
    """Return a structured C0 quality report; raise no error for data findings."""
    pack_dir = pack_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    files = sorted(path for path in pack_dir.iterdir() if path.is_file()) if pack_dir.is_dir() else []
    if not pack_dir.is_dir():
        raise FileNotFoundError(pack_dir)

    present = {path.name for path in files if path.name != "PACK_MANIFEST.json"}
    for missing in sorted(REQUIRED_PACK_FILES - present):
        errors.append(f"Missing required C0 file: {missing}")

    manifest_path = pack_dir / "PACK_MANIFEST.json"
    manifest = None
    if not manifest_path.exists():
        errors.append("Missing PACK_MANIFEST.json")
    else:
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
            f"PACK_MANIFEST.json {'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
            for error in schema_errors
        )
        manifest_entries = {item.get("name"): item for item in manifest.get("files", []) if isinstance(item, dict)}
        for name in sorted(REQUIRED_PACK_FILES):
            path = pack_dir / name
            entry = manifest_entries.get(name)
            if not path.exists() or entry is None:
                continue
            actual_hash = _sha256(path)
            if actual_hash != entry.get("sha256"):
                errors.append(f"{name}: SHA-256 does not match PACK_MANIFEST.json")
            try:
                actual_rows = row_count(path)
                if actual_rows != entry.get("rows"):
                    errors.append(f"{name}: manifest row count {entry.get('rows')} != actual {actual_rows}")
            except (ValueError, RuntimeError) as exc:
                errors.append(f"{name}: cannot count rows ({exc})")
        for filename, entry in manifest_entries.items():
            if filename not in REQUIRED_PACK_FILES:
                warnings.append(f"Manifest includes a file outside the C0 v1.0 pack list: {filename}")

    row_counts: dict[str, int] = {}
    for filename in sorted(REQUIRED_PACK_FILES):
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            row_counts[filename] = row_count(path)
            if row_counts[filename] == 0:
                errors.append(f"{filename}: required C0 data file is empty")
        except (ValueError, RuntimeError) as exc:
            errors.append(f"{filename}: cannot count rows ({exc})")

    for filename in ("wards.geojson", "buildings.parquet", "vt_building_risk.parquet", "grid_250m.geojson"):
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            frame = _load_geo(path)
        except Exception as exc:
            errors.append(f"{filename}: cannot read geospatial layer ({exc})")
            continue
        missing_columns = sorted(REQUIRED_COLUMNS[filename] - set(frame.columns))
        if missing_columns:
            errors.append(f"{filename}: missing required columns: {', '.join(missing_columns)}")
        if frame.crs is None:
            errors.append(f"{filename}: missing CRS")
        elif frame.crs.to_epsg() != 4326:
            errors.append(f"{filename}: CRS must be EPSG:4326, found {frame.crs}")
        if frame.geometry.isna().any() or frame.geometry.is_empty.any():
            errors.append(f"{filename}: contains null or empty geometry")
        if not frame.geometry.is_valid.all():
            errors.append(f"{filename}: contains invalid geometry")
        if filename in {"wards.geojson", "buildings.parquet"} and not frame.geometry.geom_type.isin(
            {"Polygon", "MultiPolygon"}
        ).all():
            errors.append(f"{filename}: geometry must contain only polygons or multipolygons")
        if filename == "wards.geojson" and "ward_id" in frame:
            _id_errors("wards.geojson ward_id", frame["ward_id"], errors)
            if expected_wards is not None and len(frame) != expected_wards:
                errors.append(f"wards.geojson: expected {expected_wards} rows, found {len(frame)}")
        elif filename == "buildings.parquet" and "bldg_id" in frame:
            _id_errors("buildings.parquet bldg_id", frame["bldg_id"], errors)
            allowed_sources = {"osm", "google", "microsoft", "esri", "vt"}
            if "source" in frame and not frame["source"].isin(allowed_sources).all():
                errors.append("buildings.parquet: source contains values outside the C0 source enum")
            if "footprint_m2" in frame and ((frame["footprint_m2"] <= 0).any() or frame["footprint_m2"].isna().any()):
                errors.append("buildings.parquet: footprint_m2 must be positive and non-null")
        elif filename == "grid_250m.geojson" and "cell_id" in frame:
            _id_errors("grid_250m.geojson cell_id", frame["cell_id"], errors)
        elif filename == "vt_building_risk.parquet":
            for column in ("risk_insar", "risk_10yrs", "risk_30yrs", "risk_50yrs"):
                if column in frame:
                    values = frame[column].dropna()
                    if not values.isin({0, 1, 2, 3, 4}).all():
                        errors.append(f"vt_building_risk.parquet: {column} values must be 0-4 or null")

    for filename in ("vlm_points.parquet", "collapse_incidents.csv"):
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            if filename.endswith(".csv"):
                import pandas as pd

                table = pd.read_csv(path)
            else:
                import pandas as pd

                table = pd.read_parquet(path)
        except Exception as exc:
            errors.append(f"{filename}: cannot read table ({exc})")
            continue
        missing_columns = sorted(REQUIRED_COLUMNS[filename] - set(table.columns))
        if missing_columns:
            errors.append(f"{filename}: missing required columns: {', '.join(missing_columns)}")
            continue
        id_column = "pt_id" if filename == "vlm_points.parquet" else "incident_id"
        _id_errors(f"{filename} {id_column}", table[id_column], errors)
        if filename == "vlm_points.parquet":
            for column in ("lon", "lat", "vlm_mm_yr"):
                values = pd.to_numeric(table[column], errors="coerce")
                if not values.map(lambda value: math.isfinite(float(value))).all():
                    errors.append(f"vlm_points.parquet: {column} must contain finite numbers")
            if (
                pd.to_numeric(table["lon"], errors="coerce").between(-180, 180).eq(False).any()
                or pd.to_numeric(table["lat"], errors="coerce").between(-90, 90).eq(False).any()
            ):
                errors.append("vlm_points.parquet: longitude/latitude outside geographic bounds")
            if not table["source"].eq("vt-in-v2").all():
                errors.append("vlm_points.parquet: source must be vt-in-v2")
        else:
            lon_null, lat_null = table["lon"].isna(), table["lat"].isna()
            if (lon_null ^ lat_null).any():
                errors.append("collapse_incidents.csv: lon and lat must both be null or both present")
            present_coords = ~lon_null & ~lat_null
            lon = pd.to_numeric(table.loc[present_coords, "lon"], errors="coerce")
            lat = pd.to_numeric(table.loc[present_coords, "lat"], errors="coerce")
            if not lon.between(-180, 180).all() or not lat.between(-90, 90).all():
                errors.append("collapse_incidents.csv: longitude/latitude outside geographic bounds")

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
    parser.add_argument("--report", type=Path, help="Optional path for a JSON quality report")
    args = parser.parse_args()

    report = validate_pack(args.pack_dir, expected_wards=args.expected_wards)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
