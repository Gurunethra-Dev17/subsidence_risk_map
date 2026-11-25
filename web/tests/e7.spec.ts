import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { Map as MapLibreMap } from 'maplibre-gl'
import type { components } from '../types/openapi'

type Api = components['schemas']
const origin = 'http://127.0.0.1:5173'
const geo = 'http://127.0.0.1:8003'
const api = 'http://127.0.0.1:8002/api/v1'
const manifestPath = geo + '/e7/overlay_manifest.json'
const imagePath = geo + '/e7/los_overlay.png'
const sourceId = 'overlay-fresh-insar'
const rasterId = sourceId + '-raster'
const corners = [
  [76.61587229394829, 28.648149926013904], [77.70824846425482, 28.648149926013904],
  [77.70824846425482, 28.25991027166655], [76.61587229394829, 28.25991027166655],
]
const layers = (page: Page) => page.getByText('Layers', { exact: true })
const fresh = (page: Page) => page.getByRole('checkbox', { name: 'Fresh InSAR Observation' })
const legend = (page: Page) => page.getByRole('figure', { name: 'Relative LOS displacement (cm)' })

test.beforeEach(async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.abort())
})

async function openLayers(page: Page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Basemap unavailable · ward data visible')).toBeVisible({ timeout: 25_000 })
  await layers(page).click()
}

test('real E7 is opt-in, positioned exactly, and survives style changes without refetching', async ({ page, request }) => {
  const seen: string[] = []
  page.on('request', (event) => {
    if (event.url().startsWith(geo + '/e7/')) seen.push(event.url())
  })
  await openLayers(page)
  await expect(fresh(page)).not.toBeChecked()
  await expect(legend(page)).toHaveCount(0)
  const analytics = process.env.DELHI_ANALYTICS_DIR || join(homedir(), 'Desktop', 'subsidence-data', 'delhi-c2-c3-person-c')
  const accepted = JSON.parse(await readFile(join(analytics, 'ward_summary.json'), 'utf8')) as { wards: Api['Ward'][] }
  const ranked = (await (await request.get(api + '/wards?sort=rank&order=asc&limit=250')).json() as Api['WardPage']).items
  const scores = (wards: Api['Ward'][]) => Object.fromEntries(wards.map((ward) =>
    [ward.ward_id, [ward.ward_name, ward.rank, ward.score, ward.status]]))
  expect(ranked).toHaveLength(250)
  expect(scores(ranked)).toEqual(scores(accepted.wards))
  expect(seen).toEqual([])

  // Inspect the actual MapLibre instance that installs the raster.
  await page.evaluate(async (id) => {
    const moduleUrl = performance.getEntriesByType('resource').map(({ name }) => name)
      .find((name) => /\/maplibre-gl(?:\.mjs|\.js)(?:\?|$)/.test(name))
    if (!moduleUrl) throw new Error('MapLibre module unavailable')
    const { Map }: typeof import('maplibre-gl') = await import(moduleUrl)
    const addLayer = Map.prototype.addLayer
    Map.prototype.addLayer = function (layer, before) {
      if (layer.id === id) {
        Reflect.set(window, 'e7TestMap', this)
        Reflect.set(window, 'e7TestInstallations', (Reflect.get(window, 'e7TestInstallations') ?? 0) + 1)
      }
      return addLayer.call(this, layer, before)
    }
  }, rasterId)
  const inspectStyle = () => page.evaluate(({ sourceId, rasterId }) => {
    const map = Reflect.get(window, 'e7TestMap') as MapLibreMap | undefined
    const style = map?.getStyle()
    const source = style?.sources[sourceId]
    return {
      source: source?.type === 'image' ? { type: source.type, coordinates: source.coordinates } : null,
      layers: style?.layers.map(({ id }) => id),
      resampling: map?.getLayer(rasterId) ? map.getPaintProperty(rasterId, 'raster-resampling') : null,
      installations: Reflect.get(window, 'e7TestInstallations') as number,
    }
  }, { sourceId, rasterId })

  const before = await (await request.get(api + '/wards/131/cells')).json()
  const ranking = page.getByRole('button', { name: 'BIJWASAN', exact: true })
  const wardRow = page.getByRole('row').filter({ has: ranking })
  const rankText = await wardRow.textContent()
  await ranking.click()
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  const started = performance.now()
  await fresh(page).check()
  await expect(legend(page)).toBeVisible()
  const first = Math.round(performance.now() - started)
  expect(seen).toEqual([manifestPath, imagePath])
  const style = await inspectStyle()
  expect(style.source).toEqual({ type: 'image', coordinates: corners })
  expect(style.resampling).toBe('nearest')
  const ids = style.layers!
  expect(ids.indexOf('inspection-ward-fill')).toBeLessThan(ids.indexOf(rasterId))
  expect(ids.indexOf(rasterId)).toBeLessThan(ids.indexOf('inspection-ward-outline'))
  expect(ids.indexOf(rasterId)).toBeLessThan(ids.indexOf('inspection-ward-selected'))
  await expect(legend(page)).toContainText('≤ −2.247 cm')
  await expect(legend(page)).toContainText('0 cm')
  await expect(legend(page)).toContainText('≥ +2.247 cm')
  await expect(page.getByText('Negative is away from the sensor', { exact: false })).toContainText('missing or masked observations')
  await page.getByText('Observation details and limitations').click()
  const detail = page.locator('.fresh-insar-details')
  for (const text of [
    'S1_056011_IW2_20261104_20261116_VV_INT80_A048', '4 November 2026', '16 November 2026',
    '12-day interferogram, VV polarization, 80 m product spacing', 'coherence threshold 0.30',
    '48.7%', '19.3%', '49 have usable observations and 201 have none', '69.8% (1,317', '38.8% (1,113',
    'symmetric 98th-percentile scale', 'cannot be interpreted as vertical subsidence',
    'ASF DAAC HyP3 2026 using hyp3_isce2 3.0.2 / ISCE 2.6.5. Contains modified Copernicus Sentinel data 2026, processed by ESA.',
  ]) await expect(detail).toContainText(text)
  await page.getByText('Observation details and limitations').click()

  const basemap = page.getByRole('combobox', { name: 'Basemap', exact: true })
  for (const [theme, installations] of [['dark', 2], ['street', 3]] as const) {
    await basemap.selectOption(theme)
    // Provider errors are controlled. The fallback styles still perform a real MapLibre style replacement.
    await expect(page.locator('.map-canvas')).toHaveAttribute('data-basemap', theme)
    await expect.poll(async () => (await inspectStyle()).installations).toBe(installations)
    await expect(fresh(page)).toBeChecked()
    await expect(legend(page)).toBeVisible()
    await expect.poll(async () => (await inspectStyle()).layers?.filter((id) => id === rasterId).length).toBe(1)
  }
  const renderedPixels = () => page.evaluate(() => {
    const map = Reflect.get(window, 'e7TestMap') as MapLibreMap
    return new Promise<string>((resolve) => {
      map.once('render', () => resolve(map.getCanvas().toDataURL('image/png')))
      map.triggerRepaint()
    })
  })
  const visiblePixels = await renderedPixels()
  await fresh(page).uncheck()
  await expect.poll(async () => (await inspectStyle()).source).toBeNull()
  expect(await renderedPixels() === visiblePixels).toBe(false)
  await expect(page.getByRole('checkbox', { name: /Grid cells/ })).toBeChecked()
  const toggle = performance.now()
  await fresh(page).check()
  await expect(legend(page)).toBeVisible()
  console.log('E7 map layer (ms, one local browser sample)', { first, repeat: Math.round(performance.now() - toggle) })
  expect(seen).toEqual([manifestPath, imagePath])
  expect(await wardRow.textContent()).toBe(rankText)
  expect(await (await request.get(api + '/wards/131/cells')).json()).toEqual(before)
  expect(scores((await (await request.get(api + '/wards?sort=rank&order=asc&limit=250')).json() as Api['WardPage']).items)).toEqual(scores(ranked))
  await expect(page.getByRole('checkbox', { name: /Radar points|Buildings/ })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(legend(page)).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('real artifact server serves pinned E7 bytes and keeps C5 range and gzip support', async ({ request }) => {
  const headers = { Origin: origin }
  const manifest = await request.get(manifestPath, { headers })
  expect(manifest.status()).toBe(200)
  expect(manifest.headers()).toMatchObject({ 'access-control-allow-origin': origin, 'cache-control': 'private, no-store' })
  expect((await manifest.json()).maplibre_corners_lon_lat).toEqual(corners)
  const image = await request.get(imagePath, { headers })
  expect(image.status()).toBe(200)
  expect(image.headers()['content-type']).toBe('image/png')
  expect(createHash('sha256').update(await image.body()).digest('hex')).toBe('20434023bc7de664608746a99a1bfe30b213d3f95e15b7e197c4f623d352f94e')
  expect((await request.head(imagePath, { headers })).headers()['content-length']).toBe('467682')
  expect((await request.get(imagePath, { headers: { ...headers, Range: 'bytes=0-7' } })).status()).toBe(206)
  expect((await request.get(imagePath, { headers: { ...headers, Range: 'bytes=900000-900001' } })).status()).toBe(416)
  expect((await request.fetch(imagePath, { method: 'OPTIONS', headers })).status()).toBe(204)
  for (const path of [
    '', 'los_relative_cm_masked.tif', 'qa_summary.json', 'api_fresh_data_status.json',
    'qa_corrected/los_overlay.png', '%2e%2e%2flos_overlay.png', '..%5cqa_corrected%5clos_overlay.png', 'los_overlay.png?file=other',
  ]) expect((await request.get(geo + '/e7/' + path, { headers })).status()).toBe(404)
  expect((await request.get(imagePath)).status()).toBe(403)
  expect((await request.get(imagePath, { headers: { Origin: 'https://unapproved.example' } })).status()).toBe(403)
  expect((await request.get(imagePath, { headers: { ...headers, Host: 'unapproved.example' } })).status()).toBe(403)
  const fallback = await request.get(geo + '/delhi/geojson/131.json')
  expect(fallback.headers()['content-encoding']).toBe('gzip')
  expect((await fallback.json()).features[0].properties.ward_id).toBe('131')
  const tiles = await request.get(geo + '/delhi/delhi-wards-candidate-0.0.3.pmtiles', { headers: { ...headers, Range: 'bytes=0-15' } })
  expect(tiles.status()).toBe(206)
  expect((await tiles.body()).subarray(0, 7).toString()).toBe('PMTiles')
})

test('controlled missing and malformed manifests show an error without requesting a PNG', async ({ page, request }) => {
  let attempted = 0
  let images = 0
  const headers = { 'access-control-allow-origin': origin }
  const manifest = await (await request.get(manifestPath, { headers: { Origin: origin } })).json()
  page.on('request', (request) => { if (request.url() === imagePath) images++ })
  await page.route(manifestPath, (route) => {
    attempted++
    if (attempted === 1) return route.fulfill({ status: 404, headers })
    if (attempted === 2) {
      return route.fulfill({ headers, json: { ...manifest, maplibre_corners_lon_lat: [...corners].reverse() } })
    }
    return route.continue()
  })
  await openLayers(page)
  await fresh(page).check()
  const message = page.getByText('Fresh observation could not be loaded.')
  await expect(message).toBeVisible()
  await expect(legend(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Retry observation' }).click()
  await expect(message).toBeVisible()
  expect(attempted).toBe(2)
  expect(images).toBe(0)
  await page.getByRole('button', { name: 'Retry observation' }).click()
  await expect(legend(page)).toBeVisible()
  expect(images).toBe(1)
})

test('controlled missing or corrupt image never displays a ready state', async ({ page }) => {
  await page.route(imagePath, (route) => route.fulfill({ status: 503 }), { times: 1 })
  await openLayers(page)
  await fresh(page).check()
  await expect(page.getByText('Fresh observation could not be loaded.')).toBeVisible()
  await expect(legend(page)).toHaveCount(0)
  await page.route(imagePath, (route) => route.fulfill({ contentType: 'image/png', body: 'bad image' }), { times: 1 })
  await page.getByRole('button', { name: 'Retry observation' }).click()
  await expect(page.getByText('Fresh observation could not be loaded.')).toBeVisible()
  await expect(legend(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Retry observation' }).click()
  await expect(legend(page)).toBeVisible()
})

test('real processed C3 status preserves historical evidence and malformed status stays unavailable', async ({ page, request }) => {
  const response = await request.get(api + '/validation')
  const validation = await response.json() as Api['ValidationSummary']
  expect(validation.fresh_data_check.status).toBe('processed_not_validated')
  expect(validation.fresh_data_check.note).toContain('historical pattern/sign comparison and independent validation were not run')
  await page.goto('/#validation')
  await expect(page.getByText('Fresh observation processed — not independently validated.', { exact: true })).toBeVisible()
  await expect(page.getByText('0.9241')).toBeVisible()
  await expect(page.getByText('Comparison matrix unavailable.')).toBeVisible()
  await page.route(api + '/validation', (route) => route.fulfill({
    json: { ...validation, fresh_data_check: { status: { unexpected: true }, note: 'Unknown observation' } },
  }))
  await page.reload()
  await expect(page.getByText(/Fresh-data check/)).toContainText('unavailable')
  await expect(page.getByText('Unknown observation')).toHaveCount(0)
  await expect(page.getByText('0.9241')).toBeVisible()
})
