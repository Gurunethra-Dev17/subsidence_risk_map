# Delhi subsidence inspection-prioritization prototype

## Mentor review summary — page 1 of 2

### Purpose and scope

This hackathon prototype combines building-scale ground-motion and differential-settlement
indicators into a transparent **relative inspection-prioritization** view for Delhi wards and
250 m cells. It is not a structural inspection, a building-safety certification, a collapse
prediction, or a causal model. The ranking is intended to help decide where a qualified engineer
might investigate further. The project plan describes the planned method in
[`docs/01_SOLUTION.md`](../docs/01_SOLUTION.md) and the work split and gates in
[`docs/02_IMPLEMENTATION_AND_WORKING_PLAN.md`](../docs/02_IMPLEMENTATION_AND_WORKING_PLAN.md).

**Evidence labels used below:** “planned” refers to the project method; “reference snapshot” refers
to Person D’s separate saved code/results and is preliminary; “synthetic” refers to D8 tests/demo;
“locally verified” refers to checked team artifacts. There is no accepted final real-data C2/C3 run
or independent scientific validation at this stage.

### Data, provenance, and current status

The documented baseline source is the Virginia Tech *Data for Vertical Land Motion and Building
Damage Risk for the Indian Megacities*, version 2, dated 2025-04-28. The solution document describes
city vertical-land-motion files, published `Risk_*` categories, and a collapse-incident workbook.
The source page is [Virginia Tech Dataverse](https://data.lib.vt.edu/articles/dataset/Data_for_Vertical_Land_Motion_and_Building_Damage_Risk_for_the_Indian_Megacities/25856260).
The project plan calls for C0 building footprints and C1 building metrics; their frozen fields and
metadata are specified in [`docs/03_CODEBASE_AND_API_CONTRACTS.md`](../docs/03_CODEBASE_AND_API_CONTRACTS.md).
Building-footprint provenance/licensing must be carried with the pack; the solution document notes
Overture attribution and ODbL-related terms, and says the published dataset licence still needs
confirmation.

The team’s locally verified C1 file has null beta metrics. Person D’s separate reference snapshot
and saved D5 report 238,115 non-null beta-horizon values among 1,883,862 records. These inputs are
not currently reconciled; the authoritative C0/C1 version and its provenance are awaiting
confirmation. Person D’s numeric analysis outputs must therefore be treated as preliminary and
must not be substituted for a run on the confirmed team inputs.

The source table extracted from the 2025 Central Ground Water Board Delhi assessment contains 34
assessment units (`out/delhi/cgwb_delhi_2025.pdf`, Annexure VI; handoff CSV under
`out/delhi/d2_cgwb_handoff/`). Matching assessment-unit boundaries are unverified. Person D’s D2
code uses Survey of India subdistrict boundaries as provisional proxies; its QA explicitly says
they are not confirmed CGWB polygons. The resulting ward groundwater values are spatial estimates,
not direct ward measurements, and are not final C2 values.

### From InSAR metrics to ward indicators

The planned C1 method derives point velocities from radar observations, pairs nearby points, and
estimates differential distortion. The project method defines pair distortion as
`abs(v_i − v_j) × 1e-3 / d_ij` per year, with velocities in mm/year and distance in metres;
building-level `beta` is summarized from contributing pairs. Multiplying by the configured horizon
produces a constant-rate scenario, not a forecast. The worked example and parameter definitions
are in `docs/01_SOLUTION.md`, sections 7.1–7.2. The Delhi scientific context is the 2025 study
[Building damage risk in sinking Indian megacities](https://doi.org/10.1038/s41893-025-01663-0).

The plan defines I1 as the share of buildings sinking faster than 4 mm/year, I2 as the ward 90th
percentile of horizon distortion, I3 as building exposure, and I4 as groundwater extraction stage.
Coverage is buildings with usable data divided by buildings; below the configured 50% threshold a
ward is `insufficient_data` and excluded from ranking. Person D’s reference aggregation consumes
preassigned ward IDs rather than performing the planned C0 geometry-to-ward spatial join, so that
assignment still needs upstream verification.

The reference D3 code percentile-ranks available indicators and renormalizes the 0.30/0.35/0.20/0.15
weights over indicators available for each ward. It currently hard-codes the weights and uses
minimum-tie ranks. Its saved revised index has 245 ranked wards but only 239 distinct ranks, so the
ranks are not contiguous as H3 requires. This is an upstream D3 issue; D8 deliberately rejects rank
gaps instead of silently changing them.

## Mentor review summary — page 2 of 2

### Groundwater, cells, uncertainty, and validation

Person D’s D2 implementation area-weights assessment-unit extraction stages over ward intersections
and assigns the category covering the largest intersected area. The source CSV has 34 records and
the proxy workflow reports 250 wards processed, but matching CGWB boundaries and the unit-area
discrepancies remain unresolved. If groundwater cannot be supported, the planned index drops I4,
renormalizes available weights, and flags the omission; it must not replace missing groundwater
with zero.

The frozen cell contract calls for I1/I2/I3 scoring within wards and suppression of cells with fewer
than five buildings; suppressed properties must contain no restricted metrics. Person D’s current
cell code is explicitly provisional: it omits I2, marks ambiguous ward assignments, and produces
tabular intermediates rather than final geometry-backed C2 GeoJSON. Cell boundaries must come from
a supplied, verified grid; the exporter will not construct them.

Person D’s saved D4 report describes 500 Dirichlet weight draws (concentration 50, seed 42) across
245 baseline wards. Its saved mean Kendall tau is approximately 0.903 and the median p05–p95 rank
interval width is 37 places. These are preliminary results tied to the unreconciled reference input.
All three 50 m A7 radius variants produced zero ranked wards; 100 m variants ranked 245, while
150 m variants ranked 250 (compared on the common 245-ward population). Sensitivity experiments
describe model stability under selected assumptions; they are not independent observations or
confidence intervals.

Person D’s D5 report contains internal checks but explicitly marks the independent published-risk
comparison unavailable: Spearman correlation and confusion matrix are null, and its reported
`vt_risk_insar` is null for all 1,883,862 rows in that reference report. D6 has eight source incident
records; none has independently verified collapse-site coordinates. Six exploratory ward matches
use approximate locality/street reference points, one record is unresolved, and the Shah Beri,
Greater Noida record is excluded from Delhi matching. These points are not building locations.
Person D’s D7 report compares two of four literature/locality references with Delhi wards; the
coordinates are approximate, two references are outside Delhi, and temporary tie-broken ranks were
used. Neither D6 nor D7 establishes building-level agreement or causation. The Delhi NCR literature
source is [Garg et al. (2022)](https://doi.org/10.1038/s41598-021-04193-9); the project’s other
hotspot reference is the 2025 Nature Sustainability paper cited above.

### Export status and interpretation

D8’s `analytics/export.py` maps explicit intermediate files to C2 ward JSON, C2 cell GeoJSON, and
C3 validation JSON. It validates the frozen schemas, coverage flags, contiguous ward ranks, rank
ranges, supplied EPSG:4326 cell polygons, and suppression. Synthetic tests and an ignored synthetic
demo pass; they verify exporter behavior, not Delhi results. No final real-data C2/C3 export has been
accepted, and H3 remains pending until authoritative inputs and upstream issues are resolved.

The C2/C3 contract and H3 criteria are documented in `docs/03_CODEBASE_AND_API_CONTRACTS.md`,
sections 4.4–4.5. Any C3 null or unavailable comparison must retain its explanatory note. All results
remain descriptive associations. They do not establish that subsidence caused a collapse, identify
an unsafe building, or predict future structural failure.

### Five questions for technical review

1. **Angular distortion:** Given that C1 summarizes nearby InSAR point-pair gradients into a
   building-level beta percentile, what geotechnical validation would you require before using this
   as a ward inspection-prioritization indicator, and which geometric or temporal failure modes
   could make it misleading?
2. **Index and missing indicators:** Is percentile ranking across currently eligible wards, followed
   by per-ward renormalization of the 0.30/0.35/0.20/0.15 weights when I2 or I4 is missing, a
   defensible comparison? Should wards with different available-indicator sets be ranked together,
   or should the product show separate comparable cohorts?
3. **Groundwater allocation:** What evidence would be sufficient to accept an area-weighted CGWB
   assessment-unit-to-ward join, and should the current Survey of India subdistrict proxy be excluded
   until boundaries are confirmed against CGWB units?
4. **Uncertainty and coverage:** Are the 50% building-coverage threshold and 500 Dirichlet weight
   draws with p05/p95 rank intervals suitable for this prototype? What additional uncertainty or
   radius-variant checks are essential, especially where a variant yields no ranked wards?
5. **Validation evidence:** With published categories unavailable in the current C1 and no
   independently verified collapse-site coordinates, what independent reference data and validation
   design would you consider credible without overstating a small-sample spatial association?

### Outreach email draft

**Subject:** Request for technical review — Delhi InSAR inspection-prioritization prototype

Hello,

We are building a hackathon-stage Delhi mapping prototype that combines building-scale InSAR
metrics, ward coverage, groundwater context, and sensitivity analysis to help prioritize areas for
inspection. It is an exploratory decision-support tool, not a safety certification or collapse
prediction. We have attached a short methodology and validation summary that distinguishes implemented
work, preliminary results, and unresolved data limitations.

Would you be willing to review the methodology and advise us on the five technical questions in the
summary, particularly the interpretation of angular distortion, groundwater spatial allocation,
and the validation evidence needed before presenting real-data results? We would welcome a brief
written response or a short discussion at your convenience. We can share the relevant code and
provenance notes if useful.

Thank you for considering it,

Subsidence Risk Map project team

---

## Final-results update checklist — not part of the mentor summary

Update this package after Person A confirms the authoritative C0/C1 inputs and after a real-data D8
run. Record the source version, C0/C1 contract metadata, hashes, engine/config versions, and actual
null/non-null counts. Recompute and replace any affected numerical claims for:

- C1 beta and VLM availability, plus D1 ward-level counts and coverage after verified spatial
  assignment;
- D2 groundwater values only after matching assessment-unit boundaries are confirmed (otherwise
  retain the proxy limitation and do not present them as final);
- D3 indicator availability, scores, ranks, tie handling, and contiguous rank acceptance;
- D4 mean Kendall tau, rank intervals, interval-width summary, and each comparable A7 radius result;
- D5 Spearman/confusion/per-ward comparison only if an appropriate independent published-risk
  reference is available and joinable;
- D6 source counts, city/date exclusions, coordinate provenance, and comparisons only where
  independent locations support them;
- D7 source coordinates, ward assignment, and rank/percentile values using accepted D3 ranks;
- D8 generated C2/C3 metadata, rows/features, null explanations, figures, schema checks, and every
  H3 criterion.

Keep approximate coordinates and unavailable comparisons labeled as such. Do not replace nulls with
fabricated zeros or change the frozen C2/C3 contracts.
