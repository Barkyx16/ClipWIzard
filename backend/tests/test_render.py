import pytest

from app.media.ffmpeg import probe
from app.media.render import RenderOptions, render_clip


@pytest.mark.parametrize("aspect,size", [
    ("vertical_blur", (1080, 1920)),
    ("vertical_crop", (1080, 1920)),
    ("square", (1080, 1080)),
    ("landscape", (320, 180)),
])
def test_render_aspects(demo_video, tmp_path, aspect, size):
    out = tmp_path / f"{aspect}.mp4"
    opts = RenderOptions(aspect=aspect, title="Shootout at the docks: no way!", quality="fast")
    render_clip(demo_video, out, 25.0, 29.0, 320, 180, 25.0, True, opts, tmp_path / "work")
    info = probe(out)
    assert (info.width, info.height) == size
    assert abs(info.duration - 4.0) < 0.3
    assert info.has_audio


def test_render_reports_progress(demo_video, tmp_path):
    seen = []
    render_clip(demo_video, tmp_path / "p.mp4", 10.0, 16.0, 320, 180, 25.0, True,
                RenderOptions(aspect="landscape", quality="fast"), tmp_path / "work",
                progress=seen.append)
    assert seen and max(seen) > 0.5


def test_strip_unrenderable():
    from app.media.render import strip_unrenderable

    assert strip_unrenderable("Sent to orbit 🚀🔥 lol") == "Sent to orbit lol"
    assert strip_unrenderable("Café — ok") == "Café — ok"


def test_slow_motion_doubles_duration(demo_video, tmp_path):
    out = tmp_path / "slow.mp4"
    render_clip(demo_video, out, 52.0, 55.0, 320, 180, 25.0, True,
                RenderOptions(aspect="landscape", speed=0.5, quality="fast"), tmp_path / "w")
    info = probe(out)
    assert abs(info.duration - 6.0) < 0.3
    assert info.has_audio


def _integrated_lufs(path):
    import re
    import subprocess

    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out)[-1])


def test_loudness_normalisation(demo_video, tmp_path):
    quiet = tmp_path / "quiet.mp4"
    norm = tmp_path / "norm.mp4"
    # 5-15s of the demo is the quiet "cruising" ambience.
    render_clip(demo_video, quiet, 5, 15, 320, 180, 25.0, True,
                RenderOptions(aspect="landscape", normalize=False, quality="fast"), tmp_path / "w1")
    render_clip(demo_video, norm, 5, 15, 320, 180, 25.0, True,
                RenderOptions(aspect="landscape", normalize=True, quality="fast"), tmp_path / "w2")
    before, after = _integrated_lufs(quiet), _integrated_lufs(norm)
    assert before < -25
    assert -17 < after < -11
