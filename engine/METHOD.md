# Person A: engine method

This note describes the implemented A1-A7 geospatial engine and the interpretation limits of its C1 outputs. The formulas and parameter values below reflect the code and the Delhi C6 configuration; configuration values can differ by city.

## Inputs and coordinate conventions

The C6 configuration supplies the city bounding box, projected UTM EPSG code, C0 pack location, random seed, and analysis parameters. The point loader accepts `vlm_mm_yr` directly in mm/year. Source columns named `vlm_cm_yr` or `vlm` are interpreted as cm/year and multiplied by 10. Coordinates and rates must be finite and valid; points outside the inclusive configured longitude/latitude bounding box are clipped.

Negative VLM values mean sinking and positive values mean rising. The engine does not reverse signs. Spatial distances are calculated after projecting the building and point geometries to the configured UTM CRS, where distances and buffers are in metres.

## A2: assign point motion to buildings

For each building, the engine computes its centroid in the projected CRS and selects VLM points within `radius_m`. It records the point count as `n_points`. If that count is below `min_points`, the building is marked `sparse` and `vlm_mm_yr` and `vlm_iqr_mm_yr` are null.

For a building with enough observations, each selected point at distance \(d_i\) receives inverse-distance weight:

\[
w_i = \frac{1}{d_i}.
\]

The building estimate is the weighted median of the selected rates. `vlm_iqr_mm_yr` is the weighted 75th percentile minus the weighted 25th percentile. Weighted quantiles use the midpoint plotting positions of the sorted observations and linear interpolation. When one or more observations coincide exactly with the centroid, those observations receive equal weight and the non-coincident observations do not contribute to that estimate.

The returned A2 rows preserve the input building order and contain `bldg_id`, `n_points`, `vlm_mm_yr`, `vlm_iqr_mm_yr`, and `sparse`.

## A3: building-scale angular distortion

Each building footprint is buffered by `footprint_buffer_m`. VLM points intersecting that buffered footprint are the building's anchor points. Candidate pairs are formed from each anchor and all points within `pair_max_m`; a pair is retained when its distance is within the inclusive interval [`pair_min_m`, `pair_max_m`] and at least one endpoint is an anchor. A pair with two anchor points is counted once.

For pair \(i,j\), with VLM rates in mm/year and projected separation \(d_{ij}\) in metres, the annual differential rate is:

\[
\beta_{ij} = \frac{|v_i-v_j| \times 10^{-3}}{d_{ij}}.
\]

The factor \(10^{-3}\) converts mm/year to m/year, so \(\beta_{ij}\) is a dimensionless angular rate per year. The engine records all eligible pairs in `n_pairs`. With at least three pairs, the building's `beta_rate_per_yr` is the 90th percentile of the pair rates. With fewer than three pairs, it preserves `n_pairs` and leaves the distortion estimate, horizon value, ratio, and class null.

The configured horizon value is a scenario multiplier:

\[
\beta_{horizon} = \beta_{rate\ per\ year} \times horizon\_years.
\]

It is not a forecast. The engine formats the result as the nearest reciprocal `1/N`; zero is represented as `1/inf`. For `class_edges_ratio = [watch_denominator, inspect_denominator]`, both descending, classification uses inclusive thresholds:

- `inspect` when \(\beta_{horizon} \ge 1/inspect\_denominator\)
- `watch` when \(\beta_{horizon} \ge 1/watch\_denominator\)
- `low` otherwise

For the Delhi defaults `[1000, 500]`, the watch threshold is 0.001 and the inspect threshold is 0.002. These are configured indicator bands, not probabilities of damage or failure.

The worked example in the tests uses rates −10 and −6 mm/year separated by 20 m. It gives \(\beta_{ij}=0.0002\) per year and, at a 10-year horizon, \(\beta_{horizon}=0.002\), reported as `1/500` and classified `inspect` under the Delhi defaults.

## C1 assembly and metadata

The exporter joins C0 building attributes, A2 assignments, and A3 distortion results by `bldg_id`. IDs must be non-empty and unique, and the assignment and distortion ID sets must exactly match the C0 buildings. The output preserves C0 building order.

C1@1.0 rows contain:

| Field | Meaning |
|---|---|
| `bldg_id` | Stable building join key |
| `ward_id`, `cell_id` | C0 administrative and grid identifiers |
| `n_points`, `vlm_mm_yr`, `vlm_iqr_mm_yr`, `sparse` | A2 point assignment outputs |
| `n_pairs`, `beta_rate_per_yr`, `beta_horizon`, `beta_ratio_horizon`, `beta_class` | A3 distortion outputs |
| `vt_risk_insar` | Nullable source risk category copied from C0 when available |
| `engine_version` | Version label recorded for the run |
| `params_hash` | SHA-256 of canonical JSON for the C6 `params` mapping |

Parquet metadata records the C1 contract version, horizon, seed, engine version, and parameter hash. The parameter hash covers the parameter mapping only; it is not a hash of the input pack. The chunked runner writes intermediate fragments and combines them into a single output. The output is written under the local ignored `out/delhi/` directory.

## A7: parameter robustness runs

The robustness runner evaluates the Cartesian product of `radius_variants_m` and `pair_distance_variants_m`. It reuses A2 assignments for each radius across pair windows and reuses A3 distortion results for each pair window across radii. Each variant receives its own C1 output and parameter hash, with a summary containing row counts and non-null VLM coverage.

The Delhi configuration has three radii (50, 100, and 150 m) and three pair windows (80–100, 80–120, and 80–160 m), for nine variants. The original 10–60 m interval yielded no eligible point pairs on the supplied Delhi VLM grid: the minimum nearest-neighbor distance among distinct points is about 81 m, and the median is about 83.8 m. The wider windows match the observed sampling spacing; a 5,500-building citywide sample yielded at least three pairs for 2.35%, 12.82%, and 16.84% of buildings in the respective windows. Full-city counts were 41,296, 238,115, and 311,017 buildings. These counts are the same across radii because the A3 pair calculation is independent of the A2 radius. Robustness variants are sensitivity runs, not independent observations or probabilistic confidence intervals.

## Parameters used by the Delhi run

| Parameter | Delhi value | Role |
|---|---:|---|
| `utm_epsg` | 32643 | Projected CRS for metric calculations |
| `radius_m` | 100 | A2 centroid search radius |
| `min_points` | 3 | Minimum observations for non-null A2 estimates |
| `pair_min_m`, `pair_max_m` | 80, 120 | Inclusive A3 pair-distance bounds for the Delhi VLM grid |
| `footprint_buffer_m` | 20 | A3 footprint expansion for pair membership |
| `horizon_years` | 10 | Scenario multiplier for cumulative distortion |
| `class_edges_ratio` | `[1000, 500]` | Denominator thresholds for `watch` and `inspect` |
| `radius_variants_m` | `[50, 100, 150]` | A7 A2 sensitivity variants |
| `pair_distance_variants_m` | `[[80, 100], [80, 120], [80, 160]]` | A7 A3 sensitivity variants |

## Interpretation limits

- A2 summarizes nearby radar observations at a building centroid; it does not measure motion of the building structure itself.
- `vlm_iqr_mm_yr` describes the spread of selected point rates. It is not a confidence interval or a complete uncertainty model.
- A3 measures spatial differences among nearby point rates around a footprint. Sparse or uneven point coverage can affect the estimate; fewer than three eligible pairs produce null distortion fields.
- Multiplying by `horizon_years` is a linear scenario assumption, not a prediction that rates remain constant.
- The `beta_class` labels are rule-based indicator bands. They do not establish structural damage, collapse probability, or causation.
- `vt_risk_insar` is nullable and is only populated when a joinable building risk value is available in C0. The current candidate's VT risk file has no joinable `bldg_id` values, so current exports leave this field null.
- The full-city Delhi run is internal validation only. The pack and its derived outputs must remain off the public branch while the ward-source licence is unresolved.

## Verification snapshot

The A3 worked example is covered by `engine/tests/test_distortion.py`. The full local test suite and Ruff passed before this parameter correction; they were not rerun for it. The corrected full-city internal run used engine revision `f3af18a`, processed 1,883,862 buildings in 744.9 seconds at chunk size 5,000, and had 1,055,505 non-null VLM estimates (56.03%). The C1 output has 238,115 buildings with at least three eligible pairs; beta fields are non-null exactly for those rows. Row count, unique IDs, C1 metadata, sparse/null consistency, and parameter-hash consistency were checked. The output is not published because the input pack's ward-source licence is unresolved.
