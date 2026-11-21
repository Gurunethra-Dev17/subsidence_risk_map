# FastAPI backend

The versioned API implements the frozen C4 contract in
`contracts/schemas/api.openapi.yaml`. Run commands from the repository root so
that the `api` package imports correctly and relative artifact paths resolve
from that directory.

## Dependencies and startup

Python 3.11 is supported. Install the API and developer dependencies for local
work:

```sh
python -m pip install -e '.[api,dev,integration]'
```

Production runtime needs `.[api,integration]` to provide the API server and the
PyArrow-based preflight command. The `dev` extra is only needed for tests and
linting. GIS extras such as GeoPandas and Rasterio are not required by this API
preflight.

```sh
python -m pip install -e '.[api,integration]'
```

Development startup (mock artifacts and the `demo-authority` token are enabled
only when `API_ENV=dev` is explicitly set):

```sh
# Linux/macOS
API_ENV=dev python -m uvicorn api.main:app --reload

# Windows PowerShell
$env:API_ENV = 'dev'
python -m uvicorn api.main:app --reload
```

Production startup uses the same ASGI application. Inject settings and secrets
through the deployment environment before starting Uvicorn. The authority
secret must come from a secret manager or protected environment injection; do
not put a real token in source control, an image, or a command line.

```sh
# Linux/macOS; values shown in angle brackets are deployment-provided.
export API_ENV=production
export AUTHORITY_TOKEN='<injected-secret>'
export API_WARD_SUMMARY_PATH='/mounted/artifacts/ward_summary.json'
export API_CELL_SCORES_PATH='/mounted/artifacts/cell_scores.geojson'
export API_VALIDATION_SUMMARY_PATH='/mounted/artifacts/validation_summary.json'
export API_BUILDING_METRICS_PATH='/mounted/artifacts/building_metrics.parquet'
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2

# Windows PowerShell
$env:API_ENV = 'production'
$env:AUTHORITY_TOKEN = '<injected-secret>'
$env:API_WARD_SUMMARY_PATH = 'D:\artifacts\ward_summary.json'
$env:API_CELL_SCORES_PATH = 'D:\artifacts\cell_scores.geojson'
$env:API_VALIDATION_SUMMARY_PATH = 'D:\artifacts\validation_summary.json'
$env:API_BUILDING_METRICS_PATH = 'D:\artifacts\building_metrics.parquet'
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Choose worker count based on the deployment's CPU and memory limits. Artifacts
can be mounted read-only; the API reads them but does not write them. The
process needs directory traversal and read access to configured files.

## Configuration

| Variable | Required | Behavior |
| --- | --- | --- |
| `API_ENV` | Yes for deployment preflight | `production` is the supported production value. Only explicit `dev` enables mock defaults and the development authority token fallback. |
| `AUTHORITY_TOKEN` | Yes in production | Secret for `X-Authority-Token`; must be nonempty. Inject from a secret manager. |
| `API_WARD_SUMMARY_PATH` | Yes in production | C2 ward-summary JSON. |
| `API_CELL_SCORES_PATH` | Yes in production | C2 cell-score GeoJSON FeatureCollection. |
| `API_VALIDATION_SUMMARY_PATH` | Yes in production | C3 validation-summary JSON. |
| `API_BUILDING_METRICS_PATH` | Yes in production | C1 building-metrics Parquet. |
| `API_BUILDINGS_GEOMETRY_PATH` | Optional | C0 building-geometry Parquet. Configure this when authority building responses require C0 geometries. |
| `API_CORS_ORIGINS` | Optional | Comma-separated allowed browser origins; unset means CORS is disabled. |
| `API_VERSION` | Optional | API version label; defaults to `starter`. |

## Request rate limits

The API allows 60 public data GET requests and 30 `/buildings` GET requests per
client IP in each 60-second fixed window. `/health` and `OPTIONS` requests are
exempt. Client IPs come from the ASGI connection; `X-Forwarded-For` is not
trusted by the application. The limiter has bounded in-memory state and is
intended for local or single-process staging use. Each worker has independent
counters, restarts reset them, and clients behind the same untrusted proxy may
share one address. Use a trusted proxy's rate limiter for multi-worker or
multi-instance deployments.

All artifact paths must identify readable files. In non-development mode, the
preflight rejects configured files whose resolved paths point inside
`contracts/mock`, including relative paths and symlink aliases. Production
does not silently substitute mock files when a path is absent or invalid.
Configure environment variables before starting the process: app settings and
the module-level data store capture configuration at import time.

DuckDB's spatial extension is required for geometry-backed building queries.
The API executes `LOAD spatial` for geometry-backed building queries. Depending
on DuckDB configuration, `LOAD` can automatically install a missing known
extension; that can require network access and a writable extension directory.
Production deployments should provision the extension ahead of time and
consider disabling DuckDB's `autoinstall_known_extensions` option for API
connections after provisioning. This application does not currently enforce
that option. Verify extension loading in the final runtime environment.

The deployment preflight does not import DuckDB or install/load the spatial
extension. A successful metadata-only preflight therefore does not verify that
the spatial extension is available or can load at runtime.

## Deployment preflight

After setting production variables, run from the repository root:

```sh
python -m api.preflight
```

The command exits `0` and prints `PREFLIGHT_OK` when mandatory checks pass. It
exits `1` and prints `PREFLIGHT_FAILED` plus safe diagnostic codes otherwise.
It never prints configured paths, token values, SQL, building IDs, or artifact
records. A successful preflight also lists checks it did not perform.

The preflight verifies production mode, authority-secret presence, required
artifact configuration/readability, mock-path exclusion, C2 ward and cell
schemas, C3 schema, selected C6 configuration consistency, and C1 Parquet
schema/file declarations. If configured, C0 Parquet schema and GeoParquet CRS
metadata are inspected as well. Parquet checks read footer/schema metadata;
they do not iterate row groups or load columns.

`API_BUILDINGS_GEOMETRY_PATH` is optional by contract. If it is omitted, the
preflight does not establish that C1 provides coordinate extension columns
needed for bbox filtering. Configure C0 geometry when production building
queries require polygon-backed spatial filtering.

`GET /api/v1/health` is a **liveness** check only. It can return HTTP 200 when
artifacts are unavailable. Run the deployment preflight as a separate release
gate to check data readiness; do not treat the health response as proof that
data routes are ready.

The preflight does not establish dataset-wide C0/C1 ID-set equality, duplicate
absence, row-value validity, or `sparse` nullability. The separate
`api.integration_validation.validate_building_artifacts` operation scans the
complete supplied C0/C1 artifacts. It can use substantial time, memory, and
temporary disk depending on dataset size. Run it only as a separately planned
and explicitly authorized integration-validation operation; it is not called
by API requests, startup, or the deployment preflight. Do not run it against
production data without the appropriate authorization and resource planning.
