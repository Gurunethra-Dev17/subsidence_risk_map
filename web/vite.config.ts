import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import type { Plugin } from 'vite'
import type { components } from './types/openapi'
import { publicHttpUrl } from './src/api/publicUrl'

function publicFixtures(): Plugin {
  const id = 'virtual:public-fixtures'
  const root = new URL('../contracts/mock/', import.meta.url)
  type Api = components['schemas']

  return {
    name: 'public-contract-fixtures',
    resolveId(source) {
      return source === id ? '\0' + id : undefined
    },
    async load(source) {
      if (source !== '\0' + id) return

      const read = async (file: string) => {
        const path = fileURLToPath(new URL(file, root))
        this.addWatchFile(path)
        return readFile(path, 'utf8')
      }
      const [wards, validation, boundaries, cells, points, rawExamples] = await Promise.all([
        read('ward_summary.json'),
        read('validation_summary.json'),
        read('delhi-pack-0.0.1/wards.geojson'),
        read('cell_scores.geojson'),
        read('delhi-pack-0.0.1/vlm_points.csv'),
        read('api/responses.json'),
      ])
      const { meta, wards: page, health } = JSON.parse(rawExamples) as {
        meta: Pick<Api['MetaResponse'], 'contract_versions'>
        wards: Pick<Api['WardPage'], 'limit' | 'offset'>
        health: Api['Health']
      }
      const examples = {
        contractVersions: meta.contract_versions,
        limit: page.limit,
        offset: page.offset,
        health: { status: health.status, version: health.version },
      }

      // Export only the public examples used by the app.
      return `
        export const wards = ${JSON.stringify(wards)}
        export const validation = ${JSON.stringify(validation)}
        export const boundaries = ${JSON.stringify(boundaries)}
        export const cells = ${JSON.stringify(cells)}
        export const points = ${JSON.stringify(points)}
        export const examples = ${JSON.stringify(examples)}
      `
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)))
  if (Object.keys(env).some((key) => /(?:TOKEN|SECRET|PASSWORD)/i.test(key))) {
    throw new Error('Keep credentials out of all VITE_* configuration.')
  }
  for (const key of ['VITE_MOCK_MODE', 'VITE_BASEMAP_ENABLED']) {
    if (env[key]?.trim() && !/^(true|false)$/i.test(env[key].trim())) throw new Error(`${key} must be true or false.`)
  }
  for (const key of ['VITE_API_URL', 'VITE_WARDS_GEOJSON_URL', 'VITE_WARDS_TILE_URL', 'VITE_CELLS_TILE_URL', 'VITE_POINTS_TILE_URL', 'VITE_BASEMAP_TILE_URL', 'VITE_BASEMAP_STYLE_URL']) {
    if (!env[key]?.trim()) continue
    try { publicHttpUrl(env[key].trim(), 'https://frontend.invalid/') }
    catch { throw new Error(`${key} must be a relative, HTTPS or loopback URL without credentials.`) }
  }
  return {
  plugins: [react(), publicFixtures()],
  worker: { format: 'es' },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.replaceAll('\\', '/').includes('/maplibre-gl/dist/maplibre-gl.mjs')) return 'maplibre-engine'
        },
      },
    },
  },
  server: {
    // The browser can only access web/. The plugin reads the selected fixtures in Node.
    fs: { allow: [fileURLToPath(new URL('.', import.meta.url))] },
    watch: { ignored: ['**/.npm-cache/**'] },
  },
  }
})
