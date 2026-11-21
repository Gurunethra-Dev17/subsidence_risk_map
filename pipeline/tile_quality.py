"""Validate a C5 PMTiles candidate and write a machine-readable report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline.paths import pack_destination

CANDIDATE_MANIFEST_NAME = "TILES_CANDIDATE.json"
ID_FIELD_BY_LAYER = {
    "wards": "ward_id",
    "cells": "cell_id",
    "points": "pt_id",
    "buildings": "bldg_id",
}

EXPECTED = {
    "wards": {
        "fields": {"ward_id", "ward_name", "status", "score", "rank"},
        "zooms": (0, 12),
        "geometry": {"Polygon", "MultiPolygon"},
    },
    "cells": {
        "fields": {"cell_id", "ward_id", "suppressed", "cell_score", "cell_rank_in_ward"},
        "zooms": (8, 14),
        "geometry": {"Polygon", "MultiPolygon"},
    },
    "points": {
        "fields": {"pt_id", "vlm_mm_yr"},
        "zooms": (10, 15),
        "geometry": {"Point", "MultiPoint"},
    },
    "buildings": {
        "fields": {"bldg_id", "vlm_mm_yr", "beta_ratio_horizon", "beta_class", "sparse"},
        "zooms": (13, 16),
        "geometry": {"Polygon", "MultiPolygon"},
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_manifest_header(manifest: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    if manifest.get("contract") != "C5@1.0":
        errors.append("Manifest contract must be C5@1.0")
    if manifest.get("kind") != "geometry-only PMTiles candidate":
        warnings.append("Candidate is not labeled geometry-only")
    if not manifest.get("attribution"):
        errors.append("Manifest is missing C5 attribution")


def _check_manifest_layers(manifest: dict[str, Any], errors: list[str]) -> tuple[dict[str, Any], set[str]]:
    listed = {item.get("layer"): item for item in manifest.get("files", [])}
    if len(listed) != len(manifest.get("files", [])):
        errors.append("Manifest contains duplicate layer entries")
    expected_layers = set(listed)
    if not {"wards", "cells"}.issubset(expected_layers):
        errors.append("C5 candidates must include wards and cells")
    missing_layers = expected_layers - set(listed)
    extra_layers = set(listed) - set(EXPECTED)
    if missing_layers:
        errors.append(f"Missing layer entries: {sorted(missing_layers)}")
    if extra_layers:
        errors.append(f"Unknown layer entries: {sorted(extra_layers)}")
    return listed, expected_layers


def _validate_archive_metadata(
    candidate_dir: Path, layer: str, item: dict[str, Any], errors: list[str]
) -> tuple[Path, str, int] | None:
    path = (candidate_dir / item.get("file", "")).resolve()
    if candidate_dir not in path.parents:
        errors.append(f"{layer}: file path escapes candidate directory")
        return None
    if not path.is_file():
        errors.append(f"{layer}: missing archive {item.get('file')}")
        return None
    actual_hash = _sha256(path)
    actual_bytes = path.stat().st_size
    if actual_hash != item.get("sha256"):
        errors.append(f"{layer}: SHA-256 does not match manifest")
        return None
    if actual_bytes != item.get("bytes"):
        errors.append(f"{layer}: byte size does not match manifest")
    if (item.get("minzoom"), item.get("maxzoom")) != EXPECTED[layer]["zooms"]:
        errors.append(f"{layer}: manifest zoom range does not match C5")
    return path, actual_hash, actual_bytes


def _validate_archive_content(
    path: Path,
    layer: str,
    item: dict[str, Any],
    actual_hash: str,
    actual_bytes: int,
    pyogrio: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    try:
        info = pyogrio.read_info(path, layer=layer, force_feature_count=True)
        fields = set(info["fields"])
        missing_fields = EXPECTED[layer]["fields"] - fields
        if missing_fields:
            errors.append(f"{layer}: missing C5 fields {sorted(missing_fields)}")
        if info.get("crs") != "EPSG:3857":
            errors.append(f"{layer}: tile CRS must be EPSG:3857")
        if info.get("geometry_type") not in EXPECTED[layer]["geometry"]:
            errors.append(f"{layer}: unsupported geometry type {info.get('geometry_type')}")
        key = ID_FIELD_BY_LAYER.get(layer, "id")
        frame = pyogrio.read_dataframe(path, layer=layer, columns=[key])
        unique_features = int(frame[key].nunique(dropna=True))
        if unique_features != item.get("features"):
            errors.append(f"{layer}: distinct {key} count does not match manifest")
        return {
            "layer": layer,
            "file": item["file"],
            "features": info.get("features"),
            "unique_source_features": unique_features,
            "fields": sorted(fields),
            "bytes": actual_bytes,
            "sha256": actual_hash,
            "crs": info.get("crs"),
            "geometry_type": info.get("geometry_type"),
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{layer}: cannot open PMTiles layer: {exc}")
        return None


def _check_omitted_layers(manifest: dict[str, Any], expected_layers: set[str], errors: list[str]) -> set[str]:
    omitted = set(manifest.get("omitted_layers", []))
    for layer in set(EXPECTED) - expected_layers:
        if layer not in omitted:
            errors.append(f"{layer}: omitted layer must be listed explicitly")
    if omitted != set(EXPECTED) - expected_layers:
        errors.append("Manifest omitted_layers does not match archive layers")
    return omitted


def validate_candidate(candidate_dir: Path) -> dict[str, Any]:
    """Check manifest integrity and each PMTiles layer's C5 schema/zoom metadata."""
    import pyogrio

    candidate_dir = candidate_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = candidate_dir / CANDIDATE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    _check_manifest_header(manifest, errors, warnings)
    listed, expected_layers = _check_manifest_layers(manifest, errors)

    layer_reports = []
    for layer, item in listed.items():
        if layer not in EXPECTED:
            continue
        meta = _validate_archive_metadata(candidate_dir, layer, item, errors)
        if meta is None:
            continue
        path, actual_hash, actual_bytes = meta
        report = _validate_archive_content(path, layer, item, actual_hash, actual_bytes, pyogrio, errors)
        if report is not None:
            layer_reports.append(report)

    omitted = _check_omitted_layers(manifest, expected_layers, errors)
    return {
        "contract": "C5@1.0",
        "city": manifest.get("city"),
        "candidate_dir": str(candidate_dir),
        "expected_layers": sorted(expected_layers),
        "omitted_layers": sorted(omitted),
        "layers": layer_reports,
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_candidate(args.candidate_dir)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        report_path = pack_destination(args.candidate_dir, args.report, "tiles_quality.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
