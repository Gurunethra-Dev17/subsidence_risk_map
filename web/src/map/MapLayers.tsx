import { memo, useLayoutEffect, useRef, useState } from 'react'
import { Layers3 } from 'lucide-react'
import type { Map as MapLibreMap, SourceSpecification } from 'maplibre-gl'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { getDataService } from '../api/service'
import { isUnauthorized } from '../api/authorityErrors'
import type { AuthoritySession } from '../api/authority'
import { config } from '../config'
import { makeOverlayLayers, overlayHitLayers, overlayLayerId, overlayLegends, overlaySelection, overlaySettings, overlaySourceId } from './overlayLayers'
import type { OverlayKey } from './overlayLayers'
import { selectedLine } from './wardLayers'

type Viewport = { zoom: number; bbox: string }
type LayerStatus = 'off' | 'zoom' | 'loading' | 'empty' | 'ready' | 'unavailable' | 'error'

function readViewport(map: MapLibreMap): Viewport {
  const { lng: west, lat: south } = map.getBounds().getSouthWest().wrap()
  const { lng: east, lat: north } = map.getBounds().getNorthEast().wrap()
  const bbox = west < east ? [west, south, east, north] : [-180, south, 180, north]
  return { zoom: map.getZoom(), bbox: bbox.map((value) => value.toFixed(6)).join(',') }
}

function LayerToggle({ layer, map, view, wardId, realMap, authority, onUnauthorized, onHide }: {
  layer: OverlayKey
  map: MapLibreMap | null
  view: Viewport | null
  wardId: string | null
  realMap: boolean
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
  const archive = !realMap ? undefined : layer === 'cells' ? config.cellTiles : layer === 'points' ? config.pointTiles : undefined
  const buildingView = layer === 'buildings' ? view?.bbox : undefined
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
    let vectorSource = false
    const canFallback = !fallback && Boolean(archive && layer === 'cells')

    function failed(error?: unknown) {
      if (controller.signal.aborted) return
      if (isUnauthorized(error)) { onUnauthorized(); return }
      if (canFallback) {
        onHide(layer)
        setFallback(true)
      }
      else setStatus('error')
    }

    async function install(current: MapLibreMap) {
      let source: SourceSpecification
      if (archive && !fallback) {
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
      for (const style of [...makeOverlayLayers(layer, vector, opacityRef.current / 100), ...overlaySelection(layer, vector)]) {
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
      if (!vectorSource) return
      const layers = overlayHitLayers(layer).filter((id) => map.getLayer(id))
      if (!layers.length) return
      const visibleCount = map.queryRenderedFeatures({ layers }).length
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
    }
  }, [allowed, archive, atZoom, attempt, buildingView, cellWard, enabled, fallback, layer, map, onHide, onUnauthorized, session])

  const changeOpacity = (value: number) => {
    setOpacity(value)
    opacityRef.current = value
    if (!map) return
    for (const id of [...overlayHitLayers(layer), overlayLayerId(layer) + '-hatch']) {
      const style = map.getLayer(id)
      if (style?.type === 'circle') {
        map.setPaintProperty(id, 'circle-opacity', value / 100)
        map.setPaintProperty(id, 'circle-stroke-opacity', value / 100)
      } else if (style?.type === 'fill') {
        map.setPaintProperty(id, 'fill-opacity', value / 100)
      }
    }
  }

  const detail = {
    off: 'Hidden',
    zoom: `Zoom to level ${spec.zoom} to display`,
    loading: 'Loading layer…',
    empty: 'No features returned for this view',
    ready: layer === 'buildings' ? 'Viewport query · up to 500 buildings' : spec.description,
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

export default memo(function MapLayers({ map, wardId, realMap, authority, onUnauthorized, onHide, theme, onTheme, visible }: {
  map: MapLibreMap | null
  wardId: string | null
  realMap: boolean
  authority: AuthoritySession | null
  onUnauthorized: () => void
  onHide: (layer: OverlayKey) => void
  theme: 'auto' | 'street' | 'dark'
  onTheme: (theme: 'auto' | 'street' | 'dark') => void
  visible: boolean
}) {
  const [view, setView] = useState<Viewport | null>(null)
  useLayoutEffect(() => {
    if (!map || !visible) return
    const update = () => {
      // Resizes of the hidden overview must not replace the last real viewport.
      if (!map.getContainer().clientWidth || !map.getContainer().clientHeight) return
      const next = readViewport(map)
      setView((previous) => previous?.bbox === next.bbox && previous.zoom === next.zoom ? previous : next)
    }
    update()
    map.on('moveend', update)
    return () => { map.off('moveend', update) }
  }, [map, visible])

  const shared = { map, view, wardId, realMap, authority, onUnauthorized, onHide }
  return <details className="layers-control">
    <summary><Layers3 size={17} /> Layers</summary>
    <div className="layers-popover">
      <label className="basemap-picker">Basemap <select value={theme} onChange={(event) => {
        const value = event.target.value
        onTheme(value === 'dark' || value === 'street' ? value : 'auto')
      }}>
        <option value="auto">Follow appearance</option><option value="street">Light streets</option><option value="dark">Dark streets</option>
      </select></label>
      <LayerToggle layer="cells" {...shared} />
      {(config.mock || authority) && <LayerToggle layer="points" {...shared} />}
      {authority && <LayerToggle layer="buildings" {...shared} />}
    </div>
  </details>
})
