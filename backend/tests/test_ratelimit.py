from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.ratelimit import RateLimiter, RateLimitMiddleware, _bucket


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


def test_limiter_memory_is_bounded():
    rl = RateLimiter(per_minute=5, per_hour=50, max_keys=1000)
    for i in range(5000):  # many distinct (e.g. rotating) addresses
        rl.check(f"10.0.{i // 256}.{i % 256}", 1000.0 + i * 0.001)
    assert len(rl) == 1000
    # Idle keys are swept once their hour has passed.
    rl.check("fresh", 1000.0 + 4000)
    assert len(rl) == 1


def test_ip_buckets():
    assert _bucket("2001:db8:1:2:3:4:5:6") == _bucket("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"
    assert _bucket("::ffff:203.0.113.9") == "203.0.113.9"
    assert _bucket("203.0.113.9") == "203.0.113.9"
    assert _bucket("not-an-ip") is None


def _app(limiter):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.post("/api/videos/{vid}/clips")
    def clips(vid: str):
        if vid == "busy":
            raise HTTPException(429, "Your videos are still processing")
        return {"ok": True}

    @app.get("/api/videos/{vid}")
    def get(vid: str):
        return {"ok": True}

    return app


def test_middleware_limits_only_job_endpoints():
    client = TestClient(_app(RateLimiter(per_minute=2, per_hour=100)))
    assert client.post("/api/videos/x/clips").status_code == 200
    assert client.post("/api/videos/x/clips").status_code == 200
    r = client.post("/api/videos/x/clips")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert "Slow down" in r.json()["detail"]
    for _ in range(5):
        assert client.get("/api/videos/x").status_code == 200


def test_rejected_requests_dont_use_the_budget():
    client = TestClient(_app(RateLimiter(per_minute=2, per_hour=100)))
    for _ in range(10):  # an app-level 429 ("still processing") retried many times
        assert client.post("/api/videos/busy/clips").status_code == 429
    assert client.post("/api/videos/x/clips").status_code == 200


def test_forwarded_for_uses_the_proxy_appended_entry(monkeypatch):
    client = TestClient(_app(RateLimiter(per_minute=1, per_hour=100)))
    # Untrusted: the header is ignored entirely; same client address -> limited.
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "2.2.2.2"}).status_code == 429

    monkeypatch.setenv("CLIPWIZARD_TRUST_PROXY", "1")
    # Trusted proxy appends the real client (rightmost). A forged leftmost value changes nothing.
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "9.9.9.9, 3.3.3.3"}).status_code == 200
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "8.8.8.8, 3.3.3.3"}).status_code == 429
    assert client.post("/api/videos/x/clips", headers={"x-forwarded-for": "4.4.4.4"}).status_code == 200
