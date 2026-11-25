const localIntegration = import.meta.env.MODE === 'c11'
const internal = import.meta.env.DEV && import.meta.env.MODE === 'delhi-preview'
const e9 = import.meta.env.DEV && import.meta.env.MODE === 'delhi-e9'
const mockMode = import.meta.env.VITE_MOCK_MODE?.trim().toLowerCase()
const mock = !internal && !e9 && (mockMode ? mockMode !== 'false' : !localIntegration)
const assets = 'http://127.0.0.1:8003/delhi'

export const config = {
  internal,
  e9,
  freshInsar: e9 && import.meta.env.VITE_E7_INTERNAL_PREVIEW?.trim().toLowerCase() === 'true',
  mock,
  requireReal: e9 || (!mock && !internal && import.meta.env.VITE_REQUIRE_REAL_DELHI?.trim().toLowerCase() === 'true'),
  apiUrl: e9 ? 'http://127.0.0.1:8002/api/v1' : internal ? '/__delhi_preview/api' : (import.meta.env.VITE_API_URL?.trim() || (localIntegration ? 'http://127.0.0.1:8000/api/v1' : '/api/v1')).replace(/\/+$/, ''),
  delhiVintage: e9 ? 'delhi-candidate-0.0.1' : import.meta.env.VITE_DELHI_DATA_VINTAGE?.trim(),
  delhiAttribution: import.meta.env.VITE_DELHI_MAP_ATTRIBUTION?.trim(),
  wardGeoJson: e9 ? assets + '/wards.geojson' : internal ? '/__delhi_preview/wards.geojson' : import.meta.env.VITE_WARDS_GEOJSON_URL?.trim(),
  wardFallback: e9 ? assets + '/geojson' : import.meta.env.VITE_WARD_GEOJSON_FALLBACK_URL?.trim().replace(/\/+$/, ''),
  wardTiles: e9 ? assets + '/delhi-wards-candidate-0.0.3.pmtiles' : internal ? undefined : import.meta.env.VITE_WARDS_TILE_URL?.trim(),
  cellTiles: internal || e9 ? undefined : import.meta.env.VITE_CELLS_TILE_URL?.trim(),
  pointTiles: e9 ? assets + '/delhi-points-candidate-0.0.3.pmtiles' : internal ? undefined : import.meta.env.VITE_POINTS_TILE_URL?.trim(),
  basemapTiles: import.meta.env.VITE_BASEMAP_TILE_URL?.trim(),
  basemapAttribution: import.meta.env.VITE_BASEMAP_ATTRIBUTION?.trim(),
  basemapStyle: import.meta.env.VITE_BASEMAP_STYLE_URL?.trim() || 'https://tiles.openfreemap.org/styles/bright',
  darkBasemapStyle: 'https://tiles.openfreemap.org/styles/dark',
  basemapEnabled: import.meta.env.VITE_BASEMAP_ENABLED?.trim().toLowerCase() !== 'false',
}
