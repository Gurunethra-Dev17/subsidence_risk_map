"""Safe adapter from optional E7 status manifests to the C3 status field."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NOT_RUN = {
    "status": "not_run",
    "note": (
        "No valid E7 dry-run manifest is configured; no refresh processing has "
        "been verified and no displacement product is available."
    ),
}
DRY_RUN_NOTE = (
    "ASF catalog metadata contains a repeat-pass VV shortlist; no HyP3 job was "
    "submitted and no displacement product is available."
)
PROCESSED_NOTE = (
    "An ASF HyP3 fresh InSAR product is available for {reference} to {secondary}. "
    "The historical pattern/sign comparison and independent validation were not run; "
    "this is relative line-of-sight motion, not vertical subsidence, and existing risk scores are unchanged."
)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(UTC)


def _valid_dry_run_manifest(manifest: Any) -> bool:
    if not isinstance(manifest, dict):
        return False
    if (
        manifest.get("processing_status") != "not_submitted"
        or manifest.get("hyp3_eligibility") != "unverified"
        or manifest.get("displacement_product") != "not_available"
        or manifest.get("polarization") != "VV"
    ):
        return False
    required_strings = (
        "source_pair_report",
        "reference_scene_id",
        "secondary_scene_id",
        "full_burst_id",
        "flight_direction",
        "data_provenance",
    )
    if any(not isinstance(manifest.get(key), str) or not manifest[key] for key in required_strings):
        return False
    if manifest["reference_scene_id"] == manifest["secondary_scene_id"]:
        return False
    if manifest["flight_direction"] not in {"ASCENDING", "DESCENDING"}:
        return False
    if not (
        "Real ASF catalog metadata" in manifest["data_provenance"]
        and "not processed InSAR measurements" in manifest["data_provenance"]
    ):
        return False
    if _timestamp(manifest.get("generated_utc")) is None:
        return False
    reference = _timestamp(manifest.get("reference_acquisition_time"))
    secondary = _timestamp(manifest.get("secondary_acquisition_time"))
    if reference is None or secondary is None or secondary <= reference:
        return False
    if reference.date() == secondary.date():
        return False
    orbit = manifest.get("relative_orbit")
    separation = manifest.get("temporal_separation_days")
    if isinstance(orbit, bool) or not isinstance(orbit, int | float) or not math.isfinite(orbit):
        return False
    if (
        isinstance(separation, bool)
        or not isinstance(separation, int | float)
        or not math.isfinite(separation)
        or separation <= 0
    ):
        return False
    expected = (secondary - reference).total_seconds() / 86400
    return math.isclose(separation, expected, rel_tol=1e-9, abs_tol=1e-9)


def _valid_product_status_manifest(manifest: Any) -> bool:
    if not isinstance(manifest, dict):
        return False
    if (
        manifest.get("schema") != "E7_PRODUCT_STATUS@1.0"
        or manifest.get("processing_status") != "processed"
        or manifest.get("fresh_data_check_status") != "not_run"
        or manifest.get("api_status") != "processed_not_validated"
        or manifest.get("polarization") != "VV"
        or manifest.get("flight_direction") not in {"ASCENDING", "DESCENDING"}
    ):
        return False
    if not isinstance(manifest.get("product_id"), str) or not manifest["product_id"]:
        return False
    reference = manifest.get("reference_acquisition_date")
    secondary = manifest.get("secondary_acquisition_date")
    try:
        reference_date = datetime.strptime(reference, "%Y-%m-%d").date()
        secondary_date = datetime.strptime(secondary, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    separation = manifest.get("temporal_separation_days")
    if isinstance(separation, bool) or not isinstance(separation, int):
        return False
    if (secondary_date - reference_date).days != separation or separation <= 0:
        return False
    threshold = manifest.get("coherence_threshold")
    coverage = manifest.get(
        "usable_pixel_intersection_area_pct_of_ward_union",
        manifest.get("usable_pixel_area_estimate_pct_of_ward_union"),
    )
    for value, low, high in ((threshold, 0, 1), (coverage, 0, 100)):
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not low < value <= high
        ):
            return False
    targets = manifest.get("target_ward_coverage")
    if not isinstance(targets, dict):
        return False
    for name in ("BIJWASAN", "MAHIPALPUR"):
        row = targets.get(name)
        if not isinstance(row, dict) or not isinstance(row.get("ward_id"), str):
            return False
        value = row.get(
            "usable_pixel_intersection_area_pct", row.get("usable_pixel_area_estimate_pct")
        )
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            return False
    return True


def validation_with_insar_status(
    validation_summary: dict[str, Any], manifest_path: str | Path | None = None
) -> dict[str, Any]:
    """Copy C3 and update only ``fresh_data_check`` from an optional E7 manifest.

    The path is explicit via argument or ``API_INSAR_MANIFEST_PATH``. Dry-run
    discovery and processed-product status have separate validators. There is
    intentionally no repository-local output default, so hosted deployments
    without an ignored local manifest retain a truthful not-run status.
    """
    configured = manifest_path
    if configured is None:
        configured = os.getenv("API_INSAR_MANIFEST_PATH")
    status = NOT_RUN.copy()
    if configured and str(configured).strip():
        try:
            with Path(configured).expanduser().open(encoding="utf-8") as stream:
                manifest = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError):
            manifest = None
        if _valid_product_status_manifest(manifest):
            status = {
                "status": "processed_not_validated",
                "note": PROCESSED_NOTE.format(
                    reference=manifest["reference_acquisition_date"],
                    secondary=manifest["secondary_acquisition_date"],
                ),
            }
        elif _valid_dry_run_manifest(manifest):
            status = {"status": "not_submitted", "note": DRY_RUN_NOTE}

    result = dict(validation_summary)
    result["fresh_data_check"] = status
    return result
