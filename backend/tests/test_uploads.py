import time

import pytest
from fastapi.testclient import TestClient

MB = 1024 * 1024


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _start(client, data, fp="demo:1", **extra):
    return client.post("/api/uploads", json={
        "filename": "big session.mp4", "size": len(data), "fingerprint": fp, "max_clips": 2, **extra})


def _put(client, uid, data, offset):
    return client.put(f"/api/uploads/{uid}", params={"offset": offset}, content=data,
                      headers={"content-type": "application/octet-stream"})


def test_chunked_upload_with_resume(client, demo_video):
    from app.config import get_settings

    data = demo_video.read_bytes()
    r = _start(client, data, fp="resume-test")
    assert r.status_code == 201
    up = r.json()
    assert up["received"] == 0 and up["chunk_size"] > 0
    uid = up["id"]

    # First chunk lands.
    assert _put(client, uid, data[:MB], 0).json()["received"] == MB
    # Wrong offset is refused and tells the client where to continue.
    bad = _put(client, uid, data[MB:2 * MB], 0)
    assert bad.status_code == 409 and bad.json()["detail"]["received"] == MB
    # Finishing early is refused.
    assert client.post(f"/api/uploads/{uid}/complete").status_code == 409

    # Simulate a connection that died mid-chunk: junk bytes past `received`.
    part = get_settings().partial_dir / f"{uid}.part"
    with open(part, "ab") as f:
        f.write(b"garbage-from-a-dropped-request")

    # "Reload the page": starting again with the same fingerprint resumes.
    again = _start(client, data, fp="resume-test").json()
    assert again["id"] == uid and again["received"] == MB

    offset = MB
    while offset < len(data):
        chunk = data[offset: offset + MB]
        assert _put(client, uid, chunk, offset).status_code == 200
        offset += len(chunk)
    assert part.stat().st_size == len(data)

    r = client.post(f"/api/uploads/{uid}/complete")
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert r.json()["name"] == "big session.mp4"
    assert not part.exists()
    assert client.get(f"/api/uploads/{uid}").status_code == 404

    deadline = time.time() + 60
    while time.time() < deadline:
        v = client.get(f"/api/videos/{vid}").json()
        if v["status"] in ("ready", "failed"):
            break
        time.sleep(0.3)
    assert v["status"] == "ready", v["error"]
    assert len(v["highlights"]) == 2
    client.delete(f"/api/videos/{vid}")


def test_upload_validation_and_privacy(client, demo_video):
    from app.main import app

    assert client.post("/api/uploads", json={"filename": "a.txt", "size": 10, "fingerprint": "x"}).status_code == 400
    assert client.post("/api/uploads", json={
        "filename": "a.mp4", "size": 10**15, "fingerprint": "x"}).status_code == 413

    data = b"0123456789" * 10
    uid = _start(client, data, fp="small").json()["id"]
    too_far = _put(client, uid, data + b"extra", 0)
    assert too_far.status_code == 413
    assert client.get(f"/api/uploads/{uid}").json()["received"] == 0

    with TestClient(app) as stranger:
        assert stranger.get(f"/api/uploads/{uid}").status_code == 404
        assert _put(stranger, uid, data, 0).status_code == 404
        # A stranger reusing the fingerprint gets their own upload.
        assert _start(stranger, data, fp="small").json()["id"] != uid

    assert client.delete(f"/api/uploads/{uid}").status_code == 204


def test_non_video_upload_is_rejected_on_complete(client):
    data = b"not a video at all" * 100
    uid = _start(client, data, fp="junk").json()["id"]
    assert _put(client, uid, data, 0).status_code == 200
    r = client.post(f"/api/uploads/{uid}/complete")
    assert r.status_code == 400


def test_auto_export_after_analysis(client, demo_video):
    data = demo_video.read_bytes()
    up = _start(client, data, fp="auto-export", auto_export={
        "top": 2, "aspect": "vertical_facecam", "captions": False, "watermark": "@me"}).json()
    assert _put(client, up["id"], data, 0).status_code == 200
    vid = client.post(f"/api/uploads/{up['id']}/complete").json()["id"]

    deadline = time.time() + 120
    clips = []
    while time.time() < deadline:
        v = client.get(f"/api/videos/{vid}").json()
        clips = v["clips"]
        if v["status"] == "ready" and len(clips) == 2 and all(c["status"] == "done" for c in clips):
            break
        time.sleep(0.5)
    assert v["status"] == "ready", v["error"]
    assert len(clips) == 2 and all(c["status"] == "done" for c in clips), clips
    top_two = {h["id"] for h in v["highlights"][:2]}
    assert {c["highlight_id"] for c in clips} == top_two
    for c in clips:
        assert c["options"]["aspect"] == "vertical_smart"  # facecam needs a marked box
        assert c["options"]["watermark"] == "@me" and c["options"]["auto"] is True

    # A re-scan doesn't export again.
    r = client.post(f"/api/videos/{vid}/reanalyze", json={"max_clips": 2})
    assert r.status_code == 200 and r.json()["settings"]["auto_export"] is None
    while client.get(f"/api/videos/{vid}").json()["status"] != "ready":
        time.sleep(0.3)
    assert len(client.get(f"/api/videos/{vid}/clips").json()) == 2
    client.delete(f"/api/videos/{vid}")


def test_auto_export_respects_render_limit(client, demo_video, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(type(get_settings()), "max_active_renders", property(lambda self: 1), raising=False)
    data = demo_video.read_bytes()
    up = _start(client, data, fp="auto-cap", auto_export={"top": 3, "quality": "fast"}).json()
    _put(client, up["id"], data, 0)
    vid = client.post(f"/api/uploads/{up['id']}/complete").json()["id"]
    deadline = time.time() + 90
    while time.time() < deadline:
        v = client.get(f"/api/videos/{vid}").json()
        if v["status"] == "ready" and v["clips"] and all(c["status"] == "done" for c in v["clips"]):
            break
        time.sleep(0.5)
    assert v["status"] == "ready"
    assert len(v["clips"]) == 1  # capped to the workspace's render limit
    client.delete(f"/api/videos/{vid}")
