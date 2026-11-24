"""Convert Virginia Tech building-risk polygons for a configured city."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from pipeline.paths import load_c6_config

LOG = logging.getLogger("pipeline.risk")
GEOGRAPHIC_CRS = "EPSG:4326"

SOURCE_FIELDS = {
    "risk_insar": "risk_insar",
    "risk_10yrs": "risk_10yrs",
    "risk_30yrs": "risk_30yrs",
    "risk_50 yr": "risk_50yrs",
}


def _modules() -> tuple[Any, Any, Any]:
    try:
        import geopandas as gpd
        import pandas as pd
        import shapely
    except ImportError as exc:
        raise RuntimeError("The risk converter needs the optional geo dependencies; install the project with [geo].") from exc
    return gpd, pd, shapely


def convert_risk_layer(
    *, input_path: Path, output_path: Path, bbox: list[float]
) -> dict[str, Any]:
    """Filter the source shapefile by city bbox, normalize fields and write GeoParquet."""
    gpd, pd, _ = _modules()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")

    frame = gpd.read_file(input_path, bbox=tuple(bbox))
    if frame.crs is None:
        raise ValueError(f"Risk source has no CRS; refusing to guess: {input_path}")
    folded = {str(column).strip().casefold(): column for column in frame.columns}
    missing = [name for name in SOURCE_FIELDS if name.casefold() not in folded]
    if missing:
        raise ValueError(f"Risk source is missing fields: {', '.join(missing)}")
    geometry_name = frame.geometry.name
    source_id = folded.get("index")
    selected = [folded[name.casefold()] for name in SOURCE_FIELDS]
    if source_id:
        selected = [source_id, *selected]
    frame = frame[[*selected, geometry_name]].copy().to_crs(GEOGRAPHIC_CRS)

    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("Risk source contains null or empty geometry")
    if not frame.geometry.is_valid.all():
        raise ValueError("Risk source contains invalid geometry; inspect and repair before conversion")
    if not frame.geometry.geom_type.isin({"Polygon", "MultiPolygon"}).all():
        raise ValueError("Risk source contains non-polygon geometry")

    output = pd.DataFrame(index=frame.index)
    output["bldg_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    missing_counts: dict[str, int] = {}
    risk_counts: dict[str, dict[str, int]] = {}
    for source_name, target_name in SOURCE_FIELDS.items():
        source_column = folded[source_name.casefold()]
        values = pd.to_numeric(frame[source_column], errors="coerce")
        invalid_values = values.notna() & ~values.isin({0, 1, 2, 3, 4})
        if invalid_values.any():
            raise ValueError(f"{source_column} contains non-category values: {values[invalid_values].head().tolist()}")
        missing_counts[target_name] = int(values.isna().sum())
        counts = values.value_counts(dropna=True).sort_index()
        risk_counts[target_name] = {str(int(k)): int(v) for k, v in counts.items()}
        output[target_name] = values.astype("Int8")

    output = gpd.GeoDataFrame(output, geometry=frame.geometry, crs=GEOGRAPHIC_CRS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False, compression="snappy")

    stats: dict[str, Any] = {
        "rows": len(output),
        "crs": GEOGRAPHIC_CRS,
        "geometry_types": output.geometry.geom_type.value_counts().to_dict(),
        "risk_null_counts": missing_counts,
        "risk_category_counts": risk_counts,
        "bldg_id_null_count": len(output),
        "source_id_distinct": int(frame[source_id].nunique()) if source_id else None,
        "source_id_field": source_id,
    }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Virginia Tech risk polygons to C0 GeoParquet fields.")
    parser.add_argument("--config", type=Path, required=True, help="City C6 YAML config")
    parser.add_argument("--input", type=Path, required=True, help="Risk shapefile")
    parser.add_argument("--output", type=Path, required=True, help="Output GeoParquet path")
    args = parser.parse_args()
    _project_root, config = load_c6_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = convert_risk_layer(input_path=args.input, output_path=args.output, bbox=config["bbox"])
    LOG.info("Wrote %s", args.output)
    LOG.info("Statistics: %s", json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
