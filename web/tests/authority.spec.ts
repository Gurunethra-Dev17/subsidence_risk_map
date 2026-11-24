import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const live = 'http://localhost:4181'
const credential = 'playwright-test-only'

async function prepare(page: Page, status: number) {
  const protectedRequests: { supplied: boolean; url: string }[] = []
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith('/buildings')) {
      const supplied = request.headers()['x-authority-token'] === credential
      protectedRequests.push({ supplied, url: request.url() })
      // Transport double only. It does not implement or replace the deployed backend.
      await route.fulfill(status === 200
        ? { json: { type: 'FeatureCollection', features: [] } }
        : { status, json: { error: { message: 'Rejected' } } })
    } else {
      await route.fulfill({ status: 503, json: { error: { message: 'Service unavailable' } } })
    }
  })
  await page.goto(live, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  return protectedRequests
}

async function signIn(page: Page) {
  await page.getByRole('button', { name: 'Authority access' }).click()
  await page.getByLabel('Authority token').fill(credential)
  await page.getByRole('button', { name: 'Verify access' }).click()
}

test('API errors can retry and rejected credentials leave public mode active', async ({ page }) => {
  const requests = await prepare(page, 401)
  const ranking = page.locator('#rankings')
  await expect(ranking.getByRole('alert')).toContainText('Service unavailable')
  const retry = page.waitForRequest((request) => new URL(request.url()).pathname === '/api/v1/wards')
  await ranking.getByRole('button', { name: 'Try again' }).click()
  await retry
  expect(requests).toHaveLength(0)
  await signIn(page)
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('rejected authority access')
  await expect(page.getByLabel('Authority token')).toHaveValue('')
  expect(requests.map(({ supplied }) => supplied)).toEqual([true])
  await page.keyboard.press('Escape')
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Switch to dark appearance' }).click()
  await page.getByRole('link', { name: 'Ward Inspector', exact: true }).click()
  const ward = page.getByRole('combobox', { name: 'Ward', exact: true })
  await expect(ward).toBeDisabled()
  await expect(ward).toHaveCSS('color-scheme', 'dark')
  await expect(ward).toHaveCSS('opacity', '1')
})

test('verified transport grants a memory-only session, and logout revokes it', async ({ page }) => {
  const requests = await prepare(page, 200)
  expect(requests).toHaveLength(0)
  await signIn(page)
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Ward Inspector', exact: true }).click()
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  expect(requests.map(({ supplied }) => supplied)).toEqual([true])
  expect(requests.every(({ url }) => !url.includes(credential))).toBe(true)
  expect(await page.evaluate((secret) => JSON.stringify([localStorage, sessionStorage]).includes(secret), credential)).toBe(false)
  await signIn(page)
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Ward Inspector' })).toBeVisible()
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  expect(requests.map(({ supplied }) => supplied)).toEqual([true, true])
})

test('authority expires and the page returns to public mode', async ({ page }) => {
  const requests = await prepare(page, 200)
  await page.clock.install()
  await signIn(page)
  await expect(page.getByText('Authority mode', { exact: true })).toBeVisible()
  await page.clock.fastForward('20:01')
  await expect(page.getByText('Authority session expired.')).toBeVisible()
  await expect(page.getByText('Public mode', { exact: true })).toBeVisible()
  expect(requests).toHaveLength(1)
})
