import pytest

from app.media.ffmpeg import probe
from app.media.render import RenderOptions, join_segments, render_clip


@pytest.fixture(scope="module")
def segments(demo_video, tmp_path_factory):
    work = tmp_path_factory.mktemp("segs")
    parts = []
    for i, (a, b) in enumerate([(25, 28), (52, 55), (70, 74)]):
        out = work / f"p{i}.mp4"
        render_clip(demo_video, out, a, b, 320, 180, 25.0, True,
                    RenderOptions(aspect="vertical_blur", title=f"Moment {i + 1}", quality="fast"), work / f"w{i}")
        parts.append(out)
    return parts


@pytest.mark.parametrize("transition", ["fade", "fadeblack", "slideleft"])
def test_join_with_transitions(segments, tmp_path, transition):
    out = tmp_path / f"{transition}.mp4"
    seen = []
    join_segments(segments, out, transition, True, tmp_path / "w", progress=seen.append)
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio
    # 3 + 3 + 4 seconds minus two 0.4s overlaps.
    assert info.duration == pytest.approx(9.2, abs=0.25)
    assert seen and max(seen) > 0.8


def test_join_with_hard_cuts(segments, tmp_path):
    out = tmp_path / "cut.mp4"
    join_segments(segments, out, "cut", True, tmp_path / "w")
    assert probe(out).duration == pytest.approx(10.0, abs=0.25)


def test_join_single_segment(segments, tmp_path):
    out = tmp_path / "one.mp4"
    join_segments(segments[:1], out, "fade", True, tmp_path / "w")
    assert probe(out).duration == pytest.approx(3.0, abs=0.2)
