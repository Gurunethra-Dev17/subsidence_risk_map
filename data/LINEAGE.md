# Data lineage and licence notes

**Status:** Virginia Tech v2 Delhi source files, a converted Delhi risk GeoParquet derivative, a normalized Delhi 2022 ward candidate, a 250 m grid, and an Overture building candidate are present locally. The exact Virginia Tech v2 record is listed as CC0 1.0 by the NLM Dataset Catalog. The ward candidate has 250 official IDs and names confirmed against the State Election Commission lists. Four invalid geometries were repaired; overlaps were quantified and retained without changing source boundaries. Research on the exact OpenCity resource confirms its catalog metadata labels the 2022 KML “Other (Public Domain)” and names GSDL Delhi as source; the Kaggle mirror copy separately claims ODbL 1.0. The publisher KML direct download returned HTTP 403 during the 2026-11-17 check, so byte identity with the Kaggle archive could not be verified. Treat the candidate as technically validated, but keep redistribution clearance unresolved: OpenCity's generic catalog label is not a separately supplied licence instrument, and the Kaggle claim conflicts. A separate MCD map PDF states departmental-use and reproduction restrictions; whether those restrictions apply to this KML is unknown. A DataMeet Chennai ward GeoJSON candidate has now been acquired locally under `data/raw/chennai-wards/originals/`; its specific source folder states CC BY-SA 2.5 India and attributes the data to Transparent Chennai. Its boundary vintage and feature count still need validation; it is not in a pack.

**Prototype scope (2026-11-17):** The project owner authorized use of the existing Delhi ward candidate for internal prototyping despite unresolved reuse terms. This is project-scope authorization only; it does not establish a source licence or permit external/public redistribution of the ward geometry, grid, pack, or tiles.
**OpenCity source preference (2026-11-17):** The project owner directed that the prototype use the OpenCity original rather than the Kaggle mirror. Re-checks of the resource download and CKAN API on production and staging returned HTTP 403. No OpenCity file was acquired and the current Kaggle-derived candidate has not been relabeled or replaced. B5 source switch remains pending until an authorized OpenCity download/copy is available.
**Last reviewed:** 2026-11-17.

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

The VT version-specific licence and Overture theme/source terms are documented below. Delhi ward redistribution remains unresolved: the exact OpenCity resource metadata says “Other (Public Domain),” but the mirror supplying the local archive says ODbL 1.0, and no explicit GSDL licence text or direct publisher KML was obtained. Keep the C0 pack and derivative ward/grid/tile candidates internal until this is resolved.

## Planned sources

| Data | Intended source and version | Licence information found so far | Current status and required action |
|---|---|---|---|
| Baseline VLM and published building-risk data | [Virginia Tech Indian Megacities dataset](https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260), project target v2 (2025-04-28) | The exact versioned DOI `10.7294/25856260.v2` is listed as CC0 1.0 in the [NLM Dataset Catalog](https://datasetcatalog.nlm.nih.gov/dataset?q=0002368942), checked 2026-11-16. | Delhi VLM CSV, risk ZIP, and incident workbook are present under `data/raw/vt-v2/originals/`. Official v2 and v3 Figshare APIs point to the same incident workbook (file ID `46461859`, MD5 `85b62761ce60aa3d58b8249f1f67094f`): 25 populated rows despite metadata saying 26. Keep 25 source rows; do not fabricate a record. See `data/AUDIT.md`. |
| Building footprints | [Overture Maps Buildings theme](https://docs.overturemaps.org/guides/buildings/), release `2026-10-21.0` (downloaded 2026-11-16) | Overture's [attribution guide](https://docs.overturemaps.org/attribution/) lists the Buildings theme as ODbL and documents compatible source terms: OSM ODbL, Microsoft ODbL, Google Open Buildings CC BY 4.0, and Esri Community Maps CC BY 4.0. In this Delhi release, feature `sources` records show OSM, Microsoft, and Google; no Esri. Google's feature-level `license` value is null, so attribution is based on Overture's official guide. | 16 tiles are present with per-tile rows, hashes, release state, and source counts in `data/raw/overture/delhi-buildings-2026-11-16/EXTRACTION.json`. The normalized C0-shaped candidate is `buildings_delhi_candidate.parquet`; retain Overture's release and source attribution in the manifest. |
| Delhi wards | Kaggle mirror of [OpenCity Delhi wards dataset](https://data.opencity.in/dataset/delhi-wards-information), resource `21fff296-b1f4-4dbc-bbd1-189cf572717a`, 2022 KML; OpenCity metadata identifies GSDL Delhi as source | Exact OpenCity resource metadata says “Other (Public Domain)”; Kaggle mirror says ODbL 1.0. These are conflicting catalog claims, not a licence text from GSDL. An MCD PDF restriction was found, but its applicability to this KML is unproven. Redistribution clearance remains unresolved. | Technical B3 normalization and checks are complete. The publisher's direct KML URL returned HTTP 403 on 2026-11-17, so the local Kaggle copy could not be matched byte-for-byte to the publisher copy. Keep the candidate out of a distributable pack pending rights resolution. See `data/AUDIT.md`.
| Delhi ward fallback | [DataMeet Municipal Spatial Data — Delhi](https://github.com/datameet/Municipal_Spatial_Data/blob/master/Delhi/Readme.md) | Repository readme states CC BY-SA 2.5 India. | DataMeet and the related India GeoData copy are not suitable: the downloaded India GeoData `Delhi_Wards.geojson` has 290 features and does not match the project's MCD 2022 set of 250. Local audit copy `data/raw/delhi-wards-2022/originals/india_geodata_delhi_wards.geojson`, SHA-256 `f331e967962383127eae891c01ed3f3762f2b029feb892641f2466787b3bed55`; repository README says it was scraped from an ArcGIS Online map and is shared under CC BY-SA 2.5 India. Reject as a geometry replacement. |
| Chennai wards | [DataMeet Municipal Spatial Data — Chennai](https://github.com/datameet/Municipal_Spatial_Data/tree/master/Chennai), `Wards.geojson`; folder readme says source data was received from Transparent Chennai. | Chennai folder readme states CC BY-SA 2.5 India. | Candidate downloaded to `data/raw/chennai-wards/originals/Wards.geojson` on 2026-11-16. Vintage, feature count, CRS, geometry validity, and agreement with the current 200-ward GCC geography remain to be checked before use. Deferred while Delhi H1 is prioritized. |

## Derived C0 files

| C0 file | Derivation and lineage fields to retain |
|---|---|
| `wards.geojson` | Working candidate is derived from the 2022-labelled KML by selecting IDs 1-250, omitting the unnamed ID-0 feature, and writing the C0 properties and EPSG:4326 geometry. All 250 names match the State Election Commission final map lists; the normalized polygons are valid and the small overlaps are documented. Keep outside the released pack until ward-source terms are resolved. |
| `buildings.parquet` | Working candidate `data/raw/overture/delhi-buildings-2026-11-16/buildings_delhi_candidate.parquet` is derived from 16 Overture tiles. It carries C0 source categories, stable `bldg_id`, positive `footprint_m2`, projected-centroid `ward_id`/`cell_id` assignments, and EPSG:4326 geometry. 740,639 rows retain null assignments: 740,088 centroids are inside the configured bbox but outside all wards, and 551 fall just outside the bbox while their footprints intersect it. All null centroids were checked against the ward layer with no matches. Raw `sources` provenance counts and version fields are in the extraction record; include the release and source-specific attributions in the manifest. |
| `vlm_points.parquet` | Working Delhi candidate is `data/raw/vt-v2/derived/vlm_points_delhi.parquet`: all 182,817 source rows retained, `vlm_mm_yr = VLM_cm_per_yr * 10`, negative sign preserved, repeated coordinates retained, stable source-row `pt_id`, and `source=vt-in-v2`. |
| `vt_building_risk.parquet` | Working Delhi subset is derived from the Virginia Tech v2 risk shapefile by selecting polygons intersecting the configured bbox, renaming the four risk fields, preserving missing markers as null, and leaving `bldg_id` null because source `index` is non-unique. The exact v2 record is catalogued as CC0 1.0; retain the undocumented star-marker interpretation note in the manifest. |
| `grid_250m.geojson` | Derived from the selected ward boundary geometry using the city's configured UTM CRS and 250 m global-origin grid. Store stable cell IDs and majority-overlap ward IDs. |
| `collapse_incidents.csv` | Working Delhi candidate is `data/raw/vt-v2/derived/collapse_incidents_delhi.csv`, selecting the 8 workbook rows labelled `Delhi`. Dates and available description fields are retained in normalized form; all coordinates remain null because the workbook has no coordinate fields. One source row is Delhi-labelled but has a Ghaziabad address; the note preserves it without inventing coordinates. |

## Manifest and attribution requirements

For each actual C0 pack, `PACK_MANIFEST.json` must contain measured SHA-256 hashes and row counts for every contract file, plus one source entry for every data source with its URL, exact licence, and actual access timestamp. The manifest must also list required attributions and any conversion or vintage notes. Do not use placeholder values in a real pack.

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
