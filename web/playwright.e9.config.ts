import { defineConfig } from '@playwright/test'
import browserConfig from './playwright.config'

if (!process.env.E9_TEST_AUTHORITY_TOKEN) {
  throw new Error('Supply the temporary local E9 token to the test process.')
}
const e7 = process.env.VITE_E7_INTERNAL_PREVIEW?.trim().toLowerCase() === 'true'

export default defineConfig({
  ...browserConfig,
  testMatch: e7 ? ['**/e9.spec.ts', '**/e7.spec.ts'] : '**/e9.spec.ts',
  testIgnore: [],
  outputDir: '.npm-cache/e9-test-results',
  timeout: 100_000,
  use: { ...browserConfig.use, baseURL: 'http://127.0.0.1:5173', trace: 'off', screenshot: 'off', video: 'off' },
  webServer: {
    command: 'npm run dev:e9',
    url: 'http://127.0.0.1:5173',
    env: { AUTHORITY_TOKEN: '', E9_TEST_AUTHORITY_TOKEN: '' },
  },
})
