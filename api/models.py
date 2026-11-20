"""Pydantic models shared by the API scaffold and endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """C4 standard error response envelope."""

    error: ErrorDetail
