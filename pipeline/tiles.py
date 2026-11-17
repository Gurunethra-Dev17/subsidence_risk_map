"""Build the C5 per-ward GeoJSON fallback from a C0 ward layer.

The fallback is gzip-compressed JSON written with a ``.json`` suffix. Configure
the static host to return ``Content-Encoding: gzip`` for these objects.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Any


TILE_PROPERTIES = ("ward_id", "ward_name", "status", "score", "rank")
C5_ATTRIBUTION = (
    "© OpenStreetMap contributors, Microsoft, Esri Community Maps contributors, "
    "Google Open Buildings; ground-motion data: Virginia Tech dataset (see licence)"
)
LOG = logging.getLogger("pipeline.tiles")


def build_ward_fallback(input_path: Path, output_dir: Path, city: str, version: str) -> dict[str, Any]:
    """Write one deterministic gzip GeoJSON FeatureCollection per ward."""
    with input_path.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    if source.get("type") != "FeatureCollection" or not isinstance(source.get("features"), list):
        raise ValueError("Input must be a GeoJSON FeatureCollection")

    output_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for feature in source["features"]:
        properties = feature.get("properties") or {}
        ward_id = properties.get("ward_id")
        geometry = feature.get("geometry")
        if ward_id is None or not isinstance(geometry, dict):
            raise ValueError("Every ward feature needs ward_id and geometry")
        ward_id = str(ward_id)
        if ward_id in seen:
            raise ValueError(f"Duplicate ward_id: {ward_id}")
        seen.add(ward_id)
        if not ward_id.isdigit():
            raise ValueError(f"Unsafe ward_id for output filename: {ward_id!r}")
        props = {
            "ward_id": ward_id,
            "ward_name": properties.get("ward_name"),
            # C1/C2 outputs are not available yet; preserve the C5 schema as null.
            "status": None,
            "score": None,
            "rank": None,
        }
        record = {"type": "Feature", "properties": props, "geometry": geometry}
        payload = {
            "type": "FeatureCollection",
            "name": f"{city}-wards-{version}",
            "features": [record],
        }
        raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        # mtime=0 makes repeated runs byte-for-byte stable.
        compressed = gzip.compress(raw, mtime=0)
        destination = output_dir / f"{ward_id}.json"
        destination.write_bytes(compressed)
        records.append({
            "ward_id": ward_id,
            "file": destination.name,
            "encoding": "gzip",
            "content_encoding": "gzip",
            "bytes": len(compressed),
            "sha256": hashlib.sha256(compressed).hexdigest(),
        })

    if not records:
        raise ValueError("Input contains no ward features")
    manifest = {
        "contract": "C5@1.0",
        "city": city,
        "version": version,
        "kind": "per-ward GeoJSON fallback candidate",
        "layer": "wards",
        "properties": list(TILE_PROPERTIES),
        "zoom_range": [0, 12],
        "attribution": "© OpenStreetMap contributors, Microsoft, Esri Community Maps contributors, Google Open Buildings; ground-motion data: Virginia Tech dataset (see licence)",
        "metric_fields_pending": ["status", "score", "rank"],
        "features": len(records),
        "files": records,
    }
    (output_dir / "TILES_CANDIDATE.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def build_pmtiles(
    pack_dir: Path,
    output_dir: Path,
    city: str,
    version: str,
    *,
    include_points: bool = True,
    include_buildings: bool = True,
) -> dict[str, Any]:
    """Build the four C5 PMTiles archives from a C0 pack using GDAL's PMTiles driver.

    C1/C2 exports are not inputs yet, so their contracted properties are emitted
    as typed nulls and listed in the candidate manifest. Building tiles are put
    under ``authority/`` as required by C5.
    """
    try:
        import geopandas as gpd
        import numpy as np
        import pandas as pd
        import pyogrio
    except ImportError as exc:
        raise RuntimeError("PMTiles generation requires the project's optional geo dependencies") from exc

    if "PMTiles" not in pyogrio.list_drivers():
        raise RuntimeError("Installed GDAL/pyogrio does not provide the PMTiles vector writer")
    required = {"wards.geojson", "grid_250m.geojson"}
    if include_points:
        required.add("vlm_points.parquet")
    if include_buildings:
        required.add("buildings.parquet")
    missing = sorted(name for name in required if not (pack_dir / name).is_file())
    if missing:
        raise FileNotFoundError(f"C0 pack lacks tile inputs: {', '.join(missing)}")
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite tile output directory: {output_dir}")

    wards = gpd.read_file(pack_dir / "wards.geojson")
    wards = wards[["ward_id", "ward_name", "geometry"]].copy()
    wards["ward_id"] = wards["ward_id"].astype("string")
    wards["ward_name"] = wards["ward_name"].astype("string")
    wards["status"] = pd.Series([None] * len(wards), dtype="string")
    wards["score"] = pd.Series([np.nan] * len(wards), dtype="float64")
    wards["rank"] = pd.Series([pd.NA] * len(wards), dtype="Int32")

    cells = gpd.read_file(pack_dir / "grid_250m.geojson")
    cells = cells[["cell_id", "ward_id", "geometry"]].copy()
    # Tiny slivers are lost during PMTiles quantization. Prune them only from
    # this delivery candidate and record the IDs; retain the complete C0 grid.
    source_cell_count = len(cells)
    cell_area_m2 = cells.to_crs("EPSG:32643").geometry.area
    pruned_cell_ids = cells.loc[cell_area_m2 < 1.0, "cell_id"].astype(str).tolist()
    cells = cells.loc[cell_area_m2 >= 1.0].copy()
    cells["cell_id"] = cells["cell_id"].astype("string")
    cells["ward_id"] = cells["ward_id"].astype("string")
    cells["suppressed"] = pd.Series([None] * len(cells), dtype="boolean")
    cells["cell_score"] = pd.Series([np.nan] * len(cells), dtype="float64")
    cells["cell_rank_in_ward"] = pd.Series([pd.NA] * len(cells), dtype="Int32")

    points = None
    if include_points:
        points = pd.read_parquet(pack_dir / "vlm_points.parquet")
        points = points[["pt_id", "vlm_mm_yr", "lon", "lat"]].copy()
        points["pt_id"] = points["pt_id"].astype("string")
        points = gpd.GeoDataFrame(
            points, geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs="EPSG:4326"
        )[["pt_id", "vlm_mm_yr", "geometry"]]
        points["vlm_mm_yr"] = points["vlm_mm_yr"].astype("float64")

    buildings = None
    if include_buildings:
        buildings = gpd.read_parquet(pack_dir / "buildings.parquet")
        buildings = buildings[["bldg_id", "geometry"]].copy()
        buildings["bldg_id"] = buildings["bldg_id"].astype("string")
        buildings["vlm_mm_yr"] = pd.Series([np.nan] * len(buildings), dtype="float64")
        buildings["beta_ratio_horizon"] = pd.Series([None] * len(buildings), dtype="string")
        buildings["beta_class"] = pd.Series([None] * len(buildings), dtype="string")
        buildings["sparse"] = pd.Series([pd.NA] * len(buildings), dtype="boolean")

    layers = [
        ("wards", wards, 0, 12, "public"),
        ("cells", cells, 8, 14, "public"),
    ]
    if points is not None:
        layers.append(("points", points, 10, 15, "public"))
    if buildings is not None:
        layers.append(("buildings", buildings, 13, 16, "authority"))
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as temp:
        staging = Path(temp)
        for layer_name, frame, min_zoom, max_zoom, access in layers:
            folder = staging / access
            folder.mkdir(parents=True, exist_ok=True)
            tile_path = folder / f"{city}-{layer_name}-{version}.pmtiles"
            LOG.info("Building %s (%s features), zoom %s-%s", layer_name, len(frame), min_zoom, max_zoom)
            pyogrio.write_dataframe(
                frame,
                tile_path,
                driver="PMTiles",
                layer=layer_name,
                dataset_options={
                    "MINZOOM": str(min_zoom),
                    "MAXZOOM": str(max_zoom),
                    "NAME": f"{city.title()} {layer_name} {version}",
                    "DESCRIPTION": "C5 geometry candidate; metric joins pending",
                    "TYPE": "overlay",
                },
                layer_options={"NAME": layer_name, "MINZOOM": str(min_zoom), "MAXZOOM": str(max_zoom)},
            )
            manifest_files.append({
                "layer": layer_name,
                "file": f"{access}/{tile_path.name}",
                "minzoom": min_zoom,
                "maxzoom": max_zoom,
                "features": len(frame),
                "bytes": tile_path.stat().st_size,
                "sha256": _sha256_file(tile_path),
            })
        manifest = {
            "contract": "C5@1.0",
            "city": city,
            "version": version,
            "kind": "geometry-only PMTiles candidate",
            "attribution": C5_ATTRIBUTION,
            "metric_fields_pending": {
                "wards": ["status", "score", "rank"],
                "cells": ["suppressed", "cell_score", "cell_rank_in_ward"],
                "points": [],
                "buildings": ["vlm_mm_yr", "beta_ratio_horizon", "beta_class", "sparse"],
            },
            "omitted_layers": [
                layer for layer, included in (("points", include_points), ("buildings", include_buildings))
                if not included
            ],
            "pruned_features": {
                "cells": {
                    "reason": "projected polygon area below 1 square metre; these degenerate slivers are dropped by PMTiles quantization",
                    "source_count": source_cell_count,
                    "pruned_count": len(pruned_cell_ids),
                    "pruned_ids": pruned_cell_ids,
                }
            },
            "files": manifest_files,
        }
        (staging / "TILES_CANDIDATE.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.replace(output_dir)
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="C0 wards.geojson for per-ward GeoJSON fallback")
    parser.add_argument("--output-dir", type=Path, help="Output directory for GeoJSON or PMTiles candidate")
    parser.add_argument("--city", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--pack-dir", type=Path, help="Build all C5 PMTiles archives from a C0 pack")
    parser.add_argument("--pmtiles-output-dir", type=Path, help="Output directory for the PMTiles candidate")
    parser.add_argument("--skip-buildings", action="store_true", help="Build wards/cells/points only")
    parser.add_argument("--skip-points", action="store_true", help="Build wards/cells only")
    args = parser.parse_args()
    if args.pack_dir:
        if not args.pmtiles_output_dir:
            parser.error("--pmtiles-output-dir is required with --pack-dir")
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        result = build_pmtiles(
            args.pack_dir, args.pmtiles_output_dir, args.city, args.version,
            include_points=not args.skip_points,
            include_buildings=not args.skip_buildings,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not args.input or not args.output_dir:
            parser.error("--input and --output-dir are required for the per-ward GeoJSON fallback")
        result = build_ward_fallback(args.input, args.output_dir, args.city, args.version)
        print(f"Wrote {result['features']} ward fallback files to {args.output_dir}")


if __name__ == "__main__":
    main()
