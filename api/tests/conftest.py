"""Shared API-test isolation fixtures."""

import pytest

from api import main as api_main
from api.rate_limit import FixedWindowRateLimiter


@pytest.fixture(autouse=True)
def isolate_api_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every API test fresh in-memory rate-limit state."""
    monkeypatch.setattr(api_main, "rate_limiter", FixedWindowRateLimiter())
