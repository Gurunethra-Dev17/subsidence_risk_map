import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { performance } from 'node:perf_hooks'
import { expect, test } from '@playwright/test'
import type { C2CellScoresGeoJSON, C2WardSummary } from '../types/contracts'
import type { components } from '../types/openapi'
import { scoreBand, showNumber } from '../src/wardMetrics'

const local = '/__delhi_preview'
const api = local + '/api'
const read = async <T>(file: string): Promise<T> => JSON.parse(await readFile(join(process.env.DELHI_ANALYTICS_DIR!, file), 'utf8'))

test.beforeEach(async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/**', (route) => route.abort())
})

test('C4 preview serves the checked-in contracts from external exports and rejects private routes', async ({ request }) => {
  const [summary, sourceCells] = await Promise.all([read<C2WardSummary>('ward_summary.json'), read<C2CellScoresGeoJSON>('cell_scores.geojson')])
  const wards = await request.get(api + '/wards?limit=500')
  expect(wards.ok()).toBeTruthy()
  const list = await wards.json()
  expect(list.total).toBe(summary.meta.n_wards)
  expect(list.items).toEqual([...summary.wards].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity)))
  const boundary = await request.get(local + '/wards.geojson')
  const features = (await boundary.json()).features as { properties: { ward_id: string } }[]
  expect(features.map((feature) => feature.properties.ward_id).sort()).toEqual(summary.wards.map((ward) => ward.ward_id).sort())
  const id = list.items[0].ward_id
  expect(await (await request.get(api + '/wards/' + id)).json()).toEqual(list.items[0])
  const cells = await request.get(api + '/wards/' + id + '/cells')
  expect(cells.headers()['content-type']).toContain('application/geo+json')
  expect((await cells.json()).features).toEqual(sourceCells.features.filter(({ properties }) => properties.ward_id === id))
  expect((await request.get(api + '/buildings')).status()).toBe(401)
  expect((await request.get(api + '/wards/' + id + '/brief.pdf')).status()).toBe(501)
  expect((await request.get(api + '/meta', { headers: { Origin: 'https://unrelated.example' } })).status()).toBe(403)
  expect((await request.get(local + '/figures/unlisted.png')).status()).toBe(404)
  expect((await request.get(api + '/meta')).headers()['cache-control']).toBe('no-store')
})

test('actual ward rankings, map, inspector and brief share selection and keep missing values', async ({ page }, info) => {
  const summary = await read<C2WardSummary>('ward_summary.json')
  const high = summary.wards.find((ward) => ward.rank === 1)!
  const low = summary.wards.find((ward) => ward.rank === summary.meta.n_ranked)!
  const insufficient = summary.wards.find((ward) => ward.status === 'insufficient_data')!
  const start = performance.now()
  await page.goto('/')
  await expect(page.getByText('Internal Delhi candidate preview', { exact: true })).toBeVisible()
  await expect(page.locator('.ward-select')).toHaveCount(summary.meta.n_wards)
  const wardList = performance.now()
  await expect(page.getByText('Basemap unavailable · ward data visible')).toBeVisible()
  const map = performance.now()
  const ranking = page.getByRole('button', { name: high.ward_name, exact: true })
  await expect(ranking.locator('xpath=ancestor::tr')).toContainText(showNumber(high.score))
  const search = page.getByRole('searchbox', { name: 'Search wards' })
  await search.fill(insufficient.ward_name)
  await page.getByRole('combobox', { name: 'Filter by priority band' }).selectOption('insufficient')
  await page.getByRole('button', { name: insufficient.ward_name, exact: true }).click()
  await expect(page.locator('.ward-summary')).toContainText('Insufficient data')
  await search.fill(low.ward_name)
  await page.getByRole('combobox', { name: 'Filter by priority band' }).selectOption('all')
  await page.getByRole('button', { name: low.ward_name, exact: true }).click()
  await expect(page.locator('.ward-summary')).toContainText(scoreBand(low.status, low.score).label)
  await search.fill(high.ward_name)
  const selection = performance.now()
  await ranking.focus()
  await ranking.press('Enter')
  await expect(ranking).toHaveAttribute('aria-pressed', 'true')
  const selected = performance.now()
  const canvas = await page.locator('.maplibregl-canvas').boundingBox()
  if (!canvas) throw new Error('Delhi ward canvas did not render.')
  const x = canvas.x + canvas.width / 2
  const y = canvas.y + canvas.height / 2
  const tooltip = page.getByRole('tooltip').filter({ hasText: high.ward_name })
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return tooltip.count()
  }).toBe(1)
  await expect(tooltip).toContainText(`${showNumber(high.score)}/100 · Rank #${high.rank}`)
  await page.getByRole('button', { name: 'Clear ward selection' }).click()
  await page.mouse.click(x, y)
  await expect(ranking).toHaveAttribute('aria-pressed', 'true')
  await page.getByText('Layers', { exact: true }).click()
  const cellStart = performance.now()
  const response = page.waitForResponse((result) => result.url().endsWith(api + '/wards/' + high.ward_id + '/cells'))
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  const { features } = await (await response).json() as C2CellScoresGeoJSON
  await expect(page.getByRole('list', { name: 'Grid cells legend' })).toContainText('Suppressed')
  const cells = performance.now()
  await expect(page.getByRole('checkbox', { name: /Radar points|Buildings/ })).toHaveCount(0)
  await page.getByRole('slider', { name: 'Grid cells opacity' }).press('ArrowLeft')
  await page.getByText('Layers', { exact: true }).click()
  await expect(page.getByRole('button', { name: '2D plan' })).toBeVisible()
  await page.getByRole('button', { name: '3D buildings' }).click()
  await expect(ranking).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '2D plan' }).click()
  await page.screenshot({ path: info.outputPath('delhi-map.png') })
  const navigationStart = performance.now()
  await page.getByRole('link', { name: 'Open Ward Inspector' }).click()
  const inspector = page.locator('#inspector')
  await expect(inspector.getByRole('heading', { name: high.ward_name })).toBeVisible()
  const inspectorReady = performance.now()
  await expect(inspector.locator('dl').filter({ hasText: 'Groundwater extraction' })).toContainText('Unavailable')
  await expect(inspector.locator('dl').filter({ hasText: '90th percentile distortion' })).toContainText(high.beta_p90_horizon!.toPrecision(4))
  await expect(inspector).toContainText('No distortion histogram is available for this ward.')
  await page.screenshot({ path: info.outputPath('delhi-inspector.png') })
  await page.getByRole('link', { name: 'Open Inspection Brief' }).click()
  const brief = page.getByRole('region', { name: 'Ward inspection brief' })
  await expect(brief).toContainText('browser print fallback')
  await expect(brief).toContainText(high.ward_name)
  const publishable = features.filter(({ properties }) => properties.suppressed === false && properties.cell_rank_in_ward !== null && properties.cell_score !== null)
  await expect(brief.getByRole('rowheader')).toHaveCount(publishable.length)
  const suppressed = features.find(({ properties }) => properties.suppressed)
  expect(suppressed).toBeDefined()
  await expect(brief.getByRole('rowheader', { name: suppressed?.properties.cell_id })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.emulateMedia({ media: 'print' })
  await expect(brief.getByRole('heading', { name: high.ward_name })).toBeVisible()
  await page.screenshot({ path: info.outputPath('delhi-brief-print.png') })
  await page.emulateMedia({ media: 'screen' })
  await page.goBack()
  await expect(inspector).toContainText(high.ward_name)
  await page.goForward()
  await expect(brief).toContainText(high.ward_name)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Inspection Brief', exact: true })).toBeVisible()
  const timings = { wardList: wardList - start, wardMap: map - start, selection: selected - selection, cells: cells - cellStart, inspector: inspectorReady - navigationStart }
  console.log('Internal preview timings (ms)', Object.fromEntries(Object.entries(timings).map(([name, time]) => [name, Math.round(time)])))
})

test('validation preserves absent evidence and loads the supplied local figures', async ({ page, request }, info) => {
  const validation = await read<components['schemas']['ValidationSummary']>('validation_summary.json')
  await page.goto('/')
  await page.getByRole('link', { name: 'Methods & Evidence' }).click()
  await expect(page.getByText(/at distances of 80–120 m inclusive/)).toBeVisible()
  await expect(page.getByText(/35\.29%.*41\.18%.*23\.53%/)).toBeVisible()
  await page.getByRole('link', { name: 'Validation', exact: true }).click()
  await expect(page.getByText('Comparison matrix unavailable.')).toBeVisible()
  await expect(page.getByText(/Kendall τ unavailable at 50 m/)).toBeVisible()
  await expect(page.getByText(/Fresh-data check/)).toContainText('not run')
  await expect(page.getByRole('list').filter({ hasText: 'Kapashera' })).toContainText('Bijwasan')
  const figures = page.getByRole('heading', { name: 'Internal validation figures' }).locator('..')
  await expect(figures.getByRole('img')).toHaveCount(validation.figures.length)
  for (const figure of validation.figures) {
    const image = await request.get(local + '/' + figure.path)
    expect(image.headers()['content-type']).toBe('image/png')
    expect((await image.body()).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  }
  await page.screenshot({ path: info.outputPath('delhi-validation.png') })
})

test('failed real loading offers retry without synthetic substitution', async ({ page }) => {
  await page.route('**' + api + '/meta', (route) => route.fulfill({ status: 503 }))
  await page.goto('/')
  const error = page.getByRole('alert').filter({ hasText: 'City metadata unavailable' })
  await expect(error).toBeVisible()
  await expect(page.getByText('Synthetic wards', { exact: true })).toHaveCount(0)
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0)
  await page.unroute('**' + api + '/meta')
  await error.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Delhi wards · GeoJSON', { exact: true })).toBeVisible()
})
