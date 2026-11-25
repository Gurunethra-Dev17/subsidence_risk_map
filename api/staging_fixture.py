"""Generate a tiny, deterministic C1 Parquet fixture for synthetic API staging."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_ENGINE_VERSION = "synthetic-staging-v1"
_FIXTURE_PARAMS = {"fixture": _ENGINE_VERSION, "horizon_years": 10}
_PARAMS_HASH = hashlib.sha256(
    json.dumps(
        _FIXTURE_PARAMS,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()

_ROWS = (
    (
        "SYNTH-DEMO-001",
        "SYNTH-WARD-001",
        "SYNTH-CELL-001",
        5,
        -4.2,
        0.4,
        3,
        0.0002,
        0.002,
        "1/500",
        "inspect",
        False,
        1,
        _ENGINE_VERSION,
        _PARAMS_HASH,
        77.10,
        28.70,
    ),
    (
        "SYNTH-DEMO-002",
        "SYNTH-WARD-001",
        "SYNTH-CELL-001",
        0,
        None,
        None,
        0,
        None,
        None,
        None,
        None,
        True,
        None,
        _ENGINE_VERSION,
        _PARAMS_HASH,
        77.20,
        28.75,
    ),
    (
        "SYNTH-DEMO-003",
        "SYNTH-WARD-002",
        "SYNTH-CELL-002",
        4,
        -1.5,
        0.2,
        2,
        0.0001,
        0.001,
        "1/1000",
        "watch",
        False,
        2,
        _ENGINE_VERSION,
        _PARAMS_HASH,
        77.50,
        29.00,
    ),
)


def generate_synthetic_c1(output_path: str | Path) -> Path:
    """Write a C1-compatible Parquet fixture only at the explicitly given path.

    Existing destinations are rejected to prevent accidental replacement. The
    extra ``lon`` and ``lat`` columns support the API's C1-only bbox query path.
    """
    destination = Path(output_path).expanduser()
    if not str(output_path).strip():
        raise ValueError("An explicit output path is required")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("The output path already exists")

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    import duckdb

    metadata = {
        "contract": "C1@1.0",
        "horizon_years": "10",
        "seed": "0",
        "engine_version": _ENGINE_VERSION,
        "params_hash": _PARAMS_HASH,
    }
    metadata_sql = ", ".join(f"{key}: '{value}'" for key, value in metadata.items())
    destination_sql = destination.as_posix().replace("'", "''")

    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE synthetic_c1 (
                bldg_id VARCHAR NOT NULL,
                ward_id VARCHAR,
                cell_id VARCHAR,
                n_points INTEGER NOT NULL,
                vlm_mm_yr FLOAT,
                vlm_iqr_mm_yr FLOAT,
                n_pairs INTEGER NOT NULL,
                beta_rate_per_yr FLOAT,
                beta_horizon FLOAT,
                beta_ratio_horizon VARCHAR,
                beta_class VARCHAR,
                sparse BOOLEAN NOT NULL,
                vt_risk_insar TINYINT,
                engine_version VARCHAR NOT NULL,
                params_hash VARCHAR NOT NULL,
                lon DOUBLE NOT NULL,
                lat DOUBLE NOT NULL
            )
            """
        )
        placeholders = ", ".join("?" for _ in _ROWS[0])
        connection.executemany(f"INSERT INTO synthetic_c1 VALUES ({placeholders})", _ROWS)
        connection.execute(
            f"COPY synthetic_c1 TO '{destination_sql}' "
            f"(FORMAT PARQUET, KV_METADATA {{{metadata_sql}}})"
        )

    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        help="explicit path for the generated Parquet file; existing files are not overwritten",
    )
    args = parser.parse_args()
    generate_synthetic_c1(args.output)
    print("Synthetic C1 staging fixture created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
