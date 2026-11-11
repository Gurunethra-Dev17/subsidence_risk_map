# Engine (Person A)

Implements C1 building metrics from a C0 pack. Public interfaces are described in the contracts document. Start with synthetic fixtures under `contracts/mock/`.

## I/O (A1)

`engine.io.load_config(path)` validates C6 and resolves configured paths from the repository root. `engine.io.load_vlm_points(cfg)` reads `vlm_points.parquet` (or the CSV stand-in in the H0 mock), normalizes known cm/yr source columns to mm/yr, clips to the configured bbox, and returns EPSG:4326 GeoDataFrame points. Negative values are preserved as sinking; there is no automatic sign flip. Read `points.attrs["load_stats"]` for counts, value range, UTM bbox area, and point density.

The point loader requires the optional geospatial dependencies: `pip install -e ".[geo]"`.

## Point assignment (A2)

`engine.assign.assign_points_to_buildings(buildings, points, cfg)` projects both GeoDataFrames into the configured UTM zone, queries radar points within `radius_m` of each building centroid, and returns the C1 assignment columns. Buildings with fewer than `min_points` observations are marked sparse with null estimates. Processing is chunked by 50,000 buildings by default; callers can override `chunk_size` for their memory budget.
