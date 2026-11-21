import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, BookOpen, ChartNoAxesCombined, FlaskConical, LocateFixed, Map as MapIcon, Moon, ScanLine, Sun } from 'lucide-react'
import { getDataService, getSyntheticWardGeometry, isSyntheticDataset } from '../api/service'
import type { DataService, Ward } from '../api/service'
import { config } from '../config'
import Rankings from '../panels/Rankings'
import AuthorityAccess from '../modes/AuthorityAccess'
import type { AuthoritySession } from '../api/authority'
import { formatNumber, insufficientBand, scoreBands, unavailableBand } from '../wardMetrics'

const MapWorkspace = lazy(() => import('../map/MapWorkspace'))
const Evidence = lazy(() => import('./Evidence'))
const InspectionBrief = lazy(() => import('../panels/InspectionBrief'))
const WardInspector = lazy(() => import('../panels/WardInspector'))

type Resource<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; error: string }
type Selection = { id: string; origin: 'map' | 'ranking' }

function useResource<T>(read: (service: DataService, signal: AbortSignal) => Promise<T>, enabled = true) {
  const [state, setState] = useState<Resource<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!enabled) return
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
  }, [attempt, enabled, read])
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
const loadHealth = (service: DataService, signal: AbortSignal) => service.getHealth(signal)
const loadValidation = (service: DataService, signal: AbortSignal) => service.getValidation(signal)

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
  const health = useResource(loadHealth, !config.mock)
  const wards = useResource(listAllWards)
  const city = meta.state.status === 'ready' ? meta.state.data : undefined
  const synthetic = isSyntheticDataset(city)
  const useFixtureBoundaries = config.mock || (synthetic && city?.city === 'delhi' && !config.wardTiles)
  const geometry = useResource(getSyntheticWardGeometry, useFixtureBoundaries)
  const [readEvidence, setReadEvidence] = useState(false)
  const validation = useResource(loadValidation, readEvidence)
  const [appearance, setAppearance] = useState<'light' | 'dark'>(() => {
    try { return localStorage.getItem('map-appearance') === 'dark' ? 'dark' : 'light' }
    catch { return 'light' }
  })
  useEffect(() => {
    document.documentElement.dataset.appearance = appearance
    try { localStorage.setItem('map-appearance', appearance) } catch { /* Storage is optional. */ }
  }, [appearance])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [page, setPage] = useState<'map' | 'methods' | 'validation'>('map')
  const [rankingsCollapsed, setRankingsCollapsed] = useState(false)
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false)
  const [brief, setBrief] = useState<Ward | null>(null)
  const [inspectorOpened, setInspectorOpened] = useState(false)
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
    setInspectorOpened(true)
    setInspectorCollapsed(false)
  }, [])
  const entries = wards.state.status === 'ready' ? wards.state.data : undefined
  const fixtureGeometry = useFixtureBoundaries && geometry.state.status === 'ready' ? geometry.state.data : null
  const mapGeometry = useMemo(() => {
    if (!fixtureGeometry) return null
    if (!entries) return config.mock ? fixtureGeometry : null
    const byId = new Map(entries.map((ward) => [ward.ward_id, ward]))
    // Live data must match the bundled fixture IDs before using its boundaries.
    if (!config.mock && (byId.size !== fixtureGeometry.features.length ||
      !fixtureGeometry.features.every(({ properties }) => byId.has(properties.ward_id)))) return null
    return {
      ...fixtureGeometry,
      features: fixtureGeometry.features.map((feature) => {
        const ward = byId.get(feature.properties.ward_id)
        return { ...feature, properties: {
          ...feature.properties, status: ward?.status ?? null, score: ward?.score ?? null,
        } }
      }),
    }
  }, [entries, fixtureGeometry])
  const mapPending = useFixtureBoundaries
    ? geometry.state.status === 'loading' || wards.state.status === 'loading'
    : !config.wardTiles && meta.state.status === 'loading'
  const selectedWard = entries?.find((ward) => ward.ward_id === selection?.id)
  const coverage = useMemo(() => {
    if (!entries || !city || entries.length !== city.n_wards) return null
    const totals = entries.reduce((sum, ward) => ({
      buildings: sum.buildings + ward.n_buildings,
      measured: sum.measured + ward.n_buildings_with_data,
    }), { buildings: 0, measured: 0 })
    return totals.buildings ? formatNumber(100 * totals.measured / totals.buildings) + '%' : null
  }, [city, entries])

  return (
    <>
      <a className="skip-link" href="#main">Skip to workspace</a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="#main" onClick={() => setPage('map')}><span className="brand-icon"><LocateFixed size={22} /></span><span>Subsidence Risk Map<small>Urban ground-motion monitoring</small></span></a>
          <nav aria-label="Workspace">
            <button type="button" aria-current={page === 'map' ? 'page' : undefined} onClick={() => setPage('map')}><MapIcon size={16} /> Workspace</button>
            <button type="button" aria-current={page === 'methods' ? 'page' : undefined} onClick={() => setPage('methods')}><BookOpen size={16} /> Methodology</button>
            <button type="button" aria-current={page === 'validation' ? 'page' : undefined} onClick={() => { setReadEvidence(true); setPage('validation') }}><ChartNoAxesCombined size={16} /> Validation</button>
          </nav>
          <div className="header-tools">
            <button type="button" className="header-button appearance-control" aria-label={appearance === 'dark' ? 'Switch to light appearance' : 'Switch to dark appearance'}
              onClick={() => setAppearance((value) => value === 'dark' ? 'light' : 'dark')}>{appearance === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
            <AuthorityAccess session={authority} signIn={signIn} signOut={() => signOut()} />
          </div>
        </div>
      </header>

      <main id="main" className={'container app-main' + (page === 'map' ? ' map-page' : '')} tabIndex={-1}>
        {authorityNotice && <div className="session-notice" role="status">{authorityNotice}</div>}
        <div className="workspace-view" hidden={page !== 'map'}>
        <div className="workspace-heading">
          <div>
            <h1><Activity size={21} /> {city?.city ?? 'City'} monitoring</h1>
            <div className="source-status">{synthetic ? <FlaskConical size={14} /> : <Activity size={14} />}
              <strong>{config.mock ? 'Mock data' : synthetic ? 'Live API · synthetic demo data' : 'Live API'}</strong>
              <span>{config.mock ? 'Synthetic ward and radar overlays' : synthetic ? 'Fictional ward metrics and boundaries' : city?.data_vintage}</span>
              {!config.mock && <span role="status">{health.state.status === 'ready' ? `API reachable · ${health.state.data.version}`
                : health.state.status === 'error' ? 'API health check failed' : 'Checking API health…'}</span>}
            </div>
          </div>
          {city && <dl className="city-totals">
            <div><dt>Wards monitored</dt><dd>{formatNumber(city.n_wards)}</dd></div>
            <div><dt>Inspection ranks</dt><dd>{formatNumber(city.n_ranked)}</dd></div>
            <div><dt>Insufficient data</dt><dd>{formatNumber(city.n_wards - city.n_ranked)}</dd></div>
            <div title="Buildings with data divided by total buildings across all listed wards"><dt>Building coverage</dt><dd>{coverage ?? '—'}</dd></div>
          </dl>}
        </div>
        {meta.state.status === 'error' && <FailedState label="City metadata" error={meta.state.error} retry={meta.retry} />}

        <div className="workspace-grid">
          <section className="panel map-panel" id="workspace" aria-labelledby="map-title">
            <div className="panel-heading">
              <span className="section-icon"><MapIcon size={18} /></span>
              <h2 id="map-title">Risk atlas</h2>
              {mapGeometry && <span className="map-dataset">Synthetic wards</span>}
              {selection && <a className="map-inspect-link" href="#inspector">Ward details</a>}
            </div>
            <div className="map-frame">
              {useFixtureBoundaries && geometry.state.status === 'error' ? (
                <div className="map-message"><FailedState label="Ward boundaries" error={geometry.state.error} retry={geometry.retry} /></div>
              ) : mapPending ? <p className="map-message" role="status">Loading ward map…</p> : (
                <Suspense fallback={<p className="map-message" role="status">Loading map…</p>}>
                  <MapWorkspace key={wards.attempt + ':' + geometry.attempt} geometry={mapGeometry} selection={selection} onSelect={onSelect} appearance={appearance}
                    authority={authority} onUnauthorized={unauthorized} />
                </Suspense>
              )}
            </div>
            <MapLegend />
            <p className="map-caption">City-relative inspection priority <button type="button" className="text-button" onClick={() => setPage('methods')}>How to read the index</button></p>
          </section>

          <aside className="sidebar" aria-label="Ward analysis">
            {wards.state.status === 'ready' ? <Rankings wards={wards.state.data} selectedId={selection?.id ?? null} onSelect={onSelect}
              collapsed={rankingsCollapsed} onCollapse={() => setRankingsCollapsed((value) => !value)} /> : (
              <section className="panel" id="rankings" aria-labelledby="ranking-title">
                <div className="panel-heading"><h2 id="ranking-title">Ward rankings</h2></div>
                {wards.state.status === 'loading' ? <p className="panel-state" role="status">Loading ward rankings…</p>
                  : <FailedState label="Ward rankings" error={wards.state.error} retry={wards.retry} />}
              </section>
            )}
            {inspectorOpened ? <Suspense fallback={<p className="panel-state" role="status">Loading ward inspector…</p>}>
              <WardInspector id={selection?.id ?? null} name={selectedWard?.ward_name} rankedCount={city?.n_ranked} onClose={() => setSelection(null)}
                collapsed={inspectorCollapsed} onCollapse={() => setInspectorCollapsed((value) => !value)} onBrief={setBrief} />
            </Suspense> : <section className="panel inspector empty-inspector" id="inspector" tabIndex={-1}>
              <div className="panel-heading"><span className="section-icon"><ScanLine size={17} /></span><h2>Ward inspector</h2></div>
              <p><strong>Awaiting ward selection</strong><span>Choose a boundary or ranking row to review evidence and prepare an inspection brief.</span></p>
            </section>}
          </aside>
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
