"""Normalize an acquired ward boundary layer into the C0 wards.geojson layer."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from pipeline.paths import load_c6_config, resolve_pack_dir

LOG = logging.getLogger("pipeline.wards")
GEOGRAPHIC_CRS = "EPSG:4326"
WARDS_FILENAME = "wards.geojson"


def _polygonal_only(geometry: Any, shapely: Any) -> tuple[Any, int]:
    """Keep polygon components from a repaired geometry, dropping lower dimensions."""
    if geometry is None or geometry.is_empty:
        return None, 0
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry, 0
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
        import shapely
    except ImportError as exc:
        raise RuntimeError(
            "The ward pipeline needs the optional geo dependencies; install the project with [geo]."
        ) from exc
    return gpd, shapely


def _repair_ward_geometries(geometries: list[Any], shapely: Any) -> tuple[list[Any], int, int]:
    fixed, repaired_count, discarded_parts = [], 0, 0
    for geometry in geometries:
        if geometry is not None and not geometry.is_valid:
            geometry = shapely.make_valid(geometry)
            repaired_count += 1
        geometry, discarded = _polygonal_only(geometry, shapely)
        discarded_parts += discarded
        fixed.append(geometry)
    return fixed, repaired_count, discarded_parts


def normalize_wards(
    *,
    input_path: Path,
    id_column: str,
    name_column: str,
    city: str,
    source: str,
    source_year: int,
    bbox: list[float],
    expected_count: int | None = None,
) -> tuple[Any, dict[str, int]]:
    """Validate and normalize ward polygons for one configured city."""
    gpd, shapely = _geo_modules()
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if input_path.suffix.lower() in {".parquet", ".geoparquet"}:
        wards = gpd.read_parquet(input_path)
    else:
        wards = gpd.read_file(input_path)
    if wards.crs is None:
        raise ValueError(f"Ward source has no CRS; refusing to guess: {input_path}")
    missing_columns = [name for name in (id_column, name_column) if name not in wards.columns]
    if missing_columns:
        raise ValueError(f"Ward source is missing configured columns: {', '.join(missing_columns)}")

    input_count = len(wards)
    wards = wards[[id_column, name_column, wards.geometry.name]].copy()
    wards = wards.rename(columns={id_column: "ward_id", name_column: "ward_name"})
    wards = wards.to_crs(GEOGRAPHIC_CRS)
    wards = wards.loc[wards["ward_id"].notna() & wards["ward_name"].notna()].copy()
    wards["ward_id"] = wards["ward_id"].map(lambda value: str(value).strip())
    wards["ward_name"] = wards["ward_name"].map(lambda value: str(value).strip())
    wards = wards.loc[(wards["ward_id"] != "") & (wards["ward_name"] != "")].copy()
    wards = wards.loc[wards.geometry.notna() & ~wards.geometry.is_empty].copy()
    if wards["ward_id"].duplicated().any():
        duplicates = wards.loc[wards["ward_id"].duplicated(keep=False), "ward_id"].unique().tolist()
        raise ValueError(f"Ward IDs must be unique; duplicate examples: {duplicates[:10]}")

    fixed_geometries, repaired_count, discarded_parts = _repair_ward_geometries(wards.geometry.tolist(), shapely)
    wards[wards.geometry.name] = fixed_geometries
    wards = wards.loc[wards.geometry.notna() & ~wards.geometry.is_empty].copy()
    polygonal = wards.geometry.geom_type.isin({"Polygon", "MultiPolygon"})
    if not polygonal.all():
        kinds = wards.loc[~polygonal].geometry.geom_type.value_counts().to_dict()
        raise ValueError(f"Ward boundaries must be polygonal after repair; found {kinds}")
    if not wards.geometry.is_valid.all():
        raise ValueError("Ward geometry repair did not produce valid polygons")

    min_lon, min_lat, max_lon, max_lat = bbox
    city_box = shapely.box(min_lon, min_lat, max_lon, max_lat)
    wards = wards.loc[wards.geometry.intersects(city_box)].copy()
    wards["city"] = city
    wards["source"] = source
    wards["source_year"] = int(source_year)
    wards = wards[["ward_id", "ward_name", "city", "source", "source_year", wards.geometry.name]]
    wards = wards.set_crs(GEOGRAPHIC_CRS, allow_override=True).reset_index(drop=True)

    if wards["ward_id"].isna().any() or wards["ward_id"].duplicated().any():
        raise ValueError("Normalized ward IDs must be non-null and unique")
    if expected_count is not None and len(wards) != expected_count:
        raise ValueError(f"Expected {expected_count} wards, found {len(wards)}")

    stats = {
        "input_rows": input_count,
        "output_rows": len(wards),
        "excluded_rows": input_count - len(wards),
        "repaired_invalid_geometries": repaired_count,
        "discarded_nonpolygon_parts": discarded_parts,
    }
    return wards, stats


def process_from_config(
    *,
    config_path: Path,
    input_path: Path,
    id_column: str,
    name_column: str,
    source: str,
    source_year: int,
    output_path: Path | None = None,
    expected_count: int | None = None,
) -> tuple[Path, dict[str, int]]:
    project_root, config = load_c6_config(config_path)
    pack_dir = resolve_pack_dir(project_root, config["paths"]["pack_dir"])
    destination = (pack_dir / WARDS_FILENAME).resolve()
    if output_path is not None:
        requested_destination = (
            output_path.resolve()
            if output_path.is_absolute()
            else (pack_dir / output_path).resolve()
        )
        if requested_destination != destination:
            raise ValueError(f"C0 ward output must be {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    wards, stats = normalize_wards(
        input_path=input_path,
        id_column=id_column,
        name_column=name_column,
        city=config["city"],
        source=source,
        source_year=source_year,
        bbox=config["bbox"],
        expected_count=expected_count,
    )
    wards.to_file(destination, driver="GeoJSON", index=False)
    return destination, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare contract C0 ward polygons as GeoJSON.")
    parser.add_argument("--config", type=Path, required=True, help="City C6 YAML config")
    parser.add_argument("--input", type=Path, required=True, help="Acquired ward polygon file")
    parser.add_argument("--id-column", required=True, help="Source column containing stable ward IDs")
    parser.add_argument("--name-column", required=True, help="Source column containing ward names")
    parser.add_argument("--source", required=True, help="Human-readable ward boundary source")
    parser.add_argument("--source-year", type=int, required=True)
    parser.add_argument("--expected-count", type=int, help="Fail if output ward count differs")
    parser.add_argument("--output", type=Path, help="Output path; defaults to wards.geojson in pack_dir")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    output, stats = process_from_config(
        config_path=args.config,
        input_path=args.input,
        id_column=args.id_column,
        name_column=args.name_column,
        source=args.source,
        source_year=args.source_year,
        output_path=args.output,
        expected_count=args.expected_count,
    )
    LOG.info("Wrote %s", output)
    LOG.info("Statistics: %s", json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
