# Person B Work Progress

**Target branch:** `main`
**Last updated:** 2026-11-17
**Status:** Delhi internal C0 passes pack quality, and reduced C5 wards/cells PMTiles v0.0.2 passes archive/schema/hash/ID checks. Local preview passed HTTP range/HEAD checks. Unresolved ward redistribution terms prevent H1/public release; no public host is configured, so H4 is not passed. Chennai portability (B8) is outside the current Delhi scope.

## What Person B is responsible for

Person B builds the project data packs and map tiles. The implementation plan assigns work in `pipeline/` and `data/`. The data pack must follow contract C0. The vector tiles and hosting must follow contract C5. Contracts are treated as fixed: code and files should follow them, and any proposed contract change must go through the change process in the implementation plan.

## Current B1-B11 status (contract-aware, 2026-11-17)

| Task | Status | What is done | What remains |
|---|---|---|---|
| **B1 Dataset audit** | Complete | Acquired and audited the three selected Delhi VT v2 originals; recorded source/version/licence evidence, checksums, schemas, counts, CRS, risk codes, missingness, VLM units/sign convention, and conversion caveats. Compared official v2/v3 inventories and confirmed the shared incident workbook has 25 populated rows despite the publisher's 26-incident description. | No remaining B1 deliverable. Keep the 25-row discrepancy and star-to-null interpretation caveats visible in the audit and lineage; do not fabricate data. |
| **B2 Buildings pipeline** | Complete | Downloaded 16 tiles from Overture release 2026-10-21.0; recorded UTC extraction window, per-tile rows/hashes, release sidecars, source record counts/versions/licenses; normalized to a 1,883,862-row GeoParquet C0 candidate with unique stable IDs, positive areas, valid geometries, and C0-compliant null assignments. Official Overture attribution guidance confirms the Buildings theme is ODbL and lists OSM, Microsoft, and Google Open Buildings as compatible source families; Delhi tile provenance has those three. | No remaining B2 pipeline deliverable. Rebuild after source release or boundary changes. Pack release remains subject to B3 ward rights/access metadata and B5 pack handoff. |
| **B3 Ward pipeline** | Complete | Normalizer and 250-ward candidate are complete. All ward IDs are unique; all 250 geometries are valid/non-empty after four repairs; official SEC names and IDs are confirmed. A downloaded PopulationIndia 2022 ward table independently matches all 250 IDs and names. Pairwise overlaps are measured and documented without altering source boundaries. | No remaining B3 pipeline work. Keep the Kaggle/OpenCity rights discrepancy under B9; it remains a separate release-pack gate. |
| **B4 250 m grid** | Complete | Generated and round-trip-validated the 23,051-cell candidate from the normalized ward geometry using the configured EPSG:32643 CRS and 250 m cell size. Cell IDs are unique and stable, all cells have a ward assignment, and all serialized geometries are non-empty, valid Polygon/MultiPolygon features in EPSG:4326. | No remaining B4 pipeline work. Rebuild if the boundary geometry changes. Ward-source redistribution clearance remains a separate B9/release gate. |
| **B5 C0 pack/manifest** | Builder complete; OpenCity-source prototype pending | The internal six-file pack and manifest pass C0 quality with 250 wards. Existing candidate was built from the Kaggle-supplied copy; the user has directed that the prototype use the OpenCity original instead. | Replace the source only after the OpenCity original can be obtained and compared. Production/staging resource and API endpoints returned HTTP 403 on 2026-11-17. Keep any current candidate labelled as Kaggle-derived/internal only. |
| **B6 C5 tiles** | Complete (Delhi reduced-scope fallback) | Added a GDAL-backed PMTiles builder and generated wards (250 source features, z0-12) and cells (23,047 retained source features, z8-14) in v0.0.2. C5 fields and zooms are present. Four sub-1 sqm slivers are listed in the manifest; the full C0 grid is unchanged. | Points/buildings, C1/C2 metric joins, public URLs, and app/H4 acceptance remain follow-up integration work. |
| **B7 Hosting** | Complete locally; public deployment blocked | `pipeline/serve_tiles.py` serves the Delhi candidate locally. Range GET returned 206 with Content-Range; HEAD returned 200; CORS and `Cache-Control: public, max-age=86400` are present. | No public host/account or live URL is configured. H4 needs deployment and app acceptance. |
| **B8 Chennai portability** | Out of scope for Delhi | B8 is the separate second-city portability exercise. | Resume when Chennai is explicitly in scope and current, complete city inputs are available. |
| **B9 Lineage/licences** | Complete (documented) | Completed the source/rights dossier in `data/LINEAGE.md`: exact VT v2 CC0 record, Overture release and compatible source licences/attributions, ward-source conflict, access-time evidence, and rejected alternatives. Correctly distinguishes recorded Overture access times from local file-arrival timestamps for VT and ward files. | The documented ward rights conflict and missing upstream timestamps remain release restrictions, not undocumented B9 work. Do not issue a distributable C0 pack until rights are clarified and actual access times are available or explicitly accepted by the project owner. |
| **B10 Data-quality checks** | Complete for internal Delhi candidates | C0 report checks six files, hashes/counts, schemas, CRS, geometry and IDs. Added `pipeline/tile_quality.py`; v0.0.2 passes PMTiles hashes, CRS, geometry, C5 fields/zooms and distinct source-ID checks; two regression tests pass. Report: `out/delhi/tiles-candidate/pmtiles-wards-cells-v0.0.2/tiles_quality.json`. | Rerun after any rebuild. Internal QA does not grant redistribution rights or H1 approval. |
| **B11 Integration support** | Complete as handoff tooling; acceptance pending | Added `B_DELHI_HANDOFF.md` with candidate paths, repeatable rebuild/QA steps and C1/C2 integration points. | No C1/C2 exports or consuming-package feedback have been supplied; integration acceptance remains pending. |

**Handoff status:** Delhi B1-B7 and B9-B11 local deliverables are complete at the documented internal/reduced scope. B8 is the separate Chennai task. Public release and H1/H4 acceptance remain blocked by documented rights/access metadata and hosting/integration gates. See `B_DELHI_HANDOFF.md`.

## Work completed so far

### 1. Started the published dataset audit (B1)

Created `data/AUDIT.md` with information available from the Virginia Tech dataset page. In simple terms, it records:

- The dataset covers New Delhi, Mumbai, Bengaluru, Chennai, and Kolkata.
- The publisher lists five city VLM CSV files. Each is described as having longitude, latitude, and VLM in centimetres per year, referenced to IGS14. For Delhi, all 182,817 rows parse numerically; there are repeated coordinates, so do not deduplicate them without a documented rule. The study identifies sufficiently negative VLM as subsidence.
- The publisher lists five city building-risk shapefile archives. They are described as multipolygons with four risk fields: `Risk_InSAR`, `Risk_10yrs`, `Risk_30yrs`, and `Risk_50yrs`.
- The publisher describes risk codes 0 through 4, from Very Low through Very High, and missing values where a risk value is unavailable.
- The collapse-incident spreadsheet is described as containing 26 incidents and eight fields: date, address, collapsed structure, city, injuries, deaths, research paper, and cited sources.
- The publisher page displays a CC0 1.0 licence.
- The current publisher page displays version 3, while the project solution document names version 2 dated 2025-04-28. These versions must not be treated as interchangeable without checking what changed.

The audit clearly marks publisher descriptions separately from checks that require the actual files. The three selected Delhi v2 originals are now under `data/raw/vt-v2/originals/` with their original names. The VLM CSV header, row count, missing values, range, and extent have been checked. The collapse workbook headers and populated rows have been checked. The risk ZIP's contents, shapefile type, PRJ, DBF fields, and feature count have been read from the archive without extracting it.

The local workbook has 25 populated incident rows, while the publisher describes 26 incidents. This discrepancy is recorded in `data/AUDIT.md` for follow-up. The risk ZIP is extracted to the expected path with all five companion files. Streaming all DBF rows found 4,936,526 records and risk counts that match the study paper reported Delhi high/very-high totals. Each risk field also contains 86,707 `*********` markers whose meaning must be resolved before conversion. The DBF `index` is not unique. Geometry validity and pack conversion have not been run.

### 2. Started a contract-based C0 manifest builder (B5 groundwork)

Created `pipeline/manifest.py` and documented its use in `pipeline/README.md`. The helper:

- Requires the six data files named in C0: `wards.geojson`, `buildings.parquet`, `vlm_points.parquet`, `vt_building_risk.parquet`, `grid_250m.geojson`, and `collapse_incidents.csv`.
- Requires source information to be supplied, rather than inventing a licence or download date.
- Calculates a SHA-256 hash for each pack file.
- Counts rows in CSV, GeoJSON FeatureCollection, and Parquet files.
- Writes `PACK_MANIFEST.json` only after checking it against the repository's frozen C0 schema.

The helper is groundwork for producing the real data pack. No real pack has been created: required inputs are still missing, and the ward source is not cleared for release.

### 3. Started the building-footprint processing pipeline (B2)

Created `pipeline/buildings.py` and added run instructions to `pipeline/README.md`. This step takes one or more local building extracts plus ward and grid files. It then:

- Checks that the source CRS exists and converts inputs to EPSG:4326 for storage.
- Repairs invalid shapes and keeps polygon footprints that intersect the city's configured bounding box.
- Creates stable building IDs from source IDs, or from the normalized geometry when an input ID is missing.
- Removes duplicate IDs and exact duplicate shapes, keeping the first source in the order supplied.
- Calculates footprint area in the configured city UTM CRS and removes shapes smaller than 10 m² by default; the threshold can be set on the command line.
- Assigns `ward_id` and `cell_id` using each building centroid. Unmatched buildings keep null IDs, as C0 requires.
- Writes `buildings.parquet` into the configured pack directory unless another output path is given.

This is the local-file processing part of B2. It does not fetch Overture or OBE data. The source extracts, ward file, and grid file are not in the repository yet, so no real city pack has been produced.

### 4. Started the ward-boundary processing pipeline (B3)

Created `pipeline/wards.py` and documented it in `pipeline/README.md`. It takes a ward boundary file plus configurable source ID/name columns and writes C0's required `ward_id`, `ward_name`, `city`, `source`, `source_year`, and polygon geometry in EPSG:4326. It requires a known source CRS, repairs invalid shapes, rejects missing or duplicate ward IDs and non-polygon features, filters to the configured city bounding box, and can check an expected ward count.

The local Kaggle KML candidate contains 250 named ward IDs and one extra unnamed ID-0 polygon. All 250 names match the official State Election Commission 2022 map lists. The exact source licence is unresolved and polygon topology has not been checked because no GIS geometry tool is installed. The 250-feature candidate is kept under `data/raw/.../derived/`, outside the C0 pack, until those checks are complete.

### 5. Started the 250 m grid generator (B4)

Created `pipeline/grid.py` and documented it in `pipeline/README.md`. It reads the normalized ward layer, projects it into the city's configured UTM zone, lays down square cells using the configured 250 m size, clips cells to the union of ward polygons, and converts the output back to EPSG:4326. Each cell ID uses its city, cell size, and global UTM grid indices, so rebuilding the same city grid with the same projection and cell size produces the same IDs. Each cell receives the ward it overlaps by the greatest area; ties are resolved by ward ID order. The output fields are the C0 `cell_id` and nullable `ward_id` plus geometry.

The grid generator can check an expected number of wards. The real grid has not been generated because the ward candidate is not yet cleared for the C0 pack and GIS dependencies are unavailable in this environment.

### 6. Started automated pack-quality checks (B10)

Created `pipeline/quality.py` and documented it in `pipeline/README.md`. It checks whether a C0 pack has all six required files, whether the manifest matches the frozen schema and the files' current hashes and row counts, and whether fields and data match the C0 requirements. It checks EPSG:4326, non-empty valid polygon geometry, unique ward/building/cell IDs, the allowed building source names, risk codes 0–4, numeric VLM coordinates and values, and geographic coordinate limits. It can also require an expected ward count and writes a JSON report when requested.

The quality checker cannot confirm that a building total is plausible without the selected source extent and real output counts. That check remains a data-specific audit item. The checker has not yet been run on a real pack because no real pack is available.

### 7. Started the source lineage and licence record (B9)

Created `data/LINEAGE.md` with plain-language notes for the planned Virginia Tech, Overture, and ward-boundary sources. It separates what was verified from what still needs confirmation. For example, the current Virginia Tech page displays CC0 but is now v3 while this project targets v2. Overture's Buildings theme has multiple upstream providers and source-specific terms, so the record says to preserve actual source metadata and verify attribution rather than treating all features as having identical upstream terms. It also records that the DataMeet Delhi fallback may be outdated.

The file does not invent source access timestamps: actual download dates, release IDs, checksums, and licence details must be entered when the data is acquired.

## Important contract rules to keep following

- **C0:** pack filenames, fields, CRS, manifest shape, source/licence records, hashes, and row counts must match `docs/03_CODEBASE_AND_API_CONTRACTS.md`.
- **C5:** tile names, layer names, zoom ranges, attributes, URLs, range requests, CORS, cache behavior, and attribution must match `docs/03_CODEBASE_AND_API_CONTRACTS.md`.
- Keep real and derived datasets out of Git unless the project storage plan changes; the pipeline README says they belong in shared storage.
- Do not put placeholder hashes or row counts into a real pack manifest.
- Do not silently change frozen contracts. Flag any contract mismatch and use the documented change process.

## Work still needed

### B1 - Finish the dataset audit

- Record the confirmed publisher-description mismatch: official v2/v3 APIs point to the same 25-row workbook while the description says 26. Keep the source rows as-is; revisit only if the publisher releases a corrected workbook.
- Keep the undocumented `*********` risk marker mapping to null in the lineage notes; the numeric DBF schema and publisher missing-value description support it, but the literal marker has not been confirmed directly.

### Remaining B work

- **B2 remaining:** include Overture source attributions in the eventual manifest and rebuild after any ward-source or boundary change.
- **B3/B4 remaining:** no pipeline work remains. Resolve ward-source terms under B9 before promoting the validated ward and grid candidates into a C0 pack.
- **B5:** assemble the six contract files and create the manifest with verified source licences, actual access timestamps, hashes, counts, attributions, and notes.
- **B6:** build C5 vector tiles and connect C1/C2 attributes when those outputs are available; use the documented GeoJSON fallback if required.
- **B7:** configure static hosting to meet C5 URL, CORS, HTTP range, and cache requirements.
- **B8:** run the pipeline for Chennai using configuration and record any manual steps.
- **B9 remaining:** resolve ward-source terms and capture actual UTC access timestamps for the sources; release IDs and source lineage are otherwise documented for the current Delhi candidates.
- **B10 remaining:** run the checker on a complete C0 pack and record the report.
- **B11:** rebuild and fix data packs or tiles if integration feedback or contract-approved changes require it.

## Current limitations

- All six Delhi C0-shaped working candidates now exist under `data/raw/`, but they have not been assembled into a pack or passed the pack checker.
- The ward terms conflict across the Kaggle mirror, OpenCity metadata, and a separate MCD map notice; the notice is not confirmed to govern the OpenCity KML. Keep the ward and grid candidates outside a release pack until the source terms are resolved.
- The local incident workbook has 25 populated rows against the publisher's description of 26; only 8 rows are labelled Delhi and coordinates are absent.
- The NLM catalog lists the exact Virginia Tech v2 record as CC0 1.0. Its risk conversion preserves stars as null with the documented caveat; source geometries and resulting GeoParquet have been validated.
- Actual UTC acquisition timestamps still need to be recovered or recorded for manifest sources. No C0 manifest or quality report exists yet.

## Files changed for Person B so far

- `pipeline/overture.py` — tiled Overture bbox-download helper.
- `data/LINEAGE.md` — planned sources, licence notes, derivations, and pending lineage fields.

- `data/AUDIT.md` — initial source metadata audit with pending checks.
- `pipeline/manifest.py` — C0 manifest generation helper.
- `pipeline/buildings.py` — local building-footprint processor for C0.
- `pipeline/wards.py` — local ward-boundary normalizer for C0.
- `pipeline/grid.py` — stable 250 m grid generator for C0.
- `pipeline/quality.py` — automated C0 pack-quality checker.
- `pipeline/README.md` — usage instructions for the manifest builder, building processor, ward normalizer, grid generator, and quality checker.
- `B_PROGRESS.md` — this running progress record.


## New real-data findings (2026-11-12)

I counted all Delhi v2 VLM rows and all DBF attribute rows directly from the downloaded files. The results are in `data/AUDIT.md`. In short: the VLM CSV has 182,817 valid numeric records and repeated coordinates; the risk DBF has 4,936,526 records, its high-risk totals agree with the study, and its `index` field is not unique. All four risk columns have asterisks on exactly the same 86,707 features; their meaning still needs checking before we convert the risk data. The study confirms that negative VLM means subsidence. I could not check polygon shapes because this environment does not have a GIS reader installed.


## Next input needed: 2022 Delhi ward polygons

I checked the B plan and contract. The next data input needed to make the Delhi ward file and 250 m grid is a vector boundary layer for the 2022 Municipal Corporation of Delhi wards. The State Election Commission's official delimitation order confirms 250 MCD wards, but its page offers the order and maps as documents; it does not provide a confirmed GIS vector file. OpenCity is the planned vector source in the project plan, but its dataset page could not be inspected from this environment, so its file format, fields, download link, and licence must be checked when the file is obtained.

**Please download only the boundary layer that contains the 250 post-unification MCD wards from the 2022 delimitation.** Prefer GeoJSON, or a zipped shapefile with all companion files. Do not use the official PDF/map image as the pipeline input. Avoid older 272/273 ward boundaries and data that combines the MCD wards with NDMC/cantonment into a different ward count.

Save the publisher download unchanged under `data/raw/delhi-wards-2022/originals/`. If it is a ZIP, keep the ZIP there and extract a copy under `data/raw/delhi-wards-2022/extracted/`. I created both folders. Do not rename the downloaded files; once they are present, I will inspect the real columns, CRS, feature count, licence/attribution, and boundary extent before running `pipeline/wards.py`. The expected count of 250 is valid only if the file is confirmed to be the 2022 MCD delimitation layer.

**Other real building source:** Delhi VT risk polygons are already downloaded and the C0 contract permits `source: vt` for building footprints, but their geometry has not yet been normalized or quality-checked. B2 also calls for Overture buildings; the tiled download helper is ready, and that source remains outstanding if we follow the plan's Overture path. I will not claim a complete C0 pack until wards, buildings, VLM points, risk layer, grid, incidents, and the C0 manifest are all prepared and checked.


## OpenCity download outage and exact ward resource (2026-11-12)

The user tried the OpenCity dataset page and received `502 Bad Gateway`. This is a server error from the site, not a mistake in the user's steps. I checked the available cached catalogue metadata: the correct resource is **Delhi MCD Wards Map - 2022**, format **KML**, about **6.8 MiB**, source **GSDL Delhi**, credit **Vaidyanathan R**, with the catalogue licence listed as **Public Domain**. The resource ID is `21fff296-b1f4-4dbc-bbd1-189cf572717a`. The dataset page distinguishes this from the **2017 KML**, which has 272 wards, and a separate **2022 zones map**; download the 2022 wards KML only.

The live page and staging page are both returning gateway errors during this check, so I could not fetch or inspect the actual KML. The metadata says the 2022 dataset has 250 unified wards. Once the site works, save that KML unchanged in `data/raw/delhi-wards-2022/originals/`. As it is a single KML file, it does not need ZIP extraction. Then inspect its actual feature count, fields, CRS, spatial extent, and geometry before using it.


## Candidate alternate while OpenCity returns 502

A possible alternative download is Bharatlas's **Delhi Ward Map (290 wards)** GeoJSON: https://bharatlas.com/view/wards_delhi. Its page lists 290 wards across MCD, NDMC, and Delhi Cantonment, says the source is OpenCity, gives a 2026-05-26 source snapshot, and lists CC BY-SA 4.0. It is not ready to feed directly to the Delhi pipeline because it includes 40 boundaries outside the project's 250 MCD wards. If this route is used, preserve the downloaded file, inspect its fields and licence, identify/filter the 250 MCD features only, and check names/boundaries against the official 2022 delimitation order. Record Bharatlas/OpenCity lineage, CC BY-SA attribution, source snapshot, and any filtering in the audit and C0 manifest.

This alternate does **not** require a C0 contract change. C0 still requires the same `wards.geojson` fields, EPSG:4326, unique `ward_id` values, and geometry. Only source/attribution/licence metadata and the documented preparation steps would differ. Do not use the 290 rows as if they were the 250 MCD wards.


## Inspection of uploaded Bharatlas GeoJSON (2026-11-12)

The uploaded `data/raw/delhi-wards-2022/originals/wards_delhi.geojson` is valid JSON and contains 290 non-empty Polygon features in CRS84 (longitude/latitude). Its only properties are `Ward_No` and `Ward_Name`. The ward numbers are 1 through 272, plus 17 `NDMC_` / `CANT_` labels and one feature with no ward number/name. This means the file is not a clean 250-feature 2022 MCD layer.

I compared a ward with the official MCD 2022 list: this GeoJSON says Ward 80 is CHANDNI CHOWK, while the official 2022 MCD order says Ward 80 is RAM NAGAR. So the candidate does not match 2022 numbering. **Do not filter this file by keeping rows 1-250**; that would create a wrong ward layer. Keep the original for audit only and do not use it for the C0 pack. The discrepancy has been recorded here; the source needs a verified 2022 boundary file or the exact OpenCity 2022 KML.

Basic checks completed: the file is 737,950 bytes, has no missing geometries, all 290 geometry types are Polygon, coordinate bounds are 76.838772-77.347470 E and 28.404252-28.883496 N, and polygon rings are closed. Full topology/overlap validation was not run. The GeoJSON declares CRS84. Its SHA-256 is `2b811a4fd6b73e6bc1e5ff64326796a11873be1bb3e38546714d39192c1c1e46`.

This finding **does not change C0**. We still need a 250-feature 2022 MCD ward layer with the same C0 fields and EPSG:4326 output. The downloaded alternate's lineage/licence would need to be recorded if it were ever used, but this candidate is not selected.


## Next-step options after rejecting the 290-ward file (2026-11-12)

I checked current government sources for another machine-readable 2022 ward boundary. The State Election Commission/MCD pages provide the official 2022 ward order, ward list, and map PDFs; the MCD GIS portal is interactive. I did not find a confirmed direct vector download from those government pages during this check. The Green Delhi portal lists the current 250 ward names, which is useful for validating names, but it does not provide a boundary file in the page information checked.

Recommended path: retry/download the exact OpenCity **Delhi MCD Wards Map - 2022 KML** when its 502 error clears. If that remains unavailable and the team needs to proceed, a derived boundary could be digitized from the official 2022 map/order, but that takes extra work and must be clearly documented as digitized/derived and checked against the official ward list. Do not substitute the 290-feature file or the old 272-ward layer.

While the ward source is pending, B can continue source-independent work on the Virginia Tech VLM, risk layer, incident table, and building-footprint preparation. Ward normalization, centroid-to-ward assignments, the clipped grid, and the full C0 pack must wait for the verified boundaries. C0 itself remains unchanged at 250 wards.


## Virginia Tech originals checksummed (2026-11-12)

I calculated SHA-256 hashes for the three downloaded Virginia Tech v2 Delhi source files: the collapse workbook, risk ZIP, and VLM CSV. Their byte sizes and hashes are recorded in `data/AUDIT.md`. These are source-file checksums; the final C0 pack manifest still needs hashes and row counts for its converted output files.


## MCD/GSDL portal check (2026-11-12)

I checked the official MCD information/map pages and indexed details for the MCD web map. They expose a ward lookup / interactive map and names for the current 250 wards, and the government also publishes a 2022 ward map PDF. The pages I could inspect did not provide a confirmed downloadable 2022 KML, GeoJSON, or shapefile. The Green Delhi portal's 250-ward list can help verify ward IDs and names but is not itself a boundary file. The CUA browser host was unavailable, so I could not interact with the live map to inspect its controls or network-backed layers.

Status: no verified replacement vector has been found yet. Keep the 290-feature Bharatlas file out of processing. Preferred path remains the exact OpenCity/GSDL 2022 wards KML, with download currently blocked by the site's 502. The official MCD PDF is a reference; digitizing from it would be a separately documented derived-data fallback and requires geometry validation against the 250 official ward IDs/names. No C0 contract change is needed.


## New ward-boundary candidate found by user (2026-11-12)

The user found a page titled **Open City ? Delhi Wards Shape Dataset (.kml)**, uploaded by Vitrum Analytik. The page description says it contains Delhi ward boundaries and population attributes, including ward number/name, Assembly Constituency, and SC population. This is a promising candidate because it is KML, but the screenshot does not show the vintage, actual feature count, full source chain, or full licence. It is not approved for use yet. If downloaded, keep the KML unchanged in `data/raw/delhi-wards-2022/originals/`; then check all ward IDs/names against the official 2022 list, verify there are exactly 250 MCD ward polygons, inspect CRS/geometry, and record the source attribution and licence from the full page.


## Kaggle KML details supplied by user (2026-11-12)

The user supplied the data card for `delhi_wards.kml` (7.17 MB). It lists fields `FID`, `WNo_SEC`, `AC_No`, `AC_Name`, `Ward_No`, `WardName`, `TotalPop`, `SC_Pop`, and `NW2022`. It claims 272 polygon features and says `NW2022` contains the 2022 naming format. **Do not use these 272 features directly as the C0 wards layer**, because the official 2022 MCD delimitation has 250 wards. The `NW2022` field may or may not provide a reliable mapping for dissolving/recombining old geometries into the 250 current wards; this must be checked against the actual KML and the official 250-ward list before relying on it.

The licence also needs source-level checking: this Kaggle page states ODbL 1.0, while the cached OpenCity metadata for its separately listed 2022 KML says Public Domain. Keep the Kaggle copy's stated ODbL terms and attribution with it unless the actual original source record establishes otherwise. This candidate is potentially inspectable but is not approved yet.

## Uploaded Delhi ward KML inspection (2026-11-12)

I checked the user's downloaded `data/raw/delhi-wards-2022/originals/archive.zip` and the extracted copy at `data/raw/delhi-wards-2022/extracted/archive/delhi_wards.kml`. The ZIP contains only `delhi_wards.kml`, and its bytes exactly match the extracted copy. The extracted KML is 7,173,765 bytes; SHA-256: `528f90b258eb41546e485deee7b5f1371be6ef005128a73e08e395a98b84e08a`.

The actual KML has 251 polygon features, despite the Kaggle data card claiming 272. It has 250 distinct ward IDs from 1 through 250, with no missing or duplicate IDs; those 250 rows also have 250 distinct, nonblank ward names. Ward 80 is `RAM NAGAR` and ward 250 is `SABAPUR`, matching the State Election Commission's 2022 election report. The Commission's official delimitation page says the 2022 boundary set is 250 wards: https://sec.delhi.gov.in/sec/delimitation-order-2022. Its election report is https://sec.delhi.gov.in/sites/default/files/SEC/generic_multiple_files/electionreportvolume1-mcdelections2022.pdf.

There is one additional polygon with `Ward_No=0`, blank ward name and assembly-constituency name, and zero population values. It has real geometry (bbox 77.1314411, 28.5406682 to 77.1676996, 28.5944006), so its identity must be determined before making the 250-feature output. Do not count it as an MCD ward or silently drop it. The other 250 ward geometries span bbox 76.8387761, 28.4042432 to 77.3474764, 28.8835632. The KML has 235 single-polygon features and 16 multi-geometry features; all 272 rings parsed and were closed, with no short/open ring found in this check. KML coordinates are longitude/latitude (WGS 84).

**Status:** Delhi internal C0 passes pack quality, and reduced C5 wards/cells PMTiles v0.0.2 passes archive/schema/hash/ID checks. Local preview passed HTTP range/HEAD checks. Unresolved ward redistribution terms prevent H1/public release; no public host is configured, so H4 is not passed. Chennai portability (B8) is outside the current Delhi scope.


## Delhi ward candidate prepared (2026-11-12)

I read the frozen C0 contract before processing the ward file. C0 still requires `wards.geojson` in EPSG:4326, with `ward_id` as a unique string and the properties `ward_name`, `city`, `source`, and `source_year`. I did not change the contract.

I kept the downloaded ZIP in `data/raw/delhi-wards-2022/originals/` and its extracted KML in `data/raw/delhi-wards-2022/extracted/archive/`. I made a separate working file at `data/raw/delhi-wards-2022/derived/wards_250_candidate.geojson`. It contains 250 features, ward IDs `1` to `250` as strings, 250 distinct ward names, polygon geometry in longitude/latitude, and only the required C0 ward properties. The ID-0 feature stays in the unchanged original KML; it was omitted from the candidate because it has no ward name and is not one of the 250 official ward IDs. The candidate has 268 polygon parts and 271 closed rings. Its bounds are 76.8387761?77.3474764 E and 28.4042432?28.8835632 N. Its SHA-256 is `5ed3e9c3a8ad77465bec6c9213eb77df2ab342eb19f3e909538505cf1be95de1`.

I checked the file structure and required properties after writing it. The current environment has no GeoPandas or Shapely, so polygon self-intersections/topology could not be checked. Ward 80 (`RAM NAGAR`) and ward 250 (`SABAPUR`) match the State Election Commission's 2022 report, but the full 250-name comparison remains to do. The Kaggle card's ODbL claim also conflicts with cached OpenCity Public Domain metadata; confirm the exact source and licence before using this as a released C0 pack file. The candidate is therefore prepared for review, not yet cleared for release. More details are in `data/AUDIT.md` and `data/LINEAGE.md`.


## Official ward-name check completed (2026-11-12)

I compared every ward ID and name in the candidate with the State Election Commission's final map lists. All 250 ward IDs from 1 to 250 are present and all 250 names match. The check covered the official list for wards 1-240 and the separate official list for wards 241-250. In the KML, `WardName` and `NW2022` agree for all numbered wards. Ward 178 is `TUGHLAKABAD`; the official map and delimitation order use that spelling. One earlier PDF text extraction showed a different spelling, so I checked the official map rather than changing the source name.

I also checked the extra feature numbered 0. It has no ward name and zero population fields. Its centroid is outside the 250 numbered ward polygons in a simple point-in-ring check. This supports keeping it out of the 250-ward output; its precise real-world identity is still unknown. The downloaded source remains unchanged.

The next remaining ward-data checks are polygon topology and exact source/licence attribution. Ring closure and coordinate ranges were checked, but there is no GIS geometry library or command-line GIS tool installed here to check for self-intersections and other topology errors. The Kaggle card says ODbL 1.0, while cached OpenCity metadata for a separate 2022 KML says Public Domain. Keep the 250-feature GeoJSON as a working candidate outside `data/pack/` until those items are resolved. The C0 contract remains unchanged. See `data/AUDIT.md` and `data/LINEAGE.md` for source details.

## Removed superseded ward file (2026-11-12)

At the user's request, I removed `data/raw/delhi-wards-2022/originals/wards_delhi.geojson` after confirming it was the earlier rejected 290-feature file. I kept the current 250-ward candidate GeoJSON, the extracted `delhi_wards.kml`, and its original ZIP. The ID-0 feature remains only in the unchanged source KML; it is excluded from the candidate.


## Ward geometry and source metadata follow-up (2026-11-16)

The repository `.venv` has GeoPandas 1.2.0 and Shapely 2.2.0, so I used it to complete the topology checks that were previously blocked. The 250-feature candidate had four invalid polygons (ward IDs 20, 56, 108, 114), all self-intersections. `make_valid` repaired them. Ward 20 became a GeometryCollection with one polygon and one zero-area line artifact; `pipeline/wards.py` now keeps polygonal parts and discards lower-dimensional artifacts during normalization. The normalized output is `data/raw/delhi-wards-2022/derived/wards_250_validated.geojson`: 250 rows, 250 unique IDs, EPSG:4326, no null/empty geometries, and zero individually invalid geometries. Normalization reports four repaired geometries and one discarded line artifact.

A projected pairwise check in EPSG:32643 found 100 ward pairs overlapping by more than 0.01 m². Their combined overlap is about 3,900 m², the largest pair overlap about 1,145 m², against about 1,393 km² total ward area (about 0.00028%). The C0 contract and H1 gate do not require a partition without overlaps, so no authoritative ward geometry was changed. I created `ward_overlap_pairs_candidate.csv` and `ward_overlap_areas_candidate.geojson` to make the affected pairs reviewable. Centroid and grid assignments are deterministic under the current lower-ward-ID tie rule. See `data/AUDIT.md`.

The indexed OpenCity dataset and resource metadata currently list the 2022 ward KML as “Other (Public Domain)” and identify GSDL Delhi as the source. The Kaggle mirror card still lists ODbL 1.0. A separate MCD map PDF says “restricted for departmental use only / not for export” and requires written permission for reproduction; it is not the same KML, so its terms cannot be assumed to govern this dataset. Since the local archive is the Kaggle copy and source statements conflict, the applicable terms remain unresolved. Keep both normalized wards and grid output under `data/raw/.../derived/`; do not put them in a C0 pack yet. References are recorded in `data/AUDIT.md`.

A provisional grid was generated from the repaired ward layer at `data/raw/delhi-wards-2022/derived/grid_250m_candidate.geojson`. It contains 23,051 unique 250 m cells, assigned to all 250 ward IDs, with zero empty or invalid geometries after reloading the serialized GeoJSON; all features are Polygon or MultiPolygon in EPSG:4326. The generator repaired 11 invalid grid intersections and discarded 10 lower-dimensional artifacts. The output stays under `data/raw/.../derived/`; it is not a C0 pack file because the Kaggle/OpenCity source-rights discrepancy remains unresolved.

The grid exporter now writes GeoJSON from the validated feature collection and reopens it to check row count, unique IDs, non-null/non-empty geometry, validity, and polygon-only types. The earlier GDAL/OGR writer serialized three degenerate interior rings that were invalid on reload; the round-trip check caught this, and the validated writer path now produces a clean file.


## B1 risk-marker review (2026-11-12)

I inspected the DBF field descriptors and streamed all records. The four risk fields are numeric (`N`) with width 9 and precision 6. Their valid risk categories are 0?4; `*********` is not a valid number. The same 86,707 features have the marker in all four risk fields, and 10,240 of those are inside the configured Delhi bbox. The publisher describes unavailable risk values as missing. The documented C0 conversion rule is therefore: write these risk values as `null` and retain the polygon row and geometry. The raw DBF remains unchanged. This is a schema-and-description-based interpretation; the publisher has not separately documented the star string itself. See `data/AUDIT.md`.


## B2 Overture setup prepared (2026-11-12)

I checked the official Overture client instructions. It can download only the selected bounding box as GeoParquet and uses the latest STAC release by default. The project helper splits the Delhi C6 bbox `[76.84, 28.40, 77.35, 28.89]` into 16 tiles at 0.15 degrees and records the run in `EXTRACTION.json`.

The workspace has about 286 GiB free. The repository `.venv` now uses Python 3.11.16 and contains GeoPandas, Shapely, PyArrow, and Overture client 2.1.1. The download command is in `pipeline/README.md`. No C0 contract change was made.


## Virginia Tech risk layer converted (2026-11-16)

Added `pipeline/risk.py` and converted the Delhi risk shapefile to `data/raw/vt-v2/derived/vt_building_risk_delhi.parquet`. The configured bbox selects 3,517,198 polygon features (3,517,174 Polygon and 24 MultiPolygon), all individually valid and non-empty. The four risk categories are nullable int8; 10,282 features carry nulls in all four fields. The earlier audit count of 10,240 uses the source point coordinate inside the bbox, while this conversion includes polygon geometries that intersect the bbox, so 42 additional polygons are retained. The source `index` is non-unique (253,179 distinct IDs in this subset), so `bldg_id` stays null.

PyArrow confirmed GeoParquet metadata, row count, risk counts, and null counts after writing; 10,000 sampled serialized geometries reopened valid. The output is 270,689,606 bytes, SHA-256 `8F41D4316A5ED44F1B2E02DC2C7377044D0055301BDBA1CA7BF86D11FE0B828D`. It remains a `data/raw/` derivative until the Virginia Tech v2 redistribution terms and remaining C0 files are ready.


## Overture extraction and building normalization (2026-11-16)

Used the repository Python 3.11 environment and Overture client 2.1.1. The 16 Delhi bbox tiles were downloaded into `data/raw/overture/delhi-buildings-2026-11-16/` from release `2026-10-21.0`; the earlier one-tile partial directory was preserved. `EXTRACTION.json` now records each tile's row count, byte size, SHA-256, release sidecar, and source-lineage summary. Total tile count is 1,887,427 features / 258,384,086 bytes.

The tile source metadata reports Google Open Buildings 1,052,311 records (version 2024-04-16; feature metadata has no `license` value), Microsoft ML Buildings 419,981 records (ODbL-1.0, version 2026-08-11), and OpenStreetMap 415,135 records (ODbL-1.0, September 2026 updates). The Overture attribution guide states that Google Open Buildings is CC BY 4.0 and that the Buildings theme is ODbL; see `data/LINEAGE.md` for the attribution notes.

Normalized all tiles with the C0 building processor to `buildings_delhi_candidate.parquet` (1,883,862 rows; 3,565 removed by area/dedup filters). All IDs are unique, footprint areas are positive, and all serialized geometries passed validity checks. 1,143,223 rows map to a ward and cell; 740,639 have null `ward_id` and `cell_id`. A follow-up assignment review found zero of those null centroids intersect a ward; 740,088 centroids remain inside the configured bbox but outside the MCD ward layer. The other 551 centroids lie just outside the bbox even though their footprints intersect it, so the rows remain in the bbox-intersection crop and retain null assignments. Null rows by source are Google 377,470, Microsoft 183,693, and OSM 179,476. The candidate is 221,228,634 bytes, SHA-256 `3BDBCFF29B8269AF5363573BD99798B278D725E0E43083A85CE35DCEB9242531`. The Overture tile files and candidate remain under `data/raw/`, outside the C0 pack.


## Virginia Tech VLM and incidents prepared (2026-11-16)

Added `pipeline/vt.py`. The VLM candidate `data/raw/vt-v2/derived/vlm_points_delhi.parquet` has all 182,817 rows, converts cm/yr to mm/yr by multiplying by 10, and preserves repeated coordinates and negative sinking values. It has unique stable row IDs and `source=vt-in-v2`; SHA-256 `f9da1c061c69e790e80acde288497ad531318664efe49115ba17a2ce7e84c588`.

The incident candidate `data/raw/vt-v2/derived/collapse_incidents_delhi.csv` contains 8 of the 25 workbook rows labelled Delhi. It retains source details in `note`, normalizes dates, and keeps coordinates null because the workbook has no coordinates. One Delhi-labelled row has an address in Ghaziabad, so it cannot be assigned spatially without geocoding. The CSV's SHA-256 is `c2b31c1e6d3cbd1aebf1aa63b2a494776c4221be9d6f8535e110a7a215effc4f`. The official Figshare v2 and v3 APIs reference the same workbook (file ID `46461859`, MD5 `85b62761ce60aa3d58b8249f1f67094f`), so the 26-versus-25 difference is a publisher-description mismatch, not a missing local download. Retain all 25 rows and do not fabricate a 26th. The NLM Dataset Catalog confirms the exact v2 dataset record (DOI 10.7294/25856260.v2) is CC0 1.0; citations and audit details are recorded in `data/AUDIT.md` and `data/LINEAGE.md`.

## OpenCity publisher download attempt (2026-11-16)

The user shared the OpenCity resource page showing the direct URL for `Delhi MCD Wards Map - 2022`, resource ID `21fff296-b1f4-4dbc-bbd1-189cf572717a`, described as the 250 wards after 2022 unification. Fetch attempts from the environment received HTTP 403 from both `staging.opencity.in` and `data.opencity.in`; the browser-control service was unavailable. No publisher KML was saved, and the existing Kaggle archive/candidates remain unchanged. If the user can download the file through their browser, preserve it separately under `data/raw/delhi-wards-2022/originals/`, then compare its checksum and parsed features before replacing the candidate lineage. `pipeline/pack.py` is ready to assemble and validate the pack after exact source metadata and access timestamps are available.

## Delhi C0 data preflight (2026-11-16)

Ran `pipeline.quality` against hard-linked candidate files in `data/raw/delhi-pack-preflight/`, with `--expected-wards 250`. Counts checked: 250 wards, 1,883,862 buildings, 182,817 VLM points, 3,517,198 VT risk polygons, 23,051 cells, and 8 collapse incidents. The initial run reported only the missing `PACK_MANIFEST.json`; the internal draft manifest was added later and the final candidate check passed. The initial report is `out/delhi/c0_preflight_quality.json`; the manifest-backed report is `out/delhi/c0_internal_candidate_quality.json`. Neither is a release C0/H1 pass.

Computed a manifest-input inventory at `out/delhi/c0_pack_inventory_preview.json` from the six hard-linked preflight files. It contains measured SHA-256 hashes and row counts for each candidate. It is explicitly marked preview-only; source licences, actual UTC access timestamps, and final attributions remain pending, so it is not a C0 manifest.

## Delhi internal candidate manifest (2026-11-16)

Wrote `data/raw/delhi-pack-preflight/PACK_MANIFEST.json` for an internal candidate version `delhi-candidate-0.0.1`. It contains the six measured file hashes/counts, source references, and notes that the ward licence is unresolved and that VT/ward `accessed_utc` values use observed local file creation times rather than separately captured upstream request timestamps. Re-ran `pipeline.quality` with `--expected-wards 250`; the internal candidate passed with 250 wards, 1,883,862 buildings, 182,817 VLM points, 3,517,198 risk polygons, 23,051 cells, 8 incidents, zero errors, and zero warnings. The manifest and report remain under ignored internal paths; this is not a release pack or H1 pass.

## C5 geometry-only fallback started (2026-11-17)

Added `pipeline/tiles.py` to emit the frozen C5 per-ward GeoJSON fallback as deterministic gzip-compressed FeatureCollections with `<ward_id>.json` names. The output manifest records C5 property names, zoom range, fixed attribution, byte sizes, and hashes. Built 250 ward files under `out/delhi/tiles-candidate/geojson/` from the internal preflight candidate. `status`, `score`, and `rank` are null because C1/C2 exports are not available yet. This is only the wards layer: PMTiles, cell/point/building layers, metric joins, hosting, and H4 acceptance remain outstanding. It is an internal candidate and must not be hosted or treated as a release while ward source terms are unresolved.

## B3 ward pipeline completion and source-rights research (2026-11-17)

Completed the technical ward pipeline: the normalized file has 250 unique ward IDs, all 250 names match the official 2022 SEC final lists, all geometries are valid/non-empty after four repairs, and overlaps are measured and documented without altering authoritative boundary shapes. The exact OpenCity resource record identifies a 2022 KML, source GSDL Delhi, credit Vaidyanathan R, and catalog licence “Other (Public Domain)”; the parent dataset describes the 250 unified 2022 wards. The SEC delimitation order independently confirms the vintage. The Kaggle mirror used for the local KML claims ODbL 1.0, and OpenCity's generic Public Domain catalog label is not a separate licence instrument, so release-rights clearance remains tracked under B9. The publisher KML endpoint returned HTTP 403. B3 is complete as a pipeline deliverable; the rights caveat does not leave B3 normalization or validation work outstanding.

The user supplied `the user-supplied local KML` for source comparison. Its 7,173,765 bytes and SHA-256 `528f90b258eb41546e485deee7b5f1371be6ef005128a73e08e395a98b84e08a` match the KML member in the existing Kaggle ZIP exactly. This independently confirms file identity but not publisher origin or reuse rights; no candidate geometry or source licence status changed.

Downloaded the [PopulationIndia 2022 ward table](https://www.populationindia.com/wards/delhi-mcd-2022/) from its “Download all 250 wards” link to `data/raw/delhi-wards-2022/originals/populationindia_delhi_mcd_wards_2022.csv`. It contains 250 unique IDs, boundary date 2022-10-17, population reference year 2011, and ward names matching the normalized candidate 250/250. SHA-256: `ff15fff1104a575774898e858fe1379e670f05435a1994bca60708b2b8642e6c`. The CSV contains attributes only, no geometries, and the page states no licence; it serves as an independent B3 ID/name cross-check, not a replacement boundary layer or licence resolution.

## B4 250 m grid complete (2026-11-17)

The existing candidate at `data/raw/delhi-wards-2022/derived/grid_250m_candidate.geojson` was generated from the validated 250-ward layer with the Delhi config (EPSG:32643, 250 m cells). Prior round-trip validation confirmed 23,051 unique cell IDs, assignment to all 250 ward IDs, no null/empty/invalid geometries, and polygon-only geometry after GeoJSON reload in EPSG:4326. Grid generation also repaired 11 invalid intersections and discarded 10 lower-dimensional artifacts. B4 pipeline work is complete; regenerate after any ward geometry changes. The separate ward-source rights caveat remains under B9 and still blocks the final pack.

## B5 internal C0 pack assembly complete (2026-11-17)

Ran `pipeline.pack` to assemble `out/delhi/pack-build-candidate-0.0.1/`. The pack contains all six C0 files and a generated `PACK_MANIFEST.json` with measured hashes, row counts (250 wards, 1,883,862 buildings, 182,817 VLM points, 3,517,198 risk polygons, 23,051 cells, 8 incidents), three source entries, attributions, and explicit caveats. The pack assembler finalized the candidate directory only after its `pipeline.quality` check returned no errors. The ward licence remains explicitly unresolved and VT/ward access times remain observed local arrival times, so this is an internal candidate, not a distributable release pack. B5 builder work is complete; B9 rights and access metadata remain release blockers.

## B6 geometry-only PMTiles fallback built (2026-11-17)

Extended `pipeline/tiles.py` to use the installed GDAL 3.12.4 PMTiles vector driver. The candidate at `out/delhi/tiles-candidate/pmtiles-wards-cells/` contains `public/delhi-wards-candidate-0.0.1.pmtiles` (250 features; z0–12; 716,548 bytes; SHA-256 `4cf677c608ca07ff311eee0476361b32b5cd1464771643bed8dc04651912d373`) and `public/delhi-cells-candidate-0.0.1.pmtiles` (23,051 features; z8–14; 2,380,182 bytes; SHA-256 `9334b7a12cda6a441de51117ecf1a0dfefc612afbf0aeb3a2030ab096e797125`). GDAL reopened both archives and confirmed layer names and fields: `wards` (`ward_id`, `ward_name`, `status`, `score`, `rank`) and `cells` (`cell_id`, `ward_id`, `suppressed`, `cell_score`, `cell_rank_in_ward`). The tileset manifest records the fixed C5 attribution, zooms, hashes, feature counts, pending metric fields, and omitted layers. By user direction, the slow point and building layers were pruned from this fallback; the full C0 source pack was left unchanged. This geometry-only candidate does not pass H4: point/building tiles, C1/C2 attributes, hosting, and app loading remain outstanding. The initial all-layer attempt showed that the point layer is slow in GDAL and that dense tiles may hit GDAL's 500 KB default tile-size precision reduction; the interrupted attempt was not retained.

## B9 lineage and rights dossier completed (2026-11-17)

Updated `data/LINEAGE.md` with all source terms and attributions, UTC time evidence, and explicit gaps. Overture's run record contains a verified extraction window and 2026-10-21.0 release. VT and the Kaggle ward archive have precise local `CreationTimeUtc` arrival times, but the earlier upstream request times were not captured; these are labeled as arrival-time proxies, not true source-access timestamps. The exact OpenCity resource metadata says “Other (Public Domain)” but the local Kaggle copy claims ODbL 1.0, and no explicit GSDL licence text or direct publisher file was obtained. Researched and downloaded the India GeoData CC BY-SA 2.5 India alternative; it has 290 features, so it is rejected for the 2022 MCD 250-ward layer. PopulationIndia's CSV is documented as a 250-row names/IDs cross-check only, without geometry or stated reuse terms. B9 documentation is complete; the unresolved ward rights and exact upstream timestamp gaps remain explicit release gates, not silently filled values.

## Reduced-scope delivery and B7 local preview (2026-11-17)

Added `B_ALTERNATE_PLAN.md` with a problem/action/result matrix for B1–B11. The reduction is limited to the map delivery candidate: keep the wards/cells PMTiles fallback, omit point/building tile layers until they are needed, and leave the complete C0 source pack untouched. Added `pipeline/serve_tiles.py` for local candidate review with byte-range requests, `HEAD`, CORS, and C5 cache headers. Manual local HTTP verification returned Range `206` with 32 requested bytes and `Content-Range`, and `HEAD` `200` with the archive length; both responses included CORS and `Cache-Control: public, max-age=86400`. Public cloud hosting and redistribution remain separate release gates.
