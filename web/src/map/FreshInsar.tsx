import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ImageSource, Map as MapLibreMap } from 'maplibre-gl'
import { loadFreshInsar } from './freshInsarData'
import { wardOutline } from './wardLayers'

const sourceId = 'overlay-fresh-insar'
const rasterId = sourceId + '-raster'
const label = 'Fresh InSAR Observation'
type Observation = Awaited<ReturnType<typeof loadFreshInsar>>
const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'long', timeZone: 'UTC' })
const signed = (value: number) => `${value < 0 ? '−' : '+'}${Math.abs(value).toFixed(3)}`

function ObservationDetails({ manifest }: { manifest: Observation['manifest'] }) {
  return <>
    <figure className="fresh-insar-legend" aria-label="Relative LOS displacement (cm)">
      <figcaption>Relative LOS displacement (cm)</figcaption>
      <div className="fresh-insar-scale" aria-hidden="true" />
      <div className="fresh-insar-labels">
        <span>≤ {signed(manifest.lower)} cm<br />Away</span>
        <span>0 cm<br />Midpoint</span>
        <span>≥ {signed(manifest.upper)} cm<br />Toward</span>
      </div>
    </figure>
    <p>Negative is away from the sensor and positive is toward it. Transparent areas indicate missing or masked observations.</p>
    <details className="fresh-insar-details">
      <summary>Observation details and limitations</summary>
      <p><strong>Sentinel-1</strong> <span className="fresh-insar-product">{manifest.product}</span></p>
      <p>Reference {date.format(manifest.reference)}, secondary {date.format(manifest.secondary)}.
        One ascending {manifest.days}-day interferogram, {manifest.polarization} polarization, 80 m product spacing.
        Exploratory coherence threshold {manifest.threshold.toFixed(2)}.</p>
      <p>The nominal footprint overlaps {manifest.footprint.toFixed(1)}% of the 2022 Delhi ward area.
        Usable pixels intersect {manifest.usable.toFixed(1)}% of that area. Of 250 wards, 49 have usable observations and 201 have none.</p>
      <p>Usable area in Bijwasan (131) is {manifest.bijwasan.toFixed(1)}% (1,317 usable pixel centers).
        Mahipalpur (133) has {manifest.mahipalpur.toFixed(1)}% (1,113 usable pixel centers).</p>
      <p>The display uses a symmetric 98th-percentile scale. Out-of-scale values saturate at the endpoint colors.
        The display-grid measurements range from {signed(manifest.minimum)} to {signed(manifest.maximum)} cm.
        The visualization leaves the underlying masked GeoTIFF values unclipped.</p>
      <p>Relative line-of-sight displacement is derived from unwrapped phase and cannot be interpreted as vertical subsidence.
        The team has yet to independently verify the phase reference stability or cross-check the result against ground truth or
        historical patterns and signs. The result covers 12 days and has no annualized rate.</p>
      <p>Processing omitted atmospheric correction and disabled the water mask during unwrapping.
        Phase-unwrapping errors are possible. The relative orbit and perpendicular baseline are unreported.
        Observations require valid phase, coherence and connected-component support.</p>
      <p>Missing observations establish neither zero movement nor safe conditions. Ward and cell priorities use the existing C2 evidence.</p>
      <p>{manifest.attribution}</p>
    </details>
  </>
}

export default function FreshInsar({ map }: { map: MapLibreMap | null }) {
  const [enabled, setEnabled] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [observation, setObservation] = useState<Observation | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [renderStatus, setRenderStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const cached = useRef<Observation | null>(null)

  useEffect(() => () => { cached.current?.image.close() }, [])

  useEffect(() => {
    if (!enabled || cached.current) return
    const controller = new AbortController()
    void loadFreshInsar(controller.signal).then((result) => {
      if (controller.signal.aborted) {
        result.image.close()
        return
      }
      cached.current = result
      setObservation(result)
    }).catch(() => { if (!controller.signal.aborted) setLoadError(true) })
    return () => controller.abort()
  }, [attempt, enabled])

  useLayoutEffect(() => {
    if (!enabled || !map || !observation) return
    const cleanup = () => {
      if (map.getLayer(rasterId)) map.removeLayer(rasterId)
      if (map.getSource(sourceId)) map.removeSource(sourceId)
    }
    let failed = false
    const onError = (event: object) => {
      if ('sourceId' in event && event.sourceId === sourceId) {
        failed = true
        setRenderStatus('error')
      }
    }
    map.on('error', onError)
    try {
      map.addSource(sourceId, { type: 'image', coordinates: observation.manifest.coordinates })
      const source = map.getSource<ImageSource>(sourceId)
      if (!source || !map.getLayer(wardOutline)) throw new Error('The observation layer could not be installed.')
      map.addLayer({
        id: rasterId, type: 'raster', source: sourceId,
        paint: { 'raster-resampling': 'nearest', 'raster-fade-duration': 0 },
      }, wardOutline)
      source.updateImage({ image: observation.image })
      if (failed || !map.getLayer(rasterId)) throw new Error('The observation image could not be installed.')
      setRenderStatus('ready')
    } catch {
      cleanup()
      setRenderStatus('error')
    }
    return () => {
      map.off('error', onError)
      cleanup()
    }
  }, [attempt, enabled, map, observation])

  const unavailable = loadError || renderStatus === 'error'
  const ready = Boolean(map && observation && renderStatus === 'ready')
  return <div className="layer-row">
    <label className="layer-name"><input type="checkbox" checked={enabled} onChange={(event) => {
      setLoadError(false)
      setRenderStatus('loading')
      setEnabled(event.target.checked)
    }} />{label}</label>
    {enabled && <p role="status">{unavailable ? 'Fresh observation could not be loaded.' :
      ready ? 'Internal preview · one 12-day observation' : 'Loading fresh observation…'}</p>}
    {enabled && unavailable && <button type="button" className="text-button" onClick={() => {
      setLoadError(false)
      setRenderStatus('loading')
      setAttempt((count) => count + 1)
    }}>Retry observation</button>}
    {enabled && ready && !unavailable && observation && <ObservationDetails manifest={observation.manifest} />}
  </div>
}
