"""Contract-driven D8 exporter for C2/C3 analytics artifacts."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "contracts" / "schemas"
WARD_FIELDS = (
    "ward_id",
    "ward_name",
    "status",
    "n_buildings",
    "n_buildings_with_data",
    "coverage_pct",
    "share_sinking_gt4",
    "vlm_median_mm_yr",
    "beta_p90_horizon",
    "beta_p90_ratio_horizon",
    "gw_stage_pct",
    "gw_category",
    "score",
    "rank",
    "rank_p05",
    "rank_p95",
    "flags",
    "histogram",
)
CELL_FIELDS = (
    "cell_id",
    "ward_id",
    "n_buildings",
    "suppressed",
    "vlm_median_mm_yr",
    "beta_p90_horizon",
    "share_sinking_gt4",
    "cell_score",
    "cell_rank_in_ward",
)
ALLOWED_FLAGS = {
    "sparse_points",
    "groundwater_missing",
    "small_ward",
    "low_coverage",
    "boundary_vintage",
}
NULL_TOKENS = {"", "null", "none", "na", "nan"}


class ExportError(ValueError):
    """Actionable input or contract validation error."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ExportError(f"CSV has no header: {path}")
            return list(reader)
    except OSError as exc:
        raise ExportError(f"Cannot read CSV {path}: {exc}") from exc


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"Cannot read JSON {path}: {exc}") from exc


def _number(value: Any, field: str, *, nullable: bool = True) -> int | float | None:
    if value is None or (isinstance(value, str) and value.strip().lower() in NULL_TOKENS):
        if nullable:
            return None
        raise ExportError(f"Required numeric field '{field}' is empty")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ExportError(f"Field '{field}' must be numeric") from exc
    if not math.isfinite(result):
        raise ExportError(f"Field '{field}' must be finite")
    return result


def _integer(value: Any, field: str, *, nullable: bool = False) -> int | None:
    number = _number(value, field, nullable=nullable)
    if number is None:
        return None
    if not number.is_integer():
        raise ExportError(f"Field '{field}' must be an integer")
    return int(number)


def _boolean(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"true", "1"}:
        return True
    if token in {"false", "0"}:
        return False
    raise ExportError(f"Field '{field}' must be true or false")


def _list_value(value: Any, field: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or str(value).strip().lower() in NULL_TOKENS:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc:
            raise ExportError(f"Field '{field}' must contain a list") from exc
    if not isinstance(parsed, list):
        raise ExportError(f"Field '{field}' must contain a list")
    return parsed


def _require_columns(rows: list[dict[str, Any]], required: set[str], label: str) -> None:
    if not rows:
        raise ExportError(f"{label} has no records")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ExportError(f"{label} is missing required columns: {', '.join(missing)}")


def _timestamp(value: str | None) -> str:
    if value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ExportError("generated_utc must be an ISO-8601 datetime") from exc
        if parsed.tzinfo is None:
            raise ExportError("generated_utc must include a timezone")
        return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate(schema_name: str, payload: dict[str, Any]) -> None:
    schema_path = SCHEMAS / schema_name
    schema = _read_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "document"
        raise ExportError(f"{schema_name} violation at {location}: {first.message}")


def build_ward_summary(
    ward_rows: list[dict[str, str]],
    sensitivity_rows: list[dict[str, str]],
    metadata: dict[str, Any],
    generated_utc: str | None = None,
) -> dict[str, Any]:
    """Map agreed intermediate CSV fields to the frozen C2 ward contract."""
    _require_columns(
        ward_rows,
        set(WARD_FIELDS) - {"rank_p05", "rank_p95"},
        "Ward CSV",
    )
    _require_columns(sensitivity_rows, {"ward_id", "rank_p05", "rank_p95"}, "Sensitivity CSV")
    if not isinstance(metadata, dict):
        raise ExportError("Metadata JSON must be an object")
    meta_required = {"city", "data_vintage", "engine_version", "params", "weights"}
    missing_meta = sorted(meta_required - set(metadata))
    if missing_meta:
        raise ExportError(f"Metadata JSON is missing: {', '.join(missing_meta)}")
    if not isinstance(metadata["params"], dict) or not isinstance(metadata["weights"], dict):
        raise ExportError("Metadata params and weights must be objects")
    coverage_min = _number(
        metadata["params"].get("coverage_min", metadata["params"].get("coverage_min_pct", 0.5)),
        "params.coverage_min",
        nullable=False,
    )
    if coverage_min is None:
        raise ExportError("params.coverage_min is required")
    if 0 < coverage_min <= 1:
        coverage_min *= 100
    if not 0 <= coverage_min <= 100:
        raise ExportError("params.coverage_min must represent a percentage from 0 to 100")
    weights = metadata["weights"]
    if {"i1", "i2", "i3", "i4"} - set(weights):
        raise ExportError("Metadata weights must include i1, i2, i3 and i4")
    weights_out = {key: _number(weights[key], f"weights.{key}") for key in ("i1", "i2", "i3", "i4")}

    range_by_ward: dict[str, tuple[int | None, int | None]] = {}
    for row in sensitivity_rows:
        ward_id = str(row["ward_id"]).strip()
        if not ward_id or ward_id in range_by_ward:
            raise ExportError("Sensitivity CSV has an empty or duplicate ward_id")
        range_by_ward[ward_id] = (
            _integer(row["rank_p05"], "rank_p05", nullable=True),
            _integer(row["rank_p95"], "rank_p95", nullable=True),
        )

    wards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ward_rows:
        ward_id = str(row["ward_id"]).strip()
        if not ward_id or ward_id in seen:
            raise ExportError("Ward CSV has an empty or duplicate ward_id")
        seen.add(ward_id)
        if ward_id not in range_by_ward:
            raise ExportError(f"Sensitivity CSV has no rank range for ward_id {ward_id}")
        status = row["status"].strip()
        if status not in {"ranked", "insufficient_data"}:
            raise ExportError(f"Unknown status for ward_id {ward_id}: {status}")
        n_buildings = _integer(row["n_buildings"], "n_buildings")
        n_with_data = _integer(row["n_buildings_with_data"], "n_buildings_with_data")
        coverage = _number(row["coverage_pct"], "coverage_pct", nullable=False)
        if n_buildings is None or n_with_data is None or coverage is None:
            raise ExportError(f"Building counts and coverage are required for ward_id {ward_id}")
        if not str(row["ward_name"]).strip():
            raise ExportError(f"ward_name is empty for ward_id {ward_id}")
        if n_with_data > n_buildings:
            raise ExportError(f"n_buildings_with_data exceeds n_buildings for ward_id {ward_id}")
        expected_coverage = 0.0 if n_buildings == 0 else 100.0 * n_with_data / n_buildings
        if abs(coverage - expected_coverage) > 0.11:
            raise ExportError(f"coverage_pct disagrees with counts for ward_id {ward_id}")

        flags = _list_value(row["flags"], "flags")
        if any(not isinstance(flag, str) or flag not in ALLOWED_FLAGS for flag in flags):
            raise ExportError(f"Unsupported C2 coverage flag for ward_id {ward_id}")
        rank = _integer(row.get("rank"), "rank", nullable=True)
        rank_p05, rank_p95 = range_by_ward[ward_id]
        if status == "insufficient_data":
            if coverage >= coverage_min or "low_coverage" not in flags:
                raise ExportError(
                    f"Insufficient ward {ward_id} must be below configured coverage and flagged low_coverage"
                )
            if rank is not None or _number(row.get("score"), "score") is not None:
                raise ExportError(f"Insufficient ward {ward_id} cannot have score or rank")
            if rank_p05 is not None or rank_p95 is not None:
                raise ExportError(f"Insufficient ward {ward_id} cannot have rank ranges")
        else:
            if coverage < coverage_min:
                raise ExportError(
                    f"Ranked ward {ward_id} is below the configured coverage threshold"
                )
            if rank is None or rank < 1 or rank_p05 is None or rank_p95 is None:
                raise ExportError(f"Ranked ward {ward_id} requires rank and sensitivity range")
            if rank_p05 > rank or rank > rank_p95:
                raise ExportError(f"Rank range does not bracket rank for ward_id {ward_id}")

        histogram: Any = row.get("histogram")
        if histogram in (None, "") or (
            isinstance(histogram, str) and histogram.strip().lower() in NULL_TOKENS
        ):
            histogram = None
        elif isinstance(histogram, str):
            try:
                histogram = json.loads(histogram)
            except json.JSONDecodeError as exc:
                raise ExportError(f"Invalid histogram JSON for ward_id {ward_id}") from exc

        ward = {
            "ward_id": ward_id,
            "ward_name": str(row["ward_name"]).strip(),
            "status": status,
            "n_buildings": n_buildings,
            "n_buildings_with_data": n_with_data,
            "coverage_pct": coverage,
            "share_sinking_gt4": _number(row.get("share_sinking_gt4"), "share_sinking_gt4"),
            "vlm_median_mm_yr": _number(row.get("vlm_median_mm_yr"), "vlm_median_mm_yr"),
            "beta_p90_horizon": _number(row.get("beta_p90_horizon"), "beta_p90_horizon"),
            "beta_p90_ratio_horizon": row.get("beta_p90_ratio_horizon") or None,
            "gw_stage_pct": _number(row.get("gw_stage_pct"), "gw_stage_pct"),
            "gw_category": row.get("gw_category") or None,
            "score": _number(row.get("score"), "score"),
            "rank": rank,
            "rank_p05": rank_p05,
            "rank_p95": rank_p95,
            "flags": flags,
            "histogram": histogram,
        }
        wards.append(ward)

    ranked = [ward for ward in wards if ward["status"] == "ranked"]
    ranks = [ward["rank"] for ward in ranked]
    if sorted(ranks) != list(range(1, len(ranked) + 1)):
        raise ExportError("Ranked ward ranks must be unique and contiguous from 1 through N")
    if len(range_by_ward) != len(wards):
        raise ExportError("Sensitivity CSV ward set does not exactly match ward CSV")

    output_meta = {
        "city": str(metadata["city"]),
        "data_vintage": str(metadata["data_vintage"]),
        "generated_utc": _timestamp(generated_utc or metadata.get("generated_utc")),
        "engine_version": str(metadata["engine_version"]),
        "params": metadata["params"],
        "weights": weights_out,
        "n_wards": len(wards),
        "n_ranked": len(ranked),
    }
    payload = {"contract": "C2@1.0", "meta": output_meta, "wards": wards}
    _validate("ward_summary.schema.json", payload)
    return payload


def build_cell_scores(
    cell_rows: list[dict[str, str]], geometry_document: dict[str, Any]
) -> dict[str, Any]:
    """Join cell attributes to supplied GeoJSON geometry without fabricating shapes."""
    _require_columns(cell_rows, set(CELL_FIELDS), "Cell CSV")
    if (
        not isinstance(geometry_document, dict)
        or geometry_document.get("type") != "FeatureCollection"
    ):
        raise ExportError("Cell geometry input must be a GeoJSON FeatureCollection")
    crs = geometry_document.get("crs")
    if crs is not None:
        try:
            crs_name = crs["properties"]["name"].upper().replace("::", ":")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ExportError("GeoJSON CRS declaration is malformed") from exc
        if crs_name not in {"EPSG:4326", "URN:OGC:DEF:CRS:EPSG:6.6:4326", "OGC:CRS84"}:
            raise ExportError("Cell geometry CRS must be EPSG:4326 / CRS84")
    features = geometry_document.get("features")
    if not isinstance(features, list):
        raise ExportError("GeoJSON FeatureCollection features must be an array")

    try:
        from shapely.geometry import shape
    except ImportError as exc:
        raise ExportError(
            "Cell geometry validation requires the declared geo dependencies"
        ) from exc

    geometry_by_id: dict[str, dict[str, Any]] = {}
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ExportError("Cell geometry contains a malformed Feature")
        properties = feature.get("properties")
        cell_id = properties.get("cell_id") if isinstance(properties, dict) else None
        geometry = feature.get("geometry")
        if not isinstance(cell_id, str) or not cell_id or cell_id in geometry_by_id:
            raise ExportError("Cell geometry has a missing or duplicate cell_id")
        if not isinstance(geometry, dict):
            raise ExportError(f"Missing geometry for cell_id {cell_id}")
        try:
            decoded = shape(geometry)
        except Exception as exc:
            raise ExportError(f"Invalid geometry for cell_id {cell_id}") from exc
        if (
            decoded.is_empty
            or decoded.geom_type not in {"Polygon", "MultiPolygon"}
            or not decoded.is_valid
        ):
            raise ExportError(
                f"Cell geometry must be a valid non-empty Polygon/MultiPolygon: {cell_id}"
            )
        min_lon, min_lat, max_lon, max_lat = decoded.bounds
        if min_lon < -180 or max_lon > 180 or min_lat < -90 or max_lat > 90:
            raise ExportError(f"Cell geometry coordinates are outside EPSG:4326 bounds: {cell_id}")
        geometry_by_id[cell_id] = geometry

    output_features: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in cell_rows:
        cell_id = str(row["cell_id"]).strip()
        if not cell_id or cell_id in seen or cell_id not in geometry_by_id:
            raise ExportError("Cell CSV has an empty/duplicate cell_id or lacks matching geometry")
        seen.add(cell_id)
        count = _integer(row["n_buildings"], "n_buildings")
        if count is None:
            raise ExportError(f"n_buildings is required for cell_id {cell_id}")
        suppressed = _boolean(row["suppressed"], "suppressed")
        if suppressed != (count < 5):
            raise ExportError(
                f"Suppression does not follow the 5-building rule for cell_id {cell_id}"
            )
        props: dict[str, Any] = {
            "cell_id": cell_id,
            "ward_id": row["ward_id"] or None,
            "n_buildings": count,
            "suppressed": suppressed,
        }
        for field in ("vlm_median_mm_yr", "beta_p90_horizon", "share_sinking_gt4", "cell_score"):
            props[field] = _number(row[field], field)
        props["cell_rank_in_ward"] = _integer(
            row["cell_rank_in_ward"], "cell_rank_in_ward", nullable=True
        )
        if suppressed and any(props[field] is not None for field in CELL_FIELDS[4:]):
            raise ExportError(f"Suppressed cell {cell_id} exposes restricted metrics")
        output_features.append(
            {"type": "Feature", "geometry": geometry_by_id[cell_id], "properties": props}
        )
    if seen != set(geometry_by_id):
        raise ExportError("Cell CSV and geometry inputs must contain exactly the same cell IDs")
    by_ward: dict[str, list[int]] = {}
    for feature in output_features:
        props = feature["properties"]
        rank = props["cell_rank_in_ward"]
        if rank is not None:
            if props["ward_id"] is None:
                raise ExportError("Ranked cell must have a ward_id")
            by_ward.setdefault(props["ward_id"], []).append(rank)
    if any(sorted(ranks) != list(range(1, len(ranks) + 1)) for ranks in by_ward.values()):
        raise ExportError("Cell ranks must be unique and contiguous within each ward")
    payload = {"type": "FeatureCollection", "features": output_features}
    _validate("cell_scores.schema.json", payload)
    return payload


def _default_c3(generated_utc: str) -> dict[str, Any]:
    unavailable = "Not supplied; comparison was not performed."
    return {
        "contract": "C3@1.0",
        "generated_utc": generated_utc,
        "vt_consistency": {
            "n_buildings": 0,
            "spearman_rho": None,
            "labels": ["0", "1", "2", "3", "4"],
            "confusion_matrix": [],
            "note": (
                "Consistency with published categories, not independent ground truth. "
                f"{unavailable} Zero here means no records were processed, not a zero result."
            ),
        },
        "collapse_check": {
            "n_incidents_total": 0,
            "n_in_city": 0,
            "by_published_risk": {},
            "by_rank_band": {},
            "note": (
                "Very small n. No statistical claim. Collapse causes are not attributed to subsidence. "
                f"{unavailable} Zero here means no records were processed; no validation is implied."
            ),
        },
        "hotspot_check": [],
        "robustness": {
            "kendall_tau_weights_mean": None,
            "rank_range_width_median": None,
            "radius_variants": [],
        },
        "fresh_data_check": {
            "status": "not_run",
            "note": (
                "Filled by E7 output if the refresh pipeline ran: dates, area, pattern and sign agreement. "
                f"{unavailable}"
            ),
        },
        "figures": [],
    }


def build_validation_summary(
    validation_input: dict[str, Any] | None, generated_utc: str
) -> dict[str, Any]:
    payload = _default_c3(generated_utc)
    if validation_input is not None:
        if not isinstance(validation_input, dict):
            raise ExportError("Validation input JSON must be an object")
        allowed = {
            "vt_consistency",
            "collapse_check",
            "hotspot_check",
            "robustness",
            "fresh_data_check",
        }
        unknown = set(validation_input) - allowed
        if unknown:
            raise ExportError(f"Unknown C3 sections: {', '.join(sorted(unknown))}")
        for section, value in validation_input.items():
            payload[section] = value
    _validate("validation_summary.schema.json", payload)
    for section in ("vt_consistency", "collapse_check", "fresh_data_check"):
        if not str(payload[section].get("note", "")).strip():
            raise ExportError(f"C3 {section}.note must explain results or unavailability")
    fixed_notes = {
        "vt_consistency": "Consistency with published categories, not independent ground truth.",
        "collapse_check": (
            "Very small n. No statistical claim. Collapse causes are not attributed to subsidence."
        ),
        "fresh_data_check": (
            "Filled by E7 output if the refresh pipeline ran: dates, area, pattern and sign agreement."
        ),
    }
    for section, required_note in fixed_notes.items():
        if required_note not in payload[section]["note"]:
            payload[section]["note"] = f"{required_note} {payload[section]['note']}"
    if not payload["hotspot_check"]:
        payload["vt_consistency"]["note"] += " No hotspot comparison was supplied."
    if any(
        value is None
        for value in (
            payload["robustness"].get("kendall_tau_weights_mean"),
            payload["robustness"].get("rank_range_width_median"),
        )
    ):
        payload["vt_consistency"]["note"] += " Robustness comparisons were not supplied."
    collapse_keys = {"n_incidents_total", "n_in_city", "by_published_risk", "by_rank_band", "note"}
    if set(payload["collapse_check"]) != collapse_keys:
        raise ExportError("C3 collapse_check must contain exactly its five frozen fields")
    robustness_keys = {"kendall_tau_weights_mean", "rank_range_width_median", "radius_variants"}
    if set(payload["robustness"]) != robustness_keys:
        raise ExportError("C3 robustness must contain exactly its documented fields")
    for variant in payload["robustness"]["radius_variants"]:
        if not isinstance(variant, dict) or set(variant) != {"radius_m", "kendall_tau_vs_baseline"}:
            raise ExportError(
                "Each C3 radius variant must contain radius_m and kendall_tau_vs_baseline"
            )
    hotspot_keys = {"name", "source", "ward_id", "rank", "percentile"}
    for hotspot in payload["hotspot_check"]:
        if not isinstance(hotspot, dict) or set(hotspot) != hotspot_keys:
            raise ExportError(
                "Each C3 hotspot_check item must contain exactly the five documented fields"
            )
    if payload["vt_consistency"]["spearman_rho"] is None and not any(
        marker in payload["vt_consistency"]["note"].lower()
        for marker in ("unavailable", "not supplied", "not performed", "not run")
    ):
        raise ExportError("Null C3 Spearman result needs an explanatory unavailability note")
    return payload


def _write_json(path: Path, payload: dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ExportError(f"Output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _make_figures(
    wards: list[dict[str, Any]],
    sensitivity_rows: list[dict[str, str]],
    figure_dir: Path,
    city: str = "",
) -> list[dict[str, str]]:
    figure_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str((figure_dir / ".mplconfig").resolve()))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ExportError("Figure generation requires matplotlib from the geo extra") from exc

    records: list[dict[str, str]] = []
    city_label = city.strip().title()
    prefix = f"{city_label} " if city_label else ""
    ranked = [row for row in wards if row["status"] == "ranked" and row["score"] is not None]
    if ranked:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(
            [row["score"] for row in ranked], bins=min(15, max(5, len(ranked))), color="#386cb0"
        )
        ax.set(
            title=f"{prefix}ward inspection-index score distribution",
            xlabel="Score",
            ylabel="Wards",
        )
        fig.tight_layout()
        name = "ward_score_distribution.png"
        fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
        plt.close(fig)
        records.append(
            {
                "id": "ward_score_distribution",
                "path": str((figure_dir / name).as_posix()),
                "caption": f"{city_label or 'Supplied-city'} ranked-ward scores; no validation comparison.",
            }
        )

        top = sorted(ranked, key=lambda row: row["rank"])[:15]
        if top and all(row["rank_p05"] is not None and row["rank_p95"] is not None for row in top):
            fig, ax = plt.subplots(figsize=(8, 5))
            y = list(range(len(top)))
            ranks = [row["rank"] for row in top]
            low = [row["rank"] - row["rank_p05"] for row in top]
            high = [row["rank_p95"] - row["rank"] for row in top]
            ax.errorbar(ranks, y, xerr=[low, high], fmt="o", capsize=2)
            ax.set_yticks(y, [row["ward_name"] for row in top])
            ax.set(
                title=f"{prefix}top 15 wards: baseline ranks and D4 ranges",
                xlabel="Rank (1 is highest priority)",
            )
            ax.invert_yaxis()
            fig.tight_layout()
            name = "top_priority_ward_ranges.png"
            fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
            plt.close(fig)
            records.append(
                {
                    "id": "top_priority_ward_ranges",
                    "path": str((figure_dir / name).as_posix()),
                    "caption": f"{city_label or 'Supplied-city'} top 15 ward ranks with D4 ranges; descriptive priority, not collapse probability.",
                }
            )

    if ranked and all(
        row["rank_p05"] is not None and row["rank_p95"] is not None for row in ranked
    ):
        ordered = sorted(ranked, key=lambda row: row["rank"])
        fig, ax = plt.subplots(figsize=(8, 4))
        x = list(range(1, len(ordered) + 1))
        y = [row["rank"] for row in ordered]
        low = [row["rank"] - row["rank_p05"] for row in ordered]
        high = [row["rank_p95"] - row["rank"] for row in ordered]
        ax.errorbar(x, y, yerr=[low, high], fmt=".", markersize=3, capsize=1)
        ax.set(
            title=f"{prefix}ward ranks and supplied 5th–95th percentile ranges",
            xlabel="Ward ordered by rank",
            ylabel="Rank (1 is highest)",
        )
        ax.invert_yaxis()
        fig.tight_layout()
        name = "ward_rank_ranges.png"
        fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
        plt.close(fig)
        records.append(
            {
                "id": "ward_rank_ranges",
                "path": str((figure_dir / name).as_posix()),
                "caption": f"{city_label or 'Supplied-city'} rank intervals copied from sensitivity input.",
            }
        )

    if sensitivity_rows and {"rank_min", "rank_max"} <= set(sensitivity_rows[0]):
        usable = [row for row in sensitivity_rows if row.get("rank_min") and row.get("rank_max")]
        if usable:
            mins = [_number(row["rank_min"], "rank_min", nullable=False) for row in usable]
            maxs = [_number(row["rank_max"], "rank_max", nullable=False) for row in usable]
            widths = [hi - lo for lo, hi in zip(mins, maxs)]
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.hist(widths, bins=min(15, max(5, len(widths))), color="#7fc97f")
            ax.set(
                title=f"{prefix}supplied sensitivity rank-range widths",
                xlabel="rank_max − rank_min",
                ylabel="Wards",
            )
            fig.tight_layout()
            name = "sensitivity_rank_range_width.png"
            fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
            plt.close(fig)
            records.append(
                {
                    "id": "sensitivity_rank_range_width",
                    "path": str((figure_dir / name).as_posix()),
                    "caption": f"{city_label or 'Supplied-city'} distribution of rank-range widths in sensitivity CSV.",
                }
            )
    plt.close("all")
    return records


def _make_supplemental_figures(
    figure_data: dict[str, Any],
    validation: dict[str, Any],
    figure_dir: Path,
    city: str,
) -> list[dict[str, str]]:
    """Plot accepted D4/C1 summaries and C3 references without recalculating analytics."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError as exc:
        raise ExportError("Figure generation requires matplotlib from the geo extra") from exc

    label = city.strip().title() or "Supplied city"
    records: list[dict[str, str]] = []
    sensitivity = figure_data.get("weight_sensitivity")
    if isinstance(sensitivity, dict):
        tau = sensitivity.get("kendall_tau_vs_baseline")
        if isinstance(tau, dict) and all(
            isinstance(tau.get(key), (int, float))
            for key in ("minimum", "median", "mean", "maximum")
        ):
            fig, ax = plt.subplots(figsize=(7, 3.5))
            low, median, mean, high = (
                float(tau[key]) for key in ("minimum", "median", "mean", "maximum")
            )
            ax.hlines(0, low, high, color="#386cb0", linewidth=3)
            ax.plot(median, 0, "o", label="Median")
            ax.plot(mean, 0, "D", label="Mean")
            ax.set(xlim=(-1, 1), ylim=(-0.5, 0.5), yticks=[], xlabel="Kendall τ vs baseline")
            ax.set_title(f"{label} D4 weight-perturbation rank stability")
            ax.legend(loc="upper right")
            ax.text(
                0.02,
                0.08,
                f"{sensitivity.get('draws_completed')} draws; descriptive summary",
                transform=ax.transAxes,
            )
            fig.tight_layout()
            name = "weight_perturbation_rank_stability.png"
            fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
            plt.close(fig)
            records.append(
                {
                    "id": "weight_perturbation_rank_stability",
                    "path": str((figure_dir / name).as_posix()),
                    "caption": f"{label} D4 Kendall tau summary across supplied weight perturbations; not an independent validation metric.",
                }
            )

    variants = figure_data.get("a7_variants")
    if isinstance(variants, list) and variants:
        parsed = [row for row in variants if isinstance(row, dict)]
        if parsed:
            fig, ax = plt.subplots(figsize=(9, 4.5))
            pair_labels = sorted(
                {f"{row.get('pair_min_m')}–{row.get('pair_max_m')} m" for row in parsed}
            )
            radius_values = sorted({int(row["radius_m"]) for row in parsed})
            offsets = {
                radius: (index - (len(radius_values) - 1) / 2) * 0.18
                for index, radius in enumerate(radius_values)
            }
            colors = {
                radius: color
                for radius, color in zip(
                    radius_values, ("#1b9e77", "#d95f02", "#7570b3"), strict=False
                )
            }
            for row in parsed:
                x = pair_labels.index(f"{row.get('pair_min_m')}–{row.get('pair_max_m')} m")
                radius = int(row["radius_m"])
                value = row.get("kendall_tau_vs_baseline")
                xpos = x + offsets[radius]
                if isinstance(value, (int, float)):
                    ax.scatter(xpos, float(value), color=colors[radius])
                else:
                    ax.text(
                        xpos,
                        0.035,
                        "n/a",
                        color=colors[radius],
                        ha="center",
                        fontsize=7,
                    )
            ax.set_xticks(range(len(pair_labels)), pair_labels)
            ax.set_ylim(-0.05, 1.05)
            ax.set_ylabel("Kendall τ vs D3 baseline (unavailable shown n/a)")
            ax.set_title(f"{label} A7 radius and pair-window rank sensitivity")
            legend_handles = [
                Line2D([0], [0], marker="o", color=color, linestyle="", label=f"{radius} m")
                for radius, color in colors.items()
            ]
            ax.legend(
                handles=legend_handles,
                title="Radius",
                ncol=len(radius_values),
                loc="lower right",
            )
            fig.tight_layout()
            name = "a7_radius_pair_sensitivity.png"
            fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
            plt.close(fig)
            records.append(
                {
                    "id": "a7_radius_pair_sensitivity",
                    "path": str((figure_dir / name).as_posix()),
                    "caption": f"{label} D4 rank correlations for nine A7 variants; 50 m variants are unavailable because no wards ranked. Parameter hashes differ from baseline C1 where recorded.",
                }
            )

    availability = figure_data.get("c1_availability")
    if isinstance(availability, dict):
        total = availability.get("total_buildings")
        metrics = [
            ("VLM velocity", availability.get("vlm_nonnull")),
            ("Angular distortion", availability.get("beta_horizon_nonnull")),
        ]
        if (
            isinstance(total, int)
            and total > 0
            and all(isinstance(value, int) for _, value in metrics)
        ):
            present = [value for _, value in metrics]
            missing = [total - value for value in present]
            fig, ax = plt.subplots(figsize=(7, 3.5))
            y = list(range(len(metrics)))
            ax.barh(y, present, label="Available", color="#1b9e77")
            ax.barh(y, missing, left=present, label="Unavailable (null)", color="#d9d9d9")
            ax.set_yticks(y, [name for name, _ in metrics])
            ax.set_xlim(0, total)
            ax.set_xlabel("Buildings")
            ax.set_title(f"{label} C1 metric availability")
            ax.legend(loc="lower right")
            for position, value in enumerate(present):
                ax.text(value, position, f" {value:,} available", va="center", fontsize=8)
            fig.tight_layout()
            name = "c1_metric_availability.png"
            fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
            plt.close(fig)
            records.append(
                {
                    "id": "c1_metric_availability",
                    "path": str((figure_dir / name).as_posix()),
                    "caption": f"{label} C1 available and null metric counts; unavailable values are not treated as zero.",
                }
            )

    hotspot_rows = validation.get("hotspot_check")
    if isinstance(hotspot_rows, list) and hotspot_rows:
        fig, ax = plt.subplots(figsize=(7, 4))
        assigned = [
            row
            for row in hotspot_rows
            if isinstance(row, dict) and isinstance(row.get("rank"), int)
        ]
        unassigned = [
            row for row in hotspot_rows if isinstance(row, dict) and row.get("rank") is None
        ]
        if assigned:
            ax.scatter(
                [row["rank"] for row in assigned],
                [row["name"] for row in assigned],
                color="#386cb0",
            )
        if unassigned:
            for row in unassigned:
                ax.text(
                    0.02,
                    0.95 - 0.08 * unassigned.index(row),
                    f"{row['name']}: not comparable",
                    transform=ax.transAxes,
                )
        ax.set_xlim(0, 250)
        ax.invert_xaxis()
        ax.set_xlabel("Ward inspection rank (1 is highest; nulls are not comparable)")
        ax.set_title(f"{label} literature hotspot reference comparison")
        fig.tight_layout()
        name = "literature_hotspot_reference_ranks.png"
        fig.savefig(figure_dir / name, dpi=120, metadata={"Software": "D8 contract exporter"})
        plt.close(fig)
        records.append(
            {
                "id": "literature_hotspot_reference_ranks",
                "path": str((figure_dir / name).as_posix()),
                "caption": f"{label}: approximate reference points only; two of four records have ward ranks. This is supplementary literature consistency, not independent validation.",
            }
        )

    plt.close("all")
    return records


def export_artifacts(args: argparse.Namespace) -> None:
    paths = [
        args.wards_csv,
        args.sensitivity_csv,
        args.meta_json,
        args.cells_csv,
        args.geometry_geojson,
    ]
    for path in paths:
        if not path.is_file():
            raise ExportError(f"Required input does not exist or is not a file: {path}")
    figure_data_path = getattr(args, "figure_data_json", None)
    if figure_data_path is not None and not figure_data_path.is_file():
        raise ExportError(
            f"Supplemental figure input does not exist or is not a file: {figure_data_path}"
        )
    inputs = {path.resolve() for path in paths}
    if figure_data_path is not None:
        inputs.add(figure_data_path.resolve())
    outputs = [args.ward_output, args.cell_output, args.validation_output]
    if len({path.resolve() for path in outputs}) != len(outputs):
        raise ExportError("C2/C3 output paths must be distinct")
    if any(path.resolve() in inputs for path in outputs):
        raise ExportError("An output path cannot overwrite an input artifact")
    if not args.overwrite and any(path.exists() for path in outputs):
        existing = next(path for path in outputs if path.exists())
        raise ExportError(f"Output exists; pass --overwrite to replace it: {existing}")
    if not args.overwrite and args.figure_dir.exists() and any(args.figure_dir.iterdir()):
        raise ExportError(
            f"Figure output directory is not empty; pass --overwrite to replace files: {args.figure_dir}"
        )
    generated = _timestamp(args.generated_utc)
    wards = build_ward_summary(
        _read_csv(args.wards_csv),
        _read_csv(args.sensitivity_csv),
        _read_json(args.meta_json),
        generated,
    )
    cells = build_cell_scores(_read_csv(args.cells_csv), _read_json(args.geometry_geojson))
    validation_input = _read_json(args.validation_json) if args.validation_json else None
    validation = build_validation_summary(validation_input, generated)
    meta_data = _read_json(args.meta_json)
    city = str(meta_data.get("city", "")) if isinstance(meta_data, dict) else ""
    figures = _make_figures(
        wards["wards"], _read_csv(args.sensitivity_csv), args.figure_dir, city=city
    )
    if figure_data_path is not None:
        figure_data = _read_json(figure_data_path)
        if not isinstance(figure_data, dict):
            raise ExportError("Supplemental figure data must be a JSON object")
        figures.extend(_make_supplemental_figures(figure_data, validation, args.figure_dir, city))
    for figure in figures:
        figure_path = args.figure_dir / Path(figure["path"]).name
        figure["path"] = Path(
            os.path.relpath(figure_path, args.validation_output.parent)
        ).as_posix()
    validation["figures"] = figures
    _validate("validation_summary.schema.json", validation)

    # Validate all payloads before writing any output file.
    _write_json(args.ward_output, wards, args.overwrite)
    _write_json(args.cell_output, cells, args.overwrite)
    _write_json(args.validation_output, validation, args.overwrite)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export contract-validated C2/C3 artifacts from explicit analytics intermediates."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export", help="Build C2 ward/cell and C3 outputs")
    export_parser.add_argument("--wards-csv", type=Path, required=True)
    export_parser.add_argument("--sensitivity-csv", type=Path, required=True)
    export_parser.add_argument("--meta-json", type=Path, required=True)
    export_parser.add_argument("--cells-csv", type=Path, required=True)
    export_parser.add_argument("--geometry-geojson", type=Path, required=True)
    export_parser.add_argument("--validation-json", type=Path)
    export_parser.add_argument("--ward-output", type=Path, required=True)
    export_parser.add_argument("--cell-output", type=Path, required=True)
    export_parser.add_argument("--validation-output", type=Path, required=True)
    export_parser.add_argument("--figure-dir", type=Path, required=True)
    export_parser.add_argument(
        "--figure-data-json",
        type=Path,
        help="Optional accepted D4/C1 summary data for supplementary figures",
    )
    export_parser.add_argument(
        "--generated-utc", help="Fixed ISO-8601 timestamp for reproducible output"
    )
    export_parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        export_artifacts(args)
    except ExportError as exc:
        parser.exit(2, f"D8 export error: {exc}\n")
    print(
        f"C2/C3 export complete: {args.ward_output}, {args.cell_output}, {args.validation_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
