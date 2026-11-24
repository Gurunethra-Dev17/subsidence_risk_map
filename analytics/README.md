# Analytics (Person D)

Consumes C1-derived intermediates and produces C2 ward/cell outputs and C3 validation summaries.

## D8 contract exporter

`analytics.export` maps explicit intermediate files to the frozen C2/C3 contracts. It does not
import D1–D7 modules, fill missing indicators, resolve rank ties, create cell geometry, or claim
unavailable validation results. Ranked wards need unique contiguous ranks and supplied rank ranges
that bracket the rank. Cell attributes must match supplied valid polygon geometry; cells with fewer
than five buildings must be suppressed with all restricted metrics null. C2 flags are checked
against the frozen enum.

Install the existing project geo dependencies (`.[geo]`) before generating figures. Use explicit
inputs and outputs; the command below illustrates the interface, not a final-data run:

```powershell
python -m analytics.export export `
  --wards-csv out/delhi/d8_mock/inputs/wards.csv `
  --sensitivity-csv out/delhi/d8_mock/inputs/sensitivity.csv `
  --meta-json out/delhi/d8_mock/inputs/meta.json `
  --cells-csv out/delhi/d8_mock/inputs/cells.csv `
  --geometry-geojson out/delhi/d8_mock/inputs/cell_geometry.geojson `
  --ward-output out/delhi/d8_mock/ward_summary.json `
  --cell-output out/delhi/d8_mock/cell_scores.geojson `
  --validation-output out/delhi/d8_mock/validation_summary.json `
  --figure-dir out/delhi/d8_mock/figures `
  --generated-utc 2026-11-24T12:00:00Z
```

Optional `--validation-json` supplies C3 section objects (`vt_consistency`, `collapse_check`,
`hotspot_check`, `robustness`, `fresh_data_check`). Unprovided sections remain explicitly marked
unavailable/not run; existing C3 notes preserve the fixed caveats and explain unavailable
comparisons. Required schema counters of zero are accompanied by notes saying no records were
processed. `--overwrite` is required to replace existing JSON outputs. A fixed
`--generated-utc` makes JSON repeatable for identical inputs. Figures are generated only where
supplied score/rank/sensitivity values support them. Published-risk comparison figures are not
fabricated.

The D8 exporter is a phase-one contract boundary. Mock/synthetic output demonstrates wiring only;
it does not complete H3 or validate real Delhi data. Final output still depends on reconciled C0/C1,
confirmed groundwater boundaries, corrected upstream ranking/rank-range artifacts, supplied cell
geometry, and available independent validation inputs.

### Supplemental real-data figures

For an accepted real-data run, analytics.export export can additionally take
--figure-data-json containing already-computed D4 weight_sensitivity and a7_variants
summaries plus C1 metric-availability counts. The exporter only visualizes these supplied
summaries; it does not rerun sensitivity analyses or derive new measurements. It may also use
the supplied C3 hotspot_check rows to draw the literature-reference figure. Missing or
unavailable comparisons remain labeled as unavailable. These figures are descriptive and do
not constitute independent validation.
