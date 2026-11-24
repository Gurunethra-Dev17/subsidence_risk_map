"""Readiness checks and reproducible orchestration for the D8 C2/C3 exporter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from analytics import export as d8


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _error(report: dict[str, Any], code: str, message: str) -> None:
    report["errors"].append({"code": code, "message": message})
    report["checks"].append({"name": code, "status": "failed", "message": message})


def _pass(report: dict[str, Any], code: str, message: str) -> None:
    report["checks"].append({"name": code, "status": "passed", "message": message})


def _warning(report: dict[str, Any], code: str, message: str) -> None:
    report["warnings"].append({"code": code, "message": message})
    report["checks"].append({"name": code, "status": "warning", "message": message})


def _input_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    return {
        "wards_csv": args.wards_csv,
        "sensitivity_csv": args.sensitivity_csv,
        "meta_json": args.meta_json,
        "cells_csv": args.cells_csv,
        "geometry_geojson": args.geometry_geojson,
        "validation_json": args.validation_json,
        "d6_validation_json": args.d6_validation_json,
        "ward_geometry_geojson": args.ward_geometry_geojson,
        "integration_manifest": args.integration_manifest,
    }


def _read_inputs(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any] | None:
    paths = _input_paths(args)
    required = {"wards_csv", "sensitivity_csv", "meta_json", "cells_csv", "geometry_geojson"}
    loaded: dict[str, Any] = {}
    for name, path in paths.items():
        if path is None:
            continue
        if not path.is_file():
            if name in required:
                _error(report, f"missing_{name}", f"Required input is not a file: {path}")
            else:
                _error(report, f"missing_{name}", f"Configured input is not a file: {path}")
            continue
        try:
            report["inputs"][name] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            if name in {"wards_csv", "sensitivity_csv", "cells_csv"}:
                loaded[name] = d8._read_csv(path)
            else:
                loaded[name] = d8._read_json(path)
        except (d8.ExportError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            _error(report, f"unreadable_{name}", str(exc))
    if report["errors"]:
        return None
    return loaded


def _check_cell_ids(rows: list[dict[str, Any]], geometry: Any, report: dict[str, Any]) -> None:
    if not isinstance(geometry, dict) or geometry.get("type") != "FeatureCollection":
        _error(
            report,
            "invalid_cell_geometry_root",
            "Cell geometry must be a GeoJSON FeatureCollection",
        )
        return
    features = geometry.get("features")
    if not isinstance(features, list):
        _error(report, "invalid_cell_geometry_features", "Cell geometry features must be an array")
        return

    csv_ids = [str(row.get("cell_id", "")).strip() for row in rows]
    geo_ids = [
        (feature.get("properties") or {}).get("cell_id")
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
        else None
        for feature in features
    ]
    duplicate_csv = len(csv_ids) - len(set(csv_ids))
    valid_geo_ids = [value for value in geo_ids if isinstance(value, str)]
    duplicate_geo = len(valid_geo_ids) - len(set(valid_geo_ids))
    if duplicate_csv:
        _error(report, "duplicate_cell_csv_ids", f"Cell CSV contains {duplicate_csv} duplicate IDs")
    if duplicate_geo:
        _error(
            report,
            "duplicate_cell_geometry_ids",
            f"Cell geometry contains {duplicate_geo} duplicate IDs",
        )
    if any(not value for value in csv_ids):
        _error(report, "empty_cell_csv_id", "Cell CSV contains an empty cell_id")
    if any(not isinstance(value, str) or not value for value in geo_ids):
        _error(
            report, "invalid_cell_geometry_id", "Every geometry feature must have a string cell_id"
        )
    geo_id_set = set(valid_geo_ids)
    if set(csv_ids) != geo_id_set:
        missing = len(set(csv_ids) - geo_id_set)
        extra = len(geo_id_set - set(csv_ids))
        _error(
            report,
            "cell_geometry_id_mismatch",
            f"Cell CSV and geometry IDs differ: {missing} missing geometries, {extra} extra features",
        )
    else:
        _pass(report, "cell_geometry_ids", f"All {len(csv_ids)} cell IDs match supplied geometry")


def _check_ward_geometry(
    ward_rows: list[dict[str, Any]], geometry_path: Path | None, report: dict[str, Any]
) -> None:
    if geometry_path is None:
        _warning(
            report, "ward_geometry_not_supplied", "Ward IDs were not compared with ward geometry"
        )
        return
    try:
        document = d8._read_json(geometry_path)
    except (d8.ExportError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        _error(report, "unreadable_ward_geometry", str(exc))
        return
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        _error(report, "invalid_ward_geometry", "Ward geometry must be a GeoJSON FeatureCollection")
        return
    features = document.get("features")
    if not isinstance(features, list):
        _error(report, "invalid_ward_geometry", "Ward geometry features must be an array")
        return
    ids = [
        (feature.get("properties") or {}).get("ward_id")
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
        else None
        for feature in features
    ]
    if any(not isinstance(value, str) or not value for value in ids):
        _error(report, "invalid_ward_geometry_ids", "Every ward feature must have a string ward_id")
        return
    if len(ids) != len(set(ids)):
        _error(report, "duplicate_ward_geometry_ids", "Ward geometry contains duplicate ward IDs")
        return
    ward_ids = {str(row.get("ward_id", "")).strip() for row in ward_rows}
    if ward_ids != set(ids):
        _error(
            report,
            "ward_geometry_id_mismatch",
            f"Ward CSV and geometry IDs differ: {len(ward_ids - set(ids))} missing geometries, "
            f"{len(set(ids) - ward_ids)} extra features",
        )
        return
    _pass(report, "ward_geometry_ids", f"All {len(ids)} ward IDs match supplied geometry")


def _resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (d8.ROOT / path).resolve()


def _check_source_metadata(metadata: Any, manifest: Any, report: dict[str, Any]) -> None:
    if not isinstance(metadata, dict):
        return
    if manifest is None:
        _warning(
            report,
            "source_manifest_not_supplied",
            "No integration manifest was supplied; candidate C1/C6 provenance was not checked.",
        )
        _warning(
            report,
            "upstream_lineage_missing",
            "Intermediate files do not prove which C1 hash produced their values.",
        )
        return
    if not isinstance(manifest, dict):
        _error(report, "invalid_integration_manifest", "Integration manifest must be a JSON object")
        return
    c1 = manifest.get("c1_candidate")
    c0 = manifest.get("c0_candidate")
    if not isinstance(c1, dict) or not isinstance(c0, dict):
        _error(report, "invalid_integration_manifest", "Manifest lacks C0/C1 candidate objects")
        return

    c1_path_value = c1.get("path")
    expected_c1_hash = c1.get("sha256")
    if not isinstance(c1_path_value, str) or not isinstance(expected_c1_hash, str):
        _error(report, "invalid_integration_manifest", "Manifest lacks C1 path or SHA-256")
    else:
        c1_path = _resolve_repo_path(c1_path_value)
        if not c1_path.is_file() or _sha256(c1_path) != expected_c1_hash:
            _error(
                report,
                "c1_manifest_hash_mismatch",
                "Staged C1 file is missing or differs from its manifest hash",
            )
        else:
            _pass(report, "c1_manifest_hash", "Staged C1 matches its integration-manifest hash")
        if metadata.get("engine_version") != c1.get("engine_version"):
            _error(
                report,
                "engine_version_mismatch",
                "D8 metadata engine_version differs from staged C1",
            )
        if metadata.get("params_hash") is not None and metadata["params_hash"] != c1.get(
            "params_hash"
        ):
            _error(report, "params_hash_mismatch", "D8 metadata params_hash differs from staged C1")

    c6_path_value = c1.get("c6_reference_config_path")
    if not isinstance(c6_path_value, str):
        _warning(
            report,
            "c6_config_not_recorded",
            "Integration manifest does not identify its matching C6 config",
        )
    else:
        c6_path = _resolve_repo_path(c6_path_value)
        if not c6_path.is_file():
            _error(report, "missing_c6_config", "Manifest-selected C6 config is missing")
        else:
            try:
                config = yaml.safe_load(c6_path.read_text(encoding="utf-8-sig"))
                d8._validate("config.schema.json", config)
            except (OSError, UnicodeError, yaml.YAMLError, d8.ExportError) as exc:
                _error(
                    report, "invalid_c6_config", f"Manifest-selected C6 config is invalid: {exc}"
                )
            else:
                if (
                    str(metadata.get("city", "")).casefold()
                    != str(config.get("city", "")).casefold()
                ):
                    _error(
                        report, "city_mismatch", "D8 metadata city differs from staged C6 config"
                    )
                if metadata.get("engine_version") != c1.get("engine_version"):
                    _error(
                        report,
                        "engine_version_mismatch",
                        "D8 metadata engine_version differs from staged C1",
                    )
                if metadata.get("params") != config.get("params"):
                    _error(
                        report,
                        "params_mismatch",
                        "D8 metadata params differ from the full staged C6 params mapping",
                    )
                if metadata.get("weights") != config.get("weights"):
                    _error(
                        report,
                        "weights_mismatch",
                        "D8 metadata weights differ from staged C6 weights",
                    )
                if metadata.get("data_vintage") != c0.get("pack_version"):
                    _error(
                        report,
                        "data_vintage_mismatch",
                        "D8 metadata data_vintage differs from C0 pack_version",
                    )
                if c1.get("params_hash"):
                    try:
                        canonical = json.dumps(
                            config["params"],
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                            allow_nan=False,
                        ).encode("utf-8")
                    except (TypeError, ValueError) as exc:
                        _error(
                            report,
                            "invalid_c6_params",
                            f"C6 params cannot be canonically hashed: {exc}",
                        )
                    else:
                        actual_hash = hashlib.sha256(canonical).hexdigest()
                        if actual_hash != c1.get("params_hash"):
                            _error(
                                report,
                                "c6_c1_params_hash_mismatch",
                                "Full C6 params hash differs from staged C1 metadata",
                            )
                        else:
                            _pass(
                                report,
                                "c6_c1_params_hash",
                                "Full staged C6 params hash matches staged C1",
                            )

    missing = manifest.get("c0_candidate", {}).get("missing_artifacts", [])
    if missing or not manifest.get("c0_candidate", {}).get("c0_manifest_complete", True):
        _warning(
            report,
            "c0_pack_incomplete",
            "The full C0 pack is incomplete; downstream C1-based inputs may still be checked, but H1 completeness is not established.",
        )
    license_info = manifest.get("licensing_and_handling", {})
    if isinstance(license_info, dict) and license_info.get("restriction"):
        report["limitations"].append(str(license_info["restriction"]))
    source_hashes = metadata.get("source_hashes")
    if not isinstance(source_hashes, dict) or not any(
        source_hashes.get(key) == c1.get("sha256")
        for key in ("c1", "building_metrics.parquet", "C1/building_metrics.parquet")
    ):
        _warning(
            report,
            "upstream_lineage_missing",
            "D8 metadata does not link the intermediate CSVs to the staged C1 SHA-256; input hashes are recorded, but analytical lineage remains unproven.",
        )
    else:
        _pass(report, "upstream_c1_lineage", "D8 metadata links to the staged C1 SHA-256")


def check_readiness(args: argparse.Namespace) -> dict[str, Any]:
    """Check D8 input compatibility without writing C2/C3 outputs or doing analytics."""
    report: dict[str, Any] = {
        "report_type": "D8 integration readiness",
        "generated_utc": _utc_now(),
        "status": "not_ready",
        "summary": {},
        "checks": [],
        "errors": [],
        "warnings": [],
        "limitations": [
            "This checker validates handoff and contract readiness; it does not perform D1-D7 scientific computations.",
            "A passing synthetic check demonstrates wiring only and is not real-data validation.",
        ],
        "inputs": {},
    }
    loaded = _read_inputs(args, report)
    if loaded is None:
        return report

    ward_rows = loaded["wards_csv"]
    sensitivity_rows = loaded["sensitivity_csv"]
    cell_rows = loaded["cells_csv"]
    metadata = loaded["meta_json"]
    geometry = loaded["geometry_geojson"]
    validation = loaded.get("validation_json")
    d6_fragment = loaded.get("d6_validation_json")

    if isinstance(ward_rows, list) and ward_rows:
        ranks: list[int] = []
        rank_parse_ok = True
        for row in ward_rows:
            if row.get("status") != "ranked":
                continue
            try:
                number = float(row.get("rank", ""))
                if not number.is_integer() or number < 1:
                    rank_parse_ok = False
                    break
                ranks.append(int(number))
            except (TypeError, ValueError):
                rank_parse_ok = False
                break
        if rank_parse_ok and len(ranks) != len(set(ranks)):
            _error(report, "duplicate_ward_ranks", "Ranked ward ranks are not unique")
        elif rank_parse_ok and ranks and sorted(ranks) != list(range(1, len(ranks) + 1)):
            _error(
                report,
                "noncontiguous_ward_ranks",
                "Ranked ward ranks are not contiguous from 1 through N",
            )
        elif rank_parse_ok:
            _pass(report, "ward_rank_contiguity", "Ranked ward ranks are unique and contiguous")

    if isinstance(cell_rows, list):
        _check_cell_ids(cell_rows, geometry, report)
    _check_ward_geometry(ward_rows, args.ward_geometry_geojson, report)

    c2_payload = None
    try:
        c2_payload = d8.build_ward_summary(
            ward_rows, sensitivity_rows, metadata, report["generated_utc"]
        )
    except (d8.ExportError, TypeError, AttributeError) as exc:
        _error(report, "c2_input_validation_failed", str(exc))
    else:
        _pass(
            report,
            "c2_input_contract",
            "Ward and sensitivity inputs satisfy the frozen C2 schema and H3 rules",
        )

    c2_cells = None
    try:
        c2_cells = d8.build_cell_scores(cell_rows, geometry)
    except (d8.ExportError, TypeError, AttributeError) as exc:
        _error(report, "cell_input_validation_failed", str(exc))
    else:
        _pass(
            report,
            "cell_input_contract",
            "Cell CSV and supplied geometry satisfy the frozen C2 schema and suppression rules",
        )

    validation_input: Any = validation if validation is not None else {}
    if not isinstance(validation_input, dict):
        _error(report, "invalid_validation_json", "Validation JSON must be an object")
        validation_input = {}
    if d6_fragment is not None:
        if not isinstance(d6_fragment, dict):
            _error(report, "invalid_d6_fragment", "D6 validation fragment must be a JSON object")
        elif set(validation_input) & {"collapse_check"}:
            _error(
                report,
                "duplicate_d6_fragment",
                "Supply collapse_check in either validation JSON or the separate D6 fragment, not both",
            )
        else:
            validation_input = {**validation_input, "collapse_check": d6_fragment}
    elif "collapse_check" not in validation_input:
        _warning(
            report,
            "d6_fragment_not_supplied",
            "No D6 collapse_check fragment was supplied; C3 will explicitly report that comparison as unavailable.",
        )
    if validation is None and d6_fragment is None:
        _warning(
            report,
            "validation_comparisons_not_supplied",
            "No validation sections were supplied; unavailable C3 comparisons will retain explanatory notes.",
        )
    try:
        c3_payload = d8.build_validation_summary(validation_input, report["generated_utc"])
    except (d8.ExportError, TypeError, AttributeError) as exc:
        _error(report, "c3_input_validation_failed", str(exc))
    else:
        _pass(
            report,
            "c3_input_contract",
            "Validation inputs satisfy the frozen C3 schema and note requirements",
        )

    _check_source_metadata(metadata, loaded.get("integration_manifest"), report)
    report["summary"] = {
        "ward_rows": len(ward_rows) if isinstance(ward_rows, list) else 0,
        "ranked_wards": sum(row.get("status") == "ranked" for row in ward_rows)
        if isinstance(ward_rows, list)
        else 0,
        "cell_rows": len(cell_rows) if isinstance(cell_rows, list) else 0,
        "suppressed_cells": sum(
            str(row.get("suppressed", "")).strip().lower() in {"true", "1"} for row in cell_rows
        )
        if isinstance(cell_rows, list)
        else 0,
        "c2_ward_payload_valid": c2_payload is not None,
        "c2_cell_payload_valid": c2_cells is not None,
        "c3_payload_valid": "c3_payload" in locals(),
    }
    report["status"] = "ready" if not report["errors"] else "not_ready"
    return report


def _print_report(report: dict[str, Any]) -> None:
    print(f"Integration readiness: {report['status'].upper()}")
    for key, value in report.get("summary", {}).items():
        print(f"  {key}: {value}")
    for issue in report["errors"]:
        print(f"ERROR [{issue['code']}] {issue['message']}")
    for issue in report["warnings"]:
        print(f"WARNING [{issue['code']}] {issue['message']}")
    for limitation in report["limitations"]:
        print(f"LIMITATION {limitation}")


def _write_json(path: Path, payload: dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise d8.ExportError(f"Report exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    """Gate the existing D8 exporter, then record hashes for its explicit inputs/outputs."""
    report = check_readiness(args)
    if report["errors"]:
        return report

    output_paths = [
        args.ward_output,
        args.cell_output,
        args.validation_output,
        args.provenance_output,
    ]
    resolved_outputs = [_resolved(path) for path in output_paths]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        _error(
            report, "output_path_collision", "C2, C3 and provenance output paths must be distinct"
        )
        report["status"] = "not_ready"
        return report
    input_paths = {_resolved(Path(item["path"])) for item in report["inputs"].values()}
    if any(path in input_paths for path in resolved_outputs):
        _error(
            report, "output_overwrites_input", "An output path cannot overwrite an input artifact"
        )
        report["status"] = "not_ready"
        return report
    if args.provenance_output.exists() and not args.overwrite:
        _error(
            report, "provenance_exists", "Provenance output exists; pass --overwrite to replace it"
        )
        report["status"] = "not_ready"
        return report

    validation_path = args.validation_json
    with tempfile.TemporaryDirectory(prefix="d8-validation-") as temporary_directory:
        if args.d6_validation_json is not None:
            original = d8._read_json(args.validation_json) if args.validation_json else {}
            original["collapse_check"] = d8._read_json(args.d6_validation_json)
            validation_path = Path(temporary_directory) / "validation.json"
            validation_path.write_text(json.dumps(original, allow_nan=False), encoding="utf-8")
        export_args = argparse.Namespace(
            wards_csv=args.wards_csv,
            sensitivity_csv=args.sensitivity_csv,
            meta_json=args.meta_json,
            cells_csv=args.cells_csv,
            geometry_geojson=args.geometry_geojson,
            validation_json=validation_path,
            ward_output=args.ward_output,
            cell_output=args.cell_output,
            validation_output=args.validation_output,
            figure_dir=args.figure_dir,
            generated_utc=args.generated_utc,
            overwrite=args.overwrite,
        )
        try:
            d8.export_artifacts(export_args)
        except (d8.ExportError, OSError, TypeError, ValueError) as exc:
            _error(report, "d8_export_failed", str(exc))
            report["status"] = "not_ready"
            return report

    produced = [args.ward_output, args.cell_output, args.validation_output]
    if args.figure_dir.exists():
        produced.extend(path for path in args.figure_dir.rglob("*") if path.is_file())
    outputs = [
        {"path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in produced
    ]
    provenance = {
        "report_type": "D8 integration provenance",
        "generated_utc": _utc_now(),
        "readiness_status": "ready",
        "source_inputs": report["inputs"],
        "readiness_checks": report["checks"],
        "outputs": outputs,
        "warnings": report["warnings"],
        "limitations": report["limitations"],
        "h3_contract_checks": "PASS: existing D8 builder validated C2/C3 schemas, ranks, rank ranges, cell IDs, geometry and suppression before writing.",
    }
    try:
        _write_json(args.provenance_output, provenance, args.overwrite)
    except (OSError, d8.ExportError) as exc:
        _error(report, "provenance_write_failed", str(exc))
        report["status"] = "not_ready"
        return report
    report["outputs"] = outputs
    report["provenance_output"] = str(args.provenance_output)
    report["status"] = "ready"
    return report


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wards-csv", type=Path, required=True)
    parser.add_argument("--sensitivity-csv", type=Path, required=True)
    parser.add_argument("--meta-json", type=Path, required=True)
    parser.add_argument("--cells-csv", type=Path, required=True)
    parser.add_argument("--geometry-geojson", type=Path, required=True)
    parser.add_argument("--validation-json", type=Path)
    parser.add_argument("--d6-validation-json", type=Path)
    parser.add_argument("--ward-geometry-geojson", type=Path)
    parser.add_argument("--integration-manifest", type=Path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check D8 intermediate readiness or gate and run the existing C2/C3 exporter."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser(
        "check", help="Validate D8 inputs without generating C2/C3"
    )
    _add_inputs(check_parser)
    check_parser.add_argument("--report-json", type=Path)
    check_parser.add_argument("--overwrite-report", action="store_true")

    run_parser = subparsers.add_parser("run", help="Check readiness, run D8, and write provenance")
    _add_inputs(run_parser)
    run_parser.add_argument("--ward-output", type=Path, required=True)
    run_parser.add_argument("--cell-output", type=Path, required=True)
    run_parser.add_argument("--validation-output", type=Path, required=True)
    run_parser.add_argument("--figure-dir", type=Path, required=True)
    run_parser.add_argument("--provenance-output", type=Path, required=True)
    run_parser.add_argument(
        "--generated-utc", help="Fixed ISO-8601 time for reproducible artifacts"
    )
    run_parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            report = check_readiness(args)
            _print_report(report)
            if args.report_json:
                _write_json(args.report_json, report, args.overwrite_report)
            return 0 if report["status"] == "ready" else 1
        report = run_workflow(args)
        _print_report(report)
        if report.get("outputs"):
            for output in report["outputs"]:
                print(f"OUTPUT {output['path']} sha256={output['sha256']}")
            print(f"PROVENANCE {report['provenance_output']}")
        return 0 if report["status"] == "ready" else 1
    except (d8.ExportError, OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"Integration check error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
