# SUBSIDENCE RISK MAP — Implementation and Working Plan

**Document:** 2 of 3 — who builds what, how each person works independently, and when work must be handed over.
**Companion files:** `01_SOLUTION.md` (what we build) and `03_CODEBASE_AND_API_CONTRACTS.md` (repository layout and frozen contracts C0–C6).

There are five people: **Person A, B, C, D, E**. There are no calendar dates here. The plan is organised by **work packages** and **handoff gates (H0–H7)**, so it works whether you have four days or fourteen. Effort is stated in hours of work, not days.

---

## 1. Principles

1. **Contracts first.** Every file one person produces for another is defined in `03_CODEBASE_AND_API_CONTRACTS.md` and frozen at v1.0. Nobody waits for another person's real output to start. They build against mock files that follow the contract.
2. **Mocks first, real data later.** Each package must run `make demo` using mock fixtures. Integration means swapping a mock file for the real file.
3. **One owner per folder.** You change only your folder. Changes to `contracts/` go through the change process in section 8.
4. **Equal-sized packages.** Each person has a substantial technical package of about 44–47 hours. No one is assigned documentation or demos only.
5. **Blocked for more than 60 minutes means switch to the fallback** in your package and post a note. Never sit waiting.

## 2. Packages at a glance

| Person | Package | Folders owned | Effort (h) | Share doable without anyone else |
|---|---|---|---|---|
| **A** | Geospatial core engine (assignment, distortion, building metrics) | `engine/`, `contracts/`, `configs/` | 47 | ~79% |
| **B** | Data pipeline, vector tiles, hosting, city portability | `pipeline/`, `data/` | 45 | ~84% |
| **C** | Frontend application | `web/` | 46 | ~82% |
| **D** | Ward scoring, groundwater context, uncertainty and validation analytics | `analytics/` | 44 | ~66% |
| **E** | API service, server-side briefs, fresh-InSAR and time-series track | `api/`, `insar/` | 47 | ~94% |

Each package also supplies one section of the final submission material (method, data lineage, live app, validation summary, API and InSAR note), so no one is a pure "writer".

*Availability note:* packages D and E are built from self-contained modules that can be done in separate blocks of time. This affects scheduling only, not the size of the work.

---

## 3. Work packages

Column key: **Needs** = input from someone else (blank means independent). **Dep** marks effort that needs another person's output. Estimates are working hours.

### 3.1 Person A — Geospatial core engine

**Mission:** turn baseline radar points and building footprints into per-building ground-motion and distortion metrics (contract C1), correctly, reproducibly and fast.

| ID | Task | Needs | Produces | Hours | Dep |
|---|---|---|---|---|---|
| A0 | Create the repository skeleton, commit the contracts and mock fixtures from file 03, add the schema-validation script | — | `contracts/`, `contracts/mock/`, `contracts/validate.py` | 2 | |
| A1 | Config loader (C6) and point loaders: unit conversion cm/yr → mm/yr, sign check, city UTM projection, bbox clip, point-density statistics | — | `engine/io.py` | 4 | |
| A2 | Point-to-building assignment: KD-tree radius query, inverse-distance weighted median, minimum-points rule, `sparse` flag, vectorised and chunked for millions of buildings | Real buildings preferred. Fallback: synthetic buildings or the published shapefile geometry | `engine/assign.py` | 7 | |
| A3 | Angular distortion module: point pairs within 10–60 m, per-pair rate, building-level 90th percentile within buffered footprint, horizon projection, ratio string, class assignment | — | `engine/distortion.py` | 8 | |
| A4 | Unit and property tests with synthetic fixtures, including the worked example (−10 and −6 mm/yr, 20 m apart → 1/500 at 10 years); regression snapshots | — | `engine/tests/` | 5 | |
| A5 | Performance and memory: benchmark on the pilot city, chunked processing by tile or ward, GeoParquet I/O, command-line entry point, run logging | B's real building pack (H1) | `python -m engine.run` | 6 | 6 |
| A6 | Export `building_metrics.parquet` per C1 with engine version and parameter hash; deterministic runs | — | C1 export | 4 | |
| A7 | Parameter robustness runner: re-run with `radius_m` ∈ {50, 100, 150} and pair-distance variants, store outputs in a standard layout | — | `engine/robustness.py` | 4 | |
| A8 | Integration support: fix schema or data issues found by downstream consumers, keep the validator current | D, E, C feedback | patches | 4 | 4 |
| A9 | Engine method note (formulas, parameters, limits) and docstrings; supplies the "method" section of the submission | — | `engine/METHOD.md` | 3 | |
| | | | **Total** | **47** | **10** |

**Independent effort:** 37 of 47 hours (~79%).
**Fallbacks:** if the real building pack is late, use the published risk shapefile geometry (if it contains buildings) or a synthetic building grid built over the point extent; for benchmarking, download one ward of buildings directly with `obe`.

### 3.2 Person B — Data pipeline, tiles, hosting, portability

**Mission:** produce clean, versioned, reproducible data packs (C0) and map tiles (C5) for any city from configuration alone.

| ID | Task | Needs | Produces | Hours | Dep |
|---|---|---|---|---|---|
| B1 | Acquire the published dataset and audit it: file list, columns, units, geometry type, risk coding, collapse spreadsheet fields, licence text | — | `data/AUDIT.md` | 3 | |
| B2 | Buildings pipeline with `obe`/Overture: bounding-box tiling, attribute normalisation, deduplication, invalid-geometry repair, sliver removal; parameterised by city | — | `pipeline/buildings.py`, GeoParquet | 7 | |
| B3 | Wards pipeline: Delhi 2022 wards (OpenCity), fallback DataMeet/GSDL; standard IDs, names, CRS; validation report | — | `pipeline/wards.py`, `wards.geojson` | 4 | |
| B4 | 250 m grid generator in the city's UTM zone with stable cell IDs, clipped to the city | — | `grid_250m.geojson` | 2 | |
| B5 | Data pack builder: bundles files, writes `PACK_MANIFEST.json` with hashes, row counts, sources, licences, attributions; versioned releases | — | C0 packs | 4 | |
| B6 | Vector tile build (tippecanoe → PMTiles): ward polygons, cells, buildings; attribute joins from C1/C2 exports; zoom and size tuning; chunked-GeoJSON fallback | Geometry tiles independent (4 h). Attribute join needs C1/C2 exports (4 h) | `*.pmtiles` per C5 | 8 | 4 |
| B7 | Static hosting of tiles and data: object storage or static host, CORS, cache headers, URL conventions per C5 | — | live tile URLs | 3 | |
| B8 | City portability: run the full pipeline for a second city by configuration only (Chennai: UTM 44N, city wards), record every manual step that was needed | — | `configs/chennai.yaml`, portability notes | 6 | |
| B9 | Data lineage and licence compliance: sources, access dates, attributions (Overture ODbL), confirm the published dataset's licence; supplies the "data" section of the submission | — | `data/LINEAGE.md` | 2 | |
| B10 | Automated data-quality tests: ward count, geometry validity, CRS, null IDs, building counts, duplicate IDs | — | `pipeline/tests/` | 3 | |
| B11 | Integration support: rebuild packs and tiles when contracts or fields change | A, D, C, E feedback | rebuilds | 3 | 3 |
| | | | **Total** | **45** | **7** |

**Independent effort:** 38 of 45 hours (~84%).
**Fallbacks:** if tippecanoe or PMTiles tooling fails, publish per-ward GeoJSON files, gzip-compressed, loaded on demand; if OpenCity wards fail, use DataMeet or the city's government GIS service; if Overture is too large, restrict extraction to the pilot wards.

### 3.3 Person C — Frontend application

**Mission:** a fast, accessible map application that makes the ranking understandable and usable by a non-specialist.

| ID | Task | Needs | Produces | Hours | Dep |
|---|---|---|---|---|---|
| C1 | App scaffold (Vite, React, TypeScript, MapLibre GL), design tokens, responsive layout, environment config for API and tile URLs, **mock mode** driven by contract fixtures; generate TypeScript types from the JSON Schemas | — | `web/` shell | 5 | |
| C2 | Ward choropleth with colour-blind-safe scale, legend, hover and selection, hatched "insufficient data" style | — | map layer | 5 | |
| C3 | Ranking table: sort, search, filter, rank-range display, selection synchronised with the map | — | ranking panel | 4 | |
| C4 | Ward detail panel: indicators with tooltips, distortion histogram, uncertainty badges | — | detail panel | 6 | |
| C5 | Layer manager: radar points, cells, buildings via PMTiles; zoom-dependent rendering; layer toggles | Mock tiles (3 h). Real tiles from H4 (3 h) | layers | 6 | 3 |
| C6 | Public and authority modes: feature flag, UI states, building layer gating, token entry | — | mode switch | 3 | |
| C7 | Brief preview and download from the API, with a client-side print fallback | API brief endpoint (fallback: print) | brief UI | 3 | |
| C8 | Methods, limits and validation pages rendered from the repository files | Page text and figures from A9 and D8 (1.5 h); layout independent | static pages | 3 | 1.5 |
| C9 | Performance (bundle size, tile loading), mobile responsiveness, error, empty and loading states, keyboard accessibility, contrast checks | — | quality pass | 5 | |
| C10 | CI build, preview deployments, production deployment | — | deploy pipeline | 2 | |
| C11 | Integration with real API and tiles; fixes; the live-app section of the submission (screens and flow) | H4, H5 | integrated app | 4 | 4 |
| | | | **Total** | **46** | **8.5** |

**Independent effort:** 37.5 of 46 hours (~82%).
**Fallbacks:** run entirely in mock mode; if building tiles are late, ship wards and cells only; if the API is late, read static JSON exports directly.

### 3.4 Person D — Scoring, groundwater, uncertainty and validation analytics

**Mission:** convert building metrics into the ward ranking, show how reliable it is, and test it honestly against published results.

| ID | Task | Needs | Produces | Hours | Dep |
|---|---|---|---|---|---|
| D1 | Ward aggregation: spatial join of buildings to wards, indicators I1–I4, coverage, wards with no buildings | Developed on mock C1 or a quick fallback built from published data | `analytics/aggregate.py` | 5 | |
| D2 | Groundwater context: extract the CGWB assessment table for the pilot city (PDF table extraction), obtain assessment-unit boundaries (DataMeet), area-weighted join to wards, document every assumption | — | `analytics/groundwater.py`, `groundwater_context.csv` | 7 | |
| D3 | Inspection Index: percentile normalisation, configurable weights, coverage rule, groundwater fallback, ranking; cell index | — | `analytics/index.py` | 4 | |
| D4 | Sensitivity analysis: Dirichlet weight perturbation (500 draws), rank ranges, Kendall τ (3 h independent); radius-variant stability using A7 runs (3 h) | A7 outputs for the radius part | `analytics/sensitivity.py` | 6 | 3 |
| D5 | Consistency check against the published risk categories: Spearman ρ, confusion matrix, per-ward breakdown | A's real C1 output | `analytics/vt_consistency.py` | 4 | 4 |
| D6 | Collapse-incident analysis: filter the 26 incidents to the pilot city, locate against published risk categories and later our ranks; honest caveats | — (published data only) | `analytics/collapse_check.py` | 4 | |
| D7 | Hotspot cross-check: compile named literature hotspots with coordinates (2 h independent); compare with our ward ranks (2 h) | A and D3 output for the comparison | `analytics/hotspots.py` | 4 | 2 |
| D8 | Export `ward_summary.json` (C2) and `validation_summary.json` (C3) plus figures; development against mocks (2 h), final run (2 h); supplies the "validation" section of the submission | Final run needs real inputs | exports, `figures/` | 4 | 2 |
| D9 | Mentor review package: two-page method and validation summary, five specific review questions, outreach draft | — | `analytics/REVIEW_PACK.md` | 2 | |
| D10 | Integration support: re-runs and fixes when upstream data or contracts change | A, B feedback | re-runs | 4 | 4 |
| | | | **Total** | **44** | **15** |

**Independent effort:** 29 of 44 hours (~66%).
**Fallbacks:** if A's building metrics are late, use `analytics/fallback.py` — a quick, clearly labelled assignment of published points and pair distortion for development only. Final results must use A's engine output.

### 3.5 Person E — API service, server-side briefs, fresh-InSAR and time-series track

**Mission:** serve the data through a stable, documented API with server-side briefs, and prove the pipeline can ingest fresh satellite data.

| ID | Task | Needs | Produces | Hours | Dep |
|---|---|---|---|---|---|
| E1 | API scaffold (FastAPI), settings, error model, OpenAPI document that matches contract C4 | — | `api/` shell | 4 | |
| E2 | Data layer: DuckDB over GeoParquet and JSON for wards, cells and buildings; bounding-box queries, ward filters, pagination, ETag caching | Mock fixtures | `api/data.py` | 6 | |
| E3 | Endpoints per C4: `/meta`, `/wards`, `/wards/{id}`, `/wards/{id}/cells`, `/validation`, `/buildings` (authority only), `/health` | — | endpoints | 6 | |
| E4 | Server-side brief PDF (WeasyPrint or ReportLab): ward numbers, uncertainty statement, cell list, map thumbnail, caveats | Mock ward summary | `/wards/{id}/brief.pdf` | 6 | |
| E5 | Authority token gating, rate limiting, CORS, input validation, security tests | — | access control | 4 | |
| E6 | Contract tests against the OpenAPI document and JSON Schemas, CI, load test, Dockerfile and deployment | — | CI, container | 5 | |
| E7 | Fresh-InSAR pipeline: find Sentinel-1 bursts with `asf_search` for an area and date pairs, submit and poll HyP3 jobs through its SDK, download, post-process to GeoTIFF and image overlay with metadata; command-line and notebook | Free Earthdata account | `insar/refresh.py` | 8 | |
| E8 | Time-series feasibility: check LiCSAR frame coverage for the pilot city, run LiCSBAS on a small area if frames exist, compare velocities with baseline points, write a feasibility note; supplies the "API and InSAR" section of the submission | — | `insar/FEASIBILITY.md` | 5 | |
| E9 | Real-data integration: switch from mocks to real exports, fix mismatches | H3, H4 | integrated API | 3 | 3 |
| | | | **Total** | **47** | **3** |

**Independent effort:** 44 of 47 hours (~94%).
**Fallbacks:** if HyP3 jobs are slow or fail, use a previously downloaded product and document the dates; if LiCSAR frames do not cover the city, report that finding and stop E8 there; if hosting limits bite, serve the same endpoints from precomputed static files.

### 3.6 Effort balance

| Person | Hours | Independent hours | Needs others |
|---|---|---|---|
| A | 47 | 37 | 10 |
| B | 45 | 38 | 7 |
| C | 46 | 37.5 | 8.5 |
| D | 44 | 29 | 15 |
| E | 47 | 44 | 3 |
| **Total** | **229** | **185.5 (81%)** | **43.5 (19%)** |

---

## 4. Handoff gates (when to depend on someone)

Each gate has a producer, consumers, an acceptance check, and what the consumers do while waiting. A handoff is complete only when the acceptance check passes.

| Gate | Producer → Consumers | Artefact (contract) | Acceptance check | While waiting / if late |
|---|---|---|---|---|
| **H0** | A → everyone | Contracts v1.0 and mock fixtures committed (C0–C6) | `make validate-contracts` passes; every package runs `make demo` on mocks | Nothing is blocked. Everyone starts in parallel |
| **H1** | B → A, D | Data pack v1 (C0): wards, buildings, radar points, published risk shapefile, grid, manifest | Manifest hashes match; ward count equals the official count; no null or duplicate IDs; CRS present; building counts plausible | A uses synthetic or published-shapefile buildings. D uses mocks |
| **H2** | A → D, E, C, B | `building_metrics` v0 (C1) from the real engine | Passes C1 schema; non-null share reported; worked-example test passes in CI | D uses `analytics/fallback.py`. E and C stay on mocks |
| **H3** | D → C, E, B | `ward_summary.json` and `validation_summary.json` (C2, C3) | Pass schemas; ranks are 1..N for ranked wards; rank ranges bracket ranks; coverage rule applied | C and E stay on mocks. A uses its own summary statistics to sanity-check |
| **H4** | B → C, E | Tile and static-data URLs (C5) with attribute joins from C1/C2 | Tiles load in the app at target zooms; attribute names match C5; attribution present | C uses mock tiles. Fallback: per-ward GeoJSON |
| **H5** | E → C | API live on a staging URL (C4) | Contract tests pass; `/wards` returns real data; authority token blocks `/buildings` without a token | C reads static exports directly |
| **H6** | A, D, B, E → C | Release candidate: all artefacts regenerated from a clean checkout with one version tag | `make all` reproduces every artefact; all schemas pass; numbers in the app match the exports | Keep previous tag live |
| **H7** | Everyone → submission | Each owner's section: method (A), data lineage (B), live app (C), validation (D), API and InSAR (E) | Each section matches the code and the release tag | — |

**Sequence in words:** after H0 every person works alone. The first real dependencies are H1 and H2 (data to engine, engine to analytics). H3 to H5 connect analytics, tiles and API to the app. H6 locks the release candidate. H7 assembles the submission.

---

## 5. Independence plan

For each person: how long they can work without anyone else, the first thing they need, and the fallback.

| Person | Work they can do entirely alone | First real need | Fallback | Needs-others share |
|---|---|---|---|---|
| **A** | A0, A1, A2 (on synthetic or published geometry), A3, A4, A6, A7, A9 — about **37 h** | Real buildings for benchmarking (A5) at H1; consumer feedback (A8) after H2 | Synthetic buildings; one ward downloaded directly | ~21% |
| **B** | B1–B5, B7–B10 plus geometry-only tiles — about **38 h** | Metrics and summaries for tile attributes (B6) at H2/H3 | Ship geometry-only tiles first; add attributes on later rebuild | ~16% |
| **C** | Entire UI in mock mode (C1–C4, C6, C7 fallback, C9, C10, mock-tile layers) — about **37.5 h** | Real tiles (H4), real API (H5), page content (H3) | Mock mode; static JSON; wards-and-cells only | ~18% |
| **D** | D1–D3, weight-sensitivity, D6, hotspot compilation, D9, export development — about **29 h** | Real building metrics (D5, D7 comparison, radius sensitivity) at H2 | `analytics/fallback.py` for development only | ~34% |
| **E** | E1–E8 — about **44 h**, almost entirely alone | Real exports for final integration (E9) at H3/H4 | Serve mock or static artefacts | ~6% |

**Reading this table:** E and B can work longest without anyone. D has the most reliance on others and therefore owns the most mock-driven development. A is the only person whose output is a dependency for three others, so A's A2–A3 have the highest delivery weight in the team, and A should post engine v0 (H2) as soon as it passes the worked-example test, even before performance work is complete.

### What each person should have before they first need anyone

| Person | Deliverable that exists before the first dependency |
|---|---|
| A | Passing distortion tests and a working assignment on synthetic data |
| B | Data audit, buildings and wards pipelines, grid, a first data pack |
| C | Complete mock-mode app with map, ranking, detail panel, modes |
| D | Aggregation, groundwater table and join, index and sensitivity code on mocks |
| E | Running API on mocks with brief PDF and a first fresh-InSAR product |

---

## 6. How to work together

### 6.1 Repository rules

- One repository, folder ownership as in section 2. You edit only your folders.
- `contracts/` is owned by A as steward. Any change follows section 8.
- Branches: `a/…`, `b/…`, `c/…`, `d/…`, `e/…`. Merge to `main` by pull request.
- Review pairs: **A↔D** (engine and analytics), **B↔E** (data and API), **C↔E** (UI and API), **A↔B** (data pack and engine). Every pull request needs one reviewer from its pair.
- `main` must always pass `make validate-contracts` and `make demo`.
- Large files (data packs, tiles) live on shared storage with a manifest. Do not commit them.

### 6.2 Communication

- One shared thread. Post a status in this form whenever something changes: **Done / Doing / Blocked on (who, what) / Fallback in use**.
- A 10-minute sync each time a gate (H1–H6) is due. Otherwise work asynchronously.
- If blocked for more than 60 minutes, switch to the fallback, post it, and carry on.

### 6.3 Definition of done for any task

1. Code or analysis committed, tests passing.
2. Output validates against the relevant schema.
3. A one-line note in the shared thread saying where the artefact is.

## 7. Risks and fallbacks

| Risk | Effect | Fallback |
|---|---|---|
| Published dataset's licence is unclear | Cannot re-host | Link to it, instruct users to download, keep only derived aggregates |
| Shapefile geometry or `Risk_*` coding differs from expectation | Consistency check changes | B documents in `data/AUDIT.md`; D adapts D5 |
| Radar-point density is too sparse in many wards | Many "insufficient data" wards | Report coverage honestly; lower `radius_m` sensitivity; no imputation |
| Engine too slow for millions of buildings | Late metrics | Chunk by ward; restrict to ranked wards first; profile before optimising |
| Ward boundaries stale or inconsistent | Wrong aggregation | Cross-check with government GIS; document vintage |
| Tile tooling fails | No building layer | Per-ward GeoJSON fallback; cells only |
| HyP3 quota, queue or processing failure | No fresh-data demo | Use an earlier product; document dates; report as feasibility |
| LiCSAR frames missing for the city | No time series | State finding; keep baseline |
| Groundwater table extraction fails | No I4 | Drop I4, renormalise weights, flag |
| Validation results look weak | Credibility | Report as found; explain limits; no tuning to targets |
| Public map could harm property values | Reputational | Public view only wards and cells with ≥ 5 buildings; building view needs authority token |
| Contract change late in the build | Breakage | Additive changes only (section 8) |

### If time is short, drop in this order (last item first)

1. Second-city dry run (B8)
2. Time-series feasibility (E8)
3. Fresh-InSAR refresh (E7)
4. Server-side brief (E4) — fall back to client print (C7)
5. Authority mode and building tiles (C6, B6 buildings) — keep wards and cells
6. API (E-package) — fall back to static JSON exports

The **core** that must always ship: engine (A), data pack (B), ward ranking with rank ranges and groundwater context (D), ward map with ranking and detail panel and brief (C), and honest validation.

## 8. Contract change process

1. Any package can propose a change by posting the change request to the shared thread with the reason.
2. A decides whether it is **additive** (new optional field, new endpoint: minor version) or **breaking** (rename, remove, retype: major version).
3. Breaking changes need agreement from every consumer of that contract and are avoided. Prefer adding a new field.
4. A updates the schema, mock fixture and `contracts/CHANGELOG.md` in one pull request. Consumers update their code within one working session.

## 9. After shortlisting (if selected)

**Refinement phase (about two weeks):**

| Person | Extension work |
|---|---|
| A | Seasonal/trend separation on time series, finer distortion model, performance for second city |
| B | Second city onboarded end to end, scheduled data refresh, tile optimisation |
| C | Usability testing with real ward engineers, mobile polish, comparison view (baseline vs fresh data) |
| D | Mentor feedback on thresholds and index, expanded validation, uncertainty communication |
| E | Time-series API endpoints, scheduled fresh-InSAR runs, hardening and monitoring |

**Event phase (48 hours):** freeze scope early; A presents method and validation answers; C drives the live demo; B owns data and hosting reliability; D answers validation and robustness questions; E owns API reliability and the fresh-data segment. Rehearse the live flow (select ward, read uncertainty, download brief, switch mode) until it is routine.

## 10. Submission material — who supplies what

| Section | Supplied by | Source |
|---|---|---|
| Problem, gap, solution | Shared | `01_SOLUTION.md` |
| Method and parameters | A | `engine/METHOD.md` |
| Data and licences | B | `data/LINEAGE.md` |
| Live app and flow | C | deployed URL, screens |
| Scoring and validation results | D | `validation_summary.json`, figures |
| API and fresh-data demonstration | E | OpenAPI document, `insar/FEASIBILITY.md` |

A final read-through for consistency with the release tag happens at H7, with every owner checking their own section against the code.
