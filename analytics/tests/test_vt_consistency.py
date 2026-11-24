import csv
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely import to_wkb
from shapely.geometry import box

from analytics.export import build_validation_summary
from analytics.vt_consistency import (
    C3_KEYS,
    D5Error,
    _check_geo_metadata,
    _write_ward_csv,
    build_c3_fragment,
    exact_wkb_correspondence,
    run,
    spearman_correlation,
)
from analytics.vt_consistency import (
    _write_json as write_json_output,
)


def test_exact_wkb_correspondence_preserves_unique_building_id():
    c0 = [{"bldg_id": "b-1", "geometry": b"same"}, {"bldg_id": "b-2", "geometry": b"other"}]
    vt = [{"geometry": b"same", "risk_insar": 2}]

    matches, stats = exact_wkb_correspondence(c0, vt)

    assert matches == [("b-1", vt[0])]
    assert stats["exact_unique_matches"] == 1
    assert stats["unmatched_c0_records"] == 1
    assert stats["ambiguous_c0_records"] == 0


def test_duplicate_or_conflicting_vt_geometry_is_ambiguous_not_first_match():
    c0 = [{"bldg_id": "b-1", "geometry": b"same"}]
    vt = [
        {"geometry": b"same", "risk_insar": 1},
        {"geometry": b"same", "risk_insar": 4},
    ]

    matches, stats = exact_wkb_correspondence(c0, vt)

    assert matches == []
    assert stats["ambiguous_c0_records"] == 1
    assert stats["duplicate_vt_geometry_groups"] == 1


def test_duplicate_c0_footprints_are_not_matched_to_single_vt_record():
    c0 = [
        {"bldg_id": "b-1", "geometry": b"same"},
        {"bldg_id": "b-2", "geometry": b"same"},
    ]
    vt = [{"geometry": b"same", "risk_insar": 2}]

    matches, stats = exact_wkb_correspondence(c0, vt)

    assert matches == []
    assert stats["ambiguous_c0_records"] == 2
    assert stats["duplicate_c0_geometry_groups"] == 1


def test_missing_geometry_and_missing_risk_do_not_create_matches():
    c0 = [{"bldg_id": "b-1", "geometry": None}]
    vt = [{"geometry": None, "risk_insar": None}]

    matches, stats = exact_wkb_correspondence(c0, vt)

    assert matches == []
    assert stats["unmatched_c0_records"] == 1


def test_spearman_uses_only_already_paired_values_and_handles_undefined():
    assert spearman_correlation([1, 2, 3], [2, 4, 8]) == pytest.approx(1.0)
    assert spearman_correlation([1], [2]) is None
    assert spearman_correlation([1, 1], [2, 3]) is None
    with pytest.raises(D5Error, match="finite"):
        spearman_correlation([float("nan"), 2], [1, 2])


def test_c3_fragment_has_exact_frozen_shape_and_truthful_unavailable_values():
    fragment = build_c3_fragment()

    assert set(fragment) == C3_KEYS
    assert fragment["n_buildings"] == 0
    assert fragment["spearman_rho"] is None
    assert fragment["labels"] == ["0", "1", "2", "3", "4"]
    assert fragment["confusion_matrix"] == []
    assert "unavailable" in fragment["note"].lower()
    payload = build_validation_summary({"vt_consistency": fragment}, "2026-11-24T12:00:00Z")
    assert payload["vt_consistency"]["n_buildings"] == fragment["n_buildings"]
    assert payload["vt_consistency"]["spearman_rho"] is None


def test_c3_fragment_rejects_invalid_values_and_explains_missing_crosswalk():
    with pytest.raises(D5Error):
        build_c3_fragment(-1, None)
    with pytest.raises(D5Error):
        build_c3_fragment(1, 1.1)
    fragment = build_c3_fragment(2, 0.5)
    assert fragment["n_buildings"] == 2
    assert fragment["spearman_rho"] == 0.5
    assert fragment["confusion_matrix"] == []
    assert "crosswalk" in fragment["note"]


def test_output_writer_refuses_overwrite_without_explicit_flag(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text('{"keep": true}', encoding="utf-8")

    with pytest.raises(D5Error, match="pass --overwrite"):
        write_json_output(path, {"replace": True}, False)

    assert json.loads(path.read_text(encoding="utf-8")) == {"keep": True}


def test_ward_csv_reconciles_all_supplied_ward_ids_without_fabricated_risk(tmp_path):
    wards = [
        {"ward_id": f"w-{index}", "rank": str(index + 1), "score": str(index)}
        for index in range(250)
    ]
    path = tmp_path / "ward_vt_consistency.csv"

    _write_ward_csv(path, wards, False, {"w-0": (1, 0, 0, None)})

    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 250
    assert {row["ward_id"] for row in rows} == {row["ward_id"] for row in wards}
    assert rows[0]["valid_risk_count"] == "0"
    assert rows[0]["mean_risk_insar"] == ""


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_geo_parquet(path, rows, crs_code=4326, geometry_types=None):
    geometry_meta = {
        "encoding": "WKB",
        "geometry_types": geometry_types or ["Polygon"],
        "crs": {"id": {"authority": "EPSG", "code": crs_code}},
    }
    schema = pa.schema(
        [(name, values.type) for name, values in rows.items()],
        metadata={b"geo": json.dumps({"columns": {"geometry": geometry_meta}}).encode()},
    )
    pq.write_table(pa.Table.from_pydict(rows, schema=schema), path)


def _synthetic_run_inputs(tmp_path, exact_match=True, missing_risk=False):
    c0 = tmp_path / "buildings.parquet"
    c1 = tmp_path / "building_metrics.parquet"
    risk = tmp_path / "vt_building_risk.parquet"
    c0_geom = to_wkb(box(0, 0, 1, 1))
    vt_geom = c0_geom if exact_match else to_wkb(box(2, 2, 3, 3))
    _write_geo_parquet(
        c0,
        {
            "bldg_id": pa.array(["b-1"], type=pa.string()),
            "ward_id": pa.array(["w-0"], type=pa.string()),
            "geometry": pa.array([c0_geom], type=pa.binary()),
        },
    )
    c1_schema = pa.schema(
        [
            ("bldg_id", pa.string()),
            ("ward_id", pa.string()),
            ("cell_id", pa.string()),
            ("n_points", pa.int32()),
            ("vlm_mm_yr", pa.float64()),
            ("vlm_iqr_mm_yr", pa.float64()),
            ("n_pairs", pa.int32()),
            ("beta_rate_per_yr", pa.float64()),
            ("beta_horizon", pa.float64()),
            ("beta_ratio_horizon", pa.string()),
            ("beta_class", pa.string()),
            ("sparse", pa.bool_()),
            ("vt_risk_insar", pa.int8()),
            ("engine_version", pa.string()),
            ("params_hash", pa.string()),
        ],
        metadata={
            b"contract": b"C1@1.0",
            b"engine_version": b"f3af18a",
            b"params_hash": b"1a30d00c183cb58b2ee4d9327d9e839a8bc3f4267a0c3b15b207c181b49ac6d5",
            b"horizon_years": b"10",
            b"seed": b"42",
        },
    )
    c1_values = {
        "bldg_id": ["b-1"],
        "ward_id": ["w-0"],
        "cell_id": ["cell-0"],
        "n_points": [3],
        "vlm_mm_yr": [-5.0],
        "vlm_iqr_mm_yr": [1.0],
        "n_pairs": [1],
        "beta_rate_per_yr": [0.0002],
        "beta_horizon": [0.002],
        "beta_ratio_horizon": ["1/500"],
        "beta_class": ["inspect"],
        "sparse": [False],
        "vt_risk_insar": [None],
        "engine_version": ["f3af18a"],
        "params_hash": ["1a30d00c183cb58b2ee4d9327d9e839a8bc3f4267a0c3b15b207c181b49ac6d5"],
    }
    pq.write_table(pa.Table.from_pydict(c1_values, schema=c1_schema), c1)
    _write_geo_parquet(
        risk,
        {
            "bldg_id": pa.array([None], type=pa.string()),
            "risk_insar": pa.array([None if missing_risk else 2], type=pa.int8()),
            "risk_10yrs": pa.array([2], type=pa.int8()),
            "risk_30yrs": pa.array([3], type=pa.int8()),
            "risk_50yrs": pa.array([4], type=pa.int8()),
            "geometry": pa.array([vt_geom], type=pa.binary()),
        },
    )
    config = tmp_path / "delhi.yaml"
    config.write_text(
        """contract: C6@1.0
city: delhi
display_name: Delhi
utm_epsg: 32643
bbox: [76.84, 28.40, 77.35, 28.89]
seed: 42
paths: {pack_dir: data/pack, out_dir: out/delhi}
params: {coverage_min: 0.5}
weights: {i1: 0.3, i2: 0.35, i3: 0.2, i4: 0.15}
mode: public
""",
        encoding="utf-8",
    )
    wards = tmp_path / "wards.geojson"
    _write_json(wards, {"type": "FeatureCollection", "features": []})
    pack = tmp_path / "PACK_MANIFEST.json"
    integration = tmp_path / "integration_manifest.json"
    _write_json(
        pack,
        {
            "files": [
                {"name": c0.name, "sha256": hashlib.sha256(c0.read_bytes()).hexdigest()},
                {"name": risk.name, "sha256": hashlib.sha256(risk.read_bytes()).hexdigest()},
            ]
        },
    )
    _write_json(
        integration,
        {
            "c0_candidate": {
                "files": [
                    {"path": str(c0), "actual_sha256": hashlib.sha256(c0.read_bytes()).hexdigest()}
                ]
            },
            "c1_candidate": {
                "sha256": hashlib.sha256(c1.read_bytes()).hexdigest(),
                "c6_reference_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            },
        },
    )
    d3 = tmp_path / "ward_index.csv"
    with d3.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["ward_id", "rank", "score"])
        writer.writeheader()
        for index in range(250):
            writer.writerow(
                {
                    "ward_id": f"w-{index}",
                    "rank": "1" if index == 0 else "",
                    "score": "75" if index == 0 else "",
                }
            )
    d4 = tmp_path / "ward_sensitivity.csv"
    with d4.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["ward_id", "rank_p05", "rank_p95"])
        writer.writeheader()
        for index in range(250):
            writer.writerow(
                {
                    "ward_id": f"w-{index}",
                    "rank_p05": "1" if index == 0 else "",
                    "rank_p95": "1" if index == 0 else "",
                }
            )
    d3qa = tmp_path / "d3_qa.json"
    _write_json(
        d3qa,
        {"inputs": {str(c1): {"sha256": hashlib.sha256(c1.read_bytes()).hexdigest()}}},
    )
    from argparse import Namespace

    args = Namespace(
        c0=c0,
        c1=c1,
        published_risk=risk,
        wards=wards,
        pack_manifest=pack,
        d3_ward_index=d3,
        d3_qa=d3qa,
        d4_sensitivity=d4,
        config=config,
        integration_manifest=integration,
        output_dir=tmp_path / "d5",
        overwrite=False,
    )
    return args


def test_synthetic_cli_run_produces_c3_compatible_exact_match_and_all_wards(tmp_path):
    args = _synthetic_run_inputs(tmp_path)

    qa = run(args)

    fragment = json.loads((args.output_dir / "vt_consistency.json").read_text(encoding="utf-8"))
    payload = build_validation_summary({"vt_consistency": fragment}, "2026-11-24T12:00:00Z")
    wards = list(
        csv.DictReader((args.output_dir / "ward_vt_consistency.csv").open(encoding="utf-8"))
    )
    assert payload["vt_consistency"]["n_buildings"] == 1
    assert payload["vt_consistency"]["spearman_rho"] is None
    assert qa["geometry"]["counts"]["exact_unique_matches"] == 1
    assert qa["matched_records_with_valid_risk_insar"] == 1
    assert len(wards) == 250
    assert wards[0]["matched_buildings"] == "1"
    assert wards[0]["mean_risk_insar"] == "2.0"


def test_synthetic_cli_run_reports_unavailable_without_spatial_matches(tmp_path):
    args = _synthetic_run_inputs(tmp_path, exact_match=False)

    qa = run(args)

    fragment = json.loads((args.output_dir / "vt_consistency.json").read_text(encoding="utf-8"))
    assert qa["geometry"]["counts"]["exact_unique_matches"] == 0
    assert fragment["n_buildings"] == 0
    assert fragment["spearman_rho"] is None
    assert fragment["confusion_matrix"] == []


def test_synthetic_cli_run_keeps_missing_published_risk_unavailable(tmp_path):
    args = _synthetic_run_inputs(tmp_path, missing_risk=True)

    qa = run(args)

    assert qa["geometry"]["counts"]["exact_unique_matches"] == 1
    assert qa["matched_c0_c1_vt_buildings"] == 1
    assert qa["matched_records_with_valid_risk_insar"] == 0
    assert qa["paired_beta_and_risk_insar_count"] == 0
    assert qa["ward_comparison"]["spearman_score_vs_mean_risk_insar"] is None


def test_geoparquet_crs_must_be_wgs84(tmp_path):
    path = tmp_path / "wrong-crs.parquet"
    _write_geo_parquet(
        path,
        {
            "bldg_id": pa.array(["b-1"]),
            "geometry": pa.array([to_wkb(box(0, 0, 1, 1))], type=pa.binary()),
        },
        crs_code=32643,
    )
    with pytest.raises(D5Error, match="EPSG:4326"):
        _check_geo_metadata(path, require_risk_fields=False)


def test_geoparquet_non_polygonal_metadata_is_rejected(tmp_path):
    path = tmp_path / "point.parquet"
    _write_geo_parquet(
        path,
        {"bldg_id": pa.array(["b-1"]), "geometry": pa.array([b"point"], type=pa.binary())},
        geometry_types=["Point"],
    )
    with pytest.raises(D5Error, match="polygonal"):
        _check_geo_metadata(path, require_risk_fields=False)
