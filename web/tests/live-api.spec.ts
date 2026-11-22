import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'

const api = 'http://127.0.0.1:8000/api/v1'
const origin = 'http://localhost:5173'
const north = '/wards/ward-001'
const buildings = api + '/buildings?bbox=0,0,0.0001,0.0001&limit=1'

test.beforeEach(async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.abort())
})

test('live synthetic boundaries, rankings, details, cells, validation and PDF', async ({ page }) => {
  const responses = new Set<string>()
  page.on('response', (response) => {
    if (response.ok() && response.url().startsWith(api + '/')) {
      responses.add(response.url().slice(api.length).split('?')[0])
    }
  })

  await page.goto('/')
  await expect(page.getByText('Live API · synthetic demo data')).toBeVisible()
  await expect(page.getByText(/API reachable ·/)).toBeVisible()
  await expect(page.getByText('Synthetic wards', { exact: true })).toBeVisible()
  await expect(page.getByText('Basemap unavailable · ward data visible')).toBeVisible()
  const ranking = page.getByRole('button', { name: 'Demo North', exact: true })
  await expect(page.locator('.ward-select')).toHaveText(['Demo North', 'Demo South', 'Demo Empty'])
  await ranking.click()
  const inspector = page.locator('#inspector')
  await expect(inspector.getByText('Groundwater data missing')).toBeVisible()
  await expect(inspector.getByText('Building distortion distribution')).toBeVisible()

  // Ranking selection focuses the ward. Select its boundary on the map after clearing the inspector.
  const canvas = await page.locator('.map-canvas').boundingBox()
  if (!canvas) throw new Error('Map canvas is unavailable')
  const x = canvas.x + canvas.width / 2
  const y = canvas.y + canvas.height / 2
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return page.getByRole('tooltip').filter({ hasText: 'Demo North' }).count()
  }).toBe(1)
  await inspector.getByRole('button', { name: 'Clear ward selection' }).click()
  await page.mouse.click(x, y)
  await expect(ranking).toHaveAttribute('aria-pressed', 'true')

  await page.getByText('Layers', { exact: true }).click()
  const cellsResponse = page.waitForResponse((response) => response.url() === api + north + '/cells')
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  const cells = await cellsResponse
  expect(cells.headers()['content-type']).toContain('application/geo+json')
  expect(await cells.json()).toMatchObject({
    type: 'FeatureCollection',
    features: [{ properties: { cell_id: 'cell-001', ward_id: 'ward-001', suppressed: false } }],
  })
  await expect(page.getByRole('list', { name: 'Grid cells legend' })).toBeVisible()
  await page.getByText('Layers', { exact: true }).click()

  await page.getByRole('button', { name: 'Inspection brief' }).click()
  const brief = page.getByRole('dialog', { name: 'Ward inspection brief' })
  await expect(brief.getByText('API PDF available')).toBeVisible()
  await expect(brief.getByText('Synthetic demonstration', { exact: false })).toBeVisible()
  await expect(brief.getByRole('rowheader', { name: 'cell-001' })).toBeVisible()
  await brief.getByText('Preview API PDF', { exact: true }).click()
  const preview = brief.locator('object[type="application/pdf"]')
  await expect(preview).toBeVisible()
  await expect(preview).toHaveAttribute('data', /^blob:http:\/\/localhost:5173\//)
  const download = page.waitForEvent('download')
  await brief.getByRole('link', { name: 'Download PDF' }).click()
  const pdf = await download
  expect(pdf.suggestedFilename()).toBe('ward-ward-001-inspection.pdf')
  expect((await readFile(await pdf.path())).subarray(0, 5).toString()).toBe('%PDF-')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Validation' }).click()
  await expect(page.getByText(/Synthetic demo data · counts and settings/)).toBeVisible()
  await expect(page.getByRole('figure', { name: 'Incidents' })).toContainText('Full catalogue 26')
  expect([...responses].sort()).toEqual([
    '/health', '/meta', '/validation', '/wards', north, north + '/brief.pdf', north + '/cells',
  ])
})

test('rankings show loading and recover from a failed request', async ({ page }) => {
  let failRequest!: () => void
  const pending = new Promise<void>((resolve) => { failRequest = resolve })
  await page.route(api + '/wards?**', async (route) => {
    await pending
    await route.abort()
  }, { times: 1 })
  try {
    await page.goto('/')
    await expect(page.getByRole('status').filter({ hasText: 'Loading ward rankings' })).toBeVisible()
  } finally {
    failRequest()
  }
  const rankings = page.locator('#rankings')
  await expect(rankings.getByRole('alert')).toContainText('Ward rankings unavailable')
  await rankings.getByRole('button', { name: 'Try again' }).click()
  await expect(rankings.getByRole('button', { name: 'Demo North' })).toBeVisible()
})

test('CORS permits authority preflight and the protected resource rejects missing and invalid tokens', async ({ request }) => {
  const preflight = await request.fetch(buildings, {
    method: 'OPTIONS',
    headers: { Origin: origin, 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'x-authority-token' },
  })
  expect(preflight.status()).toBe(200)
  expect(preflight.headers()['access-control-allow-origin']).toBe(origin)
  expect(preflight.headers()['access-control-allow-headers'].toLowerCase()).toContain('x-authority-token')

  const response = await request.get(buildings, { headers: { Origin: origin } })
  expect(response.status()).toBe(401)
  expect(response.headers()['access-control-allow-origin']).toBe(origin)
  expect(response.headers()['cache-control']).toBe('no-store')
  expect(await response.json()).toMatchObject({ error: { code: 'authority_required' } })

  const invalid = await request.get(buildings, { headers: { Origin: origin, 'X-Authority-Token': 'invalid-playwright-credential' } })
  expect(invalid.status()).toBe(401)
  expect(invalid.headers()['cache-control']).toBe('no-store')
  expect(await invalid.json()).toMatchObject({ error: { code: 'authority_required' } })

  const missing = await request.get(api + '/wards/no-such-ward', { headers: { Origin: origin } })
  expect(missing.status()).toBe(404)
  expect(missing.headers()['access-control-allow-origin']).toBe(origin)
  expect(await missing.json()).toMatchObject({ error: { code: 'not_found' } })
})

test('building points can be inspected and disappear on sign out', async ({ page, context }) => {
  const credential = 'playwright-test-only'
  let viewportRequests = 0
  // The public routes remain live. Only the protected transport uses a test double.
  await page.route(api + '/buildings?**', async (route) => {
    const request = route.request()
    const headers = {
      'access-control-allow-origin': origin,
      'access-control-allow-headers': 'x-authority-token',
      'cache-control': 'no-store',
    }
    if (request.method() === 'OPTIONS') return route.fulfill({ headers })
    const query = new URL(request.url()).searchParams
    const viewport = query.get('limit') === '500'
    if (viewport) viewportRequests += 1
    if (request.headers()['x-authority-token'] !== credential) return route.fulfill({ status: 401, headers })

    const features = []
    if (viewport) {
      const [west, south, east, north] = (query.get('bbox') ?? '').split(',').map(Number)
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [(west + east) / 2, (south + north) / 2] },
        properties: { bldg_id: 'SYNTH-DEMO-001', vlm_mm_yr: -4.2, beta_ratio_horizon: '1/500', beta_class: 'inspect', sparse: false },
      })
    }
    await route.fulfill({ headers, json: { type: 'FeatureCollection', features } })
  })

  await page.goto('/')
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Authority access' }).click()
  await page.getByLabel('Authority token').fill(credential)
  await page.getByRole('button', { name: 'Verify access' }).click()
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Demo North', exact: true }).click()
  await page.getByText('Layers', { exact: true }).click()
  const toggle = page.getByRole('checkbox', { name: /Buildings/ })
  await toggle.check()
  await expect(page.getByRole('list', { name: 'Buildings legend' })).toBeVisible()
  await page.getByText('Layers', { exact: true }).click()

  const canvas = page.locator('.maplibregl-canvas')
  const bounds = await canvas.boundingBox()
  if (!bounds) throw new Error('Map canvas is unavailable')
  const x = bounds.x + bounds.width / 2
  const y = bounds.y + bounds.height / 2
  const tooltip = page.getByRole('tooltip').filter({ hasText: 'SYNTH-DEMO-001' })
  const inspector = page.getByRole('region', { name: 'Selected map feature' })
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return tooltip.count()
  }).toBe(1)
  await page.mouse.click(x, y)
  await expect(inspector).toContainText('SYNTH-DEMO-001')
  await expect(inspector.locator('dd')).toHaveText(['-4.2 mm/yr', '1/500', 'inspect', 'Coverage available'])

  const stored = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage, document.cookie]))
  expect(stored.includes(credential)).toBe(false)
  expect((await context.cookies()).some(({ value }) => value.includes(credential))).toBe(false)

  const previousRequests = viewportRequests
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  await expect(inspector).toHaveCount(0)
  await page.getByText('Layers', { exact: true }).click()
  await expect(toggle).toHaveCount(0)
  await page.getByText('Layers', { exact: true }).click()
  await page.mouse.move(x, y)
  await page.mouse.click(x, y)
  await expect(tooltip).toHaveCount(0)
  await expect(inspector).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Demo North', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(viewportRequests).toBe(previousRequests)
})
