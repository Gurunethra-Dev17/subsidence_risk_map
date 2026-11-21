import type { FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson'
import type { components, operations } from '../../types/openapi'
import { config } from '../config'

type Api = components['schemas']
export type Ward = Api['Ward']
export type WardQuery = NonNullable<operations['listWards']['parameters']['query']>
export type WardGeometry = FeatureCollection<Polygon | MultiPolygon, Pick<Ward, 'ward_id' | 'ward_name'>>
export type RadarGeometry = FeatureCollection<Point, { pt_id: string; vlm_mm_yr: number }>

export interface DataService {
  getMeta(signal?: AbortSignal): Promise<Api['MetaResponse']>
  listWards(query?: WardQuery, signal?: AbortSignal): Promise<Api['WardPage']>
  getWard(wardId: string, signal?: AbortSignal): Promise<Ward>
  getWardCells(wardId: string, signal?: AbortSignal): Promise<Api['CellFeatureCollection']>
  getWardBrief(wardId: string, signal?: AbortSignal): Promise<Blob>
  getValidation(signal?: AbortSignal): Promise<Api['ValidationSummary']>
  getHealth(signal?: AbortSignal): Promise<Api['Health']>
  getMockWardGeometry(): Promise<WardGeometry | null>
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

async function request(path: string, accept: string, signal?: AbortSignal) {
  const response = await fetch(config.apiUrl + path, {
    headers: { Accept: accept },
    credentials: 'omit',
    signal,
  })
  if (!response.ok) {
    const body: Api['ErrorEnvelope'] | undefined = await response.json().catch(() => undefined)
    const message = body?.error?.message
    throw new DataServiceError(
      response.status,
      typeof message === 'string' ? message : `Request failed (HTTP ${response.status}).`,
      body?.error?.code,
    )
  }
  return response
}

async function json<T>(path: string, signal?: AbortSignal, accept = 'application/json'): Promise<T> {
  return (await request(path, accept, signal)).json()
}

const wardPath = (wardId: string) => `/wards/${encodeURIComponent(wardId)}`

const liveService: DataService = {
  getMeta: (signal) => json('/meta', signal),
  listWards(query, signal) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) params.set(key, String(value))
    }
    return json(params.size ? `/wards?${params}` : '/wards', signal)
  },
  getWard: (wardId, signal) => json(wardPath(wardId), signal),
  getWardCells: (wardId, signal) => json(`${wardPath(wardId)}/cells`, signal, 'application/geo+json, application/json'),
  async getWardBrief(wardId, signal) {
    const response = await request(`${wardPath(wardId)}/brief.pdf`, 'application/pdf', signal)
    if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/pdf')) {
      throw new DataServiceError(502, 'The brief endpoint did not return a PDF.')
    }
    return response.blob()
  },
  getValidation: (signal) => json('/validation', signal),
  getHealth: (signal) => json('/health', signal),
  async getMockWardGeometry() {
    return null
  },
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
