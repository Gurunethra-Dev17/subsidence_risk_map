"""FastAPI application scaffold for the C4 REST API."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.models import ErrorEnvelope


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
    return JSONResponse(status_code=status_code, content=envelope.model_dump())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    del request
    if exc.status_code == 404:
        return error_response(404, "not_found", "Resource not found")
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
    return error_response(500, "internal", "Internal server error")


@app.get(f"{API_PREFIX}/health", tags=["health"])
async def health() -> dict[str, str]:
    """Return liveness status and the running API version tag."""
    return {"status": "ok", "version": settings.api_version}
