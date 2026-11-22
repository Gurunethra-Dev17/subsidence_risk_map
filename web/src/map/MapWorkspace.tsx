import { useCallback, useEffect, useRef, useState } from 'react'
import { addProtocol, LngLatBounds, Map as MapLibreMap, NavigationControl, removeProtocol, ScaleControl, setWorkerUrl } from 'maplibre-gl'
import type { MapMouseEvent, SourceSpecification } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { LocateFixed, RotateCcw, RotateCw, X } from 'lucide-react'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { WardGeometry } from '../api/service'
import type { AuthoritySession } from '../api/authority'
import { isDelhiWardId } from '../api/delhiMap'
import { config } from '../config'
import { scoreBand, showNumber } from '../wardMetrics'
import { loadBasemap, neutralBasemap } from './basemap'
import type { BasemapStatus } from './basemap'
import { addBounds, hatchId, hatchImage, selectionLayers, wardFill, wardFilter, wardLayers, wardSource } from './wardLayers'
import MapLayers from './MapLayers'
import { describeFeature, featureKey, overlayHitLayers, overlayKeys, overlaySettings } from './overlayLayers'
import type { MapFeature, OverlayKey } from './overlayLayers'
import { cityBearing, cityPitch, useCityPerspective } from './useCityPerspective'
import WardPlan from './WardPlan'

setWorkerUrl(workerUrl)

type Selection = { id: string; origin: 'map' | 'ranking' }
type Hover = { x: number; y: number; label: string; detail: string; layer?: OverlayKey }

function featureBounds(map: MapLibreMap, id: string) {
  const bounds = new LngLatBounds()
  const features = map.querySourceFeatures(wardSource, { sourceLayer: 'wards', filter: wardFilter(id) })
  for (const { geometry } of features) {
    if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') addBounds(bounds, geometry)
  }
  return bounds
}

function hitTest(map: MapLibreMap, event: MapMouseEvent) {
  const layers = [...overlayKeys.flatMap(overlayHitLayers), wardFill].filter((id) => map.getLayer(id))
  if (!layers.length) return {}
  const hits = map.queryRenderedFeatures(event.point, { layers })
  for (const key of overlayKeys) {
    const ids = overlayHitLayers(key)
    const hit = hits.find((item) => ids.includes(item.layer.id))
    const feature = hit && describeFeature(key, hit.properties)
    if (feature) return { feature }
  }
  return { ward: hits.find((hit) => hit.layer.id === wardFill)?.properties }
}

export default function MapWorkspace({ geometry, wardTiles, realMap, selection, onSelect, authority, onUnauthorized, appearance }: {
  geometry: WardGeometry | null
  wardTiles?: string
  realMap: boolean
  selection: Selection | null
  onSelect: (id: string, origin: Selection['origin']) => void
  authority: AuthoritySession | null
  onUnauthorized: () => void
  appearance: 'light' | 'dark'
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const overview = useRef<LngLatBounds | null>(null)
  const [instance, setInstance] = useState<MapLibreMap | null>(null)
  const [layerMap, setLayerMap] = useState<MapLibreMap | null>(null)
  const [override, setOverride] = useState<'auto' | 'street' | 'dark'>('auto')
  const theme = override === 'auto' ? (appearance === 'dark' ? 'dark' : 'street') : override
  const initialTheme = useRef(theme)
  const [styleChange, setStyleChange] = useState<Awaited<ReturnType<typeof loadBasemap>> | null>(null)
  const appliedStyle = useRef<typeof styleChange>(null)
  const lastFocused = useRef<Selection | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [feature, setFeature] = useState<MapFeature | null>(null)
  const [mapError, setMapError] = useState(false)
  const [archiveError, setArchiveError] = useState<string | null>(null)
  const { active, preferred, change, coverage } = useCityPerspective(layerMap, mapError)
  const [basemap, setBasemap] = useState<BasemapStatus>('loading')
  const [hover, setHover] = useState<Hover | null>(null)
  const [focusMiss, setFocusMiss] = useState<string | null>(null)
  const tiles = wardTiles
  const hasGeometry = Boolean(geometry?.features.length || tiles)

  useEffect(() => {
    const element = container.current
    if (!hasGeometry || !element) return
    const controller = new AbortController()
    let ownedMap: MapLibreMap | undefined
    let hoverFrame = 0
    let lastPointer: MapMouseEvent | null = null
    let hasProtocol = false

    const reportError = () => {
      if (!controller.signal.aborted) {
        setLayerMap(null)
        setMapError(true)
      }
    }
    const reportArchiveError = (message: string) => {
      if (!controller.signal.aborted) setArchiveError(message)
      reportError()
    }

    async function mount(element: HTMLDivElement) {
      const bounds = new LngLatBounds()
      let source: SourceSpecification
      const library = realMap && (tiles || config.cellTiles || config.pointTiles) ? await import('pmtiles') : null
      if (controller.signal.aborted) return
      const protocol = library && new library.Protocol({ metadata: true })
      if (protocol) {
        addProtocol('pmtiles', protocol.tile)
        hasProtocol = true
      }
      if (tiles && library && protocol) {
        const url = new URL(tiles, window.location.href).href
        const archive = new library.PMTiles(url)
        const [header, metadata] = await Promise.all([archive.getHeader(), archive.getMetadata()]).catch(() => [null, null] as const)
        if (controller.signal.aborted) return
        if (!header || !metadata) {
          reportArchiveError('The configured Delhi ward PMTiles could not be loaded.')
          return
        }
        const { vector_layers: layers } = metadata as { vector_layers?: { id?: string }[] }
        if (header.tileType !== library.TileType.Mvt || !Array.isArray(layers) || !layers.some((layer) => layer?.id === 'wards')) {
          reportArchiveError('Dataset mismatch. The ward archive must contain the C5 wards source layer.')
          return
        }
        protocol.add(archive)
        source = { type: 'vector', url: 'pmtiles://' + url }
        bounds.extend([header.minLon, header.minLat]).extend([header.maxLon, header.maxLat])
      } else if (geometry) {
        source = { type: 'geojson', data: geometry, ...(realMap ? {} : { attribution: 'Synthetic ward fixtures' }) }
        for (const feature of geometry.features) addBounds(bounds, feature.geometry)
      } else return

      const current = new MapLibreMap({
        container: element,
        style: neutralBasemap(initialTheme.current),
        bounds: bounds.isEmpty() ? undefined : bounds,
        fitBoundsOptions: { padding: 55, maxZoom: 14, duration: 0 },
        attributionControl: { compact: true },
        maxZoom: 19,
        renderWorldCopies: false,
        dragRotate: false,
        touchPitch: false,
        maxPitch: 58,
        cooperativeGestures: true,
      })
      ownedMap = current
      map.current = current
      overview.current = bounds
      current.addControl(new NavigationControl({ showCompass: true }), 'top-right')
      current.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')

      let installingWards = false
      current.on('webglcontextlost', reportError)
      current.on('error', (event) => {
        const sourceId = 'sourceId' in event ? event.sourceId : undefined
        if (controller.signal.aborted || (typeof sourceId === 'string' && sourceId.startsWith('overlay-'))) return
        if (sourceId === wardSource && tiles) reportArchiveError('The configured Delhi ward PMTiles could not be loaded.')
        else if (sourceId === wardSource || installingWards) reportError()
        else setBasemap('degraded')
      })
      current.on('style.load', () => {
        if (controller.signal.aborted) return
        installingWards = true
        try {
          current.addSource(wardSource, source)
          current.addImage(hatchId, hatchImage())
          const labels = current.getStyle().layers.find((layer) => layer.type === 'symbol')?.id
          for (const layer of wardLayers(Boolean(tiles))) current.addLayer(layer, labels)
          setInstance(current)
          setLayerMap(current)
        } catch {
          reportError()
        } finally {
          installingWards = false
        }
      })
      const clearHover = () => {
        lastPointer = null
        current.getCanvas().style.cursor = ''
        setHover(null)
      }
      current.on('mousemove', (event) => {
        lastPointer = event
        if (hoverFrame) return
        hoverFrame = requestAnimationFrame(() => {
          hoverFrame = 0
          if (!lastPointer) return
          const { feature, ward } = hitTest(current, lastPointer)
          current.getCanvas().style.cursor = feature || ward ? 'pointer' : ''
          const { x, y } = lastPointer.point
          if (feature) {
            setHover({ x, y, label: feature.id, detail: feature.fields[0].value, layer: feature.layer })
          } else if (typeof ward?.ward_name === 'string' && (!realMap || isDelhiWardId(ward.ward_id))) {
            const band = scoreBand(ward.status, ward.score)
            setHover({ x, y, label: ward.ward_name,
              detail: band.label + (typeof ward.score === 'number' && band.id !== 'insufficient' && band.id !== 'unavailable'
                ? ' · ' + showNumber(ward.score) + '/100' : '') })
          } else setHover(null)
        })
      })
      current.on('mouseout', clearHover)
      current.on('movestart', clearHover)
      current.on('click', (event) => {
        const { feature, ward } = hitTest(current, event)
        clearHover()
        if (feature) setFeature(feature)
        else if (typeof ward?.ward_id === 'string' && (!realMap || isDelhiWardId(ward.ward_id))) {
          setFeature(null)
          onSelect(ward.ward_id, 'map')
        }
      })
    }

    void mount(element).catch(reportError)
    return () => {
      controller.abort()
      cancelAnimationFrame(hoverFrame)
      ownedMap?.remove()
      map.current = null
      appliedStyle.current = null
      lastFocused.current = null
      if (hasProtocol) removeProtocol('pmtiles')
    }
  }, [attempt, geometry, hasGeometry, onSelect, realMap, tiles])

  useEffect(() => {
    if (!instance || instance !== map.current) return
    const controller = new AbortController()
    void loadBasemap(controller.signal, theme).then((result) => {
      if (controller.signal.aborted) return
      setBasemap(result.status)
      if (!appliedStyle.current && theme === initialTheme.current && result.status !== 'available') return
      setLayerMap(null)
      setStyleChange(result)
    })
    return () => controller.abort()
  }, [instance, theme])

  useEffect(() => {
    if (!styleChange || !instance || instance !== map.current || appliedStyle.current === styleChange) return
    appliedStyle.current = styleChange
    instance.setStyle(styleChange.style, { diff: false })
    const timeout = window.setTimeout(() => {
      if (instance !== map.current || instance.getSource(wardSource)) return
      setBasemap('fallback')
      instance.setStyle(neutralBasemap(theme), { diff: false })
    }, 5000)
    return () => window.clearTimeout(timeout)
  }, [instance, styleChange, theme])

  const hideFeature = useCallback((key: OverlayKey) => {
    setFeature((value) => value?.layer === key ? null : value)
    setHover((value) => value?.layer === key ? null : value)
  }, [])
  const visibleFeature = feature && (authority || feature.layer === 'cells' || (config.mock && feature.layer === 'points')) ? feature : null
  useEffect(() => {
    if (!authority) {
      hideFeature('buildings')
      if (!config.mock) hideFeature('points')
    }
  }, [authority, hideFeature])

  useEffect(() => {
    if (!layerMap) return
    for (const key of overlayKeys) {
      for (const id of overlayHitLayers(key)) {
        const layer = id + '-selection'
        if (layerMap.getLayer(layer)) {
          layerMap.setFilter(layer, visibleFeature?.layer === key ? ['==', ['get', featureKey[key]], visibleFeature.id] : false)
        }
      }
    }
  }, [layerMap, visibleFeature])

  useEffect(() => {
    const current = layerMap
    if (!current) return
    for (const layer of selectionLayers) current.setFilter(layer, wardFilter(selection?.id ?? null))
    if (selection?.origin !== 'ranking' || lastFocused.current === selection) return

    const focus = (bounds: LngLatBounds) => {
      if (bounds.isEmpty()) return false
      lastFocused.current = selection
      setFocusMiss(null)
      current.fitBounds(bounds, { padding: 62, maxZoom: 15.5, duration: 500,
        pitch: current.getPitch(), bearing: current.getBearing() })
      return true
    }
    const boundary = geometry?.features.find((feature) => feature.properties.ward_id === selection.id)
    if (boundary && focus(addBounds(new LngLatBounds(), boundary.geometry))) return
    if (!tiles || focus(featureBounds(current, selection.id))) return

    const finish = () => {
      current.off('idle', finish)
      clearTimeout(timeout)
      if (!focus(featureBounds(current, selection.id))) setFocusMiss(selection.id)
    }
    const timeout = window.setTimeout(finish, 2500)
    current.once('idle', finish)
    const bounds = overview.current
    if (bounds && !bounds.isEmpty()) current.fitBounds(bounds, { padding: 55, maxZoom: 14, duration: 0 })
    return () => {
      clearTimeout(timeout)
      current.off('idle', finish)
    }
  }, [geometry, layerMap, selection, tiles])

  const resetView = () => {
    const bounds = overview.current
    setFocusMiss(null)
    if (bounds && !bounds.isEmpty()) map.current?.fitBounds(bounds, {
      padding: 55, maxZoom: 14, duration: 350, pitch: active ? cityPitch : 0, bearing: active ? cityBearing : 0,
    })
  }
  const shown3d = active && !mapError
  const perspectiveStatus = {
    available: 'Public building heights may be estimated',
    missing: '2D · no building heights in view',
    unsupported: '2D · building heights unavailable',
    zoom: 'Zoom in for 3D buildings',
    pending: 'Checking for building detail',
  }[coverage]

  return (
    <>
      <div className="map-canvas" ref={container} aria-label="Map of ward inspection priorities"
        data-perspective={shown3d ? '3d' : '2d'} data-basemap={theme} />
      {mapError && geometry && <WardPlan geometry={geometry} synthetic={!realMap} activeId={selection?.id} onSelect={(id) => onSelect(id, 'map')} />}
      {hasGeometry && !mapError && <MapLayers map={layerMap} wardId={selection?.id ?? null} authority={authority} onUnauthorized={onUnauthorized}
        realMap={realMap} theme={override} onTheme={setOverride} onHide={hideFeature} />}
      {!hasGeometry && <p className="map-message">No ward boundaries are available. Ward summaries are accessible from the rankings.</p>}
      {hasGeometry && !instance && !mapError && <p className="map-message" role="status">Loading ward map…</p>}
      {mapError && <div className="map-message plan-message" role="alert">{archiveError ?? (geometry ?
        'Interactive graphics unavailable. The 2D ward plan remains selectable.' :
        'Interactive graphics unavailable. Use the rankings to inspect wards.')}
        <button type="button" className="text-button" onClick={() => {
          setLayerMap(null)
          setStyleChange(null)
          setInstance(null)
          setMapError(false)
          setArchiveError(null)
          setAttempt((count) => count + 1)
        }}>Retry map</button>
      </div>}
      {instance && !mapError && <>
        <button type="button" className="map-reset" title="Reset map view" onClick={resetView} aria-label="Reset map view"><LocateFixed size={17} /></button>
        <div className="city-view-controls" aria-label="Map perspective">
          <div className="perspective-buttons">
            <button type="button" aria-label="2D plan" aria-pressed={preferred === '2d'} onClick={() => change('2d')}>2D</button>
            <button type="button" aria-label="3D buildings" aria-pressed={preferred === '3d'} onClick={() => change('3d')}>3D</button>
            {shown3d && <>
              <button type="button" aria-label="Rotate map left" onClick={() => instance.rotateTo(instance.getBearing() - 30, { duration: 250 })}><RotateCcw size={15} /></button>
              <button type="button" aria-label="Rotate map right" onClick={() => instance.rotateTo(instance.getBearing() + 30, { duration: 250 })}><RotateCw size={15} /></button>
            </>}
          </div>
          <span className="perspective-status" role="status">{preferred === '2d' ? 'Plan view' : perspectiveStatus}</span>
        </div>
        {basemap === 'fallback' && <span className="map-note" role="status">Basemap unavailable · ward data visible</span>}
        {basemap === 'degraded' && <span className="map-note" role="status">Some basemap detail is unavailable</span>}
        {focusMiss && focusMiss === selection?.id && <span className="map-note map-note-focus" role="status">Selected ward was outside loaded tiles</span>}
        {hover && (authority || hover.layer !== 'buildings') && (config.mock || authority || hover.layer !== 'points') && (
          <div className="map-tooltip" role="tooltip" style={{
            left: Math.max(8, Math.min(hover.x + 13, (container.current?.clientWidth ?? 215) - 198)),
            top: Math.max(10, hover.y - 64),
          }}><strong>{hover.label}</strong><span>{hover.detail}</span></div>
        )}
      </>}
      {visibleFeature && !mapError && <section className="map-feature" aria-label="Selected map feature">
        <div><strong>{overlaySettings[visibleFeature.layer].label} · {visibleFeature.id}</strong>
          <button type="button" className="icon-button" aria-label="Clear map feature" onClick={() => setFeature(null)}><X size={15} /></button></div>
        <dl>{visibleFeature.fields.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </section>}
    </>
  )
}
