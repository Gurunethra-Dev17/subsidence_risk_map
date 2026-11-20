"""FastAPI application scaffold for the C4 REST API."""

from __future__ import annotations

import os
from dataclasses import dataclass

from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.data import data_store, json_etag
from api.brief import generate_brief_pdf
from api.models import (
    CellFeatureCollection,
    ErrorEnvelope,
    HealthResponse,
    ValidationSummary,
    Ward,
    WardPage,
)


@dataclass(frozen=True)
class Settings:
    """Runtime settings read from environment variables."""

    api_env: str = os.getenv("API_ENV", "dev")
    api_version: str = os.getenv("API_VERSION", "starter")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("API_CORS_ORIGINS", "").split(",")
        if origin.strip()
    )


settings = Settings()
API_PREFIX = "/api/v1"

app = FastAPI(
    title="Subsidence Risk Map API",
    summary="Versioned API for the Subsidence Risk Map project.",
    description=(
        "C4 REST API for satellite-based ground movement monitoring and "
        "inspection prioritisation."
    ),
    version=settings.api_version,
    openapi_url=f"{API_PREFIX}/openapi.json",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    envelope = ErrorEnvelope(
        error={"code": code, "message": message, "details": {}}
    )
    body = envelope.model_dump()
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"ETag": json_etag(body)},
    )


def json_response(
    body: dict,
    *,
    cache_control: str | None = None,
    media_type: str = "application/json",
) -> JSONResponse:
    """Return a JSON response with the C4 entity tag and optional cache policy."""
    headers = {"ETag": json_etag(body)}
    if cache_control is not None:
        headers["Cache-Control"] = cache_control
    return JSONResponse(content=body, headers=headers, media_type=media_type)


def _error_responses(*status_codes: int) -> dict[int, dict]:
    descriptions = {
        400: "A query parameter is invalid.",
        404: "The requested ward does not exist.",
        429: "Too many requests.",
        500: "An unexpected failure occurred.",
    }
    return {
        status_code: {
            "model": ErrorEnvelope,
            "description": descriptions[status_code],
            "headers": {"ETag": {"schema": {"type": "string"}}},
        }
        for status_code in status_codes
    }


def _success_headers(*, ward_cache: bool = False) -> dict[str, dict]:
    headers = {"ETag": {"schema": {"type": "string"}}}
    if ward_cache:
        headers["Cache-Control"] = {
            "schema": {"type": "string", "const": WARD_CACHE_CONTROL}
        }
    return headers


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    del request
    if exc.status_code == 404:
        return error_response(404, "not_found", str(exc.detail))
    if exc.status_code == 400:
        return error_response(400, "invalid_param", str(exc.detail))
    if exc.status_code == 401:
        return error_response(401, "authority_required", str(exc.detail))
    if exc.status_code == 429:
        return error_response(429, "rate_limited", str(exc.detail))
    return error_response(exc.status_code, "internal", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    return error_response(400, "invalid_param", "Invalid request parameters")


@app.exception_handler(Exception)
async def unexpected_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    del request, exc
    return error_response(500, "internal", "Unexpected failure")


@app.get(
    f"{API_PREFIX}/health",
    tags=["health"],
    response_model=HealthResponse,
    responses={
        200: {"headers": _success_headers()},
        **_error_responses(429, 500),
    },
)
async def health() -> JSONResponse:
    """Return liveness status and the running API version tag."""
    return json_response({"status": "ok", "version": settings.api_version})


WARD_CACHE_CONTROL = "public, max-age=300"


@app.get(
    f"{API_PREFIX}/wards",
    tags=["wards"],
    response_class=JSONResponse,
    response_model=WardPage,
    responses={
        200: {"headers": _success_headers(ward_cache=True)},
        **_error_responses(400, 429, 500),
    },
)
async def list_wards(
    status: Literal["ranked", "insufficient_data"] | None = None,
    sort: Literal["rank", "score", "name"] = "rank",
    order: Literal["asc", "desc"] = "asc",
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """List, filter, sort, and paginate C2 ward summaries."""
    result = data_store.list_wards(
        status=status,
        sort=sort,
        order=order,
        q=q,
        limit=limit,
        offset=offset,
    )
    return json_response(result, cache_control=WARD_CACHE_CONTROL)


@app.get(
    f"{API_PREFIX}/wards/{{ward_id}}",
    tags=["wards"],
    response_class=JSONResponse,
    response_model=Ward,
    responses={
        200: {"headers": _success_headers(ward_cache=True)},
        **_error_responses(404, 429, 500),
    },
)
async def get_ward(ward_id: str) -> JSONResponse:
    """Return one C2 ward summary."""
    ward = data_store.get_ward(ward_id)
    if ward is None:
        raise HTTPException(status_code=404, detail="Unknown ward_id")
    return json_response(ward, cache_control=WARD_CACHE_CONTROL)


@app.get(
    f"{API_PREFIX}/wards/{{ward_id}}/cells",
    tags=["wards"],
    response_class=JSONResponse,
    response_model=CellFeatureCollection,
    responses={
        200: {
            "headers": _success_headers(ward_cache=True),
            "content": {
                "application/geo+json": {
                    "schema": {"$ref": "#/components/schemas/CellFeatureCollection"}
                }
            },
        },
        **_error_responses(404, 429, 500),
    },
)
async def get_ward_cells(ward_id: str) -> JSONResponse:
    """Return C2 cells for a known ward, retaining suppression nulls."""
    if data_store.get_ward(ward_id) is None:
        raise HTTPException(status_code=404, detail="Unknown ward_id")
    cells = data_store.get_cells(ward_id)
    return json_response(
        cells,
        cache_control=WARD_CACHE_CONTROL,
        media_type="application/geo+json",
    )


@app.get(
    f"{API_PREFIX}/wards/{{ward_id}}/brief.pdf",
    tags=["wards"],
    response_class=Response,
    responses={
        200: {
            "description": "One-page ward inspection brief PDF",
            "headers": {
                "Cache-Control": {
                    "schema": {"type": "string", "const": "no-store"}
                }
            },
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        },
        **_error_responses(404, 429, 500),
    },
)
async def get_ward_brief(ward_id: str) -> Response:
    """Return a public, ward-level PDF brief without persistent output files."""
    ward = data_store.get_ward(ward_id)
    if ward is None:
        raise HTTPException(status_code=404, detail="Unknown ward_id")
    cells = data_store.get_cells(ward_id)
    c2_meta = data_store.load_ward_summary().get("meta", {})
    pdf = generate_brief_pdf(ward, cells, c2_meta)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


@app.get(
    f"{API_PREFIX}/validation",
    tags=["validation"],
    response_class=JSONResponse,
    response_model=ValidationSummary,
    responses={
        200: {"headers": _success_headers()},
        **_error_responses(429, 500),
    },
)
async def get_validation() -> JSONResponse:
    """Return the configured C3 validation summary."""
    return json_response(data_store.load_validation_summary())


def _c4_openapi() -> dict:
    """Keep FastAPI's generated validation status aligned with C4's HTTP 400."""
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
    )
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)
    app.openapi_schema = schema
    return schema


app.openapi = _c4_openapi
