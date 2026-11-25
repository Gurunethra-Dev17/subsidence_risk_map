import type { FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson'
import type { components, operations } from '../../types/openapi'
import { config } from '../config'
import { apiBase, fetchApi, publicEndpoint, wardEndpoint, wardListEndpoint } from './endpoints'

type Api = components['schemas']
export type Ward = Api['Ward']
export type WardQuery = NonNullable<operations['listWards']['parameters']['query']>
export type WardGeometry = FeatureCollection<Polygon | MultiPolygon,
  Pick<Ward, 'ward_id' | 'ward_name'> & Partial<Pick<Ward, 'status' | 'score' | 'rank'>>>
export type RadarGeometry = FeatureCollection<Point, { pt_id: string; vlm_mm_yr: number }>

export interface DataService {
  getMeta(signal?: AbortSignal): Promise<Api['MetaResponse']>
  listWards(query?: WardQuery, signal?: AbortSignal): Promise<Api['WardPage']>
  getWard(wardId: string, signal?: AbortSignal): Promise<Ward>
  getWardCells(wardId: string, signal?: AbortSignal): Promise<Api['CellFeatureCollection']>
  getWardBrief(wardId: string, signal?: AbortSignal): Promise<Blob>
  getValidation(signal?: AbortSignal): Promise<Api['ValidationSummary']>
  getHealth(signal?: AbortSignal): Promise<Api['Health']>
  getMockRadarGeometry(): Promise<RadarGeometry | null>
  getMockCellGeometry(): Promise<Api['CellFeatureCollection'] | null>
}

export class DataServiceError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: Api['ErrorEnvelope']['error']['code'],
  ) {
    super(message)
    this.name = 'DataServiceError'
  }
}

export function isSyntheticDataset(meta?: Api['MetaResponse']) {
  return config.mock || (typeof meta?.data_vintage === 'string' && meta.data_vintage.trim().toLowerCase() === 'synthetic')
}

export function isAcceptedDelhiDataset(meta?: Api['MetaResponse']) {
  return meta?.city === 'delhi' && meta.data_vintage === 'delhi-candidate-0.0.1' && meta.engine_version === 'f3af18a'
}

export async function getSyntheticWardGeometry(): Promise<WardGeometry> {
  return (await import('./mock')).syntheticWardGeometry
}

const base = () => apiBase(config.apiUrl, window.location.href)

async function request(url: URL, accept: string, signal?: AbortSignal) {
  const response = await fetchApi(url, { Accept: accept }, signal ? [signal] : [])
  if (!response.ok) {
    const body: Api['ErrorEnvelope'] | undefined = await response.json().catch(() => undefined)
    const reason = body?.error?.message
    let message = typeof reason === 'string' ? reason : `Request failed (HTTP ${response.status}).`
    if (response.status === 429) message = 'The data service is busy. Wait a moment and try again.'
    throw new DataServiceError(response.status, message, body?.error?.code)
  }
  return response
}

async function json<T>(url: URL, signal?: AbortSignal, accept = 'application/json'): Promise<T> {
  return (await request(url, accept, signal)).json()
}

function cachedByWard<T>(capacity: number, load: (wardId: string, signal?: AbortSignal) => Promise<T>) {
  const cache = new Map<string, { value: T; expires: number }>()
  return async (wardId: string, signal?: AbortSignal) => {
    signal?.throwIfAborted()
    const hit = cache.get(wardId)
    if (hit && hit.expires > Date.now()) return hit.value
    const value = await load(wardId, signal)
    signal?.throwIfAborted()
    if (!cache.has(wardId) && cache.size >= capacity) {
      const oldest = cache.keys().next().value
      if (oldest !== undefined) cache.delete(oldest)
    }
    cache.set(wardId, { value, expires: Date.now() + 60_000 })
    return value
  }
}

const liveService: DataService = {
  async getMeta(signal) {
    const meta = await json<Api['MetaResponse']>(publicEndpoint(base(), 'meta'), signal)
    if (config.requireReal && (isSyntheticDataset(meta) || meta.city !== 'delhi' || meta.n_wards !== 250 ||
      !config.delhiVintage || meta.data_vintage !== config.delhiVintage || (config.e9 && !isAcceptedDelhiDataset(meta)))) {
      throw new DataServiceError(409, 'The API does not serve the configured real Delhi dataset.')
    }
    return meta
  },
  listWards(query, signal) {
    return json(wardListEndpoint(base(), query), signal)
  },
  getWard: cachedByWard<Ward>(100, (wardId, signal) => json(wardEndpoint(base(), wardId, 'ward'), signal)),
  getWardCells: cachedByWard<Api['CellFeatureCollection']>(12, (wardId, signal) =>
    json(wardEndpoint(base(), wardId, 'cells'), signal, 'application/geo+json, application/json')),
  async getWardBrief(wardId, signal) {
    const response = await request(wardEndpoint(base(), wardId, 'brief'), 'application/pdf', signal)
    if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/pdf')) {
      throw new DataServiceError(502, 'The brief endpoint did not return a PDF.')
    }
    return response.blob()
  },
  getValidation: (signal) => json(publicEndpoint(base(), 'validation'), signal),
  getHealth: (signal) => json(publicEndpoint(base(), 'health'), signal),
  async getMockRadarGeometry() {
    return null
  },
  async getMockCellGeometry() {
    return null
  },
}

export async function getDataService(): Promise<DataService> {
  return config.mock ? (await import('./mock')).mockService : liveService
}
