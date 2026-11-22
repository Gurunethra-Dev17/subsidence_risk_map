import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from 'recharts'
import type { components } from '../../types/openapi'
import { isSyntheticDataset } from '../api/service'
import ChartFrame from '../panels/ChartFrame'

type Api = components['schemas']
const indicators = [
  { id: 'i1', name: 'Sinking share', description: 'Share of buildings with radar data sinking at least 4 mm per year.' },
  { id: 'i2', name: 'Projected distortion', description: 'Ward 90th percentile of cumulative angular distortion under constant rates.' },
  { id: 'i3', name: 'Exposure', description: 'Total building count within the ward boundary.' },
  { id: 'i4', name: 'Groundwater extraction', description: 'Area-weighted stage of extraction from groundwater assessment units.' },
] as const

const numeric = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const valueText = (value: unknown) => numeric(value) ? value.toLocaleString('en-IN', { maximumFractionDigits: 3 }) : 'Unavailable'

function MetricChart({ rows, label, min = 0 }: { rows: { name: string; value: number }[]; label: string; min?: number }) {
  return <figure className="evidence-chart" aria-label={label}>
    <ChartFrame className="evidence-chart-canvas">
      {(size) => (
        <BarChart {...size} accessibilityLayer data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 3" />
          <XAxis dataKey="name" tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
          <YAxis allowDecimals={min < 0} domain={min < 0 ? [-1, 1] : [0, 'auto']} width={35} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
          <Tooltip formatter={(value) => [value, label]} />
          <Bar name={label} dataKey="value" fill="var(--chart-series)" maxBarSize={56} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      )}
    </ChartFrame>
    <figcaption>{rows.map((row) => `${row.name} ${valueText(row.value)}`).join(' · ')}</figcaption>
  </figure>
}

function EngineMethod() {
  return <section className="evidence-section">
    <h2>From radar observations to building indicators</h2>
    <p>Vertical land motion (VLM) is reported in millimetres per year. Negative rates mean sinking and positive rates mean rising. The loader multiplies inputs in centimetres per year by 10 and clips observations to the configured city bounds. The engine calculates distances in metres in projected UTM coordinates (EPSG:32643 for Delhi).</p>
    <h3>Motion near a building centroid</h3>
    <p>The Delhi defaults use observations within 100 m of the centroid. With fewer than three points, the estimate and interquartile range are unavailable and the record is marked sparse. Otherwise, the engine takes the weighted median of the rates, with weight <var>wᵢ</var> = 1/<var>dᵢ</var> for distance <var>dᵢ</var>. Observations exactly at the centroid receive equal weight and supply the estimate on their own.</p>
    <p>The weighted interquartile range is the 75th minus the 25th percentile of the selected rates. The engine computes weighted percentiles by linear interpolation between midpoint plotting positions. The spread quantifies variation among nearby observations. Structural motion and statistical confidence require separate evidence.</p>
    <h3>Angular distortion scenario</h3>
    <p>The engine buffers each footprint by 20 m and forms distinct pairs at distances of 10–60 m inclusive, with at least one observation inside or on the buffered footprint. Each pair contributes an annual angular rate <var>βᵢⱼ</var> = |<var>vᵢ</var> − <var>vⱼ</var>| × 10<sup>−3</sup> / <var>dᵢⱼ</var>, where <var>v</var> is in mm/yr and <var>dᵢⱼ</var> is in metres.</p>
    <p>With at least three pairs, the building rate is the 90th percentile of the pair rates. The horizon distortion is that rate multiplied by the scenario length in years (10 by default for Delhi), yielding a dimensionless value. The display rounds to the nearest reciprocal 1/N and uses 1/inf for zero. Fewer than three pairs leave the rate, horizon distortion, ratio, and class unavailable.</p>
    <ul>
      <li><strong>Low</strong> below 0.001 (1/1000).</li>
      <li><strong>Watch</strong> at 0.001 and above, below 0.002.</li>
      <li><strong>Inspect</strong> at 0.002 (1/500) and above.</li>
    </ul>
    <p>In the engine’s worked example, −10 and −6 mm/yr over 20 m give a pair rate of 0.0002 per year. A building rate of that magnitude gives 0.002 over 10 years, displayed as 1/500 and classified Inspect.</p>
    <p>Sparse or uneven radar coverage can affect the estimate. The horizon assumes constant rates and the classes are screening bands, with no implied probability of damage or failure. Delhi’s sensitivity runs cross 50, 100, and 150 m centroid radii with 10–40, 10–60, and 20–60 m pair windows. The nine variants test parameter sensitivity.</p>
    <p><a href="https://github.com/Gurunethra-Dev17/subsidence_risk_map/blob/4883e08/engine/METHOD.md">Engine method and Delhi defaults</a></p>
  </section>
}

function Methodology({ meta }: { meta?: Api['MetaResponse'] }) {
  return <>
    <section className="evidence-section">
      <h2>How the Inspection Index works</h2>
      <p>Each indicator is percentile-ranked among eligible wards in the city. The index is the weighted sum of those percentiles, scaled from 0 to 100. If groundwater is unavailable, its weight is redistributed across the remaining indicators.</p>
      <div className="method-indicators">
        {indicators.map(({ id, name, description }) => {
          const weight = meta?.weights[id]
          return <div key={id}><strong>{name}</strong><p>{description}</p>
            <small>{weight == null ? 'Weight unavailable' : `${valueText(weight * 100)}% base weight`}</small>
          </div>
        })}
      </div>
      <p>Median vertical motion adds context. Negative values indicate sinking. A ward with insufficient coverage receives no score or rank. Small cell samples are suppressed.</p>
    </section>
    <EngineMethod />
    <section className="evidence-section">
      <h2>Sources and uncertainty</h2>
      <dl className="method-sources">
        <div><dt>Satellite ground motion</dt><dd>The project uses the Virginia Tech Indian megacities dataset as a baseline for radar-derived vertical land motion.</dd></div>
        <div><dt>Footprints and boundaries</dt><dd>Building footprints provide exposure and ward boundaries define the aggregation units. The project plan identifies Overture footprints and Delhi’s 2022 delimitation as candidate inputs.</dd></div>
        <div><dt>Groundwater</dt><dd>Central Ground Water Board assessments provide extraction-stage context where joinable to wards.</dd></div>
        <div><dt>Rank sensitivity</dt><dd>The 5th–95th percentile range shows how a ward’s rank changes when indicator weights vary. Coverage reports the share of buildings with enough data for the analysis.</dd></div>
      </dl>
      <p className="evidence-callout">The index prioritises inspections. A high score does not establish structural failure or diagnose building safety. Distortion projections are scenarios under constant rates.</p>
      <p className="muted-copy">Dataset vintage {meta?.data_vintage ?? 'unavailable'} · Engine {meta?.engine_version ?? 'unavailable'}</p>
    </section>
  </>
}

function Validation({ data }: { data: Api['ValidationSummary'] }) {
  const { vt_consistency: comparison, collapse_check: incidents, robustness, fresh_data_check: fresh } = data
  const matrix = comparison.confusion_matrix
  const showMatrix = comparison.labels.length > 0 && matrix.length === comparison.labels.length &&
    matrix.every((row) => row.length === comparison.labels.length && row.every(numeric))
  const radii = Array.isArray(robustness.radius_variants) ? robustness.radius_variants.flatMap((item: unknown) => {
    if (!item || typeof item !== 'object') return []
    const row = item as Record<string, unknown>
    return numeric(row.radius_m) && numeric(row.kendall_tau_vs_baseline)
      ? [{ name: row.radius_m + ' m', value: row.kendall_tau_vs_baseline }] : []
  }) : []
  return <>
    <section className="evidence-section">
      <h2>Collapse catalogue coverage</h2>
      <MetricChart label="Incidents" rows={[
        { name: 'Full catalogue', value: incidents.n_incidents_total }, { name: 'In city', value: incidents.n_in_city },
      ]} />
      <p>{incidents.note}</p>
    </section>
    <section className="evidence-section">
      <h2>Consistency with published categories</h2>
      <p>Buildings compared <strong>{valueText(comparison.n_buildings)}</strong> · Spearman ρ <strong>{valueText(comparison.spearman_rho)}</strong></p>
      <p>{comparison.note}</p>
      {showMatrix ? <div className="evidence-table"><table>
        <caption>Published-category comparison counts</caption>
        <thead><tr><th scope="col">Category</th>{comparison.labels.map((name) => <th scope="col" key={name}>{name}</th>)}</tr></thead>
        <tbody>{matrix.map((row, i) => <tr key={i}><th scope="row">{comparison.labels[i]}</th>{row.map((count, j) => <td key={j} data-has-value={Boolean(count)}>{valueText(count)}</td>)}</tr>)}</tbody>
      </table></div> : <p className="muted-copy">Comparison matrix unavailable.</p>}
    </section>
    <section className="evidence-section">
      <h2>Robustness and fresh data</h2>
      <p>Weight sensitivity mean Kendall τ <strong>{valueText(robustness.kendall_tau_weights_mean)}</strong> · Median rank-range width <strong>{valueText(robustness.rank_range_width_median)}</strong></p>
      {radii.length ? <MetricChart rows={radii} label="Kendall τ" min={-1} /> : <p className="muted-copy">Radius sensitivity scores unavailable.</p>}
      <p>Fresh-data check <strong className="capitalize">{fresh.status.replaceAll('_', ' ')}</strong>. {fresh.note}</p>
      <h3>Published hotspot checks</h3>
      {data.hotspot_check.length ? <ul className="hotspot-list">{data.hotspot_check.map((hotspot, i) => <li key={i}>
        <strong>{typeof hotspot.name === 'string' ? hotspot.name : 'Hotspot'}</strong>
        {typeof hotspot.source === 'string' && <span>{hotspot.source}</span>}
        <span>Rank {valueText(hotspot.rank)} · Percentile {valueText(hotspot.percentile)}</span>
      </li>)}</ul> : <p className="muted-copy">Hotspot checks unavailable.</p>}
    </section>
  </>
}

export default function Evidence({ page, meta, validation, validationError, retry }: {
  page: 'methods' | 'validation'
  meta?: Api['MetaResponse']
  validation?: Api['ValidationSummary']
  validationError?: string
  retry: () => void
}) {
  return <div className="evidence-page">
    <header><h1>{page === 'methods' ? 'Methodology' : 'Validation'}</h1>
      <p>{isSyntheticDataset(meta) ? 'Synthetic demo data · counts and settings demonstrate the workflow.' : 'Contract-backed city evidence and coverage.'}</p>
    </header>
    {page === 'methods' ? <Methodology meta={meta} /> : validation ? <Validation data={validation} /> : validationError
      ? <section className="evidence-section" role="alert"><p>Validation unavailable. {validationError}</p><button type="button" className="text-button" onClick={retry}>Try again</button></section>
      : <p role="status">Loading validation evidence…</p>}
  </div>
}
