import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const vite = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const result = spawnSync(process.execPath, [vite, 'build', '--outDir', '.npm-cache/c9-live'], {
  stdio: 'inherit',
  env: {
    ...process.env,
    VITE_MOCK_MODE: 'false',
    VITE_API_URL: '/api/v1',
    VITE_DELHI_DATA_VINTAGE: 'browser-test-vintage',
    VITE_DELHI_MAP_ATTRIBUTION: 'Browser test ward-source credit',
    VITE_WARDS_GEOJSON_URL: '/test-map/wards.geojson',
    VITE_WARDS_TILE_URL: '/test-map/wards.pmtiles',
    VITE_CELLS_TILE_URL: '/test-map/cells.pmtiles',
    VITE_POINTS_TILE_URL: '/test-map/points.pmtiles',
  },
})
if (result.error) throw result.error
process.exitCode = result.status ?? 1
