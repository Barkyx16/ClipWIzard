import subprocess

import numpy as np

from app.media.ffmpeg import probe
from app.media.render import RenderOptions, render_clip


def _make_stream_video(path):
    """Dark gameplay with a bright 'facecam' in the top-right corner."""
    w, h, fps, secs = 640, 360, 25, 3
    frame = np.full((h, w), 40, np.uint8)
    frame[20:110, 480:620] = 230  # facecam: x .75-.97, y .06-.31
    proc = subprocess.Popen([
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
        "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ], stdin=subprocess.PIPE)
    for _ in range(fps * secs):
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


def _rows(video, t=1.0):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
         "-vf", "scale=108:192,format=gray", "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(192, 108).mean(axis=1)


def test_facecam_on_top_gameplay_below(tmp_path):
    src = tmp_path / "stream.mp4"
    _make_stream_video(src)
    out = tmp_path / "fc.mp4"
    opts = RenderOptions(aspect="vertical_facecam", quality="fast", title="Clutch escape",
                         facecam={"x": 0.75, "y": 0.0556, "w": 0.21875, "h": 0.25})
    render_clip(src, out, 0.0, 2.0, 640, 360, 25, False, opts, tmp_path / "w")
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    rows = _rows(out)
    # Top panel is the bright facecam, the bottom is dark gameplay.
    assert rows[10:40].mean() > 180
    assert rows[120:180].mean() < 80
