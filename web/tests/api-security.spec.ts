import { createServer } from 'node:http'
import { expect, test } from '@playwright/test'
import { apiBase, buildingEndpoint, fetchApi, publicEndpoint, wardEndpoint, wardListEndpoint } from '../src/api/endpoints'

const pageUrl = 'https://frontend.example/dashboard'
const sameOrigin = apiBase('/api/v1/', pageUrl)

test('approved API bases retain their origin and configured prefix', () => {
  const bases = [
    ['/api/v1/', 'https://frontend.example/api/v1/'],
    ['./api/v1', 'https://frontend.example/api/v1/'],
    ['https://data.example/custom/api/v1', 'https://data.example/custom/api/v1/'],
    ['http://127.0.0.1:8002/api/v1', 'http://127.0.0.1:8002/api/v1/'],
    ['http://[::1]:8002/api/v1', 'http://[::1]:8002/api/v1/'],
  ]
  for (const [input, expected] of bases) {
    const base = apiBase(input, pageUrl)
    expect(base.href).toBe(expected)
    expect(publicEndpoint(base, 'health').href).toBe(expected + 'health')
    expect(wardEndpoint(base, '131', 'cells').href).toBe(expected + 'wards/131/cells')
    expect(wardEndpoint(base, 'ward-001', 'brief').href).toBe(expected + 'wards/ward-001/brief.pdf')
  }
  expect(wardEndpoint(sameOrigin, 'Ward A', 'ward').pathname).toBe('/api/v1/wards/Ward%20A')
})

test('ambiguous bases and invalid ward segments fail before any request', () => {
  const invalidBases = [
    '//data.example/api/v1', '  //data.example/api/v1', '/\t/data.example',
    'https:/data.example/api/v1', 'https:///data.example/api/v1',
    'http://data.example/api/v1', 'https://user@data.example/api/v1',
    '/api/v1?mode=demo', '/api/v1#preview',
  ]
  for (const input of invalidBases) expect(() => apiBase(input, pageUrl)).toThrow()
  for (const id of ['', ' ', '.', '..', 'ward/other', 'ward\\other', 'ward%20other', 'ward?query', 'ward#fragment', 'ward\n']) {
    expect(() => wardEndpoint(sameOrigin, id, 'ward')).toThrow('Invalid ward identifier.')
  }
})

test('C4 query values stay inside the query string and unknown keys are omitted', () => {
  const query = { q: 'Road & Park? #1', limit: 25, offset: 0, token: 'ignored-fixture' }
  const wards = wardListEndpoint(sameOrigin, query)
  expect(wards.pathname).toBe('/api/v1/wards')
  expect(Object.fromEntries(wards.searchParams)).toEqual({ q: query.q, limit: '25', offset: '0' })

  const bbox = '77.10,28.55,77.12,28.57'
  const request = { bbox, ward_id: 'ward-001', limit: 5, offset: 2 }
  const buildings = buildingEndpoint(sameOrigin, request)
  expect(buildings.pathname).toBe('/api/v1/buildings')
  expect(Object.fromEntries(buildings.searchParams)).toEqual({ bbox, ward_id: 'ward-001', limit: '5' })
  for (const malformed of ['1,2,3', '1,,3,4', '1,2,3,Infinity', '1,2,3,0xff']) {
    expect(() => buildingEndpoint(sameOrigin, { bbox: malformed })).toThrow('Invalid building bounding box.')
  }
})

test('API fetch blocks redirects before sending a follow-up and honours cancellation', async () => {
  const received: { url?: string; authority?: string | string[]; cookie?: string }[] = []
  let onMetaRequest: () => void = () => {}
  const server = createServer((request, response) => {
    received.push({ url: request.url, authority: request.headers['x-authority-token'], cookie: request.headers.cookie })
    if (request.url === '/api/v1/meta') {
      onMetaRequest()
      return
    }
    response.writeHead(request.url?.startsWith('/api/v1/') ? 307 : 200, { Location: '/fixture-target' }).end()
  })
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  try {
    const address = server.address()
    if (!address || typeof address === 'string') throw new Error('Missing test server address.')
    const base = apiBase('/api/v1', `http://127.0.0.1:${address.port}`)
    const token = 'redirect-test-fixture'
    const target = buildingEndpoint(base, { bbox: '0,0,1,1', limit: 1 })
    await expect(fetchApi(target, { 'X-Authority-Token': token }, [], 'no-store')).rejects.toThrow()
    await expect(fetchApi(publicEndpoint(base, 'health'), {}, [])).rejects.toThrow()
    expect(received).toEqual([
      { url: target.pathname + target.search, authority: token, cookie: undefined },
      { url: '/api/v1/health', authority: undefined, cookie: undefined },
    ])
    const cancelled = new AbortController()
    cancelled.abort()
    await expect(fetchApi(publicEndpoint(base, 'meta'), {}, [cancelled.signal])).rejects.toMatchObject({ name: 'AbortError' })
    expect(received).toHaveLength(2)

    const started = new Promise<void>((resolve) => { onMetaRequest = resolve })
    const inFlight = new AbortController()
    const pending = fetchApi(publicEndpoint(base, 'meta'), {}, [inFlight.signal])
    await started
    inFlight.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  } finally {
    server.closeAllConnections()
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  }
})
