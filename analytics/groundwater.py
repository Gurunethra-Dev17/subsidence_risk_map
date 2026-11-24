
from pathlib import Path
import json
import re
import sys

import geopandas as gpd
import pandas as pd


# ==================================================
# 1. PATHS AND CONFIGURATION
# ==================================================

ROOT = Path(__file__).resolve().parent.parent

CSV_PATH = (
    ROOT / "data" / "groundwater" / "raw"
    / "cgwb_delhi_2025_assessment_units.csv"
)

SHAPE_PATH = (
    ROOT / "data" / "groundwater" / "raw"
    / "CGWB" / "07" / "DELHI_SUBDISTRICT_BDY.shp"
)

WARDS_PATH = ROOT / "data" / "wards.geojson"

OUTPUT_DIR = ROOT / "out" / "d2"
OUTPUT_CSV = OUTPUT_DIR / "groundwater_context.csv"
QA_JSON = OUTPUT_DIR / "groundwater_qa.json"

AREA_CRS = "EPSG:32643"
AREA_WARNING_PCT = 10.0


# ==================================================
# 2. NAME NORMALIZATION
# ==================================================

ALIASES = {
    "DELHICANTONMENT": "DELHICANTT",
    "NAZURLAND": "NAZUL",
}


def normalize_name(value):
    if pd.isna(value):
        return ""

    name = re.sub(r"[^A-Z0-9]", "", str(value).upper())

    return ALIASES.get(name, name)


# ==================================================
# 3. LOAD AND VALIDATE INPUTS
# ==================================================

def check_inputs():
    for path in [CSV_PATH, SHAPE_PATH, WARDS_PATH]:
        if not path.exists():
            raise FileNotFoundError(
                f"Input file not found: {path}"
            )


def load_inputs():
    print("Loading groundwater assessment data...")

    assessment = pd.read_csv(CSV_PATH)
    units = gpd.read_file(SHAPE_PATH)
    wards = gpd.read_file(WARDS_PATH)

    required_csv = [
        "assessment_unit_name",
        "stage_of_groundwater_extraction_pct",
        "categorization",
        "total_area_of_assessment_unit_ha",
    ]

    required_shape = [
        "SUB_DIST",
        "geometry",
    ]

    required_wards = [
        "ward_id",
        "ward_name",
        "geometry",
    ]

    for col in required_csv:
        if col not in assessment.columns:
            raise ValueError(
                f"Missing CSV column: {col}"
            )

    for col in required_shape:
        if col not in units.columns:
            raise ValueError(
                f"Missing shapefile column: {col}"
            )

    for col in required_wards:
        if col not in wards.columns:
            raise ValueError(
                f"Missing ward column: {col}"
            )

    if assessment["assessment_unit_name"].duplicated().any():
        raise ValueError(
            "Duplicate assessment-unit names in CSV"
        )

    if units["SUB_DIST"].duplicated().any():
        raise ValueError(
            "Duplicate SUB_DIST values in shapefile"
        )

    if wards["ward_id"].duplicated().any():
        raise ValueError(
            "Duplicate ward IDs in wards.geojson"
        )

    if wards["ward_id"].isna().any():
        raise ValueError(
            "Null ward IDs found"
        )

    if wards.crs is None or units.crs is None:
        raise ValueError(
            "Missing CRS in spatial input"
        )

    return assessment, units, wards


# ==================================================
# 4. MATCH CSV AND SHAPEFILE ASSESSMENT UNITS
# ==================================================

def match_units(assessment, units):
    assessment = assessment.copy()
    units = units.copy()

    assessment["match_key"] = (
        assessment["assessment_unit_name"]
        .apply(normalize_name)
    )

    units["match_key"] = (
        units["SUB_DIST"]
        .apply(normalize_name)
    )

    if assessment["match_key"].duplicated().any():
        raise ValueError(
            "Duplicate normalized names in assessment CSV"
        )

    if units["match_key"].duplicated().any():
        raise ValueError(
            "Duplicate normalized names in shapefile"
        )

    csv_names = set(assessment["match_key"])
    shape_names = set(units["match_key"])

    missing_shapes = sorted(csv_names - shape_names)
    missing_csv = sorted(shape_names - csv_names)

    if missing_shapes or missing_csv:
        raise ValueError(
            "Assessment-unit matching failed.\n"
            f"CSV units without polygons: {missing_shapes}\n"
            f"Polygons without CSV records: {missing_csv}"
        )

    merged = units.merge(
        assessment,
        on="match_key",
        how="inner",
        validate="one_to_one",
        suffixes=("_shape", "_csv"),
    )

    if len(merged) != len(assessment):
        raise ValueError(
            "Not all assessment units were matched"
        )

    merged["stage_of_groundwater_extraction_pct"] = (
        pd.to_numeric(
            merged["stage_of_groundwater_extraction_pct"],
            errors="coerce",
        )
    )

    merged["total_area_of_assessment_unit_ha"] = (
        pd.to_numeric(
            merged["total_area_of_assessment_unit_ha"],
            errors="coerce",
        )
    )

    invalid_stage = (
        merged["stage_of_groundwater_extraction_pct"].notna()
        & ~merged["stage_of_groundwater_extraction_pct"].between(
            0, 1000
        )
    )

    if invalid_stage.any():
        raise ValueError(
            "Unexpected groundwater stage values found"
        )

    print(
        f"Successfully matched {len(merged)} assessment units."
    )

    return merged


# ==================================================
# 5. VALIDATE GEOMETRIES
# ==================================================

def validate_geometries(wards, units):
    for name, frame in [
        ("Ward", wards),
        ("Assessment", units),
    ]:
        if frame.geometry.isna().any():
            raise ValueError(
                f"Null {name.lower()} geometries found"
            )

        if frame.geometry.is_empty.any():
            raise ValueError(
                f"Empty {name.lower()} geometries found"
            )

        if not frame.geometry.is_valid.all():
            raise ValueError(
                f"Invalid {name.lower()} geometries found"
            )

        if not frame.geom_type.isin(
            ["Polygon", "MultiPolygon"]
        ).all():
            raise ValueError(
                f"Unexpected {name.lower()} geometry type"
            )


# ==================================================
# 6. COMPARE REPORTED AND POLYGON AREAS
# ==================================================

def calculate_area_differences(units):
    records = []

    for row in units.itertuples():
        polygon_area_ha = row.geometry.area / 10000

        reported_area_ha = (
            row.total_area_of_assessment_unit_ha
        )

        if (
            pd.isna(reported_area_ha)
            or reported_area_ha <= 0
        ):
            difference_pct = None
        else:
            difference_pct = (
                abs(polygon_area_ha - reported_area_ha)
                / reported_area_ha
                * 100
            )

        records.append({
            "assessment_unit": row.SUB_DIST,
            "reported_area_ha": (
                float(reported_area_ha)
                if pd.notna(reported_area_ha)
                else None
            ),
            "polygon_area_ha": float(polygon_area_ha),
            "area_difference_pct": difference_pct,
            "warning": (
                difference_pct is not None
                and difference_pct > AREA_WARNING_PCT
            ),
        })

    return records


# ==================================================
# 7. CHECK ASSESSMENT POLYGON OVERLAPS
# ==================================================

def check_unit_overlaps(units):
    overlaps = []

    for i in range(len(units)):
        geom_a = units.geometry.iloc[i]

        for j in range(i + 1, len(units)):
            geom_b = units.geometry.iloc[j]

            if not geom_a.intersects(geom_b):
                continue

            overlap_area = geom_a.intersection(
                geom_b
            ).area

            if overlap_area > 1.0:
                overlaps.append({
                    "unit_a": units.iloc[i]["SUB_DIST"],
                    "unit_b": units.iloc[j]["SUB_DIST"],
                    "overlap_area_m2": float(overlap_area),
                })

    return overlaps


# ==================================================
# 8. AREA-WEIGHTED GROUNDWATER ALLOCATION
# ==================================================

def allocate_groundwater(wards, units):
    print("Starting spatial intersection...")

    records = []

    for ward in wards.itertuples():
        ward_geometry = ward.geometry
        ward_area = ward_geometry.area

        if ward_area <= 0:
            raise ValueError(
                f"Invalid ward area: {ward.ward_id}"
            )

        total_intersection_area = 0.0

        stage_weighted_sum = 0.0
        stage_area = 0.0

        category_areas = {}
        intersected_units = []

        for unit in units.itertuples():

            if not ward_geometry.intersects(
                unit.geometry
            ):
                continue

            intersection = ward_geometry.intersection(
                unit.geometry
            )

            intersection_area = intersection.area

            if intersection_area <= 0:
                continue

            total_intersection_area += intersection_area

            intersected_units.append(
                str(unit.SUB_DIST)
            )

            stage = (
                unit.stage_of_groundwater_extraction_pct
            )

            if pd.notna(stage):
                stage_weighted_sum += (
                    intersection_area * float(stage)
                )

                stage_area += intersection_area

            category = unit.categorization

            if pd.notna(category):
                category = str(category).strip()

                if category:
                    category_areas[category] = (
                        category_areas.get(category, 0.0)
                        + intersection_area
                    )

        coverage_pct = (
            total_intersection_area
            / ward_area
            * 100
        )

        if coverage_pct > 101:
            raise ValueError(
                f"Ward {ward.ward_id} has "
                f"{coverage_pct:.2f}% assessment coverage. "
                "Check overlapping assessment polygons."
            )

        if stage_area > 0:
            gw_stage = (
                stage_weighted_sum / stage_area
            )
        else:
            gw_stage = None

        if category_areas:
            gw_category = max(
                category_areas,
                key=category_areas.get,
            )
        else:
            gw_category = None

        records.append({
            "ward_id": str(ward.ward_id),
            "ward_name": ward.ward_name,

            "gw_stage_pct": (
                round(gw_stage, 4)
                if gw_stage is not None
                else None
            ),

            "gw_category": gw_category,

            "gw_coverage_pct": round(
                coverage_pct, 4
            ),

            "gw_stage_coverage_pct": round(
                stage_area / ward_area * 100,
                4,
            ),

            "gw_assessment_units": ";".join(
                sorted(set(intersected_units))
            ),
        })

    return pd.DataFrame(records)


# ==================================================
# 9. MAIN PIPELINE
# ==================================================

def main():
    check_inputs()

    assessment, units, wards = load_inputs()

    print(f"Assessment CSV records: {len(assessment)}")
    print(f"Assessment polygons: {len(units)}")
    print(f"Wards: {len(wards)}")

    if len(assessment) != 34:
        raise ValueError(
            "Expected 34 assessment CSV records"
        )

    if len(units) != 34:
        raise ValueError(
            "Expected 34 assessment polygons"
        )

    if len(wards) != 250:
        raise ValueError(
            "Expected 250 ward polygons"
        )

    units = match_units(
        assessment,
        units,
    )

    validate_geometries(
        wards,
        units,
    )

    print("Projecting geometries to metric CRS...")

    wards = wards.to_crs(AREA_CRS)
    units = units.to_crs(AREA_CRS)

    area_report = calculate_area_differences(
        units
    )

    overlaps = check_unit_overlaps(
        units
    )

    if overlaps:
        raise ValueError(
            "Assessment polygons overlap by more than "
            "1 square metre. Review the overlaps before "
            f"allocation. Examples: {overlaps[:10]}"
        )

    result = allocate_groundwater(
        wards,
        units,
    )

    if len(result) != 250:
        raise ValueError(
            f"Expected 250 output rows, got {len(result)}"
        )

    if result["ward_id"].duplicated().any():
        raise ValueError(
            "Duplicate ward IDs in groundwater output"
        )

    if result["ward_id"].nunique() != 250:
        raise ValueError(
            "Not all 250 wards are represented"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUTPUT_CSV,
        index=False,
    )

    # ------------------------------------------------
    # QA REPORT
    # ------------------------------------------------

    qa = {
        "project": "Delhi Groundwater Context D2",
        "assessment_year": 2025,

        "assessment_csv_records": len(assessment),
        "assessment_polygons": len(units),
        "wards_processed": len(result),

        "area_crs": AREA_CRS,

        "allocation_method": (
            "Area-weighted mean of intersecting "
            "assessment-unit groundwater extraction "
            "stage values"
        ),

        "category_method": (
            "Category covering the largest intersected "
            "area within each ward"
        ),

        "boundary_source": (
            "Survey of India Delhi subdistrict boundaries. "
            "Provisional proxy, not confirmed CGWB polygons."
        ),

        "wards_with_stage": int(
            result["gw_stage_pct"].notna().sum()
        ),

        "wards_without_stage": int(
            result["gw_stage_pct"].isna().sum()
        ),

        "wards_with_category": int(
            result["gw_category"].notna().sum()
        ),

        "wards_with_zero_coverage": int(
            (result["gw_coverage_pct"] == 0).sum()
        ),

        "wards_below_95pct_coverage": int(
            (result["gw_coverage_pct"] < 95).sum()
        ),

        "mean_spatial_coverage_pct": round(
            float(result["gw_coverage_pct"].mean()),
            4,
        ),

        "area_comparison_warning_threshold_pct": (
            AREA_WARNING_PCT
        ),

        "assessment_unit_area_comparison": area_report,

        "overlapping_assessment_polygons": overlaps,

        "limitations": [
            "Survey of India subdistrict polygons are provisional proxies.",
            "CGWB assessment-unit polygon boundaries are not independently verified.",
            "Ward values are spatial estimates, not direct ward-level measurements.",
            "Assessment-unit area discrepancies require review.",
        ],
    }

    with open(
        QA_JSON,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            qa,
            file,
            indent=4,
            ensure_ascii=False,
        )

    # ------------------------------------------------
    # FINAL SUMMARY
    # ------------------------------------------------

    print("\nD2 GROUNDWATER PROCESS COMPLETED")
    print("--------------------------------")

    print(f"Output CSV: {OUTPUT_CSV}")
    print(f"QA report: {QA_JSON}")

    print(f"Wards processed: {len(result)}")

    print(
        "Wards with groundwater stage:",
        qa["wards_with_stage"],
    )

    print(
        "Wards without groundwater stage:",
        qa["wards_without_stage"],
    )

    print(
        "Wards with zero spatial coverage:",
        qa["wards_with_zero_coverage"],
    )

    print(
        "Wards below 95% spatial coverage:",
        qa["wards_below_95pct_coverage"],
    )

    print("\nFirst 5 output rows:")
    print(
        result.head().to_string(index=False)
    )


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print(f"\nD2 FAILED: {exc}")
        sys.exit(1)
