"""Reusable authority-token dependency for protected API routes."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

AUTHORITY_HEADER = "X-Authority-Token"
_DEVELOPMENT_TOKEN = "demo-authority"

authority_api_key = APIKeyHeader(
    name=AUTHORITY_HEADER,
    scheme_name="AuthorityToken",
    description="Authority access token supplied by the deployment.",
    auto_error=False,
)


def _expected_authority_token() -> str | None:
    """Read credentials at request time so tests/config reloads stay isolated."""
    configured = os.getenv("AUTHORITY_TOKEN")
    if configured is not None:
        return configured if configured.strip() else None

    if os.getenv("API_ENV", "production").casefold() == "dev":
        return _DEVELOPMENT_TOKEN
    return None


async def require_authority(
    supplied_token: Annotated[str | None, Security(authority_api_key)],
) -> None:
    """Require the configured authority token, comparing values in constant time."""
    expected_token = _expected_authority_token()
    if not supplied_token or expected_token is None:
        raise HTTPException(status_code=401, detail="Authority token required")

    supplied_bytes = supplied_token.encode("utf-8")
    expected_bytes = expected_token.encode("utf-8")
    if not hmac.compare_digest(supplied_bytes, expected_bytes):
        raise HTTPException(status_code=401, detail="Authority token required")
