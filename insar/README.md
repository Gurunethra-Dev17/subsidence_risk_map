# InSAR extensions (Person E)

## E7.1: bounded ASF discovery

Use Python 3.11 and install this optional dependency group:

```powershell
python -m pip install -e ".[insar,dev]"
```

The discovery CLI makes a read-only, unauthenticated ASF search restricted to
the documented `SLC_BURST` dataset. `--max-results` is sent to ASF and is capped
locally at 250; the result list is also truncated to that bound. It does not
submit HyP3 jobs, download products, or assert that catalog bursts are confirmed
compatible pairs. Fields not supplied by ASF remain `null` (burst fields are
included only when present).

Example using the approximate, city-wide Delhi C6 bbox as a **provisional search
extent only**, not a scientifically validated hotspot:

```powershell
New-Item -ItemType Directory -Force insar/outputs | Out-Null
python -m insar.refresh discovery `
  --bbox 76.84,28.40,77.35,28.89 `
  --start 2025-01-01 `
  --end 2025-03-31 `
  --max-results 25 `
  --output insar/outputs/delhi-candidates.json
```

The output directory must already exist. Existing output files are protected;
pass `--overwrite` only when replacement is intended. `insar/outputs/` is
ignored by Git. Do not commit catalog output if it contains operational
metadata, and never commit Earthdata credentials or downloaded products.

Both date arguments are inclusive UTC calendar dates: the ASF query uses
`--start` at `00:00:00Z` and `--end` at `23:59:59Z` on the supplied end date.

The bbox, dates, and candidate pair selection require scientific review. A
catalog match is not proof of a viable interferometric pair, HyP3 eligibility,
or measured displacement. E7.1 is discovery only; processing and comparison
remain later work. Fresh InSAR is line-of-sight motion, not vertical motion.

## E7.2: offline repeat-pass shortlisting

The normalizer preserves ASF's top-level polarization, maps `pathNumber` to
relative orbit, and reads burst metadata from the SDK's nested `properties.burst`
object. `shortlist_pairs()` groups records only when explicit full burst ID,
polarization, relative orbit, flight direction, platform, processing level,
beam mode, and subswath are available and match. It considers only acquisitions
on different UTC dates; missing or unsupported metadata is reported as
unresolved, with no filename-based inference. The function is an offline
metadata helper and does not run automatically during discovery. Its results
are unverified candidates, not confirmed HyP3-compatible pairs; do not submit
them for processing until HyP3 requirements and the candidate metadata have
been checked.

Run the offline `pairs` command on an existing discovery report (no ASF
connection is made). The default cap is 100 pairs and `--max-pairs` accepts
1–1000. The input report must contain at most 250 normalized result records.
The output directory must already exist; existing output is protected unless
`--overwrite` is supplied.

```powershell
python -m insar.refresh pairs `
  --input insar/outputs/delhi_burst_discovery.json `
  --output insar/outputs/delhi_pair_shortlist.json `
  --max-pairs 100
```

The JSON report includes candidate pairs, unresolved records with reason codes,
and unpaired records. No missing metadata is inferred from filenames. Empty
candidate output is valid when there are no eligible records. Every candidate
is explicitly unverified and is **not** confirmation of HyP3 compatibility.

## E7.3: offline dry-run refresh manifest

Select the shortest temporal-separation VV candidate from an E7.2 pair report
without contacting ASF or submitting a processing job:

```powershell
python -m insar.refresh dry-run `
  --input insar/outputs/delhi_pair_shortlist.json `
  --output insar/outputs/delhi_dry_run_manifest.json
```

The command validates the pair-report fields, uses stable tie-breaking for
equal separations, and refuses to replace an existing output unless
`--overwrite` is provided. It writes a `not_submitted` manifest with HyP3
eligibility `unverified`, displacement product `not_available`, and provenance
identified as ASF catalog metadata rather than processed InSAR measurements.
If no valid VV candidate exists, it exits without writing a manifest.

## E7: processed product QA and internal overlay

For an already downloaded ASF HyP3 burst product, run local QA without any
network access or job submission. The QA command uses the optional `geo`
dependencies already declared in `pyproject.toml`. Pass the extracted product
directory, original ZIP, accepted ward GeoJSON and C2 ward summary explicitly:

```powershell
# If an inherited PROJ_LIB/PROJ_DATA points at a different GIS installation,
# clear those overrides in this PowerShell process for the Python geo stack.
Remove-Item Env:PROJ_LIB -ErrorAction SilentlyContinue
Remove-Item Env:PROJ_DATA -ErrorAction SilentlyContinue
$env:MPLCONFIGDIR = Join-Path $env:TEMP 'e7-matplotlib-cache'
python -m insar.product_qa `
  --product-dir out/delhi/e7_hyp3_S1_056011_IW2_20261104_20261116_VV_INT80_A048/S1_056011_IW2_20261104_20261116_VV_INT80_A048 `
  --archive out/delhi/S1_056011_IW2_20261104_20261116_VV_INT80_A048.zip `
  --wards out/delhi/wards.geojson `
  --c2-summary out/delhi/integration_2026-11-22/analytics/d8/ward_summary.json `
  --output-dir out/delhi/e7_hyp3_S1_056011_IW2_20261104_20261116_VV_INT80_A048/S1_056011_IW2_20261104_20261116_VV_INT80_A048/qa_corrected `
  --coherence-threshold 0.30
```

The output directory must be new or empty. It contains raster QA figures,
`qa_summary.json`, a masked relative-LOS GeoTIFF, a transparent EPSG:4326 PNG,
`overlay_manifest.json`, checksums and `PERSON_C_HANDOFF.md`. For MapLibre, use
the four `maplibre_corners_lon_lat` coordinates from the overlay manifest in
top-left, top-right, bottom-right, bottom-left order. Keep the overlay separate
from C2 scores and risk styling. This frozen C4 API does not serve the PNG; it
is an internal static-artifact handoff, and the normal API continues to operate
without it.

To expose only an aggregate, honest processing status through the existing C3
response, configure `API_INSAR_MANIFEST_PATH` to the generated
`api_fresh_data_status.json` before starting the API. The endpoint returns
`processed_not_validated`; it does not expose the PNG or change the underlying
C3 artifact. Leave this variable unset when that status manifest is not
deployed. For local PowerShell startup, set it in that server process, for
example: `$env:API_INSAR_MANIFEST_PATH = 'out/delhi/e7_hyp3_S1_056011_IW2_20261104_20261116_VV_INT80_A048/S1_056011_IW2_20261104_20261116_VV_INT80_A048/qa_corrected/api_fresh_data_status.json'`.

QA derives LOS displacement as `-unwrapped_phase * 2.8 cm / (2*pi)`: ASF
states that unwrapped phase is positive away from the sensor, while its
LOS-displacement convention has the opposite sign (positive toward, negative
away). The product does not include a dedicated LOS-displacement raster.

Ward coverage is now the sum of actual raster-cell/ward polygon intersection
areas, not whole-cell counts based on pixel centers. The QA summary retains all
250 ward records and validates coverage within [0, 100]%. The tiny floating-
point overlay overruns are reported in the QA summary; only values within the
explicit 1e-12 relative tolerance are bounded to polygon area, while larger
overruns fail analysis.

The PNG display uses a symmetric 98th-percentile scale, so values outside it
use saturated endpoint colors. The masked GeoTIFF preserves all derived values
without display clipping. Frontend legend recommendation: relative LOS
displacement (cm), negative away, 0 midpoint, positive toward; label endpoints
as <= lower and >= upper display limit. Measured values can exceed those
display limits.

A single 12-day ascending pair is not vertical subsidence, annual velocity,
building damage, collapse likelihood or independent validation. The coherence
cutoff is an exploratory display mask, not a universal standard. The supplied
product was unwrapped without a water mask or atmospheric correction; phase
reference and unwrapping errors remain limitations. The overlay is suitable
only for a limited internal demonstration. Confirm source/data licensing and
redistribution permissions before public hosting. The phase/LOS sign and
Sentinel-1 2-pi-to-half-wavelength conversion follow the ASF [InSAR product
guide](https://hyp3-docs.asf.alaska.edu/guides/insar_product_guide/) and [burst
InSAR product guide](https://hyp3-docs.asf.alaska.edu/guides/burst_insar_product_guide/).
