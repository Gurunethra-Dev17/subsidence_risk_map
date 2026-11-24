# Data lineage and licence notes

**Status:** Virginia Tech v2 Delhi source files, a converted Delhi risk GeoParquet derivative, a normalized Delhi 2022 ward candidate, a 250 m grid, and an Overture building candidate are present locally. The exact Virginia Tech v2 record is listed as CC0 1.0 by the NLM Dataset Catalog. The ward candidate has 250 official IDs and names confirmed against the State Election Commission lists. Four invalid geometries were repaired; overlaps were quantified and retained without changing source boundaries. OpenCity catalog metadata labels the 2022 KML as Other (Public Domain) and names GSDL Delhi as source; the Kaggle mirror copy separately claims ODbL 1.0. The project owner confirmed ward-source rights clearance on 2026-11-18. The local bytes remain the Kaggle mirror copy; the publisher KML was not obtained for byte comparison, so the manifest preserves both metadata claims and the owner clearance confirmation without relabeling the local file as a publisher download. A DataMeet Chennai ward GeoJSON candidate is also present under data/raw/chennai-wards/originals; its source folder states CC BY-SA 2.5 India and credits Transparent Chennai. Its boundary vintage and feature count still need validation; it is not in a pack.

## Rights clearance update (2026-11-18)

The project owner confirms that ward-source rights clearance is complete. Both catalog statements remain in the manifest as provenance: OpenCity lists Other (Public Domain) and the Kaggle mirror listing says ODbL 1.0. The local archive is still the Kaggle-supplied copy; clearance does not change the origin of those bytes. The owner confirmation is recorded in the C0 manifests and this lineage file.


**Prototype scope (2026-11-17):** The project owner authorized use of the existing Delhi ward candidate for internal prototyping. This is retained as the historical scope at that time; the owner later confirmed ward-source rights clearance on 2026-11-18.
**OpenCity source preference (2026-11-17):** The project owner directed that the prototype use the OpenCity original rather than the Kaggle mirror. Re-checks of the resource download and CKAN API on production and staging returned HTTP 403 on 2026-11-17; direct production/staging KML requests returned HTTP 403 again on 2026-11-18. No OpenCity file was acquired and the current Kaggle-derived candidate has not been relabeled or replaced. B5 source switch remains pending until an authorized OpenCity download/copy is available.
**Last reviewed:** 2026-11-18.

## Access-time evidence and limits

The C0 manifest's `accessed_utc` values must mean the time the source was accessed, not the time this repository file was later reviewed. The Overture extraction start/finish times are recorded directly by `pipeline.overture` and verified against the release sidecars. For the Virginia Tech originals and the Kaggle ward archive, repository file `CreationTimeUtc` values record when local copies appeared in this workspace; the original upstream request times were not captured, so these are arrival-time proxies and must not be represented as verified upstream access times in a release manifest. The candidate manifest preserves that distinction in its notes.

| Local source | Observed local arrival time (UTC) | Evidence | Upstream access time |
|---|---|---|---|
| VT v2 `Building_Collapse_Incidents.xlsx` | 2026-11-12 06:55:05Z | Local `CreationTimeUtc` | Not recorded |
| VT v2 `New_Delhi_Buildings_Damage_Risk.zip` | 2026-11-12 06:55:10Z | Local `CreationTimeUtc` | Not recorded |
| VT v2 `New_Delhi_VLM_data.csv` | 2026-11-12 07:29:41Z | Local `CreationTimeUtc` | Not recorded |
| Kaggle ward `archive.zip` | 2026-11-12 10:52:33Z | Local `CreationTimeUtc` | Not recorded |
| Overture Buildings release `2026-10-21.0` | 2026-11-16 12:20:30–12:42:00Z | `EXTRACTION.json` run record | Recorded |
| PopulationIndia ward cross-check CSV | 2026-11-16 19:04:37Z | Local file `CreationTimeUtc`; CSV is not a C0 source | Download captured locally; page gives no licence |
| India GeoData 290-ward alternative | 2026-11-17 06:07:03Z | Local file `CreationTimeUtc`; rejected as wrong ward count/vintage | Download captured locally; not a C0 source |
| DataMeet Chennai ward candidate | 2026-11-16 17:31:24Z | Local file `CreationTimeUtc` | Download captured locally; candidate only |

The VT version-specific licence and Overture theme/source terms are documented below. Ward-source rights clearance was confirmed by the project owner on 2026-11-18. Keep the OpenCity catalog label and Kaggle mirror listing distinct in source records, and preserve the fact that the local file came from the Kaggle mirror rather than a publisher download.

## Planned sources

| Data | Intended source and version | Licence information found so far | Current status and required action |
|---|---|---|---|
| Baseline VLM and published building-risk data | [Virginia Tech Indian Megacities dataset](https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260), project target v2 (2025-04-28) | The exact versioned DOI `10.7294/25856260.v2` is listed as CC0 1.0 in the [NLM Dataset Catalog](https://datasetcatalog.nlm.nih.gov/dataset?q=0002368942), checked 2026-11-18; the listed contributors are Mohammad Khorrami, Leonard Ohenhen, Nitheshnirmal Sadhasivam, Manoochehr Shirzaei, and Susanna Werth. | Delhi VLM CSV, risk ZIP, and incident workbook are present under `data/raw/vt-v2/originals/`. Official v2 and v3 Figshare APIs point to the same incident workbook (file ID `46461859`, MD5 `85b62761ce60aa3d58b8249f1f67094f`): 25 populated rows despite metadata saying 26. Keep 25 source rows; do not fabricate a record. See `data/AUDIT.md`. |
| Building footprints | [Overture Maps Buildings theme](https://docs.overturemaps.org/guides/buildings/), release `2026-10-21.0` (downloaded 2026-11-16) | Overture's [attribution guide](https://docs.overturemaps.org/attribution/) lists the Buildings theme as ODbL and documents compatible source terms: OSM ODbL, Microsoft ODbL, Google Open Buildings CC BY 4.0, and Esri Community Maps CC BY 4.0. In this Delhi release, feature `sources` records show OSM, Microsoft, and Google; no Esri. Google's feature-level `license` value is null, so attribution is based on Overture's official guide. | 16 tiles are present with per-tile rows, hashes, release state, and source counts in `data/raw/overture/delhi-buildings-2026-11-16/EXTRACTION.json`. The normalized C0-shaped candidate is `buildings_delhi_candidate.parquet`; retain Overture's release and source attribution in the manifest. |
| Delhi wards | Local Kaggle mirror copy of [OpenCity Delhi wards dataset](https://data.opencity.in/dataset/delhi-wards-information), resource `21fff296-b1f4-4dbc-bbd1-189cf572717a`, 2022 KML; OpenCity metadata identifies GSDL Delhi as source and credits Vaidyanathan R | OpenCity resource metadata labels it Other (Public Domain); the Kaggle mirror listing says ODbL 1.0. The project owner confirmed ward-source rights clearance on 2026-11-18. Preserve both source claims and the clearance confirmation; do not claim the local bytes were downloaded from OpenCity. | Technical B3 normalization and checks are complete. The publisher direct KML returned HTTP 403 on 2026-11-17, so the local Kaggle copy could not be matched byte-for-byte to the publisher copy. See `data/AUDIT.md`.
| Delhi ward fallback | [DataMeet Municipal Spatial Data — Delhi](https://github.com/datameet/Municipal_Spatial_Data/blob/master/Delhi/Readme.md) | Repository readme states CC BY-SA 2.5 India. | DataMeet and the related India GeoData copy are not suitable: the downloaded India GeoData `Delhi_Wards.geojson` has 290 features and does not match the project's MCD 2022 set of 250. Local audit copy `data/raw/delhi-wards-2022/originals/india_geodata_delhi_wards.geojson`, SHA-256 `f331e967962383127eae891c01ed3f3762f2b029feb892641f2466787b3bed55`; repository README says it was scraped from an ArcGIS Online map and is shared under CC BY-SA 2.5 India. Reject as a geometry replacement. |
| Chennai wards | DataMeet Municipal Spatial Data, `Chennai/Wards.geojson`; readme says data was received from Transparent Chennai | Source folder states CC BY-SA 2.5 India; DataMeet credits Transparent Chennai. | Local file preflight on 2026-11-18 found 201 valid EPSG:4326 polygons with unique `Ward_No` values 0-200. The file includes ID 0 (`Zone_No` = `-`, `Zone_Name` = `St. Thomas Mount`), while the Greater Chennai Corporation reports 200 wards. Source vintage and treatment of ID 0 are unresolved; no C0 ward candidate or grid was generated. See the B8 preflight below.

### B8 Chennai source preflight (2026-11-18)

`data/raw/chennai-wards/originals/Wards.geojson` is 608,157 bytes, SHA-256 `2dff80b6f514e644b9a428696909216e9d22aedd07c8ebab33192ec9e3cb1ab2`; its observed local arrival time is 2026-11-16 17:31:24Z. GeoPandas reads 201 non-empty, valid Polygon features in EPSG:4326 with unique `Ward_No` values from 0 through 200. All 201 geometries intersect the configured Chennai bbox.

The extra ID 0 has `Zone_No` `-` and `Zone_Name` `St. Thomas Mount`. Greater Chennai Corporation materials describe 200 wards, so the source file does not yet align with the configured C0 ward count. The source readme does not identify a boundary year. Do not silently drop or include ID 0, and do not set a `source_year` until the source vintage and intended feature set are confirmed. No Chennai C0 ward output or grid was generated during this preflight.

## Derived C0 files

| C0 file | Derivation and lineage fields to retain |
|---|---|
| `wards.geojson` | Working candidate is derived from the 2022-labelled KML by selecting IDs 1-250, omitting the unnamed ID-0 feature, and writing the C0 properties and EPSG:4326 geometry. All 250 names match the State Election Commission final map lists; the normalized polygons are valid and the small overlaps are documented. Ward-source rights clearance was confirmed by the project owner on 2026-11-18; retain Kaggle-copy provenance and both source metadata claims in the manifest. |
| `buildings.parquet` | Working candidate `data/raw/overture/delhi-buildings-2026-11-16/buildings_delhi_candidate.parquet` is derived from 16 Overture tiles. It carries C0 source categories, stable `bldg_id`, positive `footprint_m2`, projected-centroid `ward_id`/`cell_id` assignments, and EPSG:4326 geometry. 740,639 rows retain null assignments: 740,088 centroids are inside the configured bbox but outside all wards, and 551 fall just outside the bbox while their footprints intersect it. All null centroids were checked against the ward layer with no matches. Raw `sources` provenance counts and version fields are in the extraction record; include the release and source-specific attributions in the manifest. |
| `vlm_points.parquet` | Working Delhi candidate is `data/raw/vt-v2/derived/vlm_points_delhi.parquet`: all 182,817 source rows retained, `vlm_mm_yr = VLM_cm_per_yr * 10`, negative sign preserved, repeated coordinates retained, stable source-row `pt_id`, and `source=vt-in-v2`. |
| `vt_building_risk.parquet` | Working Delhi subset is derived from the Virginia Tech v2 risk shapefile by selecting polygons intersecting the configured bbox, renaming the four risk fields, preserving missing markers as null, and leaving `bldg_id` null because source `index` is non-unique. The exact v2 record is catalogued as CC0 1.0; retain the undocumented star-marker interpretation note in the manifest. |
| `grid_250m.geojson` | Derived from the selected ward boundary geometry using the city's configured UTM CRS and 250 m global-origin grid. Store stable cell IDs and majority-overlap ward IDs. |
| `collapse_incidents.csv` | Working Delhi candidate is `data/raw/vt-v2/derived/collapse_incidents_delhi.csv`, selecting the 8 workbook rows labelled `Delhi`. Dates and available description fields are retained in normalized form; all coordinates remain null because the workbook has no coordinate fields. One source row is Delhi-labelled but has a Ghaziabad address; the note preserves it without inventing coordinates. |

## Manifest and attribution requirements

For each actual C0 pack, `PACK_MANIFEST.json` must contain measured SHA-256 hashes and row counts for every contract file, plus one source entry for every data source with its URL, licence record, and access timestamp. The manifest must also list required attributions and conversion or vintage notes. Use the actual upstream access time when captured; when only local arrival time is available, label it as a proxy in the notes rather than presenting it as a verified upstream timestamp.

For the buildings theme, display or retain the source-specific attributions required by the actual Overture release. The Overture documentation's general example includes `© OpenStreetMap contributors, Overture Maps Foundation`; check the theme's attribution details and source metadata before finalizing the pack attribution. The map UI must also use the separate C5 attribution string exactly as specified by the contract.

## References

- [Virginia Tech dataset](https://doi.org/10.7294/25856260)
- [NLM Dataset Catalog record for Virginia Tech v2, DOI 10.7294/25856260.v2](https://datasetcatalog.nlm.nih.gov/dataset?q=0002368942)
- [Overture Maps attribution and licensing](https://docs.overturemaps.org/attribution/)
- [Overture Buildings theme guide](https://docs.overturemaps.org/guides/buildings/)
- [Overture Maps FAQ](https://overturemaps.org/about/faq/)
- [Delhi State Election Commission](https://sec.delhi.gov.in/sec/about-sec-delhi)
- [DataMeet Delhi readme](https://github.com/datameet/Municipal_Spatial_Data/blob/master/Delhi/Readme.md)
- [DataMeet outdated-boundary notice](https://github.com/datameet/Municipal_Spatial_Data/issues/57)
- [India GeoData Delhi boundary README and CC BY-SA 2.5 India terms](https://github.com/yashveeeeeeer/india-geodata/blob/main/data/urban/municipal-boundaries/delhi/Readme.md)
- [PopulationIndia 2022 ward table](https://www.populationindia.com/wards/delhi-mcd-2022/) (ID/name cross-check only; no geometry or stated reuse licence)
- Contract C0 and C5: `docs/03_CODEBASE_AND_API_CONTRACTS.md`
