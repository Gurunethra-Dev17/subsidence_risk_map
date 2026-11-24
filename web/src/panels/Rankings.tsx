import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ListOrdered, Search } from 'lucide-react'
import type { Ward } from '../api/service'
import { flagLabels, insufficientBand, rankRange, scoreBand, scoreBands, showNumber, unavailableBand } from '../wardMetrics'

type Field = 'rank' | 'ward_name' | 'score' | 'coverage_pct'
const columns: { field: Field; label: string }[] = [
  { field: 'rank', label: 'Rank' },
  { field: 'ward_name', label: 'Ward' },
  { field: 'score', label: 'Score' },
  { field: 'coverage_pct', label: 'Coverage' },
]

export default function Rankings({ wards, selectedId, onSelect, collapsed, onCollapse }: {
  wards: Ward[]
  selectedId: string | null
  onSelect: (id: string, origin: 'ranking') => void
  collapsed: boolean
  onCollapse: () => void
}) {
  const [query, setQuery] = useState('')
  const [band, setBand] = useState('all')
  const [sort, setSort] = useState<{ field: Field; descending: boolean }>({ field: 'rank', descending: false })
  const viewport = useRef<HTMLDivElement>(null)
  const activeRow = useRef<HTMLTableRowElement>(null)

  const visible = useMemo(() => {
    const search = query.trim().toLocaleLowerCase('en-IN')
    return wards.filter((ward) =>
      (band === 'all' || scoreBand(ward.status, ward.score).id === band) &&
      (ward.ward_name.toLocaleLowerCase('en-IN').includes(search) || ward.ward_id.toLocaleLowerCase('en-IN').includes(search)),
    ).sort((a, b) => {
      const left = a[sort.field]
      const right = b[sort.field]
      if (left == null) return right == null ? a.ward_name.localeCompare(b.ward_name) : 1
      if (right == null) return -1
      const order = typeof left === 'number' && typeof right === 'number'
        ? left - right : String(left).localeCompare(String(right), 'en-IN')
      return (sort.descending ? -order : order) || a.ward_name.localeCompare(b.ward_name, 'en-IN')
    })
  }, [band, query, sort, wards])

  useEffect(() => {
    const scroller = viewport.current
    const row = activeRow.current
    if (!scroller || !row) return
    const bounds = scroller.getBoundingClientRect()
    const item = row.getBoundingClientRect()
    const top = bounds.top + (scroller.querySelector('thead')?.getBoundingClientRect().height ?? 0)
    if (item.top < top) scroller.scrollTop -= top - item.top
    else if (item.bottom > bounds.bottom) scroller.scrollTop += item.bottom - bounds.bottom
  }, [selectedId, visible])

  const clear = () => { setQuery(''); setBand('all') }
  const hiddenSelection = selectedId && wards.some((ward) => ward.ward_id === selectedId)
    && !visible.some((ward) => ward.ward_id === selectedId)

  return (
    <section className="panel ranking-panel" id="rankings" aria-labelledby="ranking-title">
      <div className="panel-heading">
        <span className="section-icon"><ListOrdered size={18} /></span>
        <h2 id="ranking-title">Ward rankings</h2>
        <span className="panel-count" aria-live="polite">{visible.length} of {wards.length}</span>
        <button type="button" className="icon-button" aria-controls="ranking-content" aria-expanded={!collapsed}
          aria-label={collapsed ? 'Expand rankings' : 'Collapse rankings'} onClick={onCollapse}><ChevronDown size={17} /></button>
      </div>
      <div id="ranking-content" hidden={collapsed}>
      <div className="ranking-tools">
        <label className="search-field"><Search size={17} />
          <input type="search" placeholder="Search ward" aria-label="Search wards" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <label className="filter-field">
          <span className="sr-only">Filter by priority band</span>
          <select value={band} onChange={(event) => setBand(event.target.value)}>
            <option value="all">All priorities</option>
            {[...scoreBands, insufficientBand, unavailableBand].map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
      </div>
      {hiddenSelection && <p className="ranking-notice">The selected ward is hidden by filters. <button type="button" className="text-button" onClick={clear}>Show all</button></p>}
      {visible.length > 0 ? (
        <div className="table-viewport" ref={viewport}>
          <table>
            <caption className="sr-only">Ward rankings with Inspection Index scores, rank ranges and data coverage</caption>
            <thead><tr>
              {columns.map(({ field, label }) => {
                const active = sort.field === field
                return <th key={field} scope="col" aria-sort={active ? (sort.descending ? 'descending' : 'ascending') : undefined}>
                  <button type="button" onClick={() => setSort({ field, descending: active ? !sort.descending : field === 'score' || field === 'coverage_pct' })}>
                    {label}{active && (sort.descending ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
                  </button>
                </th>
              })}
            </tr></thead>
            <tbody>
              {visible.map((ward) => {
                const selected = ward.ward_id === selectedId
                const uncertainty = rankRange(ward)
                const priority = scoreBand(ward.status, ward.score)
                const flags = ward.flags.map((flag) => flagLabels[flag] ?? flag)
                return (
                  <tr key={ward.ward_id} ref={selected ? activeRow : undefined} data-selected={selected}
                    onClick={() => onSelect(ward.ward_id, 'ranking')}>
                    <td><strong>{ward.rank ?? '—'}</strong>
                      {uncertainty && <small title="5th–95th percentile sensitivity range"><span className="sr-only">Sensitivity range </span>{uncertainty.label}</small>}
                    </td>
                    <th scope="row">
                      <button className="ward-select" type="button" aria-pressed={selected} onClick={(event) => {
                        event.stopPropagation()
                        onSelect(ward.ward_id, 'ranking')
                      }}>{ward.ward_name}</button>
                      <small title={flags.join(', ') || undefined}>
                        {ward.status === 'insufficient_data' ? 'Insufficient data' : flags.length ? `${flags.length} quality ${flags.length === 1 ? 'flag' : 'flags'}` : 'Ranked'}
                      </small>
                    </th>
                    <td><span className="score-cell" title={priority.label}><i className={priority.id === 'insufficient' ? 'swatch hatch-swatch' : 'swatch'} style={{ backgroundColor: priority.color }} /><span>{showNumber(ward.score)}</span></span></td>
                    <td>{showNumber(ward.coverage_pct)}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="panel-state" role="status">
          <p>{wards.length ? 'No wards match your search and filter.' : 'No ward summaries are available.'}</p>
          {wards.length > 0 && <button type="button" className="text-button" onClick={clear}>Clear filters</button>}
        </div>
      )}
      <footer className="ranking-foot">Select a ward to focus its boundary and review the indicators.</footer>
      </div>
    </section>
  )
}
