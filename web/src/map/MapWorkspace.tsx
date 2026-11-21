import { useEffect, useRef, useState } from 'react'
import { addProtocol, Map, NavigationControl, removeProtocol, ScaleControl, setWorkerUrl } from 'maplibre-gl'
import type { GeoJSONSource, SourceSpecification, StyleSpecification } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { PMTiles, Protocol } from 'pmtiles'
import type { Header } from 'pmtiles'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { WardGeometry } from '../api/service'
import { config } from '../config'

// Vite moves the map bundle, so use the URL of the worker it emits.
setWorkerUrl(workerUrl)

function mapStyle(source: SourceSpecification): StyleSpecification {
  const vectorLayer = source.type === 'vector' ? { 'source-layer': 'wards' } : {}
  return {
    version: 8,
    sources: {
      wards: source,
      ...(config.basemapTiles && config.basemapAttribution ? {
        basemap: {
          type: 'raster',
          tiles: [config.basemapTiles],
          tileSize: 256,
          attribution: config.basemapAttribution,
        },
      } : {}),
    },
    layers: [
      ...(config.basemapTiles && config.basemapAttribution ? [{
        id: 'basemap', type: 'raster' as const, source: 'basemap',
        paint: { 'raster-opacity': 0.76, 'raster-saturation': -0.85 },
      }] : []),
      {
        id: 'ward-fill', type: 'fill', source: 'wards', ...vectorLayer,
        paint: { 'fill-color': '#79b3ac', 'fill-opacity': 0.46 },
      },
      {
        id: 'ward-outline', type: 'line', source: 'wards', ...vectorLayer,
        paint: { 'line-color': '#20645e', 'line-width': 2 },
      },
    ],
  }
}

export default function MapWorkspace({ geometry }: { geometry: WardGeometry | null }) {
  const container = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const tiles = config.mock ? undefined : config.wardTiles
  const hasGeometry = Boolean(geometry?.features.length || tiles)

  useEffect(() => {
    const element = container.current
    if (!hasGeometry || !element) return

    let active = true
    let map: Map | undefined
    let protocol: Protocol | undefined

    async function mountMap(element: HTMLDivElement) {
      let source: SourceSpecification
      let header: Header | undefined
      if (tiles) {
        const url = new URL(tiles, window.location.href).href
        const archive = new PMTiles(url)
        header = await archive.getHeader()
        if (!active) return
        protocol = new Protocol({ metadata: true })
        protocol.add(archive)
        addProtocol('pmtiles', protocol.tile)
        source = { type: 'vector', url: `pmtiles://${url}` }
      } else if (geometry) {
        source = { type: 'geojson', data: geometry, attribution: 'Synthetic contract fixture' }
      } else {
        return
      }

      const instance = new Map({
        container: element,
        style: mapStyle(source),
        bounds: header
          ? [header.minLon, header.minLat, header.maxLon, header.maxLat]
          : undefined,
        fitBoundsOptions: { padding: 42, maxZoom: 15, duration: 0 },
        maxZoom: 19,
        renderWorldCopies: false,
        dragRotate: false,
        touchPitch: false,
        cooperativeGestures: true,
      })
      map = instance
      instance.addControl(new NavigationControl({ showCompass: false }), 'top-right')
      instance.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
      instance.on('error', ({ error }) => reportError(error))
      instance.once('load', async () => {
        if (geometry && !tiles) {
          try {
            const bounds = await instance.getSource<GeoJSONSource>('wards')?.getBounds()
            if (active && bounds && !bounds.isEmpty()) {
              instance.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 })
            }
          } catch (error) {
            reportError(error)
            return
          }
        }
        if (active) setStatus((current) => current === 'error' ? current : 'ready')
      })
    }

    function reportError(error: unknown) {
      if (!active) return
      console.error('Ward map failed to load', error)
      setStatus('error')
    }

    void mountMap(element).catch(reportError)
    return () => {
      active = false
      map?.remove()
      if (protocol) removeProtocol('pmtiles')
    }
  }, [geometry, hasGeometry, tiles])

  return (
    <>
      <div className="map-canvas" ref={container} aria-label="Interactive map of ward boundaries" />
      {!hasGeometry && <div className="map-message">No ward boundaries are available.</div>}
      {hasGeometry && status === 'loading' && <div className="map-message" role="status">Loading map…</div>}
      {hasGeometry && status === 'error' && <div className="map-message" role="alert">Unable to load the map. Ward summaries remain available.</div>}
    </>
  )
}
