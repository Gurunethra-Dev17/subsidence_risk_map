import type { FeatureCollection, Geometry } from 'geojson'
import type { components, operations } from '../../types/openapi'
import { config } from '../config'
import { AuthorityError } from './authorityErrors'
import { apiBase, buildingEndpoint, fetchApi } from './endpoints'

type Properties = components['schemas']['BuildingProperties']
type Query = NonNullable<operations['listBuildings']['parameters']['query']>
export type BuildingGeometry = FeatureCollection<Geometry | null, Properties>

export interface AuthoritySession {
  expiresAt: number
  getBuildings: (query: Query, signal?: AbortSignal) => Promise<BuildingGeometry>
  close: () => void
}

function authorityFailure(status: number) {
  if (status === 401 || status === 403) return 'The server rejected authority access.'
  if (status === 429) return 'The authority service is busy. Wait a moment and try again.'
  return 'The authority service could not complete the request.'
}

export async function openAuthority(token: string, signal: AbortSignal): Promise<AuthoritySession> {
  if (config.mock) throw new AuthorityError(0, 'Authority access requires a live API.')
  let api: URL
  try { api = apiBase(config.apiUrl, window.location.href) }
  catch {
    throw new AuthorityError(0, 'Authority access requires an HTTPS API or a local development API.')
  }
  const session = new AbortController()
  let secret = token
  const expiresAt = Date.now() + 20 * 60_000
  const close = () => { secret = ''; session.abort() }

  async function getBuildings(query: Query, requestSignal?: AbortSignal): Promise<BuildingGeometry> {
    if (!secret || Date.now() >= expiresAt) throw new AuthorityError(401, 'Your authority session has ended.')
    const url = buildingEndpoint(api, query)
    let response: Response
    try {
      response = await fetchApi(url, { Accept: 'application/geo+json, application/json', 'X-Authority-Token': secret },
        requestSignal ? [session.signal, requestSignal] : [session.signal], 'no-store')
    } catch {
      throw new AuthorityError(0, 'The authority service could not be reached.')
    }
    if (!response.ok) throw new AuthorityError(response.status, authorityFailure(response.status))
    const body: BuildingGeometry = await response.json().catch(() => {
      throw new AuthorityError(502, 'The authority service did not return a building collection.')
    })
    if (body?.type !== 'FeatureCollection' || !Array.isArray(body.features)) {
      throw new AuthorityError(502, 'The authority service did not return a building collection.')
    }
    session.signal.throwIfAborted()
    requestSignal?.throwIfAborted()
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
