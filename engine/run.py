"""Chunked C0-to-C1 geospatial engine command line."""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from engine.assign import assign_points_to_buildings
from engine.distortion import compute_building_distortion
from engine.export import export_building_metrics
from engine.io import load_config, load_vlm_points

LOGGER = logging.getLogger("engine.run")
BUILDING_COLUMNS = ["bldg_id", "footprint_m2", "source", "ward_id", "cell_id", "geometry"]


class EngineRunError(RuntimeError):
    """Raised when a C0-to-C1 run cannot complete safely."""


def _default_engine_version() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "working-tree"


def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def _combine_parquet_parts(parts: list[Path], destination: Path) -> None:
    if not parts:
        raise EngineRunError("no buildings matched the selected C0 input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    writer = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        first = pq.ParquetFile(parts[0])
        writer = pq.ParquetWriter(
            temp_path, first.schema_arrow, compression="zstd", version="2.6",
            use_dictionary=False, write_statistics=True,
        )
        for part in parts:
            parquet_file = pq.ParquetFile(part)
            if not parquet_file.schema_arrow.equals(first.schema_arrow, check_metadata=True):
                raise EngineRunError(f"C1 chunk schema or metadata differs in {part.name}")
            for batch in parquet_file.iter_batches(batch_size=65536):
                writer.write_batch(batch)
        writer.close()
        writer = None
        os.replace(temp_path, destination)
    except (OSError, pa.ArrowException, EngineRunError):
        if writer is not None:
            writer.close()
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise


def run_engine(
    config_path: str | Path,
    *,
    pack_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    chunk_size: int = 10_000,
    ward_id: str | None = None,
    limit_buildings: int | None = None,
    engine_version: str | None = None,
) -> dict:
    """Stream C0 buildings in chunks and produce a C1 Parquet file.

    The input C0 buildings are GeoParquet, read as Arrow record batches. Each
    batch is converted to a GeoDataFrame, processed by A2/A3, exported as a
    temporary C1 fragment, and appended to the final Parquet file. A ward filter
    and row limit support repeatable pilot benchmarks without loading the city
    into memory.
    """
    if chunk_size <= 0:
        raise EngineRunError("chunk_size must be a positive integer")
    if limit_buildings is not None and limit_buildings <= 0:
        raise EngineRunError("limit_buildings must be a positive integer")
    cfg = load_config(str(config_path))
    if pack_dir is not None:
        paths = {**cfg.paths, "pack_dir": Path(pack_dir).expanduser().resolve()}
        cfg = replace(cfg, paths=paths)
    manifest_path = cfg.pack_dir / "PACK_MANIFEST.json"
    if not manifest_path.is_file():
        raise EngineRunError(f"C0 manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineRunError(f"cannot read C0 manifest {manifest_path}: {exc}") from exc
    if manifest.get("contract") != "C0@1.0" or manifest.get("city") != cfg.city:
        raise EngineRunError("C0 manifest contract/city do not match the selected C6 configuration")
    pack_version = manifest.get("pack_version", cfg.pack_dir.name)
    buildings_path = cfg.pack_dir / "buildings.parquet"
    points_path = cfg.pack_dir / "vlm_points.parquet"
    for required in (buildings_path, points_path):
        if not required.is_file():
            raise EngineRunError(f"required C0 input does not exist: {required}")

    version = engine_version or _default_engine_version()
    if output_path is None:
        suffix = f"_ward-{ward_id}" if ward_id is not None else ""
        if limit_buildings is not None:
            suffix += f"_first-{limit_buildings}"
        output = cfg.out_dir / f"building_metrics{suffix}.parquet"
    else:
        output = Path(output_path).expanduser().resolve()
    summary_path = output.with_name(f"{output.stem}.run_summary.json")
    log_path = output.with_name(f"{output.stem}.engine_run.log")
    _configure_logging(log_path)

    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - optional geo dependencies
        raise EngineRunError(
            "engine.run requires the 'geo' extra; install with pip install -e '.[geo]'"
        ) from exc

    points = load_vlm_points(cfg, path=str(points_path))
    LOGGER.info(
        "Loaded %d in-bbox VLM points from %s; bbox density %.3f points/km2",
        len(points), points_path, points.attrs["load_stats"].points_per_km2,
    )
    building_file = pq.ParquetFile(buildings_path)
    building_manifest_entry = next(
        (entry for entry in manifest.get("files", []) if entry.get("name") == "buildings.parquet"),
        None,
    )
    if (building_manifest_entry is None
            or building_file.metadata.num_rows != building_manifest_entry.get("rows")):
        raise EngineRunError("C0 building row count does not match PACK_MANIFEST.json")
    required_columns = set(BUILDING_COLUMNS)
    if not required_columns <= set(building_file.schema_arrow.names):
        missing = sorted(required_columns - set(building_file.schema_arrow.names))
        raise EngineRunError(f"C0 buildings are missing required columns: {', '.join(missing)}")
    geo_metadata = json.loads((building_file.schema_arrow.metadata or {}).get(b"geo", b"{}"))
    geometry_meta = geo_metadata.get("columns", {}).get("geometry", {})
    if not geometry_meta.get("crs"):
        raise EngineRunError("C0 GeoParquet buildings must declare geometry CRS")

    processed = 0
    nonnull_vlm = 0
    part_paths = []
    started = time.perf_counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engine-c1-parts-", dir=output.parent) as tmp:
        part_dir = Path(tmp)
        for source_batch in building_file.iter_batches(batch_size=chunk_size, columns=BUILDING_COLUMNS):
            frame = source_batch.to_pandas()
            if ward_id is not None:
                frame = frame.loc[frame["ward_id"].astype("string") == str(ward_id)]
            if limit_buildings is not None:
                remaining = limit_buildings - processed
                if remaining <= 0:
                    break
                frame = frame.head(remaining)
            if frame.empty:
                continue
            geometry = gpd.GeoSeries.from_wkb(frame.pop("geometry"), crs="EPSG:4326")
            buildings = gpd.GeoDataFrame(frame.reset_index(drop=True), geometry=geometry.reset_index(drop=True), crs="EPSG:4326")
            if buildings.geometry.isna().any() or buildings.geometry.is_empty.any():
                raise EngineRunError("C0 building chunk contains null or empty geometries")
            if not buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
                raise EngineRunError("C0 building chunk contains non-polygon geometry")
            if not buildings.geometry.is_valid.all():
                raise EngineRunError("C0 building chunk contains invalid geometry")

            assignments = assign_points_to_buildings(buildings, points, cfg, chunk_size=chunk_size)
            distortions = compute_building_distortion(buildings, points, cfg)
            part_path = part_dir / f"part-{len(part_paths):06d}.parquet"
            export_info = export_building_metrics(
                buildings, assignments, distortions, cfg, part_path, engine_version=version,
            )
            part_paths.append(part_path)
            processed += export_info["rows"]
            nonnull_vlm += int(assignments["vlm_mm_yr"].notna().sum())
            LOGGER.info(
                "Finished chunk %d: %d buildings, cumulative %d, VLM coverage %.4f, elapsed %.1fs",
                len(part_paths), export_info["rows"], processed,
                nonnull_vlm / processed, time.perf_counter() - started,
            )
            if limit_buildings is not None and processed >= limit_buildings:
                break

        _combine_parquet_parts(part_paths, output)

    summary = {
        "contract": "C1@1.0",
        "city": cfg.city,
        "pack_version": pack_version,
        "engine_version": version,
        "seed": cfg.seed,
        "params": dict(cfg.params),
        "params_hash": pq.ParquetFile(output).schema_arrow.metadata[b"params_hash"].decode("ascii"),
        "buildings_processed": processed,
        "non_null_vlm_buildings": nonnull_vlm,
        "non_null_vlm_share": nonnull_vlm / processed if processed else 0.0,
        "chunk_size": chunk_size,
        "ward_id_filter": ward_id,
        "limit_buildings": limit_buildings,
        "output": str(output),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LOGGER.info(
        "Completed %d buildings; non-null VLM share %.4f; output %s",
        processed, summary["non_null_vlm_share"], output,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compute C1 building metrics from a C0 pack")
    parser.add_argument("--config", default="configs/delhi.yaml", help="C6 config YAML path")
    parser.add_argument("--pack-dir", type=Path, help="local C0 pack folder override")
    parser.add_argument("--output", type=Path, help="C1 Parquet output path")
    parser.add_argument("--chunk-size", type=int, default=10_000, help="buildings processed per chunk")
    parser.add_argument("--ward-id", help="process only this C0 ward (useful for pilot benchmarks)")
    parser.add_argument("--limit-buildings", type=int, help="process at most this many matched buildings")
    parser.add_argument("--engine-version", help="version recorded in C1 rows/metadata (default: git commit)")
    args = parser.parse_args(argv)
    run_engine(
        args.config, pack_dir=args.pack_dir, output_path=args.output,
        chunk_size=args.chunk_size, ward_id=args.ward_id,
        limit_buildings=args.limit_buildings, engine_version=args.engine_version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
