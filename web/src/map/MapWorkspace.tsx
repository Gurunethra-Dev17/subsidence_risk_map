import { useEffect, useRef, useState } from 'react'
import { addProtocol, LngLatBounds, Map as MapLibreMap, NavigationControl, removeProtocol, ScaleControl, setWorkerUrl } from 'maplibre-gl'
import type { LngLat, MapMouseEvent, SourceSpecification } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { LocateFixed, X } from 'lucide-react'
import { PMTiles, Protocol } from 'pmtiles'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { WardGeometry } from '../api/service'
import type { AuthoritySession } from '../api/authority'
import { config } from '../config'
import { scoreBand, showNumber } from '../wardMetrics'
import { loadBasemap } from './basemap'
import type { BasemapStatus } from './basemap'
import { addBounds, hatchId, hatchImage, selectionLayers, wardFill, wardFilter, wardLayers, wardSource } from './wardLayers'
import MapLayers from './MapLayers'
import { describeFeature, featureKey, overlayKeys, overlayLayerId, overlaySettings } from './overlayLayers'
import type { MapFeature, OverlayKey } from './overlayLayers'

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

export default function MapWorkspace({ geometry, selection, onSelect, authority, onUnauthorized }: {
  geometry: WardGeometry | null
  selection: Selection | null
  onSelect: (id: string, origin: Selection['origin']) => void
  authority: AuthoritySession | null
  onUnauthorized: () => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const overview = useRef<LngLatBounds | null>(null)
  const camera = useRef<{ center: LngLat; zoom: number } | null>(null)
  const [layerMap, setLayerMap] = useState<MapLibreMap | null>(null)
  const [theme, setTheme] = useState<'street' | 'dark'>('street')
  const [feature, setFeature] = useState<MapFeature | null>(null)
  const [ready, setReady] = useState(false)
  const [mapError, setMapError] = useState(false)
  const [basemap, setBasemap] = useState<BasemapStatus>('loading')
  const [hover, setHover] = useState<Hover | null>(null)
  const [focusMiss, setFocusMiss] = useState<string | null>(null)
  const tiles = config.mock ? undefined : config.wardTiles
  const hasGeometry = Boolean(geometry?.features.length || tiles)

  useEffect(() => {
    const element = container.current
    if (!hasGeometry || !element) return

    const controller = new AbortController()
    let instance: MapLibreMap | undefined
    const protocol = new Protocol({ metadata: true })
    addProtocol('pmtiles', protocol.tile)

    async function mount(element: HTMLDivElement) {
      const bounds = new LngLatBounds()
      const basePromise = loadBasemap(controller.signal, theme)
      let source: SourceSpecification
      if (tiles) {
        const url = new URL(tiles, window.location.href).href
        const archive = new PMTiles(url)
        const header = await archive.getHeader()
        if (controller.signal.aborted) return
        protocol.add(archive)
        source = { type: 'vector', url: 'pmtiles://' + url }
        bounds.extend([header.minLon, header.minLat]).extend([header.maxLon, header.maxLat])
      } else if (geometry) {
        source = { type: 'geojson', data: geometry, attribution: 'Synthetic ward fixtures' }
        for (const feature of geometry.features) addBounds(bounds, feature.geometry)
      } else {
        return
      }
      const base = await basePromise
      if (controller.signal.aborted) return

      const current = new MapLibreMap({
        container: element,
        style: base.style,
        ...(camera.current ?? { bounds: bounds.isEmpty() ? undefined : bounds }),
        fitBoundsOptions: { padding: 55, maxZoom: 14, duration: 0 },
        attributionControl: { compact: true },
        maxZoom: 19,
        renderWorldCopies: false,
        dragRotate: false,
        touchPitch: false,
        cooperativeGestures: true,
      })
      instance = current
      map.current = current
      overview.current = bounds
      setBasemap(base.status)
      current.addControl(new NavigationControl({ showCompass: false }), 'top-right')
      current.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')

      let installingWards = false
      current.on('error', (event) => {
        if (controller.signal.aborted) return
        const sourceId = 'sourceId' in event ? event.sourceId : undefined
        if (typeof sourceId === 'string' && sourceId.startsWith('overlay-')) return
        if (sourceId === wardSource || installingWards || base.status !== 'available') {
          reportError(event.error)
        } else {
          // Basemap requests fail independently of the public ward overlay.
          setBasemap('degraded')
        }
      })
      current.once('style.load', () => {
        if (controller.signal.aborted) return
        installingWards = true
        try {
          current.addSource(wardSource, source)
          current.addImage(hatchId, hatchImage())
          const labels = base.style.layers.find((layer) => layer.type === 'symbol')?.id
          for (const layer of wardLayers(Boolean(tiles))) current.addLayer(layer, labels)
          const hitTest = (event: MapMouseEvent) => {
            const layers = [...overlayKeys.map(overlayLayerId), wardFill].filter((id) => current.getLayer(id))
            const hits = current.queryRenderedFeatures(event.point, { layers })
            const layer = overlayKeys.find((key) => hits.some((hit) => hit.layer.id === overlayLayerId(key)))
            const overlay = layer && hits.find((hit) => hit.layer.id === overlayLayerId(layer))
            return {
              feature: layer && overlay ? describeFeature(layer, overlay.properties) : null,
              ward: hits.find((hit) => hit.layer.id === wardFill)?.properties,
            }
          }
          current.on('mousemove', (event) => {
            const hit = hitTest(event)
            current.getCanvas().style.cursor = hit.feature || hit.ward ? 'pointer' : ''
            const point = { x: event.point.x, y: event.point.y }
            if (hit.feature) {
              setHover({ ...point, label: hit.feature.id, detail: hit.feature.fields[0].value, layer: hit.feature.layer })
            } else if (typeof hit.ward?.ward_name === 'string') {
              const band = scoreBand(hit.ward.status, hit.ward.score)
              setHover({ ...point, label: hit.ward.ward_name,
                detail: band.label + (typeof hit.ward.score === 'number' ? ' · ' + showNumber(hit.ward.score) + '/100' : '') })
            } else setHover(null)
          })
          current.on('mouseout', () => {
            current.getCanvas().style.cursor = ''
            setHover(null)
          })
          current.on('movestart', () => setHover(null))
          current.on('click', (event) => {
            const hit = hitTest(event)
            setHover(null)
            if (hit.feature) setFeature(hit.feature)
            else if (typeof hit.ward?.ward_id === 'string') {
              setFeature(null)
              onSelect(hit.ward.ward_id, 'map')
            }
          })
          setLayerMap(current)
          setReady(true)
        } catch (error) {
          reportError(error)
        } finally {
          installingWards = false
        }
      })
    }

    function reportError(error: unknown) {
      if (controller.signal.aborted) return
      console.error('Ward map failed to load', error)
      setMapError(true)
    }

    void mount(element).catch(reportError)
    return () => {
      controller.abort()
      instance?.remove()
      map.current = null
      removeProtocol('pmtiles')
    }
  }, [geometry, hasGeometry, onSelect, theme, tiles])

  const visibleFeature = feature && (authority || feature.layer === 'cells' || (config.mock && feature.layer === 'points')) ? feature : null
  useEffect(() => {
    if (!authority) {
      setFeature((previous) => previous?.layer === 'buildings' || (!config.mock && previous?.layer === 'points') ? null : previous)
      setHover((previous) => previous?.layer === 'buildings' || (!config.mock && previous?.layer === 'points') ? null : previous)
    }
  }, [authority])

  useEffect(() => {
    if (!layerMap) return
    for (const key of overlayKeys) {
      const layer = overlayLayerId(key) + '-selection'
      if (layerMap.getLayer(layer)) {
        layerMap.setFilter(layer, visibleFeature?.layer === key ? ['==', ['get', featureKey[key]], visibleFeature.id] : false)
      }
    }
  }, [layerMap, visibleFeature])

  useEffect(() => {
    const current = map.current
    if (!ready || !current) return
    const id = selection?.id ?? null
    for (const layer of selectionLayers) current.setFilter(layer, wardFilter(id))
    if (!id || selection?.origin !== 'ranking') return

    const synthetic = geometry?.features.find((feature) => feature.properties.ward_id === id)
    const focus = (bounds: LngLatBounds) => {
      if (bounds.isEmpty()) return false
      setFocusMiss(null)
      current.fitBounds(bounds, { padding: 62, maxZoom: 15.5, duration: 500 })
      return true
    }
    if (synthetic && focus(addBounds(new LngLatBounds(), synthetic.geometry))) return
    if (!tiles) return
    if (focus(featureBounds(current, id))) return
    // Return to the archive overview to load tiles that may be outside the current viewport.
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      current.off('idle', finish)
      clearTimeout(timeout)
      if (!focus(featureBounds(current, id))) setFocusMiss(id)
    }
    const timeout = window.setTimeout(finish, 2500)
    current.once('idle', finish)
    const bounds = overview.current
    if (bounds && !bounds.isEmpty()) current.fitBounds(bounds, { padding: 55, maxZoom: 14, duration: 0 })
    return () => {
      settled = true
      clearTimeout(timeout)
      current.off('idle', finish)
    }
  }, [geometry, ready, selection, tiles])

  const resetView = () => {
    const bounds = overview.current
    setFocusMiss(null)
    if (bounds && !bounds.isEmpty()) map.current?.fitBounds(bounds, { padding: 55, maxZoom: 14, duration: 350 })
  }

  return (
    <>
      <div className="map-canvas" ref={container} aria-label="Map of ward inspection priorities" />
      {hasGeometry && <MapLayers map={layerMap} wardId={selection?.id ?? null} authority={authority} onUnauthorized={onUnauthorized}
        theme={theme} onTheme={(next) => {
          if (next === theme) return
          const current = map.current
          if (current) camera.current = { center: current.getCenter(), zoom: current.getZoom() }
          setLayerMap(null)
          setReady(false)
          setMapError(false)
          setHover(null)
          setFeature(null)
          setTheme(next)
        }}
        onHide={(key) => {
          if (feature?.layer === key) setFeature(null)
          if (hover?.layer === key) setHover(null)
        }} />}
      {!hasGeometry && <p className="map-message">No ward boundaries are available.</p>}
      {hasGeometry && !ready && !mapError && <p className="map-message" role="status">Loading ward map…</p>}
      {mapError && <p className="map-message" role="alert">Ward map unavailable. Use the ranking table to inspect wards.</p>}
      {ready && !mapError && (
        <>
          <button type="button" className="map-reset" title="Reset map view" onClick={resetView} aria-label="Reset map view">
            <LocateFixed size={17} />
          </button>
          {basemap === 'fallback' && <span className="map-note" role="status">Street basemap unavailable</span>}
          {basemap === 'degraded' && <span className="map-note" role="status">Some basemap detail is unavailable</span>}
          {focusMiss === selection?.id && focusMiss && <span className="map-note map-note-focus" role="status">Selected ward was outside loaded tiles</span>}
          {hover && (authority || hover.layer !== 'buildings') && (config.mock || authority || hover.layer !== 'points') && (
            <div className="map-tooltip" role="tooltip" style={{
              left: Math.min(hover.x + 13, (container.current?.clientWidth ?? 215) - 198),
              top: Math.max(10, hover.y - 64),
            }}>
              <strong>{hover.label}</strong>
              <span>{hover.detail}</span>
            </div>
          )}
        </>
      )}
      {visibleFeature && <section className="map-feature" aria-label="Selected map feature">
        <div><strong>{overlaySettings[visibleFeature.layer].label} · {visibleFeature.id}</strong>
          <button type="button" className="icon-button" aria-label="Clear map feature" onClick={() => setFeature(null)}><X size={15} /></button></div>
        <dl>{visibleFeature.fields.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </section>}
    </>
  )
}
