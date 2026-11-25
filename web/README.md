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

## Real E9, E7 and E4 loopback integration

The approved E7/E4 backend checkpoint is `33d106b883bfc592b0ba4dd1fa66f6e3ac78113d` from `origin/e/api-insar`. It includes the E4 geographic PDF correction at `82d6602`. Keep it detached in a separate worktree and reuse the existing Python 3.11 environment.

The E7 package is the **outer** `C:\Users\Roshan\Desktop\subsidence-data\qa_corrected` directory. Verify all eight entries in `SHA256SUMS.txt`. The loopback server reads `overlay_manifest.json` and `los_overlay.png` and pins both hashes. The API reads `api_fresh_data_status.json` directly. The handoff, QA summary, figures and GeoTIFF are audit inputs. The nested extraction is redundant.

### Verify external resources and prepare the worktree

Run in the first PowerShell terminal.

```powershell
$frontend = Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map'
$packages = Join-Path $env:USERPROFILE 'Desktop/subsidence-data'
$c5 = Join-Path $packages 'delhi-c5-local-testing-candidate-0.0.3'
$d8 = Join-Path $packages 'delhi-c2-c3-person-c'
$e9 = Join-Path $packages 'delhi-e9-person-c'
$e7 = Join-Path $packages 'qa_corrected'
function Confirm-Sha256($Path, $Expected) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash
    if ($actual -ne $Expected) { throw "Checksum mismatch at ${Path}. Expected $Expected. Got $actual." }
}
function Confirm-Manifest($Root, $Manifest) {
    $rows = Get-Content -LiteralPath (Join-Path $Root $Manifest) -ErrorAction Stop
    foreach ($row in $rows) {
        $digest, $name = $row -split '\s+', 2
        Confirm-Sha256 (Join-Path $Root $name) $digest
    }
    Write-Output "$Manifest at $Root verified ($($rows.Count) entries)"
}
Confirm-Manifest $e7 'SHA256SUMS.txt'
Confirm-Manifest $c5 'SHA256SUMS.txt'
Confirm-Manifest $d8 'checksums.sha256'
Confirm-Manifest $e9 'SHA256SUMS.txt'
foreach ($row in Get-Content -LiteralPath (Join-Path $e9 'REQUIRED_EXISTING_SHA256.txt')) {
    $digest, $name = $row -split '\s+', 2
    $path = if ($name -eq 'out/delhi/buildings.parquet') { Join-Path $packages 'buildings.parquet' } else {
        Join-Path $d8 ([IO.Path]::GetFileName($name))
    }
    Confirm-Sha256 $path $digest
}
Confirm-Sha256 (Join-Path $packages 'buildings.parquet') '3BDBCFF29B8269AF5363573BD99798B278D725E0E43083A85CE35DCEB9242531'
Confirm-Sha256 (Join-Path $e7 'los_overlay.png') '20434023bc7de664608746a99a1bfe30b213d3f95e15b7e197c4f623d352f94e'

Set-Location $frontend
$checkpoint = '33d106b883bfc592b0ba4dd1fa66f6e3ac78113d'
$backend = Join-Path $env:TEMP 'subsidence-e7-33d106b-backend'
$python = Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map-c11-backend/.venv/Scripts/python.exe'
git cat-file -e "$checkpoint^{commit}"
if ($LASTEXITCODE) { git fetch origin e/api-insar }
if (!(Test-Path -LiteralPath $backend)) { git worktree add --detach $backend $checkpoint }
if ((git -C $backend rev-parse HEAD) -ne $checkpoint) { throw 'Backend checkpoint mismatch.' }
& $python -B -c 'import fastapi, uvicorn, pydantic, reportlab, duckdb, pyarrow, httpx'
if ($LASTEXITCODE) { throw 'The existing Python API environment is incomplete.' }
```

### Start the API

Continue in the first terminal. The public ward routes and the authority route read the accepted datasets in place. Keep this terminal for teardown.

```powershell
$env:API_ENV = 'production'
$env:API_WARD_SUMMARY_PATH = Join-Path $d8 'ward_summary.json'
$env:API_CELL_SCORES_PATH = Join-Path $d8 'cell_scores.geojson'
$env:API_VALIDATION_SUMMARY_PATH = Join-Path $d8 'validation_summary.json'
$env:API_BUILDING_METRICS_PATH = Join-Path $e9 'C1/building_metrics.parquet'
$env:API_BUILDINGS_GEOMETRY_PATH = Join-Path $packages 'buildings.parquet'
$env:API_C6_CONFIG_PATH = Join-Path $e9 'reference/configs/delhi.yaml'
$env:API_CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
$env:API_INSAR_MANIFEST_PATH = Join-Path $e7 'api_fresh_data_status.json'
$env:AUTHORITY_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
if (Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue) { throw 'Port 8002 is occupied.' }
Push-Location $backend
try {
    & $python -B -m api.preflight
    if ($LASTEXITCODE) { throw 'E9 preflight failed.' }
    $e9Server = Start-Process -FilePath $python -WorkingDirectory $backend -ArgumentList '-B','-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8002','--no-access-log' -WindowStyle Hidden -PassThru
} finally { Pop-Location }
```

At this checkpoint the expected preflight output is below. The `NOT_CHECKED` lines remain open validations.

```text
PREFLIGHT_OK
NOT_CHECKED:c0_c1_dataset_wide_row_integrity
NOT_CHECKED:c0_c1_id_set_equality
NOT_CHECKED:parquet_row_values_and_nullability
NOT_CHECKED:building_bbox_geometry_availability_when_c0_is_unconfigured
```

Check [health](http://127.0.0.1:8002/api/v1/health) and the [validation response](http://127.0.0.1:8002/api/v1/validation). The browser suite reads its temporary token from the test process environment. For manual authority review, generate a temporary value privately in a local password manager. Use the masked prompt below in place of the token assignment before backend startup, then enter the same value in the masked Authority access form.

```powershell
$temporaryToken = Read-Host 'Temporary authority token' -AsSecureString
$env:AUTHORITY_TOKEN = [System.Net.NetworkCredential]::new('', $temporaryToken).Password
$temporaryToken.Dispose()
```

Keep the token out of Vite variables, terminal output, screenshots, URLs and browser storage. Start the geography and frontend from separate terminals with no authority token in their environment.

### Start geography and the frontend

Run in the second PowerShell terminal. The server binds only to `127.0.0.1:8003`. C5 keeps HEAD, single byte ranges, local CORS and gzip fallbacks. E7 requires one of the two local Vite origins and supports exactly two routes.

```powershell
Set-Location (Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map')
$packages = Join-Path $env:USERPROFILE 'Desktop/subsidence-data'
$env:DELHI_GEOGRAPHY_DIR = Join-Path $packages 'delhi-c5-local-testing-candidate-0.0.3'
$env:DELHI_E7_DIR = Join-Path $packages 'qa_corrected'
$python = Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map-c11-backend/.venv/Scripts/python.exe'
& $python -B web/scripts/serve-e9-geography.py
```

Run in the third PowerShell terminal.

```powershell
Set-Location (Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map/web')
$env:VITE_E7_INTERNAL_PREVIEW = 'true'
npm.cmd run dev:e9
```

Open [the real E9 app](http://127.0.0.1:5173). Preview mode requires accepted Delhi metadata and canonical ward IDs before enabling the map and authority access. Ward GeoJSON is preferred, with ward PMTiles as a transport fallback. The Grid cells control requests the selected ward from C4 and retains the C2 slivers outside the C5 archive. Authority mode controls historical radar and building access. E7 internal access follows the separate loopback configuration.

### Run the browser suites and stop the servers

Stop manual Vite with Ctrl+C in the third terminal and leave the API and geography servers running. Run the real suite in the first terminal.

```powershell
$env:E9_TEST_AUTHORITY_TOKEN = $env:AUTHORITY_TOKEN
$env:VITE_E7_INTERNAL_PREVIEW = 'true'
$env:DELHI_ANALYTICS_DIR = $d8
$env:PLAYWRIGHT_CHANNEL = 'msedge'
Remove-Item Env:AUTHORITY_TOKEN
Push-Location (Join-Path $frontend 'web')
try { npm.cmd run test:e9 } finally {
    Pop-Location
    Remove-Item Env:E9_TEST_AUTHORITY_TOKEN, Env:VITE_E7_INTERNAL_PREVIEW -ErrorAction SilentlyContinue
}
```

The suite uses real C4 responses and original E7 assets. Tests labelled controlled substitute only the failure responses. The Vite child receives empty token variables. To verify the actual `not_run` fallback, stop the API, clear `API_INSAR_MANIFEST_PATH`, generate a new temporary token and rerun the API and real browser suite with the internal preview flag disabled.

Stop geography with Ctrl+C in the second terminal. In the first terminal stop only the API process created above.

```powershell
if ($e9Server -and !$e9Server.HasExited) { Stop-Process -Id $e9Server.Id }
Remove-Item Env:AUTHORITY_TOKEN, Env:E9_TEST_AUTHORITY_TOKEN, Env:API_INSAR_MANIFEST_PATH, Env:VITE_E7_INTERNAL_PREVIEW -ErrorAction SilentlyContinue
```

Run standard quality checks in a clean terminal without the internal preview flag. The default Playwright suite includes the API-security cases. Run the candidate and live suites sequentially because both use port 5173.

```powershell
Set-Location (Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map/web')
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd run verify:assets
npm.cmd test
$packages = Join-Path $env:USERPROFILE 'Desktop/subsidence-data'
$env:DELHI_GEOGRAPHY_DIR = Join-Path $packages 'delhi-c5-local-testing-candidate-0.0.3'
$env:DELHI_ANALYTICS_DIR = Join-Path $packages 'delhi-c2-c3-person-c'
npm.cmd run test:delhi
# Start the synthetic API on port 8000 using the C11 instructions below, then run:
npm.cmd run test:live
git diff --check
```

### Interpretation and manual review

E7 displays relative displacement along the satellite line of sight from one ascending VV interferogram spanning 4–16 November 2026. The 80 m source product was masked at exploratory coherence 0.30. The overlay is 1359 × 483 RGBA in EPSG:4326, uses nearest-neighbor rendering and keeps the approved pixel alpha. The display range is ±2.2467668056488037 cm using the 98th percentile of absolute display-grid values. The observed range on that grid is −3.9590609073638916 to +2.3064234256744385 cm. The thresholded native QA grid reaches +2.4771595001220703 cm. Endpoint colors saturate where the display scale is exceeded. The native masked values retain their range.

Negative values are away from the sensor, zero is the midpoint, and positive values are toward the sensor. Missing or masked pixels are transparent. The nominal footprint covers about 48.7% of the ward union and usable pixels intersect about 19.3%. Usable area is about 69.8% in Bijwasan (131) and 38.8% in Mahipalpur (133). QA records usable observations in 49 wards and none in 201.

The result is derived from unwrapped phase. It measures relative LOS motion and cannot establish vertical subsidence. Independent ground truth, historical pattern and sign comparisons, annualization and independent phase-reference verification are absent. Processing omitted atmospheric correction and had the water mask disabled during unwrapping. Unwrapping errors are possible and the supplied metadata leaves the relative orbit and perpendicular baseline unspecified. Ward and cell risk assessment continues to use C2. The E7 handoff records `processing_status=processed`, `fresh_data_check_status=not_run` and `api_status=processed_not_validated`.

Attribution as supplied by the package.

> ASF DAAC HyP3 2026 using hyp3_isce2 3.0.2 / ISCE 2.6.5. Contains modified Copernicus Sentinel data 2026, processed by ESA.

- Verify 250 wards, search, rank sort and filters. Select Bijwasan from the table and then from the map. Check the Inspector, rank range, indicator units and unavailable values.
- Open Layers using the keyboard. Confirm Fresh InSAR Observation starts off, enables independently of Grid cells and keeps ward outlines and the active ward visible. Check the legend, dates, coverage, attribution and transparent areas.
- Switch light and dark appearance and street styles, then 2D and 3D. Confirm selection and layer state survive style switches. Check Layers at a narrow width and verify the ward-plan fallback with WebGL disabled.
- In Validation, check the processed wording and historical robustness and literature panels. With the optional API manifest absent, verify the fresh-data check reads “not run.”
- For Bijwasan, Mahipalpur and an insufficient-data ward such as Dakshin Puri, preview and download the E4 PDF. Check the ward ID, geographic cell map, suppression legend, unavailable indicators, eligible cell rows and caveats. Simulate a PDF request failure locally and confirm Print / Save as PDF uses the labelled browser fallback.
- Confirm public mode hides historical radar and authority building controls. Enter a valid temporary token, inspect real polygons and metrics, then sign out and reload. Confirm public mode resumes and the token is absent from the URL and browser storage.
- Visit the brief and methods, then use browser back and forward. Check responsive layouts and visible loading, error and retry states.

Keep the E7 files on loopback without a tunnel or static hosting. The authority token protects the API buildings route. The static E7 permission model is the internal handoff, the local origin allowlist and the explicit preview opt-in.

## C11 local API integration

For synthetic live regression, use a separate PowerShell terminal with the detached worktree and Python environment prepared above. This API listens on port 8000.

```powershell
$backend = Join-Path $env:TEMP 'subsidence-e7-33d106b-backend'
$python = Join-Path $env:USERPROFILE 'Desktop/subsidence_risk_map-c11-backend/.venv/Scripts/python.exe'
Set-Location $backend
Remove-Item Env:API_WARD_SUMMARY_PATH, Env:API_CELL_SCORES_PATH, Env:API_VALIDATION_SUMMARY_PATH, Env:API_BUILDING_METRICS_PATH, Env:API_BUILDINGS_GEOMETRY_PATH, Env:API_C6_CONFIG_PATH, Env:API_INSAR_MANIFEST_PATH, Env:AUTHORITY_TOKEN -ErrorAction SilentlyContinue
$env:API_ENV = 'dev'
$env:API_CORS_ORIGINS = 'http://localhost:5173'
& $python -B -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal, run `npm run dev:live` from `web/` and open [http://localhost:5173](http://localhost:5173). This mode defaults to [the loopback API](http://127.0.0.1:8000/api/v1/health). Its health indicator reports liveness. Rankings, ward details, cells, validation and ward PDFs use HTTP responses from the local process.

The backend's development artifacts contain fictional Delhi demo wards and metrics. When metadata identifies synthetic Delhi data and the ward IDs match, the map draws the checked-in synthetic boundaries without needing an archive. Actual Delhi metrics and hosted PMTiles require separate artifacts and configuration.

Run `npm run test:live` with the backend running and frontend port 5173 free. Playwright starts the frontend and checks the seven public routes, the map and PDF flow, loading and retry, and CORS with unauthenticated buildings rejection. For successful authenticated testing, have the developer inject `AUTHORITY_TOKEN` into the backend process and enter the same token privately in the Authority access dialog. The token goes in the `X-Authority-Token` header of the protected `GET /buildings` request.

The buildings request requires a bounding box. The bundled C1 building metrics lack coordinates, so the backend also needs compatible C0 geometry configured via `API_BUILDINGS_GEOMETRY_PATH` or location-enabled C1 metrics.

Stop the synthetic server with Ctrl+C in its own terminal.

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

### Git-connected deployment handoff for Person A

| Setting | Value |
| --- | --- |
| GitHub repository | `Gurunethra-Dev17/subsidence_risk_map` |
| Production branch | `main` |
| Root and framework | `web`, Vite |
| Install command | `npm ci --engine-strict` |
| Build command | `npm run build && npm run verify:assets` |
| Output directory | `dist` |
| Public API | `VITE_API_URL` set to Person E’s approved HTTPS Render URL with `/api/v1` |
| Data matching | `VITE_MOCK_MODE=false`, `VITE_REQUIRE_REAL_DELHI=true`, `VITE_DELHI_DATA_VINTAGE=delhi-candidate-0.0.1` for the accepted E9 release |
| C5 geography | Approved HTTPS `VITE_WARDS_GEOJSON_URL` and `VITE_WARDS_TILE_URL`. Set `VITE_WARD_GEOJSON_FALLBACK_URL` and `VITE_DELHI_MAP_ATTRIBUTION` from the approved release. Supply `VITE_POINTS_TILE_URL` only for the approved historical radar release. Leave `VITE_CELLS_TILE_URL` blank for E9. |
| E7 configuration | Leave `VITE_E7_INTERNAL_PREVIEW` disabled. Public delivery requires confirmed redistribution terms and a separate approved HTTPS artifact-delivery design. |

Person A can connect Vercel to the private repository through their authorized GitHub installation. Before any real-data release, obtain the exact production API and C5 URLs from the dataset owners and confirm the backend checkpoint, data vintage and redistribution scope. The current Render deployment’s contents require independent confirmation. The E7 PNG is outside the frozen C4 API. Public E7 delivery depends on team approval of both redistribution and the access policy for the PNG and metadata.

Configure API CORS for the final frontend origin and the authority header. Serve the approved C5 archives with single byte Range support, valid `206` and `Content-Range`, CORS with exposed `Accept-Ranges`, `Content-Range` and `Content-Length`, and gzip `Content-Encoding` for per-ward fallbacks. Preserve data at the approved versioned paths. Keep the authority token on the API side.

- Confirm the Vercel project builds `main` from `web`, passes the asset audit and returns 404 for nonexistent artifact paths.
- Check the real Render `/health`, `/meta` and `/validation`, plus 250 ward records with the accepted vintage, rank order and C2 cell scores. Verify the PDF endpoint, including preview and download.
- Probe the deployed origin’s CORS preflight, PMTiles range response and gzip ward fallback. Check ward selection and the map on desktop and mobile, including alternate themes and the WebGL fallback.
- Verify public rejection for buildings, then test authenticated polygons and sign-out with a privately provisioned token. Confirm no artifacts or tokens are present in the production bundle.

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
