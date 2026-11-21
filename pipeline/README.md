# Data pipeline (Person B)

The pipeline builds C0 data packs, validates C0/C5 candidates, and serves local C5 tile previews. Real datasets and generated outputs belong in shared storage or `out/`, not Git. `data/raw/`, `data/pack/`, and `out/` are Git-ignored.

## Delhi candidate status

- The six-file candidate pack is at `data/raw/delhi-pack-preflight/` and passes `pipeline.quality` as C0@1.0.
- The internal assembled pack is at `out/delhi/pack-build-candidate-0.0.1/`.
- The reduced C5 candidate is at `out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2/`. It contains wards and cells only; four sub-1 m² grid slivers are excluded from tile conversion and recorded in its manifest. The C0 grid remains unchanged.
- C1/C2 metrics are not present, so the candidate's metric fields remain null. Point and building layers are omitted from the reduced candidate.
- The project owner confirmed OneDrive cloud-copy verification and ward-source rights clearance on 2026-11-18. C0 manifests record the OpenCity catalog label, the Kaggle mirror listing, the clearance confirmation, the actual local-copy provenance, and source credit.

## Build and review C5 candidates

All generated paths are constrained to the project's `out/` directory. Use a new versioned destination for each rebuild; existing output directories are not overwritten.

Build the reduced wards/cells candidate from a completed C0 pack:

```powershell
python -m pipeline.tiles `
  --pack-dir out/delhi/pack-build-candidate-0.0.1 `
  --pmtiles-output-dir out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.3 `
  --city delhi `
  --version candidate-0.0.3 `
  --skip-points `
  --skip-buildings
```

The same steps are available as `make tiles-candidate`, `make tiles-quality`, and `make serve-tiles`. Override `CITY`, `PACK_DIR`, `TILE_VERSION`, or `TILE_DIR` when needed. Each build requires a new versioned `TILE_DIR`.

When C1/C2 exports are available under `out/`, pass their paths with `--ward-summary`, `--cell-scores`, and `--building-metrics`. The builder verifies the C1/C2 fields and unique join IDs, records input hashes and join coverage, and joins by `ward_id`, `cell_id`, and `bldg_id`. The make target defaults to the reduced wards/cells-only candidate; set `C5_LAYER_ARGS=` to include point/building layers, and set `C5_METRIC_ARGS` to the optional metric arguments.

For example, after C1/C2 exports arrive, build a new candidate with:

```powershell
make tiles-candidate TILE_VERSION=candidate-0.0.4 C5_LAYER_ARGS= C5_METRIC_ARGS="--ward-summary out/delhi/ward_summary.json --cell-scores out/delhi/cell_scores.geojson --building-metrics out/delhi/building_metrics.parquet"
```

Validate a candidate and write the report inside its directory:

```powershell
python -m pipeline.tile_quality `
  out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2 `
  --report tiles_quality.json
```

Serve a candidate for local review only:

```powershell
python -m pipeline.serve_tiles `
  --candidate-dir out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2 `
  --host 127.0.0.1 `
  --port 8765
```

The local preview supports HTTP range requests, `HEAD`, CORS, and the C5 cache header. It is not a public deployment. Public hosting requires a configured host and separate release approval. Building tiles are served only under the `/authority/` route.

The per-ward gzip GeoJSON fallback can be built from a C0 ward layer with `python -m pipeline.tiles --input <wards.geojson> --output-dir out/<city>/tiles-candidate/geojson-v<version> --city <city> --version <version>`.

## Integration gates

- Rebuild metric-bearing ward, cell, point, or building tiles when the corresponding C1/C2 exports and consuming-package feedback are available. Preserve the C0 source pack and build to a new versioned C5 directory.
- Preserve the owner's ward-rights clearance record and the source metadata claims when preparing a versioned release pack.
- Chennai portability is a separate B8 task and needs complete, validated Chennai inputs.
