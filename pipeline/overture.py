"""Download city-sized Overture building extracts in repeatable bbox tiles."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOG = logging.getLogger("pipeline.overture")
RELEASE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2}\.\d+)\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def split_bbox(bbox: list[float], tile_degrees: float) -> list[tuple[int, int, tuple[float, float, float, float]]]:
    """Split [west,south,east,north] into deterministic row/column bboxes."""
    if len(bbox) != 4:
        raise ValueError("bbox must be [west, south, east, north]")
    west, south, east, north = map(float, bbox)
    if west >= east or south >= north:
        raise ValueError("bbox west/south must be less than east/north")
    if not (math.isfinite(tile_degrees) and tile_degrees > 0):
        raise ValueError("tile_degrees must be a positive finite number")

    columns = math.ceil((east - west) / tile_degrees)
    rows = math.ceil((north - south) / tile_degrees)
    tiles = []
    for row in range(rows):
        tile_south = south + row * tile_degrees
        tile_north = min(north, tile_south + tile_degrees)
        for column in range(columns):
            tile_west = west + column * tile_degrees
            tile_east = min(east, tile_west + tile_degrees)
            tiles.append((row, column, (tile_west, tile_south, tile_east, tile_north)))
    return tiles


def _render_bbox(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{coordinate:.8f}" for coordinate in bbox)


def _raw_output_directory(config_path: Path, output_dir: Path) -> Path:
    raw_root = config_path.resolve().parents[1] / "data" / "raw"
    destination = output_dir.resolve()
    try:
        destination.relative_to(raw_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Overture extracts must be written under {raw_root}") from exc
    return destination


def extract_buildings(
    *,
    config_path: Path,
    output_dir: Path,
    tile_degrees: float = 0.15,
    overwrite: bool = False,
    runner: Any = subprocess.run,
) -> Path:
    """Run the official Overture CLI for each bbox tile and write a run record."""
    import yaml

    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config.get("contract") != "C6@1.0":
        raise ValueError(f"Expected a C6@1.0 city config: {config_path}")
    output_dir = _raw_output_directory(config_path, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tiles = split_bbox(config["bbox"], tile_degrees)
    output_files = [output_dir / f"building_r{row:02d}_c{column:02d}.parquet" for row, column, _ in tiles]
    record_path = output_dir / "EXTRACTION.json"
    existing = [path for path in [*output_files, record_path] if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Extraction output already exists; choose a new directory or pass --overwrite: "
            + ", ".join(path.name for path in existing)
        )

    try:
        cli_version = importlib.metadata.version("overturemaps")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("Install the official Overture client with `pip install overturemaps` first") from exc
    cli_path = shutil.which("overturemaps")
    if cli_path is None:
        executable = "overturemaps.exe" if sys.platform == "win32" else "overturemaps"
        candidate = Path(sys.executable).parent / executable
        if not candidate.is_file():
            raise RuntimeError(f"Could not locate the installed Overture CLI next to {sys.executable}")
        cli_path = str(candidate)

    started = utc_now()
    outputs = []
    logs = []
    releases = set()
    for (row, column, bbox), output_path in zip(tiles, output_files, strict=True):
        command = [
            cli_path,
            "download",
            f"--bbox={_render_bbox(bbox)}",
            "-f",
            "geoparquet",
            "--type=building",
            "-o",
            str(output_path),
        ]
        result = runner(command, check=False, capture_output=True, text=True)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        logs.append({"tile_row": row, "tile_column": column, "command": command, "stdout": stdout, "stderr": stderr})
        releases.update(RELEASE_PATTERN.findall(stdout + "\n" + stderr))
        if result.returncode != 0:
            raise RuntimeError(
                f"Overture download failed for tile row={row}, column={column}; see command output above."
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Overture command succeeded but produced no data file: {output_path}")
        tile_release = None
        state_path = Path(str(output_path) + ".state")
        if state_path.is_file():
            try:
                tile_release = json.loads(state_path.read_text(encoding="utf-8")).get("last_release")
            except (OSError, json.JSONDecodeError):
                tile_release = None
        if tile_release:
            releases.add(str(tile_release))
        outputs.append(
            {
                "name": output_path.name,
                "bbox": list(bbox),
                "bytes": output_path.stat().st_size,
                "release": tile_release,
            }
        )

    record = {
        "city": config["city"],
        "source": "Overture Maps Buildings",
        "source_url": "https://overturemaps.org",
        "client": "overturemaps",
        "client_version": cli_version,
        "format": "GeoParquet",
        "feature_type": "building",
        "bbox": config["bbox"],
        "tile_degrees": tile_degrees,
        "started_utc": started,
        "finished_utc": utc_now(),
        "observed_release_labels": sorted(releases),
        "release_note": (
            "The official client uses Overture STAC by default. If no release label was printed, "
            "confirm the release from the output metadata/source records before publishing the pack."
        ),
        "outputs": outputs,
        "logs": logs,
    }
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download tiled Overture buildings for a city C6 config.")
    parser.add_argument("--config", type=Path, required=True, help="City C6 YAML config")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory under data/raw for extracts")
    parser.add_argument("--tile-degrees", type=float, default=0.15)
    parser.add_argument("--overwrite", action="store_true", help="Replace prior tile files in this output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    record = extract_buildings(
        config_path=args.config,
        output_dir=args.output_dir,
        tile_degrees=args.tile_degrees,
        overwrite=args.overwrite,
    )
    LOG.info("Wrote extraction record %s", record)


if __name__ == "__main__":
    main()
