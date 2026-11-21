"""Synthetic production preflight tests; no private artifact files are used."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from api import integration_validation, metadata, preflight

ROOT = Path(__file__).parents[2]
MOCKS = ROOT / "contracts" / "mock"
TOKEN = "synthetic-preflight-authority-token"


def _write_c1(path: Path, *, missing_column: str | None = None) -> None:
    config = yaml.safe_load((ROOT / "configs" / "delhi.yaml").read_text(encoding="utf-8"))
    fields = [
        pa.field("bldg_id", pa.string(), nullable=False),
        pa.field("ward_id", pa.string()),
        pa.field("cell_id", pa.string()),
        pa.field("n_points", pa.int32(), nullable=False),
        pa.field("vlm_mm_yr", pa.float32()),
        pa.field("vlm_iqr_mm_yr", pa.float32()),
        pa.field("n_pairs", pa.int32(), nullable=False),
        pa.field("beta_rate_per_yr", pa.float32()),
        pa.field("beta_horizon", pa.float32()),
        pa.field("beta_ratio_horizon", pa.string()),
        pa.field("beta_class", pa.string()),
        pa.field("sparse", pa.bool_(), nullable=False),
        pa.field("vt_risk_insar", pa.int8()),
        pa.field("engine_version", pa.string(), nullable=False),
        pa.field("params_hash", pa.string(), nullable=False),
    ]
    if missing_column:
        fields = [field for field in fields if field.name != missing_column]
    schema = pa.schema(fields).with_metadata(
        {
            b"contract": b"C1@1.0",
            b"horizon_years": str(config["params"]["horizon_years"]).encode(),
            b"seed": str(config["seed"]).encode(),
            b"engine_version": b"synthetic-engine",
            b"params_hash": integration_validation.canonical_params_hash(
                config["params"]
            ).encode(),
        }
    )
    pq.write_table(pa.Table.from_pylist([], schema=schema), path)


def _valid_environment(tmp_path: Path) -> dict[str, str]:
    names = {
        "API_WARD_SUMMARY_PATH": "ward_summary.json",
        "API_CELL_SCORES_PATH": "cell_scores.geojson",
        "API_VALIDATION_SUMMARY_PATH": "validation_summary.json",
    }
    environment = {"API_ENV": "production", "AUTHORITY_TOKEN": TOKEN}
    for variable, filename in names.items():
        path = tmp_path / filename
        shutil.copyfile(MOCKS / filename, path)
        environment[variable] = str(path)
    c1_path = tmp_path / "building_metrics.parquet"
    _write_c1(c1_path)
    environment["API_BUILDING_METRICS_PATH"] = str(c1_path)
    return environment


def test_valid_synthetic_production_configuration_passes_without_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_environment(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("full C0/C1 validator must not run during preflight")

    monkeypatch.setattr(integration_validation, "validate_building_artifacts", forbidden)
    result = preflight.run_preflight(env)

    assert result.ok
    assert result.issues == []
    assert "c0_c1_id_set_equality" in result.checks_not_performed


def test_missing_required_environment_variables_fail(tmp_path: Path) -> None:
    result = preflight.run_preflight({"API_ENV": "production"})

    assert not result.ok
    assert "authority_token_missing" in result.issues
    assert {"c2_ward_summary", "c2_cell_scores", "c3_validation_summary", "c1_building_metrics"}.issubset(result.issues)


def test_unset_api_environment_fails(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env.pop("API_ENV")

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "api_env_must_be_production" in result.issues


@pytest.mark.parametrize("token", [None, ""])
def test_missing_or_empty_authority_token_fails(
    tmp_path: Path, token: str | None
) -> None:
    env = _valid_environment(tmp_path)
    if token is None:
        env.pop("AUTHORITY_TOKEN")
    else:
        env["AUTHORITY_TOKEN"] = token

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "authority_token_missing" in result.issues


def test_dev_environment_is_rejected(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env["API_ENV"] = "dev"

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "api_env_must_be_production" in result.issues


def test_missing_artifact_fails_without_fallback(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env["API_WARD_SUMMARY_PATH"] = str(tmp_path / "missing.json")

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_ward_summary" in result.issues


def test_unreadable_artifact_directory_fails(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env["API_CELL_SCORES_PATH"] = str(tmp_path)

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_cell_scores" in result.issues


@pytest.mark.parametrize("bad_content", [b"not json", b"{}"])
def test_malformed_artifact_fails_safely(
    tmp_path: Path, bad_content: bytes
) -> None:
    env = _valid_environment(tmp_path)
    Path(env["API_CELL_SCORES_PATH"]).write_bytes(bad_content)

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_cell_scores_invalid" in result.issues


@pytest.mark.parametrize("bad_document", ["[]", '{"contract":"C2@1.0","meta":[],"wards":[]}'])
def test_malformed_c2_metadata_fails_without_uncaught_error(
    tmp_path: Path, bad_document: str
) -> None:
    env = _valid_environment(tmp_path)
    Path(env["API_WARD_SUMMARY_PATH"]).write_text(bad_document, encoding="utf-8")

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_ward_summary_invalid" in result.issues


def test_relative_mock_artifact_path_is_rejected(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env["API_WARD_SUMMARY_PATH"] = "contracts/mock/ward_summary.json"

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_ward_summary" in result.issues


def test_symlink_alias_to_mock_artifact_is_rejected(tmp_path: Path) -> None:
    alias = tmp_path / "ward-alias.json"
    try:
        alias.symlink_to(MOCKS / "ward_summary.json")
    except OSError as exc:
        windows_privilege_restriction = (
            os.name == "nt" and getattr(exc, "winerror", None) == 1314
        )
        unsupported_filesystem = exc.errno in {
            errno.ENOSYS,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        if windows_privilege_restriction:
            pytest.skip("Windows did not grant symlink creation privilege (winerror 1314)")
        if unsupported_filesystem:
            pytest.skip(f"filesystem does not support symlinks (errno {exc.errno})")
        raise
    env = _valid_environment(tmp_path)
    env["API_WARD_SUMMARY_PATH"] = str(alias)

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_ward_summary" in result.issues


def test_optional_geometry_path_inside_mock_directory_is_rejected(
    tmp_path: Path,
) -> None:
    env = _valid_environment(tmp_path)
    env["API_BUILDINGS_GEOMETRY_PATH"] = "contracts/mock/building_metrics.json"

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c0_geometry_path_invalid" in result.issues


def test_optional_geometry_path_may_be_absent(tmp_path: Path) -> None:
    result = preflight.run_preflight(_valid_environment(tmp_path))

    assert result.ok


def test_valid_synthetic_c0_geometry_metadata_passes(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    c0_path = tmp_path / "c0.parquet"
    geo_metadata = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "crs": {"id": {"authority": "EPSG", "code": 4326}},
            }
        },
    }
    schema = pa.schema(
        [
            pa.field("bldg_id", pa.string()),
            pa.field("footprint_m2", pa.float64()),
            pa.field("source", pa.string()),
            pa.field("ward_id", pa.string()),
            pa.field("cell_id", pa.string()),
            pa.field("geometry", pa.binary()),
        ],
        metadata={b"geo": json.dumps(geo_metadata).encode("utf-8")},
    )
    pq.write_table(pa.Table.from_pylist([], schema=schema), c0_path)
    env["API_BUILDINGS_GEOMETRY_PATH"] = str(c0_path)

    result = preflight.run_preflight(env)

    assert result.ok


def test_configured_but_missing_geometry_path_fails(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env["API_BUILDINGS_GEOMETRY_PATH"] = str(tmp_path / "missing-c0.parquet")

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c0_geometry_path_invalid" in result.issues


def test_c2_c6_city_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _valid_environment(tmp_path)
    temporary_configs = tmp_path / "configs"
    temporary_configs.mkdir()
    config = yaml.safe_load((ROOT / "configs" / "delhi.yaml").read_text(encoding="utf-8"))
    config["city"] = "chennai"
    (temporary_configs / "delhi.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(preflight, "CONFIGS_DIR", temporary_configs)
    monkeypatch.setattr(metadata, "CONFIGS_DIR", temporary_configs)

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c2_ward_summary_invalid" in result.issues


def test_invalid_c3_validation_json_fails(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    Path(env["API_VALIDATION_SUMMARY_PATH"]).write_text("null", encoding="utf-8")

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c3_validation_summary_invalid" in result.issues


def test_c1_missing_required_column_fails(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    c1_path = tmp_path / "incomplete.parquet"
    _write_c1(c1_path, missing_column="sparse")
    env["API_BUILDING_METRICS_PATH"] = str(c1_path)

    result = preflight.run_preflight(env)

    assert not result.ok
    assert "c1_parquet_metadata_invalid" in result.issues


def test_diagnostics_do_not_reveal_token_or_paths(tmp_path: Path) -> None:
    env = _valid_environment(tmp_path)
    env["API_WARD_SUMMARY_PATH"] = str(tmp_path / "private-ward-path.json")
    result = preflight.run_preflight(env)
    diagnostics = json.dumps({"issues": result.issues, "checks": result.checks_not_performed})

    assert TOKEN not in diagnostics
    assert str(tmp_path) not in diagnostics
    assert "private-ward-path" not in diagnostics


def test_cli_exit_code_and_output_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in _valid_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    assert preflight.main() == 0
    assert "PREFLIGHT_OK" in capsys.readouterr().out

    monkeypatch.delenv("AUTHORITY_TOKEN")
    assert preflight.main() == 1
    output = capsys.readouterr().out
    assert "authority_token_missing" in output
    assert TOKEN not in output


def test_module_cli_exit_codes_use_synthetic_configuration(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(_valid_environment(tmp_path))
    command = [sys.executable, "-m", "api.preflight"]
    success = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )

    assert success.returncode == 0
    assert "PREFLIGHT_OK" in success.stdout
    assert TOKEN not in success.stdout + success.stderr
    env.pop("AUTHORITY_TOKEN")
    failure = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )

    assert failure.returncode == 1
    assert "authority_token_missing" in failure.stdout
    assert TOKEN not in failure.stdout + failure.stderr
