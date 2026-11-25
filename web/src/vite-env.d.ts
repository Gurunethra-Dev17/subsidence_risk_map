interface ImportMetaEnv {
  readonly VITE_MOCK_MODE?: string
  readonly VITE_E7_INTERNAL_PREVIEW?: string
  readonly VITE_API_URL?: string
  readonly VITE_DELHI_DATA_VINTAGE?: string
  readonly VITE_DELHI_MAP_ATTRIBUTION?: string
  readonly VITE_WARDS_GEOJSON_URL?: string
  readonly VITE_WARDS_TILE_URL?: string
  readonly VITE_CELLS_TILE_URL?: string
  readonly VITE_POINTS_TILE_URL?: string
  readonly VITE_BASEMAP_TILE_URL?: string
  readonly VITE_BASEMAP_ATTRIBUTION?: string
  readonly VITE_BASEMAP_STYLE_URL?: string
  readonly VITE_BASEMAP_ENABLED?: string
}

declare module 'virtual:public-fixtures' {
  export const wards: string
  export const validation: string
  export const boundaries: string
  export const cells: string
  export const points: string
  export const examples: {
    contractVersions: import('../types/openapi').components['schemas']['MetaResponse']['contract_versions']
    limit: number
    offset: number
    health: import('../types/openapi').components['schemas']['Health']
  }
}
