"""Small bounded fixed-window rate limiter for single-process deployments."""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

UNKNOWN_CLIENT = "unknown"


def client_ip_from_scope(scope: Mapping[str, object]) -> str:
    """Return the normalized peer IP from ASGI scope, ignoring forwarded headers."""
    client = scope.get("client")
    if not isinstance(client, (tuple, list)) or not client:
        return UNKNOWN_CLIENT
    host = client[0]
    if not isinstance(host, str):
        return UNKNOWN_CLIENT
    # Scope IDs are local interface annotations, not part of the remote address.
    address = host.split("%", 1)[0]
    try:
        return ipaddress.ip_address(address).compressed
    except ValueError:
        return UNKNOWN_CLIENT


@dataclass
class _Window:
    started_at: float
    requests: int


@dataclass
class _Client:
    last_seen: float
    windows: dict[str, _Window]


class FixedWindowRateLimiter:
    """Thread-safe fixed windows with bounded LRU storage and idle expiry."""

    def __init__(
        self,
        *,
        max_clients: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_clients < 1:
            raise ValueError("max_clients must be positive")
        self._max_clients = max_clients
        self._clock = clock
        self._clients: OrderedDict[str, _Client] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def tracked_clients(self) -> int:
        """Return the current bounded entry count, primarily for diagnostics/tests."""
        with self._lock:
            return len(self._clients)

    def allow(
        self,
        client_ip: str,
        *,
        bucket: str,
        limit: int,
        window_seconds: float = 60.0,
    ) -> bool:
        """Consume one request from a client/bucket fixed window if available."""
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")

        with self._lock:
            now = self._clock()
            # LRU order also orders last_seen; stale clients can be removed from
            # the front without retaining an unbounded auxiliary expiry queue.
            while self._clients:
                oldest_ip, oldest = next(iter(self._clients.items()))
                if now - oldest.last_seen < window_seconds:
                    break
                del self._clients[oldest_ip]

            client = self._clients.get(client_ip)
            if client is None:
                if len(self._clients) >= self._max_clients:
                    self._clients.popitem(last=False)
                client = _Client(now, {})
                self._clients[client_ip] = client
            else:
                self._clients.move_to_end(client_ip)
                client.last_seen = now

            entry = client.windows.get(bucket)
            if entry is None:
                entry = _Window(now, 0)
                client.windows[bucket] = entry
            elif now - entry.started_at >= window_seconds:
                entry.started_at = now
                entry.requests = 0

            if entry.requests >= limit:
                return False
            entry.requests += 1
            return True
