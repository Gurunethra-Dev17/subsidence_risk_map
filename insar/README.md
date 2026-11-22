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
