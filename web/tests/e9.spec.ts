import { readFile } from 'node:fs/promises'
import { performance } from 'node:perf_hooks'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { components } from '../types/openapi'
import { showNumber } from '../src/wardMetrics'

const api = 'http://127.0.0.1:8002/api/v1'
const geo = 'http://127.0.0.1:8003/delhi'
const mapReady = (page: Page) => page.getByText('Basemap unavailable · ward data visible')
type Api = components['schemas']

test.beforeEach(async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/**', (route) => route.abort())
})

async function hoverWard(page: Page, ward: Api['Ward']) {
  const canvas = await page.locator('.maplibregl-canvas').boundingBox()
  if (!canvas) throw new Error('Map canvas unavailable.')
  const x = canvas.x + canvas.width / 2
  const y = canvas.y + canvas.height / 2
  const tooltip = page.getByRole('tooltip').filter({ hasText: ward.ward_name })
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return tooltip.count()
  }).toBe(1)
  await expect(tooltip).toContainText(`${showNumber(ward.score)}/100 · Rank #${ward.rank}`)
  return { x, y }
}

test('real E9 wards, scoped cells, inspector, PDF and evidence render from live C4', async ({ page }) => {
  const start = performance.now()
  const wardResponse = page.waitForResponse((response) => response.url().startsWith(api + '/wards?'))
  await page.goto('/')
  const ranked = await (await wardResponse).json() as Api['WardPage']
  const ward = ranked.items[0]
  expect(ranked.items.length).toBe(250)
  expect(ranked.items.filter((item) => item.status === 'insufficient_data')).toHaveLength(5)
  await expect(page.locator('.ward-select')).toHaveCount(250)
  const listReady = performance.now()
  await expect(mapReady(page)).toBeVisible({ timeout: 25_000 })
  const mapReadyAt = performance.now()
  const ranking = page.getByRole('button', { name: ward.ward_name, exact: true })
  const selectStart = performance.now()
  await ranking.click()
  const point = await hoverWard(page, ward)
  const selectedAt = performance.now()
  await page.getByRole('button', { name: 'Clear ward selection' }).click()
  await page.mouse.click(point.x, point.y)
  await expect(ranking).toHaveAttribute('aria-pressed', 'true')

  await page.getByText('Layers', { exact: true }).click()
  const cellStart = performance.now()
  const cellResponse = page.waitForResponse(api + '/wards/' + ward.ward_id + '/cells')
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  const cells = await (await cellResponse).json() as Api['CellFeatureCollection']
  const cellReady = performance.now()
  expect(cells.features.every(({ properties }) => properties.ward_id === ward.ward_id)).toBeTruthy()
  const suppressed = cells.features.find(({ properties }) => properties.suppressed)?.properties
  expect(suppressed).toMatchObject({ cell_score: null, cell_rank_in_ward: null, vlm_median_mm_yr: null, beta_p90_horizon: null })
  await expect(page.getByRole('list', { name: 'Grid cells legend' })).toContainText('Suppressed')
  await expect(page.getByRole('checkbox', { name: /Radar points|Buildings/ })).toHaveCount(0)
  await page.getByText('Layers', { exact: true }).click()
  await page.getByRole('button', { name: '3D buildings' }).click()
  await expect(ranking).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '2D plan' }).click()

  const inspectorStart = performance.now()
  await page.getByRole('link', { name: 'Open Ward Inspector' }).click()
  const inspector = page.locator('#inspector')
  await expect(inspector.getByRole('heading', { name: ward.ward_name })).toBeVisible()
  const inspectorReady = performance.now()
  await expect(inspector).toContainText('Groundwater assessment-unit boundaries could not be reliably matched to wards.')
  await expect(inspector).toContainText('The C2 export has no agreed histogram bins or denominator.')
  await expect(inspector).toContainText(ward.beta_p90_horizon!.toPrecision(4))
  const pdfResponse = page.waitForResponse(api + '/wards/' + ward.ward_id + '/brief.pdf')
  const pdfStart = performance.now()
  await page.getByRole('link', { name: 'Open Inspection Brief' }).click()
  const pdf = await pdfResponse
  expect(pdf.headers()['content-type']).toContain('application/pdf')
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-')
  const pdfReady = performance.now()
  const brief = page.getByRole('region', { name: 'Ward inspection brief' })
  await expect(brief).toContainText('API PDF available')
  await expect(brief.getByRole('rowheader', { name: suppressed?.cell_id })).toHaveCount(0)
  await brief.getByText('Preview API PDF', { exact: true }).click()
  await expect(brief.locator('object')).toBeVisible()
  const download = page.waitForEvent('download')
  await brief.getByRole('link', { name: 'Download PDF' }).click()
  expect((await readFile(await (await download).path())).subarray(0, 5).toString()).toBe('%PDF-')
  for (const width of [768, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  }
  await page.getByRole('link', { name: 'Methods & Evidence' }).click()
  await expect(page.getByText(/80–120 m inclusive/)).toBeVisible()
  await expect(page.getByText(/35\.29%.*41\.18%.*23\.53%/)).toBeVisible()
  await page.getByRole('link', { name: 'Validation', exact: true }).click()
  await expect(page.getByText('0.9241')).toBeVisible()
  if (process.env.VITE_E7_INTERNAL_PREVIEW?.trim().toLowerCase() === 'true') {
    await expect(page.getByText('Fresh observation processed — not independently validated.', { exact: true })).toBeVisible()
  } else {
    await expect(page.getByText(/Fresh-data check/)).toContainText('not run')
  }
  await expect(page.getByText('Comparison matrix unavailable.')).toBeVisible()
  console.log('E9 timings (ms)', {
    list: Math.round(listReady - start), map: Math.round(mapReadyAt - start), selection: Math.round(selectedAt - selectStart),
    cells: Math.round(cellReady - cellStart), inspector: Math.round(inspectorReady - inspectorStart), pdf: Math.round(pdfReady - pdfStart),
  })
})

test('candidate ward PMTiles use real C4 colours and hover values when C0 transport fails', async ({ page, request }) => {
  const archive = geo + '/delhi-wards-candidate-0.0.3.pmtiles'
  const head = await request.head(archive)
  expect(head.status()).toBe(200)
  expect(head.headers()['accept-ranges']).toBe('bytes')
  const range = await request.get(archive, { headers: { Range: 'bytes=0-15', Origin: 'http://127.0.0.1:5173' } })
  expect(range.status()).toBe(206)
  expect(range.headers()['content-range']).toMatch(/^bytes 0-15\//)
  expect(range.headers()['access-control-allow-origin']).toBe('http://127.0.0.1:5173')
  expect((await range.body()).subarray(0, 7).toString()).toBe('PMTiles')
  const fallback = await request.get(geo + '/geojson/131.json')
  expect(fallback.headers()['content-encoding']).toBe('gzip')
  expect((await fallback.json()).features[0].properties.ward_id).toBe('131')
  await page.route(geo + '/wards.geojson', (route) => route.fulfill({ status: 503 }))
  const response = page.waitForResponse((result) => result.url().startsWith(api + '/wards?'))
  await page.goto('/')
  const { items: [ward] } = await (await response).json() as Api['WardPage']
  await expect(page.getByText('Ward GeoJSON unavailable · using configured ward PMTiles.')).toBeVisible()
  await expect(mapReady(page)).toBeVisible({ timeout: 25_000 })
  await page.getByRole('button', { name: ward.ward_name, exact: true }).click()
  await hoverWard(page, ward)
})

async function enterAuthority(page: Page, token: string) {
  await page.getByRole('button', { name: 'Authority access' }).click()
  await page.getByLabel('Authority token').evaluate((input, value) => {
    const field = input as HTMLInputElement
    field.value = value
  }, token)
  await page.getByRole('button', { name: 'Verify access' }).click()
}

type Ring = number[][]
type PolygonCoordinates = Ring[]
type BuildingClickCandidate = { featureIndex: number; featureId: string; point: [number, number]; width: number }

function pointInRing(ring: Ring, point: [number, number]) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [x1, y1] = ring[i]
    const [x2, y2] = ring[j]
    if ((y1 > point[1]) !== (y2 > point[1]) &&
      point[0] < ((x2 - x1) * (point[1] - y1)) / (y2 - y1) + x1) inside = !inside
  }
  return inside
}

function pointInPolygon(polygon: PolygonCoordinates, point: [number, number]) {
  return Boolean(polygon[0]?.length && pointInRing(polygon[0], point) &&
    !polygon.slice(1).some((hole) => pointInRing(hole, point)))
}

function scanlineInterior(polygon: PolygonCoordinates): { point: [number, number]; width: number } | null {
  const exterior = polygon[0]
  if (!exterior || exterior.length < 4) return null
  const latitudes = [...new Set(exterior.map(([, latitude]) => latitude))].sort((a, b) => a - b)
  let best: { point: [number, number]; width: number } | null = null

  const intersections = (ring: Ring, latitude: number) => {
    const longitudes: number[] = []
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [x1, y1] = ring[j]
      const [x2, y2] = ring[i]
      if ((y1 > latitude) !== (y2 > latitude)) {
        longitudes.push(x1 + ((latitude - y1) * (x2 - x1)) / (y2 - y1))
      }
    }
    longitudes.sort((a, b) => a - b)
    const intervals: [number, number][] = []
    for (let i = 0; i + 1 < longitudes.length; i += 2) {
      if (longitudes[i + 1] > longitudes[i]) intervals.push([longitudes[i], longitudes[i + 1]])
    }
    return intervals
  }

  for (let i = 0; i + 1 < latitudes.length; i++) {
    const latitude = (latitudes[i] + latitudes[i + 1]) / 2
    let segments = intersections(exterior, latitude)
    for (const hole of polygon.slice(1)) {
      for (const [holeWest, holeEast] of intersections(hole, latitude)) {
        segments = segments.flatMap(([west, east]) => {
          if (holeEast <= west || holeWest >= east) return [[west, east] as [number, number]]
          const remaining: [number, number][] = []
          if (holeWest > west) remaining.push([west, holeWest])
          if (holeEast < east) remaining.push([holeEast, east])
          return remaining
        })
      }
    }
    for (const [west, east] of segments) {
      const point: [number, number] = [(west + east) / 2, latitude]
      const width = east - west
      if (width > 0 && pointInPolygon(polygon, point) && (!best || width > best.width)) best = { point, width }
    }
  }
  return best
}

function buildingInteriorCandidates(collection: Api['BuildingFeatureCollection']): BuildingClickCandidate[] {
  const candidates: BuildingClickCandidate[] = []
  collection.features.forEach(({ geometry, properties }, featureIndex) => {
    if (typeof properties.bldg_id !== 'string' || !geometry) return
    const polygons: PolygonCoordinates[] = geometry.type === 'Polygon'
      ? [geometry.coordinates as PolygonCoordinates]
      : geometry.type === 'MultiPolygon' ? geometry.coordinates as PolygonCoordinates[] : []
    for (const polygon of polygons) {
      const interior = scanlineInterior(polygon)
      if (interior) candidates.push({ featureIndex, featureId: properties.bldg_id, ...interior })
    }
  })
  return candidates.sort((a, b) => b.width - a.width)
}

async function findRenderedBuildingClick(page: Page, candidates: BuildingClickCandidate[]) {
  return page.evaluate((points) => {
    type MapLike = {
      project: (coordinate: [number, number]) => { x: number; y: number }
      getContainer: () => HTMLElement
      getCanvas: () => HTMLCanvasElement
      getZoom: () => number
      getLayer: (id: string) => { minzoom?: number } | undefined
      getLayoutProperty: (id: string, name: string) => unknown
      queryRenderedFeatures: (point: { x: number; y: number }, options: { layers: string[] }) =>
        { properties?: Record<string, unknown>; layer: { id: string } }[]
    }
    const root = document.getElementById('root')
    const rootKey = root && Object.keys(root).find((key) => key.startsWith('__reactContainer$'))
    const fiberRoot = rootKey
      ? (root as HTMLElement & Record<string, unknown>)[rootKey] as { stateNode?: { current?: unknown } }
      : null
    const stack = [fiberRoot?.stateNode?.current ?? fiberRoot]
    const seen = new Set<object>()
    let map: MapLike | null = null
    while (stack.length && !map) {
      const fiber = stack.pop() as {
        memoizedState?: { memoizedState?: unknown; next?: unknown } | null
        child?: unknown
        sibling?: unknown
      } | null
      if (!fiber || typeof fiber !== 'object' || seen.has(fiber)) continue
      seen.add(fiber)
      let hook = fiber.memoizedState
      for (let count = 0; hook && count < 100; count++) {
        const value = hook.memoizedState
        for (const candidate of [value, (value as { current?: unknown } | null)?.current]) {
          if (candidate && typeof (candidate as MapLike).project === 'function' &&
            typeof (candidate as MapLike).queryRenderedFeatures === 'function') {
            map = candidate as MapLike
            break
          }
        }
        hook = hook.next as typeof hook
        if (map) break
      }
      if (fiber.child) stack.push(fiber.child as typeof fiber)
      if (fiber.sibling) stack.push(fiber.sibling as typeof fiber)
    }
    if (!map) return null

    const fillLayer = map.getLayer('overlay-buildings-main')
    const pointLayer = map.getLayer('overlay-buildings-main-points')
    const layers = ['overlay-buildings-main', 'overlay-buildings-main-points']
      .filter((id) => map?.getLayer(id) && map.getLayoutProperty(id, 'visibility') !== 'none')
    if (!fillLayer || !pointLayer || map.getZoom() < Math.max(fillLayer.minzoom ?? 0, pointLayer.minzoom ?? 0)) return null

    const container = map.getContainer().getBoundingClientRect()
    const canvas = map.getCanvas()
    const canvasBounds = canvas.getBoundingClientRect()
    for (const candidate of points) {
      const projected = map.project(candidate.point)
      const clientX = container.left + projected.x
      const clientY = container.top + projected.y
      if (clientX < canvasBounds.left || clientX >= canvasBounds.right ||
        clientY < canvasBounds.top || clientY >= canvasBounds.bottom) continue
      if (document.elementFromPoint(clientX, clientY) !== canvas) continue
      const hits = map.queryRenderedFeatures(projected, { layers })
      if (hits.some((hit) => hit.properties?.bldg_id === candidate.featureId)) {
        return { ...candidate, screen: [clientX, clientY] as [number, number] }
      }
    }
    return null
  }, candidates)
}

test('real authority renders bounded footprints and radar, then clears restricted data on sign-out', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'GET' && request.url().startsWith(api + '/buildings')) requests.push(request.url())
  })
  await page.goto('/')
  await expect(mapReady(page)).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  expect(requests).toHaveLength(0)
  const token = process.env.E9_TEST_AUTHORITY_TOKEN!
  await enterAuthority(page, token)
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.locator('.ward-select').first().click()
  const zoom = page.getByRole('button', { name: 'Zoom in' })
  await zoom.click()
  await page.getByText('Layers', { exact: true }).click()
  await page.getByRole('checkbox', { name: /Radar points/ }).check()
  await expect(page.getByRole('list', { name: 'Radar points legend' })).toBeVisible()
  await page.getByText('Layers', { exact: true }).click()
  for (let i = 0; i < 3; i++) await zoom.click()
  await page.getByText('Layers', { exact: true }).click()
  const start = performance.now()
  const footprints = page.waitForResponse((response) => response.url().startsWith(api + '/buildings?') &&
    new URL(response.url()).searchParams.get('limit') === '500' && response.ok())
  await page.getByRole('checkbox', { name: /Buildings/ }).check()
  await page.getByText('Layers', { exact: true }).click()
  const response = await footprints
  const responded = performance.now()
  const collection = await response.json() as Api['BuildingFeatureCollection']
  expect(response.headers()['cache-control']).toBe('no-store')
  expect(collection.features.length).toBeGreaterThan(0)
  expect(collection.features.every(({ geometry }) => ['Polygon', 'MultiPolygon'].includes(String(geometry?.type)))).toBeTruthy()
  await page.getByText('Layers', { exact: true }).click()
  await expect(page.getByRole('list', { name: 'Buildings legend' })).toBeVisible()
  const rendered = performance.now()
  await page.getByText('Layers', { exact: true }).click()
  const ids = new Set(collection.features.map(({ properties }) => properties.bldg_id))
  const candidates = buildingInteriorCandidates(collection)
  expect(candidates.length, 'Building response had no valid polygon interior points').toBeGreaterThan(0)
  const selectable = await findRenderedBuildingClick(page, candidates)
  expect(selectable, 'No building interior was rendered and unobscured by map controls').toBeTruthy()
  const target = selectable!
  const picked = target.featureId
  expect(ids.has(target.featureId)).toBeTruthy()
  const confirmedAtClickPoint = await findRenderedBuildingClick(page, [target])
  expect(confirmedAtClickPoint?.featureId, 'Target building is no longer rendered at the projected click point')
    .toBe(target.featureId)
  await page.mouse.click(...target.screen)
  const panel = page.getByRole('region', { name: 'Selected map feature' })
  await expect(panel).toBeVisible()
  const selectedLabel = await panel.locator('strong').textContent()
  expect(selectedLabel?.startsWith('Buildings')).toBeTruthy()
  expect(selectedLabel?.split('·').at(-1)?.trim()).toBe(target.featureId.trim())
  await expect(panel).toContainText('Vertical land motion')
  await expect(panel).toContainText('Radar coverage')
  const beforeZoom = requests.length
  const updated = page.waitForResponse((result) => result.url().startsWith(api + '/buildings?') && result.ok())
  await zoom.evaluate((element) => {
    const button = element as HTMLButtonElement
    button.click()
    button.click()
  })
  await updated
  expect(requests.length - beforeZoom).toBe(1)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: /Radar points|Buildings/ })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Selected map feature' })).toHaveCount(0)
  expect(await page.evaluate((secret) => [location.href, JSON.stringify(localStorage), JSON.stringify(sessionStorage)]
    .some((value) => value.includes(secret)), token)).toBe(false)
  await page.getByRole('link', { name: 'Ward Inspector', exact: true }).click()
  await expect(page.getByText(picked!, { exact: true })).toHaveCount(0)
  await enterAuthority(page, token)
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  console.log('E9 viewport sample (ms from layer/zoom start)', { response: Math.round(responded - start),
    rendered: Math.round(rendered - start), requests: requests.length })
})

test('controlled 429 and incompatible metadata require an explicit retry without fixture substitution', async ({ page }) => {
  let count = 0
  await page.route(api + '/meta', (route) => {
    count += 1
    if (count === 1) return route.fulfill({ status: 429, json: { error: { code: 'rate_limited', message: 'Too many requests' } } })
    if (count === 2) return route.fulfill({ json: { city: 'delhi', data_vintage: 'synthetic', n_wards: 3 } })
    return route.continue()
  })
  await page.goto('/')
  const error = page.getByRole('alert').filter({ hasText: 'City metadata unavailable' })
  await expect(error).toContainText('The data service is busy.')
  expect(count).toBe(1)
  await error.getByRole('button', { name: 'Try again' }).click()
  await expect(error).toContainText('does not serve the configured real Delhi dataset')
  await expect(page.getByText('Synthetic wards', { exact: true })).toHaveCount(0)
  await expect(page.locator('.ward-select')).toHaveCount(0)
  await error.getByRole('button', { name: 'Try again' }).click()
  await expect(page.locator('.ward-select')).toHaveCount(250)
  expect(count).toBe(3)
  await page.route(api + '/wards/*/brief.pdf', (route) => route.fulfill({ status: 503 }))
  await page.evaluate(() => { window.print = () => document.body.setAttribute('data-print-verified', 'true') })
  await page.locator('.ward-select').first().click()
  await page.getByRole('link', { name: 'Open Inspection Brief' }).click()
  await expect(page.getByText('API PDF unavailable · browser print fallback')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download PDF' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Print / Save as PDF' }).click()
  await expect(page.locator('body')).toHaveAttribute('data-print-verified', 'true')
})
