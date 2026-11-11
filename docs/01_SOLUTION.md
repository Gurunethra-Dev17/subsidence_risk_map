# SUBSIDENCE RISK MAP

## Satellite-Based Ground Movement Monitoring and Inspection Prioritisation for Indian Cities

*Turning free radar data into a ranked, explainable inspection list for ward engineers.*

**Hackathon theme:** Smart Infrastructure & Water (GIS and satellite data, structural health)
**Document:** 1 of 3 — Solution (what we build and why).
**See also:** `02_IMPLEMENTATION_AND_WORKING_PLAN.md` (who builds what, handoffs) and `03_CODEBASE_AND_API_CONTRACTS.md` (repository layout and frozen contracts).

---

## 1. The problem

Indian cities are sinking, and they are sinking unevenly.

- A 2025 *Nature Sustainability* study used satellite radar (2015–2023) on more than 13 million buildings and about 80 million people in Delhi, Mumbai, Chennai, Kolkata and Bengaluru. It found **878 km² of urban land subsiding**, with about **1.9 million people living where the ground sinks faster than 4 mm per year**.
- Maximum rates in the study: Delhi 51.0, Chennai 31.7, Mumbai 26.1, Kolkata 16.4, Bengaluru 6.7 **mm/year**.
- It estimated **2,406 buildings in Delhi, Mumbai and Chennai are already at high risk** of structural damage, and that **up to 23,529 buildings across the five cities could reach very high risk within 50 years** if current rates continue.
- The process is reversible in places: an area near Dwarka (Delhi) is rising at 15.1 mm/year after groundwater regulation and recharge.
- Groundwater overuse is the dominant local driver. Delhi's stage of groundwater extraction was assessed at 100.77% (CGWB, 2024). In Chennai, 46 of 51 revenue blocks were over-exploited in 2024.

**Why uneven sinking is the real danger.** A building can tolerate sinking if it sinks evenly. When neighbouring ground sinks by different amounts (*differential settlement*), walls and foundations bend and crack. The study measures this with *angular distortion*.

**Context, not our cause:** Joshimath sank about 9 cm slowly in 2022 and then about 5.4 cm in 12 days, as measured by ISRO's NRSC with Sentinel-1. That is a hill-slope landslide case, so its cause differs from city groundwater compaction. It shows that satellites can see these events and that they can escalate quickly.

## 2. The gap

- Indian building rules focus on soil stability at design and construction. We found no formal mechanism for tracking ground movement after a building is completed.
- The published study is a one-off analysis. Researchers have mapped Delhi NCR, Ahmedabad, Ludhiana and others, and an open-source research framework for building risk (BRASE) exists, but **we found no free, municipality-facing tool that converts this into a ranked inspection list**. (This is our reading of what searches turned up. Re-check before claiming it publicly.)
- Europe has a continent-wide free ground-motion service (EGMS). India has no equivalent we could find.

**Our position:** we are not the first to measure subsidence. We make published science usable: a transparent, uncertainty-aware ranking that a ward engineer can act on, and a pipeline that can be refreshed with new satellite data.

## 3. Users and scenario

| User | What they need |
|---|---|
| Ward / municipal engineer | Which areas to inspect first, and why |
| Disaster-management cell | Where ground movement may amplify flood or earthquake risk |
| Groundwater regulator | Where extraction and sinking coincide |
| Secondary: insurers, builders, residents' associations | Context for risk and pre-construction checks |

**Scenario.** A ward engineer receives crack complaints from several apartment blocks. Today she cannot tell whether the cause is construction quality or ground movement, and has no way to rank 40 blocks. With our tool she opens the ward, sees the neighbourhood rate and the difference between adjacent areas, gets a ranked list of 250 m cells (and, for authorities, buildings), reads the uncertainty flags, and downloads a one-page brief to justify an inspection order.

## 4. What we build

### 4.1 Core features (MVP)

| ID | Feature | Description |
|---|---|---|
| F1 | Ward map | Wards coloured by the **Inspection Index** (0–100). Wards with too little radar coverage are hatched "insufficient data" and not ranked |
| F2 | Ranking | Sortable, searchable ward ranking with **rank ranges** (for example "7 (4–11)") from a sensitivity analysis |
| F3 | Ward detail | Indicators, distribution of building distortion, uncertainty badges, plain-language tooltips |
| F4 | Cell view (public) | 250 m grid cells scored inside each ward. Cells with fewer than 5 buildings are suppressed |
| F5 | Building view (authority) | Building-level metrics, available only in authority mode |
| F6 | Uncertainty layer | Radar-point density, coverage percentage, sparse-area flags |
| F7 | Inspection brief | One-page PDF per ward with numbers, caveats and suggested inspection order |
| F8 | Methods, limits and validation pages | Every assumption visible, every validation result reported as found |
| F9 | API | Versioned REST API behind the app (contract C4) |

### 4.2 Extensions

| ID | Extension | Description |
|---|---|---|
| F10 | Fresh-data refresh | Run new Sentinel-1 interferograms for a small area through ASF HyP3 and show the result next to the baseline (a pipeline demonstration, not a full time series) |
| F11 | Time series | If COMET LiCSAR frames cover the pilot city, run LiCSBAS to get velocity and seasonal separation |
| F12 | Second city | Run the same pipeline for another city by changing configuration only |

### 4.3 What we do not claim

- We **do not certify any building as safe or unsafe**.
- We **do not predict future subsidence**. Projections (10, 30, 50 years) are scenarios that assume rates stay constant, and are labelled that way.
- We **do not prove the cause** of subsidence. Groundwater extraction is the main driver in the study, but local geology varies, and one hydrogeologist notes that extraction alone does not explain everything.
- Radar measures movement **relative to a reference** and along the satellite's line of sight. Our baseline vertical-motion data comes from the published dataset.
- The ranking is **relative within a city**, not an absolute safety score.

## 5. Pilot city

**Default: Delhi.** Reasons: highest rate in the study (51.0 mm/yr), independent published Delhi NCR studies to compare against, ward boundaries after the 2022 delimitation are available, and strong groundwater context.
**Alternative: Chennai** (second-highest rate, city GIS services published, 46 of 51 blocks over-exploited). The pipeline is configuration-driven (contract C6), so switching costs data preparation only.

## 6. Datasets

Links marked **checked** were surfaced during research. "Standard portal" links are well-known sites that were not opened during research, so confirm they load.

| # | Dataset | Used for | Documented contents | Link | Licence / terms |
|---|---|---|---|---|---|
| 1 | **Virginia Tech dataset: vertical land motion and building damage risk for the Indian megacities** | Baseline ground motion, consistency check, collapse catalogue | 11 files. Per-city CSVs of vertical land motion (columns: longitude, latitude, vlm in **cm/yr**, reference frame IGS14). A shapefile with fields `Risk_InSAR`, `Risk_10yrs`, `Risk_30yrs`, `Risk_50yrs`. `Building_Collapse_Incidents.xlsx` with 26 incidents. Version 2 dated 2025-04-28 | https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260 (checked) | **Not confirmed.** Read the dataset page. If redistribution is unclear, link instead of re-hosting |
| 2 | Paper: *Building damage risk in sinking Indian megacities* (Nature Sustainability, 2025) | Method reference | Radar-based differential settlement for five cities | https://doi.org/10.1038/s41893-025-01663-0 (checked) | Journal terms |
| 3 | **Overture Maps building footprints** | Building layer | Conflation of OpenStreetMap, Esri Community Maps, Microsoft and Google Open Buildings. GeoParquet on AWS/Azure | https://overturemaps.org (checked). Catalogue note on licence: https://gee-community-catalog.org/projects/overture_buildings/ (checked) | **ODbL.** Attribute: © OpenStreetMap contributors, Microsoft, Esri Community Maps contributors, Google Open Buildings |
| 4 | Open Buildings Extractor (`obe`) | Download footprints for an area from several sources | Python package and CLI | https://pypi.org/project/obe/ (checked), https://github.com/osgeonepal/obe (checked) | Tool licence on repo |
| 5 | **Ward boundaries (Delhi, 2022 delimitation)** | Aggregation unit | Shapefiles / GeoJSON via OpenCity | https://data.opencity.in/dataset/delhi-wards-information (checked) | Check dataset page |
| 6 | DataMeet municipal spatial data and community maps | Fallback wards; district boundaries | Boundaries for many cities (quality varies, some are older) | https://projects.datameet.org/Municipal_Spatial_Data/ (checked), https://projects.datameet.org/maps/ (checked) | Per file; known errors, so validate |
| 7 | Government city GIS services (Delhi GSDL, Mumbai BMC, Chennai GCC) | Boundaries, context layers | ArcGIS REST services | Guide with all three URLs: https://opencity.in/?p=9865 (checked). Chennai: https://gis.chennaicorporation.gov.in/server/rest/services/ (checked). Delhi: https://gsdl.org.in/arcgis/rest/services (checked) | Check each service's terms |
| 8 | **CGWB groundwater assessment** | Groundwater-stress indicator | Annual extractable resources and stage of extraction by assessment unit. Delhi 2024 report | https://www.cgwb.gov.in/cgwbpnm/public/uploads/documents/17422999301875928722file.pdf (checked). Chennai context: https://citizenmatters.in/?p=83529 (checked) | Government publication |
| 9 | **Sentinel-1 via ASF HyP3** | Fresh interferograms (extension) | Free on-demand InSAR. **8,000 free credits/month**. An 80 m InSAR scene job costs 10 credits. Burst InSAR supported (up to 15 contiguous bursts). Python SDK and REST API | Docs: https://hyp3-docs.asf.alaska.edu/ (checked). Credits: https://hyp3-docs.asf.alaska.edu/using/credits/ (checked). Burst guide: https://hyp3-docs.asf.alaska.edu/guides/burst_insar_product_guide/ (checked). API: https://hyp3-docs.asf.alaska.edu/using/api/ (checked). Account: https://urs.earthdata.nasa.gov/ (standard portal) | Free Earthdata Login required |
| 10 | **COMET LiCSAR and LiCSBAS** | Time series (extension) | Free processed Sentinel-1 interferograms and open-source time-series package. **Frame coverage for the pilot city must be checked.** LiCSBAS is research code provided as-is | https://comet.nerc.ac.uk/comet-lics-portal (checked), https://github.com/comet-licsar/LiCSBAS (checked) | Open |
| 11 | NISAR data (optional) | Future refresh | L-band products free via ASF DAAC. ISRO S-band over India via Bhoonidhi. Calibrated release began July 2026 | https://www.earthdata.nasa.gov/news/nisar-l-band-data-released-expanding-record-surface-changes (checked), https://bhoonidhi.nrsc.gov.in/ (checked) | Open |
| 12 | Literature for hotspot cross-check | Validation | Delhi NCR hotspot study using free Sentinel-1 (Kapashera, southwest Delhi) | https://link.springer.com/10.1038/s41598-021-04193-9 (checked). Also Ahmedabad: https://isprs-annals.copernicus.org/articles/X-G-2025/613/2025/ (checked) | Journal terms |

**Do not use:** NASA OPERA DISP-S1 displacement product. Its coverage is North America only (https://www.earthdata.nasa.gov/data/projects/nsite/solutions/opera-north-america-disp-product-suite, checked).

**Facts the data owner must verify on first inspection (and record in `data/AUDIT.md`):**
1. Unit and sign convention of `vlm` (documented as cm/yr; we convert to mm/yr; negative should mean sinking).
2. Geometry type of the risk shapefile (building polygons, building points, or grid cells) and how `Risk_*` fields are coded (the Lagos dataset from the same group uses 0–4, very low to very high; confirm for India).
3. Whether the collapse spreadsheet contains coordinates, cities and dates.
4. The licence text.

## 7. Method

### 7.1 Parameters (all configurable, contract C6)

| Parameter | Default | Meaning |
|---|---|---|
| `radius_m` | 100 | Search radius from a building centroid for radar points |
| `min_points` | 3 | Minimum points to trust a building estimate |
| `pair_min_m`, `pair_max_m` | 10, 60 | Distance range for point pairs used in distortion |
| `footprint_buffer_m` | 20 | Pairs count for a building if a point lies within its footprint buffered by this distance |
| `horizon_years` | 10 | Horizon for cumulative distortion (scenario, not forecast) |
| `class_edges_ratio` | [1000, 500] | Distortion class edges as 1/N. **Placeholders. Confirm with a geotechnical mentor.** Related work reports reference values such as 1/500 |
| `sinking_threshold_mm_yr` | −4 | Matches the study's "exposed" threshold |
| `coverage_min` | 0.5 | Wards below this share of buildings with data are "insufficient data" |
| `grid_m` | 250 | Cell size for the public view |
| `cell_min_buildings` | 5 | Cells with fewer buildings are suppressed |
| `weights` | 0.30, 0.35, 0.20, 0.15 | Index weights (see 7.3) |
| `sens_draws` | 500 | Weight-perturbation draws |
| `sens_concentration` | 50 | Dirichlet concentration around base weights |

### 7.2 Steps

1. **Prepare points.** `v_pt (mm/yr) = vlm_cm_yr × 10`. Project to the city's UTM zone for distance calculations (Delhi, Mumbai, Bengaluru: EPSG:32643; Chennai: 32644; Kolkata: 32645).
2. **Assign to buildings.** For each building centroid, collect points within `radius_m`. If at least `min_points`, `v_b` is the inverse-distance-weighted median; otherwise `v_b` is null and the building is flagged `sparse`.
3. **Point-pair distortion.** For every pair of points at a distance `d_ij` between `pair_min_m` and `pair_max_m`:
   `beta_ij = abs(v_i − v_j) × 1e-3 / d_ij` (per year, with v in mm/yr and d in metres).
4. **Building distortion.** `beta_b` is the 90th percentile of `beta_ij` over pairs touching the building's buffered footprint (null if fewer than 3 pairs). Cumulative distortion `beta_b(T) = beta_b × T`. Display as `1/round(1/beta_b(T))`. Assign class (`low`, `watch`, `inspect`) from `class_edges_ratio`.
5. **Worked example (use as a unit test).** Points at −10 and −6 mm/yr, 20 m apart: `beta = 0.004 / 20 = 2e-4` per year. After 10 years, `2e-3 = 1/500`.
6. **Ward indicators.**
   - **I1** share of buildings with data and `v_b ≤ −4 mm/yr`
   - **I2** ward 90th percentile of `beta_b(T)`
   - **I3** exposure: building count
   - **I4** groundwater stage of extraction (%), area-weighted from assessment units to wards
7. **Coverage rule.** `coverage = buildings with data / buildings`. Below `coverage_min` the ward is `insufficient_data` and is excluded from ranking.
8. **Inspection Index.** Percentile-rank each indicator across ranked wards, then
   `score = 100 × (0.30·P(I1) + 0.35·P(I2) + 0.20·P(I3) + 0.15·P(I4))`.
   If groundwater is unavailable, drop I4, renormalise weights and flag it.
9. **Sensitivity.** Draw weights from a Dirichlet distribution centred on the base weights (`sens_draws` times), recompute ranks, and report the 5th and 95th percentile rank per ward and the mean Kendall τ against the baseline ranking. Repeat the engine with `radius_m` ∈ {50, 100, 150} and report stability.
10. **Cell index.** Same formula using I1, I2, I3 with weights renormalised (0.30, 0.35, 0.20 divided by 0.85), computed per 250 m cell, with small-cell suppression.
11. **Consistency check against the published categories.** Spearman correlation between `beta_b(T)` and the dataset's `Risk_*` categories, and a confusion table.
12. **Extension F10.** For a small area around a known hotspot, find Sentinel-1 bursts with `asf_search`, submit burst InSAR jobs through HyP3, download, and export a displacement GeoTIFF and image overlay with dates and parameters. Compare pattern and sign with the baseline map. Label as pipeline demonstration (line-of-sight, not vertical).
13. **Extension F11.** If LiCSAR frames cover the city, run LiCSBAS on a small area, compare velocities with the baseline points, and test separating long-term trend from seasonal signal.

### 7.3 Why these choices

- 90th percentile instead of maximum reduces noise from single outlier points.
- Percentile ranking makes the index relative within a city. Absolute indicators are always shown beside it.
- Rank ranges tell users how much the ordering depends on our weights, which are judgement calls.

## 8. Product experience

1. **Overview map.** Ward choropleth, legend, hatched insufficient-data wards, layer toggles.
2. **Ranking panel.** Rank, name, score, rank range, coverage badge.
3. **Ward detail.** Indicators with tooltips, histogram of building distortion, uncertainty badges, "download brief".
4. **Public mode.** Wards and 250 m cells only.
5. **Authority mode.** Adds building-level layer and building lists (token-gated in the API).
6. **Methods and limits page.** Parameters, formulas, what we do not claim.
7. **Validation page.** All results from section 9, including weak ones.

## 9. Validation plan

We report whatever the checks show, and we do not tune parameters to hit a target number.

| Check | How | What we report |
|---|---|---|
| V1 Consistency with published categories | Spearman ρ and confusion table, our `beta_b(T)` vs `Risk_*` | ρ, n, table, interpretation |
| V2 Collapse incidents | Locate in-city incidents from the 26-incident catalogue against our wards/cells and the published risk categories | Counts per category and rank band. With very small n we make no statistical claim, and causes of collapses are not attributed to subsidence |
| V3 Hotspot cross-check | Named hotspots from the literature (for Delhi NCR: Bijwasan, Faridabad, Ghaziabad from the study; Kapashera from the Delhi NCR paper) vs our ward ranks | Rank and percentile of the containing wards |
| V4 Robustness | Weight perturbation and radius variants | Rank ranges, Kendall τ |
| V5 Fresh-data plausibility | HyP3 refresh near a known hotspot | Pattern and sign agreement (qualitative) |

## 10. Limitations and responsible use

- Source radar data covers 2015–2023 in the baseline dataset. Statements are about that period.
- Radar needs stable reflecting surfaces. Vegetation and water reduce coverage, so such areas show "insufficient data" instead of guesses.
- We have no ground-truth GPS or levelling. Validation is by consistency with published results, not by independent measurement.
- Naming individual buildings as "at risk" can cause panic or harm property values. The public view is limited to wards and cells of at least 5 buildings. Building detail needs authority mode.
- Class thresholds are placeholders until reviewed by a geotechnical expert.

## 11. Pitch

**30 seconds.** "India's biggest cities are sinking unevenly. A 2025 study found 878 square kilometres of subsiding land and up to 23,529 buildings at very high risk within 50 years at current rates, yet building rules don't require watching the ground after construction. We turn free satellite data into a ranked inspection list for ward engineers, with every assumption visible and every ranking shown with its uncertainty."

**10 seconds.** "A ward-by-ward inspection list from free satellite data, with its uncertainty shown."

### Likely questions

| Question | Short answer |
|---|---|
| Isn't this the published study again? | It is built on it. We add what the study doesn't offer: a ward-level ranking, uncertainty, rank ranges, public and authority views, briefs, an API and a refresh pipeline |
| Where is the AI? | We deliberately avoid claiming AI for its own sake. The core is transparent geospatial analysis. Machine learning enters in the extension for separating trend from seasonal signal |
| How do you know it's right? | We compare with published categories, known hotspots and collapse locations, and show robustness checks. We have no ground-truth GPS and say so |
| Can it say a building is unsafe? | No. It ranks areas for inspection |
| Does groundwater cause all of it? | It's the dominant driver in the study, but geology varies. We show groundwater stress as context, not as proof |
| Why percentile ranks? | To rank wards within a city. We also show absolute indicators |
| What about privacy and misuse? | Public mode stops at ward and 250 m cells with at least 5 buildings. Building detail is for authorities |
| Can it work for other cities? | Yes. Configuration drives it, and we tested a second city's data preparation |
| What are the thresholds based on? | Placeholders we plan to confirm with a geotechnical expert. They are configurable |
| What would you add next? | Fresh time series per city, seasonal separation, and city onboarding |

## 12. Glossary

- **Subsidence:** gradual sinking of the ground surface.
- **Vertical land motion (VLM):** up/down ground movement, in mm/yr here. Negative means sinking.
- **Differential settlement:** uneven sinking between nearby points.
- **Angular distortion:** relative settlement divided by the horizontal distance between two points. A building bends more as it grows.
- **InSAR:** measuring ground movement by comparing radar signal phase between satellite passes.
- **Line of sight (LOS):** direction from satellite to ground. Raw InSAR measures movement along it.
- **IGS14:** global reference frame used by the baseline dataset.
- **Stage of groundwater extraction:** extraction as a percentage of annually extractable resource.
- **Coverage:** share of buildings with enough nearby radar points.
- **Rank range:** the spread of a ward's rank across weight and parameter variations.

## 13. Sources

- Down To Earth, study summary: https://www.downtoearth.org.in/environment/land-beneath-indias-five-largest-cities-is-sinking-due-to-over-extraction-of-groundwater-study
- UNU-INWEH release: https://unu.edu/inweh/news/groundwater-decline-and-land-subsidence-threaten-indias-big-cities
- Mongabay India: https://india.mongabay.com/2025/11/scientists-warn-of-land-sinking-beneath-indias-megacities/
- Earth.com (angular distortion explained): https://www.earth.com/news/indias-biggest-cities-are-sinking-and-its-part-of-a-worldwide-trend
- Gulf Today (building rules gap): https://www.gulftoday.ae/opinion/2025/12/02/indian-megacities-face-sinking-risks
- Competitiveness.in (no post-completion monitoring): https://competitiveness.in/a-missing-variable-in-indias-urban-bet/
- BRASE poster (related work and reference thresholds): https://gsameetings.secure-platform.com/connects26/solicitations/103015/sessiongallery/schedule/items/96619/application/15516
- Joshimath, NRSC report coverage: https://scroll.in/latest/1041802/scroll_in
- Chennai groundwater: https://citizenmatters.in/?p=83529
- Delhi groundwater (CGWB 2024): https://www.cgwb.gov.in/cgwbpnm/public/uploads/documents/17422999301875928722file.pdf
- European Ground Motion Service: https://land.copernicus.eu/pan-european/european-ground-motion-service
