import { readdir, readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { join } from 'node:path'

const output = new URL('../dist/', import.meta.url)
const files = await readdir(output, { recursive: true, withFileTypes: true })
for (const file of files) {
  assert.doesNotMatch(file.name, /^\.env(?:\.|$)|building_metrics|vt_building_risk|(?:wards|cell_scores|buildings)\.geojson|(?:ward_summary|validation_summary|export_metadata|pack_manifest|tiles_candidate)\.json|(?:ward_score_distribution|ward_rank_ranges|top_priority_ward_ranges|sensitivity_rank_range_width|weight_perturbation_rank_stability|a7_radius_pair_sensitivity|c1_metric_availability|literature_hotspot_reference_ranks)\.png|\.pmtiles$|\.parquet$|\.map$/i)
  if (!file.isFile()) continue
  if (!/\.(?:js|json|html|css)$/i.test(file.name)) continue
  const contents = await readFile(join(file.parentPath ?? file.path, file.name), 'utf8')
  assert.doesNotMatch(contents, /demo-authority|building_metrics\.json|vt_building_risk\.geojson|playwright-test-only|__delhi_preview|DELHI_(?:ANALYTICS|GEOGRAPHY)_DIR|subsidence-data|delhi-c2-c3-person-c|delhi-c5-local-testing-candidate|127\.0\.0\.1:800[23]|delhi-e9-person-c|E9_TEST_AUTHORITY_TOKEN/i)
}
console.log('Production artifacts contain no local environment files or known restricted fixture or test credential markers.')
