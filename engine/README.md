# Engine (Person A)

Implements C1 building metrics from a C0 pack. Public interfaces are described in the contracts document. Start with synthetic fixtures under `contracts/mock/`.

## I/O (A1)

`engine.io.load_config(path)` validates C6 and resolves configured paths from the repository root. `engine.io.load_vlm_points(cfg)` reads `vlm_points.parquet` (or the CSV stand-in in the H0 mock), normalizes known cm/yr source columns to mm/yr, clips to the configured bbox, and returns EPSG:4326 GeoDataFrame points. Negative values are preserved as sinking; there is no automatic sign flip. Read `points.attrs["load_stats"]` for counts, value range, UTM bbox area, and point density.

The point loader requires the optional geospatial dependencies: `pip install -e ".[geo]"`.

## Point assignment (A2)

`engine.assign.assign_points_to_buildings(buildings, points, cfg)` projects both GeoDataFrames into the configured UTM zone, queries radar points within `radius_m` of each building centroid, and returns the C1 assignment columns. Buildings with fewer than `min_points` observations are marked sparse with null estimates. Processing is chunked by 50,000 buildings by default; callers can override `chunk_size` for their memory budget.

## Building distortion (A3)

`engine.distortion.compute_building_distortion(buildings, points, cfg)` projects building footprints and VLM points into the configured UTM zone. It considers distinct point pairs 10–60 m apart by default when at least one endpoint lies within a building footprint buffered by `footprint_buffer_m`. Pair distortion is `abs(v_i - v_j) * 1e-3 / distance_m` per year. The building rate is the 90th percentile; fewer than three pairs produce null distortion metrics. The rate is multiplied by `horizon_years` as a scenario, formatted as a `1/N` ratio, and classified using `class_edges_ratio`. The returned frame preserves building order and contains the C1 distortion columns.

## C1 export (A6)

`engine.export.export_building_metrics(buildings, assignments, distortions, cfg, output_path, engine_version=...)` joins A2/A3 results to C0 building attributes by `bldg_id` and writes the C1 Parquet contract. It checks ID coverage and uniqueness, writes the contract metadata (`contract`, `horizon_years`, `seed`, `engine_version`, and `params_hash`), and returns the row count and non-null VLM share. The parameter hash is SHA-256 over canonical JSON for the C6 `params` mapping. Output is written to a temporary file and atomically replaced at the destination. Install `.[geo]` to enable Parquet export.
