import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testIgnore: ['**/live-api.spec.ts', '**/delhi-preview.spec.ts', '**/e9.spec.ts', '**/e7.spec.ts'],
  outputDir: '.npm-cache/test-results',
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://localhost:4173',
    browserName: 'chromium',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1440, height: 1000 },
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
  webServer: [
    { command: 'npm run preview', url: 'http://localhost:4173', env: { VITE_MOCK_MODE: 'true' } },
    { command: 'npm run preview -- --port 4181 --outDir .npm-cache/c9-live', url: 'http://localhost:4181' },
  ],
})
