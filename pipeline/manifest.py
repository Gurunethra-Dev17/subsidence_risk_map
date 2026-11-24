"""Build C0 manifests from a completed, contract-shaped data pack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "schemas" / "pack_manifest.schema.json"
MANIFEST_NAME = "PACK_MANIFEST.json"
REQUIRED_PACK_FILES = {
    "wards.geojson",
    "buildings.parquet",
    "vlm_points.parquet",
    "vt_building_risk.parquet",
    "grid_250m.geojson",
    "collapse_incidents.csv",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    """Count records in a supported C0 file without loading large tables at once."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return sum(1 for _ in csv.DictReader(stream))

    if suffix in {".geojson", ".json"}:
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if document.get("type") == "FeatureCollection":
            features = document.get("features")
            if not isinstance(features, list):
                raise ValueError(f"{path}: FeatureCollection has no features array")
            return len(features)
        raise ValueError(f"{path}: expected a GeoJSON FeatureCollection")

    if suffix == ".parquet":
        try:
            from pyarrow import parquet
        except ImportError as exc:
            raise RuntimeError("Counting Parquet rows requires the optional pyarrow dependency") from exc
        return parquet.ParquetFile(path).metadata.num_rows

    raise ValueError(f"Cannot count rows for unsupported pack file: {path.name}")


def build_manifest(
    pack_dir: Path,
    *,
    city: str,
    pack_version: str,
    sources: list[dict[str, str]],
    attribution: list[str],
    notes: list[str],
    created_utc: str | None = None,
) -> dict[str, Any]:
    """Create and schema-check a C0@1.0 manifest for files in ``pack_dir``."""
    pack_dir = pack_dir.resolve()
    if not pack_dir.is_dir():
        raise FileNotFoundError(f"Pack directory does not exist: {pack_dir}")
    if not sources:
        raise ValueError("C0 manifest needs at least one source with licence and access date")

    files = []
    for path in sorted(pack_dir.iterdir(), key=lambda item: item.name):
        if path.name == MANIFEST_NAME or path.is_dir() or path.name.startswith("."):
            continue
        files.append({"name": path.name, "sha256": sha256_file(path), "rows": row_count(path)})
    found_names = {item["name"] for item in files}
    missing_names = sorted(REQUIRED_PACK_FILES - found_names)
    if missing_names:
        raise ValueError(f"C0 pack is missing required files: {', '.join(missing_names)}")

    manifest = {
        "contract": "C0@1.0",
        "pack_version": pack_version,
        "created_utc": created_utc
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "city": city,
        "crs_storage": "EPSG:4326",
        "files": files,
        "sources": sources,
        "attribution": attribution,
        "notes": notes,
    }

    with SCHEMA_PATH.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.path))
    if errors:
        details = "\n".join(f"- {'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors)
        raise ValueError(f"Generated manifest violates C0@1.0:\n{details}")
    return manifest


def write_manifest(pack_dir: Path, **metadata: Any) -> Path:
    manifest = build_manifest(pack_dir, **metadata)
    target = pack_dir / MANIFEST_NAME
    temporary = target.with_name(f".{MANIFEST_NAME}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a C0@1.0 manifest for a completed data pack.")
    parser.add_argument("pack_dir", type=Path)
    parser.add_argument("--city", required=True)
    parser.add_argument("--version", required=True, dest="pack_version")
    parser.add_argument("--source", action="append", default=[], metavar="NAME|URL|LICENCE|ACCESSED_UTC")
    parser.add_argument("--attribution", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    sources = []
    for value in args.source:
        parts = value.split("|", maxsplit=3)
        if len(parts) != 4 or not all(parts):
            parser.error("--source must be NAME|URL|LICENCE|ACCESSED_UTC")
        sources.append(dict(zip(("name", "url", "licence", "accessed_utc"), parts, strict=True)))

    target = write_manifest(
        args.pack_dir,
        city=args.city,
        pack_version=args.pack_version,
        sources=sources,
        attribution=args.attribution,
        notes=args.note,
    )
    print(target)


if __name__ == "__main__":
    main()
