"""D2 CGWB groundwater context preparation with conservative proxy handling.

CGWB assessment attributes are not assigned to wards unless supported
assessment-unit boundaries are available. Provisional subdistrict polygons
may be audited and exported separately as exploratory estimates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.ops import unary_union

AREA_CRS = "EPSG:32643"
AREA_WARNING_PCT = 10.0
EXPECTED_CATEGORY_COUNTS = {
    "safe": 7,
    "semi critical": 6,
    "critical": 11,
    "overexploited": 10,
}
REQUIRED_ASSESSMENT_COLUMNS = {
    "district",
    "assessment_unit_name",
    "total_area_of_assessment_unit_ha",
    "stage_of_groundwater_extraction_pct",
    "categorization",
}
OUTPUT_COLUMNS = [
    "ward_id",
    "ward_name",
    "gw_stage_pct",
    "gw_category",
    "gw_coverage_pct",
    "gw_stage_coverage_pct",
    "gw_assessment_units",
]
ALIASES = {
    "DELHICANTONMENT": "DELHICANTT",
    "NAZURLAND": "NAZUL",
}


class D2Error(ValueError):
    """Invalid D2 input or unsafe output operation."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: Any) -> str:
    """Normalize documented spelling/spacing variations for QA matching only."""
    if pd.isna(value):
        return ""
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return ALIASES.get(normalized, normalized)


def validate_assessment_table(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load and validate the extracted 34-row CGWB source table."""
    if not path.is_file():
        raise D2Error("Assessment table path is not a file")
    try:
        assessment = pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise D2Error("Unable to read CGWB assessment table") from exc
    missing = REQUIRED_ASSESSMENT_COLUMNS - set(assessment.columns)
    if missing:
        raise D2Error(f"Assessment table is missing required columns: {sorted(missing)}")
    if len(assessment) != 34:
        raise D2Error(f"Expected 34 CGWB assessment units; found {len(assessment)}")
    key_columns = ["district", "assessment_unit_name"]
    if assessment[key_columns].isna().any().any():
        raise D2Error("CGWB district and assessment-unit names must be present")
    if assessment.duplicated(key_columns).any():
        raise D2Error("Duplicate district and assessment-unit keys in CGWB table")
    if assessment["assessment_unit_name"].map(normalize_name).duplicated().any():
        raise D2Error("Assessment-unit names are ambiguous after documented normalization")

    categories = assessment["categorization"].astype("string").str.strip().str.casefold()
    category_counts = {str(key): int(value) for key, value in categories.value_counts().items()}
    if category_counts != EXPECTED_CATEGORY_COUNTS:
        raise D2Error("CGWB category counts do not match the verified 2025 extraction")
    stages = pd.to_numeric(assessment["stage_of_groundwater_extraction_pct"], errors="coerce")
    areas = pd.to_numeric(assessment["total_area_of_assessment_unit_ha"], errors="coerce")
    if stages.isna().any() or not stages.map(math.isfinite).all() or (stages < 0).any():
        raise D2Error("CGWB extraction stages must be finite nonnegative numbers")
    if areas.isna().any() or not areas.map(math.isfinite).all() or (areas <= 0).any():
        raise D2Error("CGWB reported assessment areas must be finite positive numbers")
    qa = {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "rows": len(assessment),
        "category_counts": category_counts,
        "expected_category_counts": EXPECTED_CATEGORY_COUNTS,
        "category_counts_match": True,
        "missing_key_or_stage_or_area": 0,
        "stage_range_pct": [float(stages.min()), float(stages.max())],
    }
    return assessment, qa


def _validate_ward_frame(
    wards: gpd.GeoDataFrame,
    expected_wards: int | None = None,
    *,
    require_wgs84: bool = True,
) -> None:
    required = {"ward_id", "ward_name", "geometry"}
    missing = required - set(wards.columns)
    if missing:
        raise D2Error(f"Ward geometry is missing columns: {sorted(missing)}")
    if wards.crs is None:
        raise D2Error("Ward geometries must have a declared CRS")
    if require_wgs84 and wards.crs.to_epsg() != 4326:
        raise D2Error("Ward geometries must have a declared EPSG:4326 CRS")
    if wards["ward_id"].isna().any() or wards["ward_id"].astype(str).str.strip().eq("").any():
        raise D2Error("Ward IDs must be non-null and non-empty")
    if wards["ward_id"].astype(str).duplicated().any():
        raise D2Error("Ward IDs must be unique")
    if wards["ward_name"].isna().any():
        raise D2Error("Ward names must be non-null")
    if expected_wards is not None and len(wards) != expected_wards:
        raise D2Error(f"Expected {expected_wards} wards; found {len(wards)}")
    _validate_polygon_geometries(wards, "ward")


def _validate_polygon_geometries(frame: gpd.GeoDataFrame, label: str) -> None:
    geometry = frame.geometry
    if geometry.isna().any() or geometry.is_empty.any():
        raise D2Error(f"{label.capitalize()} geometries cannot be null or empty")
    if not geometry.is_valid.all():
        raise D2Error(
            f"{label.capitalize()} geometries contain invalid shapes; no repair was applied"
        )
    if not geometry.geom_type.isin({"Polygon", "MultiPolygon"}).all():
        raise D2Error(f"{label.capitalize()} geometries must be Polygon or MultiPolygon")


def _metric_crs(value: str) -> CRS:
    try:
        crs = CRS.from_user_input(value)
    except (TypeError, ValueError) as exc:
        raise D2Error("Area analysis CRS is invalid") from exc
    if not crs.is_projected or len(crs.axis_info) < 2:
        raise D2Error("Area analysis CRS must be projected")
    if any(not math.isclose(axis.unit_conversion_factor, 1.0) for axis in crs.axis_info[:2]):
        raise D2Error("Area analysis CRS axes must use metres")
    return crs


def missing_groundwater_context(wards: gpd.GeoDataFrame) -> pd.DataFrame:
    """Return D3-compatible rows with unavailable groundwater values left null."""
    _validate_ward_frame(wards)
    result = wards[["ward_id", "ward_name"]].copy()
    result["ward_id"] = result["ward_id"].astype(str)
    for column in OUTPUT_COLUMNS[2:]:
        result[column] = pd.NA
    result = result[OUTPUT_COLUMNS]
    if len(result) != wards["ward_id"].nunique() or result["ward_id"].duplicated().any():
        raise D2Error("Missing-data groundwater output is not one row per ward")
    return result


def _validate_proxy_frame(units: gpd.GeoDataFrame) -> None:
    required = {"SUB_DIST", "DISTRICT", "geometry"}
    missing = required - set(units.columns)
    if missing:
        raise D2Error(f"Proxy boundary layer is missing columns: {sorted(missing)}")
    if units.crs is None:
        raise D2Error("Proxy boundary layer must have a declared CRS")
    if units["SUB_DIST"].isna().any():
        raise D2Error("Proxy assessment-unit names must be present")
    if units["SUB_DIST"].map(normalize_name).duplicated().any():
        raise D2Error("Proxy assessment-unit names are ambiguous after normalization")
    _validate_polygon_geometries(units, "proxy assessment-unit")


def audit_proxy_boundaries(
    assessment: pd.DataFrame,
    units: gpd.GeoDataFrame,
    wards: gpd.GeoDataFrame,
    *,
    area_crs: str = AREA_CRS,
    area_warning_pct: float = AREA_WARNING_PCT,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Measure name, district, area, overlap and ward-coverage compatibility.

    These diagnostics do not establish that proxy polygons are CGWB
    assessment-unit boundaries.
    """
    _validate_proxy_frame(units)
    _validate_ward_frame(wards)
    if not units.crs.is_projected:
        raise D2Error("Proxy polygons must use a projected CRS before area analysis")
    area_crs = _metric_crs(area_crs).to_string()
    assessment = assessment.copy()
    units = units.copy()
    assessment["_match_key"] = assessment["assessment_unit_name"].map(normalize_name)
    units["_match_key"] = units["SUB_DIST"].map(normalize_name)
    if assessment["_match_key"].duplicated().any() or units["_match_key"].duplicated().any():
        raise D2Error("Assessment-unit correspondence is ambiguous")
    correspondence = assessment.merge(
        units[["_match_key", "SUB_DIST", "DISTRICT", "geometry"]],
        on="_match_key",
        how="outer",
        indicator=True,
        validate="one_to_one",
        suffixes=("_cgwb", "_proxy"),
    )
    unmatched_table = correspondence.loc[correspondence["_merge"] != "both"]
    matched = correspondence.loc[correspondence["_merge"] == "both"].copy()
    matched_geo = gpd.GeoDataFrame(matched, geometry="geometry", crs=units.crs)
    metric_units = matched_geo.to_crs(area_crs)
    metric_wards = wards.to_crs(area_crs)

    area_comparison = []
    for row in metric_units.itertuples(index=False):
        reported = float(row.total_area_of_assessment_unit_ha)
        polygon_area = float(row.geometry.area / 10000.0)
        difference = abs(polygon_area - reported) / reported * 100.0
        district_match = normalize_name(row.district) == normalize_name(row.DISTRICT)
        area_comparison.append(
            {
                "assessment_unit": str(row.SUB_DIST),
                "cgwb_district": str(row.district),
                "proxy_district": str(row.DISTRICT),
                "district_match": district_match,
                "reported_area_ha": reported,
                "proxy_polygon_area_ha": polygon_area,
                "area_difference_pct": difference,
                "warning_over_threshold": difference > area_warning_pct,
            }
        )

    overlaps = []
    for first in range(len(metric_units)):
        for second in range(first + 1, len(metric_units)):
            overlap_area = float(
                metric_units.geometry.iloc[first]
                .intersection(metric_units.geometry.iloc[second])
                .area
            )
            if overlap_area > 1.0:
                overlaps.append(
                    {
                        "unit_a": str(metric_units.iloc[first]["SUB_DIST"]),
                        "unit_b": str(metric_units.iloc[second]["SUB_DIST"]),
                        "overlap_area_m2": overlap_area,
                    }
                )

    proxy_union = unary_union(metric_units.geometry.tolist()) if len(metric_units) else None
    coverage = []
    coverage_by_ward = []
    if proxy_union is not None:
        for row in metric_wards.itertuples(index=False):
            ward_area = float(row.geometry.area)
            if ward_area <= 0:
                raise D2Error("Ward geometry has non-positive area")
            covered_area = float(row.geometry.intersection(proxy_union).area)
            uncovered_area = max(ward_area - covered_area, 0.0)
            coverage_pct = covered_area / ward_area * 100.0
            coverage.append(coverage_pct)
            coverage_by_ward.append(
                {
                    "ward_id": str(row.ward_id),
                    "ward_area_m2": ward_area,
                    "covered_area_m2": covered_area,
                    "uncovered_area_m2": uncovered_area,
                    "coverage_pct": coverage_pct,
                }
            )

    differences = [item["area_difference_pct"] for item in area_comparison]
    district_mismatches = [item for item in area_comparison if not item["district_match"]]
    coverage_summary = None
    if coverage:
        ward_union = unary_union(metric_wards.geometry.tolist())
        coverage_summary = {
            "wards": len(coverage),
            "min_pct": min(coverage),
            "mean_pct": sum(coverage) / len(coverage),
            "max_pct": max(coverage),
            "wards_below_95_pct": sum(value < 95.0 for value in coverage),
            "ward_union_uncovered_by_proxy_m2": float(ward_union.difference(proxy_union).area),
            "proxy_area_outside_ward_union_m2": float(proxy_union.difference(ward_union).area),
            "per_ward_denominator": "full ward polygon area in area_crs",
            "wards_below_95_ids": [
                str(metric_wards.iloc[index]["ward_id"])
                for index, value in enumerate(coverage)
                if value < 95.0
            ],
            "by_ward": coverage_by_ward,
        }
    report = {
        "status": "exploratory_proxy_only",
        "boundary_authority": "not established as CGWB assessment-unit boundaries",
        "proxy_rows": len(units),
        "name_correspondence": {
            "matched": len(matched),
            "unmatched_cgwb_units": sorted(
                unmatched_table.loc[
                    unmatched_table["_merge"] == "left_only", "assessment_unit_name"
                ]
                .astype(str)
                .tolist()
            ),
            "unmatched_proxy_units": sorted(
                unmatched_table.loc[unmatched_table["_merge"] == "right_only", "SUB_DIST"]
                .astype(str)
                .tolist()
            ),
            "district_mismatches": district_mismatches,
        },
        "area_comparison": {
            "area_crs": area_crs,
            "units_compared": len(differences),
            "warning_threshold_pct": area_warning_pct,
            "min_difference_pct": min(differences) if differences else None,
            "median_difference_pct": float(pd.Series(differences).median())
            if differences
            else None,
            "max_difference_pct": max(differences) if differences else None,
            "units_over_threshold": [
                item["assessment_unit"]
                for item in area_comparison
                if item["warning_over_threshold"]
            ],
            "by_unit": area_comparison,
        },
        "overlaps": {"pairs_over_1m2": len(overlaps), "details": overlaps},
        "ward_union_coverage": coverage_summary,
        "limitations": [
            "Name agreement is not proof that subdistrict polygons match CGWB assessment-unit boundaries.",
            "District and reported-area discrepancies indicate unresolved correspondence risk.",
            "Ward coverage is descriptive for these proxy polygons only.",
        ],
    }
    return metric_units, report


def allocate_groundwater(
    wards: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    *,
    area_crs: str = AREA_CRS,
) -> pd.DataFrame:
    """Calculate exploratory area-weighted values for verified synthetic inputs.

    The caller is responsible for establishing that input units are authoritative.
    Overlapping unit polygons are rejected to prevent double-counting.
    """
    _validate_ward_frame(wards, require_wgs84=False)
    _validate_proxy_frame(units)
    if "stage_of_groundwater_extraction_pct" not in units or "categorization" not in units:
        raise D2Error("Assessment-unit attributes are missing stage or categorization")
    area_crs = _metric_crs(area_crs).to_string()
    metric_wards = wards.to_crs(area_crs)
    metric_units = units.to_crs(area_crs)
    for first in range(len(metric_units)):
        for second in range(first + 1, len(metric_units)):
            if (
                metric_units.geometry.iloc[first]
                .intersection(metric_units.geometry.iloc[second])
                .area
                > 1.0
            ):
                raise D2Error("Assessment-unit polygons overlap; area weighting would double-count")

    records = []
    for ward in metric_wards.itertuples(index=False):
        ward_area = float(ward.geometry.area)
        if ward_area <= 0:
            raise D2Error("Ward geometry has non-positive area")
        intersections = []
        for unit in metric_units.itertuples(index=False):
            if not ward.geometry.intersects(unit.geometry):
                continue
            area = float(ward.geometry.intersection(unit.geometry).area)
            if area > 0:
                intersections.append((unit, area))
        total_area = sum(area for _, area in intersections)
        valued = [
            (unit, area, float(unit.stage_of_groundwater_extraction_pct))
            for unit, area in intersections
            if pd.notna(unit.stage_of_groundwater_extraction_pct)
        ]
        stage_area = sum(area for _, area, _ in valued)
        stage = sum(area * value for _, area, value in valued) / stage_area if stage_area else None
        category_area: dict[str, float] = {}
        for unit, area in intersections:
            if pd.notna(unit.categorization) and str(unit.categorization).strip():
                category = str(unit.categorization).strip()
                category_area[category] = category_area.get(category, 0.0) + area
        category = (
            min(category_area, key=lambda name: (-category_area[name], name))
            if category_area
            else None
        )
        names = sorted({str(unit.SUB_DIST) for unit, _ in intersections})
        records.append(
            {
                "ward_id": str(ward.ward_id),
                "ward_name": str(ward.ward_name),
                "gw_stage_pct": round(stage, 4) if stage is not None else None,
                "gw_category": category,
                "gw_coverage_pct": round(min(total_area / ward_area * 100.0, 100.0), 4),
                "gw_stage_coverage_pct": round(min(stage_area / ward_area * 100.0, 100.0), 4),
                "gw_assessment_units": ";".join(names) if names else None,
            }
        )
    result = pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)
    if result["ward_id"].duplicated().any() or len(result) != len(wards):
        raise D2Error("Groundwater allocation did not produce exactly one row per ward")
    return result


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _proxy_files(path: Path) -> list[Path]:
    """Return local shapefile components used for provenance hashing."""
    return sorted(
        item
        for item in path.parent.glob(path.stem + ".*")
        if item.is_file()
        and item.suffix.lower() in {".shp", ".shx", ".dbf", ".prj", ".cpg", ".xml"}
    )


def run_d2(args: argparse.Namespace) -> dict[str, Any]:
    assessment, assessment_qa = validate_assessment_table(args.assessment_csv)
    wards = gpd.read_file(args.wards_geojson)
    _validate_ward_frame(wards, args.expected_wards)
    context = missing_groundwater_context(wards)

    inputs = {
        "assessment_csv": _input_record(args.assessment_csv),
        "ward_geojson": _input_record(args.wards_geojson),
    }
    source_pdf = getattr(args, "source_pdf", None)
    if source_pdf is not None:
        if not source_pdf.is_file():
            raise D2Error("Configured CGWB source PDF is not a file")
        inputs["cgwb_source_pdf"] = _input_record(source_pdf)
    proxy_report: dict[str, Any] = {
        "available": False,
        "status": "unavailable",
        "note": "No verified CGWB assessment-unit boundary input was supplied.",
    }
    exploratory = None
    if args.proxy_boundaries is not None:
        proxy_path = args.proxy_boundaries
        if not proxy_path.is_file():
            raise D2Error("Configured proxy boundary path is not a file")
        try:
            proxy_units = gpd.read_file(proxy_path)
        except (OSError, ValueError, RuntimeError) as exc:
            raise D2Error("Unable to read proxy boundary layer") from exc
        for component in _proxy_files(proxy_path):
            inputs[
                f"proxy_boundary_{component.suffix.lower().lstrip('.')}"
                if component.suffix.lower() != ".xml"
                else "proxy_boundary_metadata_xml"
            ] = _input_record(component)
        matched_units, proxy_report = audit_proxy_boundaries(
            assessment,
            proxy_units,
            wards,
            area_crs=args.area_crs,
        )
        proxy_report.update(
            {
                "available": True,
                "source_path": str(proxy_path.resolve()),
                "source_file_hashes": {
                    component.name: sha256_file(component) for component in _proxy_files(proxy_path)
                },
                "source_vintage": "not established by available provenance metadata",
                "source_claim": "Survey of India Delhi subdistrict proxy, as described in Person D reference implementation",
                "used_for_authoritative_d3_input": False,
            }
        )
        if args.exploratory_proxy_output is not None:
            if (
                len(matched_units) != 34
                or proxy_report["name_correspondence"]["unmatched_proxy_units"]
                or proxy_report["name_correspondence"]["unmatched_cgwb_units"]
            ):
                raise D2Error(
                    "Cannot create exploratory proxy output with incomplete or ambiguous unit correspondence"
                )
            # Match assessed attributes onto the unique geometry key. This output is expressly exploratory.
            matched_units["stage_of_groundwater_extraction_pct"] = pd.to_numeric(
                matched_units["stage_of_groundwater_extraction_pct"], errors="raise"
            )
            exploratory = allocate_groundwater(wards, matched_units, area_crs=args.area_crs)
            proxy_report["exploratory_output"] = str(args.exploratory_proxy_output)
            proxy_report["exploratory_values_are_authoritative"] = False

    qa = {
        "project": "Delhi Groundwater Context D2",
        "contract": "C0@1.0 attributes; D2 output for D3 consumption",
        "assessment_source": {
            **assessment_qa,
            "report_pdf": inputs.get("cgwb_source_pdf"),
            "report_title": "Dynamic Ground Water Resources of NCT Delhi, 2025",
            "source_table": "Annexure VI, Assessment Unit Wise Report (Attribute Table)",
            "source_pages": [79, 80],
            "category_counts": EXPECTED_CATEGORY_COUNTS,
        },
        "inputs": inputs,
        "ward_output": {
            "path": str(args.output_csv.resolve()),
            "rows": len(context),
            "unique_ward_ids": int(context["ward_id"].nunique()),
            "stage_values_available": 0,
            "stage_values_unavailable": len(context),
            "stage_and_category_are_null": True,
            "schema": {
                column: ("string" if column in {"ward_id", "ward_name"} else "nullable")
                for column in OUTPUT_COLUMNS
            },
        },
        "boundary_method": "No proxy assigned to authoritative groundwater_context.csv because matching CGWB assessment-unit boundaries are unverified.",
        "proxy_boundary_audit": proxy_report,
        "d3_compatibility": {
            "gw_stage_pct": "null for all wards; D3 should use documented missing-I4 fallback and renormalize available weights",
            "missing_flag": "D1/D3 should retain groundwater_missing where applicable",
            "proxy_estimates_in_authoritative_file": False,
        },
        "limitations": [
            "CGWB table attributes are verified, but corresponding assessment-unit boundary polygons are not.",
            "Survey of India subdistrict geometry is a provisional proxy; name agreement does not establish boundary equivalence.",
            "The proxy contains one CGWB/proxy district mismatch and five greater-than-10-percent reported-area differences.",
            "No official assessment-unit polygons were fabricated or substituted.",
            "Exploratory proxy estimates, if generated, are not authoritative D3 input.",
        ],
        "internal_use_restriction": "Internal prototype only; ward-source licence remains unresolved.",
    }
    outputs = [args.output_csv, args.qa_json]
    if exploratory is not None:
        outputs.append(args.exploratory_proxy_output)
    resolved_inputs = {path.resolve() for path in [args.assessment_csv, args.wards_geojson]}
    if args.proxy_boundaries is not None:
        resolved_inputs.add(args.proxy_boundaries.resolve())
    if len({path.resolve() for path in outputs}) != len(outputs):
        raise D2Error("D2 output paths must be unique")
    if any(path.resolve() in resolved_inputs for path in outputs):
        raise D2Error("D2 output must not overwrite an input artifact")
    if not args.overwrite and any(path.exists() for path in outputs):
        raise D2Error("D2 output exists; choose a new versioned directory or pass --overwrite")
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    try:
        for target, writer in (
            (args.output_csv, lambda path: context.to_csv(path, index=False)),
            (
                args.qa_json,
                lambda path: path.write_text(
                    json.dumps(qa, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8",
                ),
            ),
            *(
                [
                    (
                        args.exploratory_proxy_output,
                        lambda path: exploratory.to_csv(path, index=False),
                    )
                ]
                if exploratory is not None
                else []
            ),
        ):
            temp_path = target.with_suffix(target.suffix + ".tmp")
            writer(temp_path)
            temporary.append((temp_path, target))
        for temp_path, target in temporary:
            os.replace(temp_path, target)
    except OSError:
        for temp_path, _ in temporary:
            temp_path.unlink(missing_ok=True)
        raise
    return qa


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare D2 groundwater context from explicit CGWB and ward inputs"
    )
    parser.add_argument("--assessment-csv", type=Path, required=True)
    parser.add_argument(
        "--source-pdf", type=Path, help="Optional original CGWB report for provenance hashing"
    )
    parser.add_argument("--wards-geojson", type=Path, required=True)
    parser.add_argument(
        "--output-csv",
        type=Path,
        required=True,
        help="Authoritative null-preserving groundwater_context.csv",
    )
    parser.add_argument("--qa-json", type=Path, required=True)
    parser.add_argument(
        "--proxy-boundaries", type=Path, help="Optional provisional polygons for QA only"
    )
    parser.add_argument(
        "--exploratory-proxy-output",
        type=Path,
        help="Separate non-authoritative exploratory CSV; requires --proxy-boundaries",
    )
    parser.add_argument("--expected-wards", type=int, default=250)
    parser.add_argument(
        "--area-crs", default=AREA_CRS, help="Projected CRS with metre axes for area calculations"
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.exploratory_proxy_output is not None and args.proxy_boundaries is None:
        parser.error("--exploratory-proxy-output requires --proxy-boundaries")
    try:
        qa = run_d2(args)
    except (D2Error, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"D2 failed: {exc}\n")
    print(
        f"D2 prepared {qa['ward_output']['rows']} wards; "
        f"authoritative groundwater values available: {qa['ward_output']['stage_values_available']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
