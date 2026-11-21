import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const vite = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const result = spawnSync(process.execPath, [vite, 'build', '--outDir', '.npm-cache/c9-live'], {
  stdio: 'inherit',
  env: { ...process.env, VITE_MOCK_MODE: 'false', VITE_API_URL: '/api/v1', VITE_WARDS_TILE_URL: '' },
})
if (result.error) throw result.error
process.exitCode = result.status ?? 1
