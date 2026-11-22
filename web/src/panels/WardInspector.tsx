import { lazy, Suspense } from 'react'
import { CircleHelp, ScanLine } from 'lucide-react'
import type { Ward } from '../api/service'
import { overlaySettings } from '../map/overlayLayers'
import type { MapFeature } from '../map/overlayLayers'
import { flagLabels, formatNumber, rankRange, scoreBand, showNumber } from '../wardMetrics'

const DistortionHistogram = lazy(() => import('./DistortionHistogram'))

function Explanation({ label, text }: { label: string; text: string }) {
  return (
    <details className="explanation">
      <summary aria-label={`About ${label}`} title={`About ${label}`}><CircleHelp size={15} /></summary>
      <div className="explanation-popover">{text}</div>
    </details>
  )
}

function Indicators({ ward }: { ward: Ward }) {
  const share = ward.share_sinking_gt4
  const ratio = ward.beta_p90_ratio_horizon
  const beta = ward.beta_p90_horizon
  const values = [
    { label: 'Share sinking ≥4 mm/yr', value: share == null ? null : `${formatNumber(share * 100)}%`, help: 'Share of buildings with radar-derived motion sinking at least 4 mm per year. This is indicator I1.' },
    { label: '90th percentile distortion', value: ratio ?? (beta == null ? null : beta.toPrecision(4)), help: 'The upper-end ward value for projected cumulative angular distortion under constant ground-motion rates. The displayed ratio is dimensionless. This is indicator I2.' },
    { label: 'Building exposure', value: formatNumber(ward.n_buildings), help: 'Total building count in the ward. This is the exposure indicator I3.' },
    { label: 'Groundwater extraction', value: ward.gw_stage_pct == null ? null : `${formatNumber(ward.gw_stage_pct)}%`, help: 'Area-weighted stage of groundwater extraction. If unavailable, the index redistributes the groundwater weight. This is indicator I4.' },
    { label: 'Median vertical motion', value: ward.vlm_median_mm_yr == null ? null : `${formatNumber(ward.vlm_median_mm_yr)} mm/yr`, help: 'Median vertical land motion from building summaries. Negative values indicate sinking.' },
  ]
  return (
    <section className="inspector-section" aria-labelledby="indicator-heading">
      <h3 id="indicator-heading">Component indicators</h3>
      <dl className="indicator-list">
        {values.map(({ label, value, help }) => (
          <div key={label}><dt>{label}<Explanation label={label} text={help} /></dt>
            <dd className={value == null ? 'unavailable' : undefined}>{value ?? 'Unavailable'}</dd>
          </div>
        ))}
        {ward.gw_category && <div><dt>Groundwater category</dt><dd className="capitalize">{ward.gw_category}</dd></div>}
      </dl>
    </section>
  )
}

function Quality({ ward, rankedCount }: { ward: Ward; rankedCount?: number }) {
  const range = rankRange(ward)
  const maxRank = Math.max(1, rankedCount ?? 0, range?.high ?? 0, ward.rank ?? 0)
  const scale = (rank: number) => maxRank > 1 ? (rank - 1) / (maxRank - 1) * 100 : 50
  return (
    <section className="inspector-section" aria-labelledby="quality-heading">
      <h3 id="quality-heading">Coverage &amp; uncertainty</h3>
      <div className="quality-label"><span>Buildings with data</span><strong>{formatNumber(ward.n_buildings_with_data)} / {formatNumber(ward.n_buildings)}</strong></div>
      <progress aria-label="Building data coverage" value={ward.coverage_pct} max={100} />
      {range ? (
        <div className="rank-spread">
          <div className="quality-label"><span>Rank sensitivity range</span><strong>{range.label}</strong></div>
          <div aria-hidden="true" className="range-track">
            <span className="range-span" style={{ left: scale(range.low) + '%', width: (scale(range.high) - scale(range.low)) + '%' }} />
            {ward.rank != null && <i style={{ left: scale(ward.rank) + '%' }} />}
          </div>
          {maxRank > 1 && <div aria-hidden="true" className="range-labels"><span>#1</span><span>#{maxRank}</span></div>}
          <p className="muted-copy">5th–95th percentile of ranks when indicator weights vary.</p>
        </div>
      ) : <p className="muted-copy">Rank sensitivity range unavailable.</p>}
      {ward.flags.length > 0 ? <ul className="quality-flags" aria-label="Data quality flags">
        {ward.flags.map((flag) => <li key={flag}>{flagLabels[flag] ?? flag}</li>)}
      </ul> : <p className="muted-copy">No data-quality flags reported.</p>}
    </section>
  )
}

function WardAnalytics({ ward, rankedCount }: { ward: Ward; rankedCount?: number }) {
  const priority = scoreBand(ward.status, ward.score)
  return (
    <>
      <div className="inspector-hero">
        <span className="priority-label"><i className={priority.id === 'insufficient' ? 'swatch hatch-swatch' : 'swatch'} style={{ backgroundColor: priority.color }} />{priority.label}</span>
        <dl className="inspector-metrics">
          <div><dt>Inspection Index</dt><dd>{showNumber(ward.score)}{ward.score != null && <small>/100</small>}</dd></div>
          <div><dt>City rank</dt><dd>{ward.rank == null ? '—' : '#' + formatNumber(ward.rank)}</dd></div>
          <div><dt>Coverage</dt><dd>{formatNumber(ward.coverage_pct)}<small>%</small></dd></div>
        </dl>
        {ward.status === 'insufficient_data' && <p className="insufficient-message">Available coverage is insufficient to assign a score or rank.</p>}
      </div>
      <div className="analytics-grid">
        <Indicators ward={ward} />
        <Quality ward={ward} rankedCount={rankedCount} />
      </div>
      <section className="inspector-section" aria-labelledby="histogram-heading">
        <div className="analytics-heading">
          <h3 id="histogram-heading">Building distortion distribution</h3>
          <Explanation label="building distortion distribution" text="The distribution counts buildings in angular distortion bins over the projection horizon. Published counts are aggregated at ward level." />
        </div>
        <Suspense fallback={<p className="muted-copy" role="status">Loading distribution…</p>}>
          <DistortionHistogram histogram={ward.histogram} />
        </Suspense>
      </section>
    </>
  )
}

export default function WardInspector({ ward, rankedCount, feature }: {
  ward: Ward
  rankedCount?: number
  feature: MapFeature | null
}) {
  return (
    <section className="panel inspector" id="inspector" aria-labelledby="inspector-title">
      <div className="panel-heading">
        <span className="section-icon"><ScanLine size={18} /></span>
        <div><h2 id="inspector-title">{ward.ward_name}</h2><p className="muted-copy">{ward.ward_id}</p></div>
      </div>
      <WardAnalytics ward={ward} rankedCount={rankedCount} />
      <section className="inspector-section" aria-labelledby="feature-heading">
        <h3 id="feature-heading">Map feature evidence</h3>
        {feature ? <>
          <p><strong>{overlaySettings[feature.layer].label} · {feature.id}</strong></p>
          <dl className="indicator-list">{feature.fields.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        </> : <p className="muted-copy">Select a feature in an available map layer to inspect its details here.</p>}
      </section>
      <section className="inspector-section" aria-labelledby="inspector-limitations">
        <h3 id="inspector-limitations">Scientific limitations</h3>
        <p className="muted-copy">The index prioritises field inspections. Building safety requires separate evidence. Distortion estimates assume constant ground-motion rates over the scenario horizon.</p>
      </section>
    </section>
  )
}
