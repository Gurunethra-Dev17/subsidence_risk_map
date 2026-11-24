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

These are command templates for corrected D intermediates. They are not evidence that current D
files pass. The current readiness check is expected to fail until upstream gaps below are resolved.
All real inputs and outputs remain under ignored `out/`; do not commit or publish restricted data.

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
    the readiness and provenance reports plus tests/schema results. D10/H3 acceptance remains a
    separate review after real outputs exist.
