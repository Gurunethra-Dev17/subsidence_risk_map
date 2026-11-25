"""Deterministic rate-limit tests using synthetic requests and a fake clock."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Self

from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

import api.main as api_main
from api.rate_limit import FixedWindowRateLimiter, client_ip_from_scope

TOKEN = "synthetic-rate-limit-token"
BUILDINGS_PATH = "/api/v1/buildings"
BBOX = "77.0,28.5,77.2,28.7"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class LockOwnerProbe:
    """Lock wrapper exposing ownership for a deterministic clock-order test."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner_lock = threading.Lock()
        self._owner: int | None = None

    def __enter__(self) -> Self:
        self._lock.acquire()
        with self._owner_lock:
            self._owner = threading.get_ident()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        with self._owner_lock:
            self._owner = None
        self._lock.release()

    def owned_by_current_thread(self) -> bool:
        with self._owner_lock:
            return self._owner == threading.get_ident()


def test_fixed_window_threshold_and_reset() -> None:
    clock = FakeClock()
    limiter = FixedWindowRateLimiter(clock=clock)

    assert limiter.allow("192.0.2.1", bucket="public", limit=2)
    assert limiter.allow("192.0.2.1", bucket="public", limit=2)
    assert not limiter.allow("192.0.2.1", bucket="public", limit=2)

    clock.now = 60.0
    assert limiter.allow("192.0.2.1", bucket="public", limit=2)


def test_fixed_window_updates_are_thread_safe() -> None:
    lock_probe = LockOwnerProbe()
    sampled = 0

    def ordered_clock() -> float:
        nonlocal sampled
        assert lock_probe.owned_by_current_thread()
        sampled += 1
        return float(sampled)

    limiter = FixedWindowRateLimiter(clock=ordered_clock)
    limiter._lock = lock_probe  # type: ignore[assignment]

    def request_allowed(_: int) -> bool:
        return limiter.allow(
            "192.0.2.10", bucket="public", limit=100, window_seconds=1000
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        decisions = list(pool.map(request_allowed, range(100)))
    assert sum(decisions) == 100
    assert limiter._clients["192.0.2.10"].last_seen == 100.0


def test_clients_and_route_buckets_are_independent() -> None:
    limiter = FixedWindowRateLimiter(clock=FakeClock())

    assert limiter.allow("192.0.2.1", bucket="public", limit=1)
    assert not limiter.allow("192.0.2.1", bucket="public", limit=1)
    assert limiter.allow("192.0.2.2", bucket="public", limit=1)
    assert limiter.allow("192.0.2.1", bucket="buildings", limit=1)


def test_client_key_uses_peer_ip_and_ignores_forwarded_headers() -> None:
    first_scope = {
        "client": ("2001:0db8:0:0::1", 4000),
        "headers": [(b"x-forwarded-for", b"198.51.100.10")],
    }
    spoofed_scope = {
        "client": ("2001:db8::1", 4001),
        "headers": [(b"x-forwarded-for", b"203.0.113.99")],
    }

    assert client_ip_from_scope(first_scope) == "2001:db8::1"
    assert client_ip_from_scope(first_scope) == client_ip_from_scope(spoofed_scope)
    assert client_ip_from_scope({"client": ("not-an-ip", 80)}) == "unknown"
    assert client_ip_from_scope({}) == "unknown"


def test_client_map_is_bounded_and_stale_entries_expire() -> None:
    clock = FakeClock()
    limiter = FixedWindowRateLimiter(max_clients=2, clock=clock)

    assert limiter.allow("192.0.2.1", bucket="public", limit=2)
    assert limiter.allow("192.0.2.2", bucket="public", limit=2)
    assert limiter.allow("192.0.2.3", bucket="public", limit=2)
    assert limiter.tracked_clients == 2

    clock.now = 61.0
    assert limiter.allow("192.0.2.4", bucket="public", limit=2)
    assert limiter.tracked_clients == 1


class PublicStore:
    def list_wards(self, **kwargs) -> dict:
        return {
            "items": [],
            "total": 0,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }


class BuildingStore:
    def __init__(self) -> None:
        self.calls = 0

    def get_buildings(self, **kwargs) -> dict:
        self.calls += 1
        return {"type": "FeatureCollection", "features": []}


def _configure(monkeypatch, clock: FakeClock) -> BuildingStore:
    monkeypatch.setenv("API_ENV", "production")
    monkeypatch.setenv("AUTHORITY_TOKEN", TOKEN)
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        FixedWindowRateLimiter(clock=clock),
    )
    store = BuildingStore()
    monkeypatch.setattr(api_main, "data_store", store)
    return store


def test_unauthorized_buildings_attempts_count_and_429_is_c4_no_store(
    monkeypatch,
) -> None:
    store = _configure(monkeypatch, FakeClock())
    client = TestClient(api_main.app)

    for _ in range(30):
        response = client.get(BUILDINGS_PATH, params={"bbox": BBOX})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authority_required"

    limited = client.get(BUILDINGS_PATH, params={"bbox": BBOX})
    assert limited.status_code == 429
    assert limited.json() == {
        "error": {
            "code": "rate_limited",
            "message": "Too many requests",
            "details": {},
        }
    }
    assert limited.headers.get("ETag")
    assert limited.headers["Cache-Control"] == "no-store"
    assert store.calls == 0


def test_public_and_buildings_limits_are_separate(monkeypatch) -> None:
    _configure(monkeypatch, FakeClock())
    monkeypatch.setattr(api_main, "data_store", PublicStore())
    client = TestClient(api_main.app)

    for _ in range(60):
        assert client.get("/api/v1/wards").status_code == 200

    unauthorized = client.get(BUILDINGS_PATH, params={"bbox": BBOX})
    assert unauthorized.status_code == 401


def test_health_is_exempt_from_rate_limiting(monkeypatch) -> None:
    clock = FakeClock()
    _configure(monkeypatch, clock)
    client = TestClient(api_main.app)

    for _ in range(61):
        assert client.get("/api/v1/health").status_code == 200
    assert api_main.rate_limiter.tracked_clients == 0


def test_cors_preflight_does_not_consume_buildings_limit(monkeypatch) -> None:
    _configure(monkeypatch, FakeClock())
    cors_app = CORSMiddleware(
        app=api_main.app,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )
    client = TestClient(cors_app)

    preflight = client.options(
        BUILDINGS_PATH,
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-authority-token",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"

    for _ in range(30):
        assert client.get(BUILDINGS_PATH, params={"bbox": BBOX}).status_code == 401
    assert client.get(BUILDINGS_PATH, params={"bbox": BBOX}).status_code == 429
