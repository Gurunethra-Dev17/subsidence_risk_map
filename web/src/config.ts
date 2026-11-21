export const config = {
  mock: import.meta.env.VITE_MOCK_MODE?.trim().toLowerCase() !== 'false',
  apiUrl: (import.meta.env.VITE_API_URL?.trim() || '/api/v1').replace(/\/+$/, ''),
  wardTiles: import.meta.env.VITE_WARDS_TILE_URL?.trim(),
  basemapTiles: import.meta.env.VITE_BASEMAP_TILE_URL?.trim(),
  basemapAttribution: import.meta.env.VITE_BASEMAP_ATTRIBUTION?.trim(),
}
