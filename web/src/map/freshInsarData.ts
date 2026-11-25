import type { ImageSourceSpecification } from 'maplibre-gl'
import { fetchApi } from '../api/endpoints'
import { publicHttpUrl } from '../api/publicUrl'

const artifactRoot = 'http://127.0.0.1:8003/e7/'
const approvedDigest = '20434023bc7de664608746a99a1bfe30b213d3f95e15b7e197c4f623d352f94e'

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid E7 manifest.')
  return value as Record<string, unknown>
}

function tuple(value: unknown, length: number): number[] {
  if (!Array.isArray(value) || value.length !== length || !value.every(Number.isFinite)) {
    throw new Error('Invalid E7 numeric values.')
  }
  return value
}

function percentage(value: unknown): number {
  if (typeof value !== 'number' || !(value >= 0 && value <= 100)) throw new Error('Invalid E7 coverage.')
  return value
}

function text(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Missing E7 metadata.')
  return value
}

function acquisition(value: unknown) {
  const date = text(value)
  const parsed = new Date(date + 'T00:00:00Z')
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
    throw new Error('Invalid E7 acquisition date.')
  }
  return parsed
}

export function parseFreshManifest(value: unknown) {
  const data = record(value)
  if (data.file !== 'los_overlay.png' || data.sha256 !== approvedDigest ||
    data.crs !== 'EPSG:4326' || data.resampling !== 'nearest' || data.width !== 1359 || data.height !== 483) {
    throw new Error('Unexpected E7 overlay specification.')
  }
  const [west, south, east, north] = tuple(data.bbox_west_south_east_north, 4)
  const coordinates: ImageSourceSpecification['coordinates'] = [[west, north], [east, north], [east, south], [west, south]]
  const supplied = data.maplibre_corners_lon_lat
  if (!(west >= -180 && west < east && east <= 180 && south >= -85 && south < north && north <= 85) ||
    !Array.isArray(supplied) || supplied.length !== 4 ||
    !coordinates.every(([lon, lat], i) => {
      const corner = tuple(supplied[i], 2)
      return corner[0] === lon && corner[1] === lat
    })) {
    throw new Error('Invalid E7 map placement.')
  }
  const [lower, upper] = tuple(data.color_scale_los_cm, 2)
  const [minimum, maximum] = tuple(data.measured_los_range_cm, 2)
  const reference = acquisition(data.reference_acquisition_date)
  const secondary = acquisition(data.secondary_acquisition_date)
  const days = (secondary.getTime() - reference.getTime()) / 86_400_000
  if (!(upper > 0 && lower === -upper && minimum <= lower && maximum >= upper) ||
    days !== data.temporal_separation_days || days <= 0 || data.flight_direction !== 'ASCENDING' ||
    data.polarization !== 'VV' || data.coherence_threshold !== 0.30) {
    throw new Error('Invalid E7 observation metadata.')
  }
  const targets = record(data.target_ward_coverage)
  return {
    coordinates, width: data.width, height: data.height, digest: data.sha256,
    lower, upper, minimum, maximum, reference, secondary, days,
    polarization: data.polarization, threshold: data.coherence_threshold,
    product: text(data.product_id), attribution: text(data.attribution),
    footprint: percentage(data.nominal_footprint_overlap_pct_of_ward_union),
    usable: percentage(data.usable_pixel_intersection_area_pct_of_ward_union),
    bijwasan: percentage(targets.BIJWASAN), mahipalpur: percentage(targets.MAHIPALPUR),
  }
}

async function artifact(name: 'overlay_manifest.json' | 'los_overlay.png', type: string, signal: AbortSignal) {
  const url = publicHttpUrl(name, artifactRoot)
  const response = await fetchApi(url, { Accept: type }, [signal], 'no-store')
  if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== type) {
    throw new Error('E7 artifact unavailable.')
  }
  return response
}

export async function loadFreshInsar(signal: AbortSignal) {
  const manifest = parseFreshManifest(await (await artifact('overlay_manifest.json', 'application/json', signal)).json())
  const blob = await (await artifact('los_overlay.png', 'image/png', signal)).blob()
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  if (actual !== manifest.digest) throw new Error('E7 image integrity check failed.')
  signal.throwIfAborted()
  const image = await createImageBitmap(blob)
  if (signal.aborted || image.width !== manifest.width || image.height !== manifest.height) {
    image.close()
    throw new Error('E7 image could not be loaded.')
  }
  return { manifest, image }
}
