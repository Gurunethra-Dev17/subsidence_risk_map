import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, BookOpen, ChartNoAxesCombined, FlaskConical, Layers3, Map as MapIcon } from 'lucide-react'
import { getDataService } from '../api/service'
import type { DataService, Ward } from '../api/service'
import { config } from '../config'
import Rankings from '../panels/Rankings'
import WardInspector from '../panels/WardInspector'
import AuthorityAccess from '../modes/AuthorityAccess'
import type { AuthoritySession } from '../api/authority'
import { formatNumber, insufficientBand, scoreBands, unavailableBand } from '../wardMetrics'

const MapWorkspace = lazy(() => import('../map/MapWorkspace'))
const Evidence = lazy(() => import('./Evidence'))
const InspectionBrief = lazy(() => import('../panels/InspectionBrief'))

type Resource<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; error: string }
type Selection = { id: string; origin: 'map' | 'ranking' }

function useResource<T>(read: (service: DataService, signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<Resource<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    void getDataService().then((service) => read(service, controller.signal)).then(
      (data) => { if (!controller.signal.aborted) setState({ status: 'ready', data }) },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ status: 'error', error: error instanceof Error ? error.message : 'An unexpected error occurred.' })
        }
      },
    )
    return () => controller.abort()
  }, [attempt, read])
  const retry = () => {
    setState({ status: 'loading' })
    setAttempt((count) => count + 1)
  }
  return { state, retry, attempt }
}

async function listAllWards(service: DataService, signal: AbortSignal) {
  const wards: Ward[] = []
  do {
    const page = await service.listWards({ sort: 'rank', order: 'asc', limit: 500, offset: wards.length }, signal)
    wards.push(...page.items)
    if (wards.length >= page.total || page.items.length === 0) return wards
  } while (!signal.aborted)
  signal.throwIfAborted()
  return wards
}

const loadMeta = (service: DataService, signal: AbortSignal) => service.getMeta(signal)
const loadValidation = (service: DataService, signal: AbortSignal) => service.getValidation(signal)
const loadGeometry = (service: DataService) => service.getMockWardGeometry()

function MapLegend() {
  return (
    <div className="map-legend" aria-label="Ward map legend">
      <strong>Inspection Index</strong>
      <ul>
        {scoreBands.map((band) => <li key={band.id} title={band.label}><i className="swatch" style={{ backgroundColor: band.color }} /><span>{band.range}</span></li>)}
        <li><i className="swatch hatch-swatch" style={{ backgroundColor: insufficientBand.color }} /><span>Insufficient data</span></li>
        <li><i className="swatch" style={{ backgroundColor: unavailableBand.color }} /><span>Score unavailable</span></li>
      </ul>
    </div>
  )
}

function FailedState({ label, error, retry }: { label: string; error: string; retry: () => void }) {
  return <div className="panel-state" role="alert"><strong>{label} unavailable</strong><p>{error}</p>
    <button type="button" className="text-button" onClick={retry}>Try again</button>
  </div>
}

export default function Dashboard() {
  const meta = useResource(loadMeta)
  const wards = useResource(listAllWards)
  const geometry = useResource(loadGeometry)
  const validation = useResource(loadValidation)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [page, setPage] = useState<'map' | 'methods' | 'validation'>('map')
  const [rankingsCollapsed, setRankingsCollapsed] = useState(false)
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false)
  const [brief, setBrief] = useState<Ward | null>(null)
  const [authority, setAuthority] = useState<AuthoritySession | null>(null)
  const [authorityNotice, setAuthorityNotice] = useState('')
  const session = useRef<AuthoritySession | null>(null)
  const signOut = useCallback((notice = '') => {
    session.current?.close()
    session.current = null
    setAuthority(null)
    setAuthorityNotice(notice)
  }, [])
  const signIn = (next: AuthoritySession) => {
    session.current?.close()
    session.current = next
    setAuthority(next)
    setAuthorityNotice('')
  }
  const unauthorized = useCallback(() => signOut('Authority access ended. Restricted data was cleared.'), [signOut])
  useEffect(() => {
    if (!authority) return
    const timer = window.setTimeout(() => signOut('Authority session expired.'), Math.max(0, authority.expiresAt - Date.now()))
    return () => window.clearTimeout(timer)
  }, [authority, signOut])
  useEffect(() => () => session.current?.close(), [])

  const onSelect = useCallback((id: string, origin: Selection['origin']) => {
    setSelection({ id, origin })
    setInspectorCollapsed(false)
    if (window.matchMedia('(max-width: 900px)').matches) {
      document.getElementById('inspector')?.focus()
    }
  }, [])
  const city = meta.state.status === 'ready' ? meta.state.data : undefined
  const entries = wards.state.status === 'ready' ? wards.state.data : undefined
  const mockGeometry = geometry.state.status === 'ready' ? geometry.state.data : null
  const mapGeometry = useMemo(() => {
    if (!mockGeometry || !entries) return mockGeometry
    const byId = new Map(entries.map((ward) => [ward.ward_id, ward]))
    return {
      ...mockGeometry,
      features: mockGeometry.features.map((feature) => {
        const ward = byId.get(feature.properties.ward_id)
        return { ...feature, properties: {
          ...feature.properties, status: ward?.status ?? null, score: ward?.score ?? null,
        } }
      }),
    }
  }, [entries, mockGeometry])
  const mapPending = geometry.state.status === 'loading' || (config.mock && wards.state.status === 'loading')
  const selectedWard = entries?.find((ward) => ward.ward_id === selection?.id)

  return (
    <>
      <a className="skip-link" href="#main">Skip to workspace</a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="#main" onClick={() => setPage('map')}><span className="brand-icon"><Layers3 size={20} /></span>Subsidence Risk Map</a>
          <nav aria-label="Workspace">
            <button type="button" aria-current={page === 'map' ? 'page' : undefined} onClick={() => setPage('map')}><MapIcon size={16} /> Workspace</button>
            <button type="button" aria-current={page === 'methods' ? 'page' : undefined} onClick={() => setPage('methods')}><BookOpen size={16} /> Methodology</button>
            <button type="button" aria-current={page === 'validation' ? 'page' : undefined} onClick={() => setPage('validation')}><ChartNoAxesCombined size={16} /> Validation</button>
          </nav>
          <AuthorityAccess session={authority} signIn={signIn} signOut={() => signOut()} />
        </div>
      </header>

      <main id="main" className={'container app-main' + (page === 'map' ? ' map-page' : '')} tabIndex={-1}>
        {authorityNotice && <div className="session-notice" role="status">{authorityNotice}</div>}
        <div className="workspace-view" hidden={page !== 'map'}>
        <div className="workspace-heading">
          <div>
            <div className="location"><Activity size={15} /> {city?.city ?? 'City workspace'}</div>
            <h1>Ward screening</h1>
          </div>
          {city && <dl className="city-totals">
            <div><dt>Wards</dt><dd>{formatNumber(city.n_wards)}</dd></div>
            <div><dt>Ranked</dt><dd>{formatNumber(city.n_ranked)}</dd></div>
            <div><dt>Insufficient data</dt><dd>{formatNumber(city.n_wards - city.n_ranked)}</dd></div>
          </dl>}
        </div>
        {meta.state.status === 'error' && <FailedState label="City metadata" error={meta.state.error} retry={meta.retry} />}
        {config.mock && <div className="mock-notice"><FlaskConical size={17} /><strong>Mock data</strong>
          <span>Ward boundaries, scores and radar points are synthetic. Street geography comes from the basemap.</span></div>}

        <div className="workspace-grid">
          <section className="panel map-panel" id="workspace" aria-labelledby="map-title">
            <div className="panel-heading">
              <span className="section-icon"><MapIcon size={18} /></span>
              <h2 id="map-title">Ward risk map</h2>
              {config.mock && <span className="map-dataset">Synthetic wards</span>}
              {selection && <a className="map-inspect-link" href="#inspector">Ward details</a>}
            </div>
            <div className="map-frame">
              {geometry.state.status === 'error' ? (
                <div className="map-message"><FailedState label="Ward boundaries" error={geometry.state.error} retry={geometry.retry} /></div>
              ) : mapPending ? <p className="map-message" role="status">Loading ward map…</p> : (
                <Suspense fallback={<p className="map-message" role="status">Loading map…</p>}>
                  <MapWorkspace key={wards.attempt + ':' + geometry.attempt} geometry={mapGeometry} selection={selection} onSelect={onSelect}
                    authority={authority} onUnauthorized={unauthorized} />
                </Suspense>
              )}
            </div>
            <MapLegend />
            <p className="map-caption">City-relative inspection priority <button type="button" className="text-button" onClick={() => setPage('methods')}>How to read the index</button></p>
          </section>

          <div className="sidebar">
            {wards.state.status === 'ready' ? <Rankings wards={wards.state.data} selectedId={selection?.id ?? null} onSelect={onSelect}
              collapsed={rankingsCollapsed} onCollapse={() => setRankingsCollapsed((value) => !value)} /> : (
              <section className="panel" id="rankings" aria-labelledby="ranking-title">
                <div className="panel-heading"><h2 id="ranking-title">Ward rankings</h2></div>
                {wards.state.status === 'loading' ? <p className="panel-state" role="status">Loading ward rankings…</p>
                  : <FailedState label="Ward rankings" error={wards.state.error} retry={wards.retry} />}
              </section>
            )}
            <WardInspector id={selection?.id ?? null} name={selectedWard?.ward_name} rankedCount={city?.n_ranked} onClose={() => setSelection(null)}
              collapsed={inspectorCollapsed} onCollapse={() => setInspectorCollapsed((value) => !value)} onBrief={setBrief} />
          </div>
        </div>
        </div>

        {page !== 'map' && <Suspense fallback={<p role="status">Loading evidence…</p>}>
          <Evidence page={page} meta={city} validation={validation.state.status === 'ready' ? validation.state.data : undefined}
            validationError={validation.state.status === 'error' ? validation.state.error : undefined} retry={validation.retry} />
        </Suspense>}
      </main>
      {brief && <Suspense fallback={null}><InspectionBrief ward={brief} meta={city} onClose={() => setBrief(null)} /></Suspense>}
    </>
  )
}
