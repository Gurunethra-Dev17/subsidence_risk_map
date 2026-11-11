# SUBSIDENCE RISK MAP — Codebase, File Repository and Frozen API Contracts

**Document:** 3 of 3 — repository layout, conventions, module interfaces and the **frozen contracts C0–C6**.
**Companions:** `01_SOLUTION.md` (what and why), `02_IMPLEMENTATION_AND_WORKING_PLAN.md` (who and when).

> **Freeze statement.** Contracts C0–C6 are **frozen at v1.0** as of this document. Fields may be **added** (optional) through the change process in file 02 section 8. Fields may not be removed, renamed or retyped without a major version and agreement from every consumer.

Persons: **A** (engine, contracts steward), **B** (data pipeline, tiles), **C** (frontend), **D** (analytics), **E** (API, InSAR).

---

## 1. Artefact flow

```
 published dataset + Overture + wards + grid
                  |
              [ B pipeline ]  ---- C0 data pack ---->  [ A engine ]  ---- C1 building_metrics ---->  [ D analytics ]
                  |                                                                                      |
                  |                                                              C2 ward_summary, cell_scores, C3 validation
                  |                                                                                      |
                  +---- C5 tiles + static data <------ rebuilt with C1/C2 attributes ---------------------+
                  |                                                                                      |
               [ hosting ]                                                                        [ E API (C4) ]
                  |                                                                                      |
                  +------------------------------>  [ C web app ]  <-------------------------------------+
```

Config **C6** drives every stage.

## 2. Repository layout

One repository. Owner in brackets. Edit only your folders.

```
subsidence-risk-map/
├── Makefile                          [A]  targets listed in section 3
├── release.json                      [A]  written by `make all`, see section 4.8
├── .github/workflows/ci.yml          [E]  CI: contracts, tests, build
├── docs/                             [shared via PR]  01_SOLUTION.md, 02_..., 03_...
│
├── contracts/                        [A, steward]
│   ├── CHANGELOG.md
│   ├── validate.py                   validates any artefact against its schema
│   ├── schemas/
│   │   ├── pack_manifest.schema.json         C0
│   │   ├── building_metrics.schema.json      C1 (column schema)
│   │   ├── ward_summary.schema.json          C2
│   │   ├── cell_scores.schema.json           C2
│   │   ├── validation_summary.schema.json    C3
│   │   ├── api.openapi.yaml                  C4
│   │   └── config.schema.json                C6
│   └── mock/                         small fixtures for every contract (section 4.9)
│
├── configs/                          [A]
│   ├── delhi.yaml
│   └── chennai.yaml
│
├── data/                             [B]
│   ├── AUDIT.md                      first-inspection facts about the published dataset
│   ├── LINEAGE.md                    sources, licences, access dates, attributions
│   ├── raw/                          NOT committed (shared storage)
│   └── pack/                         NOT committed; versioned packs, e.g. delhi-pack-1.0.0/
│
├── pipeline/                         [B]
│   ├── buildings.py   wards.py   grid.py   pack.py   tiles.py   run.py
│   └── tests/
│
├── engine/                           [A]
│   ├── io.py   assign.py   distortion.py   robustness.py   run.py
│   ├── METHOD.md
│   └── tests/
│
├── analytics/                        [D]
│   ├── aggregate.py   groundwater.py   index.py   sensitivity.py   cells.py
│   ├── vt_consistency.py   collapse_check.py   hotspots.py   export.py
│   ├── fallback.py                   development-only stand-in for C1
│   ├── REVIEW_PACK.md
│   ├── figures/
│   └── tests/
│
├── api/                              [E]
│   ├── main.py   models.py   data.py   auth.py   brief.py
│   ├── templates/brief.html
│   └── tests/
│
├── insar/                            [E]
│   ├── refresh.py                    fresh-data pipeline (asf_search + HyP3)
│   ├── FEASIBILITY.md                time-series feasibility (LiCSAR/LiCSBAS)
│   └── outputs/                      NOT committed
│
└── web/                              [C]
    ├── src/
    │   ├── types/contracts.ts        generated from schemas (do not edit by hand)
    │   ├── api/   map/   panels/   pages/   modes/
    ├── public/
    └── package.json
```

## 3. Conventions

### 3.1 Data conventions (apply to every contract)

| Topic | Rule |
|---|---|
| IDs | Strings, never numbers. `ward_id`, `bldg_id`, `cell_id`, `pt_id` are stable across versions of a pack |
| Coordinates | Storage and transport in **EPSG:4326**, order **lon, lat**. Computation in the city's UTM zone (set in config) |
| Units | Ground motion **mm/yr**, **negative = sinking**. Distances in metres. Distortion as a dimensionless number (per year or cumulative) |
| Missing values | Use `null`. Never `0`, never `NaN`, never empty strings |
| Timestamps | UTC, ISO 8601 (`2026-11-11T12:00:00Z`) |
| Keys and enums | JSON keys `snake_case`. Enum values lowercase |
| Ratios | Strings of the form `"1/480"` for display, plus the numeric value beside them |
| Percentages | `coverage_pct` is 0–100. Shares are 0–1 and named `share_*` |
| Randomness | Fixed seed from config (`seed`), recorded in outputs |

### 3.2 Environment

- **Python 3.11.** Pin versions in a lock file on the first commit. Suggested libraries: `geopandas`, `shapely` (≥2), `pyproj`, `pandas`, `numpy`, `scipy`, `pyarrow`, `duckdb`, `rasterio`, `matplotlib`, `jsonschema`, `pytest`, `ruff`; for API: `fastapi`, `uvicorn`, `pydantic`, `weasyprint` (or `reportlab`), `schemathesis`; for InSAR: `hyp3_sdk`, `asf_search`.
- **Node 20.** `vite`, `react`, `typescript`, `maplibre-gl`, `pmtiles`, `json-schema-to-typescript`, a charting library of C's choice.
- **Command-line tools:** `tippecanoe`, `pmtiles`.
- Linting: `ruff` for Python, ESLint for TypeScript. CI fails on lint errors.

### 3.3 Makefile targets

| Target | Owner | What it does |
|---|---|---|
| `make validate-contracts` | A | Validates all mock fixtures and any real artefact present against the schemas |
| `make demo` | all | Each package runs end to end on mock fixtures only |
| `make data` | B | Builds a data pack (C0) for the city in `CITY=` |
| `make engine` | A | Runs the engine on a pack and writes `building_metrics.parquet` (C1) |
| `make analytics` | D | Runs scoring, sensitivity, validation; writes C2 and C3 |
| `make tiles` | B | Builds PMTiles (C5) using C1/C2 attributes |
| `make api` | E | Starts the API locally against the latest artefacts |
| `make web` | C | Starts the app against the API or mocks |
| `make test` | all | All unit and contract tests |
| `make all` | A | Full clean build of one release candidate, writes `release.json` |

### 3.4 Git

- Branches `a/…` to `e/…`. Squash-merge to `main` by pull request with one reviewer from the pair (file 02 section 6).
- `main` passes `make validate-contracts` and `make demo` at all times.
- Commit messages: `<package>: <imperative summary>`, for example `engine: add pair-distortion percentile`.
- Large artefacts (packs, tiles, InSAR outputs) are never committed.

### 3.5 Module interfaces (public signatures)

These let people mock each other's code.

```python
# engine/io.py  (A)
def load_config(path: str) -> "Config": ...
def load_vlm_points(cfg: "Config") -> "GeoDataFrame":
    """columns: pt_id, vlm_mm_yr, geometry(EPSG:4326)"""

# engine/assign.py  (A)
def assign_points_to_buildings(buildings, points, cfg) -> "DataFrame":
    """columns: bldg_id, n_points, vlm_mm_yr, vlm_iqr_mm_yr, sparse"""

# engine/distortion.py  (A)
def compute_building_distortion(buildings, points, cfg) -> "DataFrame":
    """columns: bldg_id, n_pairs, beta_rate_per_yr, beta_horizon,
       beta_ratio_horizon, beta_class"""

# engine/run.py  (A)
def run(config_path: str, pack_dir: str, out_dir: str) -> None:
    """writes building_metrics.parquet (C1)"""

# analytics/aggregate.py  (D)
def build_ward_indicators(metrics, wards, groundwater, cfg) -> "DataFrame": ...
# analytics/groundwater.py  (D)
def load_groundwater(cfg) -> "DataFrame":
    """columns: ward_id, gw_stage_pct, gw_category"""
# analytics/index.py  (D)
def compute_index(indicators, cfg) -> "DataFrame":
    """adds: score, rank, status"""
# analytics/sensitivity.py  (D)
def rank_ranges(indicators, cfg) -> "DataFrame":
    """columns: ward_id, rank_p05, rank_p95; also returns kendall_tau_mean"""
# analytics/cells.py  (D)
def build_cell_scores(metrics, grid, cfg) -> "GeoDataFrame": ...
# analytics/export.py  (D)
def export_ward_summary(df, meta, out_path: str) -> None: ...
def export_validation_summary(results: dict, out_path: str) -> None: ...

# pipeline/run.py  (B)   CLI:
#   python -m pipeline.run --config configs/delhi.yaml --step buildings|wards|grid|pack|tiles
```

```ts
// web/src/types/contracts.ts  (C; generated, shown for reference)
export interface WardSummaryFile { contract: "C2@1.0"; meta: Meta; wards: Ward[]; }
export interface Ward {
  ward_id: string; ward_name: string; status: "ranked" | "insufficient_data";
  n_buildings: number; n_buildings_with_data: number; coverage_pct: number;
  share_sinking_gt4: number | null; vlm_median_mm_yr: number | null;
  beta_p90_horizon: number | null; beta_p90_ratio_horizon: string | null;
  gw_stage_pct: number | null; gw_category: string | null;
  score: number | null; rank: number | null; rank_p05: number | null; rank_p95: number | null;
  flags: string[]; histogram: { bin_edges: number[]; counts: number[] } | null;
}
```

---

## 4. Frozen contracts

### 4.1 C6 — Configuration (v1.0)

One YAML file per city. All parameters referenced in `01_SOLUTION.md` section 7.1.

```yaml
# configs/delhi.yaml   (bbox approximate; derive the real one from the radar points)
contract: C6@1.0
city: delhi
display_name: Delhi
utm_epsg: 32643
bbox: [76.84, 28.40, 77.35, 28.89]     # minLon, minLat, maxLon, maxLat
seed: 42
paths:
  pack_dir: data/pack/delhi-pack-1.0.0
  out_dir: out/delhi
params:
  radius_m: 100
  min_points: 3
  pair_min_m: 10
  pair_max_m: 60
  footprint_buffer_m: 20
  horizon_years: 10
  class_edges_ratio: [1000, 500]       # placeholders: confirm with a geotechnical mentor
  sinking_threshold_mm_yr: -4
  coverage_min: 0.5
  grid_m: 250
  cell_min_buildings: 5
  sens_draws: 500
  sens_concentration: 50
  radius_variants_m: [50, 100, 150]
weights:
  i1: 0.30
  i2: 0.35
  i3: 0.20
  i4: 0.15
mode: public                            # public | authority (UI default)
```

```yaml
# configs/chennai.yaml
contract: C6@1.0
city: chennai
display_name: Chennai
utm_epsg: 32644
bbox: [80.10, 12.85, 80.35, 13.25]     # approximate
seed: 42
paths:
  pack_dir: data/pack/chennai-pack-1.0.0
  out_dir: out/chennai
params: { radius_m: 100, min_points: 3, pair_min_m: 10, pair_max_m: 60, footprint_buffer_m: 20,
          horizon_years: 10, class_edges_ratio: [1000, 500], sinking_threshold_mm_yr: -4,
          coverage_min: 0.5, grid_m: 250, cell_min_buildings: 5, sens_draws: 500,
          sens_concentration: 50, radius_variants_m: [50, 100, 150] }
weights: { i1: 0.30, i2: 0.35, i3: 0.20, i4: 0.15 }
mode: public
```

### 4.2 C0 — Data pack (v1.0) — producer **B**, consumers A, D, E

A pack is a folder named `<city>-pack-<MAJOR.MINOR.PATCH>/`.

| File | Format | Required columns / properties |
|---|---|---|
| `wards.geojson` | GeoJSON, EPSG:4326 | `ward_id` (string, unique), `ward_name`, `city`, `source`, `source_year` |
| `buildings.parquet` | GeoParquet, EPSG:4326, polygons | `bldg_id` (string, unique), `footprint_m2` (float), `source` (`osm`\|`google`\|`microsoft`\|`esri`\|`vt`), `ward_id` (string or null), `cell_id` (string or null), geometry. **B assigns `ward_id` and `cell_id` by centroid-in-polygon**; null if outside all wards |
| `vlm_points.parquet` | Parquet, lon/lat columns | `pt_id` (string), `lon`, `lat`, `vlm_mm_yr` (float, negative = sinking), `source` (`vt-in-v2`) |
| `vt_building_risk.parquet` | GeoParquet | `geometry` as provided (see `data/AUDIT.md`), `risk_insar`, `risk_10yrs`, `risk_30yrs`, `risk_50yrs` (integers, coding per audit), `bldg_id` if joinable else null |
| `grid_250m.geojson` | GeoJSON, EPSG:4326 | `cell_id` (string, unique, stable), `ward_id` (majority ward, nullable) |
| `collapse_incidents.csv` | CSV | `incident_id`, `lon`, `lat` (nullable), `city`, `date` (nullable), `note` — fields as available in the source spreadsheet |
| `PACK_MANIFEST.json` | JSON | below |

```json
{
  "contract": "C0@1.0",
  "pack_version": "delhi-pack-1.0.0",
  "created_utc": "2026-11-11T12:00:00Z",
  "city": "delhi",
  "crs_storage": "EPSG:4326",
  "files": [
    {"name": "wards.geojson", "sha256": "<hash>", "rows": 0},
    {"name": "buildings.parquet", "sha256": "<hash>", "rows": 0},
    {"name": "vlm_points.parquet", "sha256": "<hash>", "rows": 0},
    {"name": "vt_building_risk.parquet", "sha256": "<hash>", "rows": 0},
    {"name": "grid_250m.geojson", "sha256": "<hash>", "rows": 0},
    {"name": "collapse_incidents.csv", "sha256": "<hash>", "rows": 0}
  ],
  "sources": [
    {"name": "Virginia Tech dataset (vertical land motion and building damage risk, Indian megacities)",
     "url": "https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260",
     "licence": "TO_CONFIRM", "accessed_utc": "2026-11-11T09:00:00Z"},
    {"name": "Overture Maps buildings", "url": "https://overturemaps.org",
     "licence": "ODbL", "accessed_utc": "2026-11-11T09:30:00Z"}
  ],
  "attribution": ["© OpenStreetMap contributors", "Microsoft", "Esri Community Maps contributors", "Google Open Buildings"],
  "notes": ["vlm converted from cm/yr to mm/yr by pipeline", "units and sign confirmed in data/AUDIT.md"]
}
```

**Acceptance (gate H1):** hashes match; ward count equals the official count; no null or duplicate IDs; CRS present everywhere; `vlm_mm_yr` range plausible (documented in audit).

### 4.3 C1 — Building metrics (v1.0) — producer **A**, consumers D, B (tiles), E

File: `building_metrics.parquet`. One row per building in the pack.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| `bldg_id` | string | no | From the pack |
| `ward_id` | string | yes | From the pack |
| `cell_id` | string | yes | From the pack |
| `n_points` | int32 | no | Radar points within `radius_m` (0 if none) |
| `vlm_mm_yr` | float32 | yes | Inverse-distance weighted median; null if fewer than `min_points` |
| `vlm_iqr_mm_yr` | float32 | yes | Interquartile range of contributing points |
| `n_pairs` | int32 | no | Point pairs used for distortion |
| `beta_rate_per_yr` | float32 | yes | 90th percentile of pair distortion per year; null if `n_pairs` < 3 |
| `beta_horizon` | float32 | yes | `beta_rate_per_yr × horizon_years` (scenario, not forecast) |
| `beta_ratio_horizon` | string | yes | e.g. `"1/480"` |
| `beta_class` | string | yes | `low` \| `watch` \| `inspect` from `class_edges_ratio` |
| `sparse` | bool | no | True if `vlm_mm_yr` is null for lack of points |
| `vt_risk_insar` | int8 | yes | Published category, if the building can be joined |
| `engine_version` | string | no | Git tag or commit |
| `params_hash` | string | no | Hash of the `params` block of the config |

Parquet file metadata must also contain `horizon_years`, `contract = C1@1.0`, `seed`.

**Acceptance (gate H2):** passes schema; worked-example test passes in CI (−10 and −6 mm/yr, 20 m apart → `1/500` at 10 years); non-null share of `vlm_mm_yr` reported.

### 4.4 C2 — Ward summary and cell scores (v1.0) — producer **D**, consumers C, E, B

Two artefacts: `ward_summary.json` and `cell_scores.geojson`.

**`ward_summary.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "contracts/schemas/ward_summary.schema.json",
  "title": "ward_summary",
  "type": "object",
  "required": ["contract", "meta", "wards"],
  "properties": {
    "contract": { "const": "C2@1.0" },
    "meta": {
      "type": "object",
      "required": ["city", "data_vintage", "generated_utc", "engine_version", "params", "weights", "n_wards", "n_ranked"],
      "properties": {
        "city": { "type": "string" },
        "data_vintage": { "type": "string" },
        "generated_utc": { "type": "string", "format": "date-time" },
        "engine_version": { "type": "string" },
        "params": { "type": "object" },
        "weights": {
          "type": "object",
          "required": ["i1", "i2", "i3", "i4"],
          "properties": {
            "i1": { "type": "number" }, "i2": { "type": "number" },
            "i3": { "type": "number" }, "i4": { "type": ["number", "null"] }
          }
        },
        "n_wards": { "type": "integer" },
        "n_ranked": { "type": "integer" }
      }
    },
    "wards": { "type": "array", "items": { "$ref": "#/$defs/ward" } }
  },
  "$defs": {
    "ward": {
      "type": "object",
      "required": ["ward_id", "ward_name", "status", "n_buildings", "n_buildings_with_data", "coverage_pct", "flags"],
      "properties": {
        "ward_id": { "type": "string" },
        "ward_name": { "type": "string" },
        "status": { "enum": ["ranked", "insufficient_data"] },
        "n_buildings": { "type": "integer", "minimum": 0 },
        "n_buildings_with_data": { "type": "integer", "minimum": 0 },
        "coverage_pct": { "type": "number", "minimum": 0, "maximum": 100 },
        "share_sinking_gt4": { "type": ["number", "null"], "minimum": 0, "maximum": 1 },
        "vlm_median_mm_yr": { "type": ["number", "null"] },
        "beta_p90_horizon": { "type": ["number", "null"] },
        "beta_p90_ratio_horizon": { "type": ["string", "null"] },
        "gw_stage_pct": { "type": ["number", "null"] },
        "gw_category": { "type": ["string", "null"] },
        "score": { "type": ["number", "null"], "minimum": 0, "maximum": 100 },
        "rank": { "type": ["integer", "null"], "minimum": 1 },
        "rank_p05": { "type": ["integer", "null"], "minimum": 1 },
        "rank_p95": { "type": ["integer", "null"], "minimum": 1 },
        "flags": {
          "type": "array",
          "items": { "enum": ["sparse_points", "groundwater_missing", "small_ward", "low_coverage", "boundary_vintage"] }
        },
        "histogram": {
          "type": ["object", "null"],
          "properties": {
            "bin_edges": { "type": "array", "items": { "type": "number" } },
            "counts": { "type": "array", "items": { "type": "integer" } }
          }
        }
      }
    }
  }
}
```

**Field meanings:** `share_sinking_gt4` is indicator I1; `beta_p90_horizon` is I2; `n_buildings` is I3; `gw_stage_pct` is I4. `score` and `rank` are null when `status` is `insufficient_data`.

**Example (illustrative values):**

```json
{
  "contract": "C2@1.0",
  "meta": {
    "city": "delhi", "data_vintage": "2015-2023 (published dataset v2)",
    "generated_utc": "2026-11-12T10:00:00Z", "engine_version": "a1b2c3d",
    "params": {"radius_m": 100, "horizon_years": 10},
    "weights": {"i1": 0.30, "i2": 0.35, "i3": 0.20, "i4": 0.15},
    "n_wards": 2, "n_ranked": 1
  },
  "wards": [
    {"ward_id": "W001", "ward_name": "Example Ward A", "status": "ranked",
     "n_buildings": 12000, "n_buildings_with_data": 9300, "coverage_pct": 77.5,
     "share_sinking_gt4": 0.31, "vlm_median_mm_yr": -6.2,
     "beta_p90_horizon": 0.0021, "beta_p90_ratio_horizon": "1/476",
     "gw_stage_pct": 100.8, "gw_category": "over_exploited",
     "score": 71.2, "rank": 1, "rank_p05": 1, "rank_p95": 3,
     "flags": [], "histogram": {"bin_edges": [0, 0.0005, 0.001, 0.002, 0.004], "counts": [4200, 3100, 1500, 500]}},
    {"ward_id": "W002", "ward_name": "Example Ward B", "status": "insufficient_data",
     "n_buildings": 800, "n_buildings_with_data": 120, "coverage_pct": 15.0,
     "share_sinking_gt4": null, "vlm_median_mm_yr": null,
     "beta_p90_horizon": null, "beta_p90_ratio_horizon": null,
     "gw_stage_pct": 100.8, "gw_category": "over_exploited",
     "score": null, "rank": null, "rank_p05": null, "rank_p95": null,
     "flags": ["low_coverage", "sparse_points"], "histogram": null}
  ]
}
```

**`cell_scores.geojson`** — FeatureCollection, EPSG:4326. Properties:

| Property | Type | Nullable | Meaning |
|---|---|---|---|
| `cell_id` | string | no | From the grid |
| `ward_id` | string | yes | Majority ward |
| `n_buildings` | integer | no | Buildings in the cell |
| `suppressed` | boolean | no | True if `n_buildings` < `cell_min_buildings` |
| `vlm_median_mm_yr` | number | yes | Null if suppressed |
| `beta_p90_horizon` | number | yes | Null if suppressed |
| `share_sinking_gt4` | number | yes | Null if suppressed |
| `cell_score` | number 0–100 | yes | Cell index (I1, I2, I3 with renormalised weights); null if suppressed |
| `cell_rank_in_ward` | integer | yes | 1 = highest score within the ward |

**Acceptance (gate H3):** schema passes; ranks are 1..N over ranked wards with no gaps; `rank_p05 ≤ rank ≤ rank_p95`; coverage rule applied; suppressed cells carry no metrics.

### 4.5 C3 — Validation summary (v1.0) — producer **D**, consumers C, E

File: `validation_summary.json`.

```json
{
  "contract": "C3@1.0",
  "generated_utc": "2026-11-12T10:30:00Z",
  "vt_consistency": {
    "n_buildings": 0,
    "spearman_rho": null,
    "labels": ["0", "1", "2", "3", "4"],
    "confusion_matrix": [],
    "note": "Consistency with published categories, not independent ground truth."
  },
  "collapse_check": {
    "n_incidents_total": 26,
    "n_in_city": 0,
    "by_published_risk": {},
    "by_rank_band": {},
    "note": "Very small n. No statistical claim. Collapse causes are not attributed to subsidence."
  },
  "hotspot_check": [
    {"name": "Bijwasan", "source": "Nature Sustainability 2025", "ward_id": null, "rank": null, "percentile": null},
    {"name": "Kapashera", "source": "Garg et al. 2022 (Scientific Reports)", "ward_id": null, "rank": null, "percentile": null}
  ],
  "robustness": {
    "kendall_tau_weights_mean": null,
    "rank_range_width_median": null,
    "radius_variants": [
      {"radius_m": 50, "kendall_tau_vs_baseline": null},
      {"radius_m": 150, "kendall_tau_vs_baseline": null}
    ]
  },
  "fresh_data_check": {
    "status": "not_run",
    "note": "Filled by E7 output if the refresh pipeline ran: dates, area, pattern and sign agreement."
  },
  "figures": [
    {"id": "consistency_scatter", "path": "analytics/figures/consistency_scatter.png", "caption": ""}
  ]
}
```

All numeric fields are `null` until computed. Notes are fixed text and must not be removed. **Acceptance (gate H3):** schema passes; every `null` that remains is explained in a `note`.

### 4.6 C4 — REST API (v1.0) — producer **E**, consumer C

Base path `/api/v1`. JSON unless stated. Full OpenAPI document lives in `contracts/schemas/api.openapi.yaml` and is generated from this table.

| Method and path | Purpose | Query parameters | Response |
|---|---|---|---|
| `GET /meta` | City, versions, parameters, weights, data vintage, default mode | — | `meta` object as in C2 plus `contract_versions` |
| `GET /wards` | List ward summaries | `status` (`ranked`\|`insufficient_data`), `sort` (`rank`\|`score`\|`name`), `order` (`asc`\|`desc`), `q` (name search), `limit` (default 50, max 500), `offset` | Pagination envelope of C2 wards |
| `GET /wards/{ward_id}` | Full ward summary | — | One C2 ward |
| `GET /wards/{ward_id}/cells` | Cells for a ward | — | GeoJSON FeatureCollection (cell_scores subset) |
| `GET /wards/{ward_id}/brief.pdf` | One-page inspection brief | — | `application/pdf` |
| `GET /buildings` | Building metrics (**authority only**) | `bbox` (`minLon,minLat,maxLon,maxLat`), `ward_id`, `limit` (default 500, max 5000) | GeoJSON FeatureCollection; properties `bldg_id`, `vlm_mm_yr`, `beta_ratio_horizon`, `beta_class`, `sparse` |
| `GET /validation` | Validation summary | — | C3 |
| `GET /health` | Liveness | — | `{"status": "ok", "version": "<tag>"}` |

**Pagination envelope**

```json
{ "items": [ ], "total": 250, "limit": 50, "offset": 0 }
```

**Authority access.** `GET /buildings` requires header `X-Authority-Token: <token>`. The token comes from the environment variable `AUTHORITY_TOKEN`. For local development only the token `demo-authority` is accepted when `API_ENV=dev`.

**Errors.** All errors use:

```json
{ "error": { "code": "invalid_param", "message": "bbox must have 4 numbers", "details": {} } }
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_param` | Bad query parameter |
| 401 | `authority_required` | Missing or wrong token on an authority endpoint |
| 404 | `not_found` | Unknown `ward_id` |
| 429 | `rate_limited` | Too many requests |
| 500 | `internal` | Unexpected failure |

**Caching and CORS.** `ETag` on all JSON responses, `Cache-Control: public, max-age=300` for ward endpoints, `no-store` for `/buildings` and PDFs. CORS allows `GET` and `OPTIONS` from configured origins.

**Brief contents (fixed):** ward name and rank with rank range; score; the five indicators; coverage and uncertainty statement; cell list in suggested inspection order (cells only, no building names); fixed caveat text ("ranks areas for inspection; does not certify any building; projections are scenarios under constant rates"); data vintage and version.

**Acceptance (gate H5):** contract tests pass against the OpenAPI document; `/wards` returns real data; `/buildings` returns 401 without a token.

### 4.7 C5 — Tiles and static hosting (v1.0) — producer **B**, consumers C, E

PMTiles files, named with a version suffix so caches never go stale.

| File | Layer name | Zooms | Attributes |
|---|---|---|---|
| `<city>-wards-<ver>.pmtiles` | `wards` | 0–12 | `ward_id`, `ward_name`, `status`, `score`, `rank` |
| `<city>-cells-<ver>.pmtiles` | `cells` | 8–14 | `cell_id`, `ward_id`, `suppressed`, `cell_score`, `cell_rank_in_ward` |
| `<city>-points-<ver>.pmtiles` | `points` | 10–15 | `pt_id`, `vlm_mm_yr` |
| `<city>-buildings-<ver>.pmtiles` | `buildings` | 13–16 | `bldg_id`, `vlm_mm_yr`, `beta_ratio_horizon`, `beta_class`, `sparse` |

- Base URL from environment variable `TILES_BASE_URL`, layout `${TILES_BASE_URL}/<city>/<file>`.
- Hosting must support HTTP range requests and CORS for `GET` and `HEAD` with the `Range` header. Cache: `public, max-age=86400`.
- Attribution string shown in the app: `© OpenStreetMap contributors, Microsoft, Esri Community Maps contributors, Google Open Buildings; ground-motion data: Virginia Tech dataset (see licence)`.
- **Prototype-level protection note:** building tiles are served from a separate path (`/<city>/authority/`) not linked from the public UI. Static hosting cannot enforce a token, so real protection is the API (`/buildings`). The app states this plainly.
- **Fallback:** gzip-compressed GeoJSON per ward at `${TILES_BASE_URL}/<city>/geojson/<ward_id>.json` with the same attribute names.

**Acceptance (gate H4):** tiles load in the app at target zooms; attribute names match; attribution present.

### 4.8 `release.json` (written by `make all`)

```json
{
  "release": "v1.0.0",
  "created_utc": "2026-11-15T18:00:00Z",
  "city": "delhi",
  "contracts": {"C0": "1.0", "C1": "1.0", "C2": "1.0", "C3": "1.0", "C4": "1.0", "C5": "1.0", "C6": "1.0"},
  "artefacts": {
    "pack": "delhi-pack-1.0.0",
    "building_metrics": {"sha256": "<hash>", "engine_version": "a1b2c3d"},
    "ward_summary": {"sha256": "<hash>"},
    "validation_summary": {"sha256": "<hash>"},
    "tiles": "1.0.0"
  }
}
```

### 4.9 Mock fixtures (committed by A at gate H0)

Every package can start immediately because `contracts/mock/` contains one small, valid fixture per contract.

| Fixture | Contract | Content |
|---|---|---|
| `mock/delhi-pack-0.0.1/` | C0 | 3 wards, about 200 synthetic buildings, about 500 synthetic radar points, 20 grid cells, manifest |
| `mock/building_metrics.parquet` | C1 | One row per synthetic building, including null and `sparse` cases and each `beta_class` |
| `mock/ward_summary.json` | C2 | 3 wards: two ranked, one `insufficient_data`; includes histograms |
| `mock/cell_scores.geojson` | C2 | Cells including suppressed ones |
| `mock/validation_summary.json` | C3 | Mostly `null` values with notes, as in 4.5 |
| `mock/api/` | C4 | Example responses for every endpoint, one sample PDF |
| `mock/tiles/` | C5 | Tiny PMTiles or GeoJSON for each layer |
| `mock/config.yaml` | C6 | The Delhi config above |

Mocks must include the awkward cases: a ward with no buildings, a building with null metrics, a suppressed cell, a missing groundwater value.

## 5. Contract ownership summary

| Contract | Producer | Consumers | Gate |
|---|---|---|---|
| C0 data pack | B | A, D, E | H1 |
| C1 building metrics | A | D, B, E | H2 |
| C2 ward summary, cell scores | D | C, E, B | H3 |
| C3 validation summary | D | C, E | H3 |
| C4 REST API | E | C | H5 |
| C5 tiles and static hosting | B | C, E | H4 |
| C6 configuration | A | everyone | H0 |

## 6. Quality gates in CI

| Check | Command | Fails when |
|---|---|---|
| Contract validation | `make validate-contracts` | Any fixture or artefact violates its schema |
| Unit tests | `make test` | Any package test fails, including the worked-example distortion test |
| Lint | `ruff`, ESLint | Lint errors |
| API contract tests | `schemathesis` against the OpenAPI document | API deviates from C4 |
| Web build | `npm run build` | Type errors, including contract types out of date |

## 7. Pre-flight checklist before anyone writes code

- [ ] Repository created, folders and owners match section 2
- [ ] Contracts and mocks committed (gate H0), `make validate-contracts` and `make demo` pass
- [ ] Shared storage for packs and tiles set up, with a naming rule `<city>-pack-<ver>`
- [ ] Earthdata account created (for E7)
- [ ] Pilot city confirmed (default Delhi) and config committed
- [ ] Review pairs agreed: A↔D, B↔E, C↔E, A↔B
- [ ] Published dataset's licence read and recorded in `data/AUDIT.md`
