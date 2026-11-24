# Delhi subsidence inspection-prioritization prototype

**D9 expert review draft: accepted real-data results included. External expert review and final D10/H3 acceptance are pending. Internal team use only.**

## Mentor review summary - page 1 of 2

### Purpose and scope

This hackathon prototype combines building-scale ground-motion and differential-distortion indicators into a **relative ward- and 250 m cell-level inspection-prioritization** view for Delhi. It is intended to help identify areas for qualified professional review. It is not a calibrated structural-collapse probability, a causal model, a structural inspection, or a building-safety certification.

### Data, provenance and method

The selected C0 pack is delhi-candidate-0.0.1. The accepted C1@1.0 contains 1,883,862 building records, produced with engine f3af18a, a 10-year horizon, seed 42, an 80-120 m pair window, and the staged C6 parameter hash 1a30d00c183cb58b2ee4d9327d9e839a8bc3f4267a0c3b15b207c181b49ac6d5. Other source vintages are distinct: Virginia Tech Indian Megacities v2 (DOI 10.7294/25856260.v2; 2025-04-28 per project lineage), Overture Buildings release 2026-10-21.0, and a Delhi 2022 ward candidate. No single observation date is claimed for these different inputs. The verified CGWB source is the 2025 Delhi assessment table, Annexure VI, with 34 assessment units.

The Inspection Index follows the project's frozen methodology:

- I1: share of buildings with usable VLM data and velocity at or below -4 mm/year.
- I2: ward 90th percentile of the C1 horizon angular-distortion metric.
- I3: building count (exposure).
- I4: groundwater extraction stage (%), intended to be area-weighted from assessment units to wards.

Eligible wards are percentile-ranked per indicator using average ranks scaled to 0 to 100; larger values mean higher priority. Configured weights are 30%, 35%, 20%, and 15%. For each ward, weights are renormalized over non-null indicators. With I4 unavailable, the global effective weights are approximately 35.29%, 41.18%, 23.53%, and 0%; additional per-ward renormalization applies when another indicator is missing. Scores sort descending, with ascending ward_id as the deterministic tie-break. Rank 1 is highest priority. A ward requires at least 50% VLM coverage among assigned buildings; otherwise it is marked insufficient_data and excluded from ranking.

### Accepted results

There are 250 unique wards: 245 ranked and five insufficient-data wards. Bijwasan ranks 1 with score 97.48 and D4 rank interval 1-1. Kapashera ranks 6 with score 89.44 and interval 3-13. Scores express relative priority under the selected inputs and assumptions, not risk probabilities.

The C2 cell export preserves all 23,051 supplied grid cells: 19,582 populated, 3,469 empty, 15,595 scored and 7,456 suppressed. Cells with fewer than five buildings are suppressed with restricted metrics and ranks null. Canonical cell ward_id follows the largest positive-area ward intersection, with ascending ward_id tie-breaking; it is not replaced by the majority ward among buildings. Some crossing cells consequently include buildings assigned to neighboring wards. In the spatial reconciliation, 3,728 cells intersected multiple wards; 82 had overlapping ward-intersection areas exceeding cell area. The largest-area rule reproduced the supplied grid assignment for all investigated cells, with no ties. These overlapping source polygons mean intersection area shares are not a non-overlapping partition.

D4 ran 500 Dirichlet weight perturbations (seed 42, concentration 50): mean Kendall tau was 0.9241 and median 5th-95th rank-interval width was 24. Nine A7 variants were evaluated. The three 50 m variants had no eligible ranked wards, so their correlations are unavailable. For the selected 80-120 m pair window, the 100 m and 150 m variants had tau approximately 1.000 and 0.995 on their common ranked comparison populations. This does not imply universal rank stability. The baseline C1 params hash differs from the nominal 100 m / 80-120 m A7 variant hash; similar ranks do not establish identical engine runs.

## Mentor review summary - page 2 of 2

### Coverage, groundwater and validation limits

Of 1,883,862 C1 building records, 1,055,505 have non-null building-record VLM metrics; the separate C0 VLM point dataset contains 182,817 points. C1 angular distortion is non-null for 238,115 records and unavailable for 1,645,747. Available values are aggregated; missing values remain null, are never treated as zero, and lead to available-indicator weight renormalization. Ward beta coverage ranges from about 7.9% to 22.5% (median 14.6%), so distortion coverage remains limited and materially affects interpretation. The horizon metric is a constant-rate scenario, not a forecast.

CGWB table values are verified, but correspondence between CGWB assessment-unit polygons and available boundaries is not. Exploratory proxy estimates were excluded from production scoring; all 250 ward groundwater values remain null and I4 is unavailable. No proxy estimate is presented as a verified ward measurement.

D5 found zero accepted exact unique geometry matches between C0 buildings and published-risk records. The Spearman comparison is unavailable and the confusion matrix is empty. This is neither evidence of agreement nor disagreement; broader spatial matching was exploratory and deferred. Published risk is not independent ground truth.

D6 contains eight source records labelled Delhi, but no incident has independently verified site coordinates and no spatial risk or rank comparison was performed. Incident 023's source city label conflicts with its Shah Beri, Greater Noida description. Approximate locality references are not verified sites.

D7 compared four literature/locality references. Two approximate references were assigned to ranked wards: Bijwasan (rank 1, D4 interval 1-1) and Kapashera (rank 6, interval 3-13); both fall in the descriptive top-10% priority band. Faridabad and Ghaziabad were outside supplied ward coverage; that does not establish administrative boundaries. Coordinate derivations are undocumented, observation periods and spatial scales differ, and n=2 is not independent validation or validation accuracy.

### D8 status, provenance and handling

D8 generated real C2 ward JSON, C2 cell GeoJSON, C3 validation JSON, eight figures, methodology and export metadata. Actual frozen schemas, finite-JSON, semantic and cross-reference checks passed; the full analytics suite passed 136 tests. D10 readiness returned READY, but final D10/H3 acceptance remains pending. The C2 histogram is null because no agreed binning and denominator method was available. Handoff packages were prepared for Persons B, C and E but have not been sent or integrated.

D1 QA was generated at 11:36:16Z, before the 11:49:40Z integration-manifest update documenting the subsequently verified VLM artifact. D1's run-time QA records that the C0 pack was then incomplete; the current manifest later verifies pack completeness. The historical manifest bytes are unavailable, so this accepted checksum exception cannot be reconstructed byte-for-byte. Current C0/C1/A7/C6 hashes and accepted D1-D8 outputs were checked. D7's canonical QA checksum excludes its outputs section (060f3d8d?); its full-file SHA-256 is d4504aaa?; these have different scopes.

The integration manifest retains an internal-use-only restriction while ward-source data-use terms are unresolved. Do not publish or deploy these real-data outputs until the data owner confirms permitted use. Detailed evidence is in the D1-D8 QA and provenance records under out/delhi/integration_2026-11-22/; this summary does not replace them.

### Five questions for expert review

1. Given that only 238,115 of 1,883,862 C1 building records have angular-distortion values, what validation would be needed before using the 10-year beta_horizon metric as an inspection-prioritization indicator, and how should its coverage limits be shown?
2. Is average-percentile normalization with per-ward renormalization across I1-I4 defensible when wards have different missing-indicator patterns? Would you recommend reporting comparable cohorts or additional diagnostics?
3. What boundary evidence and spatial allocation method would be adequate to assign the 34 CGWB assessment units to wards? Is excluding I4 until that correspondence is verified the appropriate treatment?
4. Are a 50% VLM coverage threshold and the reported 500 weight perturbations and A7 radius checks informative for this prototype? How should readers interpret variants with no ranked wards and rank intervals as wide as 90 places?
5. With no accepted D5 geometry matches, no independently located D6 collapse sites, and only two approximate D7 references comparable, what independent validation design and ground-truth evidence would be credible at this scale?

### Outreach email draft - not sent

**Subject:** Request for expert review - Delhi InSAR inspection-prioritization prototype

Hello,

Our team has completed a hackathon-stage Delhi mapping prototype that combines building-scale InSAR metrics, ward and cell indicators, groundwater context, and sensitivity summaries to support relative inspection prioritization. We have generated real C2/C3 exports and documented the available evidence and limitations. The prototype is not a collapse-probability model or a safety certification, and independent validation remains incomplete.

Would you be willing to review the methodology and advise us on the five questions in the accompanying summary, especially angular-distortion interpretation, missing-indicator weighting, groundwater boundary correspondence, and a credible validation design? We can share the concise summary and selected provenance material through an appropriate, rights-compliant channel. We are not seeking endorsement; critical feedback would be valuable.

Thank you for considering it,

Subsidence Risk Map project team

---

## Pending after D9

External expert feedback has not yet been obtained. Final D10/H3 acceptance, resolution of source-data-use restrictions, authoritative groundwater boundary correspondence, and independent validation remain open. Update this pack only when those items produce verified evidence; do not replace unavailable results with zeros or approximate locations.
