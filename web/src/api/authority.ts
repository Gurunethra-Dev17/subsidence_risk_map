import type { FeatureCollection, Geometry } from 'geojson'
import type { components, operations } from '../../types/openapi'
import { config } from '../config'
import { AuthorityError } from './authorityErrors'

type Properties = components['schemas']['BuildingProperties']
type Query = NonNullable<operations['listBuildings']['parameters']['query']>
export type BuildingGeometry = FeatureCollection<Geometry | null, Properties>

export interface AuthoritySession {
  expiresAt: number
  getBuildings: (query: Query, signal?: AbortSignal) => Promise<BuildingGeometry>
  close: () => void
}

export async function openAuthority(token: string, signal: AbortSignal): Promise<AuthoritySession> {
  if (config.mock) throw new AuthorityError(0, 'Authority access requires a live API.')
  const api = new URL(config.apiUrl + '/', window.location.href)
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(api.hostname)
  if (api.protocol !== 'https:' && !(loopback && api.protocol === 'http:')) {
    throw new AuthorityError(0, 'Authority access requires an HTTPS API or a local development API.')
  }
  const session = new AbortController()
  let secret = token
  const expiresAt = Date.now() + 20 * 60_000
  const close = () => { secret = ''; session.abort() }

  async function getBuildings(query: Query, requestSignal?: AbortSignal): Promise<BuildingGeometry> {
    if (!secret || Date.now() >= expiresAt) throw new AuthorityError(401, 'Your authority session has ended.')
    const url = new URL('buildings', api)
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
    let response: Response
    try {
      response = await fetch(url, {
        headers: { Accept: 'application/geo+json, application/json', 'X-Authority-Token': secret },
        credentials: 'omit', redirect: 'error', cache: 'no-store',
        signal: AbortSignal.any([session.signal, AbortSignal.timeout(20_000), ...(requestSignal ? [requestSignal] : [])]),
      })
    } catch {
      throw new AuthorityError(0, 'The authority service could not be reached.')
    }
    if (!response.ok) throw new AuthorityError(response.status,
      response.status === 401 || response.status === 403 ? 'The server rejected authority access.' : 'The authority service could not complete the request.')
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

  return { expiresAt, getBuildings, close }
}
