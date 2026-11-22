import { readdir, readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { join } from 'node:path'

const output = new URL('../dist/', import.meta.url)
const files = await readdir(output, { recursive: true, withFileTypes: true })
for (const file of files) {
  assert.doesNotMatch(file.name, /^\.env(?:\.|$)|building_metrics|vt_building_risk|buildings\.geojson|\.pmtiles$|\.parquet$|\.map$/i)
  if (!file.isFile()) continue
  if (!/\.(?:js|json|html|css)$/i.test(file.name)) continue
  const contents = await readFile(join(file.parentPath ?? file.path, file.name), 'utf8')
  assert.doesNotMatch(contents, /demo-authority|building_metrics\.json|vt_building_risk\.geojson|playwright-test-only/)
}
console.log('Production artifacts contain no local environment files or known restricted fixture or test credential markers.')
