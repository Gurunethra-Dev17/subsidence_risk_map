"""D1 ward-level aggregation and bounded assignment audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd


class D1Error(ValueError):
    """Invalid D1 input or an unsafe output operation."""


def _coverage_threshold_pct(cfg: dict[str, Any]) -> float:
    params = cfg.get("params", cfg)
    if not isinstance(params, dict):
        raise D1Error("Configuration params must be an object")
    if "coverage_min" in params:
        threshold = params["coverage_min"]
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise D1Error("params.coverage_min must be numeric")
        threshold = float(threshold)
        if 0 < threshold <= 1:
            threshold *= 100
    else:
        threshold = params.get("min_coverage_pct", cfg.get("min_coverage_pct", 50.0))
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise D1Error("min_coverage_pct must be numeric")
        threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise D1Error("Coverage threshold must be a finite percentage from 0 to 100")
    return threshold


def build_ward_indicators(
    metrics: pd.DataFrame,
    wards: pd.DataFrame,
    groundwater: pd.DataFrame | None = None,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Aggregate assigned C1 rows without filling missing measurements or assignments."""
    cfg = cfg or {}
    coverage_min_pct = _coverage_threshold_pct(cfg)
    params = cfg.get("params", cfg)
    sinking_threshold = params.get("sinking_threshold_mm_yr", -4.0)
    if isinstance(sinking_threshold, bool) or not isinstance(sinking_threshold, (int, float)):
        raise D1Error("sinking_threshold_mm_yr must be numeric")
    sinking_threshold = float(sinking_threshold)
    if not math.isfinite(sinking_threshold):
        raise D1Error("sinking_threshold_mm_yr must be finite")

    required_metrics = {"bldg_id", "ward_id", "vlm_mm_yr", "beta_horizon", "sparse"}
    required_wards = {"ward_id", "ward_name"}
    missing_metrics = required_metrics - set(metrics.columns)
    missing_wards = required_wards - set(wards.columns)
    if missing_metrics:
        raise D1Error(f"Missing metrics columns: {sorted(missing_metrics)}")
    if missing_wards:
        raise D1Error(f"Missing ward columns: {sorted(missing_wards)}")
    if wards["ward_id"].isna().any() or wards["ward_id"].astype(str).str.strip().eq("").any():
        raise D1Error("Ward IDs must be non-null and non-empty")
    if wards["ward_id"].duplicated().any():
        raise D1Error("Duplicate ward_id values found in ward geometry")
    if metrics["bldg_id"].isna().any():
        raise D1Error("Building IDs must be non-null")
    if metrics["bldg_id"].duplicated().any():
        raise D1Error("Duplicate bldg_id values found in metrics")
    if metrics["sparse"].isna().any() or not pd.api.types.is_bool_dtype(metrics["sparse"].dtype):
        raise D1Error("sparse must be a non-null boolean column")
    if not metrics["sparse"].eq(metrics["vlm_mm_yr"].isna()).all():
        raise D1Error("C1 sparse values must be true exactly when vlm_mm_yr is null")

    result_wards = wards[["ward_id", "ward_name"]].copy()
    result_wards["ward_id"] = result_wards["ward_id"].astype("string")
    metrics = metrics.copy()
    metrics["ward_id"] = metrics["ward_id"].astype("string")
    assigned = metrics.loc[metrics["ward_id"].notna()].copy()
    invalid_wards = set(assigned["ward_id"].unique()) - set(result_wards["ward_id"].unique())
    if invalid_wards:
        raise D1Error(
            f"Metrics contain ward IDs absent from supplied boundaries: {sorted(invalid_wards)}"
        )

    grouped = (
        assigned.groupby("ward_id", observed=True)
        .agg(
            n_buildings=("bldg_id", "size"),
            n_buildings_with_data=("vlm_mm_yr", "count"),
            vlm_median_mm_yr=("vlm_mm_yr", "median"),
            n_sparse=("sparse", "sum"),
            sinking_count=("vlm_mm_yr", lambda values: (values <= sinking_threshold).sum()),
            n_buildings_with_beta=("beta_horizon", "count"),
            beta_p90_horizon=("beta_horizon", lambda values: values.quantile(0.90)),
        )
        .reset_index()
    )

    result = result_wards.merge(grouped, on="ward_id", how="left", validate="one_to_one")
    count_columns = [
        "n_buildings",
        "n_buildings_with_data",
        "n_sparse",
        "sinking_count",
        "n_buildings_with_beta",
    ]
    result[count_columns] = result[count_columns].fillna(0).astype("int64")
    has_buildings = result["n_buildings"] > 0
    result["coverage_pct"] = 0.0
    result.loc[has_buildings, "coverage_pct"] = (
        result.loc[has_buildings, "n_buildings_with_data"]
        / result.loc[has_buildings, "n_buildings"]
        * 100.0
    )
    result["beta_coverage_pct"] = (
        result["n_buildings_with_beta"] / result["n_buildings"] * 100.0
    ).where(has_buildings)
    result["sparse_pct"] = (result["n_sparse"] / result["n_buildings"] * 100.0).where(has_buildings)
    result["share_sinking_gt4"] = (result["sinking_count"] / result["n_buildings_with_data"]).where(
        result["n_buildings_with_data"] > 0
    )
    result["status"] = "insufficient_data"
    eligible = has_buildings & result["coverage_pct"].ge(coverage_min_pct)
    result.loc[eligible, "status"] = "ranked"

    groundwater_by_ward: dict[str, tuple[Any, Any]] = {}
    if groundwater is not None:
        required_groundwater = {"ward_id", "gw_stage_pct", "gw_category"}
        missing = required_groundwater - set(groundwater.columns)
        if missing:
            raise D1Error(f"Missing groundwater columns: {sorted(missing)}")
        groundwater = groundwater[["ward_id", "gw_stage_pct", "gw_category"]].copy()
        groundwater["ward_id"] = groundwater["ward_id"].astype("string")
        if groundwater["ward_id"].isna().any() or groundwater["ward_id"].duplicated().any():
            raise D1Error("Groundwater ward IDs must be non-null and unique")
        unknown = set(groundwater["ward_id"]) - set(result["ward_id"])
        if unknown:
            raise D1Error(f"Groundwater contains unknown ward IDs: {sorted(unknown)}")
        groundwater_by_ward = {
            str(row.ward_id): (row.gw_stage_pct, row.gw_category)
            for row in groundwater.itertuples(index=False)
        }

    result["gw_stage_pct"] = result["ward_id"].map(
        lambda ward_id: groundwater_by_ward.get(str(ward_id), (pd.NA, pd.NA))[0]
    )
    result["gw_category"] = result["ward_id"].map(
        lambda ward_id: groundwater_by_ward.get(str(ward_id), (pd.NA, pd.NA))[1]
    )
    result["beta_p90_ratio_horizon"] = pd.NA
    result["score"] = pd.NA
    result["rank"] = pd.NA
    result["rank_p05"] = pd.NA
    result["rank_p95"] = pd.NA
    result["histogram"] = None

    flags: list[list[str]] = []
    for row in result.itertuples(index=False):
        row_flags = []
        if row.coverage_pct < coverage_min_pct:
            row_flags.append("low_coverage")
        if row.n_sparse > 0:
            row_flags.append("sparse_points")
        if pd.isna(row.gw_stage_pct):
            row_flags.append("groundwater_missing")
        flags.append(row_flags)
    result["flags"] = flags
    result.attrs["unassigned_buildings"] = int(metrics["ward_id"].isna().sum())
    result.attrs["coverage_min_pct"] = coverage_min_pct

    output_columns = [
        "ward_id",
        "ward_name",
        "status",
        "n_buildings",
        "n_buildings_with_data",
        "coverage_pct",
        "share_sinking_gt4",
        "vlm_median_mm_yr",
        "beta_p90_horizon",
        "beta_p90_ratio_horizon",
        "gw_stage_pct",
        "gw_category",
        "score",
        "rank",
        "rank_p05",
        "rank_p95",
        "flags",
        "histogram",
        # D1 QA fields consumed by later steps when useful; D8 selects C2 fields only.
        "n_sparse",
        "sparse_pct",
        "n_buildings_with_beta",
        "beta_coverage_pct",
    ]
    return result[output_columns]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_geojson_wards(path: Path):
    import geopandas as gpd

    try:
        wards = gpd.read_file(path)
    except Exception as exc:
        raise D1Error(f"Cannot read ward geometry: {exc}") from exc
    required = {"ward_id", "ward_name", "geometry"}
    missing = required - set(wards.columns)
    if missing:
        raise D1Error(f"Ward geometry is missing columns: {sorted(missing)}")
    if wards.crs is None or wards.crs.to_epsg() != 4326:
        raise D1Error("Ward GeoJSON must use EPSG:4326 coordinates")
    if len(wards) != 250:
        raise D1Error(f"Expected 250 ward geometries, found {len(wards)}")
    if wards["ward_id"].isna().any() or wards["ward_id"].astype(str).str.strip().eq("").any():
        raise D1Error("Ward geometry has a null or empty ward_id")
    if wards["ward_id"].astype(str).duplicated().any():
        raise D1Error("Ward geometry contains duplicate ward_id values")
    geometries = wards.geometry
    if geometries.isna().any() or geometries.is_empty.any() or (~geometries.is_valid).any():
        raise D1Error("Ward geometry contains null, empty, or invalid polygons")
    if not geometries.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise D1Error("Ward geometry must contain only Polygon or MultiPolygon features")
    return wards


def _check_geoparquet_crs(path: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq
    from pyproj import CRS

    parquet = pq.ParquetFile(path)
    metadata = parquet.schema_arrow.metadata or {}
    if b"geo" not in metadata:
        raise D1Error("C0 buildings Parquet has no GeoParquet metadata")
    try:
        geo = json.loads(metadata[b"geo"])
        column = geo["columns"][geo["primary_column"]]
        crs_json = column.get("crs")
        crs = CRS.from_json_dict(crs_json) if crs_json else CRS.from_user_input("OGC:CRS84")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise D1Error("C0 GeoParquet CRS metadata is malformed") from exc
    if not crs.equals(CRS.from_epsg(4326), ignore_axis_order=True):
        raise D1Error("C0 building geometry must be WGS84 / EPSG:4326")
    if "geometry" not in parquet.schema_arrow.names:
        raise D1Error("C0 buildings Parquet has no geometry column")
    return {
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "crs": "EPSG:4326",
        "geometry_column": geo["primary_column"],
        "geometry_types_metadata": column.get("geometry_types", []),
    }


def _compare_c0_c1(c0_path: Path, c1_path: Path) -> dict[str, int]:
    import duckdb

    connection = duckdb.connect(database=":memory:")
    try:
        c0_rows, c0_nulls, c0_duplicates = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE bldg_id IS NULL), "
            "count(*) - count(DISTINCT bldg_id) FROM read_parquet(?)",
            [str(c0_path)],
        ).fetchone()
        c1_rows, c1_nulls, c1_duplicates = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE bldg_id IS NULL), "
            "count(*) - count(DISTINCT bldg_id) FROM read_parquet(?)",
            [str(c1_path)],
        ).fetchone()
        if c0_nulls or c1_nulls or c0_duplicates or c1_duplicates:
            raise D1Error("C0/C1 building IDs must be non-null and unique before matching")
        comparison = connection.execute(
            "SELECT "
            "count(*) FILTER (WHERE c0.bldg_id IS NULL), "
            "count(*) FILTER (WHERE c1.bldg_id IS NULL), "
            "count(*) FILTER (WHERE c0.ward_id IS DISTINCT FROM c1.ward_id), "
            "count(*) FILTER (WHERE c0.cell_id IS DISTINCT FROM c1.cell_id) "
            "FROM read_parquet(?) AS c0 FULL OUTER JOIN read_parquet(?) AS c1 USING (bldg_id)",
            [str(c0_path), str(c1_path)],
        ).fetchone()
    finally:
        connection.close()
    return {
        "c0_rows": int(c0_rows),
        "c1_rows": int(c1_rows),
        "c0_only_ids": int(comparison[0]),
        "c1_only_ids": int(comparison[1]),
        "ward_assignment_differences": int(comparison[2]),
        "cell_assignment_differences": int(comparison[3]),
    }


def _audit_spatial_assignments(buildings_path: Path, wards) -> dict[str, Any]:
    """Stream C0 WKB and compare centroid membership with existing ward IDs."""
    import numpy as np
    import pyarrow.parquet as pq
    import shapely
    from shapely import STRtree

    parquet = pq.ParquetFile(buildings_path)
    required = {"bldg_id", "ward_id", "geometry"}
    if not required.issubset(parquet.schema_arrow.names):
        raise D1Error(
            f"C0 is missing spatial audit columns: {sorted(required - set(parquet.schema_arrow.names))}"
        )
    ward_ids = np.asarray(wards["ward_id"].astype(str).to_list(), dtype=object)
    ward_geometries = np.asarray(wards.geometry.to_list(), dtype=object)
    tree = STRtree(ward_geometries)
    counts: dict[str, int] = {
        "total_buildings": 0,
        "unassigned_buildings": 0,
        "assigned_buildings": 0,
        "geometry_missing": 0,
        "geometry_empty": 0,
        "geometry_invalid": 0,
        "geometry_non_polygon": 0,
        "unassigned_inside_unique_ward": 0,
        "unassigned_boundary_intersection": 0,
        "unassigned_overlapping_wards": 0,
        "unassigned_outside_ward_coverage": 0,
        "unassigned_unusable_geometry": 0,
        "assigned_centroid_matches_ward": 0,
        "assigned_centroid_mismatch": 0,
        "assigned_boundary_intersection": 0,
        "assigned_overlapping_wards": 0,
        "assigned_outside_ward_coverage": 0,
        "assigned_unusable_geometry": 0,
    }

    for batch in parquet.iter_batches(columns=["ward_id", "geometry"], batch_size=25_000):
        raw_wards = batch.column("ward_id").to_pylist()
        raw_wkb = batch.column("geometry").to_pylist()
        n_rows = len(raw_wards)
        counts["total_buildings"] += n_rows
        assignment = np.asarray(
            [
                str(value) if value is not None and str(value).strip() else None
                for value in raw_wards
            ],
            dtype=object,
        )
        assigned = np.asarray([value is not None for value in assignment], dtype=bool)
        counts["assigned_buildings"] += int(assigned.sum())
        counts["unassigned_buildings"] += int((~assigned).sum())

        try:
            geometries = shapely.from_wkb(raw_wkb, on_invalid="raise")
        except Exception as exc:
            raise D1Error(
                "C0 contains malformed WKB geometry; spatial assignment audit stopped"
            ) from exc
        missing = np.asarray(shapely.is_missing(geometries), dtype=bool)
        empty = (~missing) & np.asarray(shapely.is_empty(geometries), dtype=bool)
        type_ids = np.asarray(shapely.get_type_id(geometries), dtype=np.int8)
        polygonal = np.isin(type_ids, [3, 6])
        invalid = (
            (~missing)
            & (~empty)
            & polygonal
            & (~np.asarray(shapely.is_valid(geometries), dtype=bool))
        )
        unsupported = (~missing) & (~empty) & (~polygonal)
        usable = (~missing) & (~empty) & polygonal & (~invalid)
        counts["geometry_missing"] += int(missing.sum())
        counts["geometry_empty"] += int(empty.sum())
        counts["geometry_invalid"] += int(invalid.sum())
        counts["geometry_non_polygon"] += int(unsupported.sum())
        unusable = ~usable
        counts["unassigned_unusable_geometry"] += int((~assigned & unusable).sum())
        counts["assigned_unusable_geometry"] += int((assigned & unusable).sum())
        if not usable.any():
            continue

        usable_rows = np.flatnonzero(usable)
        centroids = shapely.centroid(geometries[usable])
        within_pairs = tree.query(centroids, predicate="within")
        intersect_pairs = tree.query(centroids, predicate="intersects")
        within_count = np.bincount(within_pairs[0], minlength=len(usable_rows))
        intersect_count = np.bincount(intersect_pairs[0], minlength=len(usable_rows))
        unique_within = within_count == 1
        expected_ward = np.full(len(usable_rows), None, dtype=object)
        if unique_within.any():
            unique_pairs = within_pairs[:, within_count[within_pairs[0]] == 1]
            expected_ward[unique_pairs[0]] = ward_ids[unique_pairs[1]]
        existing = assignment[usable_rows]
        has_assignment = np.asarray([value is not None for value in existing], dtype=bool)
        boundary = (within_count == 0) & (intersect_count > 0)
        overlap = within_count > 1
        outside = intersect_count == 0
        matched = has_assignment & unique_within & (existing == expected_ward)
        mismatch = has_assignment & unique_within & (existing != expected_ward)
        unassigned = ~has_assignment
        counts["assigned_centroid_matches_ward"] += int(matched.sum())
        counts["assigned_centroid_mismatch"] += int(mismatch.sum())
        counts["assigned_boundary_intersection"] += int((has_assignment & boundary).sum())
        counts["assigned_overlapping_wards"] += int((has_assignment & overlap).sum())
        counts["assigned_outside_ward_coverage"] += int((has_assignment & outside).sum())
        counts["unassigned_inside_unique_ward"] += int((unassigned & unique_within).sum())
        counts["unassigned_boundary_intersection"] += int((unassigned & boundary).sum())
        counts["unassigned_overlapping_wards"] += int((unassigned & overlap).sum())
        counts["unassigned_outside_ward_coverage"] += int((unassigned & outside).sum())

    counts["assigned_classified_total"] = sum(
        counts[key]
        for key in (
            "assigned_centroid_matches_ward",
            "assigned_centroid_mismatch",
            "assigned_boundary_intersection",
            "assigned_overlapping_wards",
            "assigned_outside_ward_coverage",
            "assigned_unusable_geometry",
        )
    )
    counts["unassigned_classified_total"] = sum(
        counts[key]
        for key in (
            "unassigned_inside_unique_ward",
            "unassigned_boundary_intersection",
            "unassigned_overlapping_wards",
            "unassigned_outside_ward_coverage",
            "unassigned_unusable_geometry",
        )
    )
    return {
        **counts,
        "assignment_rule": (
            "C0 building polygon centroid tested against EPSG:4326 ward polygons; "
            "strict within is unique assignment, intersects-only is boundary, multiple within is overlap."
        ),
        "boundary_policy": "No boundary or ambiguous case is assigned to a ward; no nearest-ward fallback.",
        "derived_assignments_applied": False,
        "metric_crs_used": False,
        "metric_crs_note": "No metric distance/area operation was used; point-in-polygon is topological in the shared geographic CRS.",
    }


def _validate_run_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    import pyarrow.parquet as pq
    import yaml
    from jsonschema import Draft202012Validator

    for name, path in (
        ("C0 buildings", args.buildings_parquet),
        ("C1 metrics", args.metrics_parquet),
        ("C1 run summary", args.run_summary),
        ("C6 config", args.config_yaml),
        ("ward geometry", args.wards_geojson),
        ("integration manifest", args.integration_manifest),
    ):
        if not path.is_file():
            raise D1Error(f"{name} file does not exist: {path}")
    try:
        config = yaml.safe_load(args.config_yaml.read_text(encoding="utf-8-sig"))
        summary = json.loads(args.run_summary.read_text(encoding="utf-8-sig"))
        manifest = json.loads(args.integration_manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise D1Error(f"Cannot read D1 metadata input: {exc}") from exc
    schema_path = (
        Path(__file__).resolve().parents[1] / "contracts" / "schemas" / "config.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(config), key=lambda error: error.json_path
    )
    if errors:
        raise D1Error(
            f"Selected C6 configuration is invalid: {errors[0].json_path}: {errors[0].message}"
        )
    if summary.get("contract") != "C1@1.0" or summary.get("city") != config.get("city"):
        raise D1Error("C1 run summary contract/city does not match selected C6 configuration")
    c1 = manifest.get("c1_candidate", {})
    c0 = manifest.get("c0_candidate", {})
    if not isinstance(c1, dict) or not isinstance(c0, dict):
        raise D1Error("Integration manifest does not contain C0/C1 candidate objects")
    if c1.get("engine_version") != summary.get("engine_version"):
        raise D1Error("C1 run summary engine version differs from integration manifest")
    if c1.get("params_hash") != summary.get("params_hash"):
        raise D1Error("C1 run summary parameter hash differs from integration manifest")
    if summary.get("params") != config.get("params"):
        raise D1Error("C1 run summary params differ from the selected C6 params")
    if summary.get("seed") != config.get("seed"):
        raise D1Error("C1 run summary seed differs from the selected C6 config")
    if summary.get("params", {}).get("horizon_years") != config.get("params", {}).get(
        "horizon_years"
    ):
        raise D1Error("C1 run summary horizon differs from the selected C6 params")
    canonical = json.dumps(
        config["params"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    expected_params_hash = hashlib.sha256(canonical).hexdigest()
    if expected_params_hash != c1.get("params_hash"):
        raise D1Error("Selected C6 params hash differs from the staged C1 hash")
    if _sha256(args.metrics_parquet) != c1.get("sha256"):
        raise D1Error("Selected C1 file hash differs from the integration manifest")
    manifest_c0 = {item.get("path"): item for item in c0.get("files", []) if isinstance(item, dict)}
    buildings_entry = manifest_c0.get("out/delhi/buildings.parquet")
    if not isinstance(buildings_entry, dict) or _sha256(
        args.buildings_parquet
    ) != buildings_entry.get("actual_sha256", buildings_entry.get("manifest_sha256")):
        raise D1Error("Selected C0 buildings hash differs from the integration manifest")
    c0_metadata = _check_geoparquet_crs(args.buildings_parquet)
    c1_file = pq.ParquetFile(args.metrics_parquet)
    if c1_file.metadata.num_rows != int(summary.get("buildings_processed", -1)):
        raise D1Error("C1 Parquet row count differs from its run summary")
    if c1_file.metadata.num_rows != c0_metadata["rows"]:
        raise D1Error("C0/C1 Parquet row counts differ")
    c1_columns = set(c1_file.schema_arrow.names)
    required_c1 = {"bldg_id", "ward_id", "cell_id", "vlm_mm_yr", "beta_horizon", "sparse"}
    if not required_c1.issubset(c1_columns):
        raise D1Error(
            f"C1 is missing required aggregation columns: {sorted(required_c1 - c1_columns)}"
        )
    if config.get("city") != "delhi":
        raise D1Error("This explicit real-data command expects the selected Delhi C6 config")
    return config, summary, {"c0": c0_metadata, "c1_rows": c1_file.metadata.num_rows}, manifest


def _validate_c1_row_metadata(path: Path, engine_version: str, params_hash: str) -> dict[str, int]:
    import duckdb

    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            "SELECT count(*) FILTER (WHERE engine_version IS DISTINCT FROM ?), "
            "count(*) FILTER (WHERE params_hash IS DISTINCT FROM ?) "
            "FROM read_parquet(?)",
            [engine_version, params_hash, str(path)],
        ).fetchone()
    finally:
        connection.close()
    result = {"engine_version_mismatches": int(row[0]), "params_hash_mismatches": int(row[1])}
    if any(result.values()):
        raise D1Error("C1 contains rows with inconsistent engine_version or params_hash")
    return result


def run_d1(args: argparse.Namespace) -> dict[str, Any]:
    """Run D1 with explicit authoritative files and write versioned outputs atomically."""
    output_paths = [args.ward_output, args.qa_output]
    if args.ward_output.resolve() == args.qa_output.resolve():
        raise D1Error("Ward CSV and QA JSON output paths must differ")
    input_paths = {
        args.buildings_parquet.resolve(),
        args.metrics_parquet.resolve(),
        args.run_summary.resolve(),
        args.config_yaml.resolve(),
        args.wards_geojson.resolve(),
        args.integration_manifest.resolve(),
    }
    if any(path.resolve() in input_paths for path in output_paths):
        raise D1Error("D1 output paths must not overwrite any input artifact")
    if not args.overwrite and any(path.exists() for path in output_paths):
        raise D1Error(
            "D1 output already exists; choose a new versioned directory or pass --overwrite"
        )
    config, summary, c0_metadata, manifest = _validate_run_inputs(args)
    wards = _validate_geojson_wards(args.wards_geojson)
    compatibility = _compare_c0_c1(args.buildings_parquet, args.metrics_parquet)
    if compatibility["c0_rows"] != compatibility["c1_rows"]:
        raise D1Error("C0/C1 row counts differ")
    if any(
        compatibility[key]
        for key in (
            "c0_only_ids",
            "c1_only_ids",
            "ward_assignment_differences",
            "cell_assignment_differences",
        )
    ):
        raise D1Error("C0/C1 IDs or source ward/cell assignments differ; aggregation stopped")
    row_metadata = _validate_c1_row_metadata(
        args.metrics_parquet, summary["engine_version"], summary["params_hash"]
    )
    spatial = _audit_spatial_assignments(args.buildings_parquet, wards)
    metrics = pd.read_parquet(
        args.metrics_parquet,
        columns=["bldg_id", "ward_id", "vlm_mm_yr", "beta_horizon", "sparse"],
    )
    if len(metrics) != c0_metadata["c1_rows"]:
        raise D1Error("Loaded C1 row count changed during D1 execution")
    aggregated = build_ward_indicators(metrics, wards[["ward_id", "ward_name"]], cfg=config)
    reconciled = int(aggregated["n_buildings"].sum()) + int(metrics["ward_id"].isna().sum())
    if reconciled != len(metrics):
        raise D1Error("Ward building counts plus unassigned rows do not reconcile to C1 rows")

    coverage = aggregated["coverage_pct"].astype(float)
    beta_coverage = aggregated["beta_coverage_pct"].dropna().astype(float)
    qa = {
        "report_type": "D1 ward aggregation QA",
        "city": config["city"],
        "contract": "C1@1.0",
        "generated_utc": pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z"),
        "input_files": {
            name: {
                "path": str(path.resolve()),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for name, path in {
                "c0_buildings": args.buildings_parquet,
                "c1_metrics": args.metrics_parquet,
                "c1_run_summary": args.run_summary,
                "c6_config": args.config_yaml,
                "ward_geometry": args.wards_geojson,
                "integration_manifest": args.integration_manifest,
            }.items()
        },
        "c1_provenance": {
            "engine_version": summary["engine_version"],
            "params_hash": summary["params_hash"],
            "pair_min_m": config["params"]["pair_min_m"],
            "pair_max_m": config["params"]["pair_max_m"],
            "buildings_processed": int(summary["buildings_processed"]),
        },
        "c0_geometry": c0_metadata["c0"],
        "c0_c1_compatibility": compatibility,
        "c1_row_metadata": row_metadata,
        "c0_pack_completeness": {
            "manifest_complete": bool(
                manifest.get("c0_candidate", {}).get("c0_manifest_complete", False)
            ),
            "missing_artifacts": manifest.get("c0_candidate", {}).get("missing_artifacts", []),
        },
        "assignment_audit": spatial,
        "aggregation": {
            "input_buildings": len(metrics),
            "assigned_buildings": int(metrics["ward_id"].notna().sum()),
            "unassigned_buildings": int(metrics["ward_id"].isna().sum()),
            "building_count_reconciliation": reconciled,
            "output_wards": len(aggregated),
            "unique_output_wards": int(aggregated["ward_id"].nunique()),
            "wards_without_buildings": int(aggregated["n_buildings"].eq(0).sum()),
            "wards_meeting_coverage": int(aggregated["status"].eq("ranked").sum()),
            "wards_insufficient_coverage": int(aggregated["status"].eq("insufficient_data").sum()),
            "coverage_min_pct": float(aggregated.attrs["coverage_min_pct"]),
            "vlm_coverage_pct": {
                "min": float(coverage.min()),
                "median": float(coverage.median()),
                "p90": float(coverage.quantile(0.9)),
                "max": float(coverage.max()),
            },
            "beta_coverage_pct": {
                "wards_with_beta": int(beta_coverage.size),
                "min": float(beta_coverage.min()) if not beta_coverage.empty else None,
                "median": float(beta_coverage.median()) if not beta_coverage.empty else None,
                "p90": float(beta_coverage.quantile(0.9)) if not beta_coverage.empty else None,
                "max": float(beta_coverage.max()) if not beta_coverage.empty else None,
            },
            "indicators": {
                "share_sinking_gt4": _series_summary(aggregated["share_sinking_gt4"]),
                "vlm_median_mm_yr": _series_summary(aggregated["vlm_median_mm_yr"]),
                "beta_p90_horizon": _series_summary(aggregated["beta_p90_horizon"]),
            },
        },
        "limitations": [
            "Ward aggregation uses only existing C1 ward_id assignments; no spatially derived assignment was applied.",
            "Spatial audit uses building polygon centroids and strict within; boundary/overlap cases remain unresolved.",
            "C0 PACK_MANIFEST is incomplete because vlm_points.parquet is missing; full C0-pack validation is not established.",
            "D1 does not calculate groundwater context, scores, rankings, rank ranges, or cell scores.",
        ],
    }
    args.ward_output.parent.mkdir(parents=True, exist_ok=True)
    args.qa_output.parent.mkdir(parents=True, exist_ok=True)
    ward_temp = args.ward_output.with_suffix(args.ward_output.suffix + ".tmp")
    qa_temp = args.qa_output.with_suffix(args.qa_output.suffix + ".tmp")
    try:
        aggregated.to_csv(ward_temp, index=False)
        qa_temp.write_text(
            json.dumps(qa, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
        )
        os.replace(ward_temp, args.ward_output)
        os.replace(qa_temp, args.qa_output)
    except Exception:
        ward_temp.unlink(missing_ok=True)
        qa_temp.unlink(missing_ok=True)
        raise
    return qa


def _series_summary(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return {"count": 0, "min": None, "median": None, "p90": None, "max": None}
    return {
        "count": int(numeric.size),
        "min": float(numeric.min()),
        "median": float(numeric.median()),
        "p90": float(numeric.quantile(0.9)),
        "max": float(numeric.max()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate D1 ward indicators from explicit C0/C1 inputs"
    )
    parser.add_argument(
        "--buildings-parquet",
        type=Path,
        required=True,
        help="Authoritative C0 buildings GeoParquet",
    )
    parser.add_argument(
        "--metrics-parquet", type=Path, required=True, help="Selected C1 building_metrics.parquet"
    )
    parser.add_argument(
        "--run-summary", type=Path, required=True, help="Matching C1 run summary JSON"
    )
    parser.add_argument(
        "--config-yaml", type=Path, required=True, help="Matching C6 city configuration"
    )
    parser.add_argument(
        "--wards-geojson", type=Path, required=True, help="250-ward EPSG:4326 GeoJSON"
    )
    parser.add_argument(
        "--integration-manifest", type=Path, required=True, help="Staging integration manifest"
    )
    parser.add_argument(
        "--ward-output", type=Path, required=True, help="Output ward_indicators.csv"
    )
    parser.add_argument("--qa-output", type=Path, required=True, help="Output d1_qa.json")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing D1 outputs")
    args = parser.parse_args(argv)
    try:
        qa = run_d1(args)
    except (D1Error, OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"D1 failed: {exc}\n")
    summary = qa["aggregation"]
    print(
        f"D1 complete: {summary['input_buildings']} buildings, "
        f"{summary['output_wards']} wards; outputs {args.ward_output} and {args.qa_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
