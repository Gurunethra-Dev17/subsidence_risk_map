"""Safe, metadata-only preflight for a configured production API deployment.

Run from the repository root with ``python -m api.preflight``. This command
does not import the ASGI application or scan Parquet row groups.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator, FormatChecker

from api.integration_validation import canonical_params_hash
from api.metadata import SCHEMAS_DIR, build_meta_payload, load_city_config

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MOCK_ROOT = (_REPO_ROOT / "contracts" / "mock").resolve()
_REQUIRED_PATHS = {
    "API_WARD_SUMMARY_PATH": "c2_ward_summary",
    "API_CELL_SCORES_PATH": "c2_cell_scores",
    "API_VALIDATION_SUMMARY_PATH": "c3_validation_summary",
    "API_BUILDING_METRICS_PATH": "c1_building_metrics",
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
_C0_REQUIRED_TYPES = {
    "bldg_id": "string",
    "footprint_m2": "number",
    "source": "string",
    "ward_id": "string",
    "cell_id": "string",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass
class PreflightResult:
    """Safe aggregate preflight result; contains codes only, never paths."""

    issues: list[str] = field(default_factory=list)
    checks_not_performed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def _schema_validate(document: Any, schema_name: str) -> None:
    schema = _read_json(SCHEMAS_DIR / schema_name)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def _resolve_configured_path(value: str | None) -> Path:
    if value is None or not value.strip():
        raise ValueError("artifact_path_unconfigured")
    resolved = Path(value).expanduser().resolve(strict=True)
    if resolved.is_relative_to(_MOCK_ROOT):
        raise ValueError("artifact_mock_path")
    if not resolved.is_file():
        raise ValueError("artifact_not_file")
    # Opening the file checks actual read access, including under test runners
    # whose effective user may bypass ordinary permission bits.
    with resolved.open("rb"):
        pass
    return resolved


def _metadata(schema: pa.Schema) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (schema.metadata or {}).items():
        try:
            result[key.decode("utf-8")] = value.decode("utf-8")
        except (AttributeError, UnicodeDecodeError):
            continue
    return result


def _declared(metadata: dict[str, str], key: str) -> str | None:
    return metadata.get(key, metadata.get(f"org.subsidence.{key}"))


def _validate_c1(path: Path, c6_config: Mapping[str, Any]) -> None:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    fields = {field.name.casefold(): field for field in schema}
    if len(fields) != len(schema) or set(_C1_TYPES) - fields.keys():
        raise ValueError("c1_schema_missing_columns")
    for name, expected_type in _C1_TYPES.items():
        if not fields[name].type.equals(expected_type):
            raise ValueError("c1_schema_type_mismatch")

    declarations = _metadata(schema)
    if _declared(declarations, "contract") != "C1@1.0":
        raise ValueError("c1_contract_declaration_invalid")
    horizon = _declared(declarations, "horizon_years")
    seed = _declared(declarations, "seed")
    engine_version = _declared(declarations, "engine_version")
    params_hash = _declared(declarations, "params_hash")
    try:
        declared_horizon = int(horizon) if horizon is not None else 0
        configured_horizon = float(c6_config["params"].get("horizon_years"))
    except (TypeError, ValueError, OverflowError):
        declared_horizon = 0
        configured_horizon = -1
    if (
        declared_horizon <= 0
        or str(declared_horizon) != horizon
        or configured_horizon != declared_horizon
    ):
        raise ValueError("c1_horizon_declaration_mismatch")
    try:
        declared_seed = int(seed) if seed is not None else None
        configured_seed = int(c6_config["seed"])
    except (TypeError, ValueError, OverflowError):
        declared_seed = None
        configured_seed = None
    if (
        declared_seed is None
        or str(declared_seed) != seed
        or declared_seed != configured_seed
    ):
        raise ValueError("c1_seed_declaration_mismatch")
    if not engine_version or not engine_version.strip():
        raise ValueError("c1_engine_version_missing")
    if not params_hash or not _SHA256.fullmatch(params_hash):
        raise ValueError("c1_params_hash_invalid")
    if params_hash != canonical_params_hash(c6_config.get("params")):
        raise ValueError("c1_params_hash_mismatch")


def _validate_c0(path: Path) -> None:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    fields = {field.name.casefold(): field for field in schema}
    if (
        len(fields) != len(schema)
        or set(_C0_REQUIRED_TYPES) - fields.keys()
        or "geometry" not in fields
    ):
        raise ValueError("c0_schema_missing_columns")
    for name, kind in _C0_REQUIRED_TYPES.items():
        data_type = fields[name].type
        valid = pa.types.is_string(data_type) if kind == "string" else pa.types.is_floating(data_type)
        if not valid:
            raise ValueError("c0_schema_type_mismatch")
    geometry_type = fields["geometry"].type
    if not (
        pa.types.is_binary(geometry_type)
        or pa.types.is_large_binary(geometry_type)
        or str(geometry_type).upper().startswith("GEOMETRY")
    ):
        raise ValueError("c0_geometry_type_invalid")

    raw_geo = (schema.metadata or {}).get(b"geo")
    if raw_geo is None:
        raise ValueError("c0_geoparquet_metadata_missing")
    try:
        geo = json.loads(raw_geo.decode("utf-8"))
        geometry = geo["columns"][geo["primary_column"]]
        crs = geometry["crs"]
        encoding = geometry.get("encoding")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("c0_geoparquet_metadata_invalid") from None
    authority_id = crs.get("id") if isinstance(crs, dict) else None
    is_epsg4326 = (
        isinstance(authority_id, dict)
        and str(authority_id.get("authority", "")).upper() == "EPSG"
        and str(authority_id.get("code", "")) == "4326"
    )
    if (
        geo.get("primary_column") != "geometry"
        or encoding not in (None, "WKB")
        or not is_epsg4326
    ):
        raise ValueError("c0_crs_invalid")


def run_preflight(environ: Mapping[str, str] | None = None) -> PreflightResult:
    """Check configured production inputs without reading Parquet row groups."""
    env = os.environ if environ is None else environ
    result = PreflightResult(
        checks_not_performed=[
            "c0_c1_dataset_wide_row_integrity",
            "c0_c1_id_set_equality",
            "parquet_row_values_and_nullability",
            "building_bbox_geometry_availability_when_c0_is_unconfigured",
        ]
    )

    if env.get("API_ENV", "").strip().casefold() != "production":
        result.issues.append("api_env_must_be_production")
    token = env.get("AUTHORITY_TOKEN")
    if token is None or not token.strip():
        result.issues.append("authority_token_missing")

    paths: dict[str, Path] = {}
    for variable, code in _REQUIRED_PATHS.items():
        try:
            paths[variable] = _resolve_configured_path(env.get(variable))
        except (OSError, RuntimeError, ValueError):
            result.issues.append(code)

    geometry_path: Path | None = None
    configured_geometry = env.get("API_BUILDINGS_GEOMETRY_PATH")
    if configured_geometry is not None and configured_geometry.strip():
        try:
            geometry_path = _resolve_configured_path(configured_geometry)
        except (OSError, RuntimeError, ValueError):
            result.issues.append("c0_geometry_path_invalid")
    elif configured_geometry is not None:
        result.issues.append("c0_geometry_path_invalid")

    ward_path = paths.get("API_WARD_SUMMARY_PATH")
    cell_path = paths.get("API_CELL_SCORES_PATH")
    validation_path = paths.get("API_VALIDATION_SUMMARY_PATH")
    c1_path = paths.get("API_BUILDING_METRICS_PATH")

    ward_summary: Any = None
    c2_valid = False
    if ward_path is not None:
        try:
            ward_summary = _read_json(ward_path)
            build_meta_payload(
                ward_summary, c6_config_path=env.get("API_C6_CONFIG_PATH")
            )  # C2 schema/version and selected C6.
            c2_valid = True
        except Exception:  # noqa: BLE001 - keep parser/config details out of CLI output
            result.issues.append("c2_ward_summary_invalid")

    if cell_path is not None:
        try:
            _schema_validate(_read_json(cell_path), "cell_scores.schema.json")
        except Exception:  # noqa: BLE001 - diagnostics must not expose artifact details
            result.issues.append("c2_cell_scores_invalid")

    if validation_path is not None:
        try:
            _schema_validate(_read_json(validation_path), "validation_summary.schema.json")
        except Exception:  # noqa: BLE001 - diagnostics must not expose artifact details
            result.issues.append("c3_validation_summary_invalid")

    c6_config: dict[str, Any] | None = None
    if c2_valid:
        try:
            # Use the same explicitly selected C6 as the metadata endpoint.
            city = ward_summary["meta"]["city"]
            c6_config = load_city_config(
                city, c6_config_path=env.get("API_C6_CONFIG_PATH")
            )
        except Exception:  # noqa: BLE001 - no filesystem/config details in diagnostics
            result.issues.append("c6_city_config_invalid")

    if c1_path is not None:
        if c6_config is None:
            result.issues.append("c1_c6_comparison_unavailable")
        else:
            try:
                _validate_c1(c1_path, c6_config)
            except Exception:  # noqa: BLE001 - Arrow/parser details can expose paths
                result.issues.append("c1_parquet_metadata_invalid")

    if geometry_path is not None:
        try:
            _validate_c0(geometry_path)
        except Exception:  # noqa: BLE001 - keep Parquet and metadata details private
            result.issues.append("c0_geometry_parquet_metadata_invalid")

    # Keep diagnostic output deterministic if one artifact failed more than once.
    result.issues = sorted(set(result.issues))
    return result


def main() -> int:
    """CLI entry point. Exit 0 means checks passed, nonzero means not ready."""
    result = run_preflight()
    if result.ok:
        print("PREFLIGHT_OK")
    else:
        print("PREFLIGHT_FAILED")
        for issue in result.issues:
            print(issue)
    for check in result.checks_not_performed:
        print(f"NOT_CHECKED:{check}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
