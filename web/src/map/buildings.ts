import type { ExpressionSpecification, FillExtrusionLayerSpecification, StyleSpecification } from 'maplibre-gl'

export const buildingLayerId = 'public-city-buildings-3d'
export const buildingZoom = 14

const roof = ['number', ['get', 'render_height'], 0] satisfies ExpressionSpecification
const base = ['min', roof, ['max', 0, ['number', ['get', 'render_min_height'], 0]]] satisfies ExpressionSpecification

export function publicBuildingLayer(style: StyleSpecification, theme: 'street' | 'dark'): FillExtrusionLayerSpecification | null {
  const footprints = style.layers.find((layer) =>
    'source-layer' in layer && layer['source-layer'] === 'building' &&
    'source' in layer && style.sources[layer.source]?.type === 'vector',
  )
  if (!footprints || !('source' in footprints)) return null

  return {
    id: buildingLayerId,
    type: 'fill-extrusion',
    source: footprints.source,
    'source-layer': 'building',
    minzoom: buildingZoom,
    filter: ['all', ['>', roof, 0], ['<', base, roof], ['!=', ['get', 'hide_3d'], true]],
    layout: { visibility: 'none' },
    paint: {
      'fill-extrusion-height': roof,
      'fill-extrusion-base': base,
      'fill-extrusion-opacity': 0.56,
      'fill-extrusion-color': theme === 'street' ? '#9baeb8' : '#6a879d',
      'fill-extrusion-vertical-gradient': true,
    },
  }
}
