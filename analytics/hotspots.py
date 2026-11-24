
from pathlib import Path
import json

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out/d7"

INDEX_FILE = ROOT / "out/d3_revised/ward_inspection_index.csv"
WARD_FILE = ROOT / "data/wards.geojson"

CSV_OUTPUT = OUT_DIR / "hotspot_crosscheck.csv"
JSON_OUTPUT = OUT_DIR / "hotspot_summary.json"


# Representative locality/city reference coordinates.
# These are not exact InSAR hotspot polygon centroids.
HOTSPOTS = [
    {
        "hotspot": "Bijwasan",
        "latitude": 28.5363,
        "longitude": 77.0567,
        "study": "Building damage risk in sinking Indian megacities (2025)",
        "source": "https://www.nature.com/articles/s41893-025-01663-0",
        "coordinate_basis": "Approximate locality reference",
    },
    {
        "hotspot": "Faridabad",
        "latitude": 28.4089,
        "longitude": 77.3178,
        "study": "Building damage risk in sinking Indian megacities (2025)",
        "source": "https://www.nature.com/articles/s41893-025-01663-0",
        "coordinate_basis": "Approximate city reference",
    },
    {
        "hotspot": "Ghaziabad",
        "latitude": 28.6692,
        "longitude": 77.4538,
        "study": "Building damage risk in sinking Indian megacities (2025)",
        "source": "https://www.nature.com/articles/s41893-025-01663-0",
        "coordinate_basis": "Approximate city reference",
    },
    {
        "hotspot": "Kapashera",
        "latitude": 28.5285,
        "longitude": 77.0860,
        "study": "Tracking hidden crisis in India's capital from space (2022)",
        "source": "https://www.nature.com/articles/s41598-021-04193-9",
        "coordinate_basis": "Approximate locality reference",
    },
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    index = pd.read_csv(INDEX_FILE)
    wards = gpd.read_file(WARD_FILE)

    required_index = {
        "ward_id", "ward_name", "status", "rank", "score"
    }

    if not required_index.issubset(index.columns):
        raise ValueError(
            f"D3 index missing columns: "
            f"{sorted(required_index - set(index.columns))}"
        )

    if wards.crs is None:
        raise ValueError("Ward boundaries have no CRS.")

    if not {"ward_id", "ward_name", "geometry"}.issubset(wards.columns):
        raise ValueError("Ward boundaries missing required columns.")

    ranked = index[index["status"] == "ranked"].copy()

    ranked["ward_id"] = ranked["ward_id"].astype(str)
    ranked["rank"] = pd.to_numeric(ranked["rank"], errors="coerce")
    ranked["score"] = pd.to_numeric(ranked["score"], errors="coerce")

    if ranked["rank"].isna().any() or ranked["score"].isna().any():
        raise ValueError("Ranked wards contain missing ranks or scores.")

    # Resolve tied ranks temporarily for D7 only.
    # Higher score first; ward_id ascending breaks exact score ties.
    # The original D3 file remains unchanged.
    ranked = ranked.sort_values(
        ["score", "ward_id"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)

    ranked["d7_rank"] = range(1, len(ranked) + 1)

    n_ranked = len(ranked)

    if n_ranked < 2:
        raise ValueError("Not enough ranked wards for percentile calculation.")

    ranked["rank_percentile"] = (
        (n_ranked - ranked["d7_rank"]) / (n_ranked - 1)
    ) * 100

    ranked_lookup = ranked[
        ["ward_id", "ward_name", "d7_rank", "score", "rank_percentile"]
    ]

    ward_geometry = wards[
        ["ward_id", "ward_name", "geometry"]
    ].copy()

    ward_geometry["ward_id"] = ward_geometry["ward_id"].astype(str)

    points = gpd.GeoDataFrame(
        HOTSPOTS,
        geometry=gpd.points_from_xy(
            [h["longitude"] for h in HOTSPOTS],
            [h["latitude"] for h in HOTSPOTS],
        ),
        crs="EPSG:4326",
    ).to_crs(wards.crs)

    joined = gpd.sjoin(
        points,
        ward_geometry,
        how="left",
        predicate="within",
    )

    results = []

    for _, row in joined.iterrows():
        ward_id = row.get("ward_id_right")
        ward_name = row.get("ward_name_right")

        # Handle GeoPandas versions that do not suffix right-side columns.
        if ward_id is None:
            ward_id = row.get("ward_id")

        if ward_name is None:
            ward_name = row.get("ward_name")

        result = {
            "hotspot": row["hotspot"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "coordinate_basis": row["coordinate_basis"],
            "literature_study": row["study"],
            "source": row["source"],
            "matched_ward_id": None,
            "matched_ward_name": None,
            "our_rank": None,
            "our_score": None,
            "rank_percentile": None,
            "comparison_status": None,
        }

        if pd.isna(ward_id):
            result["comparison_status"] = "outside_delhi_ward_boundaries"

        else:
            result["matched_ward_id"] = str(ward_id)
            result["matched_ward_name"] = ward_name

            match = ranked_lookup[
                ranked_lookup["ward_id"] == str(ward_id)
            ]

            if match.empty:
                result["comparison_status"] = "ward_found_but_not_ranked"

            else:
                match = match.iloc[0]

                result["our_rank"] = int(match["d7_rank"])
                result["our_score"] = float(match["score"])
                result["rank_percentile"] = float(
                    match["rank_percentile"]
                )
                result["comparison_status"] = "compared"

        results.append(result)

    output = pd.DataFrame(results)
    output.to_csv(CSV_OUTPUT, index=False)

    compared = output[
        output["comparison_status"] == "compared"
    ]

    summary = {
        "task": "D7 literature hotspot cross-check",
        "status": "preliminary",
        "total_literature_hotspots": len(output),
        "compared_with_delhi_ward_rankings": len(compared),
        "outside_delhi_ward_boundaries": int(
            (output["comparison_status"]
             == "outside_delhi_ward_boundaries").sum()
        ),
        "ward_found_but_not_ranked": int(
            (output["comparison_status"]
             == "ward_found_but_not_ranked").sum()
        ),
        "ranking_method": (
            "Temporary D7 ordering: score descending, "
            "ward_id ascending for ties. Original D3 ranks unchanged."
        ),
        "percentile_method": (
            "(number_of_ranked_wards - D7_rank) / "
            "(number_of_ranked_wards - 1) * 100"
        ),
        "ranked_ward_count": n_ranked,
        "hotspot_results": results,
        "limitations": [
            "Coordinates are representative locality or city references, not exact InSAR hotspot polygon centroids.",
            "Point-in-polygon assignment is exploratory and depends on the representative coordinate.",
            "Faridabad and Ghaziabad are outside the Delhi ward boundary dataset.",
            "Temporary D7 ranks resolve tied D3 scores using ward_id as a deterministic tie-breaker.",
            "Literature studies use different observation periods and methodologies.",
            "A high or low ward rank does not independently validate or invalidate the literature finding.",
            "This comparison does not establish causation.",
        ],
    }

    with JSON_OUTPUT.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=4, ensure_ascii=False)

    print("\nD7 HOTSPOT CROSS-CHECK")
    print("---------------------")
    print(
        output[
            [
                "hotspot",
                "matched_ward_name",
                "our_rank",
                "rank_percentile",
                "comparison_status",
            ]
        ].to_string(index=False)
    )

    print("\nCompared with Delhi wards:", len(compared))
    print("Outside Delhi:", summary["outside_delhi_ward_boundaries"])
    print("\nCSV:", CSV_OUTPUT)
    print("JSON:", JSON_OUTPUT)


if __name__ == "__main__":
    main()
