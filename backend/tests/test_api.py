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


def test_captions_flow(client, demo_video, monkeypatch):
    from app.media import captions

    words = [captions.Word(0.1, 0.5, "Let's"), captions.Word(0.6, 1.0, "go!")]
    monkeypatch.setattr(captions, "transcribe", lambda *a, **k: words)
    vid = _upload(client, demo_video, max_clips=1).json()["id"]
    _wait(client, f"/api/videos/{vid}")
    r = client.post(f"/api/videos/{vid}/clips", json={
        "start": 20, "end": 23, "aspect": "vertical_blur", "captions": True, "quality": "fast"})
    clip = _wait(client, f"/api/clips/{r.json()['id']}")
    assert clip["status"] == "done", clip["error"]
    assert clip["transcript"] == "Let's go!"
    assert clip["warning"] is None

    def boom(*a, **k):
        raise captions.CaptionError("model download blocked")

    monkeypatch.setattr(captions, "transcribe", boom)
    r = client.post(f"/api/videos/{vid}/clips", json={
        "start": 20, "end": 23, "captions": True, "quality": "fast"})
    clip = _wait(client, f"/api/clips/{r.json()['id']}")
    assert clip["status"] == "done"
    assert "model download blocked" in clip["warning"]
    client.delete(f"/api/videos/{vid}")


def test_montage_flow(client, demo_video):
    vid = _upload(client, demo_video, max_clips=3).json()["id"]
    video = _wait(client, f"/api/videos/{vid}")
    ids = [h["id"] for h in video["highlights"]]
    assert len(ids) == 3

    assert client.post(f"/api/videos/{vid}/montage", json={"highlight_ids": ids[:1]}).status_code == 422
    assert client.post(f"/api/videos/{vid}/montage", json={"highlight_ids": [ids[0], ids[0]]}).status_code == 422
    assert client.post(f"/api/videos/{vid}/montage", json={"highlight_ids": [ids[0], "nope"]}).status_code == 404

    r = client.post(f"/api/videos/{vid}/montage", json={
        "highlight_ids": ids, "order": "timeline", "transition": "fade", "quality": "fast"})
    assert r.status_code == 201, r.text
    m = r.json()
    starts = [s["start"] for s in m["options"]["segments"]]
    assert starts == sorted(starts)
    assert m["options"]["kind"] == "montage"
    done = _wait(client, f"/api/clips/{m['id']}", timeout=180)
    assert done["status"] == "done", done["error"]
    from app.media.ffmpeg import probe
    from app.config import get_settings

    info = probe(get_settings().clips_dir / f"{m['id']}.mp4")
    expected = sum(h["end"] - h["start"] for h in video["highlights"]) - 0.4 * 2
    assert info.duration == pytest.approx(expected, abs=0.5)
    dl = client.get(done["download_url"])
    assert "montage" in dl.headers["content-disposition"]
    client.delete(f"/api/videos/{vid}")


def test_custom_and_deleted_highlights(client, demo_video):
    vid = _upload(client, demo_video, max_clips=3).json()["id"]
    video = _wait(client, f"/api/videos/{vid}")
    assert client.post(f"/api/videos/{vid}/highlights", json={"start": 5, "end": 5.5}).status_code == 422

    r = client.post(f"/api/videos/{vid}/highlights", json={"start": 2, "end": 9, "title": "Funny NPC"})
    assert r.status_code == 201, r.text
    custom = r.json()
    assert custom["category"] == "Custom" and custom["title"] == "Funny NPC"
    assert custom["rank"] == 3 and custom["thumbnail_url"]
    assert 0 <= custom["score"] <= 100

    first = video["highlights"][0]["id"]
    assert client.delete(f"/api/highlights/{first}").status_code == 204
    hl = client.get(f"/api/videos/{vid}").json()["highlights"]
    assert [h["rank"] for h in hl] == [0, 1, 2]
    assert hl[-1]["id"] == custom["id"]
    assert client.delete(f"/api/highlights/{first}").status_code == 404
    client.delete(f"/api/videos/{vid}")


def test_watermark_render(client, demo_video):
    vid = _upload(client, demo_video, max_clips=1).json()["id"]
    _wait(client, f"/api/videos/{vid}")
    r = client.post(f"/api/videos/{vid}/clips", json={
        "start": 25, "end": 27, "watermark": "@clipking", "quality": "fast"})
    clip = _wait(client, f"/api/clips/{r.json()['id']}")
    assert clip["status"] == "done", clip["error"]
    assert clip["options"]["watermark"] == "@clipking"
    too_long = client.post(f"/api/videos/{vid}/clips", json={"start": 1, "end": 3, "watermark": "x" * 41})
    assert too_long.status_code == 422
    client.delete(f"/api/videos/{vid}")


def test_retention_cleanup(client, demo_video):
    import time as _time

    from app import db, retention
    from app.config import get_settings

    vid = _upload(client, demo_video, max_clips=1).json()["id"]
    _wait(client, f"/api/videos/{vid}")
    upload = get_settings().uploads_dir / db.get_video(vid)["filename"]
    assert upload.exists()
    assert retention.cleanup_once(days=0) == 0
    assert retention.cleanup_once(days=1) == 0  # still fresh
    removed = retention.cleanup_once(days=1, now=_time.time() + 2 * 86400)
    assert removed >= 1
    assert db.get_video(vid) is None and not upload.exists()


def test_share_links(client, demo_video):
    from app.main import app

    vid = _upload(client, demo_video, max_clips=1).json()["id"]
    video = _wait(client, f"/api/videos/{vid}")
    h = video["highlights"][0]
    r = client.post(f"/api/videos/{vid}/clips", json={
        "highlight_id": h["id"], "start": h["start"], "end": h["start"] + 2, "quality": "fast"})
    clip_id = r.json()["id"]
    clip = _wait(client, f"/api/clips/{clip_id}")
    assert clip["share_url"] is None

    shared = client.post(f"/api/clips/{clip_id}/share").json()
    url = shared["share_url"]
    assert url.startswith("/s/")
    token = url.split("/")[-1]
    # Sharing twice keeps the same link.
    assert client.post(f"/api/clips/{clip_id}/share").json()["share_url"] == url

    with TestClient(app) as stranger:
        info = stranger.get(f"/api/share/{token}")
        assert info.status_code == 200
        assert info.headers["x-robots-tag"].startswith("noindex")
        assert info.json()["title"] == h["title"]
        video_resp = stranger.get(info.json()["video_url"])
        assert video_resp.status_code == 200 and video_resp.headers["content-type"] == "video/mp4"
        dl = stranger.get(info.json()["download_url"])
        assert "attachment" in dl.headers["content-disposition"]
        # A stranger can't manage the share.
        assert stranger.delete(f"/api/clips/{clip_id}/share").status_code == 404
        assert stranger.get("/api/share/not-a-real-token-123456").status_code == 404

        assert client.delete(f"/api/clips/{clip_id}/share").json()["share_url"] is None
        assert stranger.get(f"/api/share/{token}").status_code == 404
        assert stranger.get(f"/share/{token}/video.mp4").status_code == 404
    client.delete(f"/api/videos/{vid}")


def test_workspace_limits(demo_video, monkeypatch):
    from app.config import get_settings
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings.__class__, "max_active_videos", property(lambda self: 1), raising=False)
    with TestClient(app) as c:
        first = _upload(c, demo_video, max_clips=1)
        assert first.status_code == 201
        # A second upload while the first is still processing is refused.
        second = _upload(c, demo_video, max_clips=1)
        if c.get(f"/api/videos/{first.json()['id']}").json()["status"] != "ready":
            assert second.status_code == 429, second.text
        _wait(c, f"/api/videos/{first.json()['id']}")
        if second.status_code == 201:
            _wait(c, f"/api/videos/{second.json()['id']}")
            c.delete(f"/api/videos/{second.json()['id']}")

        monkeypatch.setattr(settings.__class__, "workspace_quota_gb", property(lambda self: 0.001), raising=False)
        r = c.post("/api/uploads", json={"filename": "x.mp4", "size": 5 * 1024 * 1024, "fingerprint": "q"})
        assert r.status_code == 413 and "full" in r.json()["detail"]

        monkeypatch.setattr(settings.__class__, "max_active_renders", property(lambda self: 1), raising=False)
        vid = first.json()["id"]
        r1 = c.post(f"/api/videos/{vid}/clips", json={"start": 1, "end": 4, "quality": "fast"})
        assert r1.status_code == 201
        r2 = c.post(f"/api/videos/{vid}/clips", json={"start": 5, "end": 8, "quality": "fast"})
        if c.get(f"/api/clips/{r1.json()['id']}").json()["status"] in ("queued", "rendering"):
            assert r2.status_code == 429
        _wait(c, f"/api/clips/{r1.json()['id']}")
        c.delete(f"/api/videos/{vid}")
