"""Validate a C5 PMTiles candidate and write a machine-readable report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline.paths import pack_destination

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


def validate_candidate(candidate_dir: Path) -> dict[str, Any]:
    """Check manifest integrity and each PMTiles layer's C5 schema/zoom metadata."""
    import pyogrio

    candidate_dir = candidate_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = candidate_dir / "TILES_CANDIDATE.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract") != "C5@1.0":
        errors.append("Manifest contract must be C5@1.0")
    if manifest.get("kind") != "geometry-only PMTiles candidate":
        warnings.append("Candidate is not labeled geometry-only")
    if not manifest.get("attribution"):
        errors.append("Manifest is missing C5 attribution")

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

    layer_reports = []
    for layer, item in listed.items():
        if layer not in EXPECTED:
            continue
        path = (candidate_dir / item.get("file", "")).resolve()
        if candidate_dir not in path.parents:
            errors.append(f"{layer}: file path escapes candidate directory")
            continue
        if not path.is_file():
            errors.append(f"{layer}: missing archive {item.get('file')}")
            continue
        actual_hash = _sha256(path)
        actual_bytes = path.stat().st_size
        if actual_hash != item.get("sha256"):
            errors.append(f"{layer}: SHA-256 does not match manifest")
            continue  # skip opening a corrupted archive
        if actual_bytes != item.get("bytes"):
            errors.append(f"{layer}: byte size does not match manifest")
        if (item.get("minzoom"), item.get("maxzoom")) != EXPECTED[layer]["zooms"]:
            errors.append(f"{layer}: manifest zoom range does not match C5")
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
            # PMTiles stores clipped copies per tile, so archive feature count can
            # exceed source features. Compare distinct contracted IDs instead.
            key = "ward_id" if layer == "wards" else "cell_id" if layer == "cells" else "pt_id" if layer == "points" else "bldg_id"
            frame = pyogrio.read_dataframe(path, layer=layer, columns=[key])
            unique_features = int(frame[key].nunique(dropna=True))
            if unique_features != item.get("features"):
                errors.append(f"{layer}: distinct {key} count does not match manifest")
            layer_reports.append({
                "layer": layer,
                "file": item["file"],
                "features": info.get("features"),
                "unique_source_features": unique_features,
                "fields": sorted(fields),
                "bytes": actual_bytes,
                "sha256": actual_hash,
                "crs": info.get("crs"),
                "geometry_type": info.get("geometry_type"),
            })
        except Exception as exc:  # noqa: BLE001  # report archive-open failures instead of hiding them
            errors.append(f"{layer}: cannot open PMTiles layer: {exc}")

    omitted = set(manifest.get("omitted_layers", []))
    for layer in set(EXPECTED) - expected_layers:
        if layer not in omitted:
            errors.append(f"{layer}: omitted layer must be listed explicitly")
    if omitted != set(EXPECTED) - expected_layers:
        errors.append("Manifest omitted_layers does not match archive layers")
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
