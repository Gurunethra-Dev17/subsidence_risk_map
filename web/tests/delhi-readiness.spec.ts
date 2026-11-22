import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { Polygon } from 'geojson'
import type { Ward, WardGeometry } from '../src/api/service'

const live = 'http://localhost:4181'
const artwork = '/test-map/'
const { meta, wards: syntheticWards } = JSON.parse(await readFile(
  new URL('../../contracts/mock/ward_summary.json', import.meta.url), 'utf8',
)) as { meta: { city: string; data_vintage: string; n_wards: number; n_ranked: number }; wards: Ward[] }

function polygon(x: number, y: number): Polygon {
  const lon = 77 + x * 0.005
  const lat = 28.6 + y * 0.005
  return { type: 'Polygon', coordinates: [[[lon, lat], [lon + 0.004, lat],
    [lon + 0.004, lat + 0.004], [lon, lat + 0.004], [lon, lat]]] }
}

// Transport fixtures exercise the expected ID set. They contain only invented polygons and names.
const wardBoundaries: WardGeometry = {
  type: 'FeatureCollection',
  features: Array.from({ length: 250 }, (_, index) => ({
    type: 'Feature', geometry: polygon(index % 25, Math.floor(index / 25)),
    properties: { ward_id: String(index + 1), ward_name: `Fixture Ward ${index + 1}`, score: 0 },
  })),
}
const wardList = wardBoundaries.features.map(({ properties }, index): Ward => ({
  ...syntheticWards[0], ward_id: properties.ward_id, ward_name: properties.ward_name,
  score: null, rank: index + 1, rank_p05: null, rank_p95: null,
}))

async function routeLive(page: Page, dataset: 'synthetic' | 'wrong-vintage' | 'wrong-ids' | 'matching') {
  const wards = dataset === 'synthetic' ? syntheticWards : dataset === 'wrong-ids'
    ? [{ ...wardList[0], ward_id: 'ward-001' }, ...wardList.slice(1)] : wardList
  const vintage = dataset === 'synthetic' ? 'synthetic' : dataset === 'wrong-vintage' ? 'another-vintage' : 'browser-test-vintage'
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.abort())
  await page.route(live + '/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname.slice('/api/v1'.length)
    if (path === '/health') return route.fulfill({ json: { status: 'ok', version: 'browser-test' } })
    if (path === '/meta') return route.fulfill({ json: { ...meta, data_vintage: vintage, n_wards: wards.length } })
    if (path === '/wards') return route.fulfill({ json: { items: wards, total: wards.length, offset: 0, limit: 500 } })
    if (path === '/wards/1/cells') return route.fulfill({ json: { type: 'FeatureCollection', features: [{
      type: 'Feature', geometry: polygon(0, 0), properties: { cell_id: 'cell-missing-coverage', ward_id: '1', cell_score: 0, cell_rank_in_ward: 1 },
    }] } })
    const ward = wards.find(({ ward_id }) => path === `/wards/${ward_id}`)
    return ward ? route.fulfill({ json: ward }) : route.fulfill({ status: 404 })
  })
  const requests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith(artwork)) requests.push(path)
  })
  return requests
}

test('matching synthetic data uses fixture wards and ignores configured real sources', async ({ page }) => {
  const requests = await routeLive(page, 'synthetic')
  await page.goto(live)
  await expect(page.getByRole('alert')).toContainText('Configured Delhi map sources are disabled while the API serves synthetic data.')
  await expect(page.getByText('Synthetic wards', { exact: true })).toBeVisible()
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.getByText('Layers', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /Radar points/ })).toHaveCount(0)
  expect(requests).toEqual([])
})

for (const dataset of ['wrong-vintage', 'wrong-ids'] as const) {
  test(`blocks configured assets for an API with ${dataset}`, async ({ page }) => {
    const requests = await routeLive(page, dataset)
    await page.goto(live)
    await expect(page.getByRole('alert')).toContainText('Dataset mismatch. Delhi map sources require the configured data vintage and all 250 matching ward IDs.')
    await expect(page.getByRole('button', { name: 'Fixture Ward 1', exact: true })).toBeVisible()
    await expect(page.locator('.maplibregl-canvas')).toHaveCount(0)
    expect(requests).toEqual([])
  })
}

test('mismatched GeoJSON IDs keep the map unavailable and rankings usable', async ({ page }) => {
  const requests = await routeLive(page, 'matching')
  await page.route(live + artwork + 'wards.geojson', (route) => route.fulfill({
    json: { ...wardBoundaries, features: wardBoundaries.features.slice(1) },
  }))
  await page.goto(live)
  await expect(page.getByRole('alert')).toContainText('Dataset mismatch. Ward boundary IDs do not match the API rankings.')
  await page.getByRole('button', { name: 'Fixture Ward 1', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Fixture Ward 1', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0)
  expect(requests).toEqual([artwork + 'wards.geojson'])
})

test('missing GeoJSON tries the configured archive and reports an unavailable archive', async ({ page }) => {
  const requests = await routeLive(page, 'matching')
  await page.route(live + artwork + '**', (route) => route.fulfill({ status: 404 }))
  await page.goto(live)
  await expect(page.getByText('Ward GeoJSON unavailable · using configured ward PMTiles.')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('The configured Delhi ward PMTiles could not be loaded.')
  await expect(page.getByRole('button', { name: 'Retry map' })).toBeVisible()
  expect([...new Set(requests)]).toEqual([artwork + 'wards.geojson', artwork + 'wards.pmtiles'])
})

test('approved URL loads ward geometry, shows missing scores, and falls back to API cells', async ({ page }) => {
  const requests = await routeLive(page, 'matching')
  await page.route(live + artwork + 'wards.geojson', (route) => route.fulfill({ json: wardBoundaries }))
  await page.route(live + artwork + 'cells.pmtiles', (route) => route.fulfill({ status: 404 }))
  await page.goto(live)
  await expect(page.getByText('Delhi wards · GeoJSON', { exact: true })).toBeVisible()
  await expect(page.getByText(/ground-motion data: Virginia Tech dataset.*Browser test ward-source credit/)).toBeVisible()
  await expect(page.getByText('Basemap unavailable · ward data visible')).toBeVisible()
  await page.getByRole('button', { name: 'Fixture Ward 1', exact: true }).click()

  const canvas = page.locator('.maplibregl-canvas')
  const box = await canvas.boundingBox()
  if (!box) throw new Error('Expected an interactive ward map')
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  const tooltip = page.getByRole('tooltip')
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return tooltip.filter({ hasText: 'Fixture Ward 1' }).filter({ hasText: 'Score unavailable' }).count()
  }).toBe(1)
  await page.getByText('Layers', { exact: true }).click()
  const fallback = page.waitForResponse((response) => response.url() === live + '/api/v1/wards/1/cells')
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  expect((await fallback).status()).toBe(200)
  await expect(page.getByText('Archive unavailable · using the API fallback')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Grid cells legend' })).toContainText('Metrics unavailable')
  await page.getByText('Layers', { exact: true }).click()
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return tooltip.filter({ hasText: 'cell-missing-coverage' }).count()
  }).toBe(1)
  await page.mouse.click(x, y)
  const cell = page.getByRole('region', { name: 'Selected map feature' })
  await expect(cell.locator('dd')).toHaveText(['Coverage unavailable', 'Unavailable', 'Unavailable'])
  expect([...new Set(requests)]).toEqual([artwork + 'wards.geojson', artwork + 'cells.pmtiles'])
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByText('Delhi wards · GeoJSON', { exact: true })).toBeVisible()
})

test('Methodology explains the documented engine scenario and its limits', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Methodology' }).click()
  await expect(page.getByRole('heading', { name: 'From radar observations to building indicators' })).toBeVisible()
  await expect(page.getByText(/0\.0002 per year.*0\.002 over 10 years/)).toBeVisible()
  await expect(page.getByText(/nine variants test parameter sensitivity/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Engine method and Delhi defaults' })).toHaveAttribute('href', /4883e08\/engine\/METHOD\.md$/)
})
