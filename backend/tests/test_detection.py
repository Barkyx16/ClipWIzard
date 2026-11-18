import numpy as np

from app.analysis.highlights import DetectOptions, detect_highlights, smooth
from app.analysis.signals import MotionAccumulator, Signals, build_signals
from app.demo import BEATS
from app.media.ffmpeg import decode_for_analysis, probe


def _analyse(path, tmp_path, **opts):
    info = probe(path)
    acc = MotionAccumulator()
    decode_for_analysis(path, tmp_path / "a.raw", info.has_audio, info.duration, acc.feed)
    sig = build_signals(tmp_path / "a.raw", acc, info.has_audio)
    return info, sig, detect_highlights(sig, info.duration, DetectOptions(**opts))[1]


def test_probe(demo_video):
    info = probe(demo_video)
    assert abs(info.duration - 90) < 0.5
    assert (info.width, info.height) == (320, 180)
    assert info.has_audio


def test_finds_every_action_beat(demo_video, tmp_path):
    _, sig, cands = _analyse(demo_video, tmp_path)
    assert len(sig) == 360  # 90 s at 4 hops/s
    for name, (b0, b1) in BEATS.items():
        hits = [c for c in cands if c.start <= b1 and c.end >= b0 and b0 - 1 <= c.peak <= b1 + 1]
        assert hits, f"missed the {name} beat: {[(c.start, c.end, c.peak) for c in cands]}"


def test_categories_match_beats(demo_video, tmp_path):
    _, _, cands = _analyse(demo_video, tmp_path)
    by_beat = {}
    for name, (b0, b1) in BEATS.items():
        by_beat[name] = next(c for c in cands if b0 - 1 <= c.peak <= b1 + 1).category
    assert by_beat == {"shootout": "Shootout", "explosion": "Big Impact", "chase": "Chase"}


def test_calm_sections_are_not_clipped(demo_video, tmp_path):
    _, _, cands = _analyse(demo_video, tmp_path)
    for c in cands:
        assert not (5 <= c.peak <= 18), f"clipped a calm section at {c.peak}"


def test_clip_lengths_respect_preset(demo_video, tmp_path):
    for length, (lo, hi) in {"short": (12, 30), "medium": (25, 60)}.items():
        info, _, cands = _analyse(demo_video, tmp_path, length=length)
        assert cands
        for c in cands:
            assert 0 <= c.start < c.peak < c.end <= info.duration
            assert c.duration <= hi + 0.01
            # Clips can only be shorter than the minimum when the video edge cuts them.
            assert c.duration >= lo - 0.01 or c.start == 0 or c.end == info.duration


def test_highlights_do_not_overlap(demo_video, tmp_path):
    _, _, cands = _analyse(demo_video, tmp_path, length="medium", max_clips=10)
    ordered = sorted(cands, key=lambda c: c.start)
    for a, b in zip(ordered, ordered[1:]):
        assert a.end <= b.start + 1e-6


def test_max_clips_and_scores(demo_video, tmp_path):
    _, _, cands = _analyse(demo_video, tmp_path, max_clips=2)
    assert len(cands) == 2
    assert all(0 <= c.score <= 100 for c in cands)
    assert cands[0].category == "Shootout"  # the most intense beat ranks first


def test_flat_input_produces_no_highlights():
    n = 4 * 120
    rng = np.random.default_rng(0)
    sig = Signals(
        hop=0.25,
        loudness=(-40 + rng.normal(0, 0.3, n)).astype(np.float32),
        onsets=np.zeros(n, np.float32),
        motion=(0.01 + rng.normal(0, 0.0005, n)).astype(np.float32),
        brightness=np.full(n, 0.4, np.float32),
        cuts=np.zeros(n, np.float32),
        has_audio=True,
    )
    _, cands = detect_highlights(sig, 120.0, DetectOptions())
    assert cands == []


def test_silent_video_uses_motion_only():
    n = 4 * 100
    motion = np.full(n, 0.01, np.float32)
    motion[200:240] = 0.12  # 10 s burst of motion at 50-60 s
    sig = Signals(hop=0.25, loudness=np.full(n, -90, np.float32), onsets=np.zeros(n, np.float32),
                  motion=motion, brightness=np.full(n, 0.4, np.float32),
                  cuts=np.zeros(n, np.float32), has_audio=False)
    _, cands = detect_highlights(sig, 100.0, DetectOptions())
    assert len(cands) == 1
    assert 48 <= cands[0].peak <= 62


def test_smooth_preserves_length():
    x = np.arange(50, dtype=np.float32)
    assert smooth(x, 3).shape == x.shape
