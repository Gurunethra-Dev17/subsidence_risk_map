import { lazy, Suspense, useEffect, useState } from 'react'
import { AlertCircle, FlaskConical, Globe2, Layers2, Map as MapIcon, ShieldCheck } from 'lucide-react'
import { getDataService } from '../api/service'
import type { WardGeometry } from '../api/service'
import type { components } from '../../types/openapi'
import { config } from '../config'
import { RankingPreview, ValidationPreview, WardDetailPlaceholder } from '../panels/OverviewPanels'

const MapWorkspace = lazy(() => import('../map/MapWorkspace'))
type Api = components['schemas']
type DashboardData = {
  meta: Api['MetaResponse']
  wards: Api['WardPage']
  validation: Api['ValidationSummary']
  geometry: WardGeometry | null
}
type DashboardState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: DashboardData }

async function loadDashboard(signal: AbortSignal): Promise<DashboardData> {
  const service = await getDataService()
  const [meta, wards, validation, geometry] = await Promise.all([
    service.getMeta(signal),
    service.listWards({ sort: 'rank', order: 'asc', limit: 5 }, signal),
    service.getValidation(signal),
    service.getMockWardGeometry(),
  ])
  return { meta, wards, validation, geometry }
}

export default function Dashboard() {
  const [state, setState] = useState<DashboardState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void loadDashboard(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: 'ready', data })
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ status: 'error', message: error instanceof Error ? error.message : 'An unexpected error occurred.' })
        }
      },
    )
    return () => controller.abort()
  }, [attempt])

  const data = state.status === 'ready' ? state.data : undefined
  return (
    <>
      <a className="skip-link" href="#main">Skip to workspace</a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="#main"><span className="brand-icon"><Layers2 size={22} /></span>Subsidence Risk Map</a>
          <nav aria-label="Workspace">
            <a href="#workspace">Map</a>
            <a href="#rankings">Rankings</a>
            <a href="#validation">Validation</a>
          </nav>
          <span className="public-badge"><ShieldCheck size={17} /> Public mode</span>
        </div>
      </header>
      <main id="main" className="container">
        <div className="intro">
          <div>
            <p className="location"><Globe2 size={17} /> {data?.meta.city ?? 'City workspace'}</p>
            <h1>Ward screening overview</h1>
            <p>Explore ward-level subsidence scores and data coverage.</p>
          </div>
          {config.mock && <span className="mock-badge"><FlaskConical size={17} /> Mock data</span>}
        </div>
        {config.mock && (
          <p className="mock-notice"><FlaskConical size={18} /> Synthetic ward boundaries and scores for demonstration.</p>
        )}
        {state.status === 'loading' && <div className="panel dashboard-status" role="status">Loading ward data…</div>}
        {state.status === 'error' && (
          <div className="panel dashboard-status">
            <div role="alert"><AlertCircle size={20} /><strong>Unable to load the workspace.</strong> {state.message}</div>
            <button type="button" onClick={() => {
              setState({ status: 'loading' })
              setAttempt((count) => count + 1)
            }}>Try again</button>
          </div>
        )}
        {data && (
          <>
            <div className="stats" aria-label="Ward availability">
              <div><span>Wards in dataset</span><strong>{data.meta.n_wards}</strong></div>
              <div><span>Ranked wards</span><strong>{data.meta.n_ranked}</strong></div>
              <div><span>Insufficient data</span><strong>{data.meta.n_wards - data.meta.n_ranked}</strong></div>
            </div>
            <div className="workspace-grid">
              <section className="panel map-panel" id="workspace" aria-labelledby="map-title">
                <div className="panel-heading">
                  <div className="section-icon"><MapIcon size={19} /></div>
                  <div><h2 id="map-title">Map workspace</h2><p>Ward boundaries</p></div>
                </div>
                <div className="map-frame">
                  <Suspense fallback={<div className="map-message" role="status">Loading map…</div>}>
                    <MapWorkspace geometry={data.geometry} />
                  </Suspense>
                </div>
                <div className="map-footer"><span className="boundary-key" /> Ward boundary</div>
              </section>
              <aside className="sidebar" aria-label="Ward information">
                <RankingPreview page={data.wards} />
                <WardDetailPlaceholder />
              </aside>
            </div>
            <ValidationPreview validation={data.validation} />
          </>
        )}
      </main>
    </>
  )
}
