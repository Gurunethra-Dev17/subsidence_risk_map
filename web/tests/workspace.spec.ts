import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

async function openMap(page: Page) {
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.abort())
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Reset map view' })).toBeVisible()
}

async function pointOnFixture(page: Page, longitude: number, latitude: number) {
  const bounds = await page.locator('.map-canvas').boundingBox()
  if (!bounds) throw new Error('Map canvas is unavailable')
  // Match the overview camera for the unmodified C0 fixture in EPSG:4326.
  const mercatorY = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2
  const top = mercatorY(28.62)
  const bottom = mercatorY(28.60)
  const scale = Math.min((bounds.width - 110) / (.02 / 360), (bounds.height - 110) / (bottom - top), 512 * 2 ** 14)
  return {
    x: bounds.x + bounds.width / 2 + (longitude - 77.01) / 360 * scale,
    y: bounds.y + bounds.height / 2 + (mercatorY(latitude) - (top + bottom) / 2) * scale,
  }
}

async function hoverFixture(page: Page, x: number, y: number, label: string) {
  await expect.poll(async () => {
    await page.mouse.move(x + 1, y)
    await page.mouse.move(x, y)
    return await page.getByRole('tooltip').first().textContent({ timeout: 700 }).catch(() => '')
  }).toContain(label)
}

test('offline basemap preserves map and ranking selection in both directions', async ({ page }) => {
  await openMap(page)
  await expect(page.getByText('Basemap unavailable · ward data visible')).toBeVisible()
  const { x, y } = await pointOnFixture(page, 77.005, 28.614)
  await hoverFixture(page, x, y, 'Demo Empty')
  await page.mouse.click(x, y)
  await expect(page.getByRole('button', { name: 'Demo Empty' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Available coverage is insufficient')).toBeVisible()
  await expect(page.getByText('No distortion histogram is available')).toBeVisible()
  await page.getByRole('button', { name: 'Demo North' }).click()
  await expect(page.getByRole('button', { name: 'Demo North' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Groundwater data missing')).toBeVisible()
  const bounds = await page.locator('.map-canvas').boundingBox()
  if (!bounds) throw new Error('Map canvas is unavailable')
  await hoverFixture(page, bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, 'Demo North')
})

test('keyboard ranking, risk filters and empty results', async ({ page }) => {
  await openMap(page)
  const filter = page.getByLabel('Filter by priority band')
  await filter.selectOption('insufficient')
  await expect(page.locator('.ward-select')).toHaveText('Demo Empty')
  await filter.selectOption('all')
  await page.getByRole('button', { name: 'Ward', exact: true }).click()
  await expect(page.locator('th[aria-sort=ascending]')).toHaveText('Ward')
  await expect(page.locator('.ward-select').first()).toHaveText('Demo Empty')
  await page.getByRole('searchbox', { name: 'Search wards' }).fill('no such ward')
  await expect(page.getByText('No wards match your search and filter.')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  const ward = page.getByRole('button', { name: 'Demo South' })
  await ward.focus()
  await expect(ward).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(ward).toHaveAttribute('aria-pressed', 'true')
})

test('public overlays, keyboard opacity and suppressed cell privacy', async ({ page }) => {
  await openMap(page)
  await page.getByText('Layers', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /Buildings/ })).toHaveCount(0)
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  const opacity = page.getByRole('slider', { name: 'Grid cells opacity' })
  await opacity.press('ArrowLeft')
  await expect(opacity).toHaveValue('84')
  await page.getByText('Layers', { exact: true }).click()
  const { x, y } = await pointOnFixture(page, 77.003, 28.6007)
  await hoverFixture(page, x, y, 'cell-002')
  await page.mouse.click(x, y)
  const feature = page.getByRole('region', { name: 'Selected map feature' })
  await expect(feature).toContainText('Suppressed')
  await expect(feature).not.toContainText('/100')
  await page.getByText('Layers', { exact: true }).click()
  await page.getByRole('checkbox', { name: /Grid cells/ }).uncheck()
  await expect(feature).toHaveCount(0)
})

test('mock brief fallback and authority gating at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openMap(page)
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Authority access' }).click()
  await expect(page.getByRole('dialog')).toContainText('unavailable in mock mode')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Authority access' })).toBeFocused()
  await page.getByRole('button', { name: 'Demo North' }).click()
  await page.getByRole('button', { name: 'Inspection brief' }).click()
  await expect(page.getByRole('dialog')).toContainText('Synthetic mock · print preview')
  await expect(page.getByRole('dialog')).toContainText('cell-001')
  await expect(page.getByRole('button', { name: 'Print / Save as PDF' })).toBeEnabled()
  await expect(page.getByRole('link', { name: 'Download PDF' })).toHaveCount(0)
})

test('appearance toggle persists and validation loads on demand', async ({ page }) => {
  await openMap(page)
  await expect(page.locator('html')).toHaveAttribute('data-appearance', 'light')
  await expect(page.locator('.map-canvas')).toHaveAttribute('data-basemap', 'street')
  await page.getByRole('button', { name: 'Switch to dark appearance' }).click()
  await expect(page.locator('.map-canvas')).toHaveAttribute('data-basemap', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-appearance', 'dark')
  await page.getByRole('button', { name: 'Validation' }).click()
  await expect(page.getByRole('figure', { name: 'Incidents' })).toContainText('Full catalogue 26')
})

test('basemap switching retains the canvas and selected ward', async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#324659' } }],
  } }))
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Reset map view' })).toBeVisible()
  await page.getByRole('button', { name: 'Demo North' }).click()
  const canvas = page.locator('.maplibregl-canvas')
  await canvas.evaluate((element) => { element.setAttribute('data-lifetime', 'initial') })
  await page.getByText('Layers', { exact: true }).click()
  await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === '/styles/dark'),
    page.getByRole('combobox', { name: 'Basemap', exact: true }).selectOption('dark'),
  ])
  await expect(canvas).toHaveAttribute('data-lifetime', 'initial')
  await expect(page.getByRole('button', { name: 'Demo North' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Switch to dark appearance' }).click()
  await page.getByRole('button', { name: 'Switch to light appearance' }).click()
  await expect(page.locator('.map-canvas')).toHaveAttribute('data-basemap', 'dark')
  await page.getByRole('combobox', { name: 'Basemap', exact: true }).selectOption('auto')
  await expect(page.locator('.map-canvas')).toHaveAttribute('data-basemap', 'street')
})
