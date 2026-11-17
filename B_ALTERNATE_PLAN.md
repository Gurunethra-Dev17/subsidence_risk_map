# Reduced-scope plan for Person B

**Goal:** deliver a small, reviewable Delhi map candidate quickly while preserving the frozen C0/C5 contracts and keeping unresolved source rights visible.

## Pruning rule

Prune only the map-delivery layers. Keep the complete C0 source pack intact so analysis inputs and lineage are not silently changed. The current tile candidate contains wards and cells; it omits VLM points and building footprints and records four sub-1 sqm cell slivers pruned during tile conversion. Its C1/C2 fields remain null until the engine and analytics exports exist.

## Task plan

| Task | Current issue | Reduced-scope action | Result / remaining gate |
|---|---|---|---|
| B1 | None | Keep the version-specific VT audit and the 25-versus-26 incident discrepancy documented. | Complete. |
| B2 | Full building data is large and mixes upstream sources. | Keep the audited Overture C0 layer intact; omit buildings from the public map candidate for now. | Complete as a data pipeline; ODbL attribution stays in the pack lineage. |
| B3 | Ward copy has conflicting licence claims. | Keep the validated 250-ward candidate internal. Do not replace it with a mismatched 290-ward file. | Pipeline complete; redistribution rights still block a public C0 pack. |
| B4 | Grid inherits the ward source. | Keep the 23,051-cell candidate internal and rebuild only if ward geometry changes. | Complete as a grid pipeline; same release-rights gate as B3. |
| B5 | A release pack needs clear source rights and actual access timestamps. | Use the existing six-layer C0 candidate for internal review only. | Builder complete; do not publish until B9 gates clear. |
| B6 | Point/building PMTiles are slow and metrics are unavailable. | Ship the wards/cells fallback, omit points/buildings, preserve C0, and prune only sub-1 m? cells from tile conversion with IDs recorded. | Delhi v0.0.2 passes C5 checks. Add metric joins/layers after C1/C2 exports arrive. |
| B7 | No cloud bucket/account or public tile URL is configured. | Use `pipeline.serve_tiles` for local review with CORS, byte-range, HEAD, and cache headers. | Local preview is implemented and verified. Public deployment/H4 need host/account and app integration. |
| B8 | Second-city Chennai inputs are not validated. | Keep B8 separate from this Delhi delivery. | Outside current Delhi scope. |
| B9 | Ward rights conflict; VT/ward upstream access request times were not logged. | Record the exact claims and local-arrival evidence. Capture upstream access time on future downloads. | Dossier complete. Redistribution and timestamp release gates remain open; no inferred licence or timestamp. |
| B10 | Internal candidate must remain reproducibly checked. | Run C0 pack quality, C5 archive/schema/hash/ID checks, and tile-quality regression tests. | Complete for current internal Delhi candidates; rerun for rebuilt/release candidates. |
| B11 | No integration feedback or C1/C2 exports yet. | Keep C0/C5 frozen; document candidate paths, rebuild commands, QA gates, and C1/C2 integration points in `B_DELHI_HANDOFF.md`. | Handoff procedure is ready; integration acceptance awaits exports/consumer feedback. |

## Current stop conditions

- Do not publish the internal C0 pack or any derivatives containing the disputed ward geometry until its redistribution terms are clarified.
- Do not claim H4. The local preview is not public hosting, and the current PMTiles set contains only wards and cells with metric placeholders.
- Do not reduce, filter, or overwrite the source C0 datasets to make the map build faster. Pruning is confined to the delivery candidate and is recorded in its tile manifest.

## Implemented now

- `pipeline/tiles.py` builds the pruned wards/cells PMTiles candidate and identifies omitted layers in `TILES_CANDIDATE.json`.
- `pipeline/serve_tiles.py` provides a local preview server with HTTP Range/206, `HEAD`, CORS, and the C5 cache header.
- `out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2/` is the current pruned candidate directory.
- `pipeline.tile_quality` and `pipeline/tests/test_tile_quality.py` check the C5 candidate before integration.
