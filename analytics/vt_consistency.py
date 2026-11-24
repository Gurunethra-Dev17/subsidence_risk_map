import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.compute as pc


# ==========================================
# 1. CONFIGURATION
# ==========================================

C1_PATH = Path("data/team_handoff/C1/building_metrics.parquet")
BUILDINGS_PATH = Path("data/buildings.parquet")
OUTPUT_DIR = Path("out/d5")

HORIZON_YEARS = 10
WATCH_THRESHOLD = 1 / 1000
INSPECT_THRESHOLD = 1 / 500
SINKING_THRESHOLD = -4.0


# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

def add_check(records, name, status, checked, issues, details):
    records.append({
        "check": name,
        "status": status,
        "checked_rows": int(checked),
        "issue_rows": int(issues),
        "details": details
    })


def expected_beta_class(value):
    if pd.isna(value):
        return None
    if value >= INSPECT_THRESHOLD:
        return "inspect"
    if value >= WATCH_THRESHOLD:
        return "watch"
    return "low"


# ==========================================
# 3. LOAD INPUT DATA
# ==========================================

def main():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in [C1_PATH, BUILDINGS_PATH]:
        if not path.exists():
            raise FileNotFoundError(path)

    print("Loading C1 metrics...")

    metrics = pd.read_parquet(
        C1_PATH,
        columns=[
            "bldg_id",
            "vlm_mm_yr",
            "beta_rate_per_yr",
            "beta_horizon",
            "beta_class",
            "vt_risk_insar"
        ]
    )

    print("Loading building IDs...")

    building_ids = pd.read_parquet(
        BUILDINGS_PATH,
        columns=["bldg_id"]
    )["bldg_id"]

    records = []

    total = len(metrics)

    # ======================================
    # 4. BUILDING ID VALIDATION
    # ======================================

    duplicate_metrics = metrics["bldg_id"].duplicated().sum()
    duplicate_buildings = building_ids.duplicated().sum()

    add_check(
        records,
        "C1 duplicate building IDs",
        "PASS" if duplicate_metrics == 0 else "FAIL",
        total,
        duplicate_metrics,
        "C1 building IDs must be unique."
    )

    add_check(
        records,
        "Building geometry source duplicate IDs",
        "PASS" if duplicate_buildings == 0 else "FAIL",
        len(building_ids),
        duplicate_buildings,
        "Building source IDs must be unique."
    )

    same_order = (
        len(metrics) == len(building_ids)
        and metrics["bldg_id"].reset_index(drop=True).equals(
            building_ids.reset_index(drop=True)
        )
    )

    add_check(
        records,
        "C1 and building ID alignment",
        "PASS" if same_order else "REVIEW",
        total,
        0 if same_order else total,
        "Checks whether C1 and building records have identical IDs in identical order."
    )

    # ======================================
    # 5. BETA HORIZON FORMULA VALIDATION
    # ======================================

    rate = pd.to_numeric(
        metrics["beta_rate_per_yr"],
        errors="coerce"
    )

    horizon = pd.to_numeric(
        metrics["beta_horizon"],
        errors="coerce"
    )

    valid_beta = rate.notna() & horizon.notna()

    expected_horizon = rate * HORIZON_YEARS

    formula_errors = (
        ~np.isclose(
            horizon[valid_beta],
            expected_horizon[valid_beta],
            rtol=2e-7,
            atol=1e-12
        )
    ).sum()

    add_check(
        records,
        "Beta horizon formula",
        "PASS" if formula_errors == 0 else "FAIL",
        valid_beta.sum(),
        formula_errors,
        "beta_horizon should equal beta_rate_per_yr multiplied by 10 years."
    )

    negative_beta = (
        horizon.notna() & (horizon < 0)
    ).sum()

    add_check(
        records,
        "Non-negative beta horizon",
        "PASS" if negative_beta == 0 else "REVIEW",
        horizon.notna().sum(),
        negative_beta,
        "Differential distortion magnitude should not be negative."
    )

    # ======================================
    # 6. BETA CLASS VALIDATION
    # ======================================

    actual_class = (
        metrics["beta_class"]
        .astype("string")
        .str.strip()
        .str.lower()
    )

    expected_class = horizon.map(
        expected_beta_class
    ).astype("string")

    valid_class_rows = horizon.notna()

    class_errors = (
        actual_class[valid_class_rows]
        != expected_class[valid_class_rows]
    ).sum()

    add_check(
        records,
        "Beta class threshold consistency",
        "PASS" if class_errors == 0 else "FAIL",
        valid_class_rows.sum(),
        class_errors,
        "low < 0.001; watch >= 0.001; inspect >= 0.002."
    )

    unexpected_classes = (
        actual_class.notna()
        & ~actual_class.isin(["low", "watch", "inspect"])
    ).sum()

    add_check(
        records,
        "Valid beta class labels",
        "PASS" if unexpected_classes == 0 else "FAIL",
        actual_class.notna().sum(),
        unexpected_classes,
        "Only low, watch and inspect are accepted."
    )

    missing_class_with_beta = (
        horizon.notna() & actual_class.isna()
    ).sum()

    add_check(
        records,
        "Beta class availability",
        "PASS" if missing_class_with_beta == 0 else "FAIL",
        horizon.notna().sum(),
        missing_class_with_beta,
        "Every valid beta horizon should have a beta class."
    )

    # ======================================
    # 7. MISSING VALUE VALIDATION
    # ======================================

    missing_beta_rate = rate.isna().sum()
    missing_beta_horizon = horizon.isna().sum()

    add_check(
        records,
        "Beta rate and horizon missingness",
        "PASS" if missing_beta_rate == missing_beta_horizon else "REVIEW",
        total,
        abs(missing_beta_rate - missing_beta_horizon),
        "Missing beta rate and beta horizon counts should agree."
    )

    class_without_beta = (
        horizon.isna() & actual_class.notna()
    ).sum()

    add_check(
        records,
        "Class without beta measurement",
        "PASS" if class_without_beta == 0 else "FAIL",
        total,
        class_without_beta,
        "A beta class must not exist when beta_horizon is missing."
    )

    # ======================================
    # 8. VLM VALIDATION
    # ======================================

    vlm = pd.to_numeric(
        metrics["vlm_mm_yr"],
        errors="coerce"
    )

    valid_vlm = vlm.notna()

    sinking_count = (
        vlm[valid_vlm] < SINKING_THRESHOLD
    ).sum()

    add_check(
        records,
        "VLM availability",
        "INFO",
        total,
        vlm.isna().sum(),
        "Missing VLM values are retained, not replaced with zero."
    )

    add_check(
        records,
        "Sinking measurements",
        "INFO",
        valid_vlm.sum(),
        0,
        f"{sinking_count} valid measurements are below -4 mm/year."
    )

    # ======================================
    # 9. VT RISK FIELD
    # ======================================

    vt_null_count = metrics["vt_risk_insar"].isna().sum()

    add_check(
        records,
        "VT risk field availability",
        "INFO",
        total,
        vt_null_count,
        "vt_risk_insar remains null and is excluded from validation."
    )

    # ======================================
    # 10. GEOMETRY VALIDATION
    # ======================================

    buildings_file = pq.ParquetFile(BUILDINGS_PATH)

    geo_metadata = (
        buildings_file.schema_arrow.metadata or {}
    ).get(b"geo")

    geometry_null_count = 0
    geometry_total = 0

    for batch in buildings_file.iter_batches(
        columns=["geometry"],
        batch_size=100000
    ):
        geometry = batch.column(0)
        geometry_null_count += pc.sum(
            pc.is_null(geometry)
        ).as_py()
        geometry_total += len(geometry)

    crs = None
    geometry_types = []

    if geo_metadata:
        geo = json.loads(geo_metadata)
        geometry_info = geo["columns"]["geometry"]

        crs_info = geometry_info.get("crs")

        if crs_info:
            crs = crs_info.get("id", {}).get("code")

        geometry_types = geometry_info.get(
            "geometry_types", []
        )

    add_check(
        records,
        "Building geometry availability",
        "PASS" if geometry_null_count == 0 else "REVIEW",
        geometry_total,
        geometry_null_count,
        "Checks non-null geometry records; does not independently validate polygon topology."
    )

    add_check(
        records,
        "Geometry CRS metadata",
        "INFO",
        1,
        0,
        f"CRS EPSG:{crs}; geometry types: {geometry_types}."
    )

    # ======================================
    # 11. SAVE OUTPUTS
    # ======================================

    checks = pd.DataFrame(records)

    checks.to_csv(
        OUTPUT_DIR / "internal_consistency_checks.csv",
        index=False
    )

    beta_counts = (
        actual_class.value_counts(dropna=False)
        .to_dict()
    )

    summary = {
        "task": "D5 - Internal Consistency Validation",
        "status": "internal_checks_completed_external_validation_unavailable",
        "total_buildings": int(total),
        "beta_rate_valid": int(rate.notna().sum()),
        "beta_horizon_valid": int(horizon.notna().sum()),
        "beta_class_counts": {
            str(key): int(value)
            for key, value in beta_counts.items()
        },
        "beta_formula_errors": int(formula_errors),
        "beta_class_errors": int(class_errors),
        "valid_vlm_count": int(valid_vlm.sum()),
        "sinking_count_below_minus_4": int(sinking_count),
        "vt_risk_insar_null_count": int(vt_null_count),
        "geometry_null_count": int(geometry_null_count),
        "geometry_crs_epsg": crs,
        "geometry_types": geometry_types,
        "external_published_risk_validation": {
            "status": "unavailable",
            "spearman_correlation": None,
            "confusion_matrix": None,
            "reason": "Independent published Risk_* reference dataset is unavailable."
        },
        "limitations": [
            "Internal consistency checks do not establish independent risk accuracy.",
            "beta_horizon is a 10-year cumulative distortion scenario, not a forecast.",
            "vt_risk_insar remains null and is excluded.",
            "External published risk comparison remains unavailable.",
            "Geometry topology has not been independently validated."
        ],
        "outputs": [
            "internal_consistency_checks.csv",
            "d5_summary.json"
        ]
    }

    with open(
        OUTPUT_DIR / "d5_summary.json",
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(summary, file, indent=2)

    print("\nD5 INTERNAL VALIDATION COMPLETED")
    print("--------------------------------")
    print("Buildings:", total)
    print("Valid beta:", int(horizon.notna().sum()))
    print("Beta formula errors:", int(formula_errors))
    print("Beta class errors:", int(class_errors))
    print("Valid VLM:", int(valid_vlm.sum()))
    print("VT risk null:", int(vt_null_count))
    print("Geometry null:", int(geometry_null_count))
    print("\nChecks:")
    print(checks.to_string(index=False))
    print("\nOutputs saved in:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()

