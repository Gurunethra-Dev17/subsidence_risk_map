# Data pipeline (Person B)

Builds C0 data packs and C5 tiles. Real and derived datasets belong in shared storage, not Git.

## C0 manifest builder

After the contract-named pack files are present, generate `PACK_MANIFEST.json` with
`python -m pipeline.manifest <pack-dir> --city <city> --version <pack-version>`. Add one
`--source "NAME|URL|LICENCE|ACCESSED_UTC"` per source and repeat `--attribution` and `--note`
as needed. The command hashes each top-level pack file, counts CSV, GeoJSON FeatureCollection,
and Parquet rows, then checks the result against the frozen C0 manifest schema before writing.
It does not invent source metadata or accept unrecognized file formats.

Example (replace the metadata with the values for the actual downloaded data):

```powershell
python -m pipeline.manifest data/pack/delhi-pack-1.0.0 `
  --city delhi --version delhi-pack-1.0.0 `
  --source "Virginia Tech Indian megacities dataset|https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260|CC0-1.0|2026-11-12T00:00:00Z" `
  --attribution "Virginia Tech dataset authors"
```

Parquet row counting needs the optional `geo` dependencies (`pyarrow`). The manifest lists only
top-level files and excludes itself so its own hash is never recursive.

To assemble all six C0 files, write the manifest, and run the quality checker on
the staged result before publishing the pack directory, use
`python -m pipeline.pack <pack-dir>`. Supply one `--file PACK_FILENAME=SOURCE_PATH`
per contract file, plus the same explicit `--source`, `--attribution`, and `--note`
metadata accepted by the manifest builder. The pack command refuses to overwrite an
existing destination and removes its temporary staging directory if manifest or
quality validation fails. It does not infer licences, source dates, or file mappings.

## C0 building footprints

`pipeline/buildings.py` cleans one or more local geospatial building extracts and writes the C0
`buildings.parquet` layer. Input order is the duplicate-resolution priority. Each input needs a
source code from the C0 list and a source ID column; missing source IDs receive a stable ID from
the normalized geometry. The command repairs polygon geometry, keeps footprints intersecting the
configured city bounding box, removes exact-geometry duplicates and footprints under 10 m² by
default, calculates area in the city's configured UTM CRS, and assigns ward and cell IDs from
centroids. Missing spatial matches stay null as required by C0.

Install the optional `geo` dependencies, then run for example:

```powershell
python -m pipeline.buildings --config configs/delhi.yaml `
  --input osm osm_id data/raw/delhi/osm_buildings.parquet `
  --input microsoft building_id data/raw/delhi/microsoft_buildings.parquet `
  --wards data/raw/delhi/wards.geojson `
  --grid data/raw/delhi/grid_250m.geojson
```

This step expects extracted input files; it does not download Overture/OBE data itself. The output
defaults to `buildings.parquet` inside the configured C0 pack directory. Use `--min-area-m2` to
change the sliver threshold and `--output` to select a different destination.

## B2 Overture building download

The project pins Python 3.11 (`pyproject.toml` requires `>=3.11,<3.12`). The current repository
`.venv` is Python 3.11 and has the geospatial dependencies plus Overture client 2.1.1 installed.
The official [Overture Python client](https://docs.overturemaps.org/getting-data/overturemaps-py/)
downloads the requested bbox and defaults to the latest STAC release.

```powershell
.\.venv\Scripts\python.exe -m pipeline.overture --config configs/delhi.yaml `
  --output-dir data/raw/overture/delhi-buildings-YYYY-MM-DD `
  --tile-degrees 0.15
```

The Delhi config requests bbox `[76.84, 28.40, 77.35, 28.89]`. At 0.15 degrees per tile, the
helper requests 16 GeoParquet tiles and records the client version, tile sizes, command logs, and
release labels read from each Overture `.state` sidecar in `EXTRACTION.json`. The 2026-11-16
download is in `data/raw/overture/delhi-buildings-2026-11-16/`, with release `2026-10-21.0`;
see the source-level lineage summary in that file. The source tiles stay under `data/raw/` and are
not committed to Git. The Buildings theme is licensed ODbL-1.0; this extraction's per-feature
lineage contains OpenStreetMap (ODbL), Microsoft (ODbL), and Google Open Buildings (CC BY 4.0)
sources. The official [Overture attribution guide](https://docs.overturemaps.org/attribution/)
confirms those theme and source terms. Retain attribution to Overture Maps Foundation,
OpenStreetMap contributors, Microsoft Global ML Building Footprints, and Google Open Buildings
in the pack metadata. The normalized candidate has 1,883,862 records and preserves null ward/cell
assignments where centroids do not match the available ward/grid geography.

## C0 ward boundaries

`pipeline/wards.py` normalizes an acquired ward polygon layer to the C0 fields `ward_id`,
`ward_name`, `city`, `source`, and `source_year`, stored in EPSG:4326. It requires the source CRS,
repairs invalid geometry, rejects duplicate or missing IDs and non-polygon geometry, filters to
the configured city bounding box, and can enforce an expected ward count.

```powershell
python -m pipeline.wards --config configs/delhi.yaml `
  --input data/raw/delhi/wards_source.geojson `
  --id-column ward_id --name-column ward_name `
  --source "Official Delhi 2022 delimitation" --source-year 2022 `
  --expected-count 250
```

The source and field names vary, so provide the actual columns from the acquired file. The current local candidate is a Kaggle mirror of the [OpenCity source](https://data.opencity.in/dataset/delhi-wards-information), stored under `data/raw/delhi-wards-2022/`. Its KML has 250 named ward IDs (1?250) and one extra unnamed ID-0 polygon. The original KML is preserved; the raw candidate, repaired 250-ward normalization, provisional grid, and overlap review files are under `data/raw/delhi-wards-2022/derived/`. All 250 normalized ward geometries are individually valid. Small overlaps are quantified and preserved in review files; source boundaries were not altered. OpenCity labels its resource Public Domain while the Kaggle mirror claims ODbL 1.0; resolve which terms apply to the local copy before release. See `data/AUDIT.md` for counts and validation details. The [Delhi State Election Commission](https://sec.delhi.gov.in/sec/about-sec-delhi)
reports that the 2022 delimitation set the count at 250 wards; use that expected count only when
the input is confirmed to be that version. DataMeet's [Delhi repository](https://github.com/datameet/Municipal_Spatial_Data/blob/master/Delhi/Readme.md)
documents a CC BY-SA 2.5 India licence, but a [public issue](https://github.com/datameet/Municipal_Spatial_Data/issues/57)
reports that the Delhi ward data was outdated, so it needs a vintage check before use.

## Virginia Tech building-risk polygons

`pipeline/risk.py` converts the selected Virginia Tech risk shapefile to the C0 risk fields,
filters features whose polygon geometry intersects the configured city bbox, and writes nullable
int8 risk categories. Keep the non-unique source `index` out of `bldg_id`; it cannot identify a
building reliably. The current Delhi conversion is a working file under `data/raw/`, not a pack
file. The exact v2 record is listed as CC0 1.0 in the NLM Dataset Catalog; retain the
version-specific citation and licence in the final source metadata.

```powershell
python -m pipeline.risk --config configs/delhi.yaml `
  --input data/raw/vt-v2/extracted/New_Delhi_Buildings_Damage_Risk/Delhi_Buildings_Damage_Risk.shp `
  --output data/raw/vt-v2/derived/vt_building_risk_delhi.parquet
```

The source's `*********` risk markers are read as nulls; preserve their geometries. See
`data/AUDIT.md` for bbox semantics, category counts, and checksums.

## Virginia Tech VLM and incidents

`pipeline/vt.py` prepares the VLM point table and city-filtered incident CSV. It multiplies VLM
cm/year by 10 to produce mm/year, preserves duplicate coordinates and the source sign, and assigns
stable row IDs. Incident coordinates remain null unless source coordinates or a separate,
documented geocoding process supplies them.

```powershell
python -m pipeline.vt --config configs/delhi.yaml `
  --vlm data/raw/vt-v2/originals/New_Delhi_VLM_data.csv `
  --incidents data/raw/vt-v2/originals/Building_Collapse_Incidents.xlsx `
  --output-dir data/raw/vt-v2/derived
```

The current Delhi candidates are `vlm_points_delhi.parquet` and
`collapse_incidents_delhi.csv`; see `data/AUDIT.md` for row counts, conversion notes, and hashes.

## C0 250 m grid

`pipeline/grid.py` creates a square grid using the configured cell size and UTM zone. The grid is
anchored to the UTM coordinate origin, so a cell keeps the same ID when the same city is rebuilt
with the same projection and cell size. Cells are clipped to the union of ward polygons. Each cell
receives the `ward_id` with the largest area overlap; ties use the ward ID in ascending order. The
output is `grid_250m.geojson` in EPSG:4326 with `cell_id` and nullable `ward_id`.

```powershell
python -m pipeline.grid --config configs/delhi.yaml `
  --wards data/pack/delhi-pack-1.0.0/wards.geojson `
  --expected-ward-count 250
```

For another city's boundary vintage, pass that city's confirmed expected ward count or omit the
count check until it is confirmed. The generator repairs invalid grid intersections, keeps polygon
components, and round-trip-validates the exported GeoJSON before reporting success.

## C0 pack quality check

`pipeline/quality.py` checks a completed pack against C0. It verifies required files, manifest
schema, hashes and row counts, required fields, EPSG:4326 for geospatial files, non-empty and
valid geometry, unique IDs, allowed building sources, risk codes, and geographic coordinate
ranges. Provide a confirmed ward count to make the ward-count check mandatory. The command
returns a non-zero exit code when the report has errors and can save the report as JSON.

```powershell
python -m pipeline.quality data/pack/delhi-pack-1.0.0 `
  --expected-wards 250 `
  --report out/delhi/pack_quality.json
```

The check reports measured row counts and detects empty required pack files. It does not decide
whether a building count is plausible for the city; that threshold must come from the selected
source extent and be recorded with the data audit.

## C5 per-ward GeoJSON fallback

`pipeline/tiles.py` writes the C5 fallback path: one gzip-compressed FeatureCollection per ward,
named `<ward_id>.json`. It also writes four versioned PMTiles archives using the GDAL PMTiles
vector driver available through GeoPandas/pyogrio. The static host must return
`Content-Encoding: gzip` for fallback objects. The current internal PMTiles build has the C5
geometry and required property schemas, but ward/cell/building metric fields remain null until
C1/C2 exports are available. Its candidate manifest records hashes, feature counts, zoom ranges,
pending metric fields, and fixed attribution. Keep this geometry-only build internal; it is not an
H4 pass.

```powershell
python -m pipeline.tiles `
  --input data/pack/delhi-pack-1.0.0/wards.geojson `
  --output-dir out/delhi/tiles/geojson `
  --city delhi --version 1.0.0
```

Build all four C5 PMTiles files from a completed C0 pack as a candidate:

```powershell
python -m pipeline.tiles `
  --pack-dir data/pack/delhi-pack-1.0.0 `
  --pmtiles-output-dir out/delhi/tiles/pmtiles `
  --city delhi --version 1.0.0
```

For the implementation-plan fallback when point/building layers are late, add `--skip-points
--skip-buildings`; the candidate manifest lists omitted layers. This yields wards and cells only,
matching the implementation plan's shipping fallback.

The buildings archive is placed under `authority/` per C5. GDAL's PMTiles vector driver requires
GDAL 3.8 or newer; the current environment uses GDAL 3.12.4. Rebuild after C1/C2 metric exports
are available so the null placeholder fields can be populated.

### C5 candidate quality check (B10)

Check the archive hashes, contracted layer fields and zoom ranges, and distinct source IDs:

```powershell
python -m pipeline.tile_quality out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2 `
  --report out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2/tiles_quality.json
```

The report distinguishes tiled feature copies from distinct source features because a source
geometry can be clipped into multiple vector tiles. The Delhi fallback prunes sub-1 sqm² grid
slivers from the tile candidate only and records their IDs in `TILES_CANDIDATE.json`; C0 remains
unchanged.

## Local C5 preview server

For local review of the pruned wards/cells candidate, run:

```powershell
python -m pipeline.serve_tiles `
  --candidate-dir out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2 `
  --host 127.0.0.1 --port 8765
```

Set `TILES_BASE_URL=http://127.0.0.1:8765`; C5 URLs then follow
`<base>/<city>/<file>`. The server supports `GET`, `HEAD`, byte ranges, CORS for `Range`, and
`Cache-Control: public, max-age=86400`. This is a local preview only; it does not create a public
host or clear data redistribution rights.
