import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { buildingLayerId, buildingZoom } from './buildings'

export const cityPitch = 44
export const cityBearing = -18

export function useCityPerspective(map: MapLibreMap | null, lost: boolean, visible: boolean) {
  const [preferred, setPreferred] = useState<'2d' | '3d'>('3d')
  const [coverage, setCoverage] = useState<'pending' | 'unsupported' | 'zoom' | 'missing' | 'available'>('pending')
  const applied = useRef<{ map: MapLibreMap; active: boolean } | null>(null)

  useLayoutEffect(() => {
    if (!map || lost || !visible) return
    const layer = map.getLayer(buildingLayerId)
    if (!layer) {
      setCoverage('unsupported')
      return
    }
    map.setLayoutProperty(buildingLayerId, 'visibility', preferred === '3d' ? 'visible' : 'none')
    if (preferred === '2d') return

    const checkView = () => {
      if (!map.getLayer(buildingLayerId)) setCoverage('unsupported')
      else if (map.getZoom() < buildingZoom) setCoverage('zoom')
      else setCoverage(map.queryRenderedFeatures({ layers: [buildingLayerId] }).length ? 'available' : 'missing')
    }
    map.on('idle', checkView)
    return () => { map.off('idle', checkView) }
  }, [lost, map, preferred, visible])

  const active = !lost && preferred === '3d' && coverage === 'available'
  useEffect(() => {
    if (!map || lost || !visible) return
    if (applied.current?.map === map && applied.current.active === active) return
    applied.current = { map, active }
    if (active) {
      map.dragRotate.enable()
      map.touchPitch.enable()
      map.touchZoomRotate.enableRotation()
    } else {
      map.dragRotate.disable()
      map.touchPitch.disable()
      map.touchZoomRotate.disableRotation()
    }
    map.easeTo({
      pitch: active ? cityPitch : 0,
      bearing: active ? cityBearing : 0,
      duration: 420,
    })
  }, [active, lost, map, visible])

  function change(next: '2d' | '3d') {
    setPreferred(next)
    if (next === '3d' && map?.getLayer(buildingLayerId) && map.getZoom() < buildingZoom) {
      map.easeTo({ zoom: buildingZoom + 0.25, duration: 350 })
    }
  }

  return { active, preferred, change, coverage }
}
