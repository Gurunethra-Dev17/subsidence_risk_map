import { defineConfig } from '@playwright/test'
import browserConfig from './playwright.config'

export default defineConfig({
  ...browserConfig,
  testMatch: '**/live-api.spec.ts',
  testIgnore: [],
  outputDir: '.npm-cache/live-test-results',
  use: { ...browserConfig.use, baseURL: 'http://localhost:5173' },
  webServer: { command: 'npm run dev:live', url: 'http://localhost:5173' },
})
