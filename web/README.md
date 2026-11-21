# Web app (Person C)

React, TypeScript, Vite and MapLibre form the C1 dashboard foundation. Use Node 20.19+ within the Node 20 line (verified with 20.20.2), or Node 22.12+.

The npm override keeps MapLibre's transitive JSON linter on the Node 20-compatible 2.0.2 release.

From `web/`:

```sh
npm ci
npm run generate:types
npm run typecheck
npm run lint
npm run build
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The default public mock mode runs locally with synthetic data. `npm run preview` serves the production build on port 4173.

## Contracts and fixtures

`npm run generate:types` regenerates `types/contracts.ts` from every shared JSON schema and `types/openapi.ts` from the C4 OpenAPI document. Edit the generator if its output needs to change and regenerate the files.

Mock mode uses the C2 ward and cell summaries, C3 validation summary, and the public metadata, pagination defaults and health fields from the C4 response examples. The C5 tile fixtures are empty, so the map uses the unchanged synthetic ward boundaries from the C0 starter pack. The C4 PDF example is a placeholder filename.

## Environment

Copy `.env.example` to `.env.local` to override defaults. Set `VITE_MOCK_MODE=false` to use the public C4 API. `VITE_API_URL` must include the version prefix, which defaults to `/api/v1`. A separately hosted API must permit this frontend's origin.

`VITE_WARDS_TILE_URL` accepts a public C5 PMTiles archive in live mode. The tile host must support HTTP Range requests and cross-origin access if served separately. `VITE_BASEMAP_TILE_URL` and `VITE_BASEMAP_ATTRIBUTION` can optionally supply a public raster basemap in either mode. Treat every `VITE_*` value as public and keep credentials server-side.
