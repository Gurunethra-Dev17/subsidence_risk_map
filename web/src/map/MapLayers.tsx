import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Layers3 } from 'lucide-react'
import { addProtocol, removeProtocol } from 'maplibre-gl'
import type { Map as MapLibreMap, SourceSpecification } from 'maplibre-gl'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { PMTiles } from 'pmtiles'
import { getDataService } from '../api/service'
import { isUnauthorized } from '../api/authority'
import type { AuthoritySession } from '../api/authority'
import { config } from '../config'
import { makeOverlayLayers, overlayLayerId, overlayLegends, overlaySelection, overlaySettings, overlaySourceId } from './overlayLayers'
import type { OverlayKey } from './overlayLayers'
import { selectedLine } from './wardLayers'

const PRIVATE_PROTOCOL = 'wardprivate'
type Viewport = { zoom: number; bbox: string }
type LayerStatus = 'off' | 'zoom' | 'loading' | 'empty' | 'ready' | 'unavailable' | 'error'

function readViewport(map: MapLibreMap): Viewport {
  const { lng: west, lat: south } = map.getBounds().getSouthWest().wrap()
  const { lng: east, lat: north } = map.getBounds().getNorthEast().wrap()
  const bbox = west < east ? [west, south, east, north] : [-180, south, 180, north]
  return { zoom: map.getZoom(), bbox: bbox.map((value) => value.toFixed(6)).join(',') }
}

function LayerToggle({ layer, map, view, wardId, authority, onUnauthorized, onHide }: {
  layer: OverlayKey
  map: MapLibreMap | null
  view: Viewport | null
  wardId: string | null
  authority: AuthoritySession | null
  onUnauthorized: () => void
  onHide: (layer: OverlayKey) => void
}) {
  const [enabled, setEnabled] = useState(false)
  const [opacity, setOpacity] = useState(85)
  const [status, setStatus] = useState<LayerStatus>('off')
  const [fallback, setFallback] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const opacityRef = useRef(opacity)
  const spec = overlaySettings[layer]
  const archive = config.mock ? '' : layer === 'cells' ? config.cellTiles : layer === 'points' ? config.pointTiles : ''
  const buildingView = layer === 'buildings' && (!authority?.archive || fallback) ? view?.bbox : undefined
  const cellWard = layer === 'cells' && !config.mock && (!archive || fallback) ? wardId : null
  const atZoom = Boolean(view && view.zoom >= spec.zoom)
  const session = layer === 'buildings' ? authority : null
  const allowed = layer === 'cells' || (layer === 'points' && (config.mock || Boolean(authority))) || Boolean(session)

  useLayoutEffect(() => {
    if (!enabled) return
    if (!allowed) { setStatus('unavailable'); return }
    if (!map) { setStatus('loading'); return }
    if (!atZoom) { setStatus('zoom'); return }
    const controller = new AbortController()
    const sourceId = overlaySourceId(layer)
    const installed: string[] = []
    let privateProtocol = false
    let vectorSource = false
    const protectedArchive = session?.archive && !fallback ? session.archive : undefined
    const canFallback = !fallback && (Boolean(protectedArchive) || Boolean(archive && layer === 'cells'))

    function failed(error?: unknown) {
      if (controller.signal.aborted) return
      if (isUnauthorized(error)) { onUnauthorized(); return }
      if (canFallback) setFallback(true)
      else setStatus('error')
    }

    async function install(current: MapLibreMap) {
      let source: SourceSpecification
      if (protectedArchive) {
        const tileArchive = new PMTiles(protectedArchive)
        const header = await tileArchive.getHeader()
        if (controller.signal.aborted) return
        addProtocol(PRIVATE_PROTOCOL, async ({ url }, tileController) => {
          if (controller.signal.aborted) return { data: new ArrayBuffer(0) }
          const [z, x, y] = url.slice((PRIVATE_PROTOCOL + '://buildings/').length).split('/').map(Number)
          try {
            const data = await tileArchive.getZxy(z, x, y, AbortSignal.any([controller.signal, tileController.signal]))
            return { data: data?.data ?? new ArrayBuffer(0) }
          } catch (error) {
            failed(error)
            return { data: new ArrayBuffer(0) }
          }
        })
        privateProtocol = true
        source = { type: 'vector', tiles: [PRIVATE_PROTOCOL + '://buildings/{z}/{x}/{y}'],
          minzoom: header.minZoom, maxzoom: header.maxZoom }
      } else if (archive && !fallback) {
        source = { type: 'vector', url: 'pmtiles://' + new URL(archive, window.location.href).href }
      } else {
        let data: FeatureCollection<Geometry | null> | null = null
        if (session && buildingView) {
          data = await session.getBuildings({ bbox: buildingView, limit: 500 }, controller.signal)
        } else if (layer === 'cells' || layer === 'points') {
          const service = await getDataService()
          if (layer === 'points') data = await service.getMockRadarGeometry()
          else {
            // JSON Schema deliberately leaves GeoJSON geometry open. MapLibre validates the shape.
            const cells = config.mock ? await service.getMockCellGeometry()
              : cellWard ? await service.getWardCells(cellWard, controller.signal) : null
            data = cells as FeatureCollection | null
          }
        }
        if (controller.signal.aborted) return
        if (!data) { setStatus('unavailable'); return }
        const features = data.features.filter((feature): feature is Feature => Boolean(feature.geometry))
        if (!features.length) { setStatus('empty'); return }
        source = { type: 'geojson', data: { ...data, features }, ...(config.mock ? { attribution: 'Synthetic project fixtures' } : {}) }
      }
      if (controller.signal.aborted) return
      current.addSource(sourceId, source)
      const vector = source.type === 'vector'
      vectorSource = vector
      for (const style of [...makeOverlayLayers(layer, vector, opacityRef.current / 100), overlaySelection(layer, vector)]) {
        current.addLayer(style, current.getLayer(selectedLine) ? selectedLine : undefined)
        installed.push(style.id)
      }
      if (source.type === 'geojson') setStatus('ready')
    }

    const onError = (event: object) => {
      if ('sourceId' in event && event.sourceId === sourceId) failed()
    }
    const onSource = (event: { sourceId: string; isSourceLoaded: boolean }) => {
      if (event.sourceId === sourceId && event.isSourceLoaded && !controller.signal.aborted) {
        setStatus((previous) => previous === 'loading' ? 'ready' : previous)
      }
    }
    const onIdle = () => {
      const id = overlayLayerId(layer)
      if (!vectorSource || !map.getLayer(id)) return
      const visibleCount = map.queryRenderedFeatures({ layers: [id] }).length
      setStatus((previous) => previous === 'error' ? previous : visibleCount ? 'ready' : 'empty')
    }
    setStatus('loading')
    map.on('error', onError)
    map.on('sourcedata', onSource)
    map.on('idle', onIdle)
    void install(map).catch(failed)
    return () => {
      controller.abort()
      map.off('error', onError)
      map.off('sourcedata', onSource)
      map.off('idle', onIdle)
      for (const id of installed.reverse()) if (map.getLayer(id)) map.removeLayer(id)
      if (map.getSource(sourceId)) map.removeSource(sourceId)
      if (privateProtocol) removeProtocol(PRIVATE_PROTOCOL)
    }
  }, [allowed, archive, atZoom, attempt, buildingView, cellWard, enabled, fallback, layer, map, onUnauthorized, session])

  const changeOpacity = (value: number) => {
    setOpacity(value)
    opacityRef.current = value
    const id = overlayLayerId(layer)
    if (!map?.getLayer(id)) return
    if (layer === 'points') {
      map.setPaintProperty(id, 'circle-opacity', value / 100)
      map.setPaintProperty(id, 'circle-stroke-opacity', value / 100)
    } else {
      map.setPaintProperty(id, 'fill-opacity', value / 100)
      if (map.getLayer(id + '-hatch')) map.setPaintProperty(id + '-hatch', 'fill-opacity', value / 100)
    }
  }

  const detail = {
    off: 'Hidden',
    zoom: `Zoom to level ${spec.zoom} to display`,
    loading: 'Loading layer…',
    empty: 'No features returned for this view',
    ready: layer === 'buildings' && (!session?.archive || fallback) ? 'Viewport query · up to 500 buildings' : spec.description,
    unavailable: layer === 'cells' && !config.mock && !cellWard ? 'Select a ward for API cells' : 'No source is configured for this layer',
    error: 'Layer could not be loaded',
  }[enabled ? status : 'off']

  return <div className="layer-row">
    <label className="layer-name"><input type="checkbox" checked={enabled} onChange={(event) => {
      setEnabled(event.target.checked)
      if (!event.target.checked) onHide(layer)
    }} />{spec.label}<small>{spec.zoom}+</small></label>
    {enabled && <label className="opacity-label">Opacity <input aria-label={spec.label + ' opacity'} type="range" min={15} max={100} value={opacity} onChange={(event) => changeOpacity(Number(event.target.value))} />{opacity}%</label>}
    <p role={enabled ? 'status' : undefined}>{detail}</p>
    {enabled && status === 'ready' && layer === 'buildings' && <p>{spec.description}</p>}
    {enabled && status === 'ready' && <ul className="overlay-legend" aria-label={spec.label + ' legend'}>
      {overlayLegends[layer].map(({ label, color, hatch }) => <li key={label}>
        <i aria-hidden="true" className={hatch ? 'swatch hatch-swatch' : 'swatch'} style={{ backgroundColor: color }} />{label}
      </li>)}
    </ul>}
    {enabled && fallback && <p>Archive unavailable · using the API fallback</p>}
    {enabled && status === 'error' && <button type="button" className="text-button" onClick={() => { setFallback(false); setAttempt((count) => count + 1) }}>Retry layer</button>}
  </div>
}

export default function MapLayers({ map, wardId, authority, onUnauthorized, onHide, theme, onTheme }: {
  map: MapLibreMap | null
  wardId: string | null
  authority: AuthoritySession | null
  onUnauthorized: () => void
  onHide: (layer: OverlayKey) => void
  theme: 'street' | 'dark'
  onTheme: (theme: 'street' | 'dark') => void
}) {
  const [view, setView] = useState<Viewport | null>(null)
  useEffect(() => {
    if (!map) return
    const update = () => setView(readViewport(map))
    update()
    map.on('moveend', update)
    return () => { map.off('moveend', update) }
  }, [map])

  const shared = { map, view, wardId, authority, onUnauthorized, onHide }
  return <details className="layers-control">
    <summary><Layers3 size={17} /> Layers</summary>
    <div className="layers-popover">
      <label className="basemap-picker">Basemap <select value={theme} onChange={(event) => onTheme(event.target.value === 'dark' ? 'dark' : 'street')}>
        <option value="street">Street</option><option value="dark">Dark streets</option>
      </select></label>
      <LayerToggle layer="cells" {...shared} />
      {(config.mock || authority) && <LayerToggle layer="points" {...shared} />}
      {authority && <LayerToggle layer="buildings" {...shared} />}
    </div>
  </details>
}
