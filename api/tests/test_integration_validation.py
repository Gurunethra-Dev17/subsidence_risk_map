"""Synthetic-only tests for the standalone C0/C1 integration validator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from api.integration_validation import canonical_params_hash, validate_building_artifacts

_C1_FIELDS = [
    pa.field("bldg_id", pa.string()), pa.field("ward_id", pa.string()),
    pa.field("cell_id", pa.string()), pa.field("n_points", pa.int32()),
    pa.field("vlm_mm_yr", pa.float32()), pa.field("vlm_iqr_mm_yr", pa.float32()),
    pa.field("n_pairs", pa.int32()), pa.field("beta_rate_per_yr", pa.float32()),
    pa.field("beta_horizon", pa.float32()), pa.field("beta_ratio_horizon", pa.string()),
    pa.field("beta_class", pa.string()), pa.field("sparse", pa.bool_()),
    pa.field("vt_risk_insar", pa.int8()), pa.field("engine_version", pa.string()),
    pa.field("params_hash", pa.string()),
]
_GEO = {
    "version": "1.1.0", "primary_column": "geometry",
    "columns": {"geometry": {
        "encoding": "WKB", "geometry_types": ["Polygon", "MultiPolygon"],
        "crs": {"id": {"authority": "EPSG", "code": 4326}, "name": "WGS 84"},
    }},
}


def _polygon_wkb() -> bytes:
    with duckdb.connect(database=":memory:") as db:
        db.execute("LOAD spatial")
        return bytes(db.execute(
            "SELECT ST_AsWKB(ST_GeomFromText('POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))'))"
        ).fetchone()[0])


def _write_artifacts(
    tmp_path: Path,
    *,
    c0_ids: tuple[str | None, ...] = ("b-1", "b-2"),
    c1_ids: tuple[str | None, ...] | None = None,
    c0_overrides: dict[str, list[object]] | None = None,
    c1_overrides: dict[str, list[object]] | None = None,
    c0_types: dict[str, pa.DataType] | None = None,
    c1_types: dict[str, pa.DataType] | None = None,
    c0_geo: dict[str, object] | None = None,
    c1_metadata: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    c0_path, c1_path = tmp_path / "synthetic-c0.parquet", tmp_path / "synthetic-c1.parquet"
    c1_ids = c0_ids if c1_ids is None else c1_ids
    c0_values: dict[str, list[object]] = {
        "bldg_id": list(c0_ids), "footprint_m2": [10.0] * len(c0_ids),
        "source": ["osm"] * len(c0_ids), "ward_id": ["ward-x"] * len(c0_ids),
        "cell_id": ["cell-x"] * len(c0_ids), "geometry": [_polygon_wkb()] * len(c0_ids),
    }
    c0_values.update(c0_overrides or {})
    c0_type_map = {
        "bldg_id": pa.string(), "footprint_m2": pa.float64(), "source": pa.string(),
        "ward_id": pa.string(), "cell_id": pa.string(), "geometry": pa.binary(),
    }
    c0_type_map.update(c0_types or {})
    c0_schema = pa.schema([pa.field(name, typ) for name, typ in c0_type_map.items()])
    c0_schema = c0_schema.with_metadata({b"geo": json.dumps(c0_geo or _GEO).encode()})
    pq.write_table(pa.Table.from_pydict(c0_values, schema=c0_schema), c0_path)

    c1_values: dict[str, list[object]] = {
        "bldg_id": list(c1_ids), "ward_id": ["ward-x"] * len(c1_ids),
        "cell_id": ["cell-x"] * len(c1_ids), "n_points": [3] * len(c1_ids),
        "vlm_mm_yr": [-1.0] * len(c1_ids), "vlm_iqr_mm_yr": [None] * len(c1_ids),
        "n_pairs": [0] * len(c1_ids), "beta_rate_per_yr": [None] * len(c1_ids),
        "beta_horizon": [None] * len(c1_ids), "beta_ratio_horizon": [None] * len(c1_ids),
        "beta_class": [None] * len(c1_ids), "sparse": [False] * len(c1_ids),
        "vt_risk_insar": [None] * len(c1_ids), "engine_version": ["engine-test"] * len(c1_ids),
        "params_hash": ["hash-test"] * len(c1_ids),
    }
    c1_values.update(c1_overrides or {})
    c1_field_types = dict(zip((field.name for field in _C1_FIELDS), (field.type for field in _C1_FIELDS)))
    c1_field_types.update(c1_types or {})
    c1_schema = pa.schema([pa.field(name, typ) for name, typ in c1_field_types.items()])
    metadata = {
        "contract": "C1@1.0", "horizon_years": "10", "seed": "42",
        "engine_version": "engine-test", "params_hash": "hash-test",
    }
    metadata.update(c1_metadata or {})
    c1_schema = c1_schema.with_metadata({key.encode(): value.encode() for key, value in metadata.items()})
    pq.write_table(pa.Table.from_pydict(c1_values, schema=c1_schema), c1_path)
    return c0_path, c1_path


def _manifest(path: Path, rows: int = 2, contract: str = "C0@1.0") -> Path:
    manifest_path = path / "manifest.json"
    buildings_path = path / "synthetic-c0.parquet"
    digest = hashlib.sha256(buildings_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps({
        "contract": contract, "pack_version": "synthetic-1.0.0",
        "created_utc": "2026-01-01T00:00:00Z", "city": "synthetic",
        "crs_storage": "EPSG:4326",
        "files": [{"name": "buildings.parquet", "sha256": digest, "rows": rows}],
        "sources": [], "attribution": [], "notes": [],
    }), encoding="utf-8")
    return manifest_path


def test_valid_complete_synthetic_pair_and_manifest(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    report = validate_building_artifacts(c0, c1, c0_manifest_path=_manifest(tmp_path))
    assert report.ok
    assert report.counts["c0_rows"] == report.counts["c1_rows"] == 2
    assert report.counts["missing_c1_matches"] == report.counts["orphan_c1_ids"] == 0
    assert report.to_dict()["ok"] is True


def test_equal_row_counts_do_not_hide_mismatched_id_sets(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path, c0_ids=("c0-a", "c0-b"), c1_ids=("c0-a", "c1-orphan"))
    report = validate_building_artifacts(c0, c1)
    assert not report.ok
    assert report.counts["c0_rows"] == report.counts["c1_rows"] == 2
    assert report.counts["missing_c1_matches"] == 1
    assert report.counts["orphan_c1_ids"] == 1


def test_empty_c0_and_c1_artifacts_have_empty_matching_id_sets(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path, c0_ids=(), c1_ids=())
    report = validate_building_artifacts(c0, c1)
    assert report.ok
    assert report.counts["c0_rows"] == report.counts["c1_rows"] == 0


@pytest.mark.parametrize(
    ("c0_ids", "c1_ids", "expected"),
    [
        (("b-1", "b-2"), ("b-1",), "missing_c1_match"),
        (("b-1",), ("b-1", "orphan"), "orphan_c1_id"),
        (("b-1", "b-1"), ("b-1", "b-1"), "c0_duplicate_id"),
        ((None, ""), (None, ""), "c0_invalid_id"),
        (("b-1", "b-2"), ("b-1", "b-1"), "c1_duplicate_id"),
    ],
)
def test_id_integrity_failures_are_aggregated(
    tmp_path: Path, c0_ids: tuple[str | None, ...], c1_ids: tuple[str | None, ...], expected: str
) -> None:
    c0, c1 = _write_artifacts(tmp_path, c0_ids=c0_ids, c1_ids=c1_ids)
    report = validate_building_artifacts(c0, c1)
    assert not report.ok
    assert report.issues.get(expected, 0) > 0


def test_required_columns_and_physical_types_are_checked(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path, c1_types={"n_points": pa.int64()})
    # Re-write C1 without one required field.
    table = pq.read_table(c1)
    pq.write_table(table.drop(["vt_risk_insar"]), c1)
    report = validate_building_artifacts(c0, c1)
    assert report.issues.get("c1_type_violation") == 1
    assert report.issues.get("c1_missing_column") == 1


def test_sparse_null_and_both_relationship_errors_are_not_coerced(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"vlm_mm_yr": [None, -1.0], "sparse": [None, True]},
    )
    report = validate_building_artifacts(c0, c1)
    assert report.counts["c1_null_sparse"] == 1
    assert report.counts["c1_invalid_sparse_relationships"] == 1


def test_nullable_distortion_fields_are_allowed(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    report = validate_building_artifacts(c0, c1)
    assert report.ok


def test_invalid_beta_class_and_negative_counts_are_reported(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"beta_class": ["critical", None], "n_points": [-1, 3], "n_pairs": [0, -1]},
    )
    report = validate_building_artifacts(c0, c1)
    assert report.issues.get("c1_beta_class_violation") == 1
    assert report.issues.get("c1_count_violation") == 2


@pytest.mark.parametrize("wkt", [None, "POINT (0 0)", "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))"])
def test_null_invalid_or_non_polygon_geometry_is_reported(tmp_path: Path, wkt: str | None) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    if wkt is None:
        # A null geometry is represented as a null binary value.
        table = pq.read_table(c0).set_column(5, "geometry", pa.array([None, _polygon_wkb()], type=pa.binary()))
        pq.write_table(table, c0)
    else:
        with duckdb.connect(database=":memory:") as db:
            db.execute("LOAD spatial")
            value = db.execute("SELECT ST_AsWKB(ST_GeomFromText(?))", [wkt]).fetchone()[0]
        table = pq.read_table(c0).set_column(5, "geometry", pa.array([value, _polygon_wkb()], type=pa.binary()))
        pq.write_table(table, c0)
    report = validate_building_artifacts(c0, c1)
    assert report.issues.get("c0_geometry_violation", 0) > 0


def test_polygon_and_multipolygon_geometry_are_accepted(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    with duckdb.connect(database=":memory:") as db:
        db.execute("LOAD spatial")
        multi = db.execute("SELECT ST_AsWKB(ST_GeomFromText('MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)))'))").fetchone()[0]
    table = pq.read_table(c0).set_column(5, "geometry", pa.array([_polygon_wkb(), multi], type=pa.binary()))
    pq.write_table(table, c0)
    assert validate_building_artifacts(c0, c1).ok


def test_wrong_crs_source_and_footprint_are_reported(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(
        tmp_path,
        c0_overrides={"source": ["unknown", "osm"], "footprint_m2": [0.0, 2.0]},
        c0_geo={"version": "1.1.0", "primary_column": "geometry", "columns": {
            "geometry": {"encoding": "WKB", "geometry_types": ["Polygon"], "crs": {"id": {"authority": "EPSG", "code": 3857}}}
        }},
    )
    report = validate_building_artifacts(c0, c1)
    assert report.issues.get("c0_crs_violation") == 1
    assert report.issues.get("c0_value_violation") == 1


def _replace_geo_metadata(c0_path: Path, raw_geo: bytes | None) -> None:
    table = pq.read_table(c0_path)
    metadata = dict(table.schema.metadata or {})
    if raw_geo is None:
        metadata.pop(b"geo", None)
    else:
        metadata[b"geo"] = raw_geo
    pq.write_table(table.replace_schema_metadata(metadata), c0_path)


@pytest.mark.parametrize(
    ("crs", "expected_issue"),
    [(None, "c0_crs_violation"), ({"id": {"authority": "EPSG", "code": 3857}}, "c0_crs_violation")],
)
def test_missing_or_incorrect_crs_fails(tmp_path: Path, crs: object, expected_issue: str) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    if crs is None:
        geo = {"version": "1.1.0", "primary_column": "geometry", "columns": {
            "geometry": {"encoding": "WKB", "geometry_types": ["Polygon"]}
        }}
    else:
        geo = {"version": "1.1.0", "primary_column": "geometry", "columns": {
            "geometry": {"encoding": "WKB", "geometry_types": ["Polygon"], "crs": crs}
        }}
    _replace_geo_metadata(c0, json.dumps(geo).encode())
    report = validate_building_artifacts(c0, c1)
    assert not report.ok
    assert report.issues.get(expected_issue, 0) == 1


@pytest.mark.parametrize("raw_geo", [b"{", b"\xff", b"[]"])
def test_malformed_geoparquet_metadata_fails_safely(tmp_path: Path, raw_geo: bytes) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    _replace_geo_metadata(c0, raw_geo)
    report = validate_building_artifacts(c0, c1)
    assert not report.ok
    assert report.issues.get("c0_crs_violation", 0) == 1


def test_missing_geoparquet_metadata_fails_safely(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    _replace_geo_metadata(c0, None)
    report = validate_building_artifacts(c0, c1)
    assert report.issues.get("c0_geoparquet_metadata_missing") == 1


def test_additional_c1_column_is_allowed_by_frozen_contract(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    table = pq.read_table(c1).append_column("producer_extension", pa.array(["x", "y"]))
    pq.write_table(table, c1)
    report = validate_building_artifacts(c0, c1)
    assert report.ok
    assert any("extensions are allowed" in limitation for limitation in report.limitations)


@pytest.mark.parametrize(
    "raw_manifest",
    [
        "[]",
        '"private-manifest-value"',
        "null",
        '{"contract":"C0@1.0","crs_storage":"EPSG:4326"}',
        '{"files":"buildings.parquet"}',
        '{"files":[null]}',
        '{"files":["private-entry"]}',
        '{"files":[{"sha256":"digest","rows":2}]}',
        '{"files":[{"name":"buildings.parquet","sha256":"digest"}]}',
        '{"private":"raw-content"',
    ],
)
def test_malformed_manifest_shapes_fail_with_safe_aggregates(
    tmp_path: Path, raw_manifest: str
) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    manifest_path = tmp_path / "malformed-manifest.json"
    manifest_path.write_text(raw_manifest, encoding="utf-8")
    report = validate_building_artifacts(c0, c1, c0_manifest_path=manifest_path)
    diagnostics = json.dumps(report.to_dict())
    assert not report.ok
    assert report.issues
    assert "private-manifest-value" not in diagnostics
    assert "private-entry" not in diagnostics
    assert "raw-content" not in diagnostics
    assert str(tmp_path) not in diagnostics


def test_duplicate_buildings_inventory_entries_fail_without_hashing_other_files(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    manifest_path = _manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(dict(manifest["files"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = validate_building_artifacts(c0, c1, c0_manifest_path=manifest_path)
    assert not report.ok
    assert report.issues.get("c0_manifest_inventory_violation") == 1


def test_c1_metadata_row_consistency_and_manifest_declarations(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"engine_version": ["other", "engine-test"]},
        c1_metadata={"contract": "C1@2.0"},
    )
    report = validate_building_artifacts(c0, c1, c0_manifest_path=_manifest(tmp_path, rows=3))
    assert report.issues.get("c1_metadata_violation") == 1
    assert report.issues.get("c1_metadata_row_mismatch") == 1
    assert report.issues.get("c0_manifest_row_count_mismatch") == 1

    wrong_contract = _manifest(tmp_path, contract="C0@2.0")
    contract_report = validate_building_artifacts(c0, c1, c0_manifest_path=wrong_contract)
    assert contract_report.issues.get("c0_manifest_violation", 0) >= 1


def test_missing_c1_metadata_fails_closed(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path, c1_metadata={"contract": "", "horizon_years": "", "seed": ""})
    report = validate_building_artifacts(c0, c1)
    assert report.issues.get("c1_metadata_violation", 0) >= 1


def _write_c6_config(path: Path, params: object) -> Path:
    config = path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "contract": "C6@1.0", "city": "synthetic", "display_name": "Synthetic",
        "utm_epsg": 32643, "bbox": [0, 0, 1, 1], "seed": 42,
        "paths": {"pack_dir": "pack", "out_dir": "out"}, "params": params,
        "weights": {"i1": 0.25, "i2": 0.25, "i3": 0.25, "i4": 0.25},
        "mode": "public",
    }, sort_keys=False), encoding="utf-8")
    return config


def test_canonical_hash_matches_confirmed_unicode_test_vector() -> None:
    params = {"z": 2, "label": "Delhi \u0394", "a": 1.25}
    assert canonical_params_hash(params) == (
        "b49e0e8602f7c9759d9393bc4f4019596452d830c90c20c89c6d5f05953e55ec"
    )


def test_canonical_hash_is_key_order_independent_and_type_sensitive() -> None:
    assert canonical_params_hash({"z": 2, "a": 1}) == canonical_params_hash({"a": 1, "z": 2})
    assert canonical_params_hash({"value": 1}) != canonical_params_hash({"value": 1.0})


@pytest.mark.parametrize("bad_number", [float("nan"), float("inf"), float("-inf")])
def test_canonical_hash_rejects_non_finite_numbers(bad_number: float) -> None:
    with pytest.raises(ValueError):
        canonical_params_hash({"private-param": bad_number})


def test_canonical_hash_rejects_non_json_values() -> None:
    with pytest.raises(ValueError):
        canonical_params_hash({"value": object()})
    with pytest.raises(ValueError):
        canonical_params_hash({1: "non-string key"})


def test_c6_complete_params_mapping_matches_file_and_every_row(tmp_path: Path) -> None:
    config = yaml.safe_load((Path(__file__).parents[2] / "configs" / "delhi.yaml").read_text(encoding="utf-8"))
    expected = canonical_params_hash(config["params"])
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"params_hash": [expected, expected]},
        c1_metadata={"params_hash": expected},
    )
    report = validate_building_artifacts(c0, c1, c6_config_path=Path(__file__).parents[2] / "configs" / "delhi.yaml")
    assert report.ok
    assert report.counts["c1_c6_params_hash_row_mismatches"] == 0
    assert "c6_params_hash_recomputation" not in report.checks_not_performed


def test_wrong_c1_file_level_hash_fails_c6_comparison(tmp_path: Path) -> None:
    config = _write_c6_config(tmp_path, {"radius_m": 100, "horizon_years": 10})
    expected = canonical_params_hash({"radius_m": 100, "horizon_years": 10})
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"params_hash": ["wrong-file-hash", "wrong-file-hash"]},
        c1_metadata={"params_hash": "wrong-file-hash"},
    )
    report = validate_building_artifacts(c0, c1, c6_config_path=config)
    assert report.issues.get("c1_c6_file_params_hash_mismatch") == 1
    assert report.counts["c1_c6_params_hash_row_mismatches"] == 2
    assert expected not in json.dumps(report.to_dict())


@pytest.mark.parametrize(
    ("row_hashes", "mismatch_count"),
    [(["expected-placeholder", "bad-one"], 1), (["bad-one", "bad-two"], 2)],
)
def test_mismatches_in_one_or_multiple_rows_are_counted(
    tmp_path: Path, row_hashes: list[str], mismatch_count: int
) -> None:
    params = {"horizon_years": 10}
    expected = canonical_params_hash(params)
    row_hashes = [expected if value == "expected-placeholder" else value for value in row_hashes]
    config = _write_c6_config(tmp_path, params)
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"params_hash": row_hashes},
        c1_metadata={"params_hash": expected},
    )
    report = validate_building_artifacts(c0, c1, c6_config_path=config)
    assert report.counts["c1_c6_params_hash_row_mismatches"] == mismatch_count
    assert report.issues["c1_c6_row_params_hash_mismatch"] == mismatch_count


@pytest.mark.parametrize("params_yaml", [".nan", ".inf", "null"])
def test_invalid_c6_params_fail_and_hash_check_is_marked_unperformed(
    tmp_path: Path, params_yaml: str
) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    config = _write_c6_config(tmp_path, yaml.safe_load(params_yaml))
    report = validate_building_artifacts(c0, c1, c6_config_path=config)
    assert not report.ok
    assert report.issues.get("c6_params_invalid", 0) >= 1
    assert "c6_params_hash_comparison" in report.checks_not_performed


def test_missing_c6_params_is_a_validation_failure(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    config = _write_c6_config(tmp_path, {"safe": True})
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    raw.pop("params")
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    report = validate_building_artifacts(c0, c1, c6_config_path=config)
    assert report.issues.get("c6_config_violation", 0) >= 1
    assert report.issues.get("c6_params_invalid", 0) >= 1
    assert "c6_params_hash_comparison" in report.checks_not_performed


def test_without_c6_hash_recomputation_is_explicitly_not_performed(tmp_path: Path) -> None:
    c0, c1 = _write_artifacts(tmp_path)
    report = validate_building_artifacts(c0, c1)
    assert report.ok
    assert "c6_params_hash_recomputation" in report.checks_not_performed


def test_report_never_discloses_private_ids_or_paths(tmp_path: Path) -> None:
    secret_id = "private-building-identifier-xyz"
    c0, c1 = _write_artifacts(tmp_path, c0_ids=(secret_id, "b-2"), c1_ids=("b-1", "b-2"))
    report_text = json.dumps(validate_building_artifacts(c0, c1).to_dict())
    assert secret_id not in report_text
    assert str(tmp_path) not in report_text
    assert "SELECT" not in report_text


def test_hash_diagnostics_do_not_disclose_params_or_hash_values(tmp_path: Path) -> None:
    secret_value = "confidential-config-value"
    params = {"internal_key": secret_value, "horizon_years": 10}
    config = _write_c6_config(tmp_path, params)
    c0, c1 = _write_artifacts(
        tmp_path,
        c1_overrides={"params_hash": ["private-hash", "private-hash"]},
        c1_metadata={"params_hash": "private-hash"},
    )
    report_text = json.dumps(validate_building_artifacts(c0, c1, c6_config_path=config).to_dict())
    assert secret_value not in report_text
    assert "private-hash" not in report_text
    assert str(tmp_path) not in report_text
