import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import { GeoJSONVT } from '@maplibre/geojson-vt'
import { fromGeojsonVt } from '@maplibre/vt-pbf'
import type { FeatureCollection } from 'geojson'

test('height-enabled vector tiles render in 3D and switching preserves ward selection and layers', async ({ page }) => {
  const fixture = JSON.parse(await readFile(
    new URL('../../contracts/mock/delhi-pack-0.0.1/wards.geojson', import.meta.url), 'utf8',
  )) as FeatureCollection
  // Test transport only. Use existing synthetic footprints and explicit test heights.
  // This response never ships in the app or acts as real geographic data.
  const tiles = new GeoJSONVT({
    type: 'FeatureCollection',
    features: fixture.features.map((feature) => ({ ...feature, properties: { render_height: 35, render_min_height: 0 } })),
  })
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.fulfill({ json: {
    version: 8,
    sources: { test: { type: 'vector', tiles: ['https://tiles.example.test/three/{z}/{x}/{y}.pbf'], maxzoom: 14 } },
    layers: [
      { id: 'test-ground', type: 'background', paint: { 'background-color': '#edf2f5' } },
      { id: 'test-footprints', type: 'fill', source: 'test', 'source-layer': 'building', paint: { 'fill-color': '#bdc5cd' } },
    ],
  } }))
  await page.route('https://tiles.example.test/three/**', (route) => {
    const [z, x, y] = new URL(route.request().url()).pathname.split('/').slice(2).map(parseFloat)
    const tile = tiles.getTile(z, x, y)
    return route.fulfill({ contentType: 'application/x-protobuf', body: tile ? Buffer.from(fromGeojsonVt({ building: tile }, { version: 2, extent: 4096 })) : Buffer.alloc(0) })
  })
  await page.goto('/')
  const map = page.locator('.map-canvas')
  await expect(map).toHaveAttribute('data-perspective', '3d')
  await expect(page.getByText('Public building heights may be estimated')).toBeVisible()
  await page.getByRole('button', { name: 'Rotate map left' }).click()
  await page.getByRole('button', { name: 'Demo North' }).click()
  await page.getByText('Layers', { exact: true }).click()
  await page.getByRole('checkbox', { name: /Grid cells/ }).check()
  await page.getByText('Layers', { exact: true }).click()
  await page.getByRole('button', { name: '2D plan' }).click()
  await expect(map).toHaveAttribute('data-perspective', '2d')
  await page.getByRole('button', { name: '3D buildings' }).click()
  await expect(map).toHaveAttribute('data-perspective', '3d')
  await expect(page.getByRole('button', { name: 'Demo North' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByText('Layers', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /Grid cells/ })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: /^Buildings/ })).toHaveCount(0)
  await page.getByRole('link', { name: 'Open Ward Inspector' }).click()
  await expect(page.getByRole('heading', { name: 'Demo North' })).toBeVisible()
  await page.getByRole('link', { name: 'Back to Overview Map' }).click()
  await expect(map).toHaveAttribute('data-perspective', '3d')
  await expect(page.getByRole('button', { name: 'Rotate map left' })).toBeVisible()
})

test('without WebGL the published ward geometries remain selectable from a keyboard', async ({ page }) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, id: string, ...args: unknown[]) {
      if (id === 'webgl2' || id === 'webgl' || id === 'experimental-webgl') return null
      return Reflect.apply(getContext, this, [id, ...args])
    } as typeof getContext
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('2D ward plan remains selectable')
  const ward = page.getByRole('button', { name: /Demo North · Higher priority/ })
  await ward.focus()
  await page.keyboard.press('Enter')
  await expect(ward).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Demo North', exact: true })).toHaveAttribute('aria-pressed', 'true')
})
