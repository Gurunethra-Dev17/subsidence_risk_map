"""Compare literature hotspot reference points with finalized D3 ward ranks.

The built-in coordinates are approximate locality/city references retained from the original D7
prototype. They are not hotspot polygons, exact coordinates published by the papers, or ground
truth. Spatial assignment never repairs coordinates or chooses a nearest ward.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from shapely.geometry import Point, shape


class D7Error(ValueError):
    """Invalid D7 input or output operation."""


HOTSPOTS: list[dict[str, Any]] = [
    {
        "hotspot_id": "vt-2025-bijwasan",
        "name": "Bijwasan",
        "latitude": 28.5363,
        "longitude": 77.0567,
        "coordinate_status": "approximate_locality_reference",
        "coordinate_source": "Legacy D7 code constant; derivation not recorded",
        "coordinate_uncertainty": "Locality reference; not a published hotspot centroid or site coordinate.",
        "literature_title": "Building damage risk in sinking Indian megacities",
        "authors": "Nitheshnirmal Sadhasivam; Leonard Ohenhen; Mohammad Khorrami; Susanna Werth; Manoochehr Shirzaei",
        "publication_year": 2025,
        "source": "Nature Sustainability 2025",
        "source_url": "https://doi.org/10.1038/s41893-025-01663-0",
        "doi": "10.1038/s41893-025-01663-0",
        "source_location_detail": "The article reports Bijwasan among its Delhi-NCR hotspots (Fig. 2a); the stored point is an approximate locality reference, not a point published by the article.",
        "observation_period": "Sentinel-1 observations 2015–2023",
        "deformation_magnitude": "Up to 28.5 mm/year in affected Bijwasan area (reported by the study; not measured at the stored reference point).",
    },
    {
        "hotspot_id": "vt-2025-faridabad",
        "name": "Faridabad",
        "latitude": 28.4089,
        "longitude": 77.3178,
        "coordinate_status": "approximate_city_reference",
        "coordinate_source": "Legacy D7 code constant; derivation not recorded",
        "coordinate_uncertainty": "City reference; not a published hotspot centroid or site coordinate.",
        "literature_title": "Building damage risk in sinking Indian megacities",
        "authors": "Nitheshnirmal Sadhasivam; Leonard Ohenhen; Mohammad Khorrami; Susanna Werth; Manoochehr Shirzaei",
        "publication_year": 2025,
        "source": "Nature Sustainability 2025",
        "source_url": "https://doi.org/10.1038/s41893-025-01663-0",
        "doi": "10.1038/s41893-025-01663-0",
        "source_location_detail": "The article reports Faridabad among its Delhi-NCR hotspots (Fig. 2a); the stored point is an approximate city reference, not a point published by the article.",
        "observation_period": "Sentinel-1 observations 2015–2023",
        "deformation_magnitude": "Up to 38.2 mm/year in affected Faridabad area (reported by the study; not measured at the stored reference point).",
    },
    {
        "hotspot_id": "vt-2025-ghaziabad",
        "name": "Ghaziabad",
        "latitude": 28.6692,
        "longitude": 77.4538,
        "coordinate_status": "approximate_city_reference",
        "coordinate_source": "Legacy D7 code constant; derivation not recorded",
        "coordinate_uncertainty": "City reference; not a published hotspot centroid or site coordinate.",
        "literature_title": "Building damage risk in sinking Indian megacities",
        "authors": "Nitheshnirmal Sadhasivam; Leonard Ohenhen; Mohammad Khorrami; Susanna Werth; Manoochehr Shirzaei",
        "publication_year": 2025,
        "source": "Nature Sustainability 2025",
        "source_url": "https://doi.org/10.1038/s41893-025-01663-0",
        "doi": "10.1038/s41893-025-01663-0",
        "source_location_detail": "The article reports Ghaziabad among its Delhi-NCR hotspots (Fig. 2a); the stored point is an approximate city reference, not a point published by the article.",
        "observation_period": "Sentinel-1 observations 2015–2023",
        "deformation_magnitude": "Up to 20.7 mm/year in affected Ghaziabad area (reported by the study; not measured at the stored reference point).",
    },
    {
        "hotspot_id": "garg-2022-kapashera",
        "name": "Kapashera",
        "latitude": 28.5285,
        "longitude": 77.0860,
        "coordinate_status": "approximate_locality_reference",
        "coordinate_source": "Legacy D7 code constant; derivation not recorded",
        "coordinate_uncertainty": "Locality reference; not a published hotspot centroid or site coordinate.",
        "literature_title": "Tracking hidden crisis in India's capital from space: implications of unsustainable groundwater use",
        "authors": "Shagun Garg; Mahdi Motagh; J. Indu; Vamshi Karanam",
        "publication_year": 2022,
        "source": "Garg et al. 2022 (Scientific Reports)",
        "source_url": "https://doi.org/10.1038/s41598-021-04193-9",
        "doi": "10.1038/s41598-021-04193-9",
        "source_location_detail": "The study reports Kapashera as a subsidence feature and shows ascending/descending LOS plots (Fig. 1d); exact point derivation is undocumented.",
        "observation_period": "Sentinel-1 data 2014–2020; long-term series reported through 2019",
        "deformation_magnitude": "More than 11 cm/year reported for Kapashera; maximum exceeded 17 cm/year during 2018–2019. Neither value is measured at the stored reference point.",
    },
]

OUTPUT_NAMES = ("hotspots.json", "hotspot_comparison.csv", "d7_qa.json")
C3_HOTSPOT_KEYS = {"name", "source", "ward_id", "rank", "percentile"}
CSV_FIELDS = [
    "hotspot_id",
    "name",
    "literature_title",
    "authors",
    "publication_year",
    "doi",
    "source_url",
    "source_location_detail",
    "observation_period",
    "deformation_magnitude",
    "latitude",
    "longitude",
    "coordinate_status",
    "coordinate_source",
    "coordinate_uncertainty",
    "assignment_status",
    "intersecting_ward_ids",
    "ward_id",
    "ward_name",
    "inspection_score",
    "rank",
    "rank_percentile",
    "rank_p05",
    "rank_p95",
    "priority_band",
    "coverage_pct",
    "eligibility_flags",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise D7Error(f"Cannot read JSON input: {path}") from exc


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise D7Error(f"CSV is missing required fields: {path}")
            return list(reader)
    except OSError as exc:
        raise D7Error(f"Cannot read CSV input: {path}") from exc


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise D7Error(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise D7Error(f"{label} must be finite")
    return result


def _verify_provenance(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, str]:
    pack = _read_json(args.pack_manifest)
    integration = _read_json(args.integration_manifest)
    d3qa = _read_json(args.d3_qa)
    d4qa = _read_json(args.d4_qa)
    if not isinstance(pack, dict) or pack.get("contract") != "C0@1.0":
        raise D7Error("C0 manifest must declare C0@1.0")
    if not isinstance(integration, dict):
        raise D7Error("Integration manifest must be an object")
    entries = pack.get("files")
    if not isinstance(entries, list):
        raise D7Error("C0 manifest files must be an array")
    by_name = {entry.get("name"): entry for entry in entries if isinstance(entry, dict)}
    ward_entry = by_name.get(args.wards.name)
    if ward_entry is None or ward_entry.get("sha256") != _sha256(args.wards):
        raise D7Error("Ward geometry checksum does not match C0 manifest")
    if ward_entry.get("rows") != 250:
        raise D7Error("C0 manifest must declare 250 ward features")

    c6_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    staged_config_hash = (
        integration.get("c1_candidate", {}).get("c6_reference_config_sha256")
        if isinstance(integration.get("c1_candidate"), dict)
        else None
    )
    if c6_hash != staged_config_hash or config.get("contract") != "C6@1.0":
        raise D7Error("C6 configuration does not match staged integration provenance")
    config_schema = _read_json(Path("contracts/schemas/config.schema.json"))
    try:
        jsonschema.validate(config, config_schema)
    except jsonschema.ValidationError as exc:
        raise D7Error("C6 configuration does not satisfy its frozen schema") from exc
    if config.get("city") != "delhi":
        raise D7Error("D7 requires the staged Delhi configuration")

    ward_hash = _sha256(args.d3_ward_index)
    ward_output = d3qa.get("ward", {}).get("output", {}) if isinstance(d3qa, dict) else {}
    if ward_output.get("sha256") != ward_hash:
        raise D7Error("D3 QA does not authenticate the selected finalized ward index")
    d3_config = d3qa.get("ward", {}).get("inputs", {})
    if not isinstance(d3_config, dict) or not any(
        Path(name).name == args.config.name and value.get("sha256") == c6_hash
        for name, value in d3_config.items()
        if isinstance(name, str) and isinstance(value, dict)
    ):
        raise D7Error("D3 QA does not authenticate the selected C6 configuration")

    sensitivity_hash = _sha256(args.d4_sensitivity)
    d4_outputs = d4qa.get("outputs", {}) if isinstance(d4qa, dict) else {}
    if not isinstance(d4_outputs, dict) or not any(
        Path(name).name == args.d4_sensitivity.name and value.get("sha256") == sensitivity_hash
        for name, value in d4_outputs.items()
        if isinstance(name, str) and isinstance(value, dict)
    ):
        raise D7Error("D4 QA does not authenticate the selected sensitivity output")
    d4_inputs = d4qa.get("inputs", {})
    if not isinstance(d4_inputs, dict) or not any(
        Path(value.get("path", name)).name == args.d3_ward_index.name
        and value.get("sha256") == ward_hash
        for name, value in d4_inputs.items()
        if isinstance(name, str) and isinstance(value, dict)
    ):
        raise D7Error("D4 QA does not authenticate the selected finalized D3 index")
    if d4qa.get("c3_pair_window_selected") != "80–120 m":
        raise D7Error("D4 QA does not identify the selected 80–120 m baseline")
    return {
        "wards": _sha256(args.wards),
        "pack_manifest": _sha256(args.pack_manifest),
        "d3_ward_index": ward_hash,
        "d3_qa": _sha256(args.d3_qa),
        "d4_sensitivity": sensitivity_hash,
        "d4_qa": _sha256(args.d4_qa),
        "config": c6_hash,
        "integration_manifest": _sha256(args.integration_manifest),
    }


def _load_wards(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise D7Error("Ward geometry must be a GeoJSON FeatureCollection (EPSG:4326)")
    features = payload.get("features")
    if not isinstance(features, list) or len(features) != 250:
        raise D7Error("Ward geometry must contain exactly 250 features")
    wards = []
    by_id: dict[str, dict[str, Any]] = {}
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict):
            raise D7Error("Every ward feature must have properties")
        ward_id = str(properties.get("ward_id", "")).strip()
        name = str(properties.get("ward_name", "")).strip()
        if not ward_id or not name or ward_id in by_id:
            raise D7Error("Ward IDs and names must be present and ward IDs unique")
        try:
            geometry = shape(feature.get("geometry"))
        except (TypeError, ValueError) as exc:
            raise D7Error(f"Invalid geometry for ward {ward_id}") from exc
        if (
            geometry.is_empty
            or not geometry.is_valid
            or geometry.geom_type
            not in {
                "Polygon",
                "MultiPolygon",
            }
        ):
            raise D7Error(f"Ward {ward_id} must have valid non-empty polygon geometry")
        row = {"ward_id": ward_id, "ward_name": name, "geometry": geometry}
        by_id[ward_id] = row
        wards.append(row)
    return wards, by_id


def _load_rankings(
    path: Path, config: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    required = {
        "ward_id",
        "ward_name",
        "status",
        "n_buildings",
        "n_buildings_with_data",
        "coverage_pct",
        "score",
        "rank",
        "flags",
    }
    rows = _read_csv(path, required)
    if len(rows) != 250:
        raise D7Error("Finalized D3 index must contain exactly 250 ward rows")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        ward_id = row["ward_id"].strip()
        if not ward_id or ward_id in by_id or row["status"] not in {"ranked", "insufficient_data"}:
            raise D7Error("D3 ward IDs/statuses must be valid and unique")
        try:
            try:
                flags = json.loads(row["flags"])
            except json.JSONDecodeError:
                flags = ast.literal_eval(row["flags"])
        except (TypeError, ValueError, SyntaxError) as exc:
            raise D7Error("D3 flags must be a serialized string array") from exc
        if not isinstance(flags, list) or any(not isinstance(value, str) for value in flags):
            raise D7Error("D3 flags must be a JSON array of strings")
        total = int(row["n_buildings"])
        with_data = int(row["n_buildings_with_data"])
        coverage = _finite(row["coverage_pct"], "D3 coverage_pct")
        if total < 0 or not 0 <= with_data <= total or not 0 <= coverage <= 100:
            raise D7Error("D3 building counts or coverage are invalid")
        expected_coverage = 100 * with_data / total if total else 0.0
        if abs(coverage - expected_coverage) > 0.11:
            raise D7Error("D3 coverage_pct disagrees with its building counts")
        rank_text = row["rank"].strip()
        score_text = row["score"].strip()
        ranked = row["status"] == "ranked"
        if ranked != bool(rank_text) or ranked != bool(score_text):
            raise D7Error("D3 ranked status must agree with rank and score availability")
        rank = int(rank_text) if rank_text else None
        score = _finite(score_text, "D3 score") if score_text else None
        if ranked and (rank < 1 or not 0 <= score <= 100 or coverage < _coverage_threshold(config)):
            raise D7Error("Ranked D3 ward violates score or coverage eligibility")
        if not ranked and (score is not None or rank is not None or "low_coverage" not in flags):
            raise D7Error("Insufficient-data ward must have null score/rank and low_coverage flag")
        by_id[ward_id] = {
            **row,
            "ward_id": ward_id,
            "flags_list": flags,
            "coverage": coverage,
            "score_value": score,
            "rank_value": rank,
        }
    ranked_rows = [row for row in by_id.values() if row["status"] == "ranked"]
    rank_values = sorted(row["rank_value"] for row in ranked_rows)
    if (
        len(ranked_rows) != 245
        or len(by_id) - len(ranked_rows) != 5
        or rank_values != list(range(1, 246))
    ):
        raise D7Error(
            "Finalized D3 must contain 245 contiguous ranked wards and five unranked wards"
        )
    score_order = sorted(ranked_rows, key=lambda row: (-row["score_value"], row["ward_id"]))
    if [row["rank_value"] for row in score_order] != list(range(1, 246)):
        raise D7Error("D3 rank ordering must be score descending, then ward_id ascending")
    return by_id, {"total": len(by_id), "ranked": len(ranked_rows), "unranked": 5}


def _coverage_threshold(config: dict[str, Any]) -> float:
    value = config.get("params", {}).get("coverage_min")
    threshold = _finite(value, "C6 params.coverage_min")
    if 0 < threshold <= 1:
        threshold *= 100
    if not 0 <= threshold <= 100:
        raise D7Error("C6 coverage_min must represent 0–100 percent")
    return threshold


def _load_sensitivity(
    path: Path, rankings: dict[str, dict[str, Any]]
) -> dict[str, dict[str, int | None]]:
    rows = _read_csv(path, {"ward_id", "rank", "rank_p05", "rank_p95"})
    result: dict[str, dict[str, int | None]] = {}
    for row in rows:
        ward_id = row["ward_id"].strip()
        if not ward_id or ward_id in result:
            raise D7Error("D4 ward IDs must be non-empty and unique")
        ranking = rankings.get(ward_id)
        if ranking is None:
            raise D7Error("D4 sensitivity ward IDs must match D3 ward IDs")
        if row["rank"].strip() != (
            "" if ranking["rank_value"] is None else str(ranking["rank_value"])
        ):
            raise D7Error("D4 baseline ranks do not match finalized D3 ranks")
        lo_text, hi_text = row["rank_p05"].strip(), row["rank_p95"].strip()
        if ranking["rank_value"] is None:
            if lo_text or hi_text:
                raise D7Error("Unranked D3 wards must have null D4 rank ranges")
            low = high = None
        else:
            if not lo_text or not hi_text:
                raise D7Error("Ranked D3 wards must have D4 sensitivity ranges")
            low, high = int(lo_text), int(hi_text)
            if not 1 <= low <= ranking["rank_value"] <= high <= 245:
                raise D7Error("D4 rank range must bracket the unchanged D3 rank")
        result[ward_id] = {"rank_p05": low, "rank_p95": high}
    if set(result) != set(rankings):
        raise D7Error("D4 sensitivity must contain the same 250 ward IDs as D3")
    return result


def _load_hotspots(path: Path | None) -> list[dict[str, Any]]:
    records = HOTSPOTS if path is None else _read_json(path)
    if not isinstance(records, list) or not records:
        raise D7Error("Hotspot input must be a non-empty JSON array")
    seen: set[str] = set()
    normalized = []
    required = {
        "hotspot_id",
        "name",
        "source",
        "source_url",
        "coordinate_status",
        "coordinate_source",
    }
    for source_record in records:
        if not isinstance(source_record, dict) or not required.issubset(source_record):
            raise D7Error("Each hotspot needs ID, name, citation, and coordinate provenance fields")
        record = dict(source_record)
        hotspot_id = str(record["hotspot_id"]).strip()
        if not hotspot_id or hotspot_id in seen:
            raise D7Error("Hotspot identifiers must be non-empty and unique")
        seen.add(hotspot_id)
        lon, lat = record.get("longitude"), record.get("latitude")
        if (lon is None) != (lat is None):
            raise D7Error(f"Hotspot {hotspot_id} must supply both coordinates or neither")
        if lon is not None:
            lon = _finite(lon, f"{hotspot_id}.longitude")
            lat = _finite(lat, f"{hotspot_id}.latitude")
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise D7Error(f"Hotspot {hotspot_id} coordinates are out of bounds")
        record["hotspot_id"] = hotspot_id
        record["name"] = str(record["name"]).strip()
        record["source"] = str(record["source"]).strip()
        record["source_url"] = str(record["source_url"]).strip()
        if not all((record["name"], record["source"], record["source_url"])):
            raise D7Error("Hotspot name and literature citation must be non-empty")
        record["longitude"], record["latitude"] = lon, lat
        normalized.append(record)
    return normalized


def _assign_hotspot(record: dict[str, Any], wards: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "assignment_status": "missing_coordinates",
        "intersecting_ward_ids": [],
        "ward_id": None,
        "ward_name": None,
    }
    if record["latitude"] is None:
        return result
    point = Point(record["longitude"], record["latitude"])
    intersecting = [ward for ward in wards if ward["geometry"].intersects(point)]
    strict = [ward for ward in intersecting if ward["geometry"].contains(point)]
    result["intersecting_ward_ids"] = sorted(ward["ward_id"] for ward in intersecting)
    if len(intersecting) > 1:
        result["assignment_status"] = "ambiguous_multiple_wards"
    elif not intersecting:
        result["assignment_status"] = "outside_supplied_ward_coverage"
    elif not strict:
        result["assignment_status"] = "on_ward_boundary"
    elif len(strict) != 1:
        result["assignment_status"] = "ambiguous_multiple_wards"
    else:
        result["assignment_status"] = "assigned_approximate_reference_point"
        result["ward_id"] = strict[0]["ward_id"]
        result["ward_name"] = strict[0]["ward_name"]
    return result


def _priority_band(rank: int | None, ranked_count: int, *, assigned: bool) -> str:
    if not assigned:
        return "not_comparable"
    if rank is None:
        return "unranked"
    top_10 = math.ceil(ranked_count * 0.10)
    top_25 = math.ceil(ranked_count * 0.25)
    if rank <= top_10:
        return "top_10_percent"
    if rank <= top_25:
        return "ranks_11_to_top_25_percent"
    return "remaining_ranked"


def _record_c3(
    record: dict[str, Any],
    assignment: dict[str, Any],
    ward: dict[str, Any] | None,
    uncertainty: dict[str, Any] | None,
    ranked_count: int,
) -> dict[str, Any]:
    rank = ward["rank_value"] if ward else None
    percentile = (
        100.0 * (ranked_count - rank) / (ranked_count - 1)
        if rank is not None and ranked_count > 1
        else None
    )
    return {
        "name": record["name"],
        "source": record["source"],
        "ward_id": assignment["ward_id"],
        "rank": rank,
        "percentile": percentile,
    }


def _compare_preliminary(
    path: Path | None, current: list[dict[str, Any]], ranked_count: int
) -> dict[str, Any]:
    if path is None:
        return {"status": "not_supplied", "records": []}
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("hotspot_results"), list):
        raise D7Error("Preliminary D7 JSON must contain a hotspot_results array")
    old_rows = payload["hotspot_results"]
    old_by_name = {
        row.get("hotspot"): row for row in old_rows if isinstance(row, dict) and row.get("hotspot")
    }
    if len(old_by_name) != len(old_rows):
        raise D7Error("Preliminary D7 hotspot names must be present and unique")
    comparison = []
    for row in current:
        prior = old_by_name.get(row["name"])
        if prior is None:
            comparison.append({"name": row["name"], "preliminary_status": "not_present"})
            continue
        old_rank = prior.get("our_rank")
        old_assigned = prior.get("comparison_status") == "compared"
        comparison.append(
            {
                "name": row["name"],
                "preliminary_status": prior.get("comparison_status"),
                "preliminary_ward_id": prior.get("matched_ward_id"),
                "preliminary_rank": old_rank,
                "preliminary_priority_band": _priority_band(
                    old_rank, ranked_count, assigned=old_assigned
                ),
                "final_ward_id": row["ward_id"],
                "final_rank": row["rank"],
                "final_priority_band": row["priority_band"],
                "rank_change_final_minus_preliminary": (
                    row["rank"] - old_rank
                    if row["rank"] is not None and old_rank is not None
                    else None
                ),
                "interpretation": "Preliminary ranks used temporary D7 ordering; final values use unchanged accepted D3 ranks.",
            }
        )
    return {
        "status": "compared_historical_reference_only",
        "path": str(path),
        "sha256": _sha256(path),
        "preliminary_ranking_method": payload.get("ranking_method"),
        "records": comparison,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    required_paths = [
        args.wards,
        args.pack_manifest,
        args.d3_ward_index,
        args.d3_qa,
        args.d4_sensitivity,
        args.d4_qa,
        args.config,
        args.integration_manifest,
    ]
    if args.preliminary_json is not None:
        required_paths.append(args.preliminary_json)
    if any(not path.is_file() for path in required_paths):
        missing = next(path for path in required_paths if not path.is_file())
        raise D7Error(f"Required D7 input is not a file: {missing}")
    outputs = [args.output_dir / name for name in OUTPUT_NAMES]
    if not args.overwrite and any(path.exists() for path in outputs):
        raise D7Error("D7 output exists; pass --overwrite to replace outputs")

    try:
        config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise D7Error(f"Cannot read C6 configuration: {args.config}") from exc
    if not isinstance(config, dict):
        raise D7Error("C6 configuration must be an object")
    hashes = _verify_provenance(args, config)
    hashes["hotspot_records"] = _sha256(args.hotspots_json or Path(__file__))
    if args.preliminary_json is not None:
        hashes["preliminary_d7"] = _sha256(args.preliminary_json)
    hotspots = _load_hotspots(args.hotspots_json)
    wards, ward_by_id = _load_wards(args.wards)
    rankings, ranking_counts = _load_rankings(args.d3_ward_index, config)
    if set(rankings) != set(ward_by_id):
        raise D7Error("D3 ward IDs do not match verified ward geometry IDs")
    ranges = _load_sensitivity(args.d4_sensitivity, rankings)

    result_rows: list[dict[str, Any]] = []
    c3_records = []
    for record in hotspots:
        assignment = _assign_hotspot(record, wards)
        ward = rankings.get(assignment["ward_id"]) if assignment["ward_id"] else None
        sensitivity = ranges.get(assignment["ward_id"]) if assignment["ward_id"] else None
        if ward is not None and ward["rank_value"] is None:
            assignment["assignment_status"] = "assigned_to_unranked_ward"
        rank = ward["rank_value"] if ward else None
        c3 = _record_c3(record, assignment, ward, sensitivity, ranking_counts["ranked"])
        c3_records.append(c3)
        result_rows.append(
            {
                **record,
                **assignment,
                "inspection_score": ward["score_value"] if ward else None,
                "rank": rank,
                "rank_percentile": c3["percentile"],
                "rank_p05": sensitivity["rank_p05"] if sensitivity else None,
                "rank_p95": sensitivity["rank_p95"] if sensitivity else None,
                "priority_band": _priority_band(
                    rank, ranking_counts["ranked"], assigned=ward is not None
                ),
                "coverage_pct": float(ward["coverage_pct"]) if ward else None,
                "eligibility_flags": ward["flags_list"] if ward else [],
            }
        )
    if any(set(item) != C3_HOTSPOT_KEYS for item in c3_records):
        raise AssertionError("C3 hotspot fragment shape changed")

    assignments = [row["assignment_status"] for row in result_rows]
    counts = {
        "total_literature_hotspot_records": len(result_rows),
        "with_usable_coordinates": sum(row["latitude"] is not None for row in result_rows),
        "unambiguously_assigned_to_wards": sum(
            status in {"assigned_approximate_reference_point", "assigned_to_unranked_ward"}
            for status in assignments
        ),
        "outside_supplied_ward_coverage": assignments.count("outside_supplied_ward_coverage"),
        "boundary_or_multiple_ward_ambiguous": sum(
            status in {"on_ward_boundary", "ambiguous_multiple_wards"} for status in assignments
        ),
        "assigned_to_ranked_wards": sum(row["rank"] is not None for row in result_rows),
        "assigned_to_unranked_wards": assignments.count("assigned_to_unranked_ward"),
        "included_in_rank_comparison": sum(row["rank"] is not None for row in result_rows),
        "unique_assigned_wards": len(
            {row["ward_id"] for row in result_rows if row["ward_id"] is not None}
        ),
        "hotspot_records_per_priority_band": {},
        "unique_wards_per_priority_band": {},
    }
    for band in (
        "top_10_percent",
        "ranks_11_to_top_25_percent",
        "remaining_ranked",
        "unranked",
        "not_comparable",
    ):
        band_rows = [row for row in result_rows if row["priority_band"] == band]
        counts["hotspot_records_per_priority_band"][band] = len(band_rows)
        counts["unique_wards_per_priority_band"][band] = len(
            {row["ward_id"] for row in band_rows if row["ward_id"] is not None}
        )

    summary = {
        "report_type": "D7 literature hotspot comparison",
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "completed_with_approximate_reference_points",
        "methodology": {
            "spatial_assignment": "Strict point-within exactly one supplied EPSG:4326 ward polygon; multiple intersections are ambiguous; no nearest-ward fallback.",
            "rank_source": "Finalized D3 ward_index.csv; unchanged score-descending, ward_id-ascending ranks.",
            "percentile": "100 * (245 - rank) / (245 - 1); rank 1 is highest priority.",
            "priority_bands": {
                "top_10_percent": f"ranks 1-{math.ceil(245 * 0.10)}",
                "ranks_11_to_top_25_percent": f"ranks {math.ceil(245 * 0.10) + 1}-{math.ceil(245 * 0.25)}",
                "remaining_ranked": f"ranks {math.ceil(245 * 0.25) + 1}-245",
                "unranked": "no rank",
            },
            "priority_bands_are": "Descriptive analytical convention for this report, not a frozen C3 requirement.",
        },
        "denominators": counts,
        "ranking": ranking_counts,
        "literature_sources": [
            {
                key: record.get(key)
                for key in (
                    "hotspot_id",
                    "name",
                    "literature_title",
                    "authors",
                    "publication_year",
                    "doi",
                    "source_url",
                    "source_location_detail",
                    "observation_period",
                    "deformation_magnitude",
                    "latitude",
                    "longitude",
                    "coordinate_status",
                    "coordinate_source",
                    "coordinate_uncertainty",
                )
            }
            for record in result_rows
        ],
        "limitations": [
            "All four coordinates are legacy approximate locality/city references; the coordinate derivations are undocumented and are not exact literature-published hotspot points.",
            "Nature article pages did not fully load in the research browser; indexed article text and the Cambridge repository record support the cited author lists, periods and area-level rates, but the legacy coordinate derivation is undocumented and no exact hotspot-point coordinate was verified.",
            "A ward assignment identifies only the ward containing an approximate reference point, not the spatial extent of a literature hotspot.",
            "Faridabad/Ghaziabad points outside supplied ward coverage are not thereby proven outside the Delhi administrative boundary.",
            "Literature observation periods and spatial scales differ; this very small, nonrepresentative sample cannot validate or invalidate the index or establish causation.",
            "Rank uncertainty is represented by D4 intervals; hotspot agreement is supplementary literature consistency, not independent building-level ground truth or collapse prediction.",
        ],
        "preliminary_comparison": _compare_preliminary(
            args.preliminary_json, result_rows, ranking_counts["ranked"]
        ),
        "inputs": {
            name: {"path": str(path), "sha256": hashes[name]}
            for name, path in (
                ("wards", args.wards),
                ("pack_manifest", args.pack_manifest),
                ("d3_ward_index", args.d3_ward_index),
                ("d3_qa", args.d3_qa),
                ("d4_sensitivity", args.d4_sensitivity),
                ("d4_qa", args.d4_qa),
                ("config", args.config),
                ("integration_manifest", args.integration_manifest),
                ("hotspot_records", args.hotspots_json or Path(__file__)),
                *(
                    [("preliminary_d7", args.preliminary_json)]
                    if args.preliminary_json is not None
                    else []
                ),
            )
        },
        "outputs": {},
        "internal_use_only": True,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(outputs[0], c3_records, args.overwrite)
    _write_csv(outputs[1], result_rows, args.overwrite)
    summary["outputs"] = {
        path.name: {"path": str(path), "sha256": _sha256(path)} for path in outputs[:2]
    }
    qa_content = {key: value for key, value in summary.items() if key != "outputs"}
    summary["outputs"][outputs[2].name] = {
        "path": str(outputs[2]),
        "sha256": hashlib.sha256(_canonical_json(qa_content).encode()).hexdigest(),
        "sha256_scope": "canonical QA content excluding outputs (avoids recursive self-hash)",
    }
    _write_json(outputs[2], summary, args.overwrite)
    return summary


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _write_json(path: Path, value: Any, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D7Error(f"Output exists; pass --overwrite to replace it: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _write_csv(path: Path, rows: list[dict[str, Any]], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise D7Error(f"Output exists; pass --overwrite to replace it: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                    for key, value in row.items()
                    if key in CSV_FIELDS
                }
            )
    os.replace(temporary, path)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Compare documented literature hotspot references with finalized D3 ward ranks."
    )
    sub = result.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser(
        "run", help="Validate provenance, assign hotspot points and write D7 outputs"
    )
    for name in (
        "wards",
        "pack-manifest",
        "d3-ward-index",
        "d3-qa",
        "d4-sensitivity",
        "d4-qa",
        "config",
        "integration-manifest",
        "output-dir",
    ):
        run_parser.add_argument(f"--{name}", type=Path, required=True)
    run_parser.add_argument(
        "--hotspots-json",
        type=Path,
        help="Optional explicit hotspot record array; defaults to the documented original D7 references",
    )
    run_parser.add_argument(
        "--preliminary-json",
        type=Path,
        help="Optional historical Person D D7 summary for a read-only comparison",
    )
    run_parser.add_argument("--overwrite", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
    except (D7Error, OSError, ValueError, jsonschema.SchemaError) as exc:
        print(f"D7 failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps({"status": report["status"], "denominators": report["denominators"]}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
