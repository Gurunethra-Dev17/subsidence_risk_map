import type { ExpressionSpecification, LayerSpecification } from 'maplibre-gl'
import { scoreBands, unavailableBand } from '../wardMetrics'

export const overlaySettings = {
  cells: { label: 'Grid cells', zoom: 8, description: 'Cell Inspection Index · hatching marks suppressed cells' },
  points: { label: 'Radar points', zoom: 10, description: 'Vertical land motion · orange: sinking ≥4 mm/yr · blue: other motion' },
  buildings: { label: 'Buildings', zoom: 13, description: 'Distortion class · blue: low · amber: watch · plum: inspect · grey: unavailable' },
} as const

export type OverlayKey = keyof typeof overlaySettings
export type MapFeature = { layer: OverlayKey; id: string; fields: { label: string; value: string }[] }
const radarColors = { sinking: '#cf621c', other: '#276d9f', missing: '#8796a5' }
const buildingColors = { low: '#559dc2', watch: '#e6b34e', inspect: '#a54b88', missing: '#8796a5' }
export const overlayLegends: Record<OverlayKey, { label: string; color: string; hatch?: boolean }[]> = {
  points: [{ label: 'Sinking ≥4 mm/yr', color: radarColors.sinking }, { label: 'Other motion', color: radarColors.other }, { label: 'Unavailable', color: radarColors.missing }],
  cells: [...scoreBands.map((band) => ({ label: band.range, color: band.color })), { label: 'Suppressed', color: '#8796a5', hatch: true }],
  buildings: [{ label: 'Low', color: buildingColors.low }, { label: 'Watch', color: buildingColors.watch },
    { label: 'Inspect', color: buildingColors.inspect }, { label: 'Unavailable', color: buildingColors.missing }],
}
export const overlayLayerId = (key: OverlayKey) => `overlay-${key}-main`
export const overlaySourceId = (key: OverlayKey) => `overlay-${key}`
export const overlayKeys: OverlayKey[] = ['buildings', 'points', 'cells']
export const featureKey = { cells: 'cell_id', points: 'pt_id', buildings: 'bldg_id' }

export function overlaySelection(key: OverlayKey, vector: boolean): LayerSpecification {
  const base = { id: overlayLayerId(key) + '-selection', source: overlaySourceId(key),
    ...(vector ? { 'source-layer': key } : {}), filter: false as const, minzoom: overlaySettings[key].zoom }
  return key === 'points'
    ? { ...base, type: 'circle', paint: { 'circle-radius': 9, 'circle-opacity': 0, 'circle-stroke-color': '#f9db87', 'circle-stroke-width': 3 } }
    : { ...base, type: 'line', paint: { 'line-color': '#f9db87', 'line-width': 3.5 } }
}

export function makeOverlayLayers(key: OverlayKey, vector: boolean, opacity: number): LayerSpecification[] {
  const source = { source: overlaySourceId(key), ...(vector ? { 'source-layer': key } : {}) }
  const base = { id: overlayLayerId(key), ...source, minzoom: overlaySettings[key].zoom }
  if (key === 'points') return [{
    ...base, type: 'circle', paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3, 15, 6, 19, 8],
      'circle-color': ['case', ['!=', ['typeof', ['get', 'vlm_mm_yr']], 'number'], radarColors.missing,
        ['<=', ['number', ['get', 'vlm_mm_yr']], -4], radarColors.sinking, radarColors.other],
      'circle-stroke-color': '#fff', 'circle-stroke-width': 1.3,
      'circle-opacity': opacity, 'circle-stroke-opacity': opacity,
    },
  }]
  if (key === 'buildings') return [{
    ...base, type: 'fill', paint: {
      'fill-color': ['match', ['get', 'beta_class'], 'low', buildingColors.low, 'watch', buildingColors.watch, 'inspect', buildingColors.inspect, buildingColors.missing],
      'fill-outline-color': '#152f4c', 'fill-opacity': opacity,
    },
  }]

  const suppressed = ['==', ['get', 'suppressed'], true] satisfies ExpressionSpecification
  return [
    { ...base, type: 'fill', paint: {
      'fill-color': ['case', suppressed, '#8796a5', ['!=', ['typeof', ['get', 'cell_score']], 'number'], unavailableBand.color,
        ['step', ['number', ['get', 'cell_score']], scoreBands[0].color, scoreBands[1].min, scoreBands[1].color, scoreBands[2].min, scoreBands[2].color]],
      'fill-outline-color': '#253c58', 'fill-opacity': opacity,
    } },
    { ...base, id: base.id + '-hatch', type: 'fill', filter: suppressed,
      paint: { 'fill-pattern': 'inspection-hatch', 'fill-opacity': opacity } },
  ]
}

const numberField = (value: unknown, suffix = '') => typeof value === 'number' && Number.isFinite(value)
  ? new Intl.NumberFormat('en-IN', { maximumSignificantDigits: 7 }).format(value) + suffix : 'Unavailable'

export function describeFeature(layer: OverlayKey, properties: Record<string, unknown>): MapFeature | null {
  const id = properties[featureKey[layer]]
  if (typeof id !== 'string') return null
  const rows: [string, string][] = []
  if (layer === 'points') {
    rows.push(['Vertical land motion', numberField(properties.vlm_mm_yr, ' mm/yr')])
  } else if (layer === 'cells') {
    const suppressed = properties.suppressed === true
    rows.push(['Coverage', suppressed ? 'Suppressed · small sample' : 'Eligible for cell scoring'])
    if (!suppressed) {
      rows.push(['Index', numberField(properties.cell_score, '/100')], ['Rank in ward', numberField(properties.cell_rank_in_ward)])
      if (typeof properties.vlm_median_mm_yr === 'number') rows.push(['Median vertical motion', numberField(properties.vlm_median_mm_yr, ' mm/yr')])
      if (typeof properties.beta_p90_horizon === 'number') rows.push(['90th percentile distortion', numberField(properties.beta_p90_horizon)])
      if (typeof properties.share_sinking_gt4 === 'number') rows.push(['Share sinking ≥4 mm/yr', numberField(properties.share_sinking_gt4 * 100, '%')])
      if (typeof properties.n_buildings === 'number') rows.push(['Buildings counted', numberField(properties.n_buildings)])
    }
  } else {
    rows.push(['Vertical land motion', numberField(properties.vlm_mm_yr, ' mm/yr')],
      ['Distortion ratio', typeof properties.beta_ratio_horizon === 'string' ? properties.beta_ratio_horizon : 'Unavailable'],
      ['Distortion class', typeof properties.beta_class === 'string' ? properties.beta_class : 'Unavailable'],
      ['Radar coverage', properties.sparse === true ? 'Sparse' : properties.sparse === false ? 'Coverage available' : 'Unavailable'])
  }
  return { layer, id, fields: rows.map(([label, value]) => ({ label, value })) }
}
