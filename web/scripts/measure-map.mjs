import { chromium } from '@playwright/test'

const urls = process.argv.slice(2)
if (!urls.length) throw new Error('Pass one or more URLs of local production previews.')
const browser = await chromium.launch({
  channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})

try {
  for (const url of urls) {
    const samples = []
    for (let run = 0; run < 5; run += 1) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
      try {
        const page = await context.newPage()
        await page.route('https://tiles.openfreemap.org/styles/**', async (route) => {
          await new Promise((resolve) => setTimeout(resolve, 1000))
          await route.abort()
        })
        const start = performance.now()
        await page.goto(url, { waitUntil: 'domcontentloaded' })
        await page.getByRole('button', { name: 'Reset map view' }).waitFor({ timeout: 30_000 })
        samples.push(Math.round(performance.now() - start))
      } finally {
        await context.close()
      }
    }
    console.log(`${url} · reset control ready median ${[...samples].sort((a, b) => a - b)[2]} ms · runs ${samples.join(', ')}`)
  }
} finally {
  await browser.close()
}
