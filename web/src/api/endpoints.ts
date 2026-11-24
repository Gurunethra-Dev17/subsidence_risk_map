import type { operations } from '../../types/openapi'
import { publicHttpUrl } from './publicUrl'

type WardQuery = NonNullable<operations['listWards']['parameters']['query']>
type BuildingQuery = NonNullable<operations['listBuildings']['parameters']['query']>
type PublicEndpoint = 'meta' | 'validation' | 'health'
type WardResource = 'ward' | 'cells' | 'brief'
const publicRoutes = { meta: 'meta', validation: 'validation', health: 'health' }
const wardSuffixes = { ward: '', cells: '/cells', brief: '/brief.pdf' }
const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i

function hasControlCharacters(value: string) {
  return Array.from(value).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
}

export function apiBase(value: string, pageUrl: string) {
  const input = value.trim() || '/'
  const hasScheme = /^[a-z][a-z\d+.-]*:/i.test(input)
  if (input.startsWith('//') || /[\\?#]/.test(input) || hasControlCharacters(value) ||
    (hasScheme && !/^https?:\/\/[^/]/i.test(input))) {
    throw new Error('Invalid API base URL.')
  }
  const base = publicHttpUrl(input, pageUrl)
  if (base.search || base.hash) throw new Error('Invalid API base URL.')
  base.pathname = base.pathname.replace(/\/+$/, '') + '/'
  return base
}

function wardSegment(id: string) {
  // C4 defines an opaque string, including both numeric Delhi IDs and synthetic IDs.
  if (!id || id !== id.trim() || id === '.' || id === '..' || /[/\\%?#]/u.test(id) || hasControlCharacters(id)) {
    throw new Error('Invalid ward identifier.')
  }
  return encodeURIComponent(id)
}

function setQuery(url: URL, values: Record<string, string | number | undefined>) {
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) url.searchParams.set(key, String(value))
  }
  return url
}

export function publicEndpoint(base: URL, endpoint: PublicEndpoint) {
  if (!Object.hasOwn(publicRoutes, endpoint)) throw new Error('Unsupported public API endpoint.')
  return new URL(publicRoutes[endpoint], base)
}

export function wardEndpoint(base: URL, id: string, resource: WardResource) {
  if (!Object.hasOwn(wardSuffixes, resource)) throw new Error('Unsupported ward API resource.')
  const url = new URL('wards/', base)
  url.pathname += wardSegment(id) + wardSuffixes[resource]
  return url
}

export function wardListEndpoint(base: URL, query: WardQuery = {}) {
  const { status, q, sort, order, limit, offset } = query
  return setQuery(new URL('wards', base), { status, q, sort, order, limit, offset })
}

export function buildingEndpoint(base: URL, query: BuildingQuery) {
  const { bbox, ward_id, limit } = query
  const coordinates = bbox.split(',')
  if (coordinates.length !== 4 || coordinates.some((part) => !decimal.test(part.trim()) || !Number.isFinite(Number(part)))) {
    throw new Error('Invalid building bounding box.')
  }
  return setQuery(new URL('buildings', base), { bbox, ward_id, limit })
}

export function fetchApi(url: URL, headers: HeadersInit, signals: AbortSignal[], cache?: RequestCache) {
  return fetch(url, {
    headers,
    credentials: 'omit',
    redirect: 'error',
    cache,
    signal: AbortSignal.any([AbortSignal.timeout(20_000), ...signals]),
  })
}
