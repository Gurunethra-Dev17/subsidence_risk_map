# Project progress and work log

**Updated:** 2026-11-11  
**Working branch:** `a/config-point-loaders`

This document records what has been implemented in the repository so far, how it maps to the supplied implementation plan, and what remains open. The planning documents describe intended work; entries below describe repository changes and checks actually performed.

## Summary

The shared H0 repository scaffold was committed to `main`. Person A then added the C6/VLM input loader and the building point-assignment module on a feature branch. A packaging configuration problem found while investigating a failed CI run was fixed on that branch. The feature branch has been pushed to GitHub.

The core geospatial engine is still in progress. The distortion module (A3), engine integration/export work, real data preparation, and package-level mock demos remain outstanding.

## Work completed

### Shared initial setup (H0 starter)

Commit `8565e7a` — `setup: add shared project scaffold and contracts` — added:

- Starter folders and ownership landing pages for Persons A–E.
- C0–C3 and C6 JSON schemas, a C4 OpenAPI outline, C0–C3/C6 fixtures, and C5 GeoJSON layer examples.
- Delhi and Chennai configuration files.
- The contract validator, Makefile commands, Python project metadata, and an initial GitHub Actions workflow.
- Copies of the three supplied planning documents under `docs/`.

The fixtures are deliberately small and synthetic. The mock C0 pack uses JSON and CSV stand-ins instead of the full GeoParquet/Parquet pack described in the contract. The tile fixtures are GeoJSON, not PMTiles.

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

## Checks performed

- The contract validator passed for the six schema-backed fixtures after the initial setup and again during the packaging fix.
- `load_config('configs/delhi.yaml')` returned the expected city, UTM EPSG, bbox, and resolved pack path.
- Python syntax compilation passed for `engine/io.py` and `engine/assign.py`.
- `git diff --check` passed for the A2 change.
- A local editable-install dry run reproduced the initial setuptools flat-layout discovery error. After package discovery was configured, a no-build-isolation dry run reached a separate local limitation: this environment lacks the `bdist_wheel` command. The GitHub runner uses normal build isolation with the declared `setuptools` and `wheel` build requirements; its rerun result has not been confirmed here.

No package unit tests or full engine runs have been performed. In particular, the installed GeoPandas/Pandas stack in this environment fails to import because an Application Control policy blocks a DLL, so the spatial execution path was not exercised here.

## Current repository state

- `main` contains the initial scaffold commit `8565e7a`.
- The pushed branch `a/config-point-loaders` contains, in order, `8a180ab`, `fde74fe`, and `393566c` on top of `main`.
- The packaging fix is on the feature branch and will reach `main` when the PR is merged. It does not alter the historical check result attached to `8565e7a`.
- A local, untracked `.vscode/` folder was present in the workspace and has been left untouched.

## Plan status and next work

| Plan item | Status | Notes |
|---|---|---|
| A0 / shared scaffold | Starter committed | Contract validation passes; full end-to-end mock demo for each package is not implemented yet. |
| A1 config and point loader | Implemented | Config load checked; geospatial point execution awaits a working GeoPandas environment. |
| A2 point-to-building assignment | Implemented | Syntax and whitespace checks passed; spatial runtime and unit tests remain. |
| A3 building distortion | Not started | Next Person A engine task. |
| H1 real C0 data pack | Not started | B owns the dataset audit and real pack preparation. |
| H2 C1 output from real data | Not started | Depends on the real pack and the remaining engine work. |

The supplied plan expects owners to work in parallel against mocks after H0. H0 is only partially satisfied: the shared structure, contracts, fixtures, and validation command exist, but each package still needs a real mock-driven demo before the gate's acceptance criteria are complete.
