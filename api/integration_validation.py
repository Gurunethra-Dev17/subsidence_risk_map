"""Standalone, aggregate-only validation for C0/C1 building artifacts.

This validator is intentionally not called by the request handlers. It scans
the supplied artifacts with DuckDB aggregation and returns diagnostics that
contain no source rows, identifiers, SQL, or paths.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS = _ROOT / "contracts" / "schemas"
_C0_COLUMNS = {
    "bldg_id": "string",
    "footprint_m2": "number",
    "source": "string",
    "ward_id": "string",
    "cell_id": "string",
    "geometry": "geometry",
}
_C1_TYPES = {
    "bldg_id": pa.string(),
    "ward_id": pa.string(),
    "cell_id": pa.string(),
    "n_points": pa.int32(),
    "vlm_mm_yr": pa.float32(),
    "vlm_iqr_mm_yr": pa.float32(),
    "n_pairs": pa.int32(),
    "beta_rate_per_yr": pa.float32(),
    "beta_horizon": pa.float32(),
    "beta_ratio_horizon": pa.string(),
    "beta_class": pa.string(),
    "sparse": pa.bool_(),
    "vt_risk_insar": pa.int8(),
    "engine_version": pa.string(),
    "params_hash": pa.string(),
}
# Frozen C1 declares these columns but does not set additionalProperties=false;
# artifacts may carry extensions as long as every declared column is valid.
_C1_NULLABLE = {
    "ward_id", "cell_id", "vlm_mm_yr", "vlm_iqr_mm_yr", "beta_rate_per_yr",
    "beta_horizon", "beta_ratio_horizon", "beta_class", "vt_risk_insar",
}


@dataclass
class ValidationReport:
    """Safe summary of artifact checks; never contains identifiers or paths."""

    ok: bool
    counts: dict[str, int] = field(default_factory=dict)
    issues: dict[str, int] = field(default_factory=dict)
    scope: str = "full supplied C0 and C1 artifacts"
    limitations: list[str] = field(default_factory=list)
    checks_not_performed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-safe report with aggregate diagnostics only."""
        return asdict(self)


def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _arrow_metadata(schema: pa.Schema) -> dict[str, str]:
    raw = schema.metadata or {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        try:
            result[key.decode("utf-8")] = value.decode("utf-8")
        except (AttributeError, UnicodeDecodeError):
            continue
    return result


def _metadata_value(metadata: dict[str, str], name: str) -> str | None:
    if name in metadata:
        return metadata[name]
    # Accept the common Arrow namespaced representation without interpreting
    # unrelated metadata values as artifact declarations.
    return metadata.get(f"org.subsidence.{name}")


def _parse_positive_integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 and str(parsed) == value.strip() else None


def canonical_params_hash(params: Any) -> str:
    """Hash C6 params using ``engine/export.py::params_hash`` semantics."""
    def validate_json_value(value: Any) -> None:
        if value is None or type(value) in (str, bool, int):
            return
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("params contains a non-finite number")
            return
        if type(value) is list:
            for item in value:
                validate_json_value(item)
            return
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("params object keys must be strings")
            for item in value.values():
                validate_json_value(item)
            return
        raise ValueError("params contains a non-JSON-compatible value")

    if type(params) is not dict:
        raise ValueError("params must be a JSON object")
    validate_json_value(params)
    canonical = json.dumps(
        params,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_epsg_4326(crs: Any) -> bool:
    if not isinstance(crs, dict):
        return False
    authority_id = crs.get("id")
    if isinstance(authority_id, dict):
        authority = str(authority_id.get("authority", "")).upper()
        code = str(authority_id.get("code", ""))
        if authority == "EPSG" and code == "4326":
            return True
    name = crs.get("name")
    return isinstance(name, str) and name.upper() in {"EPSG:4326", "WGS 84 / EPSG:4326"}


def _check_geoparquet_metadata(schema: pa.Schema) -> tuple[bool, bool]:
    """Return (has_geo_metadata, declares_epsg4326) using GeoParquet metadata."""
    raw = (schema.metadata or {}).get(b"geo")
    if raw is None:
        return False, False
    try:
        geo = json.loads(raw.decode("utf-8"))
        columns = geo.get("columns", {})
        primary_column = geo.get("primary_column")
        if primary_column != "geometry":
            return True, False
        geom = columns.get(primary_column)
        if geom is None and len(columns) == 1:
            geom = next(iter(columns.values()))
        if not isinstance(geom, dict):
            return True, False
        encoding = geom.get("encoding")
        # GeoParquet 1.1 defaults to WKB if encoding is absent.
        if encoding not in (None, "WKB"):
            return True, False
        crs = geom.get("crs")
        return True, _is_epsg_4326(crs)
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError):
        return True, False


def _arrow_matches(actual: pa.DataType, expected: pa.DataType) -> bool:
    return actual.equals(expected)


def validate_building_artifacts(
    c0_buildings_path: Path,
    c1_metrics_path: Path,
    *,
    c0_manifest_path: Path | None = None,
    c6_config_path: Path | None = None,
) -> ValidationReport:
    """Validate complete supplied C0/C1 artifacts with bounded-memory queries.

    A complete scan is performed over the supplied files; this function does
    not discover or select production files on its own. Callers should use it
    only in an explicitly authorized integration-validation workflow.
    """
    issues: dict[str, int] = {}
    counts: dict[str, int] = {}
    checks_not_performed: list[str] = []
    limitations: list[str] = [
        "No unrelated pack files are hashed or inspected.",
        "No external source provenance or source licensing is verified.",
        "C1 extensions are allowed; the frozen schema does not require exactly 15 physical columns.",
    ]

    def issue(code: str, count: int = 1) -> None:
        if count:
            issues[code] = issues.get(code, 0) + int(count)

    c0_path = Path(c0_buildings_path)
    c1_path = Path(c1_metrics_path)
    try:
        c0_file = pq.ParquetFile(c0_path)
        c1_file = pq.ParquetFile(c1_path)
        c0_schema = c0_file.schema_arrow
        c1_schema = c1_file.schema_arrow
    except Exception:  # noqa: BLE001 - diagnostics intentionally hide parser details
        issue("artifact_unreadable")
        return ValidationReport(False, counts, issues, limitations=limitations)

    c0_names = {field.name.casefold(): field for field in c0_schema}
    c1_names = {field.name.casefold(): field for field in c1_schema}
    for name in _C0_COLUMNS:
        if name not in c0_names:
            issue("c0_missing_column")
    for name in _C1_TYPES:
        if name not in c1_names:
            issue("c1_missing_column")

    for name, kind in _C0_COLUMNS.items():
        field = c0_names.get(name)
        if field is None:
            continue
        typ = field.type
        valid = (
            pa.types.is_string(typ) if kind == "string"
            else pa.types.is_floating(typ) if kind == "number"
            else pa.types.is_binary(typ) or pa.types.is_large_binary(typ)
                or str(typ).upper().startswith("GEOMETRY") if kind == "geometry"
            else False
        )
        if not valid:
            issue("c0_type_violation")

    for name, expected in _C1_TYPES.items():
        field = c1_names.get(name)
        if field is None:
            continue
        if not _arrow_matches(field.type, expected):
            issue("c1_type_violation")
        if name not in _C1_NULLABLE and field.nullable:
            # Parquet's nullable bit is advisory; data null counts are checked below.
            pass

    has_geo, epsg4326 = _check_geoparquet_metadata(c0_schema)
    if not has_geo:
        issue("c0_geoparquet_metadata_missing")
    elif not epsg4326:
        issue("c0_crs_violation")

    c1_meta = _arrow_metadata(c1_schema)
    expected_meta = {
        "contract": "C1@1.0",
    }
    for key, expected in expected_meta.items():
        if _metadata_value(c1_meta, key) != expected:
            issue("c1_metadata_violation")
    horizon = _parse_positive_integer(_metadata_value(c1_meta, "horizon_years"))
    if horizon is None:
        issue("c1_metadata_violation")
    seed_text = _metadata_value(c1_meta, "seed")
    try:
        int(seed_text)  # zero and negative seeds are valid integer seeds
        seed_valid = seed_text is not None and str(int(seed_text)) == seed_text.strip()
    except (TypeError, ValueError):
        seed_valid = False
    if not seed_valid or not _metadata_value(c1_meta, "engine_version") or not _metadata_value(c1_meta, "params_hash"):
        issue("c1_metadata_violation")

    if c0_manifest_path is not None:
        manifest: dict[str, Any] | None = None
        manifest_loaded = False
        try:
            manifest = json.loads(Path(c0_manifest_path).read_text(encoding="utf-8"))
            manifest_loaded = True
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            issue("c0_manifest_invalid")
        manifest_structure_valid = isinstance(manifest, dict)
        if manifest_structure_valid:
            files = manifest.get("files")
            manifest_structure_valid = isinstance(files, list)
            if manifest_structure_valid:
                for entry in files:
                    if not isinstance(entry, dict):
                        manifest_structure_valid = False
                        break
                    if not {"name", "sha256", "rows"}.issubset(entry):
                        manifest_structure_valid = False
                        break
                    if (
                        not isinstance(entry["name"], str)
                        or not isinstance(entry["sha256"], str)
                        or not entry["sha256"].strip()
                        or not isinstance(entry["rows"], int)
                        or isinstance(entry["rows"], bool)
                    ):
                        manifest_structure_valid = False
                        break
        if manifest_loaded and not manifest_structure_valid:
            issue("c0_manifest_structure_violation")
        if manifest_structure_valid:
            try:
                jsonschema.Draft202012Validator(_schema(_SCHEMAS / "pack_manifest.schema.json")).validate(manifest)
            except jsonschema.ValidationError:
                issue("c0_manifest_violation")
            else:
                if manifest["contract"] != "C0@1.0" or manifest["crs_storage"] != "EPSG:4326":
                    issue("c0_manifest_violation")
                entries = [entry for entry in manifest["files"] if entry["name"] == "buildings.parquet"]
                if len(entries) != 1:
                    issue("c0_manifest_inventory_violation")
                else:
                    entry = entries[0]
                    if entry["rows"] != c0_file.metadata.num_rows:
                        issue("c0_manifest_row_count_mismatch")
                    counts["c0_manifest_buildings_row_count"] = c0_file.metadata.num_rows
                    try:
                        digest = hashlib.sha256()
                        with c0_path.open("rb") as artifact:
                            for block in iter(lambda: artifact.read(1024 * 1024), b""):
                                digest.update(block)
                    except OSError:
                        issue("c0_manifest_hash_unavailable")
                    else:
                        if digest.hexdigest().casefold() != entry["sha256"].casefold():
                            issue("c0_manifest_hash_mismatch")

    c6_config: dict[str, Any] | None = None
    c6_valid = False
    if c6_config_path is not None:
        try:
            c6_config = yaml.safe_load(Path(c6_config_path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - diagnostics intentionally hide parser details
            issue("c6_config_violation")
        if not isinstance(c6_config, dict):
            issue("c6_config_violation")
            issue("c6_params_invalid")
        else:
            schema_valid = True
            try:
                jsonschema.Draft202012Validator(_schema(_SCHEMAS / "config.schema.json")).validate(c6_config)
            except Exception:  # noqa: BLE001 - diagnostics intentionally hide schema details
                issue("c6_config_violation")
                schema_valid = False
            if c6_config.get("contract") != "C6@1.0":
                issue("c6_config_violation")
                schema_valid = False
            if schema_valid:
                c6_valid = True
            if not isinstance(c6_config.get("params"), dict):
                issue("c6_params_invalid")
    if c0_manifest_path is None:
        limitations.append("C0 manifest was not supplied; pack declarations and inventory row count were not checked.")

    expected_params_hash: str | None = None
    if c6_config_path is None:
        checks_not_performed.append("c6_params_hash_recomputation")
    elif c6_valid:
        try:
            expected_params_hash = canonical_params_hash(c6_config.get("params"))
        except (TypeError, ValueError, OverflowError):
            issue("c6_params_invalid")
            checks_not_performed.append("c6_params_hash_comparison")
    else:
        checks_not_performed.append("c6_params_hash_comparison")
    if expected_params_hash is not None:
        file_params_hash = _metadata_value(c1_meta, "params_hash")
        if file_params_hash != expected_params_hash:
            issue("c1_c6_file_params_hash_mismatch")

    # DuckDB performs full-file aggregates without materializing source records.
    try:
        import duckdb

        with duckdb.connect(database=":memory:") as db:
            db.execute("LOAD spatial")
            db.execute("CREATE TEMP TABLE c0 AS SELECT * FROM read_parquet(?)", [str(c0_path.resolve())])
            db.execute("CREATE TEMP TABLE c1 AS SELECT * FROM read_parquet(?)", [str(c1_path.resolve())])
            c0_count = int(db.execute("SELECT count(*) FROM c0").fetchone()[0])
            c1_count = int(db.execute("SELECT count(*) FROM c1").fetchone()[0])
            counts.update({"c0_rows": c0_count, "c1_rows": c1_count})

            c0_ids = {name for name in _C0_COLUMNS if name in c0_names}
            c1_ids = set(_C1_TYPES).intersection(c1_names)
            if "bldg_id" in c0_ids:
                null_empty = db.execute("SELECT count(*) FROM c0 WHERE bldg_id IS NULL OR trim(CAST(bldg_id AS VARCHAR)) = ''").fetchone()[0]
                duplicates = db.execute("SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) n FROM c0 WHERE bldg_id IS NOT NULL AND trim(CAST(bldg_id AS VARCHAR)) <> '' GROUP BY bldg_id HAVING count(*) > 1)").fetchone()[0]
                counts["c0_null_or_empty_ids"] = int(null_empty)
                counts["c0_duplicate_ids"] = int(duplicates)
                issue("c0_invalid_id", int(null_empty))
                issue("c0_duplicate_id", int(duplicates))
            if "bldg_id" in c1_ids:
                null_empty = db.execute("SELECT count(*) FROM c1 WHERE bldg_id IS NULL OR trim(CAST(bldg_id AS VARCHAR)) = ''").fetchone()[0]
                duplicates = db.execute("SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) n FROM c1 WHERE bldg_id IS NOT NULL AND trim(CAST(bldg_id AS VARCHAR)) <> '' GROUP BY bldg_id HAVING count(*) > 1)").fetchone()[0]
                counts["c1_null_or_empty_ids"] = int(null_empty)
                counts["c1_duplicate_ids"] = int(duplicates)
                issue("c1_invalid_id", int(null_empty))
                issue("c1_duplicate_id", int(duplicates))

                if "bldg_id" in c0_ids:
                    missing = int(db.execute("SELECT count(*) FROM c0 LEFT JOIN c1 USING (bldg_id) WHERE c0.bldg_id IS NOT NULL AND c1.bldg_id IS NULL").fetchone()[0])
                    orphan = int(db.execute("SELECT count(*) FROM c1 LEFT JOIN c0 USING (bldg_id) WHERE c1.bldg_id IS NOT NULL AND c0.bldg_id IS NULL").fetchone()[0])
                    counts["missing_c1_matches"] = missing
                    counts["orphan_c1_ids"] = orphan
                    issue("missing_c1_match", missing)
                    issue("orphan_c1_id", orphan)

            if (
                {"footprint_m2", "source"}.issubset(c0_names)
                and pa.types.is_floating(c0_names["footprint_m2"].type)
                and pa.types.is_string(c0_names["source"].type)
            ):
                invalid = int(db.execute("SELECT count(*) FROM c0 WHERE footprint_m2 IS NULL OR footprint_m2 <= 0 OR source IS NULL OR source NOT IN ('osm','google','microsoft','esri','vt')").fetchone()[0])
                counts["c0_invalid_footprint_or_source"] = invalid
                issue("c0_value_violation", invalid)
            for name in ("ward_id", "cell_id"):
                if name in c0_names:
                    bad = int(db.execute(f"SELECT count(*) FROM c0 WHERE {name} IS NOT NULL AND typeof({name}) <> 'VARCHAR'").fetchone()[0])
                    issue("c0_type_violation", bad)
            if "geometry" in c0_names:
                try:
                    geometry_counts = db.execute("""
                        SELECT count(*) FILTER (WHERE geometry IS NULL),
                               count(*) FILTER (WHERE geometry IS NOT NULL AND NOT ST_IsValid(geometry)),
                               count(*) FILTER (WHERE geometry IS NOT NULL AND ST_GeometryType(geometry) NOT IN ('POLYGON','MULTIPOLYGON'))
                        FROM c0
                    """).fetchone()
                    counts["c0_null_geometry"] = int(geometry_counts[0])
                    counts["c0_invalid_geometry"] = int(geometry_counts[1])
                    counts["c0_non_polygon_geometry"] = int(geometry_counts[2])
                    issue("c0_geometry_violation", sum(map(int, geometry_counts)))
                except Exception:  # noqa: BLE001 - geometry errors can contain private rows
                    issue("c0_geometry_validation_unavailable")

            for name in ("bldg_id", "engine_version", "params_hash"):
                if name in c1_names:
                    bad = int(db.execute(f"SELECT count(*) FROM c1 WHERE {name} IS NULL OR trim(CAST({name} AS VARCHAR)) = ''").fetchone()[0])
                    counts[f"c1_null_or_empty_{name}"] = bad
                    issue("c1_null_violation", bad)
            for name in ("n_points", "n_pairs"):
                if name in c1_names and _arrow_matches(c1_names[name].type, pa.int32()):
                    bad = int(db.execute(f"SELECT count(*) FROM c1 WHERE {name} IS NULL OR {name} < 0").fetchone()[0])
                    issue("c1_count_violation", bad)
            if "beta_class" in c1_names and pa.types.is_string(c1_names["beta_class"].type):
                bad = int(db.execute("SELECT count(*) FROM c1 WHERE beta_class IS NOT NULL AND beta_class NOT IN ('low','watch','inspect')").fetchone()[0])
                issue("c1_beta_class_violation", bad)
            if {"sparse", "vlm_mm_yr"}.issubset(c1_names) and _arrow_matches(c1_names["sparse"].type, pa.bool_()):
                null_sparse = int(db.execute("SELECT count(*) FROM c1 WHERE sparse IS NULL").fetchone()[0])
                inconsistent = int(db.execute("SELECT count(*) FROM c1 WHERE sparse IS NOT NULL AND sparse <> (vlm_mm_yr IS NULL)").fetchone()[0])
                counts["c1_null_sparse"] = null_sparse
                counts["c1_invalid_sparse_relationships"] = inconsistent
                issue("c1_null_sparse", null_sparse)
                issue("c1_sparse_relationship_violation", inconsistent)

            for name in ("engine_version", "params_hash"):
                declared = _metadata_value(c1_meta, name)
                if declared is not None and name in c1_names:
                    mismatch = int(db.execute(f"SELECT count(*) FROM c1 WHERE {name} IS DISTINCT FROM ?", [declared]).fetchone()[0])
                    counts[f"c1_{name}_metadata_mismatches"] = mismatch
                    issue("c1_metadata_row_mismatch", mismatch)
            if expected_params_hash is not None and "params_hash" in c1_names:
                mismatch = int(db.execute(
                    "SELECT count(*) FROM c1 WHERE params_hash IS DISTINCT FROM ?",
                    [expected_params_hash],
                ).fetchone()[0])
                counts["c1_c6_params_hash_row_mismatches"] = mismatch
                issue("c1_c6_row_params_hash_mismatch", mismatch)
    except Exception:  # noqa: BLE001 - aggregate errors must remain path/SQL-free
        issue("aggregate_validation_unavailable")

    if c6_valid and "horizon_years" in c6_config.get("params", {}):
        config_horizon = c6_config["params"]["horizon_years"]
        try:
            if horizon is not None and int(config_horizon) != horizon:
                issue("c1_c6_horizon_mismatch")
        except (TypeError, ValueError):
            issue("c6_config_violation")
    if c6_valid:
        config_seed = c6_config.get("seed")
        try:
            if seed_valid and int(config_seed) != int(seed_text):
                issue("c1_c6_seed_mismatch")
        except (TypeError, ValueError):
            issue("c6_config_violation")

    return ValidationReport(
        not issues,
        counts,
        issues,
        limitations=limitations,
        checks_not_performed=checks_not_performed,
    )
