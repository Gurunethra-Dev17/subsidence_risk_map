import { useEffect, useState } from 'react'
import { Download, Printer } from 'lucide-react'
import { getDataService, isSyntheticDataset } from '../api/service'
import type { Ward } from '../api/service'
import type { components } from '../../types/openapi'
import { config } from '../config'
import { flagLabels, rankRange, scoreBand } from '../wardMetrics'

type Api = components['schemas']
type Pdf = { status: 'loading' | 'fallback' } | { status: 'ready'; url: string }
const metric = (value: number | null | undefined, unit = '') =>
  value == null ? 'Unavailable' : value.toLocaleString('en-IN', { maximumSignificantDigits: 6 }) + unit

export default function InspectionBrief({ ward, meta }: {
  ward: Ward
  meta?: Api['MetaResponse']
}) {
  const [pdf, setPdf] = useState<Pdf>({ status: config.mock ? 'fallback' : 'loading' })
  const [cells, setCells] = useState<Api['CellProperties'][] | 'unavailable' | null>(null)
  const range = rankRange(ward)
  const priority = scoreBand(ward.status, ward.score)

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | undefined
    void getDataService().then(async (service) => {
      const cellsRequest = service.getWardCells(ward.ward_id, controller.signal).then((collection) => {
        if (!controller.signal.aborted) setCells(collection.features.map((feature) => feature.properties)
          .filter((cell) => cell.suppressed === false && cell.cell_rank_in_ward != null)
          .sort((a, b) => (a.cell_rank_in_ward ?? 0) - (b.cell_rank_in_ward ?? 0)))
      }).catch(() => { if (!controller.signal.aborted) setCells('unavailable') })
      if (config.mock) { await cellsRequest; return }
      try {
        const blob = await service.getWardBrief(ward.ward_id, controller.signal)
        if (controller.signal.aborted) return
        if (!blob.size || await blob.slice(0, 5).text() !== '%PDF-') {
          setPdf({ status: 'fallback' })
          return
        }
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setPdf({ status: 'ready', url: objectUrl })
      } catch {
        if (!controller.signal.aborted) setPdf({ status: 'fallback' })
      }
      await cellsRequest
    }).catch(() => {
      if (!controller.signal.aborted) { setPdf({ status: 'fallback' }); setCells('unavailable') }
    })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [ward.ward_id])

  return (
    <section className="panel brief-view" aria-label="Ward inspection brief">
      <div className="brief-toolbar">
        <span role="status">{config.mock ? 'Synthetic mock · print preview' : pdf.status === 'ready' ? 'API PDF available' : pdf.status === 'loading' ? 'Checking for API PDF…' : 'API PDF unavailable · browser print fallback'}</span>
        {pdf.status === 'ready' && <a className="primary-button" href={pdf.url} download={`ward-${ward.ward_id}-inspection.pdf`}><Download size={15} /> Download PDF</a>}
        <button type="button" className="secondary-button" disabled={cells === null} onClick={() => window.print()}><Printer size={15} /> Print / Save as PDF</button>
      </div>
      {pdf.status === 'ready' && <details className="pdf-preview"><summary>Preview API PDF</summary>
        <object data={pdf.url} type="application/pdf" aria-label="Ward inspection brief PDF"><a href={pdf.url} target="_blank" rel="noreferrer">Open API PDF</a></object>
      </details>}
      <article className="brief-paper">
        <header>
          <span className="brief-kicker">Subsidence Risk Map · Ward screening</span>
          <h2>{ward.ward_name}</h2>
          <p>{ward.ward_id} · {meta?.city ?? 'City unavailable'} · {isSyntheticDataset(meta) ? 'Synthetic demonstration' : 'Public ward summary'}</p>
        </header>
        <dl className="brief-metrics">
          <div><dt>Priority band</dt><dd>{priority.label}</dd></div>
          <div><dt>Inspection Index</dt><dd>{metric(ward.score, '/100')}</dd></div>
          <div><dt>Rank · sensitivity range</dt><dd>{metric(ward.rank)} · {range?.label ?? 'Unavailable'}</dd></div>
        </dl>
        <h3>Indicators and evidence</h3>
        <dl className="brief-indicators">
          <div><dt>Share sinking at least 4 mm/yr</dt><dd>{metric(ward.share_sinking_gt4 == null ? null : ward.share_sinking_gt4 * 100, '%')}</dd></div>
          <div><dt>90th percentile distortion</dt><dd>{ward.beta_p90_ratio_horizon ?? metric(ward.beta_p90_horizon)}</dd></div>
          <div><dt>Building exposure</dt><dd>{metric(ward.n_buildings)}</dd></div>
          <div><dt>Groundwater extraction</dt><dd>{metric(ward.gw_stage_pct, '%')}</dd></div>
          <div><dt>Median vertical motion</dt><dd>{metric(ward.vlm_median_mm_yr, ' mm/yr')}</dd></div>
        </dl>
        <h3>Coverage and uncertainty</h3>
        <p>{metric(ward.coverage_pct, '%')} coverage ({metric(ward.n_buildings_with_data)} of {metric(ward.n_buildings)} buildings).
          {range ? ' The range shows the 5th–95th percentile of rank as indicator weights vary.' : ' A rank sensitivity range is unavailable.'}
          {ward.status === 'insufficient_data' && ' Coverage is insufficient for a ward score or rank.'}</p>
        <p>{ward.flags.length ? ward.flags.map((flag) => flagLabels[flag] ?? flag).join(' · ') : 'No data-quality flags reported.'}</p>
        <h3>Cells in suggested inspection order</h3>
        {Array.isArray(cells) && cells.length > 0 ? <table><thead><tr><th>Rank</th><th>Cell</th><th>Index</th></tr></thead>
          <tbody>{cells.map((cell) => <tr key={cell.cell_id}><td>{cell.cell_rank_in_ward}</td><th scope="row">{cell.cell_id}</th><td>{metric(cell.cell_score, '/100')}</td></tr>)}</tbody>
        </table> : <p>{cells === null ? 'Loading cell evidence…' : cells === 'unavailable' ? 'Cell evidence unavailable.' : 'No publishable ranked cells in this ward.'}</p>}
        <footer>
          <strong>Inspection use</strong>
          <p>This brief ranks areas for inspection. It does not certify any building. Projections are scenarios under constant rates.</p>
          <p>Data vintage {meta?.data_vintage ?? 'unavailable'} · Engine {meta?.engine_version ?? 'unavailable'} · C2 {meta?.contract_versions.C2 ?? 'unavailable'}</p>
        </footer>
      </article>
    </section>
  )
}
