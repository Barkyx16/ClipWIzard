"""Per-IP rate limiting for the endpoints that start expensive work.

Workspaces are anonymous and free to create, so per-workspace limits alone
can be sidestepped by dropping the cookie. This caps how many jobs one client
address can start per minute and per hour.

* Only requests that were accepted (status < 400) count, so a client politely
  retrying after "your videos are still processing" doesn't burn its budget.
* IPv6 clients are bucketed per /64, since one host usually owns a whole /64.
* Memory is bounded: idle keys are swept and the table has a hard cap.

In-memory and per-process, which matches the single-process deployment
(background jobs also live in-process). Behind a reverse proxy, set
CLIPWIZARD_TRUST_PROXY=1 so the client IP is read from X-Forwarded-For.
"""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections import OrderedDict, deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Method + path patterns that start uploads, imports, renders, transcriptions or zips.
LIMITED = [
    ("POST", re.compile(r"^/api/uploads$")),
    ("POST", re.compile(r"^/api/videos$")),
    ("POST", re.compile(r"^/api/videos/import$")),
    ("POST", re.compile(r"^/api/videos/[^/]+/(clips|export-all|montage|transcripts|reanalyze)$")),
    ("GET", re.compile(r"^/api/videos/[^/]+/clips\.zip$")),
]

WINDOW = 3600.0
MAX_KEYS = 100_000


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RateLimiter:
    def __init__(self, per_minute: int, per_hour: int, max_keys: int = MAX_KEYS):
        self.per_minute, self.per_hour, self.max_keys = per_minute, per_hour, max_keys
        # key -> timestamps (oldest first); ordered by most recent activity.
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _sweep(self, now: float) -> None:
        # Least recently active keys sit at the front: drop idle ones, then enforce the cap.
        while self._hits:
            key, hits = next(iter(self._hits.items()))
            if hits and now - hits[-1] <= WINDOW and len(self._hits) <= self.max_keys:
                break
            self._hits.popitem(last=False)

    def wait_time(self, key: str, now: float | None = None) -> float | None:
        """Seconds to wait if ``key`` is over its limit, else None. Doesn't record a hit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return None
            while hits and now - hits[0] > WINDOW:
                hits.popleft()
            recent = 0
            for t in reversed(hits):  # newest first; stops after at most per_minute steps
                if now - t > 60:
                    break
                recent += 1
                if self.per_minute and recent >= self.per_minute:
                    return max(1.0, 60 - (now - t))
            if self.per_hour and len(hits) >= self.per_hour:
                return max(1.0, WINDOW - (now - hits[0]))
            return None

    def record(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            hits.append(now)
            self._hits[key] = hits  # re-insert at the end (most recent)
            self._sweep(now)

    def check(self, key: str, now: float | None = None) -> float | None:
        """Wait time if limited, otherwise record the hit and return None."""
        wait = self.wait_time(key, now)
        if wait is None:
            self.record(key, now)
        return wait

    def __len__(self) -> int:
        return len(self._hits)


def _bucket(raw: str) -> str | None:
    try:
        ip = ipaddress.ip_address(raw.strip().strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def client_key(request: Request) -> str:
    """Rate-limit key for the caller: its IP (IPv6 per /64)."""
    if os.environ.get("CLIPWIZARD_TRUST_PROXY") == "1":
        # The rightmost entry was added by our own proxy; anything to its left
        # came from the client and can be forged.
        entries = [e for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
        if entries:
            key = _bucket(entries[-1])
            if key:
                return key
    host = request.client.host if request.client else ""
    return _bucket(host) or "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter | None = None):  # type: ignore[no-untyped-def]
        super().__init__(app)
        # (explicit None check: an empty limiter has len() == 0 and is falsy)
        self.limiter = limiter if limiter is not None else RateLimiter(
            _int_env("CLIPWIZARD_RATE_LIMIT_PER_MIN", 20),
            _int_env("CLIPWIZARD_RATE_LIMIT_PER_HOUR", 200),
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        method, path = request.method, request.url.path
        if not any(m == method and rx.match(path) for m, rx in LIMITED):
            return await call_next(request)
        key = client_key(request)
        wait = self.limiter.wait_time(key)
        if wait is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Slow down a little. Try again in {int(wait) + 1} seconds."},
                headers={"Retry-After": str(int(wait) + 1)},
            )
        response = await call_next(request)
        if response.status_code < 400:  # only work that was actually accepted counts
            self.limiter.record(key)
        return response
