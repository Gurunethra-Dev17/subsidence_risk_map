import type { StyleSpecification } from 'maplibre-gl'
import { config } from '../config'
import { publicHttpUrl } from '../api/publicUrl'

const plainAttribution = (text: string) => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')

export type BasemapStatus = 'loading' | 'available' | 'fallback' | 'degraded' | 'disabled'

const background = {
  id: 'workspace-background',
  type: 'background',
  paint: { 'background-color': '#e9edf0' },
} satisfies StyleSpecification['layers'][number]

export function neutralBasemap(theme: 'street' | 'dark'): StyleSpecification {
  return { version: 8, sources: {}, layers: [
    { ...background, paint: { 'background-color': theme === 'dark' ? '#142438' : '#e9edf0' } },
  ] }
}

export async function loadBasemap(signal: AbortSignal, theme: 'street' | 'dark' = 'street'): Promise<{
  style: StyleSpecification
  status: Exclude<BasemapStatus, 'loading' | 'degraded'>
}> {
  const plain = neutralBasemap(theme)
  if (!config.basemapEnabled) return { style: plain, status: 'disabled' }

  if (theme === 'street' && config.basemapTiles && config.basemapAttribution) {
    return {
      style: {
        ...plain,
        sources: {
          streets: {
            type: 'raster',
            tiles: [config.basemapTiles],
            tileSize: 256,
            attribution: plainAttribution(config.basemapAttribution),
          },
        },
        layers: [background, {
          id: 'street-basemap', type: 'raster', source: 'streets',
          paint: { 'raster-saturation': -0.75 },
        }],
      },
      status: 'available',
    }
  }

  try {
    const styleUrl = theme === 'dark' ? config.darkBasemapStyle : config.basemapStyle
    const response = await fetch(publicHttpUrl(styleUrl, location.href), {
      signal: AbortSignal.any([signal, AbortSignal.timeout(4500)]),
      credentials: 'omit',
    })
    if (!response.ok) return { style: plain, status: 'fallback' }
    const remote: StyleSpecification = await response.json()
    if (remote.version !== 8 || !remote.sources || !Array.isArray(remote.layers)) {
      return { style: plain, status: 'fallback' }
    }
    // MapLibre receives a style object. Resolve relative references against the provider URL first.
    const absolute = (url: string) => {
      const base = response.url || new URL(styleUrl, location.href).href
      // Preserve MapLibre placeholders in tile, glyph and sprite templates.
      return publicHttpUrl(url, base).href.replace(/%7B/gi, '{').replace(/%7D/gi, '}')
    }
    for (const source of Object.values(remote.sources)) {
      if ('url' in source && source.url) source.url = absolute(source.url)
      if ('tiles' in source && source.tiles) source.tiles = source.tiles.map(absolute)
      if (source.type === 'geojson' && typeof source.data === 'string') source.data = absolute(source.data)
    }
    if (remote.glyphs) remote.glyphs = absolute(remote.glyphs)
    if (typeof remote.sprite === 'string') remote.sprite = absolute(remote.sprite)
    else if (remote.sprite) {
      remote.sprite = remote.sprite.map((item) => ({ ...item, url: absolute(item.url) }))
    }
    if (theme === 'dark') {
      for (const layer of remote.layers) {
        // Keep land-use colour when the provider's decorative woodland sprite is missing.
        if (layer.type === 'fill' && layer.paint?.['fill-pattern'] === 'wood-pattern') {
          delete layer.paint['fill-pattern']
        }
        if (layer.type === 'symbol' && layer.layout?.['text-field']) {
          layer.paint = { ...layer.paint, 'text-color': '#cee0ef', 'text-halo-color': '#17283b', 'text-halo-width': 1.2 }
        }
      }
    }
    return { style: { ...remote, layers: [background, ...remote.layers] }, status: 'available' }
  } catch {
    return { style: plain, status: 'fallback' }
  }
}
