const localIntegration = import.meta.env.MODE === 'c11'
const internal = import.meta.env.DEV && import.meta.env.MODE === 'delhi-preview'
const mockMode = import.meta.env.VITE_MOCK_MODE?.trim().toLowerCase()

export const config = {
  internal,
  mock: !internal && (mockMode ? mockMode !== 'false' : !localIntegration),
  apiUrl: internal ? '/__delhi_preview/api' : (import.meta.env.VITE_API_URL?.trim() || (localIntegration ? 'http://127.0.0.1:8000/api/v1' : '/api/v1')).replace(/\/+$/, ''),
  delhiVintage: import.meta.env.VITE_DELHI_DATA_VINTAGE?.trim(),
  delhiAttribution: import.meta.env.VITE_DELHI_MAP_ATTRIBUTION?.trim(),
  wardGeoJson: internal ? '/__delhi_preview/wards.geojson' : import.meta.env.VITE_WARDS_GEOJSON_URL?.trim(),
  wardTiles: internal ? undefined : import.meta.env.VITE_WARDS_TILE_URL?.trim(),
  cellTiles: internal ? undefined : import.meta.env.VITE_CELLS_TILE_URL?.trim(),
  pointTiles: internal ? undefined : import.meta.env.VITE_POINTS_TILE_URL?.trim(),
  basemapTiles: import.meta.env.VITE_BASEMAP_TILE_URL?.trim(),
  basemapAttribution: import.meta.env.VITE_BASEMAP_ATTRIBUTION?.trim(),
  basemapStyle: import.meta.env.VITE_BASEMAP_STYLE_URL?.trim() || 'https://tiles.openfreemap.org/styles/bright',
  darkBasemapStyle: 'https://tiles.openfreemap.org/styles/dark',
  basemapEnabled: import.meta.env.VITE_BASEMAP_ENABLED?.trim().toLowerCase() !== 'false',
}
