"""Per-IP rate limiting for the endpoints that start expensive work.

Workspaces are anonymous and free to create, so per-workspace limits alone
can be sidestepped by dropping the cookie. This caps how many jobs one IP
address can start per minute and per hour.

In-memory and per-process, which matches the single-process deployment
(background jobs also live in-process). Behind a reverse proxy, set
CLIPWIZARD_TRUST_PROXY=1 so the client IP is read from X-Forwarded-For.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Method + path patterns that start uploads, imports, renders or transcriptions.
LIMITED = [
    ("POST", re.compile(r"^/api/uploads$")),
    ("POST", re.compile(r"^/api/videos$")),
    ("POST", re.compile(r"^/api/videos/import$")),
    ("POST", re.compile(r"^/api/videos/[^/]+/(clips|export-all|montage|transcripts|reanalyze)$")),
]


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RateLimiter:
    def __init__(self, per_minute: int, per_hour: int):
        self.per_minute, self.per_hour = per_minute, per_hour
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float | None:
        """Record a hit. Returns seconds to wait if the key is over its limit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > 3600:
                hits.popleft()
            last_minute = sum(1 for t in hits if now - t <= 60)
            if self.per_minute and last_minute >= self.per_minute:
                oldest = next(t for t in hits if now - t <= 60)
                return max(1.0, 60 - (now - oldest))
            if self.per_hour and len(hits) >= self.per_hour:
                return max(1.0, 3600 - (now - hits[0]))
            hits.append(now)
            if len(self._hits) > 50_000:  # keep memory bounded
                for k in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[k]
            return None


def client_ip(request: Request) -> str:
    if os.environ.get("CLIPWIZARD_TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter | None = None):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limiter = limiter or RateLimiter(
            _int_env("CLIPWIZARD_RATE_LIMIT_PER_MIN", 20),
            _int_env("CLIPWIZARD_RATE_LIMIT_PER_HOUR", 200),
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        method, path = request.method, request.url.path
        if any(m == method and rx.match(path) for m, rx in LIMITED):
            wait = self.limiter.check(client_ip(request))
            if wait is not None:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Slow down a little. Try again in {int(wait) + 1} seconds."},
                    headers={"Retry-After": str(int(wait) + 1)},
                )
        return await call_next(request)
