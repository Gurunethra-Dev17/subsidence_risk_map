import { boundaries, cells, examples, points, validation, wards } from 'virtual:public-fixtures'
import type { C2CellScoresGeoJSON, C2WardSummary, C3ValidationSummary } from '../../types/contracts'
import type { components } from '../../types/openapi'
import { DataServiceError } from './service'
import type { DataService, RadarGeometry, Ward, WardGeometry, WardQuery } from './service'

type Api = components['schemas']
const wardFixture: Pick<C2WardSummary, 'contract' | 'meta'> & { wards: Ward[] } = JSON.parse(wards)
const validationFixture: C3ValidationSummary & Api['ValidationSummary'] = JSON.parse(validation)
const cellFixture: C2CellScoresGeoJSON = JSON.parse(cells)
const wardGeometry: WardGeometry = JSON.parse(boundaries)
const sortField = { rank: 'rank', score: 'score', name: 'ward_name' } as const

function findWard(wardId: string): Ward {
  const ward = wardFixture.wards.find((ward) => ward.ward_id === wardId)
  if (!ward) throw new DataServiceError(404, 'Unknown ward_id', 'not_found')
  return ward
}

function listWards(query: WardQuery = {}): Api['WardPage'] {
  const {
    status, q, sort = 'rank', order = 'asc',
    limit = examples.limit, offset = examples.offset,
  } = query
  if (!Number.isInteger(limit) || limit < 1 || limit > 500 || !Number.isInteger(offset) || offset < 0) {
    throw new DataServiceError(400, 'Invalid ward pagination.', 'invalid_param')
  }

  const search = q?.toLowerCase() ?? ''
  const items = wardFixture.wards.filter((ward) =>
    (!status || ward.status === status) && ward.ward_name.toLowerCase().includes(search),
  )
  const field = sortField[sort]
  const direction = order === 'desc' ? -1 : 1
  items.sort((a, b) => {
    const left = a[field]
    const right = b[field]
    if (left == null) return right == null ? 0 : 1
    if (right == null) return -1
    const comparison = typeof left === 'number' && typeof right === 'number'
      ? left - right
      : String(left).localeCompare(String(right))
    return direction * comparison
  })
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
}

export const mockService: DataService = {
  async getMeta() {
    return {
      ...wardFixture.meta,
      contract_versions: examples.contractVersions,
      default_mode: 'public',
    }
  },
  async listWards(query) {
    return listWards(query)
  },
  async getWard(wardId) {
    return findWard(wardId)
  },
  async getWardCells(wardId) {
    findWard(wardId)
    return {
      type: cellFixture.type,
      features: cellFixture.features.filter((feature) => feature.properties.ward_id === wardId),
    }
  },
  async getWardBrief(wardId) {
    findWard(wardId)
    throw new DataServiceError(501, 'The mock fixture has no PDF brief.')
  },
  async getValidation() {
    return validationFixture
  },
  async getHealth() {
    return examples.health
  },
  async getMockWardGeometry() {
    return wardGeometry
  },
  async getMockCellGeometry() {
    return cellFixture
  },
  async getMockRadarGeometry(): Promise<RadarGeometry> {
    return {
      type: 'FeatureCollection',
      features: points.trim().split(/\r?\n/).slice(1).filter(Boolean).map((row) => {
        const [id, lon, lat, vlm] = row.split(',')
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [Number(lon), Number(lat)] },
          properties: { pt_id: id, vlm_mm_yr: Number(vlm) },
        }
      }),
    }
  },
}
