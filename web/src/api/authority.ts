import type { FeatureCollection, Geometry } from 'geojson'
import type { Source } from 'pmtiles'
import type { components, operations } from '../../types/openapi'
import { config } from '../config'
import { AuthorityError } from './authorityErrors'

type Properties = components['schemas']['BuildingProperties']
type Query = NonNullable<operations['listBuildings']['parameters']['query']>
export type BuildingGeometry = FeatureCollection<Geometry | null, Properties>

export interface AuthoritySession {
  expiresAt: number
  archive?: Source
  getBuildings: (query: Query, signal?: AbortSignal) => Promise<BuildingGeometry>
  close: () => void
}

export async function openAuthority(token: string, archivePath: string, signal: AbortSignal): Promise<AuthoritySession> {
  if (config.mock) throw new AuthorityError(0, 'Authority access requires a live API.')
  const api = new URL(config.apiUrl + '/', window.location.href)
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(api.hostname)
  if (api.protocol !== 'https:' && !(loopback && api.protocol === 'http:')) {
    throw new AuthorityError(0, 'Authority access requires an HTTPS API or a local development API.')
  }
  let archiveUrl: URL | undefined
  if (archivePath) {
    archiveUrl = new URL(archivePath, api.origin)
    if (archiveUrl.origin !== api.origin || archiveUrl.username || archiveUrl.password ||
      archiveUrl.search || archiveUrl.hash || !archiveUrl.pathname.endsWith('.pmtiles')) {
      throw new AuthorityError(0, 'Enter a protected .pmtiles path on the API origin, without query parameters.')
    }
  }

  const session = new AbortController()
  let secret = token
  const expiresAt = Date.now() + 20 * 60_000
  const close = () => { secret = ''; session.abort() }

  async function secured(url: URL, headers: HeadersInit, requestSignal?: AbortSignal) {
    if (!secret || Date.now() >= expiresAt) throw new AuthorityError(401, 'Your authority session has ended.')
    const requestHeaders = new Headers(headers)
    requestHeaders.set('X-Authority-Token', secret)
    let response: Response
    try {
      response = await fetch(url, {
        headers: requestHeaders, credentials: 'omit', redirect: 'error', cache: 'no-store',
        signal: AbortSignal.any([session.signal, AbortSignal.timeout(20_000), ...(requestSignal ? [requestSignal] : [])]),
      })
    } catch {
      throw new AuthorityError(0, 'The authority service could not be reached.')
    }
    if (!response.ok) throw new AuthorityError(response.status,
      response.status === 401 || response.status === 403 ? 'The server rejected authority access.' : 'The authority service could not complete the request.')
    return response
  }

  async function getBuildings(query: Query, requestSignal?: AbortSignal): Promise<BuildingGeometry> {
    const url = new URL('buildings', api)
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
    const response = await secured(url, { Accept: 'application/geo+json, application/json' }, requestSignal)
    const body: BuildingGeometry = await response.json().catch(() => {
      throw new AuthorityError(502, 'The authority service did not return a building collection.')
    })
    if (body?.type !== 'FeatureCollection' || !Array.isArray(body.features)) {
      throw new AuthorityError(502, 'The authority service did not return a building collection.')
    }
    return body
  }

  try {
    // The frozen API has no login endpoint. Validate against a bounded /buildings request.
    await getBuildings({ bbox: '0,0,0.0001,0.0001', limit: 1 }, signal)
    signal.throwIfAborted()
  } catch (error) {
    close()
    throw error
  }

  const archive: Source | undefined = archiveUrl && {
    getKey: () => 'authority-buildings',
    async getBytes(offset, length, requestSignal) {
      const response = await secured(archiveUrl, { Range: `bytes=${offset}-${offset + length - 1}` }, requestSignal)
      if (response.status !== 206 || !response.headers.get('cache-control')?.toLowerCase().includes('no-store')) {
        await response.body?.cancel()
        throw new AuthorityError(502, 'The protected archive must support private, non-cacheable range responses.')
      }
      return { data: await response.arrayBuffer(), etag: response.headers.get('etag') ?? undefined }
    },
  }
  return { expiresAt, getBuildings, archive, close }
}
