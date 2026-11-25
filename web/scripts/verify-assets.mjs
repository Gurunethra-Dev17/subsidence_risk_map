import { readdir, readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { join } from 'node:path'

const output = new URL('../dist/', import.meta.url)
const files = await readdir(output, { recursive: true, withFileTypes: true })
const e7Files = /^(?:api_fresh_data_status\.json|los_overlay\.png|los_relative_cm_masked\.tif|overlay_manifest\.json|person_c_handoff\.md|qa_overview\.png|qa_summary\.json|ward_coverage\.png|sha256sums\.txt)$/i
const e7Markers = /\/e7\/|VITE_E7_INTERNAL_PREVIEW|LOS_OVERLAY\.PNG|overlay_manifest\.json|S1_056011_IW2_20261104_20261116_VV_INT80_A048|20434023bc7de664608746a99a1bfe30b213d3f95e15b7e197c4f623d352f94e/i
const e7Digests = new Set([
  '23a54e0b48c8a0327bebd64ffc868f132b616e7f750b5ef9289f070d2992bd81',
  '20434023bc7de664608746a99a1bfe30b213d3f95e15b7e197c4f623d352f94e',
  'abbc137a5c2c070855062dbee53033f78570eaa30cf483e39d3c029fe64ec11f',
  '8bbbf1824ad3455044edb3ee951af95cafe2a0996b4ead3cdc8bcc8900498fee',
  '901606b9afdd8614f54b56779211c00eb269d8c320361aaca9d58dbb71f61063',
  '077609c5d16f0096f55fc33f8b6ed4656d537ccaceaa2806dd3e3fc1f59fc7b9',
  'dcb468b36b5903e7b7f6bb41870596fce3635103e6c1f1210fbf9818fa318f4b',
  '9f1ab7d31b55fe047e276a0b617b8d78f5c6ca35a9ed1d3c6b6c1586d9ca304d',
])
for (const file of files) {
  assert.doesNotMatch(file.name, e7Files)
  assert.doesNotMatch(file.name, /^\.env(?:\.|$)|building_metrics|vt_building_risk|(?:wards|cell_scores|buildings)\.geojson|(?:ward_summary|validation_summary|export_metadata|pack_manifest|tiles_candidate)\.json|(?:ward_score_distribution|ward_rank_ranges|top_priority_ward_ranges|sensitivity_rank_range_width|weight_perturbation_rank_stability|a7_radius_pair_sensitivity|c1_metric_availability|literature_hotspot_reference_ranks)\.png|\.pmtiles$|\.parquet$|\.map$/i)
  if (!file.isFile()) continue
  const bytes = await readFile(join(file.parentPath ?? file.path, file.name))
  assert(!e7Digests.has(createHash('sha256').update(bytes).digest('hex')), `Restricted E7 asset in production output: ${file.name}`)
  if (!/\.(?:js|json|html|css)$/i.test(file.name)) continue
  const contents = bytes.toString('utf8')
  assert.doesNotMatch(contents, e7Markers)
  assert.doesNotMatch(contents, /demo-authority|building_metrics\.json|vt_building_risk\.geojson|playwright-test-only|__delhi_preview|DELHI_(?:ANALYTICS|GEOGRAPHY)_DIR|subsidence-data|delhi-c2-c3-person-c|delhi-c5-local-testing-candidate|127\.0\.0\.1:800[23]|delhi-e9-person-c|E9_TEST_AUTHORITY_TOKEN/i)
}
console.log('Production artifacts contain no local environment files or known restricted fixture or test credential markers.')
