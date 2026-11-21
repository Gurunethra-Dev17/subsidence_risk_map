import { LngLatBounds } from 'maplibre-gl'
import type { ExpressionSpecification, FilterSpecification, LayerSpecification } from 'maplibre-gl'
import type { MultiPolygon, Polygon } from 'geojson'
import { insufficientBand, scoreBands, unavailableBand } from '../wardMetrics'

export const wardSource = 'inspection-wards'
export const wardFill = 'inspection-ward-fill'
export const selectedLine = 'inspection-ward-selected'
const selectedHalo = 'inspection-ward-halo'
const hatch = 'inspection-hatch'
const insufficient = ['==', ['get', 'status'], 'insufficient_data'] satisfies ExpressionSpecification

export const wardFilter = (id: string | null): FilterSpecification =>
  id === null ? false : ['==', ['get', 'ward_id'], id]

export function addBounds(bounds: LngLatBounds, geometry: Polygon | MultiPolygon) {
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  for (const polygon of polygons) {
    for (const [lng, lat] of polygon[0] ?? []) bounds.extend([lng, lat])
  }
  return bounds
}

export function hatchImage() {
  const size = 8
  const image = new ImageData(size, size)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if ((x + y) % size < 2) image.data.set([50, 64, 82, 158], (y * size + x) * 4)
    }
  }
  return image
}

export function wardLayers(vector: boolean): LayerSpecification[] {
  const source = { source: wardSource, ...(vector ? { 'source-layer': 'wards' } : {}) }
  const fillColor: ExpressionSpecification = [
    'case', insufficient, insufficientBand.color,
    ['!=', ['typeof', ['get', 'score']], 'number'], unavailableBand.color,
    ['step', ['number', ['get', 'score']], scoreBands[0].color,
      scoreBands[1].min, scoreBands[1].color, scoreBands[2].min, scoreBands[2].color],
  ]
  return [
    { id: wardFill, type: 'fill', ...source, paint: { 'fill-color': fillColor, 'fill-opacity': 0.57 } },
    { id: 'inspection-ward-hatch', type: 'fill', ...source, filter: insufficient,
      paint: { 'fill-pattern': hatch } },
    { id: 'inspection-ward-outline', type: 'line', ...source,
      paint: { 'line-color': '#344960', 'line-opacity': 0.8, 'line-width': 1.4 } },
    { id: selectedHalo, type: 'line', ...source, filter: wardFilter(null),
      paint: { 'line-color': '#fff', 'line-width': 6 }, layout: { 'line-join': 'round' } },
    { id: selectedLine, type: 'line', ...source, filter: wardFilter(null),
      paint: { 'line-color': '#122642', 'line-width': 3.5 }, layout: { 'line-join': 'round' } },
  ]
}

export const selectionLayers = [selectedHalo, selectedLine]
export const hatchId = hatch
