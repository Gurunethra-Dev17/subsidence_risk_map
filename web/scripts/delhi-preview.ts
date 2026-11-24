import { createHash } from 'node:crypto'
import { readFile, realpath } from 'node:fs/promises'
import { isAbsolute, relative, resolve } from 'node:path'
import { isDeepStrictEqual } from 'node:util'
import type { ServerResponse } from 'node:http'
import type { Plugin } from 'vite'
import type { C2CellScoresGeoJSON, C2WardSummary } from '../types/contracts'
import type { components } from '../types/openapi'
import type { WardGeometry } from '../src/api/service'
import { hasDelhiWardIds } from '../src/api/delhiMap'

const prefix = '/__delhi_preview'
const host = '127.0.0.1'
const isFigure = (file: string) => /^figures\/[a-z0-9_]+\.png$/.test(file)

function send(response: ServerResponse, status: number, body: unknown, type = 'application/json') {
  response.writeHead(status, {
    'Content-Type': type,
    'Cache-Control': 'no-store',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'X-Content-Type-Options': 'nosniff',
  })
  response.end(Buffer.isBuffer(body) ? body : JSON.stringify(body))
}

function failure(response: ServerResponse, status: number, message: string) {
  const code = status === 401 ? 'authority_required' : status === 404 ? 'not_found'
    : status < 500 ? 'invalid_param' : 'internal'
  send(response, status, { error: { code, message, details: {} } })
}

async function packageReader(directory: string | undefined, checksums: string) {
  if (!directory || !isAbsolute(directory)) throw new Error('Set both DELHI preview package directories to absolute paths.')
  const root = await realpath(directory)
  async function read(file: string) {
    const path = await realpath(resolve(root, file))
    const within = relative(root, path)
    if (!within || isAbsolute(within) || within.startsWith('..')) throw new Error('Package file escapes its configured directory.')
    return readFile(path)
  }
  const hashes = new Map((await read(checksums)).toString('utf8').trim().split(/\r?\n/).map((line) => {
    const match = /^([a-f0-9]{64})\s+(.+)$/.exec(line)
    if (!match) throw new Error('Invalid package checksum manifest.')
    return [match[2], match[1]]
  }))
  async function verified(file: string) {
    const bytes = await read(file)
    if (createHash('sha256').update(bytes).digest('hex') !== hashes.get(file)) {
      throw new Error(`Checksum mismatch for ${file}.`)
    }
    return bytes
  }
  return {
    verified,
    hash: (file: string) => hashes.get(file),
    json: async <T>(file: string): Promise<T> => JSON.parse((await verified(file)).toString('utf8').replace(/^\uFEFF/, '')),
  }
}

type ExportMetadata = {
  city: string
  contract_versions: Record<string, string>
  data_vintages: {
    c0_pack_version: string
    c1_engine_version: string
    c1_seed: number
    complete_params: Record<string, unknown>
    configured_weights: Record<string, number>
  }
  input_artifacts: { path: string; sha256: string }[]
}

type PackManifest = {
  city: string
  pack_version: string
  crs_storage: string
  files: { name: string; sha256: string }[]
}

async function loadPreview() {
  const [analytical, geographical] = await Promise.all([
    packageReader(process.env.DELHI_ANALYTICS_DIR, 'checksums.sha256'),
    packageReader(process.env.DELHI_GEOGRAPHY_DIR, 'SHA256SUMS.txt'),
  ])
  const [summary, cells, validation, metadata, boundaries, manifest] = await Promise.all([
    analytical.json<C2WardSummary>('ward_summary.json'),
    analytical.json<C2CellScoresGeoJSON>('cell_scores.geojson'),
    analytical.json<components['schemas']['ValidationSummary']>('validation_summary.json'),
    analytical.json<ExportMetadata>('export_metadata.json'),
    geographical.json<WardGeometry>('c0/wards.geojson'),
    geographical.json<PackManifest>('c0/PACK_MANIFEST.json'),
  ])
  const { meta, wards } = summary
  const version = metadata.data_vintages
  const c0Hash = (name: string) => manifest.files.find((file) => file.name === name)?.sha256
  const analyticalHash = (name: string) => metadata.input_artifacts.find((file) => file.path === `out/delhi/${name}`)?.sha256
  if (metadata.city !== 'delhi' || manifest.city !== 'delhi' || meta.city !== 'delhi' ||
    manifest.crs_storage !== 'EPSG:4326' || meta.data_vintage !== manifest.pack_version ||
    meta.data_vintage !== version.c0_pack_version || meta.engine_version !== version.c1_engine_version ||
    !isDeepStrictEqual(meta.params, version.complete_params) || !isDeepStrictEqual(meta.weights, version.configured_weights) ||
    !c0Hash('grid_250m.geojson') || c0Hash('grid_250m.geojson') !== analyticalHash('grid_250m.geojson') ||
    c0Hash('wards.geojson') !== analyticalHash('wards.geojson') || c0Hash('wards.geojson') !== geographical.hash('c0/wards.geojson') ||
    summary.contract !== 'C2@1.0' || validation.contract !== 'C3@1.0' || meta.generated_utc !== validation.generated_utc) {
    throw new Error('Dataset mismatch. C0, C2 and C3 must share compatible vintages, lineage and run metadata.')
  }
  const byId = new Map(wards.map((ward) => [ward.ward_id, ward]))
  if (boundaries.type !== 'FeatureCollection' || meta.n_wards !== wards.length ||
    !hasDelhiWardIds(wards.map((ward) => ward.ward_id)) ||
    !hasDelhiWardIds(boundaries.features.map((feature) => feature.properties.ward_id))) {
    throw new Error('Dataset mismatch. The ward boundaries and scores must contain the same 250 Delhi ward IDs.')
  }
  const byWard = new Map<string, C2CellScoresGeoJSON['features']>()
  const cellIds = new Set<string>()
  const minimum = version.complete_params.cell_min_buildings
  for (const { geometry, properties, type } of cells.features) {
    const { ward_id, cell_id, n_buildings, suppressed, cell_score, cell_rank_in_ward,
      vlm_median_mm_yr, beta_p90_horizon, share_sinking_gt4 } = properties
    if (cellIds.has(cell_id) || (ward_id !== null && !byId.has(ward_id)) ||
      typeof minimum !== 'number' || suppressed !== (n_buildings < minimum) ||
      (suppressed && [cell_score, cell_rank_in_ward, vlm_median_mm_yr, beta_p90_horizon, share_sinking_gt4].some((value) => value !== null))) {
      throw new Error('Cell identity or suppression is inconsistent with the supplied contracts.')
    }
    cellIds.add(cell_id)
    if (ward_id === null) continue
    const subset = byWard.get(ward_id) ?? []
    subset.push({ type, geometry, properties: { ward_id, cell_id, n_buildings, suppressed, cell_score,
      cell_rank_in_ward, vlm_median_mm_yr, beta_p90_horizon, share_sinking_gt4 } })
    byWard.set(ward_id, subset)
  }
  const figures = new Map<string, Buffer>(await Promise.all(validation.figures.map(async (figure) => {
    if (typeof figure.path !== 'string' || !isFigure(figure.path)) throw new Error('Unexpected validation figure path.')
    return [figure.path, await analytical.verified(figure.path)] as const
  })))
  return {
    boundaries, figures, validation, byId, byWard, wards,
    meta: { ...meta, params: { ...meta.params, seed: version.c1_seed }, contract_versions: metadata.contract_versions, default_mode: 'public' },
  }
}

export function delhiPreview(): Plugin {
  return {
    name: 'delhi-internal-preview',
    apply: 'serve',
    async configureServer(server) {
      if (server.config.server.host !== host || !server.httpServer) {
        throw new Error('The Delhi preview requires a loopback-only Vite server on 127.0.0.1.')
      }
      const data = await loadPreview().catch((error: unknown) => {
        if (error && typeof error === 'object' && 'code' in error) {
          throw new Error('A required Delhi package file could not be read. Check the configured directories and file permissions.')
        }
        if (error instanceof SyntaxError) throw new Error('A Delhi package contains invalid JSON.')
        throw error
      })
      server.middlewares.use(prefix, (req, res) => {
        const address = server.httpServer?.address()
        const authority = typeof address === 'object' && address?.address === host ? `${host}:${address.port}` : undefined
        if (!authority || req.socket.remoteAddress !== host || req.headers.host !== authority ||
          (req.headers.origin && req.headers.origin !== `http://${authority}`) ||
          (req.headers['sec-fetch-site'] && req.headers['sec-fetch-site'] !== 'same-origin')) {
          return failure(res, 403, 'Delhi preview requests require this loopback origin.')
        }
        if (req.method !== 'GET') return failure(res, 405, 'Only GET requests are supported.')
        const { pathname, searchParams } = new URL(req.url ?? '/', `http://${authority}`)
        if (pathname === '/api/health') return send(res, 200, { status: 'ok', version: 'local-export-adapter' })
        if (pathname === '/api/meta') return send(res, 200, data.meta)
        if (pathname === '/api/validation') return send(res, 200, data.validation)
        if (pathname === '/wards.geojson') return send(res, 200, data.boundaries, 'application/geo+json')
        if (pathname === '/api/buildings') return failure(res, 401, 'Authority access requires the final authenticated backend.')
        const figure = data.figures.get(pathname.slice(1))
        if (figure) return send(res, 200, figure, 'image/png')
        if (pathname === '/api/wards') {
          const limit = Number(searchParams.get('limit') ?? 50)
          const offset = Number(searchParams.get('offset') ?? 0)
          const sort = searchParams.get('sort') ?? 'rank'
          const order = searchParams.get('order') ?? 'asc'
          const status = searchParams.get('status')
          if (!Number.isInteger(limit) || limit < 1 || limit > 500 || !Number.isInteger(offset) || offset < 0 ||
            !['rank', 'score', 'name'].includes(sort) || !['asc', 'desc'].includes(order) ||
            (status && !['ranked', 'insufficient_data'].includes(status))) return failure(res, 400, 'Invalid ward query.')
          const search = searchParams.get('q')?.toLowerCase() ?? ''
          const field = sort === 'name' ? 'ward_name' : sort === 'score' ? 'score' : 'rank'
          const items = data.wards.filter((ward) => (!status || ward.status === status) && ward.ward_name.toLowerCase().includes(search))
          items.sort((a, b) => {
            const left = a[field], right = b[field]
            if (left == null) return right == null ? 0 : 1
            if (right == null) return -1
            const difference = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right))
            return order === 'desc' ? -difference : difference
          })
          return send(res, 200, { items: items.slice(offset, offset + limit), total: items.length, limit, offset })
        }
        const wardRoute = /^\/api\/wards\/([1-9]\d{0,2})(?:\/(cells|brief\.pdf))?$/.exec(pathname)
        const ward = wardRoute && data.byId.get(wardRoute[1])
        if (!ward) return failure(res, 404, 'Resource unavailable.')
        if (wardRoute[2] === 'brief.pdf') return failure(res, 501, 'Backend PDF is unavailable in the internal preview.')
        if (wardRoute[2] === 'cells') {
          return send(res, 200, { type: 'FeatureCollection', features: data.byWard.get(ward.ward_id) ?? [] }, 'application/geo+json')
        }
        return send(res, 200, ward)
      })
    },
  }
}
