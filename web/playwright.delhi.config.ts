import { defineConfig } from '@playwright/test'
import browserConfig from './playwright.config'

if (!process.env.DELHI_ANALYTICS_DIR || !process.env.DELHI_GEOGRAPHY_DIR) {
  throw new Error('Set both external package directories to opt in to the internal Delhi tests.')
}

export default defineConfig({
  ...browserConfig,
  testMatch: '**/delhi-preview.spec.ts',
  testIgnore: [],
  outputDir: '.npm-cache/delhi-test-results',
  use: { ...browserConfig.use, baseURL: 'http://127.0.0.1:5173' },
  webServer: { command: 'npm run dev:delhi', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
})
