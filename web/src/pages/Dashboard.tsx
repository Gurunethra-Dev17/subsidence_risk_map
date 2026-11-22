import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, BookOpen, FileText, FlaskConical, LocateFixed, Map as MapIcon, Moon, ScanLine, Sun } from 'lucide-react'
import { getDataService, getSyntheticWardGeometry, isSyntheticDataset } from '../api/service'
import type { DataService, Ward } from '../api/service'
import { c5Attribution, delhiWardCount, hasDelhiWardIds, loadDelhiWardGeometry } from '../api/delhiMap'
import { config } from '../config'
import Rankings from '../panels/Rankings'
import AuthorityAccess from '../modes/AuthorityAccess'
import type { AuthoritySession } from '../api/authority'
import type { MapFeature } from '../map/overlayLayers'
import { formatNumber, insufficientBand, scoreBand, scoreBands, unavailableBand } from '../wardMetrics'
import { useWorkspaceView, viewHref } from './workspaceNavigation'

const MapWorkspace = lazy(() => import('../map/MapWorkspace'))
const Evidence = lazy(() => import('./Evidence'))
const InspectionBrief = lazy(() => import('../panels/InspectionBrief'))
const WardInspector = lazy(() => import('../panels/WardInspector'))

type Resource<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; error: string }
type Selection = { id: string; origin: 'map' | 'ranking' }

function useResource<T>(read: (service: DataService, signal: AbortSignal) => Promise<T>, enabled = true) {
  const [result, setResult] = useState<{ read: typeof read; state: Resource<T> } | null>(null)
  const state = result?.read === read ? result.state : { status: 'loading' as const }
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    void getDataService().then((service) => read(service, controller.signal)).then(
      (data) => { if (!controller.signal.aborted) setResult({ read, state: { status: 'ready', data } }) },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ read, state: { status: 'error', error: error instanceof Error ? error.message : 'An unexpected error occurred.' } })
        }
      },
    )
    return () => controller.abort()
  }, [attempt, enabled, read])
  const retry = () => {
    setResult(null)
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
const loadRealBoundaries = (_service: DataService, signal: AbortSignal) => loadDelhiWardGeometry(config.wardGeoJson ?? '', signal)
const hasRealMapSources = Boolean(config.wardGeoJson || config.wardTiles || config.cellTiles || config.pointTiles)

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
  const page = useWorkspaceView()
  const isOverview = page === 'map'
  const isEvidence = page === 'methods' || page === 'validation' || page === 'limitations'
  const [mapOpened, setMapOpened] = useState(isOverview)
  const [readEvidence, setReadEvidence] = useState(page === 'validation')
  const main = useRef<HTMLElement>(null)
  const previousPage = useRef(page)
  useEffect(() => {
    if (isOverview) setMapOpened(true)
    if (page === 'validation') setReadEvidence(true)
    if (previousPage.current !== page) {
      previousPage.current = page
      main.current?.focus()
      window.scrollTo(0, 0)
    }
  }, [isOverview, page])

  const meta = useResource(loadMeta)
  const health = useResource(loadHealth, !config.mock)
  const wards = useResource(listAllWards)
  const city = meta.state.status === 'ready' ? meta.state.data : undefined
  const synthetic = isSyntheticDataset(city)
  const entries = wards.state.status === 'ready' ? wards.state.data : undefined
  const useFixtureBoundaries = config.mock || (synthetic && city?.city === 'delhi')
  const realMetadataMatches = !synthetic && city?.city === 'delhi' && city.n_wards === delhiWardCount &&
    Boolean(config.delhiVintage) && city.data_vintage === config.delhiVintage
  const realDatasetMatches = useMemo(() => realMetadataMatches && Boolean(entries && hasDelhiWardIds(entries.map((ward) => ward.ward_id))),
    [entries, realMetadataMatches])
  const useRealGeoJson = realDatasetMatches && Boolean(config.wardGeoJson)
  const fixture = useResource(getSyntheticWardGeometry, useFixtureBoundaries && (mapOpened || isOverview))
  const boundaries = useResource(loadRealBoundaries, useRealGeoJson && (mapOpened || isOverview))
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
  const selectedId = selection?.id
  const loadWard = useCallback((service: DataService, signal: AbortSignal) => service.getWard(selectedId ?? '', signal), [selectedId])
  const details = useResource(loadWard, selectedId !== undefined)
  const [rankingsCollapsed, setRankingsCollapsed] = useState(false)
  const [mapFeature, setMapFeature] = useState<MapFeature | null>(null)
  const [authority, setAuthority] = useState<AuthoritySession | null>(null)
  const [authorityNotice, setAuthorityNotice] = useState('')
  const session = useRef<AuthoritySession | null>(null)
  const signOut = useCallback((notice = '') => {
    session.current?.close()
    session.current = null
    setAuthority(null)
    setMapFeature((feature) => feature?.layer === 'buildings' || (!config.mock && feature?.layer === 'points') ? null : feature)
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
  }, [])
  const fixtureGeometry = useFixtureBoundaries && fixture.state.status === 'ready' ? fixture.state.data : null
  const realGeometry = useRealGeoJson && boundaries.state.status === 'ready' ? boundaries.state.data : null
  const realGeometryMismatch = useMemo(() => Boolean(realGeometry && !hasDelhiWardIds(realGeometry.features.map(({ properties }) => properties.ward_id))),
    [realGeometry])
  const compatibleGeometry = fixtureGeometry ?? (realGeometryMismatch ? null : realGeometry)
  const mapGeometry = useMemo(() => {
    if (!compatibleGeometry) return null
    if (!entries) return config.mock ? compatibleGeometry : null
    const byId = new Map(entries.map((ward) => [ward.ward_id, ward]))
    if (!config.mock && fixtureGeometry && (byId.size !== fixtureGeometry.features.length ||
      !fixtureGeometry.features.every(({ properties }) => byId.has(properties.ward_id)))) return null
    return {
      ...compatibleGeometry,
      features: compatibleGeometry.features.map((feature) => {
        const ward = byId.get(feature.properties.ward_id)
        return { ...feature, properties: {
          ...feature.properties, status: ward?.status, score: ward?.score ?? null,
        } }
      }),
    }
  }, [compatibleGeometry, entries, fixtureGeometry])
  const realGeoJsonError = useRealGeoJson && boundaries.state.status === 'error' ? boundaries.state.error : undefined
  const wardTiles = realDatasetMatches && (!useRealGeoJson || realGeoJsonError) ? config.wardTiles : undefined
  const mapPending = meta.state.status === 'loading' ||
    (useFixtureBoundaries && (fixture.state.status === 'loading' || (!config.mock && wards.state.status === 'loading'))) ||
    (hasRealMapSources && realMetadataMatches && wards.state.status === 'loading') ||
    (useRealGeoJson && boundaries.state.status === 'loading')
  const realSourceNotice = !config.mock && hasRealMapSources && !mapPending && !realDatasetMatches
    ? synthetic ? 'Configured Delhi map sources are disabled while the API serves synthetic data.'
      : !city || (realMetadataMatches && wards.state.status === 'error') ? 'Delhi map sources are unavailable until the API dataset can be verified.'
        : 'Dataset mismatch. Delhi map sources require the configured data vintage and all 250 matching ward IDs.'
    : undefined
  const fixtureMismatch = Boolean(fixtureGeometry && entries && !mapGeometry)
  const renderRealMap = realDatasetMatches && Boolean(mapGeometry || wardTiles)
  const selectedWard = entries?.find((ward) => ward.ward_id === selection?.id)
  const selectedDetails = details.state.status === 'ready' ? details.state.data : undefined
  const inspectorFeature = selectedId && mapFeature?.wardId === selectedId &&
    (mapFeature.layer === 'cells' || authority || (config.mock && mapFeature.layer === 'points')) ? mapFeature : null
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
      <a className="skip-link" href="#main" onClick={(event) => { event.preventDefault(); main.current?.focus() }}>Skip to workspace</a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href={viewHref('map')}><span className="brand-icon"><LocateFixed size={22} /></span><span>Subsidence Risk Map<small>Urban ground-motion monitoring</small></span></a>
          <nav className="primary-nav" aria-label="Workspace">
            <a href={viewHref('map')} aria-current={isOverview ? 'page' : undefined}><MapIcon size={16} /> Overview Map</a>
            <a href={viewHref('inspector')} aria-current={page === 'inspector' ? 'page' : undefined}><ScanLine size={16} /> Ward Inspector</a>
            <a href={viewHref('brief')} aria-current={page === 'brief' ? 'page' : undefined}><FileText size={16} /> Inspection Brief</a>
          </nav>
          <div className="header-tools">
            <a className="header-button evidence-link" href={viewHref('methods')} aria-current={isEvidence ? 'location' : undefined}><BookOpen size={15} /> Methods &amp; Evidence</a>
            <button type="button" className="header-button appearance-control" aria-label={appearance === 'dark' ? 'Switch to light appearance' : 'Switch to dark appearance'}
              onClick={() => setAppearance((value) => value === 'dark' ? 'light' : 'dark')}>{appearance === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
            <AuthorityAccess session={authority} signIn={signIn} signOut={() => signOut()} />
          </div>
        </div>
      </header>

      <main id="main" ref={main} className={'container app-main' + (isOverview ? ' map-page' : '')} tabIndex={-1}>
        {authorityNotice && <div className="session-notice" role="status">{authorityNotice}</div>}
        {(mapOpened || isOverview) && <div className="workspace-view" hidden={!isOverview}>
        <div className="workspace-heading">
          <div>
            <h1><Activity size={21} /> {city?.city ?? 'City'} monitoring</h1>
            <div className="source-status">{synthetic ? <FlaskConical size={14} /> : <Activity size={14} />}
              <strong>{config.mock ? 'Synthetic data preview' : synthetic ? 'Live API · synthetic demo data' : 'Live API'}</strong>
              <span>{config.mock ? 'Fictional ward scores, boundaries and radar observations' : synthetic ? 'Fictional ward metrics and boundaries' : city?.data_vintage}</span>
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
              {mapGeometry && <span className="map-dataset">{renderRealMap ? 'Delhi wards · GeoJSON' : 'Synthetic wards'}</span>}
              {wardTiles && <span className="map-dataset">Delhi wards · PMTiles</span>}
            </div>
            {realSourceNotice && <p className="panel-state" role="alert">{realSourceNotice}</p>}
            {realGeoJsonError && wardTiles && <p className="panel-state" role="status">Ward GeoJSON unavailable · using configured ward PMTiles.</p>}
            <div className="map-frame">
              {useFixtureBoundaries && fixture.state.status === 'error' ? (
                <div className="map-message"><FailedState label="Ward boundaries" error={fixture.state.error} retry={fixture.retry} /></div>
              ) : realGeoJsonError && !wardTiles ? (
                <div className="map-message"><FailedState label="Delhi ward boundaries" error={realGeoJsonError} retry={boundaries.retry} /></div>
              ) : realGeometryMismatch || fixtureMismatch ? (
                <p className="map-message" role="alert">Dataset mismatch. Ward boundary IDs do not match the API rankings.</p>
              ) : mapPending ? <p className="map-message" role="status">Loading ward map…</p> : (
                <Suspense fallback={<p className="map-message" role="status">Loading map…</p>}>
                  <MapWorkspace key={`${wards.attempt}:${fixture.attempt}:${boundaries.attempt}:${wardTiles ?? ''}`}
                    geometry={mapGeometry} wardTiles={wardTiles} realMap={renderRealMap} selection={selection} onSelect={onSelect} appearance={appearance}
                    visible={isOverview} onFeatureChange={setMapFeature} authority={authority} onUnauthorized={unauthorized} />
                </Suspense>
              )}
            </div>
            <MapLegend />
            <p className="map-caption">City-relative inspection priority <a className="text-button" href={viewHref('methods')}>How to read the index</a></p>
            {renderRealMap && <p className="map-caption">{c5Attribution}{config.delhiAttribution && ` · ${config.delhiAttribution}`}</p>}
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
            <section className="panel ward-summary" aria-labelledby="selected-ward-title">
              <div className="panel-heading"><span className="section-icon"><ScanLine size={17} /></span><h2 id="selected-ward-title">Selected ward</h2></div>
              {selectedId ? <>
                <div className="ward-summary-content">
                  <div><strong>{selectedWard?.ward_name ?? selectedId}</strong> <span className="muted-copy">{selectedId}</span></div>
                  {selectedWard && <span className="muted-copy">{scoreBand(selectedWard.status, selectedWard.score).label}
                    {selectedWard.score != null && ` · ${formatNumber(selectedWard.score)}/100`}
                    {selectedWard.rank != null && ` · Rank #${formatNumber(selectedWard.rank)}`}</span>}
                  <div className="view-actions">
                    <a className="secondary-button" href={viewHref('inspector')}>Open Ward Inspector</a>
                    <a className="text-button" href={viewHref('brief')}>Open Inspection Brief</a>
                    <button type="button" className="text-button" onClick={() => setSelection(null)}>Clear ward selection</button>
                  </div>
                </div>
              </> : <p className="panel-state">Choose a ward on the map or in the rankings.</p>}
            </section>
          </aside>
        </div>
        </div>}

        {(page === 'inspector' || page === 'brief') && <div className="detail-view">
          <header className="detail-heading">
            <div>
              <h1>{page === 'inspector' ? 'Ward Inspector' : 'Inspection Brief'}</h1>
              <p className="source-status"><strong>{synthetic ? 'Synthetic data preview' : 'Public ward summary'}</strong>{city?.data_vintage && <span>{city.data_vintage}</span>}</p>
            </div>
            <div className="view-actions">
              <a className="secondary-button" href={viewHref('map')}>Back to Overview Map</a>
              <a className="secondary-button" href={viewHref(page === 'inspector' ? 'brief' : 'inspector')}>
                {page === 'inspector' ? 'Open Inspection Brief' : 'Open Ward Inspector'}
              </a>
            </div>
          </header>
          <div className="ward-context panel">
            <label>Ward <select disabled={!entries?.length} value={selectedId ?? ''} onChange={(event) => {
              if (event.target.value) onSelect(event.target.value, 'ranking')
              else setSelection(null)
            }}>
              <option value="">Choose a ward</option>
              {entries?.map((ward) => <option key={ward.ward_id} value={ward.ward_id}>{ward.ward_name} · {ward.ward_id}</option>)}
            </select></label>
            {wards.state.status === 'error' ? <FailedState label="Ward list" error={wards.state.error} retry={wards.retry} />
              : wards.state.status === 'loading' ? <p className="muted-copy" role="status">Loading ward list…</p>
                : entries?.length === 0 ? <p className="muted-copy">No ward summaries are available.</p> : null}
          </div>
          {!selectedId ? <section className="panel detail-empty"><h2>Select a ward</h2><p>Choose a ward above or return to the overview map.</p></section>
            : details.state.status === 'error' ? <FailedState label="Ward details" error={details.state.error} retry={details.retry} />
              : !selectedDetails ? <p className="panel-state" role="status">Loading ward details…</p>
                : <Suspense fallback={<p className="panel-state" role="status">{page === 'inspector' ? 'Loading ward inspector…' : 'Loading inspection brief…'}</p>}>
                  {page === 'inspector' ? <WardInspector ward={selectedDetails} rankedCount={city?.n_ranked} feature={inspectorFeature} />
                    : <InspectionBrief key={selectedId} ward={selectedDetails} meta={city} />}
                </Suspense>}
        </div>}

        {isEvidence && <Suspense fallback={<p role="status">Loading evidence…</p>}>
          <Evidence page={page} meta={city} validation={validation.state.status === 'ready' ? validation.state.data : undefined}
            validationError={validation.state.status === 'error' ? validation.state.error : undefined} retry={validation.retry}
            mapAttribution={realDatasetMatches ? [c5Attribution, config.delhiAttribution].filter(Boolean).join(' · ') : undefined} />
        </Suspense>}
      </main>
    </>
  )
}
