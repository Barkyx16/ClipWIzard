import subprocess

import numpy as np

from app.analysis.signals import MotionAccumulator, build_signals
from app.analysis.smartcrop import MAX_PAN_PER_SEC, camera_path, crop_x_expression, keyframes
from app.media.ffmpeg import decode_for_analysis, probe
from app.media.render import RenderOptions, render_clip


def test_path_centres_without_confidence():
    n = 200
    path = camera_path(np.full(n, 0.9, np.float32), np.zeros(n, np.float32), 0.25)
    assert np.allclose(path, 0.5, atol=1e-3)


def test_path_follows_confident_action_at_limited_speed():
    hop, n = 0.25, 400
    fx = np.full(n, 0.5, np.float32)
    fx[200:] = 0.85
    path = camera_path(fx, np.ones(n, np.float32), hop)
    assert abs(path[-1] - 0.85) < 0.02
    assert abs(path[50] - 0.5) < 0.02
    assert np.max(np.abs(np.diff(path))) <= MAX_PAN_PER_SEC * hop + 1e-6
    # The camera starts moving before the action jumps (anticipation).
    assert path[199] > 0.55


def test_keyframes_cover_clip():
    path = np.linspace(0, 1, 400).astype(np.float32)
    keys = keyframes(path, 0.25, 10.0, 20.0, every=0.5)
    assert keys[0][0] == 0 and keys[-1][0] == 10.0
    assert len(keys) == 21
    assert keys[0][1] < keys[-1][1]


def _to_python(expr: str) -> str:
    out, i = [], 0
    while i < len(expr):
        if expr.startswith("if(lt(t,", i):
            # find threshold
            j = expr.index(")", i)
            thr = expr[i + 8 : j]
            out.append(f"(__IF__ t<{thr} ,")
            i = j + 2  # skip "),"
        else:
            out.append(expr[i])
            i += 1
    s = "".join(out)
    # convert "(__IF__ cond , a, b)" into "(a if cond else b)" via a parser-free trick
    return s.replace("(__IF__", "__import__('builtins').__dict__['__IF__'](")


def test_crop_expression_is_piecewise_linear():
    import builtins

    builtins.__IF__ = lambda cond, a, b: a if cond else b  # type: ignore[attr-defined]
    try:
        keys = [(0.0, 0.5), (1.0, 0.75), (2.0, 0.75)]
        expr = crop_x_expression(keys, 1920, 608)
        f = lambda t: eval(_to_python(expr), {"t": t})  # noqa: E731
        x_at = lambda c: min(max(c * 1920 - 304, 0), 1920 - 608)  # noqa: E731
        assert abs(f(0.0) - x_at(0.5)) < 0.2
        assert abs(f(0.5) - (x_at(0.5) + x_at(0.75)) / 2) < 0.2
        assert abs(f(1.5) - x_at(0.75)) < 0.2
        assert abs(f(5.0) - x_at(0.75)) < 0.2
    finally:
        del builtins.__IF__  # type: ignore[attr-defined]


def _make_offcentre_video(path):
    """Static textured scene with a jittering bright box on the right."""
    w, h, fps, secs = 640, 360, 25, 8
    rng = np.random.default_rng(1)
    bg = (rng.integers(20, 60, (h, w), dtype=np.uint8)).astype(np.uint8)
    proc = subprocess.Popen([
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
        "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ], stdin=subprocess.PIPE)
    for i in range(fps * secs):
        f = bg.copy()
        x = 500 + int(15 * np.sin(i / 2)) + int(rng.integers(-8, 8))
        y = 140 + int(rng.integers(-20, 20))
        f[y : y + 70, x - 35 : x + 35] = 255
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


def _mean_brightness(video, t):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
         "-vf", "scale=54:96,format=gray", "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True).stdout
    return float(np.frombuffer(raw, np.uint8).mean())


def test_smart_crop_keeps_offcentre_action_in_frame(tmp_path):
    src = tmp_path / "offcentre.mp4"
    _make_offcentre_video(src)
    info = probe(src)
    acc = MotionAccumulator()
    decode_for_analysis(src, tmp_path / "a.raw", False, info.duration, acc.feed)
    sig = build_signals(None, acc, False)
    path = camera_path(sig.focus_x, sig.focus_conf, sig.hop)
    assert path[len(path) // 2] > 0.65  # camera moved right towards the box

    smart = tmp_path / "smart.mp4"
    keys = keyframes(path, sig.hop, 2.0, 7.0)
    render_clip(src, smart, 2.0, 7.0, 640, 360, 25, False,
                RenderOptions(aspect="vertical_smart", crop_keys=keys, quality="fast"), tmp_path / "w1")
    fixed = tmp_path / "fixed.mp4"
    render_clip(src, fixed, 2.0, 7.0, 640, 360, 25, False,
                RenderOptions(aspect="vertical_crop", crop_x=0.5, quality="fast"), tmp_path / "w2")

    assert probe(smart).width == 1080 and probe(smart).height == 1920
    # The 70px box covers ~7% of the crop: fully inside the smart crop adds
    # ~14 to the mean brightness; the centred crop misses it entirely.
    assert _mean_brightness(smart, 3.0) > _mean_brightness(fixed, 3.0) + 8
