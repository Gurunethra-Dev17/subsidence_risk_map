# E8 — LiCSAR/LiCSBAS time-series feasibility

## Hackathon-scoped status

**Hackathon-scoped documentation complete; conditional processing remains open.**
This note records the available frame-listing observation and its limitations.
It does not establish that LiCSAR covers the Delhi pilot area and does not
claim a time-series result. The original E8 processing requirements remain
open if geographic coverage is later verified.

## Objective

Assess whether COMET LiCSAR data and LiCSBAS processing could support a small
time-series feasibility study for the Delhi pilot, with a possible comparison
to baseline velocities. The E8 plan calls for checking frame coverage first,
running LiCSBAS on a small area only if frames cover the pilot, comparing
velocities with baseline points, and recording the result here. If coverage is
absent, the plan is to report that finding and stop E8.

## Portal observation supplied by the project team

Source: [official COMET LiCSAR portal](https://comet.nerc.ac.uk/COMET-LiCS-portal/),
accessed **2026-11-22**.

The team reports that its portal inspection displayed:

- Frame ID: `100A_06216_101111`
- Direction: Ascending
- Products listed: 585
- Epochs processed: 98%

The corresponding listed product directory is:

<https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products/100/100A_06216_101111/>

The directory contents and product downloads have **not** been verified. These
listing values are recorded as observations from the team's portal inspection;
this note does not independently verify the live portal or directory.

## Coverage and processing status

**Not verified:** geographic intersection of frame `100A_06216_101111` with
Delhi or the Bijwasan area of interest (AOI). A frame listing alone is not
proof of coverage of either pilot AOI. The frame footprint and target AOI must
be compared before treating this as usable coverage.

No LiCSBAS run has been performed. There are no time-series velocity estimates
or seasonal estimates, no comparison with baseline points, no HyP3 processing,
and no new displacement product. The E7 dry-run manifest is a shortlist of ASF
catalog metadata only; it is not a processed InSAR measurement.

Full time-series processing is deferred to a future research extension so the
team can prioritize real Delhi data integration and the hackathon map demo.
Any later velocity comparison must document reference frame, sign convention,
time interval, spatial sampling, and comparability with the baseline before
interpreting agreement or disagreement.

## Follow-up verification checklist

- [ ] Retrieve or inspect authoritative frame-footprint metadata for
      `100A_06216_101111`.
- [ ] Compare that footprint with the agreed Delhi pilot AOI and, separately,
      the Bijwasan AOI; record the AOI source/version and overlap result.
- [ ] Verify the listed product directory contents, available dates, and
      required inputs before planning any downloads.
- [ ] If coverage and usable products are confirmed, choose one bounded area
      and verify LiCSBAS setup and processing requirements before a small run.
- [ ] Identify suitable baseline points and document their source, reference
      frame, units, and spatial/temporal comparability.
- [ ] Only after those checks, run the bounded feasibility analysis and record
      methods, outputs, limitations, and whether seasonal separation is
      supportable.

## Completion boundary

This completes **E8 documentation for the hackathon scope**. It does not close
the conditional LiCSAR coverage check, LiCSBAS run, or baseline comparison if
the AOI is shown to be covered. No scientific conclusion about Delhi
subsidence or time-series agreement is made here.
