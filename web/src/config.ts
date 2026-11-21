export const config = {
  mock: import.meta.env.VITE_MOCK_MODE?.trim().toLowerCase() !== 'false',
  apiUrl: (import.meta.env.VITE_API_URL?.trim() || '/api/v1').replace(/\/+$/, ''),
  wardTiles: import.meta.env.VITE_WARDS_TILE_URL?.trim(),
  cellTiles: import.meta.env.VITE_CELLS_TILE_URL?.trim(),
  pointTiles: import.meta.env.VITE_POINTS_TILE_URL?.trim(),
  basemapTiles: import.meta.env.VITE_BASEMAP_TILE_URL?.trim(),
  basemapAttribution: import.meta.env.VITE_BASEMAP_ATTRIBUTION?.trim(),
  basemapStyle: import.meta.env.VITE_BASEMAP_STYLE_URL?.trim() || 'https://tiles.openfreemap.org/styles/bright',
  darkBasemapStyle: 'https://tiles.openfreemap.org/styles/dark',
  basemapEnabled: import.meta.env.VITE_BASEMAP_ENABLED?.trim().toLowerCase() !== 'false',
}
