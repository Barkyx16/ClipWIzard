import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _wait(client, url, key="status", done=("ready", "done", "failed"), timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(url).json()
        if body[key] in done:
            return body
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting on {url}: {body}")


def _upload(client, path, **params):
    return client.post(
        "/api/videos",
        params={"filename": "my gta6 session.mp4", **params},
        content=path.read_bytes(),
        headers={"content-type": "application/octet-stream"},
    )


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["ai_enabled"] is False


def test_rejects_unsupported_files(client):
    r = client.post("/api/videos", params={"filename": "notes.txt"}, content=b"hello")
    assert r.status_code == 400


def test_rejects_non_video_content(client):
    r = client.post("/api/videos", params={"filename": "fake.mp4"}, content=b"not a video")
    assert r.status_code == 400


def test_full_flow(client, demo_video):
    r = _upload(client, demo_video, length="short", max_clips=5)
    assert r.status_code == 201, r.text
    vid = r.json()["id"]

    video = _wait(client, f"/api/videos/{vid}")
    assert video["status"] == "ready", video["error"]
    assert video["name"] == "my gta6 session.mp4"
    hl = video["highlights"]
    assert 3 <= len(hl) <= 5
    assert [h["rank"] for h in hl] == list(range(len(hl)))
    assert hl[0]["score"] >= hl[-1]["score"]
    assert all(h["thumbnail_url"] for h in hl)
    assert client.get(hl[0]["thumbnail_url"]).status_code == 200
    assert client.get(video["source_url"]).status_code == 200

    tl = client.get(f"/api/videos/{vid}/timeline").json()
    assert tl["excitement"] and max(tl["excitement"]) == 1.0

    # Edit a title.
    r = client.patch(f"/api/highlights/{hl[0]['id']}", json={"title": "Insane docks shootout"})
    assert r.json()["title"] == "Insane docks shootout"

    # Render one clip.
    r = client.post(f"/api/videos/{vid}/clips", json={
        "highlight_id": hl[0]["id"], "start": hl[0]["start"], "end": hl[0]["start"] + 3,
        "aspect": "vertical_blur", "title_overlay": True, "title": "Insane docks shootout",
        "quality": "fast",
    })
    assert r.status_code == 201, r.text
    clip = _wait(client, f"/api/clips/{r.json()['id']}")
    assert clip["status"] == "done", clip["error"]
    dl = client.get(clip["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "video/mp4"
    assert "insane-docks-shootout" in dl.headers["content-disposition"]

    # Bulk export.
    r = client.post(f"/api/videos/{vid}/export-all", json={"top": 2, "quality": "fast"})
    assert r.status_code == 201 and len(r.json()) == 2
    for c in r.json():
        assert _wait(client, f"/api/clips/{c['id']}")["status"] == "done"
    assert len(client.get(f"/api/videos/{vid}/clips").json()) == 3

    # Invalid ranges are rejected.
    bad = client.post(f"/api/videos/{vid}/clips", json={"start": 10, "end": 9})
    assert bad.status_code == 422

    # Delete everything.
    assert client.delete(f"/api/videos/{vid}").status_code == 204
    assert client.get(f"/api/videos/{vid}").status_code == 404


def test_ai_enrichment_is_merged(client, demo_video, monkeypatch):
    """Fake the Claude client and check its output lands on the highlights."""
    import json as _json

    import anthropic

    from app.config import get_settings

    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            payload = {
                "is_gameplay": True, "category": "Police Chase", "title": "Cops can't keep up",
                "description": "Player outruns police.", "caption": "Five stars and still free.",
                "hashtags": ["#GTA6", "police chase", "gta6"], "hype_score": 91,
            }
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=_json.dumps(payload))])

    class FakeClient:
        def __init__(self, **_):
            self.beta = SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setattr(type(get_settings()), "ai_enabled", property(lambda self: True))

    vid = _upload(client, demo_video, max_clips=3).json()["id"]
    video = _wait(client, f"/api/videos/{vid}")
    assert video["status"] == "ready", video["error"]
    assert video["ai_used"] is True
    h = video["highlights"][0]
    assert h["ai_enriched"] is True
    assert h["title"] == "Cops can't keep up"
    assert h["category"] == "Police Chase"
    assert h["hashtags"] == ["gta6", "policechase"]
    assert calls and calls[0]["output_config"]["format"]["type"] == "json_schema"
    images = [b for b in calls[0]["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 5
    client.delete(f"/api/videos/{vid}")


def test_workspaces_are_private(client, demo_video):
    from app.main import app

    vid = _upload(client, demo_video, max_clips=2).json()["id"]
    video = _wait(client, f"/api/videos/{vid}")
    thumb = video["highlights"][0]["thumbnail_url"]
    source = video["source_url"]

    with TestClient(app) as stranger:
        assert all(v["id"] != vid for v in stranger.get("/api/videos").json())
        assert stranger.get(f"/api/videos/{vid}").status_code == 404
        assert stranger.get(f"/api/videos/{vid}/timeline").status_code == 404
        assert stranger.get(source).status_code == 404
        assert stranger.get(thumb).status_code == 404
        assert stranger.delete(f"/api/videos/{vid}").status_code == 404
        hid = video["highlights"][0]["id"]
        assert stranger.patch(f"/api/highlights/{hid}", json={"title": "x"}).status_code == 404
        assert stranger.post(f"/api/videos/{vid}/clips", json={"start": 1, "end": 3}).status_code == 404

        # Opening the owner's workspace key on another device grants access.
        key = client.get("/api/workspace").json()["key"]
        r = stranger.post("/api/workspace", json={"key": key})
        assert r.status_code == 200 and r.json()["videos"] >= 1
        assert stranger.get(f"/api/videos/{vid}").status_code == 200
        assert stranger.get(thumb).status_code == 200

        assert stranger.post("/api/workspace", json={"key": "x" * 10}).status_code == 422

    assert client.delete(f"/api/videos/{vid}").status_code == 204


def test_media_rejects_path_tricks(client):
    for url in ["/media/uploads/..%2Fclipwizard.sqlite3", "/media/other/x.mp4", "/media/uploads/a b.mp4"]:
        assert client.get(url).status_code == 404


def test_facecam_layout_flow(client, demo_video):
    vid = _upload(client, demo_video, max_clips=1).json()["id"]
    _wait(client, f"/api/videos/{vid}")
    # Exporting the facecam layout requires a marked facecam.
    r = client.post(f"/api/videos/{vid}/clips", json={"start": 1, "end": 3, "aspect": "vertical_facecam"})
    assert r.status_code == 422
    bad = client.put(f"/api/videos/{vid}/layout", json={"facecam": {"x": 0.9, "y": 0, "w": 0.5, "h": 0.2}})
    assert bad.status_code == 422
    rect = {"x": 0.7, "y": 0.05, "w": 0.25, "h": 0.3}
    assert client.put(f"/api/videos/{vid}/layout", json={"facecam": rect}).json() == {"facecam": rect}
    assert client.get(f"/api/videos/{vid}").json()["layout"]["facecam"] == rect
    r = client.post(f"/api/videos/{vid}/clips", json={
        "start": 1, "end": 3, "aspect": "vertical_facecam", "quality": "fast"})
    assert r.status_code == 201 and r.json()["options"]["facecam"] == rect
    assert _wait(client, f"/api/clips/{r.json()['id']}")["status"] == "done"
    assert client.put(f"/api/videos/{vid}/layout", json={"facecam": None}).json() == {}
    client.delete(f"/api/videos/{vid}")
