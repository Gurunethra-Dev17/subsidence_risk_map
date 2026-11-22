import type { MultiPolygon, Polygon } from 'geojson'
import { publicHttpUrl } from './publicUrl'
import type { WardGeometry } from './service'

export const delhiWardCount = 250
export const c5Attribution = '© OpenStreetMap contributors, Microsoft, Esri Community Maps contributors, Google Open Buildings; ground-motion data: Virginia Tech dataset (see licence)'

export function isDelhiWardId(id: unknown): id is string {
  return typeof id === 'string' && /^[1-9]\d{0,2}$/.test(id) && Number(id) <= delhiWardCount
}

export function hasDelhiWardIds(ids: readonly unknown[]) {
  return ids.length === delhiWardCount && new Set(ids).size === delhiWardCount && ids.every(isDelhiWardId)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isPolygonCoordinates(value: unknown): value is Polygon['coordinates'] {
  return Array.isArray(value) && value.length > 0 && value.every((ring: unknown) => {
    if (!Array.isArray(ring) || ring.length < 4 || !ring.every((position: unknown) => {
      if (!Array.isArray(position) || position.length < 2 ||
        !position.every((coordinate: unknown) => typeof coordinate === 'number' && Number.isFinite(coordinate))) return false
      const [lon, lat] = position
      return Math.abs(lon) <= 180 && Math.abs(lat) <= 85.051129
    })) return false
    return ring[0][0] === ring.at(-1)[0] && ring[0][1] === ring.at(-1)[1]
  })
}

function polygonGeometry(value: unknown): Polygon | MultiPolygon | null {
  if (!isRecord(value)) return null
  const { type, coordinates } = value
  if (type === 'Polygon' && isPolygonCoordinates(coordinates)) return { type, coordinates }
  if (type === 'MultiPolygon' && Array.isArray(coordinates) && coordinates.length > 0 && coordinates.every(isPolygonCoordinates)) {
    return { type, coordinates }
  }
  return null
}

export async function loadDelhiWardGeometry(value: string, signal: AbortSignal): Promise<WardGeometry> {
  const url = publicHttpUrl(value, window.location.href)
  let response: Response
  try {
    response = await fetch(url, {
      headers: { Accept: 'application/geo+json, application/json' }, credentials: 'omit', redirect: 'error',
      signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]),
    })
  } catch {
    throw new Error('The configured Delhi ward GeoJSON could not be reached.')
  }
  if (!response.ok) throw new Error(`The configured Delhi ward GeoJSON returned HTTP ${response.status}.`)

  const body: unknown = await response.json().catch(() => null)
  if (!isRecord(body) || body.type !== 'FeatureCollection' || !Array.isArray(body.features)) {
    throw new Error('Expected a GeoJSON FeatureCollection of Delhi wards.')
  }
  const features = body.features.map((feature: unknown): WardGeometry['features'][number] => {
    const properties = isRecord(feature) && feature.type === 'Feature' ? feature.properties : null
    const geometry = isRecord(feature) ? polygonGeometry(feature.geometry) : null
    if (!isRecord(properties) || !geometry || typeof properties.ward_id !== 'string' ||
      typeof properties.ward_name !== 'string' || !properties.ward_name.trim() ||
      (properties.city !== undefined && properties.city !== 'delhi') ||
      (properties.source_year !== undefined && properties.source_year !== 2022)) {
      throw new Error('Expected named Delhi 2022 ward polygons in longitude/latitude with string ward IDs.')
    }
    return { type: 'Feature', geometry, properties: { ward_id: properties.ward_id, ward_name: properties.ward_name } }
  })
  return { type: 'FeatureCollection', features }
}
