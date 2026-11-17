"""Normalize building footprints into the C0 buildings.parquet layer."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pipeline.paths import pack_destination


LOG = logging.getLogger("pipeline.buildings")
ALLOWED_SOURCES = {"osm", "google", "microsoft", "esri", "vt"}


def _geo_modules() -> tuple[Any, Any, Any, Any]:
    try:
        import geopandas as gpd
        import pandas as pd
        import shapely
        from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
        from shapely.ops import unary_union
    except ImportError as exc:
        raise RuntimeError(
            "The building pipeline needs the optional geo dependencies; install the project with [geo]."
        ) from exc
    return gpd, pd, shapely, (GeometryCollection, MultiPolygon, Polygon, box, unary_union)


def _read_layer(gpd: Any, path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = gpd.read_parquet(path) if path.suffix.lower() in {".parquet", ".geoparquet"} else gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"Input has no CRS; refusing to guess: {path}")
    if frame.geometry.name not in frame.columns:
        raise ValueError(f"Input has no active geometry column: {path}")
    return frame


def _polygonal(geometry: Any, classes: Any) -> Any:
    geometry_collection_type, multi_polygon_type, polygon_type, _, unary_union = classes
    if geometry is None or geometry.is_empty:
        return None
    try:
        repaired = geometry if geometry.is_valid else geometry.make_valid()
    except AttributeError:
        import shapely

        repaired = geometry if geometry.is_valid else shapely.make_valid(geometry)
    if isinstance(repaired, (polygon_type, multi_polygon_type)):
        return repaired
    if isinstance(repaired, geometry_collection_type) or hasattr(repaired, "geoms"):
        return _union_polygonal_parts(repaired.geoms, classes, multi_polygon_type, unary_union)
    return None


def _union_polygonal_parts(parts: Any, classes: Any, multi_polygon_type: Any, unary_union: Any) -> Any:
    polygons = []
    for part in parts:
        polygon = _polygonal(part, classes)
        if polygon is None:
            continue
        polygons.extend(list(polygon.geoms) if isinstance(polygon, multi_polygon_type) else [polygon])
    return unary_union(polygons) if polygons else None


def _stable_id(source: str, source_id: Any, geometry: Any, shapely: Any) -> str:
    if source_id is not None:
        value = str(source_id).strip()
        if value and value.lower() not in {"nan", "<na>", "nat"}:
            return f"{source}:{value}"
    normalized = shapely.normalize(geometry)
    digest = hashlib.sha256(shapely.to_wkb(normalized, hex=False)).hexdigest()[:24]
    return f"{source}:{digest}"


def _overture_source_code(provenance: Any) -> str:
    """Map Overture provenance records to the frozen C0 source enum."""
    if isinstance(provenance, str):
        try:
            provenance = json.loads(provenance)
        except json.JSONDecodeError:
            provenance = [provenance]
    if hasattr(provenance, "tolist") and not isinstance(provenance, dict):
        provenance = provenance.tolist()
    if isinstance(provenance, dict):
        provenance = [provenance]
    if not isinstance(provenance, (list, tuple)):
        raise ValueError("Overture source=auto needs a list/dict sources field for every feature")

    for item in provenance:
        if isinstance(item, dict):
            label = " ".join(
                str(item.get(field, ""))
                for field in ("provider", "dataset", "resource", "dataset_name")
            ).lower()
        else:
            label = str(item).lower()
        if "openstreetmap" in label or "osm" in label:
            return "osm"
        if "google" in label:
            return "google"
        if "microsoft" in label:
            return "microsoft"
        if "esri" in label:
            return "esri"
    raise ValueError(f"Could not map Overture provenance into the C0 source enum: {provenance!r}")


def _assign_ids(
    gpd: Any,
    buildings: Any,
    polygons: Any,
    id_column: str,
    output_column: str,
    centroid_geometries: Any,
) -> Any:
    if id_column not in polygons.columns:
        raise ValueError(f"Boundary layer is missing required ID column {id_column!r}")
    centroids = gpd.GeoDataFrame(
        {"_row": range(len(buildings))},
        geometry=centroid_geometries,
        crs="EPSG:4326",
    )
    targets = polygons[[id_column, polygons.geometry.name]].copy()
    joined = gpd.sjoin(centroids, targets, how="left", predicate="within")
    joined = joined.sort_values(["_row", id_column], kind="stable", na_position="last")
    chosen = joined.drop_duplicates("_row").set_index("_row")[id_column]
    values = chosen.reindex(range(len(buildings))).astype("string")
    buildings[output_column] = values.array
    return buildings


def _normalize_input_chunk(
    gpd: Any,
    source: str,
    id_column: str,
    input_path: Path,
    city_box: Any,
    shapely: Any,
    classes: Any,
) -> tuple[Any, int]:
    if source != "auto" and source not in ALLOWED_SOURCES:
        raise ValueError(f"Unsupported C0 source {source!r}; choose from {sorted(ALLOWED_SOURCES)} or auto")
    frame = _read_layer(gpd, input_path)
    if id_column not in frame.columns:
        raise ValueError(f"{input_path} has no source ID column {id_column!r}")
    if source == "auto":
        if "sources" not in frame.columns:
            raise ValueError(f"{input_path} has no Overture sources provenance column")
        frame["_c0_source"] = frame["sources"].map(_overture_source_code)
    else:
        frame["_c0_source"] = source
    input_rows = len(frame)
    frame = frame.to_crs("EPSG:4326")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame[frame.geometry.name] = frame.geometry.map(lambda geom: _polygonal(geom, classes))
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame = frame.loc[frame.geometry.intersects(city_box)].copy()
    frame["source"] = frame["_c0_source"]
    frame["bldg_id"] = [
        _stable_id(source_code, source_id, geometry, shapely)
        for source_code, source_id, geometry in zip(frame["source"], frame[id_column], frame.geometry, strict=True)
    ]
    chunk = frame[["bldg_id", "source"]].copy()
    chunk["geometry"] = frame.geometry
    return gpd.GeoDataFrame(chunk, geometry="geometry", crs="EPSG:4326"), input_rows


def _deduplicate_measure(
    gpd: Any, pd: Any, chunks: list[Any], utm_epsg: int, min_area_m2: float, shapely: Any
) -> Any:
    buildings = gpd.GeoDataFrame(pd.concat(chunks, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    buildings = buildings.drop_duplicates("bldg_id", keep="first")
    buildings["_geometry_key"] = buildings.geometry.map(
        lambda geom: shapely.to_wkb(shapely.normalize(geom), hex=True)
    )
    buildings = buildings.drop_duplicates("_geometry_key", keep="first").drop(columns="_geometry_key")
    metric = buildings.to_crs(epsg=utm_epsg)
    buildings["footprint_m2"] = metric.geometry.area.astype("float64")
    return buildings.loc[buildings["footprint_m2"] >= min_area_m2].copy()


def _validate_boundaries(wards: Any, grid: Any) -> None:
    for label, frame, id_column in (("wards", wards, "ward_id"), ("grid", grid, "cell_id")):
        if id_column not in frame.columns:
            raise ValueError(f"{label} layer is missing required ID column {id_column!r}")
        if frame[id_column].isna().any() or frame[id_column].duplicated().any():
            raise ValueError(f"{label} layer must have non-null, unique {id_column} values")


def prepare_buildings(
    *,
    input_specs: list[tuple[str, str, Path]],
    wards_path: Path,
    grid_path: Path,
    bbox: list[float],
    utm_epsg: int,
    min_area_m2: float = 10.0,
) -> tuple[Any, dict[str, int]]:
    """Read, clean, deduplicate and spatially attribute footprint inputs.

    ``input_specs`` entries are (C0 source code, source ID column, file path).
    Input order resolves exact-geometry duplicates in favor of the first source.
    """
    gpd, pd, shapely, classes = _geo_modules()
    _, _, _, box, _ = classes
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
    if min_area_m2 < 0:
        raise ValueError("min_area_m2 must be non-negative")
    if not input_specs:
        raise ValueError("Provide at least one --input SOURCE ID_COLUMN PATH")

    city_box = box(*bbox)
    chunks, before_count = [], 0
    for source, id_column, input_path in input_specs:
        chunk, input_rows = _normalize_input_chunk(gpd, source, id_column, input_path, city_box, shapely, classes)
        chunks.append(chunk)
        before_count += input_rows
    buildings = _deduplicate_measure(gpd, pd, chunks, utm_epsg, min_area_m2, shapely)

    wards = _read_layer(gpd, wards_path).to_crs("EPSG:4326")
    grid = _read_layer(gpd, grid_path).to_crs("EPSG:4326")
    _validate_boundaries(wards, grid)
    buildings = buildings.reset_index(drop=True)
    centroid_geometries = buildings.to_crs(epsg=utm_epsg).geometry.centroid.to_crs("EPSG:4326")
    buildings = _assign_ids(gpd, buildings, wards, "ward_id", "ward_id", centroid_geometries)
    buildings = _assign_ids(gpd, buildings, grid, "cell_id", "cell_id", centroid_geometries)

    buildings = buildings[["bldg_id", "footprint_m2", "source", "ward_id", "cell_id", buildings.geometry.name]]
    buildings = buildings.set_crs("EPSG:4326", allow_override=True)
    stats = {
        "input_rows": before_count,
        "output_rows": len(buildings),
        "removed_rows": before_count - len(buildings),
        "unassigned_ward_rows": int(buildings["ward_id"].isna().sum()),
        "unassigned_cell_rows": int(buildings["cell_id"].isna().sum()),
    }
    return buildings, stats


def process_from_config(
    *,
    config_path: Path,
    input_specs: list[tuple[str, str, Path]],
    wards_path: Path,
    grid_path: Path,
    output_path: Path | None = None,
    min_area_m2: float = 10.0,
) -> tuple[Path, dict[str, int]]:
    import yaml

    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config.get("contract") != "C6@1.0":
        raise ValueError(f"Expected a C6@1.0 city config: {config_path}")
    pack_dir = Path(config["paths"]["pack_dir"])
    if not pack_dir.is_absolute():
        pack_dir = config_path.resolve().parents[1] / pack_dir
    destination = pack_destination(pack_dir, output_path, "buildings.parquet")
    destination.parent.mkdir(parents=True, exist_ok=True)

    buildings, stats = prepare_buildings(
        input_specs=input_specs,
        wards_path=wards_path,
        grid_path=grid_path,
        bbox=config["bbox"],
        utm_epsg=int(config["utm_epsg"]),
        min_area_m2=min_area_m2,
    )
    buildings.to_parquet(destination, index=False)
    return destination, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare contract C0 building footprints as GeoParquet.")
    parser.add_argument("--config", type=Path, required=True, help="City C6 YAML config")
    parser.add_argument(
        "--input",
        action="append",
        nargs=3,
        required=True,
        metavar=("SOURCE", "ID_COLUMN", "PATH"),
        help="Input geodata; repeat in precedence order. SOURCE may be a C0 source or auto for Overture provenance.",
    )
    parser.add_argument("--wards", type=Path, required=True, help="C0 wards GeoJSON")
    parser.add_argument("--grid", type=Path, required=True, help="250 m grid GeoJSON")
    parser.add_argument("--output", type=Path, help="Output path; defaults to buildings.parquet in pack_dir")
    parser.add_argument("--min-area-m2", type=float, default=10.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    specs = [(source, id_column, Path(path)) for source, id_column, path in args.input]
    output, stats = process_from_config(
        config_path=args.config,
        input_specs=specs,
        wards_path=args.wards,
        grid_path=args.grid,
        output_path=args.output,
        min_area_m2=args.min_area_m2,
    )
    LOG.info("Wrote %s", output)
    LOG.info("Statistics: %s", json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
