# Web app (Person C)

React, TypeScript, Vite and MapLibre power the public ward screening workspace. Use Node 20.19+ within the Node 20 line (verified with 20.20.2), or Node 22.12+.

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

Open [http://localhost:5173](http://localhost:5173). The default public mock mode runs locally with synthetic data. The street basemap uses the network and the ward overlay can run independently. `npm run preview` serves the production build on port 4173.

## C11 local API integration

With Python 3.11 available, run these commands from the frontend repository root to set up the sibling worktree.

```powershell
git fetch origin e/api-insar:refs/remotes/origin/e/api-insar
git worktree add --detach ../subsidence_risk_map-c11-backend origin/e/api-insar
Set-Location ../subsidence_risk_map-c11-backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[api,dev,integration]'
$env:API_ENV = 'dev'
$env:API_CORS_ORIGINS = 'http://localhost:5173'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal, run `npm run dev:live` from `web/` and open [http://localhost:5173](http://localhost:5173). This mode defaults to [the loopback API](http://127.0.0.1:8000/api/v1/health). Its health indicator reports liveness. Rankings, ward details, cells, validation and ward PDFs use HTTP responses from the local process.

The backend's development artifacts contain fictional Delhi demo wards and metrics. When metadata identifies synthetic Delhi data and the ward IDs match, the map draws the checked-in synthetic boundaries without needing an archive. Actual Delhi metrics and hosted PMTiles require separate artifacts and configuration.

Run `npm run test:live` with the backend running and frontend port 5173 free. Playwright starts the frontend and checks the seven public routes, the map and PDF flow, loading and retry, and CORS with unauthenticated buildings rejection. For successful authenticated testing, have the developer inject `AUTHORITY_TOKEN` into the backend process and enter the same token privately in the Authority access dialog. The token goes in the `X-Authority-Token` header of the protected `GET /buildings` request.

The buildings request requires a bounding box. The bundled C1 building metrics lack coordinates, so the backend also needs compatible C0 geometry configured via `API_BUILDINGS_GEOMETRY_PATH` or location-enabled C1 metrics.

## Contracts and fixtures

`npm run generate:types` regenerates `types/contracts.ts` from every shared JSON schema and `types/openapi.ts` from the C4 OpenAPI document. Edit the generator if its output needs to change and regenerate the files.

Mock mode uses the C2 ward and cell summaries, C3 validation summary, and the public metadata, pagination defaults and health fields from the C4 response examples. The C5 tile fixtures are empty, so the map uses the unchanged synthetic ward boundaries from the C0 starter pack. The C4 PDF example is a placeholder filename.

## Ward screening

The map, ranking table and inspector share the selected ward ID. The map uses the C2 Inspection Index and the C5 ward attributes in live mode. The legend and ranking filters use display bands at 34 and 67 on the 0–100 index. Wards with insufficient data use a hatch pattern. The inspector shows aggregate indicators, published rank percentiles, coverage, flags and histogram counts when those fields are available. The rank range describes sensitivity to indicator weights.

## Environment

Copy `.env.example` to `.env.local` to override defaults. Set `VITE_MOCK_MODE=false` to use the public C4 API. `VITE_API_URL` must include the version prefix, which defaults to `/api/v1`. A separately hosted API must permit this frontend's origin.

### Real Delhi map handoff

Put these values in `web/.env.local` for local review or inject them at build time for a staging build. Obtain the values from the approved handoff for one release.

| Variable | Value |
| --- | --- |
| `VITE_MOCK_MODE` | `false` |
| `VITE_API_URL` | Person E’s matching C4 API base, including `/api/v1` |
| `VITE_DELHI_DATA_VINTAGE` | Exact real release value returned by `/meta` in `data_vintage` |
| `VITE_WARDS_GEOJSON_URL` | Approved Delhi 2022 GeoJSON URL with 250 named polygons or multipolygons in longitude/latitude and unique string IDs `1` through `250`. Preferred when configured. |
| `VITE_WARDS_TILE_URL` | Versioned C5 ward PMTiles URL with source layer `wards`. Required if GeoJSON is unset and used as fallback if the GeoJSON cannot be loaded. |
| `VITE_CELLS_TILE_URL` | Optional C5 cell PMTiles URL with layer `cells`. Leave blank to use the selected ward’s C4 cell endpoint, including when the delivered archive contains geometry only and a scored view is needed. |
| `VITE_POINTS_TILE_URL` | Optional approved C5 radar PMTiles URL with layer `points`. Live radar remains visible in Authority mode only. |
| `VITE_DELHI_MAP_ATTRIBUTION` | Optional plain-text ward-source credit from the delivered manifest. The app also displays the C5 contract attribution. Use the manifest’s exact source provenance. |

The API must report `city=delhi`, `n_wards=250`, and the configured vintage. Its ward list must contain all 250 canonical string IDs. A synthetic API continues to use its matching bundled ward boundaries and keeps the configured real map sources off. A loaded GeoJSON with mismatched IDs is rejected. A valid GeoJSON is coloured with the matching C4 ward metrics. Ward PMTiles use their own C5 metrics, including a score-unavailable style for unscored geometry. Cells with unknown suppression show unavailable coverage and metrics. A cell archive load failure still falls back to the selected ward’s C4 cells.

Use approved, versioned asset URLs for the same release as the API and confirm the C0/C5 manifests and tile QA at handoff. The [ward lineage](../data/LINEAGE.md) records GSDL Delhi as the source named by OpenCity, Vaidyanathan R as the credited contributor, and the Kaggle mirror as the origin of the candidate bytes. Use the credit and provenance for the actual delivered release.

GeoJSON must return the file directly with `GET` CORS when cross-origin. Tile hosts must support `GET`, `HEAD`, byte ranges with HTTP 206 and `Content-Range`, and CORS for the frontend origin. Use same-origin or HTTPS URLs in deployed builds. HTTP is allowed for loopback development. Add the API, archive, GeoJSON, and basemap origins to your hosting Content Security Policy as needed. Build with `npm run build` after changing environment values.

The interface starts in light appearance with the [OpenFreeMap Bright street style](https://openfreemap.org/quick_start/). The Layers menu can follow the UI appearance or explicitly select light or dark streets. Set `VITE_BASEMAP_STYLE_URL` to replace the light style or supply both `VITE_BASEMAP_TILE_URL` and `VITE_BASEMAP_ATTRIBUTION` for a public raster basemap. Set `VITE_BASEMAP_ENABLED=false` for boundary-only rendering.

### City perspective

At building detail zoom (14+) the map can extrude polygons from the public OpenMapTiles `building` layer using its positive `render_height` and `render_min_height` above ground in metres. The provider derives these values from available tags and levels. Its schema does not identify the origin of each height, so the scene labels the heights as potentially estimated. These public buildings provide geographic context only. They have no authority risk attributes, and their heights do not represent subsidence or terrain elevation.

The 2D/3D, compass, bearing and reset controls share the same map and ward selection. Zoom in to building detail on small screens. The map stays flat when eligible building data is unavailable, including on a raster basemap. Without WebGL, loaded ward GeoJSON remains selectable in a simple 2D plan. In live mode without renderable boundaries, rankings and their inspector remain available.

The bundled provider supplies street vector data. Satellite imagery requires a separately licensed raster source, credentials where required by that provider, and attribution. No satellite source is configured.

## Layers and authority access

- Configure `VITE_CELLS_TILE_URL` and `VITE_POINTS_TILE_URL` with versioned C5 PMTiles archives using the `cells` and `points` source layers. Live cells fall back to the selected ward's C4 cell endpoint. The C0 radar CSV and C2 scores supply synthetic demo layers. The demo publishes only synthetic radar points, while live radar and building controls are scoped to authority access. The optional dark street basemap uses the supported OpenFreeMap Dark style.
- Authority mode becomes available only after the live C4 `GET /buildings` endpoint accepts the entered authority header. The token is kept in tab memory for up to 20 minutes. Sign-out, expiry and 401/403 responses clear the session and restricted layers. The API must enforce authorisation.
- Restricted building metrics come exclusively from the authenticated C4 viewport query, limited to 500 features. The API serves these responses with `Cache-Control: no-store`. Keep building metrics and authority credentials server-side. HTTPS is required outside loopback development.
- The C4 PDF route generates **ward** briefs. The preview can print or save a clearly labelled ward and prioritised-cell summary when the route is unavailable. Building selections expose individually authorised metrics on the map and there is no building PDF endpoint in C4.

## CI handoff for Person E

Use Node 20.20.2 or a supported newer version and run these commands from `web/` in a complete checkout. Leave the build in its default mock mode for the browser tests.

```sh
npm ci --engine-strict
npx playwright install --with-deps chromium
npm run generate:types
git diff --exit-code -- types
npm run typecheck
npm run lint
npm run build
npm run verify:assets
npm test
npm audit
```

Playwright starts the mock production preview on port 4173 and a second production preview with live configuration on 4181. Authority cases intercept the frozen API in the test browser. They exercise client behaviour without granting access to a deployment. For a local installed Chrome, set `PLAYWRIGHT_CHANNEL=chrome` before running the tests. The tests and the browser benchmark use software WebGL for reproducible rendering.

## Static hosting

Publish only `web/dist/` from a clean build. The app uses a single entry URL and client-side view state. The included `public/_headers` supplies cache and security headers on compatible hosts. On other hosts, configure those headers directly. Revalidate HTML, cache hashed assets immutably and serve JavaScript workers with the correct MIME type. The host should serve the app over HTTPS and must keep `/api/v1/*` out of any HTML fallback.

Produce separate builds for mock and live previews. Set `VITE_MOCK_MODE=false` and `VITE_API_URL` at build time for live mode. If the API is on a separate origin, allow the deployed frontend origin, `GET`, `OPTIONS`, and `X-Authority-Token` in CORS. Use the real Delhi handoff settings above for the public map sources.

For a comparable startup measurement, serve two production builds on distinct ports and run `node scripts/measure-map.mjs URL_BEFORE URL_AFTER`. This measures five fresh Chrome contexts per build, with the basemap style request held for one second and then rejected, so it measures the ward-map fallback path independently of provider speed.
