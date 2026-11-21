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

## Contracts and fixtures

`npm run generate:types` regenerates `types/contracts.ts` from every shared JSON schema and `types/openapi.ts` from the C4 OpenAPI document. Edit the generator if its output needs to change and regenerate the files.

Mock mode uses the C2 ward and cell summaries, C3 validation summary, and the public metadata, pagination defaults and health fields from the C4 response examples. The C5 tile fixtures are empty, so the map uses the unchanged synthetic ward boundaries from the C0 starter pack. The C4 PDF example is a placeholder filename.

## Ward screening

The map, ranking table and inspector share the selected ward ID. The map uses the C2 Inspection Index and the C5 ward attributes in live mode. The legend and ranking filters use display bands at 34 and 67 on the 0–100 index. Wards with insufficient data use a hatch pattern. The inspector shows aggregate indicators, published rank percentiles, coverage, flags and histogram counts when those fields are available. The rank range describes sensitivity to indicator weights.

## Environment

Copy `.env.example` to `.env.local` to override defaults. Set `VITE_MOCK_MODE=false` to use the public C4 API. `VITE_API_URL` must include the version prefix, which defaults to `/api/v1`. A separately hosted API must permit this frontend's origin.

`VITE_WARDS_TILE_URL` accepts a public C5 PMTiles archive in live mode. The tile host must support HTTP Range requests and cross-origin access if served separately. Live camera focusing uses the geometry available from the archive's loaded ward tiles.

The default map uses the [OpenFreeMap Dark street style](https://openfreemap.org/quick_start/) with provider attribution. The Layers menu offers a street alternative. Set `VITE_BASEMAP_STYLE_URL` for that alternative or supply both `VITE_BASEMAP_TILE_URL` and `VITE_BASEMAP_ATTRIBUTION` for a public raster basemap. Set `VITE_BASEMAP_ENABLED=false` for boundary-only rendering. The basemap provider is optional for inspecting local fixtures.

## Layers and authority access

- Configure `VITE_CELLS_TILE_URL` and `VITE_POINTS_TILE_URL` with versioned C5 PMTiles archives using the `cells` and `points` source layers. Live cells fall back to the selected ward's C4 cell endpoint. The C0 radar CSV and C2 scores supply synthetic demo layers. The demo publishes only synthetic radar points, while live radar and building controls are scoped to authority access. The optional dark street basemap uses the supported OpenFreeMap Dark style.
- Authority mode becomes available only after the live C4 `GET /buildings` endpoint accepts the entered authority header. The token is kept in tab memory for up to 20 minutes. Sign-out, expiry and 401/403 responses clear the session and restricted layers. The API must enforce authorisation.
- The default building source is the authenticated viewport query, limited to 500 features. A separately deployed protected `buildings` PMTiles archive may be entered at runtime on the API origin. That deployment must authorise each range request with the same header and return HTTP 206 with `Cache-Control: no-store`. Never configure a static public building archive. HTTPS is required outside loopback development.
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

Produce separate builds for mock and live previews. Set `VITE_MOCK_MODE=false` and `VITE_API_URL` at build time for live mode. If the API is on a separate origin, allow the deployed frontend origin, `GET`, `OPTIONS`, and `X-Authority-Token` in CORS. Use the same API origin for any optional protected building archive. The archive and the API must validate every authenticated request, return `no-store` for restricted data, and support correct partial content for PMTiles. Public archive hosts must permit the frontend origin and Range requests. Production environment URLs must use HTTPS, with HTTP allowed for loopback development. Deployment-defined API origins and basemap providers must be added when a host applies a restrictive Content Security Policy.

For a comparable startup measurement, serve two production builds on distinct ports and run `node scripts/measure-map.mjs URL_BEFORE URL_AFTER`. This measures five fresh Chrome contexts per build, with the basemap style request held for one second and then rejected, so it measures the ward-map fallback path independently of provider speed.
