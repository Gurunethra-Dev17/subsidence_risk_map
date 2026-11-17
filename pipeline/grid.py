"""Generate stable C0 grid_250m.geojson cells from ward boundaries."""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Any


LOG = logging.getLogger("pipeline.grid")


def _polygonal_only(geometry: Any, shapely: Any) -> tuple[Any, int]:
    """Keep polygon components from a geometry, dropping lower dimensions."""
    if geometry is None or geometry.is_empty:
        return None, 0
    if geometry.geom_type == "Polygon":
        holes = []
        discarded = 0
        for ring in geometry.interiors:
            coordinates = list(ring.coords)
            if len(set(coordinates[:-1])) < 3 or shapely.Polygon(ring).area <= 0:
                discarded += 1
            else:
                holes.append(coordinates)
        cleaned = shapely.Polygon(geometry.exterior.coords, holes)
        if cleaned.is_valid:
            return cleaned, discarded
        fixed, extra_discarded = _polygonal_only(shapely.make_valid(cleaned), shapely)
        return fixed, discarded + extra_discarded
    if geometry.geom_type == "MultiPolygon":
        polygons = []
        discarded = 0
        for part in shapely.get_parts(geometry):
            polygonal, dropped = _polygonal_only(part, shapely)
            discarded += dropped
            if polygonal is not None:
                polygons.extend(shapely.get_parts(polygonal))
        if not polygons:
            return None, discarded
        return shapely.union_all(polygons), discarded
    if geometry.geom_type != "GeometryCollection":
        return None, 1

    polygons: list[Any] = []
    discarded = 0
    for part in shapely.get_parts(geometry):
        polygonal, dropped = _polygonal_only(part, shapely)
        discarded += dropped
        if polygonal is not None:
            if polygonal.geom_type == "Polygon":
                polygons.append(polygonal)
            else:
                polygons.extend(shapely.get_parts(polygonal))
    if not polygons:
        return None, discarded
    return shapely.union_all(polygons), discarded


def _geo_modules() -> tuple[Any, Any, Any]:
    try:
        import geopandas as gpd
        import pandas as pd
        import shapely
    except ImportError as exc:
        raise RuntimeError(
            "The grid pipeline needs the optional geo dependencies; install the project with [geo]."
        ) from exc
    return gpd, pd, shapely


def generate_grid(
    *,
    wards_path: Path,
    city: str,
    utm_epsg: int,
    grid_m: int = 250,
    expected_ward_count: int | None = None,
) -> tuple[Any, dict[str, int]]:
    """Make global-origin square cells, clipped to the union of ward polygons."""
    gpd, pd, shapely = _geo_modules()
    if grid_m <= 0:
        raise ValueError("grid_m must be positive")
    if not wards_path.exists():
        raise FileNotFoundError(wards_path)
    wards = gpd.read_parquet(wards_path) if wards_path.suffix.lower() == ".parquet" else gpd.read_file(wards_path)
    if wards.crs is None:
        raise ValueError(f"Ward layer has no CRS: {wards_path}")
    if "ward_id" not in wards.columns:
        raise ValueError("Ward layer must contain ward_id")
    if wards["ward_id"].isna().any() or wards["ward_id"].duplicated().any():
        raise ValueError("Ward IDs must be non-null and unique before grid generation")
    if expected_ward_count is not None and len(wards) != expected_ward_count:
        raise ValueError(f"Expected {expected_ward_count} wards, found {len(wards)}")

    wards = wards.loc[wards.geometry.notna() & ~wards.geometry.is_empty].copy().to_crs(epsg=utm_epsg)
    if wards.empty:
        raise ValueError("Ward layer contains no non-empty geometries")
    wards = wards[["ward_id", wards.geometry.name]].copy()
    wards["ward_id"] = wards["ward_id"].astype("string")
    wards = wards.reset_index(drop=True)
    city_shape = shapely.union_all(wards.geometry.array)
    if city_shape.is_empty or not city_shape.is_valid:
        raise ValueError("The union of ward polygons must be non-empty and valid")

    min_x, min_y, max_x, max_y = city_shape.bounds
    min_ix, max_ix = math.floor(min_x / grid_m), math.ceil(max_x / grid_m)
    min_iy, max_iy = math.floor(min_y / grid_m), math.ceil(max_y / grid_m)
    records = []
    repaired_cells = 0
    discarded_parts = 0
    for ix in range(min_ix, max_ix):
        x0 = ix * grid_m
        for iy in range(min_iy, max_iy):
            y0 = iy * grid_m
            clipped = shapely.box(x0, y0, x0 + grid_m, y0 + grid_m).intersection(city_shape)
            if clipped.is_empty or clipped.area <= 0:
                continue
            if not clipped.is_valid:
                clipped = shapely.make_valid(clipped)
                repaired_cells += 1
            clipped, discarded = _polygonal_only(clipped, shapely)
            discarded_parts += discarded
            if clipped is None or clipped.is_empty or clipped.area <= 0:
                continue
            if not clipped.is_valid:
                raise ValueError(f"Grid intersection produced invalid geometry for cell {city.upper()}_{grid_m}M_{ix}_{iy}")
            records.append(
                {
                    "cell_id": f"{city.upper()}_{grid_m}M_{ix}_{iy}",
                    "geometry": clipped,
                }
            )

    cells = gpd.GeoDataFrame(records, geometry="geometry", crs=f"EPSG:{utm_epsg}")
    if cells.empty:
        raise ValueError("No grid cells intersect the configured ward boundaries")
    intersections = gpd.sjoin(cells, wards, how="left", predicate="intersects")
    intersections["_overlap_m2"] = [
        cells.geometry.iloc[int(cell_index)].intersection(wards.geometry.iloc[int(ward_index)]).area
        if not pd.isna(ward_index)
        else 0.0
        for cell_index, ward_index in zip(intersections.index, intersections["index_right"], strict=True)
    ]
    intersections = intersections.sort_values(
        ["cell_id", "_overlap_m2", "ward_id"], ascending=[True, False, True], kind="stable", na_position="last"
    )
    majority = intersections.drop_duplicates("cell_id").set_index("cell_id")["ward_id"]
    cells["ward_id"] = cells["cell_id"].map(majority).astype("string")
    cells = cells[["cell_id", "ward_id", "geometry"]].to_crs("EPSG:4326")
    geographic_geometries = []
    for geometry in cells.geometry:
        if not geometry.is_valid:
            geometry = shapely.make_valid(geometry)
            repaired_cells += 1
        geometry, discarded = _polygonal_only(geometry, shapely)
        discarded_parts += discarded
        if geometry is None or geometry.is_empty or not geometry.is_valid:
            raise ValueError("Generated grid contains invalid polygon geometry after CRS conversion")
        geographic_geometries.append(geometry)
    cells[cells.geometry.name] = geographic_geometries
    if cells["cell_id"].isna().any() or cells["cell_id"].duplicated().any():
        raise ValueError("Generated cell IDs must be non-null and unique")

    stats = {
        "ward_count": len(wards),
        "cell_count": len(cells),
        "unassigned_ward_cells": int(cells["ward_id"].isna().sum()),
        "grid_m": grid_m,
        "repaired_invalid_cells": repaired_cells,
        "discarded_nonpolygon_parts": discarded_parts,
    }
    return cells, stats


def process_from_config(
    *,
    config_path: Path,
    wards_path: Path,
    output_path: Path | None = None,
    expected_ward_count: int | None = None,
) -> tuple[Path, dict[str, int]]:
    import yaml

    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config.get("contract") != "C6@1.0":
        raise ValueError(f"Expected a C6@1.0 city config: {config_path}")
    pack_dir = Path(config["paths"]["pack_dir"])
    if not pack_dir.is_absolute():
        pack_dir = config_path.resolve().parents[1] / pack_dir
    destination = output_path or (pack_dir / "grid_250m.geojson")
    destination.parent.mkdir(parents=True, exist_ok=True)

    grid_m = int(config["params"]["grid_m"])
    cells, stats = generate_grid(
        wards_path=wards_path,
        city=config["city"],
        utm_epsg=int(config["utm_epsg"]),
        grid_m=grid_m,
        expected_ward_count=expected_ward_count,
    )
    destination.write_text(cells.to_json(drop_id=True, to_wgs84=True), encoding="utf-8")
    gpd, _, _ = _geo_modules()
    written = gpd.read_file(destination)
    if (
        len(written) != len(cells)
        or written["cell_id"].duplicated().any()
        or written.geometry.isna().any()
        or written.geometry.is_empty.any()
        or not written.geometry.is_valid.all()
        or not written.geometry.geom_type.isin({"Polygon", "MultiPolygon"}).all()
    ):
        raise ValueError("Serialized grid failed C0 geometry and ID checks")
    return destination, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate contract C0 grid cells from ward polygons.")
    parser.add_argument("--config", type=Path, required=True, help="City C6 YAML config")
    parser.add_argument("--wards", type=Path, required=True, help="Normalized C0 wards file")
    parser.add_argument("--expected-ward-count", type=int)
    parser.add_argument("--output", type=Path, help="Output path; defaults to grid_250m.geojson in pack_dir")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    output, stats = process_from_config(
        config_path=args.config,
        wards_path=args.wards,
        output_path=args.output,
        expected_ward_count=args.expected_ward_count,
    )
    LOG.info("Wrote %s", output)
    LOG.info("Statistics: %s", json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
