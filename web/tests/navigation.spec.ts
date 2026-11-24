import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

const mainViews = ['Overview Map', 'Ward Inspector', 'Inspection Brief']

function restrictedRequests(page: Page) {
  const restricted: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (/\/buildings(?:\/|$)|(?:points|buildings).*\.pmtiles$/i.test(path)) restricted.push(path)
  })
  return restricted
}

async function readSelect(select: Locator) {
  return select.evaluate((element: HTMLSelectElement) => {
    const control = getComputedStyle(element)
    const option = getComputedStyle(element.selectedOptions[0])
    const rgb = (color: string) => color.match(/\d+(\.\d+)?/g)?.slice(0, 3).map(Number) ?? []
    const luminance = (color: string) => rgb(color).map((part) => part / 255)
      .map((part) => part <= 0.04045 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4)
      .reduce((sum, part, i) => sum + part * [0.2126, 0.7152, 0.0722][i], 0)
    const contrast = (foreground: string, background: string) => {
      const levels = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
      return (levels[0] + 0.05) / (levels[1] + 0.05)
    }
    return {
      scheme: control.colorScheme,
      native: control.appearance,
      focus: control.outlineStyle,
      textContrast: contrast(control.color, control.backgroundColor),
      optionContrast: contrast(option.color, option.backgroundColor),
    }
  })
}

test.beforeEach(async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.abort())
})

test('dedicated views share selection, history, map camera and ranking controls', async ({ page }, testInfo) => {
  const restricted = restrictedRequests(page)
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: 'Workspace' })
  await expect(nav.getByRole('link')).toHaveText(mainViews)
  await expect(nav.getByRole('link', { name: 'Overview Map' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('button', { name: 'Reset map view' })).toBeVisible()
  await page.getByRole('button', { name: 'Demo North' }).click()
  await page.getByRole('button', { name: '2D plan' }).click()
  await page.getByRole('button', { name: 'Zoom out' }).click()
  await page.getByRole('searchbox', { name: 'Search wards' }).fill('Demo')
  await page.getByLabel('Filter by priority band').selectOption('higher')
  await page.getByRole('button', { name: 'Coverage', exact: true }).click()
  await page.getByText('Layers', { exact: true }).click()
  await page.getByRole('combobox', { name: 'Basemap', exact: true }).selectOption('dark')
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  await page.getByRole('slider', { name: 'Grid cells opacity' }).press('Home')
  const canvas = page.locator('.maplibregl-canvas')
  const canvasHandle = await canvas.elementHandle()
  const scale = page.locator('.maplibregl-ctrl-scale')
  await expect(scale).toHaveText(/\d/)
  await expect(page.getByRole('list', { name: 'Grid cells legend' })).toBeVisible()
  const scaleText = await scale.innerText()
  await page.getByText('Layers', { exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('desktop-overview.png') })

  await page.getByRole('link', { name: 'Open Ward Inspector' }).click()
  await expect(page.getByRole('heading', { name: 'Ward Inspector' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Demo North' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Ward', exact: true })).toHaveValue('ward-001')
  await expect(page.getByRole('progressbar', { name: 'Building data coverage' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-inspector.png'), fullPage: true })
  await page.goBack()
  await expect(canvas).toBeVisible()
  expect(await canvasHandle?.evaluate((element) => element === document.querySelector('.maplibregl-canvas'))).toBe(true)
  await expect(scale).toHaveText(scaleText)
  await expect(page.getByRole('searchbox', { name: 'Search wards' })).toHaveValue('Demo')
  await expect(page.getByLabel('Filter by priority band')).toHaveValue('higher')
  await expect(page.locator('th[aria-sort=descending]')).toHaveText('Coverage')
  await expect(page.getByRole('button', { name: '2D plan' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByText('Layers', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /Grid cells/ })).toBeChecked()
  await expect(page.getByRole('slider', { name: 'Grid cells opacity' })).toHaveValue('15')
  await expect(page.getByRole('combobox', { name: 'Basemap', exact: true })).toHaveValue('dark')
  await expect(page.getByRole('checkbox', { name: /Buildings/ })).toHaveCount(0)
  await page.goForward()
  await page.getByRole('combobox', { name: 'Ward', exact: true }).selectOption('ward-002')
  await expect(page.getByRole('heading', { name: 'Demo South' })).toBeVisible()
  await page.getByRole('link', { name: 'Open Inspection Brief' }).click()
  const brief = page.getByRole('region', { name: 'Ward inspection brief' })
  await expect(brief.getByRole('heading', { name: 'Demo South' })).toBeVisible()
  await expect(brief.getByRole('heading', { name: 'Demo North' })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Demo South' })).toBeVisible()
  await page.getByRole('link', { name: 'Back to Overview Map' }).click()
  await page.getByRole('button', { name: 'Show all' }).click()
  await expect(page.getByRole('button', { name: 'Demo South' })).toHaveAttribute('aria-pressed', 'true')
  expect(restricted).toEqual([])
})

test('native selects are readable and keyboard focusable in both themes at tablet width', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.goto('/')
  await page.getByText('Layers', { exact: true }).click()
  const mapSelects = [page.getByLabel('Filter by priority band'), page.getByRole('combobox', { name: 'Basemap', exact: true })]
  for (const scheme of ['light', 'dark']) {
    if (scheme === 'dark') await page.getByRole('button', { name: 'Switch to dark appearance' }).click()
    await page.keyboard.press('Tab')
    for (const select of mapSelects) {
      await select.focus()
      await expect(select).toBeFocused()
      const style = await readSelect(select)
      expect(style.scheme).toBe(scheme)
      expect(style.native).toBe('auto')
      expect(style.focus).toBe('solid')
      expect(style.textContrast).toBeGreaterThan(4.5)
      expect(style.optionContrast).toBeGreaterThan(4.5)
    }
  }
  await page.screenshot({ path: testInfo.outputPath('tablet-dark-controls.png') })
  await page.getByRole('link', { name: 'Ward Inspector', exact: true }).click()
  const wards = page.getByRole('combobox', { name: 'Ward', exact: true })
  await expect(wards).toBeEnabled()
  await wards.focus()
  await page.keyboard.press('End')
  await expect(wards).toHaveValue('ward-003')
  await expect(page.getByRole('heading', { name: 'Demo Empty' })).toBeVisible()
  const style = await readSelect(wards)
  expect(style.scheme).toBe('dark')
  expect(style.optionContrast).toBeGreaterThan(4.5)
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(768)
})

test('mobile navigation, deep links and refresh keep a predictable public workspace', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#inspector')
  const nav = page.getByRole('navigation', { name: 'Workspace' })
  await expect(nav.getByRole('link')).toHaveText(mainViews)
  await expect(page.getByRole('heading', { name: 'Select a ward' })).toBeVisible()
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0)
  const ward = page.getByRole('combobox', { name: 'Ward', exact: true })
  await ward.selectOption('ward-001')
  await expect(page.getByRole('heading', { name: 'Demo North' })).toBeVisible()
  await page.getByRole('link', { name: 'Open Inspection Brief' }).click()
  await expect(page.getByRole('heading', { name: 'Demo North' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Print / Save as PDF' })).toBeEnabled()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: testInfo.outputPath('mobile-brief.png'), fullPage: true })
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Inspection Brief', exact: true })).toBeVisible()
  await expect(ward).toHaveValue('')
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Authority access' })).toBeVisible()
  await page.getByRole('link', { name: 'Methods & Evidence' }).click()
  const sections = page.getByRole('navigation', { name: 'Evidence sections' })
  await expect(sections.getByRole('link')).toHaveText(['Methodology', 'Validation', 'Limitations'])
  await sections.getByRole('link', { name: 'Limitations' }).click()
  await expect(page.getByText(/10-year distortion scenario assumes constant/)).toBeVisible()
  await sections.getByRole('link', { name: 'Validation' }).click()
  await expect(page.getByRole('figure', { name: 'Incidents' })).toContainText('Full catalogue 26')
  await expect(page.getByText('Comparison matrix unavailable.')).toBeVisible()
  await page.setViewportSize({ width: 320, height: 720 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Scientific limitations' })).toBeVisible()
})
