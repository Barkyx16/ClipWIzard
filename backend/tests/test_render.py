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
