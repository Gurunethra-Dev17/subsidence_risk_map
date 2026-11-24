"""Compare C1 metrics with the published VT risk layer using strict geometry identity.

The VT source has no joinable building IDs. This module deliberately accepts only unique,
byte-identical WKB footprints as correspondences. It does not infer nearby or overlapping matches.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import jsonschema
import pyarrow as pa
import pyarrow.parquet as pq
import yaml


class D5Error(ValueError):
    """Invalid D5 input or output operation."""


C3_KEYS = {"n_buildings", "spearman_rho", "labels", "confusion_matrix", "note"}
LABELS = ["0", "1", "2", "3", "4"]
RISK_COLUMNS = ("risk_insar", "risk_10yrs", "risk_30yrs", "risk_50yrs")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise D5Error(f"Cannot read JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise D5Error(f"JSON input must be an object: {path}")
    return value


def _check_geo_metadata(path: Path, *, require_risk_fields: bool) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    required = {"geometry", "bldg_id"}
    if require_risk_fields:
        required.update(RISK_COLUMNS)
    missing = required - set(schema.names)
    if missing:
        raise D5Error(f"Parquet input is missing required columns: {path}")
    if schema.field("bldg_id").type != pa.string() or schema.field("geometry").type != pa.binary():
        raise D5Error(f"Parquet building IDs and geometry must be string and WKB binary: {path}")
    raw_geo = (schema.metadata or {}).get(b"geo")
    if raw_geo is None:
        raise D5Error(f"GeoParquet metadata is missing: {path}")
    try:
        geo = json.loads(raw_geo)
        geometry_info = geo["columns"]["geometry"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise D5Error(f"GeoParquet geometry metadata is invalid: {path}") from exc
    crs = geometry_info.get("crs")
    crs_code = (crs or {}).get("id", {}).get("code") if isinstance(crs, dict) else None
    if crs_code != 4326:
        raise D5Error(f"Geometry input must declare EPSG:4326: {path}")
    geometry_types = geometry_info.get("geometry_types", [])
    if not geometry_types or any(
        value not in {"Polygon", "MultiPolygon"} for value in geometry_types
    ):
        raise D5Error(f"Geometry input must contain polygonal features: {path}")
    return {
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "geometry_types": geometry_types,
        "crs": "EPSG:4326",
    }


def _verify_input_provenance(
    c0_path: Path,
    c1_path: Path,
    risk_path: Path,
    pack_manifest_path: Path,
    integration_manifest_path: Path,
) -> dict[str, str]:
    pack = _read_json(pack_manifest_path)
    integration = _read_json(integration_manifest_path)
    pack_files = {entry.get("name"): entry for entry in pack.get("files", [])}
    integration_c0 = integration.get("c0_candidate", {})
    c0_entry = next(
        (
            entry
            for entry in integration_c0.get("files", [])
            if Path(entry.get("path", "")).name == c0_path.name
        ),
        None,
    )
    integration_c1 = integration.get("c1_candidate", {})
    integration_config_hash = integration_c1.get("c6_reference_config_sha256")
    expected = {
        "c0": c0_entry.get("actual_sha256") if c0_entry else None,
        "c0_pack": pack_files.get(c0_path.name, {}).get("sha256"),
        "c1": integration_c1.get("sha256"),
        "vt": pack_files.get(risk_path.name, {}).get("sha256"),
    }
    actual = {"c0": _sha256(c0_path), "c1": _sha256(c1_path), "vt": _sha256(risk_path)}
    if any(not expected[key] or actual[key] != expected[key] for key in actual):
        raise D5Error("An input checksum does not match its supplied manifest")
    if actual["c0"] != expected["c0_pack"]:
        raise D5Error("C0 building checksum differs between supplied manifests")
    c1_metadata = pq.ParquetFile(c1_path).schema_arrow.metadata or {}
    decoded = {key.decode(): value.decode() for key, value in c1_metadata.items()}
    expected_c1 = {
        "contract": "C1@1.0",
        "engine_version": "f3af18a",
        "params_hash": "1a30d00c183cb58b2ee4d9327d9e839a8bc3f4267a0c3b15b207c181b49ac6d5",
        "horizon_years": "10",
        "seed": "42",
    }
    if any(decoded.get(key) != value for key, value in expected_c1.items()):
        raise D5Error("C1 file metadata does not match the approved staged baseline")
    return {
        "c0": actual["c0"],
        "c1": actual["c1"],
        "vt": actual["vt"],
        "expected_config_hash": integration_config_hash,
    }


def exact_wkb_correspondence(
    c0_rows: list[dict[str, Any]], vt_rows: list[dict[str, Any]]
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, int]]:
    """Return one-to-one exact WKB matches, excluding duplicated geometries on either side."""
    c0_groups: dict[bytes, list[str]] = {}
    for row in c0_rows:
        geom = row.get("geometry")
        if geom is not None:
            c0_groups.setdefault(bytes(geom), []).append(str(row["bldg_id"]))
    vt_groups: dict[bytes, list[dict[str, Any]]] = {}
    for row in vt_rows:
        geom = row.get("geometry")
        if geom is not None:
            vt_groups.setdefault(bytes(geom), []).append(row)
    matches: list[tuple[str, dict[str, Any]]] = []
    ambiguous = 0
    for geom, c0_ids in c0_groups.items():
        vt_matches = vt_groups.get(geom, [])
        if not vt_matches:
            continue
        if len(c0_ids) != 1 or len(vt_matches) != 1:
            ambiguous += len(c0_ids)
            continue
        matches.append((c0_ids[0], vt_matches[0]))
    stats = {
        "c0_rows": len(c0_rows),
        "vt_rows": len(vt_rows),
        "exact_unique_matches": len(matches),
        "ambiguous_c0_records": ambiguous,
        "unmatched_c0_records": len(c0_rows) - len(matches) - ambiguous,
        "duplicate_c0_geometry_groups": sum(len(ids) > 1 for ids in c0_groups.values()),
        "duplicate_vt_geometry_groups": sum(len(rows) > 1 for rows in vt_groups.values()),
    }
    return matches, stats


def _sql_match_summary(
    con: duckdb.DuckDBPyConnection, c0_path: Path, vt_path: Path
) -> dict[str, int]:
    con.execute("SET enable_geoparquet_conversion=false")
    c0 = str(c0_path.resolve()).replace("'", "''")
    vt = str(vt_path.resolve()).replace("'", "''")
    result = con.execute(
        f"""
        WITH c AS (
          SELECT sha256(geometry) AS h, any_value(geometry) AS geom, count(*) AS n
          FROM read_parquet('{c0}') WHERE geometry IS NOT NULL GROUP BY h
        ), v AS (
          SELECT sha256(geometry) AS h, any_value(geometry) AS geom, count(*) AS n
          FROM read_parquet('{vt}') WHERE geometry IS NOT NULL GROUP BY h
        ), shared AS (
          SELECT c.geom, c.n AS c_n, v.n AS v_n FROM c JOIN v USING (h)
          WHERE c.geom=v.geom
        )
        SELECT
          (SELECT count(*) FROM read_parquet('{c0}')) AS c0_rows,
          (SELECT count(*) FROM read_parquet('{vt}')) AS vt_rows,
          coalesce(sum(CASE WHEN c_n=1 AND v_n=1 THEN 1 ELSE 0 END),0) AS exact_unique_matches,
          coalesce(sum(CASE WHEN c_n>1 OR v_n>1 THEN c_n ELSE 0 END),0) AS ambiguous_c0_records,
          (SELECT count(*) FROM (SELECT sha256(geometry) h FROM read_parquet('{c0}') WHERE geometry IS NOT NULL GROUP BY h HAVING count(*)>1)) AS duplicate_c0_geometry_groups,
          (SELECT count(*) FROM (SELECT sha256(geometry) h FROM read_parquet('{vt}') WHERE geometry IS NOT NULL GROUP BY h HAVING count(*)>1)) AS duplicate_vt_geometry_groups
        FROM shared
        """
    ).fetchone()
    stats = dict(
        zip(
            (
                "c0_rows",
                "vt_rows",
                "exact_unique_matches",
                "ambiguous_c0_records",
                "duplicate_c0_geometry_groups",
                "duplicate_vt_geometry_groups",
            ),
            map(int, result),
            strict=True,
        )
    )
    stats["unmatched_c0_records"] = (
        stats["c0_rows"] - stats["exact_unique_matches"] - stats["ambiguous_c0_records"]
    )
    return stats


def _comparison_metrics(
    con: duckdb.DuckDBPyConnection, c0_path: Path, c1_path: Path, vt_path: Path
) -> tuple[int, int, int, float | None, list[tuple[str, int, int, int, float | None]]]:
    c0 = str(c0_path.resolve()).replace("'", "''")
    c1 = str(c1_path.resolve()).replace("'", "''")
    vt = str(vt_path.resolve()).replace("'", "''")
    query = f"""
      WITH c0 AS (
        SELECT bldg_id, ward_id, geometry, sha256(geometry) h
        FROM read_parquet('{c0}') WHERE geometry IS NOT NULL
      ), c1 AS (
        SELECT bldg_id, beta_horizon FROM read_parquet('{c1}')
      ), vt_group AS (
        SELECT sha256(geometry) h, any_value(geometry) geometry,
          count(*) n, any_value(risk_insar) risk_insar
        FROM read_parquet('{vt}') WHERE geometry IS NOT NULL GROUP BY h
      ), c0_group AS (
        SELECT h, any_value(geometry) geometry, any_value(bldg_id) bldg_id,
          any_value(ward_id) ward_id, count(*) n
        FROM c0 GROUP BY h
      ), matched AS (
        SELECT cg.bldg_id, cg.ward_id, c1.beta_horizon, vg.risk_insar
        FROM c0_group cg JOIN vt_group vg ON cg.h=vg.h AND cg.geometry=vg.geometry
        JOIN c1 USING (bldg_id)
        WHERE cg.n=1 AND vg.n=1
      ), paired AS (
        SELECT * FROM matched WHERE beta_horizon IS NOT NULL AND risk_insar IS NOT NULL
      ), ranked AS (
        SELECT *,
          rank() OVER (ORDER BY beta_horizon) + (count(*) OVER (PARTITION BY beta_horizon)-1)/2.0 AS beta_rank,
          rank() OVER (ORDER BY risk_insar) + (count(*) OVER (PARTITION BY risk_insar)-1)/2.0 AS risk_rank
        FROM paired
      ), matched_ward AS (
        SELECT ward_id, count(*) matched_buildings,
          count(risk_insar) valid_risk_count, avg(risk_insar) mean_risk_insar
        FROM matched WHERE ward_id IS NOT NULL GROUP BY ward_id
      ), ward_total AS (
        SELECT ward_id, count(*) total_c0_buildings
        FROM c0 WHERE ward_id IS NOT NULL GROUP BY ward_id
      ), ward_agg AS (
        SELECT total.ward_id, total.total_c0_buildings,
          coalesce(matched.matched_buildings, 0) matched_buildings,
          coalesce(matched.valid_risk_count, 0) valid_risk_count,
          matched.mean_risk_insar
        FROM ward_total total LEFT JOIN matched_ward matched USING (ward_id)
      )
      SELECT (SELECT count(*) FROM matched),
        (SELECT count(risk_insar) FROM matched),
        (SELECT count(*) FROM paired),
        (SELECT corr(beta_rank, risk_rank) FROM ranked),
        (SELECT to_json(list(struct_pack(ward_id:=ward_id, total_c0_buildings:=total_c0_buildings,
          matched_buildings:=matched_buildings,
          valid_risk_count:=valid_risk_count, mean_risk_insar:=mean_risk_insar))) FROM ward_agg)
    """
    matched_count, valid_risk_count, count, rho, wards = con.execute(query).fetchone()
    ward_rows = []
    for item in json.loads(wards or "[]"):
        ward_rows.append(
            (
                str(item["ward_id"]),
                int(item["total_c0_buildings"]),
                int(item["matched_buildings"]),
                int(item["valid_risk_count"]),
                float(item["mean_risk_insar"]) if item["mean_risk_insar"] is not None else None,
            )
        )
    return (
        int(matched_count),
        int(valid_risk_count),
        int(count),
        float(rho) if rho is not None and math.isfinite(float(rho)) else None,
        ward_rows,
    )


def _read_ward_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {"ward_id", "rank", "score"}.issubset(
                reader.fieldnames
            ):
                raise D5Error("D3 ward index must contain ward_id, rank and score columns")
            rows = list(reader)
    except OSError as exc:
        raise D5Error(f"Cannot read D3 ward index: {path}") from exc
    ids = [row["ward_id"].strip() for row in rows]
    if len(rows) != 250 or any(not value for value in ids) or len(set(ids)) != len(ids):
        raise D5Error("D3 ward index must contain 250 unique non-empty ward IDs")
    return rows


def spearman_correlation(left: list[float], right: list[float]) -> float | None:
    """Return Spearman rho for paired finite values, or None when undefined."""
    from scipy.stats import spearmanr

    if len(left) != len(right) or len(left) < 2:
        return None
    if any(not math.isfinite(value) for value in (*left, *right)):
        raise D5Error("Spearman inputs must be finite paired values")
    if len(set(left)) == 1 or len(set(right)) == 1:
        return None
    result = spearmanr(left, right).statistic
    return float(result) if result is not None and math.isfinite(float(result)) else None


def build_c3_fragment(n_buildings: int = 0, rho: float | None = None) -> dict[str, Any]:
    if n_buildings < 0 or (rho is not None and not -1 <= rho <= 1):
        raise D5Error("C3 comparison count or correlation is invalid")
    if rho is None and n_buildings == 0:
        note = (
            "Consistency with published categories, not independent ground truth. Unavailable: "
            "no complete paired non-null comparison values were available; no correlation or "
            "confusion matrix was computed. Strict WKB equality is a conservative matching "
            "rule, not proof of source identity; overlap and proximity methods were not adopted "
            "without an agreed rule."
        )
    elif rho is None:
        note = (
            "Consistency with published categories, not independent ground truth. Spearman is "
            "unavailable because the paired values have insufficient variation; no confusion "
            "matrix was computed because no class crosswalk was supplied."
        )
    else:
        note = (
            "Consistency with published categories, not independent ground truth. Spearman is an "
            "ordinal association only; no class crosswalk was supplied, so confusion matrix is unavailable."
        )
    fragment = {
        "n_buildings": int(n_buildings),
        "spearman_rho": rho,
        "labels": LABELS,
        "confusion_matrix": [],
        "note": note,
    }
    if set(fragment) != C3_KEYS:
        raise AssertionError("Internal C3 shape error")
    return fragment


def run(args: argparse.Namespace) -> dict[str, Any]:
    paths = {
        "c0": args.c0,
        "c1": args.c1,
        "published_risk": args.published_risk,
        "wards": args.wards,
        "pack_manifest": args.pack_manifest,
        "d3_ward_index": args.d3_ward_index,
        "d3_qa": args.d3_qa,
        "d4_sensitivity": args.d4_sensitivity,
        "config": args.config,
        "integration_manifest": args.integration_manifest,
    }
    for label, path in paths.items():
        if not path.is_file():
            raise D5Error(f"Required {label} input is not a file: {path}")
    output_dir = args.output_dir
    outputs = [
        output_dir / name
        for name in ("vt_consistency.json", "ward_vt_consistency.csv", "d5_qa.json")
    ]
    if not args.overwrite and any(path.exists() for path in outputs):
        raise D5Error("A D5 output already exists; use --overwrite to replace D5 outputs")

    hashes = _verify_input_provenance(
        args.c0, args.c1, args.published_risk, args.pack_manifest, args.integration_manifest
    )
    c0_info = _check_geo_metadata(args.c0, require_risk_fields=False)
    vt_info = _check_geo_metadata(args.published_risk, require_risk_fields=True)
    risk_schema = pq.ParquetFile(args.published_risk).schema_arrow
    if any(risk_schema.field(name).type != pa.int8() for name in RISK_COLUMNS):
        raise D5Error("Published risk fields must use the C0 int8 category type")
    c1_schema = pq.ParquetFile(args.c1).schema_arrow
    required_c1 = {
        "bldg_id",
        "ward_id",
        "cell_id",
        "n_points",
        "vlm_mm_yr",
        "vlm_iqr_mm_yr",
        "n_pairs",
        "beta_rate_per_yr",
        "beta_horizon",
        "beta_ratio_horizon",
        "beta_class",
        "sparse",
        "vt_risk_insar",
        "engine_version",
        "params_hash",
    }
    if set(c1_schema.names) != required_c1:
        raise D5Error("Selected C1 artifact does not have the exact frozen 15-column schema")
    if c1_schema.field("bldg_id").type != pa.string():
        raise D5Error("C1 bldg_id must be a string")
    if c1_schema.field("beta_horizon").type not in {pa.float32(), pa.float64()}:
        raise D5Error("C1 beta_horizon must be floating point")
    d3_qa = _read_json(args.d3_qa)
    d3_inputs = d3_qa.get("inputs", {})
    d3_c1_hashes = (
        [
            value.get("sha256")
            for name, value in d3_inputs.items()
            if isinstance(name, str) and Path(name).name == args.c1.name and isinstance(value, dict)
        ]
        if isinstance(d3_inputs, dict)
        else []
    )
    if not d3_c1_hashes or any(value != hashes["c1"] for value in d3_c1_hashes):
        raise D5Error("D3 QA does not prove it used the selected C1 artifact")
    try:
        config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise D5Error(f"Cannot read C6 configuration: {args.config}") from exc
    if not isinstance(config, dict) or config.get("contract") != "C6@1.0":
        raise D5Error("Configuration must declare C6@1.0")
    try:
        config_schema = json.loads(
            Path("contracts/schemas/config.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.validate(config, config_schema)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise D5Error("Selected C6 configuration does not satisfy its frozen schema") from exc
    if config.get("city") != "delhi" or hashes["expected_config_hash"] != _sha256(args.config):
        raise D5Error("Selected C6 configuration does not match the staged C1 provenance")
    _read_json(args.integration_manifest)
    ward_rows = _read_ward_rows(args.d3_ward_index)
    with args.d4_sensitivity.open(encoding="utf-8-sig", newline="") as stream:
        sensitivity_rows = list(csv.DictReader(stream))
    if any(not row.get("ward_id") for row in sensitivity_rows):
        raise D5Error("D4 sensitivity rows must contain ward_id")
    sensitivity_ids = [row["ward_id"].strip() for row in sensitivity_rows]
    if len(sensitivity_ids) != len(set(sensitivity_ids)):
        raise D5Error("D4 sensitivity ward IDs must be unique")
    ward_ids = {row["ward_id"].strip() for row in ward_rows}
    if set(sensitivity_ids) != ward_ids:
        raise D5Error("D4 sensitivity ward IDs do not match D3 ward IDs")

    import duckdb

    started = datetime.now(UTC)
    con = duckdb.connect(":memory:")
    try:
        match_stats = _sql_match_summary(con, args.c0, args.published_risk)
        c0 = str(args.c0.resolve()).replace("'", "''")
        vt = str(args.published_risk.resolve()).replace("'", "''")
        risk_counts = con.execute(
            f"SELECT count(*) FILTER (WHERE geometry IS NOT NULL), "
            f"count(*) FILTER (WHERE risk_insar IS NOT NULL), "
            f"count(*) FILTER (WHERE risk_10yrs IS NOT NULL), "
            f"count(*) FILTER (WHERE risk_30yrs IS NOT NULL), "
            f"count(*) FILTER (WHERE risk_50yrs IS NOT NULL) FROM read_parquet('{vt}')"
        ).fetchone()
        invalid_risk_count = con.execute(
            f"SELECT count(*) FROM read_parquet('{vt}') WHERE "
            + " OR ".join(
                f"({column} IS NOT NULL AND ({column}<0 OR {column}>4))" for column in RISK_COLUMNS
            )
        ).fetchone()[0]
        if invalid_risk_count:
            raise D5Error(
                "Published risk categories contain values outside the documented 0-4 range"
            )
        c0_ward_count = con.execute(
            f"SELECT count(*) FILTER (WHERE ward_id IS NOT NULL) FROM read_parquet('{c0}')"
        ).fetchone()[0]
        matched_c1_count, matched_valid_risk_count, paired_count, rho, ward_aggregates = (
            _comparison_metrics(con, args.c0, args.c1, args.published_risk)
        )
    finally:
        con.close()

    exact = match_stats["exact_unique_matches"]
    fragment = build_c3_fragment(paired_count, rho)
    generated = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    qa = {
        "report_type": "D5 published-risk consistency QA",
        "generated_utc": generated,
        "status": "comparison_unavailable_no_unique_exact_geometry_matches"
        if exact == 0
        else "strict_matches_compared_with_confusion_matrix_unavailable_no_class_crosswalk",
        "inputs": {
            name: {"path": str(path), "sha256": hashes[hash_key]}
            for name, path, hash_key in (
                ("c0", args.c0, "c0"),
                ("c1", args.c1, "c1"),
                ("published_risk", args.published_risk, "vt"),
            )
        },
        "context_inputs": {
            name: {"path": str(path), "sha256": _sha256(path)}
            for name, path in (
                ("wards", args.wards),
                ("pack_manifest", args.pack_manifest),
                ("d3_ward_index", args.d3_ward_index),
                ("d3_qa", args.d3_qa),
                ("d4_sensitivity", args.d4_sensitivity),
                ("config", args.config),
                ("integration_manifest", args.integration_manifest),
            )
        },
        "geometry": {
            "method": "strict byte-identical WKB equality after verifying EPSG:4326 GeoParquet metadata",
            "candidate_methods_not_used": [
                "centroid containment",
                "polygon overlap",
                "nearest feature",
            ],
            "reason_not_used": "No source identity or approved spatial threshold/tie rule establishes those correspondences.",
            "c0": c0_info,
            "published_risk": vt_info,
            "counts": match_stats,
            "match_coverage_all_c0_pct": (
                100 * exact / match_stats["c0_rows"] if match_stats["c0_rows"] else None
            ),
        },
        "published_risk_nonnull_counts": dict(
            zip(RISK_COLUMNS, map(int, risk_counts[1:]), strict=True)
        ),
        "published_geometry_nonnull_count": int(risk_counts[0]),
        "published_geometry_topology": {
            "status": "reused_prior_verified_audit_not_rescanned",
            "audit_source": "data/AUDIT.md",
            "previously_reported_valid_nonempty_count": 3517198,
        },
        "invalid_published_risk_category_rows": int(invalid_risk_count),
        "c0_ward_assigned_buildings": int(c0_ward_count),
        "matched_c0_c1_vt_buildings": matched_c1_count,
        "matched_records_with_valid_risk_insar": matched_valid_risk_count,
        "paired_beta_and_risk_insar_count": paired_count,
        "ward_comparison": {},
        "building_comparison": {
            "paired_nonnull_count": paired_count,
            "spearman_rho": rho,
            "confusion_matrix": [],
            "reason": (
                "No paired non-null beta_horizon/risk_insar values; beta classes and published "
                "0-4 categories also lack an approved crosswalk."
                if paired_count == 0
                else "Spearman compares paired beta_horizon with published risk_insar categories; "
                "no class crosswalk was supplied for a confusion matrix."
            ),
        },
        "limitations": [
            "Published risk categories are a consistency reference, not independent ground truth or collapse probabilities.",
            "VT source index is non-unique; bldg_id is null in the published-risk layer.",
            "Strict WKB equality found no correspondences and can miss topologically identical polygons with different encodings.",
            "No centroid, overlap, or nearest-neighbor threshold was invented.",
            "C1 vt_risk_insar remains null and was not modified.",
            "No correlations or confusion matrix were computed from unmatched records.",
            "C0 ward coverage limitations and D2 proxy groundwater limitations remain as documented upstream.",
        ],
        "runtime_seconds": round((datetime.now(UTC) - started).total_seconds(), 3),
        "outputs": {},
    }
    qa["started_utc"] = started.isoformat(timespec="seconds").replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(outputs[0], fragment, args.overwrite)
    ward_by_id = {row[0]: row[1:] for row in ward_aggregates}
    matched_assigned = sum(value[1] for value in ward_by_id.values())
    qa["geometry"]["matched_assigned_ward_buildings"] = matched_assigned
    qa["geometry"]["match_coverage_assigned_wards_pct"] = (
        100 * matched_assigned / c0_ward_count if c0_ward_count else None
    )
    common_scores: list[float] = []
    common_risks: list[float] = []
    for row in ward_rows:
        aggregate = ward_by_id.get(row["ward_id"], (0, 0, 0, None))
        try:
            score = float(row["score"])
            mean_risk = aggregate[3]
            if mean_risk is not None and row["rank"].strip() and math.isfinite(score):
                common_scores.append(score)
                common_risks.append(mean_risk)
        except (TypeError, ValueError):
            continue
    ward_rho = spearman_correlation(common_scores, common_risks)
    qa["ward_comparison"] = {
        "ward_count": len(ward_rows),
        "common_ranked_wards": len(common_scores),
        "spearman_score_vs_mean_risk_insar": ward_rho,
        "reason": (
            "No common ranked wards with matched non-null published risk; ward correlation unavailable."
            if ward_rho is None
            else "Association of D3 score and mean published risk_insar among matched buildings; not independent validation."
        ),
    }
    _write_ward_csv(outputs[1], ward_rows, args.overwrite, ward_by_id)
    _write_json(outputs[2], qa, args.overwrite)
    qa["outputs"] = {
        path.name: {"path": str(path), "sha256": _sha256(path)} for path in outputs[:2]
    }
    _write_json(outputs[2], qa, True)
    return qa


def _write_json(path: Path, value: dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D5Error(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _write_ward_csv(
    path: Path,
    wards: list[dict[str, str]],
    overwrite: bool,
    aggregates: dict[str, tuple[int, int, int, float | None]],
) -> None:
    if path.exists() and not overwrite:
        raise D5Error(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ward_id",
        "rank",
        "total_c0_buildings",
        "matched_buildings",
        "match_coverage_pct",
        "valid_risk_count",
        "mean_risk_insar",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in sorted(wards, key=lambda item: item["ward_id"]):
            total, matched, valid, mean_risk = aggregates.get(row["ward_id"], (0, 0, 0, None))
            writer.writerow(
                {
                    "ward_id": row["ward_id"],
                    "rank": row["rank"],
                    "total_c0_buildings": total,
                    "matched_buildings": matched,
                    "match_coverage_pct": "" if total == 0 else 100 * matched / total,
                    "valid_risk_count": valid,
                    "mean_risk_insar": "" if mean_risk is None else mean_risk,
                }
            )
    os.replace(temporary, path)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run conservative D5 published-risk consistency checks."
    )
    sub = result.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Validate selected real inputs and write D5 outputs")
    for name in (
        "c0",
        "c1",
        "published-risk",
        "wards",
        "pack-manifest",
        "d3-ward-index",
        "d3-qa",
        "d4-sensitivity",
        "config",
        "integration-manifest",
        "output-dir",
    ):
        run_parser.add_argument(f"--{name}", type=Path, required=True)
    run_parser.add_argument("--overwrite", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
    except (D5Error, duckdb.Error, OSError, ValueError) as exc:
        print(f"D5 failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": report["status"], "geometry_counts": report["geometry"]["counts"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
