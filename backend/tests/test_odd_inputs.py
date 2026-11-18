"""Recordings that aren't 16:9 with sound: silent captures and portrait phone videos."""

import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app.media.ffmpeg import probe
from app.media.render import ASPECTS, RenderOptions, render_clip


def _make(path, size, with_audio, secs=20):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={secs}"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={secs}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.mark.parametrize("aspect", sorted(ASPECTS))
def test_portrait_source_renders_every_format(tmp_path, aspect):
    src = _make(tmp_path / "portrait.mp4", "360x640", True, secs=4)
    out = tmp_path / f"{aspect}.mp4"
    opts = RenderOptions(aspect=aspect, title="Phone clip", quality="fast",
                         facecam={"x": 0.6, "y": 0.05, "w": 0.35, "h": 0.2} if aspect == "vertical_facecam" else None,
                         crop_keys=[(0.0, 0.3), (2.0, 0.7)] if aspect == "vertical_smart" else [])
    render_clip(src, out, 0.5, 3.0, 360, 640, 25.0, True, opts, tmp_path / "w")
    info = probe(out)
    if aspect == "landscape":
        assert (info.width, info.height) == (360, 640)  # keeps the source shape
    else:
        assert (info.width, info.height) == ASPECTS[aspect]
    assert info.duration == pytest.approx(2.5, abs=0.3)


def test_silent_video_end_to_end(tmp_path):
    from app.main import app

    src = _make(tmp_path / "silent.mp4", "640x360", False)
    with TestClient(app) as client:
        r = client.post("/api/videos", params={"filename": "silent.mp4"}, content=src.read_bytes(),
                        headers={"content-type": "application/octet-stream"})
        assert r.status_code == 201 and r.json()["has_audio"] is False
        vid = r.json()["id"]
        deadline = time.time() + 60
        while (v := client.get(f"/api/videos/{vid}").json())["status"] not in ("ready", "failed"):
            assert time.time() < deadline
            time.sleep(0.3)
        assert v["status"] == "ready", v["error"]
        # No audio: transcripts are refused, captioned exports still render (with a warning).
        assert client.post(f"/api/videos/{vid}/transcripts", json={"start": 1, "end": 5}).status_code == 422
        c = client.post(f"/api/videos/{vid}/clips", json={
            "start": 1, "end": 5, "captions": True, "aspect": "vertical_smart", "quality": "fast"}).json()
        while (clip := client.get(f"/api/clips/{c['id']}").json())["status"] in ("queued", "rendering"):
            time.sleep(0.3)
        assert clip["status"] == "done", clip["error"]
        assert clip["warning"]
        client.delete(f"/api/videos/{vid}")
