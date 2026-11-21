import { ChartNoAxesColumnIncreasing, ClipboardCheck, MapPin } from 'lucide-react'
import type { components } from '../../types/openapi'

type Api = components['schemas']

export function RankingPreview({ page }: { page: Api['WardPage'] }) {
  return (
    <section className="panel" id="rankings" aria-labelledby="ranking-title">
      <div className="panel-heading">
        <div className="section-icon"><ChartNoAxesColumnIncreasing size={19} /></div>
        <div><h2 id="ranking-title">Ward rankings</h2><p>Preview of ward scores</p></div>
      </div>
      {page.items.length > 0 ? (
        <ul className="rank-list">
          {page.items.map((ward) => (
            <li key={ward.ward_id}>
              <span className="rank-number" aria-label={ward.rank == null ? 'Unranked' : `Rank ${ward.rank}`}>{ward.rank ?? '–'}</span>
              <span className="ward-name">{ward.ward_name}
                <small>{ward.status === 'ranked' ? 'Ranked' : 'Insufficient data'}</small>
              </span>
              <span className="ward-score">{ward.score == null ? '–' : ward.score.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
            </li>
          ))}
        </ul>
      ) : <p className="panel-copy">No ward summaries are available.</p>}
      {page.total > page.items.length && <p className="panel-copy">Showing {page.items.length} of {page.total} wards.</p>}
    </section>
  )
}

export function WardDetailPlaceholder() {
  return (
    <section className="panel" aria-labelledby="detail-title">
      <div className="panel-heading">
        <div className="section-icon"><MapPin size={19} /></div>
        <div><h2 id="detail-title">Ward detail</h2><p>Indicators and coverage</p></div>
      </div>
      <p className="panel-copy detail-placeholder">Ward details are planned for a future update.</p>
    </section>
  )
}

export function ValidationPreview({ validation }: { validation: Api['ValidationSummary'] }) {
  const status = validation.fresh_data_check.status.replaceAll('_', ' ')
  return (
    <section className="panel validation-panel" id="validation" aria-labelledby="validation-title">
      <div className="panel-heading">
        <div className="section-icon"><ClipboardCheck size={19} /></div>
        <div><h2 id="validation-title">Validation</h2><p>Fresh-data check <strong className="validation-status">{status}</strong></p></div>
      </div>
    </section>
  )
}
