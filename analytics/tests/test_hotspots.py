import csv
import hashlib
import json
from argparse import Namespace

import pytest
from shapely.geometry import box, mapping

from analytics.export import build_validation_summary
from analytics.hotspots import (
    C3_HOTSPOT_KEYS,
    D7Error,
    _assign_hotspot,
    _load_hotspots,
    _load_rankings,
    _load_sensitivity,
    _priority_band,
    _record_c3,
    run,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(tmp_path):
    wards_path = tmp_path / "wards.geojson"
    features = []
    for index in range(250):
        x = index * 3
        features.append(
            {
                "type": "Feature",
                "properties": {"ward_id": str(index + 1), "ward_name": f"Ward {index + 1}"},
                "geometry": mapping(box(x, 0, x + 1, 1)),
            }
        )
    _write_json(wards_path, {"type": "FeatureCollection", "features": features})

    config = tmp_path / "delhi.yaml"
    config.write_text(
        "contract: C6@1.0\ncity: delhi\ndisplay_name: Delhi\nutm_epsg: 32643\n"
        "bbox: [76.84, 28.40, 77.35, 28.89]\nseed: 42\n"
        "paths: {pack_dir: data/pack, out_dir: out/delhi}\n"
        "params: {coverage_min: 0.5}\n"
        "weights: {i1: 0.3, i2: 0.35, i3: 0.2, i4: 0.15}\nmode: public\n",
        encoding="utf-8",
    )

    d3_path = tmp_path / "ward_index.csv"
    d3_rows = []
    for index in range(250):
        ranked = index < 245
        d3_rows.append(
            {
                "ward_id": str(index + 1),
                "ward_name": f"Ward {index + 1}",
                "status": "ranked" if ranked else "insufficient_data",
                "n_buildings": 10,
                "n_buildings_with_data": 8 if ranked else 1,
                "coverage_pct": 80 if ranked else 10,
                "score": 100 - index * 99 / 244 if ranked else "",
                "rank": index + 1 if ranked else "",
                "flags": "[]" if ranked else '["low_coverage"]',
            }
        )
    d3_fields = list(d3_rows[0])
    _write_csv(d3_path, d3_fields, d3_rows)

    d4_path = tmp_path / "ward_sensitivity.csv"
    d4_rows = []
    for index in range(250):
        ranked = index < 245
        rank = index + 1 if ranked else ""
        d4_rows.append(
            {
                "ward_id": str(index + 1),
                "rank": rank,
                "rank_p05": max(1, index) if ranked else "",
                "rank_p95": min(245, index + 2) if ranked else "",
            }
        )
    _write_csv(d4_path, list(d4_rows[0]), d4_rows)

    pack_path = tmp_path / "PACK_MANIFEST.json"
    _write_json(
        pack_path,
        {
            "contract": "C0@1.0",
            "files": [{"name": wards_path.name, "sha256": _sha(wards_path), "rows": 250}],
        },
    )
    d3_qa_path = tmp_path / "d3_qa.json"
    _write_json(
        d3_qa_path,
        {
            "ward": {
                "output": {"sha256": _sha(d3_path)},
                "inputs": {str(config): {"sha256": _sha(config)}},
            }
        },
    )
    d4_qa_path = tmp_path / "d4_qa.json"
    _write_json(
        d4_qa_path,
        {
            "c3_pair_window_selected": "80–120 m",
            "outputs": {str(d4_path): {"sha256": _sha(d4_path)}},
            "inputs": {"d3_ward_index": {"path": str(d3_path), "sha256": _sha(d3_path)}},
        },
    )
    integration_path = tmp_path / "integration_manifest.json"
    _write_json(
        integration_path,
        {"c1_candidate": {"c6_reference_config_sha256": _sha(config)}},
    )
    return Namespace(
        wards=wards_path,
        pack_manifest=pack_path,
        d3_ward_index=d3_path,
        d3_qa=d3_qa_path,
        d4_sensitivity=d4_path,
        d4_qa=d4_qa_path,
        config=config,
        integration_manifest=integration_path,
        hotspots_json=None,
        preliminary_json=None,
        output_dir=tmp_path / "d7",
        overwrite=False,
    )


def _hotspot(identifier="h1", lon=0.5, lat=0.5, **extra):
    return {
        "hotspot_id": identifier,
        "name": identifier,
        "source": "Study 2025",
        "source_url": "https://example.org/study",
        "coordinate_status": "approximate_locality_reference",
        "coordinate_source": "Synthetic test point",
        "latitude": lat,
        "longitude": lon,
        **extra,
    }


def test_valid_hotspot_in_ranked_ward_emits_frozen_c3_fragment(tmp_path):
    args = _inputs(tmp_path)
    args.hotspots_json = tmp_path / "hotspots.json"
    _write_json(args.hotspots_json, [_hotspot()])

    report = run(args)

    fragment = json.loads((args.output_dir / "hotspots.json").read_text(encoding="utf-8"))
    assert fragment == [
        {"name": "h1", "source": "Study 2025", "ward_id": "1", "rank": 1, "percentile": 100.0}
    ]
    assert set(fragment[0]) == C3_HOTSPOT_KEYS
    payload = build_validation_summary({"hotspot_check": fragment}, "2026-11-24T00:00:00Z")
    assert payload["hotspot_check"] == fragment
    assert report["denominators"]["included_in_rank_comparison"] == 1


def test_hotspot_in_unranked_ward_is_retained_without_rank(tmp_path):
    args = _inputs(tmp_path)
    wards = json.loads(args.wards.read_text(encoding="utf-8"))
    wards["features"][0]["geometry"] = mapping(box(100, 0, 101, 1))
    wards["features"][245]["geometry"] = mapping(box(0, 0, 1, 1))
    _write_json(args.wards, wards)
    _write_json(
        args.pack_manifest,
        {
            "contract": "C0@1.0",
            "files": [{"name": args.wards.name, "sha256": _sha(args.wards), "rows": 250}],
        },
    )
    args.hotspots_json = tmp_path / "hotspots.json"
    _write_json(args.hotspots_json, [_hotspot(lon=0.5)])

    run(args)

    row = next(csv.DictReader((args.output_dir / "hotspot_comparison.csv").open(encoding="utf-8")))
    assert row["assignment_status"] == "assigned_to_unranked_ward"
    assert row["ward_id"] == "246"
    assert row["rank"] == ""
    assert row["priority_band"] == "unranked"


def test_outside_coverage_is_not_nearest_assigned():
    wards = [{"ward_id": "1", "ward_name": "one", "geometry": box(0, 0, 1, 1)}]
    result = _assign_hotspot(_hotspot(lon=5, lat=5), wards)
    assert result["assignment_status"] == "outside_supplied_ward_coverage"
    assert result["ward_id"] is None


def test_missing_coordinates_remain_unassigned():
    wards = [{"ward_id": "1", "ward_name": "one", "geometry": box(0, 0, 1, 1)}]
    result = _assign_hotspot(_hotspot(lon=None, lat=None), wards)
    assert result["assignment_status"] == "missing_coordinates"
    assert result["ward_id"] is None


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181), (float("nan"), 0)])
def test_invalid_coordinates_rejected(tmp_path, lat, lon):
    path = tmp_path / "hotspots.json"
    _write_json(path, [_hotspot(lon=lon, lat=lat)])
    with pytest.raises(D7Error):
        _load_hotspots(path)


def test_point_on_ward_boundary_is_not_assigned():
    wards = [{"ward_id": "1", "ward_name": "one", "geometry": box(0, 0, 1, 1)}]
    result = _assign_hotspot(_hotspot(lon=0, lat=0.5), wards)
    assert result["assignment_status"] == "on_ward_boundary"


def test_overlapping_ward_intersections_are_ambiguous():
    wards = [
        {"ward_id": "1", "ward_name": "one", "geometry": box(0, 0, 1, 1)},
        {"ward_id": "2", "ward_name": "two", "geometry": box(0.25, 0, 1.25, 1)},
    ]
    result = _assign_hotspot(_hotspot(), wards)
    assert result["assignment_status"] == "ambiguous_multiple_wards"
    assert result["intersecting_ward_ids"] == ["1", "2"]
    assert result["ward_id"] is None


def test_approximate_coordinate_source_is_preserved(tmp_path):
    path = tmp_path / "hotspots.json"
    record = _hotspot(coordinate_uncertainty="Locality only")
    _write_json(path, [record])
    loaded = _load_hotspots(path)
    assert loaded[0]["coordinate_status"] == "approximate_locality_reference"
    assert loaded[0]["coordinate_uncertainty"] == "Locality only"


def test_missing_literature_provenance_rejected(tmp_path):
    path = tmp_path / "hotspots.json"
    record = _hotspot()
    record["source_url"] = ""
    _write_json(path, [record])
    with pytest.raises(D7Error, match="citation"):
        _load_hotspots(path)


def test_duplicate_hotspot_identifiers_rejected(tmp_path):
    path = tmp_path / "hotspots.json"
    _write_json(path, [_hotspot(), _hotspot()])
    with pytest.raises(D7Error, match="unique"):
        _load_hotspots(path)


def test_multiple_hotspots_assigned_to_same_ward_are_counted_as_records_and_unique_wards(tmp_path):
    args = _inputs(tmp_path)
    args.hotspots_json = tmp_path / "hotspots.json"
    _write_json(args.hotspots_json, [_hotspot("one"), _hotspot("two")])

    report = run(args)

    counts = report["denominators"]
    assert counts["included_in_rank_comparison"] == 2
    assert counts["unique_assigned_wards"] == 1
    assert counts["hotspot_records_per_priority_band"]["top_10_percent"] == 2
    assert counts["unique_wards_per_priority_band"]["top_10_percent"] == 1


def test_duplicate_ward_ids_rejected(tmp_path):
    args = _inputs(tmp_path)
    rows = list(csv.DictReader(args.d3_ward_index.open(encoding="utf-8")))
    rows[1]["ward_id"] = rows[0]["ward_id"]
    _write_csv(args.d3_ward_index, list(rows[0]), rows)
    with pytest.raises(D7Error, match="unique"):
        _load_rankings(args.d3_ward_index, {"params": {"coverage_min": 0.5}})


@pytest.mark.parametrize("mutation", ["duplicate", "gap"])
def test_duplicate_or_noncontiguous_ranks_rejected(tmp_path, mutation):
    args = _inputs(tmp_path)
    rows = list(csv.DictReader(args.d3_ward_index.open(encoding="utf-8")))
    rows[1]["rank"] = rows[0]["rank"] if mutation == "duplicate" else "3"
    _write_csv(args.d3_ward_index, list(rows[0]), rows)
    with pytest.raises(D7Error):
        _load_rankings(args.d3_ward_index, {"params": {"coverage_min": 0.5}})


def test_d4_ranges_must_bracket_finalized_d3_ranks(tmp_path):
    args = _inputs(tmp_path)
    rankings, _ = _load_rankings(args.d3_ward_index, {"params": {"coverage_min": 0.5}})
    rows = list(csv.DictReader(args.d4_sensitivity.open(encoding="utf-8")))
    rows[0]["rank_p05"] = "2"
    _write_csv(args.d4_sensitivity, list(rows[0]), rows)
    with pytest.raises(D7Error, match="bracket"):
        _load_sensitivity(args.d4_sensitivity, rankings)


def test_rank_priority_bands_are_explicit_ceil_based_convention():
    assert _priority_band(1, 245, assigned=True) == "top_10_percent"
    assert _priority_band(25, 245, assigned=True) == "top_10_percent"
    assert _priority_band(26, 245, assigned=True) == "ranks_11_to_top_25_percent"
    assert _priority_band(62, 245, assigned=True) == "ranks_11_to_top_25_percent"
    assert _priority_band(63, 245, assigned=True) == "remaining_ranked"
    assert _priority_band(None, 245, assigned=True) == "unranked"
    assert _priority_band(None, 245, assigned=False) == "not_comparable"


def test_missing_rank_and_uncertainty_are_preserved_in_c3_record():
    record = _hotspot()
    assignment = {"ward_id": "246"}
    ward = {"rank_value": None}
    c3 = _record_c3(record, assignment, ward, {"rank_p05": None, "rank_p95": None}, 245)
    assert c3 == {
        "name": "h1",
        "source": "Study 2025",
        "ward_id": "246",
        "rank": None,
        "percentile": None,
    }


def test_output_overwrite_protection(tmp_path):
    args = _inputs(tmp_path)
    args.hotspots_json = tmp_path / "hotspots.json"
    _write_json(args.hotspots_json, [_hotspot()])
    run(args)
    with pytest.raises(D7Error, match="--overwrite"):
        run(args)


def test_input_provenance_and_qa_hashes_are_recorded(tmp_path):
    args = _inputs(tmp_path)
    args.hotspots_json = tmp_path / "hotspots.json"
    _write_json(args.hotspots_json, [_hotspot()])
    report = run(args)
    assert report["inputs"]["d3_ward_index"]["sha256"] == _sha(args.d3_ward_index)
    assert report["outputs"]["hotspots.json"]["sha256"] == _sha(args.output_dir / "hotspots.json")
    qa_hash = report["outputs"]["d7_qa.json"]["sha256"]
    assert len(qa_hash) == 64


def test_preliminary_results_are_compared_without_replacing_final_d3_ranks(tmp_path):
    args = _inputs(tmp_path)
    args.hotspots_json = tmp_path / "hotspots.json"
    _write_json(args.hotspots_json, [_hotspot("Bijwasan"), _hotspot("Kapashera", lon=3.5)])
    args.preliminary_json = tmp_path / "preliminary.json"
    _write_json(
        args.preliminary_json,
        {
            "ranking_method": "temporary score tie ordering",
            "hotspot_results": [
                {
                    "hotspot": "Bijwasan",
                    "comparison_status": "compared",
                    "matched_ward_id": "1",
                    "our_rank": 2,
                },
                {
                    "hotspot": "Kapashera",
                    "comparison_status": "compared",
                    "matched_ward_id": "2",
                    "our_rank": 5,
                },
            ],
        },
    )

    report = run(args)

    compared = report["preliminary_comparison"]["records"]
    assert [row["rank_change_final_minus_preliminary"] for row in compared] == [-1, -3]
    assert [row["final_rank"] for row in compared] == [1, 2]
    assert [row["preliminary_priority_band"] for row in compared] == [
        "top_10_percent",
        "top_10_percent",
    ]
    assert [row["final_priority_band"] for row in compared] == [
        "top_10_percent",
        "top_10_percent",
    ]
