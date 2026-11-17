# Published dataset audit

**Audit status:** Virginia Tech v2 Delhi originals are checksummed and converted candidates are prepared. The exact v2 record is catalogued as CC0 1.0; risk geometry validity and value checks have been performed. The star-to-null mapping follows the numeric DBF schema and publisher missing-value description, but the literal marker has not been separately confirmed by the publisher. The publisher describes 26 incidents, but the authentic workbook in both v2 and v3 contains 25 populated rows; treat this as a publisher-description mismatch and do not invent a 26th record.
**Project's pinned reference:** Virginia Tech dataset v2, dated 2025-04-28, as named in `docs/01_SOLUTION.md`.
**Dataset page currently displayed:** v3, posted 2025-10-29. Do not silently substitute v3 for the project's v2 baseline; compare the versions before building a production pack.

## Source and licence

- **Dataset:** [Data for Vertical Land Motion and Building Damage Risk for the Indian Megacities](https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260), Virginia Tech University Libraries, DOI [10.7294/25856260](https://doi.org/10.7294/25856260).
- **Publisher page status checked:** 2026-11-12; it displays v3 and lists the version history (v2 dated 2025-04-28 and v1 dated 2024-05-21).
- **Licence:** The exact versioned record for v2 (DOI `10.7294/25856260.v2`) lists Creative Commons Zero v1.0 Universal (CC0 1.0) in the [NLM Dataset Catalog](https://datasetcatalog.nlm.nih.gov/dataset?q=0002368942), checked 2026-11-16. The publisher's current landing page displays v3; the v2 catalog result is version-specific.
- **Publisher description:** InSAR-derived vertical land motion and building damage-risk data for New Delhi, Mumbai, Bengaluru, Chennai, and Kolkata.
- **Download size shown on publisher page:** 1.06 GB for the current record. The selected v2 Delhi files are now present locally; other city files and non-VT source data have not been acquired.

## Local Virginia Tech v2 Delhi files inspected

The following originals are in `data/raw/vt-v2/originals/` and keep their publisher filenames:

| File | Observed details | Status |
|---|---|---|
| `New_Delhi_VLM_data.csv` | 9,667,953 bytes; header is `Longitude`, `Latitude`, `VLM_cm_per_yr`; 182,817 data rows; no blank VLM values; observed VLM range −5.104460 to 1.519197 cm/yr; longitude/latitude extent 76.819343–77.574282 E, 28.287008–28.888355 N. | CSV header and values inspected. The project conversion to mm/yr is ×10; verify the published sign convention before interpreting the values. |
| `New_Delhi_Buildings_Damage_Risk.zip` | 414,767,914 bytes compressed, 1,068,999,036 bytes uncompressed. Contains `.shp`, `.shx`, `.dbf`, `.prj`, and `.cpg` components named `Delhi_Buildings_Damage_Risk.*`. Shapefile header reports ESRI Polygon (shape type 5), 4,936,526 records. The PRJ describes WGS 84 geographic coordinates. DBF fields are `index`, `latitude`, `longitude`, `Risk_Insar`, `Risk_10yrs`, `Risk_30yrs`, and `Risk_50 yr`. | ZIP central directory and header metadata inspected; components are extracted to `data/raw/vt-v2/extracted/New_Delhi_Buildings_Damage_Risk/`. The DBF has 4,936,526 rows, no deleted records, and 253,192 distinct `index` values (so `index` is not a unique building key). Risk values were counted directly from DBF text. Each of the four numeric fields has 86,707 `*********` markers on exactly the same features. The DBF declares each risk field as numeric width 9, precision 6; the stars cannot be parsed as risk categories 0?4. The publisher description allows missing risk values where unavailable. Record this as the source missing-value marker and convert it to C0 `null`, while retaining the feature and geometry. A stream check found 10,240 such features inside the configured Delhi bbox, so they must not be dropped. This mapping is based on the field schema and publisher missing-value description; the publisher has not separately confirmed the literal star encoding. Category counts (0, 1, 2, 3, 4) are: `Risk_Insar` 1,123,325 / 1,624,642 / 2,099,588 / 2,264 / 0; `Risk_10yrs` 1,123,211 / 1,624,377 / 2,099,062 / 3,169 / 0; `Risk_30yrs` 1,118,985 / 1,615,115 / 2,087,968 / 24,582 / 3,169; `Risk_50 yr` 1,114,671 / 1,604,849 / 2,080,414 / 38,428 / 11,457. The high/very-high counts match the study paper reported Delhi totals. A local geometry library is not installed, so geometry validity and archive CRC verification remain pending. Preserve original field names in the audit; normalize them only during conversion. |
| `Building_Collapse_Incidents.xlsx` | One sheet, `Building Collapse Incidents`; columns are `Date (YYYYMMMDD)`, `Address`, `Structure that collapsed`, `City`, `Injury`, `Death`, `Research paper`, `Cited sources`. The workbook contains 25 non-empty incident rows plus the header. MD5: `85b62761ce60aa3d58b8249f1f67094f`. | The official Figshare v2 and v3 version APIs both identify file ID `46461859`, size 15,132 bytes, with this same MD5. The workbook is the publisher's file; its 25 rows conflict with the metadata description of 26. Record the mismatch, retain 25 source rows, and do not fabricate a missing incident. No coordinate columns are present in the header. |

The expected extraction folder contains all five shapefile companions. The latest check found the three originals (CSV, ZIP, and workbook) under `originals/`, and no duplicate shapefile files under that folder. Use the copy under `extracted/New_Delhi_Buildings_Damage_Risk/` for inspection and keep the ZIP under `originals/`.

## Publisher-described file inventory

The dataset page describes 11 files:

| Files | Publisher-described contents | Audit status |
|---|---|---|
| `New_Delhi_VLM_data.csv`, `Mumbai_VLM_data.csv`, `Bengaluru_VLM_data.csv`, `Chennai_VLM_data.csv`, `Kolkata_VLM_data.csv` | Three columns: longitude (degrees), latitude (degrees), and `vlm` (cm/yr); VLM is described as IGS14. | Names, fields, units, and reference frame are from publisher metadata; row counts, nulls, coordinate ranges, sign, and version-specific differences remain unchecked. |
| `New_Delhi_Buildings_Damage_Risk.zip`, `Mumbai_Buildings_Damage_Risk.zip`, `Bengaluru_Buildings_Damage_Risk.zip`, `Chennai_Buildings_Damage_Risk.zip`, `Kolkata_Buildings_Damage_Risk.zip` | Each contains a multi-polygon building shapefile with `Risk_InSAR`, `Risk_10yrs`, `Risk_30yrs`, and `Risk_50yrs`. Values are 0 Very Low, 1 Low, 2 Medium, 3 High, 4 Very High, or NaN where unavailable. | Geometry family and risk coding are publisher-described. Actual shapefile component names, CRS, column storage types, feature counts, validity, IDs, and missingness remain unchecked. |
| `Building_Collapse_Incidents.xlsx` | 26 incidents; eight columns: Date, Address, Structure that collapsed, City, Injury, Death, Research paper, Cited sources. | Publisher-described fields contain no coordinates column. Whether locations can be geocoded from address, and date/city completeness, remain unchecked. |

The publisher metadata does not state a CRS for the building shapefiles, give the full risk-field schema beyond the four named fields, or document the VLM sign convention. Record these from the acquired v2 files and their accompanying metadata before conversion. The project config and C0 pack require storage in EPSG:4326; source CRS must be inspected and transformed explicitly rather than assumed.

## Conversion and C0 notes

- The project plan describes VLM conversion from cm/yr to mm/yr. Apply `vlm_mm_yr = vlm_cm_yr * 10` only after checking source units and the sign convention against the selected raw files and the study documentation.
- Preserve published risk categories as integer values 0–4, with missing values as null; do not infer a category for NaN.
- The published risk polygons may serve as source building geometry, subject to validation. Keep their original identifiers if present; otherwise any generated IDs must be stable and documented.
- The incident workbook contract output is `collapse_incidents.csv` with `incident_id`, `lon`, `lat` (nullable), `city`, `date` (nullable), and `note`. The source page describes addresses rather than coordinates, so `lon`/`lat` may need to remain null unless a reproducible geocoding source and permission are established.
- C0 v1.0 manifest requires the source name, URL, licence, access timestamp, per-file SHA-256 and row counts, attribution, and notes. Hashes and counts must be calculated from the actual packed files; do not copy fixture placeholders.

## Outstanding checks before B1 is complete

1. The incident-count discrepancy is confirmed as a publisher-description mismatch: the official v2 and v3 APIs point to the identical 25-row workbook (file ID `46461859`, MD5 `85b62761ce60aa3d58b8249f1f67094f`), while metadata says 26. Preserve all 25 rows; do not invent a record. Recheck only if the publisher supplies a corrected workbook.
2. The literal `*********` DBF marker has not been explicitly documented by the publisher. The conversion to null is supported by the numeric field schema and the publisher's description of unavailable risk values; retain that caveat in lineage.
3. Other-city files need inspection only if required for portability; the current B1 conversion scope is Delhi.

## References

- Virginia Tech dataset landing page and file descriptions: https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260
- Official Figshare v2 file inventory: https://api.figshare.com/v2/articles/25856260/versions/2
- Official Figshare v3 file inventory: https://api.figshare.com/v2/articles/25856260/versions/3
- Dataset DOI: https://doi.org/10.7294/25856260
- NLM catalog record for the exact v2 version and rights metadata: https://datasetcatalog.nlm.nih.gov/dataset?q=0002368942
- NLM catalog record for v3: https://datasetcatalog.nlm.nih.gov/dataset?q=0002382601
- Project dataset description and audit requirements: `docs/01_SOLUTION.md`, section 6.
- Frozen C0 manifest and pack requirements: `docs/03_CODEBASE_AND_API_CONTRACTS.md`, section 4.2.


## Follow-up inspection completed on 2026-11-12

- Counted all 182,817 rows of the New Delhi VLM CSV. All longitude, latitude, and VLM values parsed as numbers. Repeated coordinates occur in 22,238 coordinate groups (50,096 rows total), so a future pipeline must not silently drop them.
- Streamed all 4,936,526 DBF records without loading the shapefile geometry. There are zero deleted records. The `index` column repeats and is not a unique feature identifier.
- The four risk columns contain the category frequencies listed above and 86,707 `*********` values on exactly the same features. The DBF field descriptors show numeric type N, width 9, precision 6, while valid category values are 0?4. Because the source description allows missing risk values where unavailable, convert the literal marker to C0 null and preserve the record/geometry; 10,240 marker records lie inside the configured Delhi bbox. This is a documented interpretation of the source marker, not a publisher-confirmed encoding specification.
- The Delhi high-risk counts (2,264; 3,169; 24,582; 38,428) and very-high counts (0; 0; 3,169; 11,457) agree with the Nature study paper reported totals. This is a strong count-level consistency check, not a geometry check.
- The study says pixels with VLM more negative than the uncertainty threshold are subsiding. Use negative values for downward motion and preserve the sign during unit conversion. [Nature study](https://www.nature.com/articles/s41893-025-01663-0).
- No GDAL/OGR, PyShp, Shapely, or GeoPandas library is available in the current Python environment. Thus this pass did not validate polygon geometries or test DBF marker interpretation through a GIS reader.


## Checksums of the downloaded Virginia Tech v2 Delhi originals

SHA-256 hashes calculated from the local original files on 2026-11-12. These identify the source downloads; the C0 manifest must separately hash the final packed files.

| Original file | Bytes | SHA-256 |
|---|---:|---|
| `Building_Collapse_Incidents.xlsx` | 15,132 | `b176a20f8a9ce0525e5f8d76be27f8a2a91ae2ee85547d0dac78bcc6de64ec1c` |
| `New_Delhi_Buildings_Damage_Risk.zip` | 414,767,914 | `3935ba8fcb53371d318de9f0d2c926abf0006532af7a1c6d318c11a55e7b1da4` |
| `New_Delhi_VLM_data.csv` | 9,667,953 | `cdff571f6fdbefb9aea11709826a3d0446c3d759dc7c514c718e5e1ff37f7ce0` |


## Delhi 2022 ward-boundary candidate inspection (2026-11-12)

The user's Kaggle download is stored unchanged as `data/raw/delhi-wards-2022/originals/archive.zip`; its single KML member is extracted to `data/raw/delhi-wards-2022/extracted/archive/delhi_wards.kml`. The archive member and extracted KML are byte-for-byte identical. The KML is 7,173,765 bytes with SHA-256 `528f90b258eb41546e485deee7b5f1371be6ef005128a73e08e395a98b84e08a`.

The actual KML contains 251 polygon features (the Kaggle card says 272). It has one feature for each ward ID 1 through 250, with 250 unique nonblank ward names and no missing or repeated IDs. Spot checks: ward 80 is RAM NAGAR and ward 250 is SABAPUR, matching the official State Election Commission 2022 election report. The official delimitation page says the final 2022 set has 250 wards. The ward names have since been compared against the State Election Commission final map lists: all 250 names match. The population and Assembly Constituency attributes have not been independently compared.

The extra feature has `Ward_No=0`, a blank `WardName` and `AC_Name`, and zero population fields. It has polygon geometry, so it was excluded from the candidate only because it is not a named 2022 ward; its geographic identity remains unconfirmed. Do not modify the source file or treat this extra polygon as a ward. KML parsing found all rings closed with at least four coordinates and coordinates within WGS 84 ranges. A topology-validity check was not possible because GIS geometry libraries are unavailable in the current Python environment.

A separate C0-shaped working candidate was generated at `data/raw/delhi-wards-2022/derived/wards_250_candidate.geojson`. It contains the 250 numbered features, geometry, and exactly the required C0 properties (`ward_id`, `ward_name`, `city`, `source`, `source_year`). The one `Ward_No=0` feature was left in the raw KML and omitted from this derived candidate. The candidate is 7,648,887 bytes, SHA-256 `5ed3e9c3a8ad77465bec6c9213eb77df2ab342eb19f3e909538505cf1be95de1`.

This remains a candidate, not a released C0 pack file. The State Election Commission final map lists cover wards 1?240 and 241?250; all 250 KML names match after normalizing filename separators. Ward 178 is TUGHLAKABAD in the official individual ward map and delimitation order, matching the KML; an earlier text extraction from a report table had an OCR spelling variant. The KML `WardName` and `NW2022` names are identical for all 250 numbered features. The Kaggle card claims ODbL 1.0 and attributes the file to OpenCity; cached OpenCity metadata for its separate 2022 KML lists Public Domain. The exact original source record and licence still need confirmation, and polygon topology has not been checked. A pure-Python point-in-ring check found the ID-0 polygon centroid (77.1462785, 28.5677677) outside every numbered ward polygon. It remains an unassigned source feature and is omitted from the C0 candidate. No C0 contract change has been made.


### Official ward-name and ID-0 follow-up

- Compared all 250 candidate ward names with the State Election Commission's [final individual ward map list (1-240)](https://sec.delhi.gov.in/sec/final-individual-maps-newly-delimited-wards) and [final individual map list (241-250)](https://sec.delhi.gov.in/sec/final-individual-maps-newly-delimited-wards-241-250-maps). Result: 250 of 250 names match, with no missing IDs or name mismatches. The 241-250 names were checked against the official map list: Karawal Nagar-East, Dayalpur, Mustafabad, Nehru Vihar, Brij Puri, Sri Ram Colony, Sadatpur, Karawal Nagar-West, Sonia Vihar, Sabapur.
- The official map and delimitation order spell ward 178 `TUGHLAKABAD`, matching the KML. A text extraction from one report table had an OCR spelling variant; do not change the KML name based on that variant.
- The KML's `WardName` and `NW2022` name values agree for every ward ID 1-250.
- The extra ID-0 feature is unnamed and has zero population fields. A simple point-in-ring check placed its centroid outside the 250 numbered ward geometries. It is therefore not assigned to an official MCD ward in the C0 candidate. Its exact real-world identity is not established.
- The initial environment lacked GIS packages, but the repository `.venv` has GeoPandas 1.2.0 and Shapely 2.2.0. A current local geometry check found four invalid ward polygons: IDs 20, 56, 108, and 114 (self-intersections). `make_valid` repairs them; ID 20 becomes a GeometryCollection containing one polygon and one zero-area line artifact. The normalization helper now preserves the polygonal part and discards that line artifact.
- The repaired normalized output has 250 features, all valid and non-empty in EPSG:4326. It is stored as `data/raw/delhi-wards-2022/derived/wards_250_validated.geojson`, with the original candidate preserved. A projected pairwise check (EPSG:32643) found 100 intersecting ward pairs with overlap greater than 0.01 m²; combined overlap area is about 3,900 m² (0.00028% of the 1,393 km² total ward area), and the largest is about 1,145 m². These appear small in aggregate, but they remain a boundary-quality issue to review before C0 release; individual validity does not guarantee a non-overlapping partition.
- The OpenCity dataset and resource metadata pages list the 2022 MCD ward KML as “Other (Public Domain)” and identify GSDL Delhi as the source. The Kaggle mirror card still claims ODbL 1.0. Since the local bytes came from the Kaggle archive and the mirror's terms conflict with OpenCity's source record, retain both statements and do not mark redistribution rights as fully resolved without confirming which terms govern this copy.
- MCD's [2023 ward-and-zone map PDF](https://mcdonline.nic.in/portal/downloadFile/mcd_map_full_zone_image_cd_23030712390030_230322122342342.pdf) carries a “restricted for departmental use only / not for export” notice and says reproduction requires written permission from GSDL. That PDF is not the OpenCity KML, so it does not establish the KML's terms; it is an additional source-level conflict to resolve with GSDL/OpenCity before redistribution.
- A provisional grid was generated from the repaired layer at `data/raw/delhi-wards-2022/derived/grid_250m_candidate.geojson`, outside the C0 pack. It has 23,051 unique 250 m cells, all 250 ward IDs assigned, no empty or invalid geometries after GeoJSON round-trip validation, and EPSG:4326 coordinates. The generator repaired 11 invalid intersection cells and discarded 10 lower-dimensional artifacts. This remains a candidate, not a release artifact; the overlap is documented and retained, while the source-rights discrepancy is still unresolved.

The overlap review generated `ward_overlap_pairs_candidate.csv` and `ward_overlap_areas_candidate.geojson` beside the normalized wards. The 100 overlap pairs affect 103 wards; the largest pair is wards 20/54 at about 1,145 m². No source boundary was altered to remove these overlaps: the C0 schema and H1 acceptance gate require polygon geometries and valid unique ward IDs but do not require a non-overlapping partition. Downstream centroid attribution sorts ward IDs, and grid attribution chooses largest overlap then ascending ward ID, so ambiguous assignments are deterministic. Retain the overlap note and review layer with the candidate data.

Derived-file checksums (2026-11-16; working files, not C0 manifest hashes): `wards_250_validated.geojson` — 8,945,926 bytes, SHA-256 `6B79BE09875861F312D878283BFDEA5D7AB5B1F7BAC8B9C91963F90B9F871851`; `grid_250m_candidate.geojson` — 8,735,100 bytes, SHA-256 `A2021BBA939A3E18ECBB3E27FF188D0F69A22EC41133C0A2A78413568FBCAA15`.

Metadata research updated 2026-11-17: the exact [OpenCity 2022 ward resource record](https://staging.opencity.in/dataset/delhi-wards-information/resource/21fff296-b1f4-4dbc-bbd1-189cf572717a) identifies the Government of Delhi dataset, format KML, resource ID `21fff296-b1f4-4dbc-bbd1-189cf572717a`, source GSDL Delhi, credit Vaidyanathan R, and catalog licence “Other (Public Domain).” The parent [OpenCity dataset record](https://staging.opencity.in/dataset/delhi-wards-information) also labels the dataset Public Domain and describes the 2022 resource as the 250 unified wards. The [SEC's official 2022 delimitation order](https://sec.delhi.gov.in/sec/delimitation-order-2022) independently confirms the 250-ward vintage and provides final ward maps/lists. However, the Kaggle mirror that supplied the local archive claims ODbL 1.0. OpenCity's generic catalog value is not a separate licence text from GSDL, and an attempted retrieval of the publisher KML URL returned HTTP 403, preventing a byte-for-byte match with the Kaggle copy. Therefore the candidate is technically validated, but redistribution rights remain unresolved; the local archive is unchanged and is not cleared for a release pack.

User supplied `the user-supplied local KML` for follow-up. It is 7,173,765 bytes with SHA-256 `528f90b258eb41546e485deee7b5f1371be6ef005128a73e08e395a98b84e08a`, exactly matching the `delhi_wards.kml` member inside `data/raw/delhi-wards-2022/originals/archive.zip` byte-for-byte. It is therefore the same content as the existing Kaggle-mirror copy, not independent publisher provenance; it does not resolve the licence conflict.

Downloaded the “Download all 250 wards” CSV from the [PopulationIndia 2022 ward page](https://www.populationindia.com/wards/delhi-mcd-2022/) to `data/raw/delhi-wards-2022/originals/populationindia_delhi_mcd_wards_2022.csv` (14,877 bytes; SHA-256 `ff15fff1104a575774898e858fe1379e670f05435a1994bca60708b2b8642e6c`). It has 250 unique ward IDs, boundary date `2022-10-17`, population reference year 2011, and names matching the normalized ward candidate 250/250. The download is tabular and contains no geometry; no reuse licence is stated on the page. Use as an independent ID/name cross-check only, not as the boundary source or evidence of geometry redistribution rights.

The OpenCity resource page exposed the direct file URL `https://staging.opencity.in/dataset/4a4ef191-e7c1-4c99-9dee-7aed54699d35/resource/21fff296-b1f4-4dbc-bbd1-189cf572717a/download/5e24cd4e-8ef0-4e59-9446-e74af981d370.kml`. Fetch attempts from this environment received HTTP 403 from both the staging and production OpenCity hosts. No publisher copy was saved locally, and the existing Kaggle archive and derived candidates were left unchanged. If a copy is downloaded through a browser session, preserve it as a separate original and compare its SHA-256 and parsed KML features with the existing archive before changing lineage or building the pack.


### Overture building candidate assignment review (2026-11-16)

The 1,883,862-row Overture candidate has 1,143,223 buildings assigned to a ward and grid cell and 740,639 with null `ward_id`/`cell_id`. A projected-centroid spatial join found zero of the null centroids intersect any of the 250 ward polygons. Of the null group, 740,088 centroids are inside the configured bbox but outside the MCD wards; 551 centroids are just outside the bbox while their footprints intersect the bbox, so they remain in the intersection-based crop. The null rows by source are Google 377,470, Microsoft 183,693, and OSM 179,476. These null assignments follow C0 for buildings without a ward/cell match; no buildings were removed in response to this review. The exact release and source-feature metadata are recorded in `data/raw/overture/delhi-buildings-2026-11-16/EXTRACTION.json` and `data/LINEAGE.md`.

### VLM and incident table preparation (2026-11-16)

Added `pipeline/vt.py` and wrote `data/raw/vt-v2/derived/vlm_points_delhi.parquet` from all 182,817 rows in the New Delhi v2 CSV. The converter multiplies `VLM_cm_per_yr` by 10 to produce `vlm_mm_yr`, preserves the negative sign convention, retains repeated coordinates, and adds unique source-row IDs plus `source=vt-in-v2`. No rows were dropped; the output has no null values. Its `vlm_mm_yr` range is -51.044600 to 15.191975. The file is 5,813,831 bytes, SHA-256 `f9da1c061c69e790e80acde288497ad531318664efe49115ba17a2ce7e84c588`.

The same helper wrote `data/raw/vt-v2/derived/collapse_incidents_delhi.csv` with the eight workbook rows whose `City` is `Delhi`. It parses dates, keeps source address/structure/injury/death and references in `note`, and leaves both coordinates null because the workbook provides no coordinates. One source row labelled Delhi has address `Ghaziabad`; it remains under the publisher's city label and cannot be assigned spatially without geocoding. The local workbook contains 25 incidents total (the publisher describes 26), of which 8 are labelled Delhi. The CSV is 2,517 bytes, SHA-256 `c2b31c1e6d3cbd1aebf1aa63b2a494776c4221be9d6f8535e110a7a215effc4f`. Both files remain under `data/raw/` pending full-pack creation; the exact v2 record is catalogued as CC0 1.0.

### Risk marker interpretation for conversion

### Delhi VT risk conversion (2026-11-16)

The new `pipeline/risk.py` converter reads the Delhi risk shapefile with the configured city bbox as a geometry-intersection filter and wrote `data/raw/vt-v2/derived/vt_building_risk_delhi.parquet`. It contains 3,517,198 features in EPSG:4326: 3,517,174 Polygons and 24 MultiPolygons. All source geometries in this subset were non-empty and individually valid. The four risk fields were renamed to the C0 names and stored as nullable int8 values. The source `*********` marker becomes null; 10,282 intersecting features contain nulls in every risk field. This is 42 more than the earlier 10,240 point-coordinate-in-bbox count because this conversion includes polygons intersecting the bbox even when the source `latitude`/`longitude` point lies outside it. Preserve this distinction in future crop or count checks.

The source `index` is not unique (253,179 distinct values in the bbox subset), so `bldg_id` is null for every row rather than fabricating a join key. The resulting GeoParquet is 270,689,606 bytes with SHA-256 `8F41D4316A5ED44F1B2E02DC2C7377044D0055301BDBA1CA7BF86D11FE0B828D`. The PyArrow check confirmed 3,517,198 rows, GeoParquet metadata, expected 0–4/null categories and null counts; all serialized geometries were batch-validated as valid. This remains a derived input under `data/raw/`, not a C0 pack file, until the remaining pack inputs and lineage are assembled.

A direct DBF header/record check found that `Risk_Insar`, `Risk_10yrs`, `Risk_30yrs`, and `Risk_50 yr` are numeric fields of width 9 and precision 6. The literal `*********` is therefore not a valid numeric category; the valid categories remain 0?4. Exactly 86,707 records have this marker in all four risk fields. The publisher's description says risk values can be missing where unavailable. For the future C0 conversion, map these four markers to null and keep the geometry row. Do not delete those records: 10,240 are inside the configured Delhi bounding box. The literal star convention itself has not been confirmed directly by the publisher.

OpenCity-only source selection (2026-11-17): The project owner requested using the OpenCity original, not the Kaggle mirror. Rechecked the published resource download URL and CKAN resource/package API on both production and staging; each returned HTTP 403. No publisher copy was obtained. Do not change the prototype manifest source to OpenCity until the original file is available and its hash/features are compared.
