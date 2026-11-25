"""Bounded Sentinel-1 catalog discovery via the ASF Search API."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, date, datetime
from itertools import combinations, islice
from pathlib import Path
from typing import Any

MAX_RESULTS_LIMIT = 250
MAX_PAIRS_LIMIT = 1000
DEFAULT_MAX_PAIRS = 100
DISCOVERY_SOURCE = "Alaska Satellite Facility (ASF) catalog via asf_search"
RESULT_NOTE = (
    "Catalog candidates only. Results are not confirmed HyP3-compatible burst pairs "
    "and are not displacement products."
)
BURST_PROPERTY_NAMES = (
    "absoluteBurstID",
    "relativeBurstID",
    "fullBurstID",
    "burstIndex",
    "samplesPerBurst",
    "subswath",
    "azimuthTime",
    "azimuthAnxTime",
    "operaBurstID",
    "burstID",
    "burst_id",
)


class DiscoveryError(Exception):
    """Safe, user-facing discovery failure."""


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Parse and validate a W,S,E,N geographic bounding box."""
    try:
        parts = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox must contain four numeric coordinates") from exc
    if len(parts) != 4 or not all(math.isfinite(part) for part in parts):
        raise argparse.ArgumentTypeError("bbox must contain four finite coordinates")
    west, south, east, north = parts
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise argparse.ArgumentTypeError("bbox longitude must be between -180 and 180")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise argparse.ArgumentTypeError("bbox latitude must be between -90 and 90")
    if west >= east or south >= north:
        raise argparse.ArgumentTypeError("bbox west/south must be less than east/north")
    return west, south, east, north


def parse_iso_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be a valid calendar date") from exc


def parse_max_results(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-results must be an integer") from exc
    if not 1 <= result <= MAX_RESULTS_LIMIT:
        raise argparse.ArgumentTypeError(f"max-results must be between 1 and {MAX_RESULTS_LIMIT}")
    return result


def parse_max_pairs(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-pairs must be an integer") from exc
    if not 1 <= result <= MAX_PAIRS_LIMIT:
        raise argparse.ArgumentTypeError(f"max-pairs must be between 1 and {MAX_PAIRS_LIMIT}")
    return result


def parse_output_path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("output path must not be empty")
    output = Path(value)
    if output.suffix.casefold() != ".json":
        raise argparse.ArgumentTypeError("output path must have a .json extension")
    return output


def _get(properties: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = properties.get(name)
        if value is not None:
            return value
    return None


def _mapping_value(product: Any, key: str) -> Any:
    if isinstance(product, dict):
        return product.get(key)
    return getattr(product, key, None)


def _geojson_geometry(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        value = getattr(value, "__geo_interface__", None)
    return value if isinstance(value, dict) else None


def normalize_result(product: Any) -> dict[str, Any]:
    """Extract stable, non-invented fields from an ASF product/GeoJSON feature."""
    properties = _mapping_value(product, "properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    burst_properties = properties.get("burst")
    if not isinstance(burst_properties, dict):
        burst_properties = {}
    burst_fields = {
        key: value
        for key in BURST_PROPERTY_NAMES
        if (value := burst_properties.get(key, properties.get(key))) is not None
    }
    return {
        "scene_id": _get(properties, "sceneName", "scene_id"),
        "granule_id": _get(properties, "fileID", "granuleName", "granule_id"),
        "acquisition_time": _get(properties, "startTime", "start_time"),
        "platform": _get(properties, "platform", "platformName"),
        "polarization": _get(properties, "polarization", "polarisation"),
        "flight_direction": _get(properties, "flightDirection", "flight_direction"),
        "relative_orbit": _get(properties, "relativeOrbit", "pathNumber", "relative_orbit"),
        "absolute_orbit": _get(properties, "orbit", "absoluteOrbit", "absolute_orbit"),
        "beam_mode": _get(properties, "beamModeType", "beamMode", "beam_mode"),
        "group_id": _get(properties, "groupID", "group_id"),
        "processing_level": _get(properties, "processingLevel", "processing_level"),
        "geometry": _geojson_geometry(_mapping_value(product, "geometry")),
        "burst_fields": burst_fields,
    }


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def shortlist_pairs(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return conservative repeat-date candidates from normalized ASF records.

    This is a metadata shortlist only; it does not determine HyP3 compatibility.
    No scene-name parsing or inferred burst identifiers are used.
    """
    groups: dict[tuple[Any, ...], list[tuple[int, dict[str, Any], datetime]]] = {}
    unresolved = []
    for index, record in enumerate(records):
        bursts = record.get("burst_fields")
        if not isinstance(bursts, dict):
            bursts = {}
        timestamp = _parse_utc_timestamp(record.get("acquisition_time"))
        required = {
            "scene_id": record.get("scene_id") or record.get("granule_id"),
            "platform": record.get("platform"),
            "processing_level": record.get("processing_level"),
            "polarization": record.get("polarization"),
            "relative_orbit": record.get("relative_orbit"),
            "flight_direction": record.get("flight_direction"),
            "beam_mode": record.get("beam_mode"),
            "full_burst_id": bursts.get("fullBurstID"),
            "subswath": bursts.get("subswath"),
        }
        missing = [name for name, value in required.items() if value is None or value == ""]
        if timestamp is None:
            missing.append("acquisition_time")
        unsupported = []
        if record.get("processing_level") != "BURST":
            unsupported.append("unsupported_processing_level")
        if missing:
            unresolved.append(
                {
                    "record_index": index,
                    "scene_id": required["scene_id"],
                    "reason_codes": sorted({f"missing_{name}" for name in missing}),
                }
            )
            continue
        if unsupported:
            unresolved.append(
                {
                    "record_index": index,
                    "scene_id": required["scene_id"],
                    "reason_codes": unsupported,
                }
            )
            continue

        key = (
            required["platform"],
            required["processing_level"],
            required["full_burst_id"],
            required["polarization"],
            required["relative_orbit"],
            required["flight_direction"],
            required["beam_mode"],
            required["subswath"],
        )
        groups.setdefault(key, []).append((index, record, timestamp))

    candidate_pairs = []
    matched_indices: set[int] = set()
    for key, group in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
        dates: dict[date, list[tuple[int, dict[str, Any], datetime]]] = {}
        for entry in group:
            dates.setdefault(entry[2].date(), []).append(entry)
        if any(len(day_entries) > 1 for day_entries in dates.values()):
            for index, record, _ in group:
                unresolved.append(
                    {
                        "record_index": index,
                        "scene_id": record.get("scene_id") or record.get("granule_id"),
                        "reason_codes": ["multiple_records_for_pairing_key_and_date"],
                    }
                )
            continue
        ordered = sorted(group, key=lambda entry: (entry[2], str(entry[1].get("scene_id"))))
        for first, second in combinations(ordered, 2):
            if first[2].date() == second[2].date():
                continue
            common = {
                "platform": key[0],
                "processing_level": key[1],
                "full_burst_id": key[2],
                "polarization": key[3],
                "relative_orbit": key[4],
                "flight_direction": key[5],
                "beam_mode": key[6],
                "subswath": key[7],
            }
            candidate_pairs.append(
                {
                    "status": "shortlist_candidate_unverified",
                    "reference": {
                        "scene_id": first[1].get("scene_id"),
                        "granule_id": first[1].get("granule_id"),
                        "acquisition_time": first[1].get("acquisition_time"),
                    },
                    "secondary": {
                        "scene_id": second[1].get("scene_id"),
                        "granule_id": second[1].get("granule_id"),
                        "acquisition_time": second[1].get("acquisition_time"),
                    },
                    "temporal_separation_days": (second[2] - first[2]).total_seconds() / 86400,
                    "matching_metadata": common,
                }
            )
            matched_indices.update((first[0], second[0]))

    unresolved_indices = {item["record_index"] for item in unresolved}
    unpaired = [
        {
            "record_index": index,
            "scene_id": record.get("scene_id") or record.get("granule_id"),
            "reason_code": "no_matching_acquisition_on_another_date",
        }
        for index, record in enumerate(records)
        if index not in matched_indices and index not in unresolved_indices
    ]
    candidate_pairs.sort(
        key=lambda pair: (
            pair["matching_metadata"]["full_burst_id"],
            pair["matching_metadata"]["polarization"],
            pair["reference"]["acquisition_time"],
            pair["secondary"]["acquisition_time"],
        )
    )
    unresolved.sort(key=lambda item: item["record_index"])
    return {
        "candidate_pairs": candidate_pairs,
        "unresolved_records": unresolved,
        "unpaired_records": unpaired,
        "note": "Shortlist candidates only; HyP3 compatibility is unverified.",
    }


def _load_asf_search() -> Any:
    try:
        import asf_search
    except ImportError as exc:
        raise DiscoveryError(
            "ASF discovery requires the optional dependency; install with "
            'python -m pip install ".[insar]"'
        ) from exc
    return asf_search


def _bbox_wkt(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    return f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"


def _utc_date_bounds(start: date, end: date) -> tuple[str, str]:
    return f"{start.isoformat()}T00:00:00Z", f"{end.isoformat()}T23:59:59Z"


def build_document(
    *,
    bbox: tuple[float, float, float, float],
    start: date,
    end: date,
    max_results: int,
    products: Any,
    generated_utc: datetime | None = None,
) -> dict[str, Any]:
    bounded_products = islice(products, max_results)
    results = [normalize_result(product) for product in bounded_products]
    generated = generated_utc or datetime.now(UTC)
    generated = generated.astimezone(UTC).replace(microsecond=0)
    start_utc, end_utc = _utc_date_bounds(start, end)
    return {
        "generated_utc": generated.isoformat().replace("+00:00", "Z"),
        "discovery_source": DISCOVERY_SOURCE,
        "query": {
            "dataset": "SLC_BURST",
            "bbox_wsen": list(bbox),
            "start_utc": start_utc,
            "end_utc_inclusive": end_utc,
            "max_results": max_results,
        },
        "result_count": len(results),
        "results": results,
        "note": RESULT_NOTE,
    }


def validate_output_path(output: Path, *, overwrite: bool) -> None:
    if output.suffix.casefold() != ".json":
        raise DiscoveryError("output path must have a .json extension")
    if not output.parent.is_dir():
        raise DiscoveryError("output directory must already exist")
    if output.exists() and not overwrite:
        raise DiscoveryError("output already exists; pass --overwrite to replace it")


def write_document(document: dict[str, Any], output: Path, *, overwrite: bool) -> None:
    validate_output_path(output, overwrite=overwrite)
    mode = "w" if overwrite else "x"
    try:
        with output.open(mode, encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise DiscoveryError("could not write discovery output") from exc


def discover(
    *,
    bbox: tuple[float, float, float, float],
    start: date,
    end: date,
    max_results: int,
    output: Path,
    overwrite: bool = False,
    client: Any = None,
    generated_utc: datetime | None = None,
) -> dict[str, Any]:
    if start > end:
        raise DiscoveryError("start date must not be after end date")
    if not 1 <= max_results <= MAX_RESULTS_LIMIT:
        raise DiscoveryError(f"max-results must be between 1 and {MAX_RESULTS_LIMIT}")
    validate_output_path(output, overwrite=overwrite)
    if client is None:
        client = _load_asf_search()
    try:
        start_utc, end_utc = _utc_date_bounds(start, end)
        products = client.geo_search(
            dataset=client.DATASET.SLC_BURST,
            intersectsWith=_bbox_wkt(bbox),
            start=start_utc,
            end=end_utc,
            maxResults=max_results,
        )
        raise_if_incomplete = getattr(products, "raise_if_incomplete", None)
        if callable(raise_if_incomplete):
            raise_if_incomplete()
        document = build_document(
            bbox=bbox,
            start=start,
            end=end,
            max_results=max_results,
            products=products,
            generated_utc=generated_utc,
        )
    except DiscoveryError:
        raise
    except Exception as exc:
        # Do not surface response bodies, URLs, or client internals in CLI errors.
        raise DiscoveryError("ASF catalog discovery failed") from exc
    write_document(document, output, overwrite=overwrite)
    return document


def build_pairs_document(
    *,
    input_path: Path,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    generated_utc: datetime | None = None,
) -> dict[str, Any]:
    """Load a bounded discovery report and create an offline candidate shortlist."""
    if not input_path.is_file():
        raise DiscoveryError("input report does not exist or is not a file")
    try:
        with input_path.open(encoding="utf-8") as stream:
            source = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("input report is not readable valid JSON") from exc
    if not isinstance(source, dict) or not isinstance(source.get("results"), list):
        raise DiscoveryError("input report must be a discovery JSON object with a results list")
    records = source["results"]
    if len(records) > MAX_RESULTS_LIMIT or any(not isinstance(item, dict) for item in records):
        raise DiscoveryError("input report contains invalid or excessive result records")
    if not 1 <= max_pairs <= MAX_PAIRS_LIMIT:
        raise DiscoveryError(f"max-pairs must be between 1 and {MAX_PAIRS_LIMIT}")

    shortlist = shortlist_pairs(records)
    pairs = shortlist["candidate_pairs"][:max_pairs]
    generated = generated_utc or datetime.now(UTC)
    generated = generated.astimezone(UTC).replace(microsecond=0)
    return {
        "generated_utc": generated.isoformat().replace("+00:00", "Z"),
        "source_input": str(input_path),
        "max_pairs": max_pairs,
        "pair_count": len(pairs),
        "candidate_pairs": pairs,
        "unresolved_records": shortlist["unresolved_records"],
        "unpaired_records": shortlist["unpaired_records"],
        "warning": "NOT confirmed HyP3-compatible pairs; metadata shortlist only.",
    }


def create_pairs_report(
    *, input_path: Path, output: Path, max_pairs: int, overwrite: bool = False
) -> dict[str, Any]:
    validate_output_path(output, overwrite=overwrite)
    try:
        if input_path.resolve() == output.resolve():
            raise DiscoveryError("input and output paths must be different")
    except OSError as exc:
        raise DiscoveryError("could not resolve input or output path") from exc
    document = build_pairs_document(input_path=input_path, max_pairs=max_pairs)
    write_document(document, output, overwrite=overwrite)
    return document


def _validate_pair_report(source: Any) -> list[dict[str, Any]]:
    if not isinstance(source, dict):
        raise DiscoveryError("input is not a valid E7.2 pair report")
    candidates = source.get("candidate_pairs")
    unresolved = source.get("unresolved_records")
    if (
        not isinstance(candidates, list)
        or not isinstance(unresolved, list)
        or not isinstance(source.get("unpaired_records"), list)
        or not isinstance(source.get("source_input"), str)
        or not isinstance(source.get("warning"), str)
        or "HyP3-compatible" not in source["warning"]
    ):
        raise DiscoveryError("input is not a valid E7.2 pair report")
    if (
        isinstance(source.get("pair_count"), bool)
        or not isinstance(source.get("pair_count"), int)
        or source["pair_count"] != len(candidates)
    ):
        raise DiscoveryError("input pair count does not match candidate records")
    for item in unresolved:
        if (
            not isinstance(item, dict)
            or isinstance(item.get("record_index"), bool)
            or not isinstance(item.get("record_index"), int)
            or not isinstance(item.get("reason_codes"), list)
            or any(not isinstance(reason, str) for reason in item["reason_codes"])
        ):
            raise DiscoveryError("input contains invalid unresolved records")
    for pair in candidates:
        if not isinstance(pair, dict) or pair.get("status") != "shortlist_candidate_unverified":
            raise DiscoveryError("input contains an invalid candidate pair")
        reference = pair.get("reference")
        secondary = pair.get("secondary")
        metadata = pair.get("matching_metadata")
        if (
            not isinstance(reference, dict)
            or not isinstance(secondary, dict)
            or not isinstance(metadata, dict)
        ):
            raise DiscoveryError("input contains an invalid candidate pair")
        for acquisition in (reference, secondary):
            if (
                not isinstance(acquisition.get("scene_id"), str)
                or not acquisition["scene_id"]
                or not isinstance(acquisition.get("acquisition_time"), str)
                or _parse_utc_timestamp(acquisition["acquisition_time"]) is None
            ):
                raise DiscoveryError("input contains an invalid candidate acquisition")
        reference_time = _parse_utc_timestamp(reference["acquisition_time"])
        secondary_time = _parse_utc_timestamp(secondary["acquisition_time"])
        separation = pair.get("temporal_separation_days")
        if (
            isinstance(separation, bool)
            or not isinstance(separation, (int, float))
            or not math.isfinite(separation)
            or separation < 0
            or reference_time is None
            or secondary_time is None
            or reference_time.date() == secondary_time.date()
            or secondary_time <= reference_time
            or not math.isclose(
                separation,
                (secondary_time - reference_time).total_seconds() / 86400,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            raise DiscoveryError("input contains an invalid temporal separation")
        if (
            not isinstance(metadata.get("full_burst_id"), str)
            or not metadata["full_burst_id"]
            or metadata.get("polarization") not in {"VV", "VH"}
            or isinstance(metadata.get("relative_orbit"), bool)
            or not isinstance(metadata.get("relative_orbit"), (int, float, str))
            or metadata.get("relative_orbit") == ""
            or (
                isinstance(metadata.get("relative_orbit"), float)
                and not math.isfinite(metadata["relative_orbit"])
            )
            or metadata.get("flight_direction") not in {"ASCENDING", "DESCENDING"}
        ):
            raise DiscoveryError("input contains invalid matching metadata")
    return candidates


def build_dry_run_manifest(
    *, input_path: Path, generated_utc: datetime | None = None
) -> dict[str, Any]:
    """Select the shortest valid VV pair from an E7.2 report without processing it."""
    if not input_path.is_file():
        raise DiscoveryError("pair report does not exist or is not a file")
    try:
        with input_path.open(encoding="utf-8") as stream:
            source = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("pair report is not readable valid JSON") from exc
    candidates = _validate_pair_report(source)
    vv_candidates = [
        pair for pair in candidates if pair["matching_metadata"]["polarization"] == "VV"
    ]
    if not vv_candidates:
        raise DiscoveryError("pair report contains no eligible VV candidates")
    selected = min(
        vv_candidates,
        key=lambda pair: (
            pair["temporal_separation_days"],
            pair["reference"]["acquisition_time"],
            pair["secondary"]["acquisition_time"],
            pair["reference"]["scene_id"],
            pair["secondary"]["scene_id"],
            pair["matching_metadata"]["full_burst_id"],
        ),
    )
    metadata = selected["matching_metadata"]
    generated = generated_utc or datetime.now(UTC)
    generated = generated.astimezone(UTC).replace(microsecond=0)
    return {
        "generated_utc": generated.isoformat().replace("+00:00", "Z"),
        "source_pair_report": str(input_path),
        "reference_scene_id": selected["reference"]["scene_id"],
        "reference_acquisition_time": selected["reference"]["acquisition_time"],
        "secondary_scene_id": selected["secondary"]["scene_id"],
        "secondary_acquisition_time": selected["secondary"]["acquisition_time"],
        "full_burst_id": metadata["full_burst_id"],
        "polarization": metadata["polarization"],
        "relative_orbit": metadata["relative_orbit"],
        "flight_direction": metadata["flight_direction"],
        "temporal_separation_days": selected["temporal_separation_days"],
        "processing_status": "not_submitted",
        "hyp3_eligibility": "unverified",
        "displacement_product": "not_available",
        "data_provenance": "Real ASF catalog metadata; not processed InSAR measurements.",
    }


def create_dry_run_manifest(
    *, input_path: Path, output: Path, overwrite: bool = False
) -> dict[str, Any]:
    validate_output_path(output, overwrite=overwrite)
    try:
        if input_path.resolve() == output.resolve():
            raise DiscoveryError("input and output paths must be different")
    except (OSError, RuntimeError) as exc:
        raise DiscoveryError("could not resolve input or output path") from exc
    manifest = build_dry_run_manifest(input_path=input_path)
    write_document(manifest, output, overwrite=overwrite)
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover bounded Sentinel-1 candidates from ASF.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discovery = subparsers.add_parser("discovery", help="search the ASF Sentinel-1 catalog")
    discovery.add_argument("--bbox", required=True, type=parse_bbox, metavar="W,S,E,N")
    discovery.add_argument("--start", required=True, type=parse_iso_date, metavar="YYYY-MM-DD")
    discovery.add_argument("--end", required=True, type=parse_iso_date, metavar="YYYY-MM-DD")
    discovery.add_argument("--max-results", required=True, type=parse_max_results, metavar="1..250")
    discovery.add_argument("--output", required=True, type=parse_output_path)
    discovery.add_argument("--overwrite", action="store_true")
    pairs = subparsers.add_parser(
        "pairs", help="shortlist repeat-pass candidates from a discovery report"
    )
    pairs.add_argument("--input", required=True, type=Path)
    pairs.add_argument("--output", required=True, type=parse_output_path)
    pairs.add_argument(
        "--max-pairs", type=parse_max_pairs, default=DEFAULT_MAX_PAIRS, metavar="1..1000"
    )
    pairs.add_argument("--overwrite", action="store_true")
    dry_run = subparsers.add_parser(
        "dry-run", help="select one VV candidate and write a non-submitted manifest"
    )
    dry_run.add_argument("--input", required=True, type=Path)
    dry_run.add_argument("--output", required=True, type=parse_output_path)
    dry_run.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "pairs":
        try:
            document = create_pairs_report(
                input_path=args.input,
                output=args.output,
                max_pairs=args.max_pairs,
                overwrite=args.overwrite,
            )
        except DiscoveryError as exc:
            print(f"pairs error: {exc}", file=sys.stderr)
            return 2
        print(f"Wrote {document['pair_count']} unverified pair candidates to {args.output}")
        return 0
    if args.command == "dry-run":
        try:
            create_dry_run_manifest(
                input_path=args.input,
                output=args.output,
                overwrite=args.overwrite,
            )
        except DiscoveryError as exc:
            print(f"dry-run error: {exc}", file=sys.stderr)
            return 2
        print(f"Wrote not-submitted dry-run manifest to {args.output}")
        return 0
    if args.start > args.end:
        parser.error("--start must not be after --end")
    try:
        document = discover(
            bbox=args.bbox,
            start=args.start,
            end=args.end,
            max_results=args.max_results,
            output=args.output,
            overwrite=args.overwrite,
        )
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {document['result_count']} catalog candidates to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
