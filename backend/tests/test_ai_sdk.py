"""Drive the real Anthropic SDK against a mock HTTP transport (no network, no key).

Checks that the request ClipWizard builds is accepted by the SDK, carries the
beta flag, images and JSON schema, and that a realistic response is parsed.
"""

import json

import pytest

from app.analysis import ai
from app.analysis.highlights import Candidate


@pytest.fixture()
def captured(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        payload = {
            "is_gameplay": True, "category": "Explosion", "title": "Gas station goes up",
            "description": "A car hits the pumps.", "caption": "Did not expect that.",
            "hashtags": ["gta6", "boom"], "hype_score": 88,
        }
        return httpx2.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 80},
        })

    real = anthropic.Anthropic

    def client_factory(**kwargs):
        return real(api_key="sk-ant-test", max_retries=0,
                    http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(anthropic, "Anthropic", client_factory)
    return seen


def test_enrichment_request_and_parse(demo_video, tmp_path, captured):
    import anthropic

    c = Candidate(start=50.0, end=58.0, peak=52.8, excitement=5.0, score=70, category="Big Impact",
                  signals={"audio": 0.6, "gunfire": 0.1, "motion": 0.3, "impact_db": 30.0})
    result = ai._enrich_one(anthropic.Anthropic(), demo_video, c, tmp_path, 0)

    assert result["title"] == "Gas station goes up" and result["hype_score"] == 88
    body = captured["body"]
    assert captured["url"].endswith("/v1/messages?beta=true") or captured["url"].endswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in captured["headers"].get("anthropic-beta", "")
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "low"
    images = [b for b in body["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 5 and all(i["source"]["media_type"] == "image/jpeg" for i in images)
    assert "temperature" not in body  # rejected by current API versions
