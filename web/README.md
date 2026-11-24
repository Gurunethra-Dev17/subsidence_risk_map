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

## Internal Delhi candidate preview

Keep the geographical and analytical packages extracted outside the repository. In PowerShell, from `web/`:

```powershell
$packages = Join-Path $env:USERPROFILE 'Desktop/subsidence-data'
$env:DELHI_GEOGRAPHY_DIR = Join-Path $packages 'delhi-c5-local-testing-candidate-0.0.3'
$env:DELHI_ANALYTICS_DIR = Join-Path $packages 'delhi-c2-c3-person-c'
npm.cmd run dev:delhi
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Stop with Ctrl+C. With the same variables in a shell and the port free, run `npm.cmd run test:delhi`. Set `$env:PLAYWRIGHT_CHANNEL = 'msedge'` to use the installed Edge browser. The test suite starts and stops its own preview and saves restricted screenshots under `web/.npm-cache/delhi-test-results/`.

The Vite development middleware binds to IPv4 loopback, allows same-origin read requests, and loads only named resources from the two configured directories. It checks SHA-256, C0/C2 ward and grid lineage, selected run metadata, canonical ward IDs, and cell suppression before serving. It indexes the C2 citywide cells once and returns only the selected ward. The app joins C0 boundaries to C2 ward scores by ID and displays C3 figures from the local origin. The geo-package ward and cell tile candidates are geometry only. The four tile-quantization omissions remain in the C2 source and are included in their selected-ward payloads wherever a canonical ward is assigned.

The preview uses the labelled browser-print brief. Authority access and live radar require the authenticated backend. Data and figures are internal team material. Keep the preview on loopback without a tunnel. Starts with incompatible packages fail with a diagnostic and the browser exposes retry states for request failures. The normal development and production commands retain their existing mock or configured live API behavior. Production builds reject the preview mode.

## Real E9 loopback integration

Use E's backend checkpoint `3cbc30a15f9a44671a8527123c0d98bbea2973af`. Keep it in a separate detached checkout. The commands below use the existing external packages by absolute path. The backend opens these files directly, so there is no need to duplicate either Parquet export. Verify the handoff's `SHA256SUMS.txt` and `REQUIRED_EXISTING_SHA256.txt` before setup.

Run these commands from the frontend repository root to create the isolated checkout.

```powershell
git fetch origin
$frontend = (Get-Location).Path
$backend = Join-Path $env:TEMP 'subsidence-e9-3cbc30a-isolated'
git clone --shared --local --no-checkout $frontend $backend
git -C $backend checkout --detach 3cbc30a15f9a44671a8527123c0d98bbea2973af
Push-Location $backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e '.[api,integration]'
.\.venv\Scripts\python.exe -m pip check
@'
import duckdb
with duckdb.connect() as conn:
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    conn.execute("INSTALL spatial")
    conn.execute("LOAD spatial")
    print("DuckDB spatial ready")
'@ | .\.venv\Scripts\python.exe -
Pop-Location
```

You can use a verified existing Python 3.11 environment if disk space is limited. Always launch with the detached E9 checkout as the working directory so the Python API modules resolve to the exact checkpoint. In this workspace the earlier sibling checkout's `.venv\Scripts\python.exe` is a compatible alternative.

In a PowerShell terminal from the frontend root, configure and start E9. Keep the terminal open for test execution and cleanup.

```powershell
$frontend = (Get-Location).Path
$backend = Join-Path $env:TEMP 'subsidence-e9-3cbc30a-isolated'
$python = Join-Path $backend '.venv/Scripts/python.exe'
# If using the verified existing environment, set $python to its full executable path.
# $python = (Resolve-Path '..\subsidence_risk_map-c11-backend\.venv\Scripts\python.exe').Path
$packages = Join-Path $env:USERPROFILE 'Desktop/subsidence-data'
$d8 = Join-Path $packages 'delhi-c2-c3-person-c'
$e9 = Join-Path $packages 'delhi-e9-person-c'
$env:API_ENV = 'production'
$env:API_WARD_SUMMARY_PATH = Join-Path $d8 'ward_summary.json'
$env:API_CELL_SCORES_PATH = Join-Path $d8 'cell_scores.geojson'
$env:API_VALIDATION_SUMMARY_PATH = Join-Path $d8 'validation_summary.json'
$env:API_BUILDING_METRICS_PATH = Join-Path $e9 'C1/building_metrics.parquet'
$env:API_BUILDINGS_GEOMETRY_PATH = Join-Path $packages 'buildings.parquet'
$env:API_C6_CONFIG_PATH = Join-Path $e9 'reference/configs/delhi.yaml'
$env:API_CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173,https://subsidence-risk-map.vercel.app'
Remove-Item Env:API_INSAR_MANIFEST_PATH -ErrorAction SilentlyContinue
$env:AUTHORITY_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
Push-Location $backend
& $python -B -m api.preflight
if ($LASTEXITCODE) { Pop-Location; throw 'E9 preflight failed.' }
$e9Server = Start-Process -FilePath $python -WorkingDirectory $backend -ArgumentList '-B','-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8002','--no-access-log' -WindowStyle Hidden -PassThru
Pop-Location
```

Check [health](http://127.0.0.1:8002/api/v1/health) and [E9 Swagger](http://127.0.0.1:8002/api/v1/docs). The browser suite enters the temporary authority token from this process environment. For manual authority review, generate a fresh temporary value in a local password manager. Replace the token assignment in the setup above with the masked prompt below, then enter the same value in the masked Authority access form.

```powershell
$temporaryToken = Read-Host 'Temporary authority token' -AsSecureString
$env:AUTHORITY_TOKEN = [System.Net.NetworkCredential]::new('', $temporaryToken).Password
$temporaryToken.Dispose()
```

Keep the token out of Vite variables, terminal output, screenshots and browser storage.

In a separate terminal from the frontend root, serve the allowlisted B package. The server verifies the assets' SHA-256s and supports HEAD, single byte ranges, local CORS, and gzip fallbacks.

```powershell
$env:DELHI_GEOGRAPHY_DIR = Join-Path $env:USERPROFILE 'Desktop/subsidence-data/delhi-c5-local-testing-candidate-0.0.3'
python -B web/scripts/serve-e9-geography.py
```

Run the frontend from the repository root in a third terminal.

```powershell
Set-Location web
npm.cmd run dev:e9
```

Open [the real E9 app](http://127.0.0.1:5173). This development mode pins the API to port 8002 and the geographical assets to port 8003. It requires accepted Delhi metadata and canonical ward IDs before enabling the map and authority access. Ward GeoJSON is preferred. If its transport fails, the ward PMTiles use live API colours and hover values by ID. The Grid cells control requests the selected ward from C4. Candidate cell tiles provide geometry only, and the E9 session retains all C2 cells, including the four slivers outside the candidate archive. The radar control is shown in Authority mode.

For the E9 suite, stop the standalone Vite frontend with Ctrl+C and leave E9 and geography running. In the original E9 terminal:

```powershell
Set-Location (Join-Path $frontend 'web')
$env:E9_TEST_AUTHORITY_TOKEN = $env:AUTHORITY_TOKEN
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm.cmd run test:e9
Remove-Item Env:E9_TEST_AUTHORITY_TOKEN
```

The suite uses the running E9 API for ward, cell, PDF, validation and building assertions. It controls a few browser responses for failure-path checks. The Playwright Vite child receives neither token variable. Stop the geography server with Ctrl+C. In the original terminal run `Stop-Process -Id $e9Server.Id` and `Remove-Item Env:AUTHORITY_TOKEN`. Standard checks are `npm.cmd run lint`, `npm.cmd run build`, `npm.cmd run verify:assets`, and `npm.cmd test`. Use the separately documented settings for `npm.cmd run test:delhi` and `npm.cmd run test:live`.

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
| `VITE_REQUIRE_REAL_DELHI` | `true` for the approved E9 release. This blocks synthetic or incompatible API metadata and uses C4 for selected-ward cell scores. |
| `VITE_API_URL` | Person E’s matching C4 API base, including `/api/v1` |
| `VITE_DELHI_DATA_VINTAGE` | Exact real release value returned by `/meta` in `data_vintage` |
| `VITE_WARDS_GEOJSON_URL` | Approved Delhi 2022 GeoJSON URL with 250 named polygons or multipolygons in longitude/latitude and unique string IDs `1` through `250`. Preferred when configured. |
| `VITE_WARD_GEOJSON_FALLBACK_URL` | Optional base URL for approved per-ward `<ward_id>.json` geometry, used to focus a selected ward while the map uses PMTiles. |
| `VITE_WARDS_TILE_URL` | Versioned C5 ward PMTiles URL with source layer `wards`. Required if GeoJSON is unset and used as fallback if the GeoJSON cannot be loaded. |
| `VITE_CELLS_TILE_URL` | Leave blank for E9. Other live configurations can provide a validated score-enriched C5 archive with layer `cells`. |
| `VITE_POINTS_TILE_URL` | Optional C5 radar PMTiles URL with layer `points`. The control appears in Authority mode. Use an archive approved for URL disclosure because Vite includes this URL in the browser build. |
| `VITE_DELHI_MAP_ATTRIBUTION` | Optional plain-text ward-source credit from the delivered manifest. The app also displays the C5 contract attribution. Use the manifest’s exact source provenance. |

The API must report `city=delhi`, `n_wards=250`, and the configured vintage. Its ward list must contain all 250 canonical string IDs. The synthetic live mode uses its matching bundled boundaries, while strict Delhi mode requires matching real metadata before requesting ward summaries. A loaded GeoJSON with mismatched IDs is rejected. Both ward GeoJSON and ward PMTiles use the matching C4 ward metrics. Cells with unknown suppression show unavailable coverage and metrics. A configured cell archive in legacy live mode can fall back to the selected ward's C4 cells.

Use approved, versioned asset URLs for the same release as the API and confirm the C0/C5 manifests and tile QA at handoff. The [ward lineage](../data/LINEAGE.md) records GSDL Delhi as the source named by OpenCity, Vaidyanathan R as the credited contributor, and the Kaggle mirror as the origin of the candidate bytes. Use the credit and provenance for the actual delivered release.

GeoJSON must return the file directly with `GET` CORS when cross-origin. Serve the geographical package's gzip-compressed per-ward fallbacks with `Content-Type: application/geo+json` and `Content-Encoding: gzip`, even though their names end in `.json`. Tile hosts must support `GET`, `HEAD`, byte ranges with HTTP 206 and `Content-Range`, and CORS for the frontend origin. Use same-origin or HTTPS URLs in deployed builds. HTTP is allowed for loopback development. Add the API, archive, GeoJSON, and basemap origins to your hosting Content Security Policy as needed. Build with `npm run build` after changing environment values.

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

### Synthetic preview deployment

Build from the complete checkout of `Gurunethra-Dev17/subsidence_risk_map`, branch `c/frontend`, with `web/` as the working directory. The fixture plugin reads the public synthetic files in `contracts/mock/` during the build. Generated TypeScript declarations are tracked in `web/types/`. Type generation is a separate check against `contracts/schemas/`.

| Setting | Value |
| --- | --- |
| Framework preset | Vite |
| Root directory | `web` |
| Install command | `npm ci --engine-strict` |
| Build command | `npm run build && npm run verify:assets` |
| Output directory | `dist` relative to `web` |
| Build environment | `VITE_MOCK_MODE=true` |

Leave `VITE_REQUIRE_REAL_DELHI`, `VITE_API_URL`, `VITE_DELHI_DATA_VINTAGE`, `VITE_DELHI_MAP_ATTRIBUTION`, `VITE_WARDS_GEOJSON_URL`, `VITE_WARD_GEOJSON_FALLBACK_URL`, `VITE_WARDS_TILE_URL`, `VITE_CELLS_TILE_URL`, `VITE_POINTS_TILE_URL`, and basemap overrides unset. The default OpenFreeMap HTTPS basemap supplies street context and 3D heights. All ward scores and radar observations in preview mode are fictional. The PDF workflow uses its labelled print fallback.

For [Vercel Git integration](https://vercel.com/docs/git/vercel-for-github), use the `web/` project root and enable **Include source files outside of the Root Directory in the Build Step**. Set Production branch tracking to `c/frontend` for the dedicated synthetic project and use its stable project domain for CORS. `web/vercel.json` applies the existing security and cache headers and handles SPA navigation after checking static files. Keep `/api/v1/*` and missing asset paths outside the SPA fallback. Vercel selects Node.js 26.x with the current `engines.node` range. Local Node.js 20.19+ remains supported by the repository.

For [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), run the install and build locally with Node.js 20.19+ and the preview environment above. In **Workers & Pages**, select **Create application → Get started → Drag and drop your files**. Use a dedicated free project and upload only `web/dist/`. Cloudflare applies the included `_headers` and its default SPA handling. Use the stable project domain shown by the dashboard and upload future builds to the same project. This route needs a Cloudflare account with Pages deployment access and leaves GitHub disconnected. [Netlify manual deployment](https://docs.netlify.com/manage/projects/add-new-project/#deploy-local-files) can also publish the verified output and consumes its `_headers` file.

Before handing off the origin, open the assigned HTTPS domain in a signed-out browser. Confirm the synthetic label, map, Methodology and Validation views, and ward print fallback. Check the response headers for the page and a hashed asset, and confirm the browser makes no localhost, C4 API, or Delhi archive requests. Share the verified origin without a trailing slash or path for the CORS allowlist.

For a comparable startup measurement, serve two production builds on distinct ports and run `node scripts/measure-map.mjs URL_BEFORE URL_AFTER`. This measures five fresh Chrome contexts per build, with the basemap style request held for one second and then rejected, so it measures the ward-map fallback path independently of provider speed.

### Release from a verified static artifact

Public Delhi release requires explicit data-use clearance, D10/H3 acceptance, a matching final C4 API and C5 handoff, end-to-end verification, and the release owner’s approval. The Render staging API was handed off as synthetic. Keep it paired with synthetic fixtures.

From `web/`, set the approved public release values listed above and run `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run verify:assets`. For the synthetic build use `VITE_MOCK_MODE=true` and leave the Delhi settings unset. Before a real build, verify both allowed frontend origins, including `http://localhost:5173` and `https://subsidence-risk-map.vercel.app`, plus the preview origin if one is used. Request each published archive with HEAD and a byte-range GET from the frontend origin. Check CORS, exposed `Content-Range`, caching, archive layer and zoom metadata, ward and cell IDs, and suppression values against the release manifests.

After release approval, use a fresh static-only folder outside the Git checkout. The PowerShell commands below mirror the earlier successful static-artifact layout and preserve the checked-in routes and headers. Run them from `web/` after the successful build and asset check.

```powershell
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ('subsidence-vercel-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $stage
Get-ChildItem -LiteralPath dist | Where-Object Name -ne '_headers' | Copy-Item -Destination $stage -Recurse
$vercelConfig = Get-Content -LiteralPath vercel.json -Raw | ConvertFrom-Json
$vercelConfig.framework = $null
$vercelConfig.installCommand = ''
$vercelConfig.buildCommand = ''
$vercelConfig.outputDirectory = '.'
[System.IO.File]::WriteAllText((Join-Path $stage 'vercel.json'), ($vercelConfig | ConvertTo-Json -Depth 20))
vercel link --cwd $stage --project subsidence-risk-map --scope rosh-e561
vercel deploy --cwd $stage --scope rosh-e561
```

Verify the preview URL before promoting the approved deployment. Signed out, check all ward IDs and source labels, representative ranks and suppression, all views, responsive widths, map interactions and API PDF bytes. Verify asset and security headers and CORS. Confirm signed-out buildings rejection, invalid-token rejection and authorized sign-out cleanup using securely supplied credentials. Then use `vercel promote <approved-preview-url> --scope rosh-e561` and repeat the checks on the stable domain. Record the previous production deployment URL beforehand. Use `vercel rollback <previous-production-deployment-url> --scope rosh-e561` if the promoted release fails. [Vercel deploy](https://vercel.com/docs/cli/deploy) · [Vercel rollback](https://vercel.com/docs/cli/rollback)

To build the pre-E9 frontend checkpoint in a separate directory, run the following from the repository root.

```powershell
$baseline = Join-Path ([System.IO.Path]::GetTempPath()) ('subsidence-cc824c3-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $baseline
$archive = Join-Path $baseline 'baseline.zip'
git archive --format=zip --output=$archive cc824c3
Expand-Archive -LiteralPath $archive -DestinationPath $baseline
Push-Location (Join-Path $baseline 'web')
npm.cmd ci --engine-strict
npm.cmd run build
npm.cmd run verify:assets
Pop-Location
```

To restore this checkout after saving the current patch and new files, use `git restore --source=cc824c3 --worktree -- <reviewed modified files>` and move the new files to a backup folder. Run `git status --short --branch` to verify the result.
