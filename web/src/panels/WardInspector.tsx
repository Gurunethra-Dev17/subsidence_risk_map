import { lazy, Suspense, useEffect, useState } from 'react'
import { ChevronDown, CircleHelp, FileText, ScanLine, X } from 'lucide-react'
import { getDataService } from '../api/service'
import type { Ward } from '../api/service'
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
      <h4 id="indicator-heading">Component indicators</h4>
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
      <h4 id="quality-heading">Coverage &amp; uncertainty</h4>
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
      <Indicators ward={ward} />
      <Quality ward={ward} rankedCount={rankedCount} />
      <section className="inspector-section" aria-labelledby="histogram-heading">
        <div className="analytics-heading">
          <h4 id="histogram-heading">Building distortion distribution</h4>
          <Explanation label="building distortion distribution" text="The distribution counts buildings in angular distortion bins over the projection horizon. Published counts are aggregated at ward level." />
        </div>
        <Suspense fallback={<p className="muted-copy" role="status">Loading distribution…</p>}>
          <DistortionHistogram histogram={ward.histogram} />
        </Suspense>
      </section>
    </>
  )
}

type WardResult = { ward: Ward; error?: never } | { ward?: never; error: string }

function SelectedWard({ id, rankedCount, onBrief }: { id: string; rankedCount?: number; onBrief: (ward: Ward) => void }) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<WardResult | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getDataService().then((service) => service.getWard(id, controller.signal)).then(
      (ward) => { if (!controller.signal.aborted) setResult({ ward }) },
      (error: unknown) => {
        if (!controller.signal.aborted) setResult({ error: error instanceof Error ? error.message : 'An unexpected error occurred.' })
      },
    )
    return () => controller.abort()
  }, [attempt, id])

  if (!result) return <div className="panel-state" role="status">Loading ward details…</div>
  if (result.ward) {
    const ward = result.ward
    return <>
      <div className="inspect-brief-action"><button type="button" className="secondary-button" onClick={() => onBrief(ward)}><FileText size={16} /> Inspection brief</button></div>
      <WardAnalytics ward={ward} rankedCount={rankedCount} />
    </>
  }
  return <div className="panel-state" role="alert">Unable to load ward details. {result.error}
    <button className="text-button" type="button" onClick={() => { setResult(null); setAttempt((count) => count + 1) }}>Try again</button>
  </div>
}

export default function WardInspector({ id, name, rankedCount, onClose, collapsed, onCollapse, onBrief }: {
  id: string | null
  name?: string
  rankedCount?: number
  onClose: () => void
  collapsed: boolean
  onCollapse: () => void
  onBrief: (ward: Ward) => void
}) {
  return (
    <section className="panel inspector" id="inspector" aria-labelledby="inspector-title" tabIndex={-1}>
      <div className="panel-heading">
        <span className="section-icon"><ScanLine size={18} /></span>
        <div><h2 id="inspector-title">Ward inspector</h2>{id && <p className="inspector-name">{name ?? id}</p>}</div>
        <div className="inspector-actions">
          {id && <button type="button" className="icon-button" aria-label="Clear ward selection" onClick={onClose}><X size={17} /></button>}
          <button type="button" className="icon-button" aria-expanded={!collapsed} aria-controls="inspector-content" aria-label={collapsed ? 'Expand inspector' : 'Collapse inspector'} onClick={onCollapse}><ChevronDown size={17} /></button>
        </div>
      </div>
      <div id="inspector-content" hidden={collapsed}>
        {id ? <SelectedWard key={id} id={id} rankedCount={rankedCount} onBrief={onBrief} />
          : <p className="inspector-empty">Select a ward on the map or in the rankings to see its indicators and data quality.</p>}
      </div>
    </section>
  )
}
