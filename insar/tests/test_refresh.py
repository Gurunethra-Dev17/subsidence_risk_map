from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from insar.refresh import (
    DiscoveryError,
    build_document,
    discover,
    main,
    normalize_result,
    parse_bbox,
    parse_iso_date,
    parse_max_pairs,
    parse_max_results,
    parse_output_path,
    shortlist_pairs,
)


def test_bbox_validation():
    assert parse_bbox("76.8,28.4,77.3,28.9") == (76.8, 28.4, 77.3, 28.9)
    for value in (
        "76,28,77",
        "76,28,77,NaN",
        "181,28,182,29",
        "76,-91,77,-90",
        "77,28,76,29",
    ):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_bbox(value)


def test_date_and_result_limit_validation():
    assert parse_iso_date("2025-02-03") == date(2025, 2, 3)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_iso_date("2025-02-30")
    assert parse_max_results("250") == 250
    for value in ("0", "251", "many"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_max_results(value)
    assert parse_max_pairs("100") == 100
    for value in ("0", "1001", "many"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_max_pairs(value)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_output_path("")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_output_path("results.txt")


def test_normalize_result_preserves_missing_fields_and_available_burst_fields():
    result = normalize_result(
        {
            "properties": {
                "sceneName": "S1A_SYNTHETIC_SCENE",
                "fileID": "S1A_SYNTHETIC_GRANULE",
                "startTime": "2025-01-02T03:04:05Z",
                "platform": "Sentinel-1A",
                "flightDirection": "DESCENDING",
                "relativeOrbit": 42,
                "processingLevel": "SLC",
                "fullBurstID": "synthetic-burst-id",
            },
            "geometry": {"type": "Point", "coordinates": [77.0, 28.6]},
        }
    )
    assert result["scene_id"] == "S1A_SYNTHETIC_SCENE"
    assert result["granule_id"] == "S1A_SYNTHETIC_GRANULE"
    assert result["relative_orbit"] == 42
    assert result["geometry"]["type"] == "Point"
    assert result["burst_fields"] == {"fullBurstID": "synthetic-burst-id"}

    missing = normalize_result({"properties": {}})
    assert missing["scene_id"] is None
    assert missing["granule_id"] is None
    assert missing["acquisition_time"] is None
    assert missing["geometry"] is None
    assert missing["burst_fields"] == {}


def test_normalize_asf_product_shaped_object():
    product = SimpleNamespace(
        properties={
            "sceneName": "synthetic-scene",
            "startTime": "2025-01-02T03:04:05.123Z",
            "platform": "Sentinel-1A",
            "pathNumber": 42,
            "orbit": 1024,
            "polarization": "VV",
            "beamModeType": "IW",
            "groupID": "synthetic-group",
            "processingLevel": "BURST",
            "flightDirection": None,
            "burst": {
                "absoluteBurstID": 123456,
                "relativeBurstID": 654321,
                "fullBurstID": "017_034465_IW2",
                "burstIndex": 7,
                "samplesPerBurst": 1500,
                "subswath": "IW2",
                "azimuthTime": "2025-01-02T03:04:05Z",
                "azimuthAnxTime": "12.5",
            },
        },
        geometry={"type": "Polygon", "coordinates": [[[76.0, 28.0], [77.0, 28.0]]]},
    )
    normalized = normalize_result(product)
    assert normalized["scene_id"] == "synthetic-scene"
    assert normalized["granule_id"] is None
    assert normalized["acquisition_time"] == "2025-01-02T03:04:05.123Z"
    assert normalized["platform"] == "Sentinel-1A"
    assert normalized["polarization"] == "VV"
    assert normalized["flight_direction"] is None
    assert normalized["relative_orbit"] == 42
    assert normalized["absolute_orbit"] == 1024
    assert normalized["beam_mode"] == "IW"
    assert normalized["group_id"] == "synthetic-group"
    assert normalized["processing_level"] == "BURST"
    assert normalized["geometry"]["type"] == "Polygon"
    assert normalized["burst_fields"] == product.properties["burst"]


def test_build_document_is_bounded_and_marks_candidates_not_products():
    fixed_time = datetime(2025, 1, 1, tzinfo=UTC)
    doc = build_document(
        bbox=(76.8, 28.4, 77.3, 28.9),
        start=date(2025, 1, 1),
        end=date(2025, 2, 1),
        max_results=1,
        products=[{"properties": {}}, {"properties": {"sceneName": "ignored"}}],
        generated_utc=fixed_time,
    )
    assert doc["generated_utc"] == "2025-01-01T00:00:00Z"
    assert doc["result_count"] == 1
    assert len(doc["results"]) == 1
    assert "not confirmed HyP3-compatible" in doc["note"]
    assert doc["query"]["start_utc"] == "2025-01-01T00:00:00Z"
    assert doc["query"]["end_utc_inclusive"] == "2025-02-01T23:59:59Z"


def test_discovery_calls_mock_asf_with_bounded_query_and_writes_json(tmp_path):
    output = tmp_path / "candidates.json"
    fake_client = SimpleNamespace(
        DATASET=SimpleNamespace(SLC_BURST="SLC-BURST"),
        geo_search=Mock(return_value=[{"properties": {"sceneName": "fixture-scene"}}]),
    )
    doc = discover(
        bbox=(76.8, 28.4, 77.3, 28.9),
        start=date(2025, 1, 1),
        end=date(2025, 1, 2),
        max_results=10,
        output=output,
        client=fake_client,
        generated_utc=datetime(2025, 1, 3, tzinfo=UTC),
    )
    fake_client.geo_search.assert_called_once_with(
        dataset="SLC-BURST",
        intersectsWith=("POLYGON((76.8 28.4,77.3 28.4,77.3 28.9,76.8 28.9,76.8 28.4))"),
        start="2025-01-01T00:00:00Z",
        end="2025-01-02T23:59:59Z",
        maxResults=10,
    )
    assert json.loads(output.read_text(encoding="utf-8")) == doc


def test_incomplete_asf_search_fails_without_writing_shortlist(tmp_path):
    class IncompleteResults(list):
        pass

    results = IncompleteResults([{"properties": {"sceneName": "partial-result"}}])
    results.raise_if_incomplete = Mock(side_effect=RuntimeError("incomplete search"))
    output = tmp_path / "incomplete.json"
    client = SimpleNamespace(
        DATASET=SimpleNamespace(SLC_BURST="SLC-BURST"),
        geo_search=Mock(return_value=results),
    )
    with pytest.raises(DiscoveryError, match="ASF catalog discovery failed"):
        discover(
            bbox=(76.8, 28.4, 77.3, 28.9),
            start=date(2025, 1, 1),
            end=date(2025, 1, 2),
            max_results=5,
            output=output,
            client=client,
        )
    assert not output.exists()
    results.raise_if_incomplete.assert_called_once_with()


def test_empty_search_writes_empty_result(tmp_path):
    fake_client = SimpleNamespace(
        DATASET=SimpleNamespace(SLC_BURST="SLC-BURST"), geo_search=Mock(return_value=[])
    )
    doc = discover(
        bbox=(76.8, 28.4, 77.3, 28.9),
        start=date(2025, 1, 1),
        end=date(2025, 1, 2),
        max_results=5,
        output=tmp_path / "empty.json",
        client=fake_client,
    )
    assert doc["results"] == []
    assert doc["result_count"] == 0


def test_output_refuses_overwrite_without_flag(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("keep", encoding="utf-8")
    fake_client = SimpleNamespace(
        DATASET=SimpleNamespace(SLC_BURST="SLC-BURST"), geo_search=Mock(return_value=[])
    )
    with pytest.raises(DiscoveryError, match="already exists"):
        discover(
            bbox=(76.8, 28.4, 77.3, 28.9),
            start=date(2025, 1, 1),
            end=date(2025, 1, 2),
            max_results=5,
            output=output,
            client=fake_client,
        )
    assert output.read_text(encoding="utf-8") == "keep"


def test_output_overwrite_requires_and_honors_explicit_flag(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("old content", encoding="utf-8")
    fake_client = SimpleNamespace(
        DATASET=SimpleNamespace(SLC_BURST="SLC-BURST"), geo_search=Mock(return_value=[])
    )
    discover(
        bbox=(76.8, 28.4, 77.3, 28.9),
        start=date(2025, 1, 1),
        end=date(2025, 1, 2),
        max_results=5,
        output=output,
        overwrite=True,
        client=fake_client,
    )
    assert json.loads(output.read_text(encoding="utf-8"))["results"] == []


def test_cli_validation_and_mocked_client(tmp_path, monkeypatch):
    fake_client = SimpleNamespace(
        DATASET=SimpleNamespace(SLC_BURST="SLC-BURST"), geo_search=Mock(return_value=[])
    )
    monkeypatch.setattr("insar.refresh._load_asf_search", lambda: fake_client)
    output = tmp_path / "cli.json"
    assert (
        main(
            [
                "discovery",
                "--bbox",
                "76.8,28.4,77.3,28.9",
                "--start",
                "2025-01-01",
                "--end",
                "2025-01-02",
                "--max-results",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.exists()
    with pytest.raises(SystemExit):
        main(
            [
                "discovery",
                "--bbox",
                "76.8,28.4,77.3,28.9",
                "--start",
                "2025-02-01",
                "--end",
                "2025-01-02",
                "--max-results",
                "2",
                "--output",
                str(tmp_path / "bad.json"),
            ]
        )


def _shortlist_record(
    *,
    scene_id,
    acquisition_time,
    full_burst_id="synthetic-full-burst",
    polarization="VV",
    relative_orbit=42,
    flight_direction="ASCENDING",
    beam_mode="IW",
    subswath="IW2",
):
    return {
        "scene_id": scene_id,
        "granule_id": scene_id,
        "acquisition_time": acquisition_time,
        "platform": "SENTINEL-1D",
        "polarization": polarization,
        "relative_orbit": relative_orbit,
        "flight_direction": flight_direction,
        "beam_mode": beam_mode,
        "processing_level": "BURST",
        "burst_fields": {"fullBurstID": full_burst_id, "subswath": subswath},
    }


def test_shortlist_pairs_reproduces_the_20_record_date_and_polarization_groups():
    patterns = (
        ("056011_IW2", "burst-056011", "ASCENDING", "IW2", (5, 17, 29)),
        ("056012_IW2", "burst-056012", "ASCENDING", "IW2", (5, 17, 29)),
        ("290875_IW1", "burst-290875", "DESCENDING", "IW1", (13, 25)),
        ("290876_IW1", "burst-290876", "DESCENDING", "IW1", (13, 25)),
    )
    records = []
    for name, burst_id, direction, subswath, days in patterns:
        for day in days:
            for polarization in ("VV", "VH"):
                records.append(
                    _shortlist_record(
                        scene_id=f"S1_{name}_202609{day:02d}T120000_{polarization}",
                        acquisition_time=f"2026-09-{day:02d}T12:00:00Z",
                        full_burst_id=burst_id,
                        polarization=polarization,
                        flight_direction=direction,
                        beam_mode="IW",
                        subswath=subswath,
                    )
                )

    result = shortlist_pairs(records)
    assert len(records) == 20
    assert len(result["candidate_pairs"]) == 16
    assert result["unresolved_records"] == []
    assert result["unpaired_records"] == []
    assert "unverified" in result["note"]
    for pair in result["candidate_pairs"]:
        assert (
            pair["reference"]["acquisition_time"][:10] != pair["secondary"]["acquisition_time"][:10]
        )
        assert pair["matching_metadata"]["polarization"] in {"VV", "VH"}
        assert pair["status"] == "shortlist_candidate_unverified"


def test_shortlist_does_not_infer_missing_burst_id_from_scene_name():
    records = [
        _shortlist_record(
            scene_id=f"S1_056012_IW2_202609{day:02d}T125448_VV",
            acquisition_time=f"2026-09-{day:02d}T12:54:49Z",
        )
        for day in (5, 17)
    ]
    for record in records:
        record["burst_fields"] = {"subswath": "IW2"}
    result = shortlist_pairs(records)
    assert result["candidate_pairs"] == []
    assert len(result["unresolved_records"]) == 2
    assert all(
        "missing_full_burst_id" in item["reason_codes"] for item in result["unresolved_records"]
    )


@pytest.mark.parametrize(
    "changed_field,changed_value",
    [
        ("polarization", "VH"),
        ("relative_orbit", 43),
        ("flight_direction", "DESCENDING"),
        ("beam_mode", "EW"),
    ],
)
def test_shortlist_requires_matching_acquisition_metadata(changed_field, changed_value):
    first = _shortlist_record(scene_id="first", acquisition_time="2026-09-05T12:00:00Z")
    second = _shortlist_record(scene_id="second", acquisition_time="2026-09-17T12:00:00Z")
    second[changed_field] = changed_value
    result = shortlist_pairs([first, second])
    assert result["candidate_pairs"] == []
    assert len(result["unpaired_records"]) == 2


def test_shortlist_marks_invalid_or_naive_times_unresolved():
    records = [
        _shortlist_record(scene_id="bad", acquisition_time="not-a-time"),
        _shortlist_record(scene_id="naive", acquisition_time="2026-09-05T12:00:00"),
    ]
    result = shortlist_pairs(records)
    assert result["candidate_pairs"] == []
    assert len(result["unresolved_records"]) == 2
    assert all(
        "missing_acquisition_time" in item["reason_codes"] for item in result["unresolved_records"]
    )


def _write_discovery_report(path, records):
    path.write_text(json.dumps({"results": records}), encoding="utf-8")


def test_pairs_cli_writes_valid_bounded_shortlist(tmp_path):
    source = tmp_path / "discovery.json"
    output = tmp_path / "pairs.json"
    _write_discovery_report(
        source,
        [
            _shortlist_record(scene_id="first", acquisition_time="2026-09-05T12:00:00Z"),
            _shortlist_record(scene_id="second", acquisition_time="2026-09-17T12:00:00Z"),
        ],
    )

    assert main(["pairs", "--input", str(source), "--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["source_input"] == str(source)
    assert report["pair_count"] == 1
    assert report["candidate_pairs"][0]["status"] == "shortlist_candidate_unverified"
    assert "NOT confirmed HyP3-compatible" in report["warning"]
    assert report["unresolved_records"] == []


@pytest.mark.parametrize("content", ["not json", "[]", '{"results": null}', '{"results": [null]}'])
def test_pairs_cli_rejects_malformed_input(tmp_path, content, capsys):
    source = tmp_path / "bad.json"
    source.write_text(content, encoding="utf-8")
    output = tmp_path / "pairs.json"

    assert main(["pairs", "--input", str(source), "--output", str(output)]) == 2
    assert not output.exists()
    assert "pairs error:" in capsys.readouterr().err


def test_pairs_cli_writes_empty_shortlist_when_no_pairs_are_eligible(tmp_path):
    source = tmp_path / "discovery.json"
    output = tmp_path / "pairs.json"
    _write_discovery_report(
        source,
        [_shortlist_record(scene_id="single", acquisition_time="2026-09-05T12:00:00Z")],
    )

    assert main(["pairs", "--input", str(source), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["pair_count"] == 0
    assert report["candidate_pairs"] == []
    assert len(report["unpaired_records"]) == 1


def test_pairs_cli_reports_unresolved_metadata(tmp_path):
    source = tmp_path / "discovery.json"
    output = tmp_path / "pairs.json"
    unresolved = _shortlist_record(
        scene_id="missing-burst", acquisition_time="2026-09-05T12:00:00Z"
    )
    unresolved["burst_fields"] = {"subswath": "IW2"}
    _write_discovery_report(source, [unresolved])

    assert main(["pairs", "--input", str(source), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["pair_count"] == 0
    assert report["unresolved_records"][0]["reason_codes"] == ["missing_full_burst_id"]


def test_pairs_cli_preserves_existing_output_without_overwrite(tmp_path, capsys):
    source = tmp_path / "discovery.json"
    output = tmp_path / "pairs.json"
    _write_discovery_report(source, [])
    output.write_text("keep", encoding="utf-8")

    assert main(["pairs", "--input", str(source), "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == "keep"
    assert "already exists" in capsys.readouterr().err


def _candidate_pair(
    *, reference_id, secondary_id, separation, polarization="VV", full_burst_id="burst-1"
):
    reference_time = datetime(2026, 9, 5, 12, tzinfo=UTC)
    secondary_time = reference_time + timedelta(days=separation)
    return {
        "status": "shortlist_candidate_unverified",
        "reference": {
            "scene_id": reference_id,
            "acquisition_time": reference_time.isoformat().replace("+00:00", "Z"),
        },
        "secondary": {
            "scene_id": secondary_id,
            "acquisition_time": secondary_time.isoformat().replace("+00:00", "Z"),
        },
        "temporal_separation_days": separation,
        "matching_metadata": {
            "full_burst_id": full_burst_id,
            "polarization": polarization,
            "relative_orbit": 42,
            "flight_direction": "ASCENDING",
        },
    }


def _write_pair_report(path, candidates):
    path.write_text(
        json.dumps(
            {
                "pair_count": len(candidates),
                "candidate_pairs": candidates,
                "unresolved_records": [],
                "unpaired_records": [],
                "source_input": "discovery.json",
                "warning": "NOT confirmed HyP3-compatible pairs; metadata shortlist only.",
            }
        ),
        encoding="utf-8",
    )


def test_dry_run_cli_selects_shortest_vv_pair_with_stable_tie_break(tmp_path):
    source = tmp_path / "pairs.json"
    output = tmp_path / "manifest.json"
    _write_pair_report(
        source,
        [
            _candidate_pair(reference_id="z-ref", secondary_id="z-sec", separation=12),
            _candidate_pair(reference_id="b-ref", secondary_id="b-sec", separation=6),
            _candidate_pair(reference_id="a-ref", secondary_id="a-sec", separation=6),
            _candidate_pair(
                reference_id="vh-ref", secondary_id="vh-sec", separation=1, polarization="VH"
            ),
        ],
    )

    assert main(["dry-run", "--input", str(source), "--output", str(output)]) == 0

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["reference_scene_id"] == "a-ref"
    assert manifest["secondary_scene_id"] == "a-sec"
    assert manifest["temporal_separation_days"] == 6
    assert manifest["full_burst_id"] == "burst-1"
    assert manifest["polarization"] == "VV"
    assert manifest["relative_orbit"] == 42
    assert manifest["flight_direction"] == "ASCENDING"
    assert manifest["processing_status"] == "not_submitted"
    assert manifest["hyp3_eligibility"] == "unverified"
    assert manifest["displacement_product"] == "not_available"
    assert "not processed InSAR measurements" in manifest["data_provenance"]
    assert manifest["source_pair_report"] == str(source)


@pytest.mark.parametrize(
    "candidates,reported_count",
    [
        ([{"status": "bad"}], 1),
        (
            [
                {
                    **_candidate_pair(reference_id="bad", secondary_id="sec", separation=2),
                    "temporal_separation_days": float("nan"),
                }
            ],
            1,
        ),
        ([_candidate_pair(reference_id="ref", secondary_id="sec", separation=2)], 0),
    ],
)
def test_dry_run_cli_rejects_malformed_pair_report(tmp_path, candidates, reported_count, capsys):
    source = tmp_path / "bad-pairs.json"
    output = tmp_path / "manifest.json"
    source.write_text(
        json.dumps(
            {
                "pair_count": reported_count,
                "candidate_pairs": candidates,
                "unresolved_records": [],
            }
        ),
        encoding="utf-8",
    )

    assert main(["dry-run", "--input", str(source), "--output", str(output)]) == 2
    assert not output.exists()
    assert "dry-run error:" in capsys.readouterr().err


def test_dry_run_cli_fails_when_no_vv_pair_is_available(tmp_path, capsys):
    source = tmp_path / "pairs.json"
    output = tmp_path / "manifest.json"
    _write_pair_report(
        source,
        [
            _candidate_pair(
                reference_id="vh-ref", secondary_id="vh-sec", separation=12, polarization="VH"
            )
        ],
    )

    assert main(["dry-run", "--input", str(source), "--output", str(output)]) == 2
    assert not output.exists()
    assert "no eligible VV candidates" in capsys.readouterr().err


def test_dry_run_cli_preserves_existing_output_without_overwrite(tmp_path, capsys):
    source = tmp_path / "pairs.json"
    output = tmp_path / "manifest.json"
    _write_pair_report(
        source, [_candidate_pair(reference_id="ref", secondary_id="sec", separation=12)]
    )
    output.write_text("keep", encoding="utf-8")

    assert main(["dry-run", "--input", str(source), "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == "keep"
    assert "already exists" in capsys.readouterr().err
