# D10 Phase 1 — D8 Integration Handoff

This document defines the data interface to the existing D8 exporter and the checks required before
real C2/C3 outputs are generated. Frozen C2/C3 contracts remain authoritative. The checker does not
compute D1–D7 analytics, repair inputs, or claim scientific validation.

## Input files and contracts

The checker and exporter use the same five required file inputs. `analytics.integration_check`
also accepts optional provenance and validation inputs.

### Ward CSV (`--wards-csv`)

One row per C2 ward, keyed by unique non-empty string `ward_id`. Required columns:

| Field | Type / meaning | Nullability and checks |
|---|---|---|
| `ward_id`, `ward_name` | string identifier and display name | non-empty; ward IDs unique |
| `status` | enum `ranked` or `insufficient_data` | required |
| `n_buildings`, `n_buildings_with_data` | non-negative integers | required; measured count cannot exceed total |
| `coverage_pct` | number, percent 0–100 | required; must agree with counts within exporter tolerance |
| `share_sinking_gt4` | fraction 0–1 | nullable |
| `vlm_median_mm_yr` | mm/year | nullable |
| `beta_p90_horizon` | dimensionless C1 horizon metric | nullable |
| `beta_p90_ratio_horizon` | ratio label string | nullable |
| `gw_stage_pct` | groundwater extraction stage, percent | nullable |
| `gw_category` | source category string | nullable |
| `score` | Inspection Index, 0–100 | nullable; required for ranked wards by exporter logic |
| `rank` | one-based integer rank | nullable; required for ranked wards |
| `flags` | list of strings | required; allowed values: `sparse_points`, `groundwater_missing`, `small_ward`, `low_coverage`, `boundary_vintage` |
| `histogram` | JSON object | nullable |

The exporter takes `rank_p05` and `rank_p95` from the sensitivity CSV, not this CSV. Ranked ward
ranks must be unique and contiguous from 1 through N. Insufficient wards must be below configured
coverage, flagged `low_coverage`, and have null score, rank and rank ranges. Ranked wards must meet
the coverage threshold. Coverage threshold comes from `meta.params.coverage_min` (fraction or percent)
or `coverage_min_pct`.

Minimal illustrative rows (the header lists required exporter fields; real rows also carry the
other ward columns above):

```csv
ward_id,ward_name,status,n_buildings,n_buildings_with_data,coverage_pct,score,rank,flags
synthetic-ward-1,Synthetic Ward,ranked,10,9,90,75,1,[]
synthetic-ward-2,Low Coverage Ward,insufficient_data,10,2,20,,,['low_coverage']
```

### Sensitivity CSV (`--sensitivity-csv`)

Required fields are `ward_id` (string), `rank_p05` and `rank_p95` (integer ranks, nullable only for
insufficient-data wards). The IDs must be unique and match the ward CSV exactly. For every ranked
ward, `rank_p05 <= rank <= rank_p95`. Do not round or replace missing ranges to force acceptance.

```csv
ward_id,rank_p05,rank_p95
synthetic-ward-1,1,1
synthetic-ward-2,,
```

### Cell CSV (`--cells-csv`)

One row per unique `cell_id`; required fields:

| Field | Type / meaning | Nullability and checks |
|---|---|---|
| `cell_id` | string | non-empty, unique, matches geometry exactly |
| `ward_id` | string | nullable |
| `n_buildings` | non-negative integer | required |
| `suppressed` | boolean | must equal `n_buildings < 5` |
| `vlm_median_mm_yr` | mm/year | nullable |
| `beta_p90_horizon` | dimensionless C1 horizon metric | nullable |
| `share_sinking_gt4` | fraction 0–1 | nullable |
| `cell_score` | 0–100 | nullable |
| `cell_rank_in_ward` | one-based integer | nullable; ranked cells require a ward ID and contiguous ranks within each ward |

When `suppressed=true`, all metrics and ranks (`vlm_median_mm_yr`, `beta_p90_horizon`,
`share_sinking_gt4`, `cell_score`, `cell_rank_in_ward`) must be null. The exporter does not calculate
or invent cell values.

```csv
cell_id,ward_id,n_buildings,suppressed,vlm_median_mm_yr,beta_p90_horizon,share_sinking_gt4,cell_score,cell_rank_in_ward
synthetic-cell-1,synthetic-ward-1,3,true,,,,,
synthetic-cell-2,synthetic-ward-1,7,false,-2.1,0.001,0.4,61,1
```

### Cell geometry GeoJSON (`--geometry-geojson`)

Must be a GeoJSON `FeatureCollection`. Every feature needs a unique string `properties.cell_id` and
a valid, non-empty Polygon or MultiPolygon geometry in EPSG:4326/CRS84 (an omitted CRS follows the
RFC 7946 GeoJSON coordinate convention). Geometry IDs and CSV IDs must match exactly. Geometry must
come from the supplied C0 grid; the exporter does not build or repair geometry.

Minimal illustrative FeatureCollection (coordinates are synthetic and are not Delhi geometry):

```json
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"cell_id":"synthetic-cell-1"},"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}
```

### Metadata JSON (`--meta-json`)

Required object fields are `city` (string), `data_vintage` (string), `engine_version` (string),
`params` (object), and `weights` (object containing numeric `i1`, `i2`, `i3`, `i4`). `params` must
include the coverage threshold. For the latest staged C1, use
`out/delhi/integration_2026-11-22/reference/configs/delhi.yaml` as the parameter source; do not use
the older team-root `configs/delhi.yaml`. With an integration manifest, the checker compares city,
data vintage, engine, full params and weights with the staged C0/C1/C6 provenance. Optional
`params_hash` and `source_hashes.c1` fields are checked when supplied. Their absence is reported as
a lineage warning, not silently treated as proof that upstream CSVs came from the staged C1.

Minimal illustrative shape (values must be built from the selected C0/C1/C6 inputs):

```json
{
  "city": "delhi",
  "data_vintage": "delhi-candidate-0.0.1",
  "engine_version": "f3af18a",
  "params": {"pair_min_m": 80, "pair_max_m": 120, "coverage_min": 0.5},
  "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15}
}
```

The example is illustrative, not a complete Delhi parameter object. Real output must carry the
complete selected C6 `params` mapping and exact source `data_vintage`.

### Validation JSON (`--validation-json`)

Optional JSON object containing any of the C3 section keys `vt_consistency`, `collapse_check`,
`hotspot_check`, `robustness`, and `fresh_data_check`. Unknown section keys fail. Omitted comparisons
remain explicitly unavailable with notes; zero counters in defaults do not mean a zero measurement.
`vt_consistency` uses null for unavailable `spearman_rho`; `robustness` must contain
`kendall_tau_weights_mean`, `rank_range_width_median`, and `radius_variants`. Each radius variant has
exactly `radius_m` and `kendall_tau_vs_baseline`. D4 inputs with multiple pair windows must not be
flattened into a radius-only result without documenting/selecting the pair window. The latest agreed
baseline pair window is 80–120 m; the 50 m variants have no ranked wards and cannot supply a Kendall
comparison.

Example showing an unavailable comparison without implying a measured zero correlation:

```json
{"vt_consistency":{"n_buildings":0,"spearman_rho":null,"labels":[],"confusion_matrix":[],"note":"Unavailable: no approved spatial match."}}
```

### D6 validation fragment (`--d6-validation-json`)

Accepts the standalone D6 `collapse_check` object with exactly the five C3 fields:

```json
{
  "n_incidents_total": 8,
  "n_in_city": 8,
  "by_published_risk": {},
  "by_rank_band": {},
  "note": "Spatial comparison unavailable; no independently verified incident-site coordinates."
}
```

The two counts are integers, the two distributions are objects, and `note` is a non-empty string.
No additional properties are allowed. Either pass this fragment separately or include it as
`collapse_check` in validation JSON, but not both. Preserve the team D6 provenance gate: approximate
locality references are not independent incident-site verification. The current eight-record input
labels incident 023 as Delhi despite its Shah Beri/Greater Noida description; retain that caveat.

## Checker and exporter commands

From the repository root, run `check` before any export. The checker records input SHA-256 hashes,
validates schemas through the existing D8 builders, compares cell IDs and optional ward IDs to
supplied geometry, and reports fatal errors, warnings and limitations. It never writes C2/C3.

```powershell
$base = "out/delhi/d10_inputs_2026-11-22"
python -m analytics.integration_check check `
  --wards-csv "$base/wards.csv" `
  --sensitivity-csv "$base/sensitivity.csv" `
  --meta-json "$base/meta.json" `
  --cells-csv "$base/cells.csv" `
  --geometry-geojson out/delhi/grid_250m.geojson `
  --ward-geometry-geojson out/delhi/wards.geojson `
  --integration-manifest out/delhi/integration_2026-11-22/integration_manifest.json `
  --d6-validation-json out/delhi/collapse_check.json `
  --report-json "$base/readiness.json"
```

After a zero exit status, `run` repeats readiness validation, invokes the existing D8 exporter,
validates C2/C3 and H3 conditions before writing, and records source/output hashes in an external
provenance JSON. Outputs are explicit and are not overwritten unless `--overwrite` is supplied.
Use a new versioned output directory for each run. Pin `--generated-utc` to make JSON outputs
reproducible for identical inputs.

```powershell
$out = "out/delhi/d8_real_2026-11-22"
python -m analytics.integration_check run `
  --wards-csv "$base/wards.csv" `
  --sensitivity-csv "$base/sensitivity.csv" `
  --meta-json "$base/meta.json" `
  --cells-csv "$base/cells.csv" `
  --geometry-geojson out/delhi/grid_250m.geojson `
  --ward-geometry-geojson out/delhi/wards.geojson `
  --integration-manifest out/delhi/integration_2026-11-22/integration_manifest.json `
  --d6-validation-json out/delhi/collapse_check.json `
  --ward-output "$out/ward_summary.json" `
  --cell-output "$out/cell_scores.geojson" `
  --validation-output "$out/validation_summary.json" `
  --figure-dir "$out/figures" `
  --provenance-output "$out/integration_provenance.json" `
  --generated-utc 2026-11-24T12:00:00Z
```

These commands were D8-phase templates for corrected intermediates. Their former expected-failure note is historical and is superseded by the final D10 acceptance addendum below. All real inputs and outputs remain under ignored `out/`; do not commit or publish restricted data.

## Current Person D intermediate compatibility

Person D's files are read from the separate `person-d-audit` checkout and are not copied or changed
by this phase.

| Producer | Available intermediate | D8 mapping / current issue |
|---|---|---|
| D1/D3 wards | `out/d1_revised/ward_indicators.csv`, `out/d3_revised/ward_inspection_index.csv` | Revised D3 has the required ward indicators and 250 wards. Its 245 ranked rows have only 239 distinct ranks (six gaps), so it fails H3's unique contiguous rank rule. Resolve ties upstream and preserve insufficient-data wards. The CSV has no C1 source hash. |
| D2 groundwater | `out/d2/groundwater_context.csv` plus `groundwater_qa.json` | `ward_id`, `gw_stage_pct`, and `gw_category` can map into the ward rows. Values use provisional Survey of India subdistrict proxies, not confirmed CGWB assessment-unit boundaries; keep that limitation visible. |
| D4 sensitivity | `out/d4/weight_sensitivity.csv` | Has `ward_id`, `rank_p05`, `rank_p95` and extra draws summaries, but only 245 ranked wards; D8 requires the sensitivity ID set to equal all ward IDs. Add explicit null ranges for the five insufficient wards after corrected D3 output; do not invent ranks. |
| D3 cells | `out/d3/cell_inspection_index.csv` | Current 19,582-row file lacks `suppressed`, `vlm_median_mm_yr`, `beta_p90_horizon`, and `cell_score`; it has `score` instead of `cell_score`. Its IDs also do not cover the supplied 23,051-cell grid. D must define and deliver a contract-compatible matching cell set and all required fields. |
| D5 published-risk | `out/d5/d5_summary.json`, `internal_consistency_checks.csv` | Internal checks are not the C3 independent comparison. VT risk geometry has null building IDs and C1 `vt_risk_insar` is null. Spatial matching needs a documented overlay rule with unmatched/ambiguous coverage; no correlation or confusion result may be fabricated. |
| D6 collapse | Team `out/delhi/collapse_check.json` | Already has the exact five-key C3 fragment. It reports no spatial comparison because coordinates are not independently verified. Preserve the source-city/date caveats; do not use Person D's approximate ward assignments as verified sites. |
| D7 hotspots | `out/d7/hotspot_summary.json`, `hotspot_crosscheck.csv` | Map each result to exactly `name`, `source`, `ward_id`, `rank`, `percentile` for `hotspot_check`. Recompute ranks after D3 correction and retain approximate locality/city provenance and out-of-Delhi exclusions. |
| D4/D5/D6/D7 C3 sections | JSON sections supplied through validation JSON and/or the D6 fragment | Missing comparisons remain null/empty with explanatory notes. Current D5 summary is not itself the C3 `vt_consistency` object; D7's nested summary is not itself the C3 array. Transform explicitly and validate. |

The saved D1/D5 aggregates are numerically consistent with the latest candidate C1, but the current
Person D checkout's `data/building_metrics.parquet` is the older C1. Existing intermediate files do
not prove their source hash. Do not treat numerical similarity as provenance.

## Person D transfer and rerun checklist

1. Transfer only D1–D5 and D7 source/tests selected by Person D. Do not transfer or replace the team
   D6, D8 or D9 files. Record commit/source versions and keep outputs in ignored versioned paths.
2. Use the staged `integration_2026-11-22/C1` and `A7/robustness` inputs and the staged reference
   C6 config. Record exact hashes. Never select the old team-root C1/config implicitly.
3. Re-run D1 against the selected C1 and validated ward geometry; report the 740,639 null ward/cell
   assignments and the assigned population rather than silently dropping them.
4. Reconcile D2 boundaries with CGWB units, or label proxy-derived values as fallback and retain QA
   coverage/area warnings.
5. Correct D3 tied ranks upstream with an explicit deterministic rule. Re-run D3, including cell
   outputs with the required field set, suppression, and geometry IDs matching the supplied grid.
6. Re-run D4's 500 weight draws and all nine A7 variants after D3. Report the 50 m variants as
   unranked where applicable. Confirm the intended A7 baseline hash with Person A.
7. Complete D5 only after an agreed VT-to-C0 spatial matching method reports matched, unmatched and
   ambiguous coverage. Keep C1 `vt_risk_insar` null until its join is approved.
8. Re-run D7 using accepted D3 ranks and documented literature-coordinate precision. Do not treat
   approximate hotspot references as independent validation.
9. Supply versioned intermediate CSV/JSON files, a complete D8 metadata JSON, optional full C3
   validation sections, and the exact D6 fragment. Include source hashes in metadata when known.
10. Run the `check` command, resolve all fatal errors, then run the versioned `run` command. Attach
    the readiness and provenance reports plus tests/schema results. The final real-data H3 review is recorded in the D10 addendum below.


---

# D10 final internal integration handoff

Generated: 2026-11-24T16:30:42Z
Accepted baseline: `help/d6-collapse-validation` at `03cdd1cf55f6db90d5ec5b9ad840dc7a94b4ea21`.

## Status

D10 readiness returned **READY** on accepted real D3/D4/C0/C1/C6 inputs. C0 quality passed; C2 ward, C2 cell and C3 outputs pass frozen schemas and H3 technical checks. This is internal technical handoff readiness, not evidence of consumer integration, independent scientific validation or public deployment authorization. Detailed matrix: `h3_acceptance_report.md`; machine-readable evidence: `d10_qa.json`.

## Authoritative inputs and outputs

- **C0 directory:** `out/delhi/`; manifest `out/delhi/PACK_MANIFEST.json`; six files: buildings.parquet, collapse_incidents.csv, grid_250m.geojson, vlm_points.parquet, vt_building_risk.parquet, wards.geojson. Quality validation passed with expected rows: buildings 1,883,862; incidents 8; grid 23,051; VLM points 182,817; risk 3,517,198; wards 250.
- **C1:** `out/delhi/integration_2026-11-22/C1/building_metrics.parquet`; run summary `out/delhi/integration_2026-11-22/C1/building_metrics.run_summary.json`. C1@1.0, engine f3af18a, 10-year horizon, seed 42, pair window 80-120 m, params hash `1a30d00c183cb58b2ee4d9327d9e839a8bc3f4267a0c3b15b207c181b49ac6d5`; 1,883,862 unique IDs, 1,055,505 non-null VLM, 238,115 non-null beta. C0-only/C1-only IDs and assignment mismatches: zero.
- **C6:** `out/delhi/integration_2026-11-22/reference/configs/delhi.yaml`; this staged reference is the selected config, not root `configs/delhi.yaml`. Full params hash agrees with C1 metadata.
- **A7:** nine Parquets under `out/delhi/integration_2026-11-22/A7/robustness/`; hashes/metadata agree with `analytics/d4/robustness_summary.json`. Baseline C1 params hash differs from nominal 100m/80-120m A7 params hash. Similar ranking does not mean identical run.
- **D1-D7 accepted outputs:** `out/delhi/integration_2026-11-22/analytics/d1/` through `d7/`; D6 output also at `out/delhi/collapse_check.json` and QA at `out/delhi/collapse_qa.json`.
- **D8 accepted outputs:** `out/delhi/integration_2026-11-22/analytics/d8/ward_summary.json`, `cell_scores.geojson`, `validation_summary.json`; methodology, metadata, QA and figures are in the same directory.
- **D10:** `out/delhi/integration_2026-11-22/analytics/d10/`.

## Reproducible real-data readiness command

Run from repository root in PowerShell:

```powershell
python -m pipeline.quality out/delhi --expected-wards 250
$root = 'out/delhi/integration_2026-11-22'
python -m analytics.integration_check check `
  --wards-csv "$root/analytics/d3/ward_index.csv" `
  --sensitivity-csv "$root/analytics/d4/ward_sensitivity.csv" `
  --meta-json "$root/analytics/d8/inputs/meta.json" `
  --cells-csv "$root/analytics/d3/cell_scores.csv" `
  --geometry-geojson 'out/delhi/grid_250m.geojson' `
  --ward-geometry-geojson 'out/delhi/wards.geojson' `
  --integration-manifest "$root/integration_manifest.json" `
  --validation-json "$root/analytics/d8/inputs/validation.json" `
  --report-json "$root/analytics/d10/d10_qa.json" `
  --overwrite-report
```

The validation JSON already includes D4/D5/D6/D7 and fresh-data sections; do not pass the D6 fragment again. `check` writes only the explicit ignored report path and does not regenerate D8 or rerun D1-D7.

## H3 summary

- **C2 ward:** 250 unique ward IDs match C0; 245 ranked, five insufficient-data; ranks 1-245 contiguous; scores/ranks match D3; all D4 intervals match and bracket baseline; 50% coverage rule applied. Groundwater null. Histogram null is allowed because no binning/denominator was agreed.
- **C2 cells:** 23,051 unique grid IDs and geometries match C0; 19,582 populated; 3,469 empty; 15,595 scored; 7,456 suppressed. All suppressed metrics/ranks null; within-ward ranks contiguous. Canonical cell ward follows largest positive-area intersection. Cross-boundary cells may contain neighboring-ward buildings; ward polygons overlap.
- **C3:** accepted D4 results; D5 zero accepted exact matches with rho null and empty confusion matrix; D6 eight source-city labels but no independently verified coordinates; D7 four records with two approximate comparable ranks; fresh-data status `not_run`, no HyP3 job or displacement product.

## Consumer responsibilities

### Person B
Use the real ward summary and cell GeoJSON above. Preserve ward/cell IDs, geometry, suppression, null metrics and ranks. Private package `analytics/d8/handoff/delhi-c2-person-b.zip` is unchanged and retains its D8 checkpoint warning. Tile generation/H4 acceptance is separate and not verified.

### Person C
Use C2 ward/cell and C3 validation outputs. Preserve null groundwater/histogram and render unavailable evidence as unavailable, not zero. Private package `analytics/d8/handoff/delhi-c2-c3-person-c.zip` is unchanged with its original D8 warning. Receipt and frontend integration are unverified; internal use only.

### Person E
Use C0 `out/delhi/`, latest C1 above, C2 ward `.../analytics/d8/ward_summary.json`, C2 cell `.../analytics/d8/cell_scores.geojson`, C3 `.../analytics/d8/validation_summary.json`, and selected C6 config above. Verify file hashes against D8 `SHA256SUMS.txt`/D10 QA before configuration. The D branch worktree does not check out the FastAPI implementation. A read-only inspection of local `e/api-insar` at `e47993d35c37e49db69fc00f7142c9ec73db44ed` confirms `Settings` is defined in `api/main.py` (there is no `api/config.py` or `api/settings.py`) and artifact paths are defined in `api/data.py`. Production requires explicit `API_ENV=production`, nonempty `AUTHORITY_TOKEN`, and `API_WARD_SUMMARY_PATH`, `API_CELL_SCORES_PATH`, `API_VALIDATION_SUMMARY_PATH`, and `API_BUILDING_METRICS_PATH`. No `API_BUILDINGS_PATH` variable is declared; buildings reads use the metrics path and optional geometry path. `API_BUILDINGS_GEOMETRY_PATH` is optional in configuration but should point to C0 `out/delhi/buildings.parquet` for real bbox/building geometry responses; `API_CORS_ORIGINS` is optional and should contain the exact frontend origin; `API_VERSION` is optional and defaults to `starter`. The default environment is production; mock/demo-token fallback requires explicit `API_ENV=dev`, and configured `AUTHORITY_TOKEN` takes precedence. Person E should verify this mapping on the E branch before E9. No E9 code integration was performed.

## Provenance and restrictions

All 19 D8 checksum entries, three package hashes, ZIP CRCs and package member checksums passed; packaged C2/C3 primary files match accepted D8 outputs. All 46 recorded provenance source hashes passed. Historical D1 QA references the prior manifest SHA `e1a77f318ebe51946710f231cae8633613586d9b2ef4b7b862d88c1747b131fb`; the current manifest is `a3e2a6c4c0e2e10d41ff32859a7ba0d49880481c7e25c88a3d41e19eff5e2cd0`. D1 predates the update; historical bytes are unavailable. This is the sole accepted historical exception. D7 canonical digest excludes `outputs` (`060f3d8d7f8669ed3155ddcb3e7cf54ea90151cc54b45fd6ea905248cba33f74`); full-file SHA is `d4504aaae21eced0c65af17cd168c966987953a2ef535f361be98e54b71f1ba6`.

Limitations: sparse angular-distortion coverage; unverified CGWB boundaries and excluded I4; null histogram; 740,639 unassigned C0 buildings; cell boundary and overlapping ward geometry behavior; D4 uncertainty and unavailable 50m comparisons; D5 matching unavailable; D6 no verified incident locations (023 conflicts with Shah Beri/Greater Noida); D7 approximate references/small sample; no new Sentinel-1/HyP3 product. This is a relative inspection-prioritization index, not a collapse probability or safety certification. Independent validation and expert review are pending.

**Internal use only:** ward-source rights remain unresolved. Do not publish, deploy publicly or distribute outside the team. D8 packages remain byte-identical checkpoint artifacts with their original pending-D10 warning. This separate D10 report does not send or upload them.

## Decisions

- H3 technical acceptance: **PASS WITH DOCUMENTED LIMITATIONS**.
- D10 task: **COMPLETE WITH DOCUMENTED LIMITATIONS**.
- Internal handoff: **READY** for consumer integration; receipt/integration by B/C/E unverified.
- E9 technical start: **READY for internal E-branch integration**, subject to Person E configuration confirmation and existing data restrictions; E9 itself was not performed.
- Independent scientific validation: **NOT COMPLETE**; external expert review: **PENDING**.
- Public deployment: **NOT AUTHORIZED**.
