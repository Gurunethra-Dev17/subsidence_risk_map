# Project progress and work log

**Updated:** 2026-11-16
**Working branch:** `a/building-distortion`

This document records what has been implemented in the repository so far, how it maps to the supplied implementation plan, and what remains open. The planning documents describe intended work; entries below describe repository changes and checks actually performed.

## Summary

The shared H0 repository scaffold was committed to `main`. Person A has implemented the C6/VLM input loader and building point-assignment module on `a/config-point-loaders`. A CI failure caused by an incorrect Shapely import in the VLM loader was fixed in commit `e298e3f` and pushed. GitHub Actions CI run #8 passed on the updated branch; PR #1 is open: https://github.com/Gurunethra-Dev17/subsidence_risk_map/pull/1. The C4@1.0 OpenAPI description has been aligned on `a/c4-openapi-alignment`; the API implementation remains outstanding.

The core geospatial engine is still in progress. A1/A2 are implemented, and the focused VLM loader integration test passes locally. A3 angular-distortion calculation, A4 regression tests, and A5-A7 engine work are implemented on `a/building-distortion`. The B-supplied C0 candidate passes local preflight. The chunked engine CLI, C1 exporter, and robustness runner have been exercised on a ward-scoped internal pilot; the full-city run remains unbenchmarked and the data/output remain local.

## Work completed

### Shared initial setup (H0 starter)

Commit `8565e7a` — `setup: add shared project scaffold and contracts` — added:

- Starter folders and ownership landing pages for Persons A–E.
- C0–C3 and C6 JSON schemas, a C4 OpenAPI outline, C0–C3/C6 fixtures, and C5 GeoJSON layer examples.
- Delhi and Chennai configuration files.
- The contract validator, Makefile commands, Python project metadata, and an initial GitHub Actions workflow.
- Copies of the three supplied planning documents under `docs/`.

The fixtures are deliberately small and synthetic. The mock C0 pack still uses JSON and CSV stand-ins instead of the full GeoParquet pack described in the contract. A C1 `building_metrics.parquet` fixture has now been generated from the canonical C1 JSON fixture. The tile fixtures are GeoJSON, not PMTiles.

### Person A A1 — configuration and VLM point loading

Commit `8a180ab` — `engine: add config and VLM point loaders` — added `engine/io.py` and documented its use in `engine/README.md`.

- `load_config(path)` validates a C6 YAML file, checks required parameters and the bbox/weight values, and resolves pack/output paths.
- `load_vlm_points(cfg)` reads Parquet or development CSV/JSON inputs, converts `vlm_cm_yr` or generic `vlm` values to mm/yr, clips rows to the configured bbox, and returns EPSG:4326 point geometries.
- Negative rates remain negative and are documented as sinking. No sign inversion is performed.
- Point counts, value range, UTM-projected bbox area, density, and sign counts are attached as load statistics.

### CI packaging correction

Commit `fde74fe` — `setup: configure package discovery for CI` — added an explicit setuptools package include list and build backend to `pyproject.toml`.

This followed a local reproduction of the editable-install failure: setuptools rejected automatic discovery because the repository contains multiple top-level packages. This was the likely cause of the failed CI run for the initial setup. GitHub's authenticated check logs were not accessible from this environment, so the precise hosted failure log was not independently retrieved.

### Person A A2 — point assignment to buildings

Commit `393566c` — `engine: assign motion points to buildings` — added `engine/assign.py` and documented the function in `engine/README.md`.

- `assign_points_to_buildings(buildings, points, cfg)` projects buildings and points into the configured UTM zone.
- It queries points within `radius_m` of each building centroid and processes buildings in chunks (50,000 by default).
- With at least `min_points`, it returns an inverse-distance weighted median and weighted IQR. Exact coincident points share weight equally and dominate non-coincident observations.
- Buildings below the minimum, including all buildings when the point input is empty, are marked sparse and receive null estimates.
- The result preserves building order and includes `bldg_id`, `n_points`, `vlm_mm_yr`, `vlm_iqr_mm_yr`, and `sparse`.

New synthetic tests cover source-unit conversion, bbox boundaries, weighted quantiles, radius counts, exact-coordinate weighting, sparse/empty inputs, output ordering, and the public loader/assignment interfaces.

### Person A A3 — building angular distortion

`engine/distortion.py` adds `compute_building_distortion(buildings, points, cfg)` with the C1 output columns.

- Projects building footprints and VLM points into the configured UTM zone.
- Counts unique point pairs in the configured distance interval when at least one endpoint lies within the buffered building footprint.
- Computes absolute differential rate per pair, the building-level 90th percentile, and the configured horizon scenario.
- Returns null distortion metrics for buildings with fewer than three pairs, formats the horizon ratio, and assigns `low`, `watch`, or `inspect` from the configured ratio edges.

A4 adds worked-example, public-interface regression, boundary, and permutation/sign-invariance checks for this calculation.

### Person A A5 - chunked processing and command line

`engine/run.py` provides `python -m engine.run`. It streams C0 GeoParquet record batches, optionally filters to a ward and/or building limit, computes assignment and distortion metrics per bounded batch, writes temporary C1 fragments, and combines them atomically into one C1 Parquet file. It records per-chunk progress in a local log and writes a run summary with the pack version, parameter hash, row count, and VLM coverage. The Delhi pilot was run on Ward 125; a full-city benchmark is still outstanding.

### Person A A6 - C1 Parquet export

`engine/export.py` joins C0 building attributes with A2 assignment and A3 distortion results by `bldg_id`, validates unique and complete building coverage, and writes the C1 Parquet fields and metadata. The parameter hash is SHA-256 over canonical JSON for the C6 `params` mapping; writes use a temporary file followed by atomic replacement. The exporter reports the non-null share of `vlm_mm_yr` for the H2 handoff.

### Person A A7 - parameter robustness

`engine/robustness.py` runs the Cartesian product of configured radius and pair-distance variants. It reuses assignments across pair windows and distortion outputs across radii, writes each C1 export into a stable variant directory, and creates `robustness_summary.json` with each run's parameters, parameter hash, row count, and VLM coverage. Delhi and Chennai C6 configs declare `[10, 40]`, `[10, 60]`, and `[20, 60]` metre pair windows.

## Checks performed

- The contract validator passed for the six schema-backed fixtures after the initial setup and again during the packaging fix.
- `load_config('configs/delhi.yaml')` returned the expected city, UTM EPSG, bbox, and resolved pack path.
- Python syntax compilation passed for `engine/io.py` and `engine/assign.py`.
- `git diff --check` passed for the A2 change.
- `python -m pytest -q` completed with **9 passed, 2 skipped**. The skipped tests exercise the full GeoDataFrame point-loader and assignment interfaces; both are skipped only when the local Application Control policy blocks Pandas' `interval` DLL. Other import failures remain test failures.
- CI now installs the `geo` extra and runs `make test` so those two integration tests execute in the Linux workflow environment.
- The GitHub Actions run shared for the branch reported **10 passed, 1 failed**. Its failure was in the VLM CSV integration test: normalized values are a NumPy array, but the bbox filter used pandas `.loc` on that array. This was corrected to boolean-array indexing (`values[inside]`); the local suite and contract validator pass after the correction, while the local geospatial integration tests remain skipped by the DLL policy.
- The subsequent CI run found a separate VLM loader import error: `points_from_xy` was imported from `shapely.geometry`, which does not provide it. Commit `e298e3f` now uses `geopandas.points_from_xy`. The focused local integration test was attempted but skipped because local geo dependencies are unavailable. GitHub Actions CI run #8 on this commit completed successfully.
- The focused VLM loader integration test was later run locally and passed (**1 passed**) after Smart App Control was turned off for the test environment.
- The C4 OpenAPI document now includes response/error schemas, the `/buildings` query parameters, ETag and cache policy headers, and the configured-origin CORS policy. Its YAML parses successfully; API implementation and contract tests remain outstanding.
- A3-A7 are implemented on `a/building-distortion`; A5-A7 have been exercised on a bounded real-data pilot. The full-city engine run is pending further performance profiling.
- The B-supplied C0 candidate now includes valid GeoParquet building geometry. The C0/C1 join key is `bldg_id`; the VT risk file has no joinable `bldg_id` values, so `vt_risk_insar` remains null in current exports. The pack and derived outputs are restricted to internal prototype use while the ward-source licence is unresolved.
- DuckDB is included in the `api` optional dependency extra for reproducible API installs.
- A local editable-install dry run reproduced the initial setuptools flat-layout discovery error. After package discovery was configured, a no-build-isolation dry run reached a separate local limitation: this environment lacks the `bdist_wheel` command. The GitHub runner uses normal build isolation with the declared `setuptools` and `wheel` build requirements; its rerun result has not been confirmed here.

The focused VLM loader integration test passes locally. A ward-scoped engine run against the B-supplied Delhi candidate completed locally; the full-city run has not been performed.

## Current repository state

- `main` contains the initial scaffold commit `8565e7a`.
- The pushed branch `a/config-point-loaders` contains the A1/A2 implementation and follow-up fixes, including `e298e3f` (`Fix GeoPandas point construction`), on top of `main`.
- The C4 OpenAPI alignment is prepared separately from the engine PR for review; it documents existing C4@1.0 behavior and does not implement the API runtime.
- The packaging fix is on the feature branch and will reach `main` when the PR is merged. It does not alter the historical check result attached to `8565e7a`.
- A local, untracked `.vscode/` folder was present in the workspace and has been left untouched.

## Plan status and next work

| Plan item | Status | Notes |
|---|---|---|
| A0 / shared scaffold | Starter committed | Contract validation passes; full end-to-end mock demo for each package is not implemented yet. |
| A1 config and point loader | Implemented | Focused VLM CSV test passes; real Delhi VLM Parquet loaded successfully and was bbox-clipped during the pilot. |
| A2 point-to-building assignment | Implemented | Pure assignment tests pass; real Delhi pilot assignments completed. |
| A3 building distortion | Implemented | Code is in `engine/distortion.py`; emits the C1 building-level distortion fields. |
| A4 distortion and regression tests | Implemented | `engine/tests/test_distortion.py` covers examples, public interface, thresholds, edge cases, and invariants; full local suite passed before A6 work. |
| A5 performance, memory, GeoParquet I/O, CLI, logging | Implemented; pilot run completed | `engine/run.py` streams bounded batches, supports ward-scoped runs, combines C1 fragments into one output, and logs progress. Full-city benchmark remains. |
| A6 C1 Parquet export | Implemented; pilot integration completed | Verified through the chunked real-data pilot; emits required C1 metadata and reports VLM coverage. |
| A7 parameter robustness runner | Implemented; pilot integration completed | Ran all nine configured radius/pair-window combinations on a bounded real-data sample; outputs remain local. |
| C4 OpenAPI description | Updated | Response/error schemas, building query parameters, cache headers, and configured-origin CORS are documented; API runtime remains outstanding. |
| H1 real C0 data pack | Local preflight passed | B candidate pack passed manifest, hashes, row counts, CRS, ID, and geometry checks; keep pack private pending ward-source licence resolution. |
| H2 C1 output from real data | Pilot output completed | C1 schema/metadata exported for the ward pilot; full-city output and coverage report remain. |

The supplied plan expects owners to work in parallel against mocks after H0. H0 is only partially satisfied: the shared structure, contracts, fixtures, and validation command exist, but each package still needs a real mock-driven demo before the gate's acceptance criteria are complete.
