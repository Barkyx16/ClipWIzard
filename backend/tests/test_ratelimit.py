from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ratelimit import RateLimiter, RateLimitMiddleware


def test_limiter_minute_and_hour_windows():
    rl = RateLimiter(per_minute=3, per_hour=5)
    t = 1000.0
    assert [rl.check("a", t + i) for i in range(3)] == [None, None, None]
    wait = rl.check("a", t + 3)
    assert wait is not None and 50 < wait <= 60
    assert rl.check("b", t + 3) is None  # other IPs unaffected
    # A minute later the minute window frees up, until the hourly cap.
    assert rl.check("a", t + 70) is None
    assert rl.check("a", t + 71) is None
    wait = rl.check("a", t + 140)
    assert wait is not None and wait > 3000
    assert rl.check("a", t + 3700) is None


def _app(limiter):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.post("/api/videos/{vid}/clips")
    def clips(vid: str):
        return {"ok": True}

    @app.get("/api/videos/{vid}")
    def get(vid: str):
        return {"ok": True}

    return app


def test_middleware_limits_only_job_endpoints(monkeypatch):
    client = TestClient(_app(RateLimiter(per_minute=2, per_hour=100)))
    assert client.post("/api/videos/x/clips").status_code == 200
    assert client.post("/api/videos/x/clips").status_code == 200
    r = client.post("/api/videos/x/clips")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert "Slow down" in r.json()["detail"]
    for _ in range(5):
        assert client.get("/api/videos/x").status_code == 200


def test_forwarded_for_only_when_trusted(monkeypatch):
    client = TestClient(_app(RateLimiter(per_minute=1, per_hour=100)))
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    # Untrusted: the spoofed header is ignored, same client IP -> limited.
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "2.2.2.2"}).status_code == 429
    monkeypatch.setenv("CLIPWIZARD_TRUST_PROXY", "1")
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "3.3.3.3, 10.0.0.1"}).status_code == 200
