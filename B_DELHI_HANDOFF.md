# Person B Delhi handoff

**Scope:** Delhi deliverables only. Chennai portability (B8) is a separate second-city task.

## Ready for internal integration

| Interface | Candidate | State |
|---|---|---|
| C0 data pack | `out/delhi/pack-build-candidate-0.0.1/` | Six C0 files and manifest assembled; internal quality report has zero errors/warnings. |
| C5 geometry tiles | `out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2/` | Wards and cells archives reopen; expected C5 fields, zooms, hashes and distinct IDs pass B10. |
| C5 local preview | `pipeline/serve_tiles.py` | Range GET, HEAD, CORS, and cache headers were manually verified. |

The tile candidate is deliberately reduced per the approved pruning direction: points and buildings
are omitted; four sub-1 sqm² cells are excluded from tile conversion and listed in the candidate
manifest. The original C0 grid still contains all 23,051 cells. C1/C2-derived fields remain null.

## Integration rebuild procedure

1. Keep C0/C5 schemas frozen. For any requested field or schema change, update the contract first
   through the repository change process.
2. After C1/C2 exports are supplied, join the contracted ward/cell/building metrics in
   `pipeline/tiles.py`; rebuild into a new versioned output directory rather than overwriting a
   candidate.
3. Run `python -m pipeline.quality <pack-dir> --expected-wards 250 --report <report.json>`.
4. Run `python -m pipeline.tile_quality <tiles-dir> --report <tiles-quality.json>`.
5. Send the pack/tile paths, reports, contract version, and source changes to the consuming
   package for H1/H4 acceptance.

## Release gates still external to local B implementation

- **C0 distribution/H1:** ward-boundary redistribution terms conflict between the local mirror
  and catalog metadata; upstream access request timestamps were not captured. The project owner has authorized internal prototype use only; that authorization does not resolve the licence or permit public redistribution.
- **H4/public B7:** only local preview exists. No approved public host/account or live URL is
  configured, so deployment cannot be completed from this workspace.
- **Full C5 metrics:** C1/C2 exports and integration feedback have not been supplied. The current
  files are a geometry-only fallback, not the final metric-bearing four-layer set.
- **B8:** explicitly outside this Delhi handoff; it requires a validated Chennai source and inputs.
