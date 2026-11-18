"""Generate a synthetic "gameplay" video with known action beats.

Used by the test-suite and handy for trying the app without real footage:

    python -m app.demo demo.mp4

Timeline (default 90 s):
  0-25   calm cruising            (quiet, slow drift)
  25-31  shootout                 (rapid gunshots, muzzle flashes, shake)
  31-52  calm
  52-56  explosion                (huge boom, bright flash, big shake)
  56-68  calm
  68-80  car chase                (engine roar, fast scrolling scenery)
  80-90  calm
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

W, H, FPS, SR = 320, 180, 25, 22050
BEATS = {"shootout": (25.0, 31.0), "explosion": (52.0, 56.0), "chase": (68.0, 80.0)}


def _audio(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(duration * SR)
    t = np.arange(n) / SR
    a = rng.normal(0, 0.008, n) + 0.015 * np.sin(2 * np.pi * 220 * t)  # quiet ambience

    s0, s1 = BEATS["shootout"]
    for shot in np.arange(s0, s1, 1 / 8):
        i = int((shot + rng.uniform(-0.02, 0.02)) * SR)
        k = np.arange(int(0.06 * SR))
        a[i : i + len(k)] += rng.normal(0, 0.6, len(k)) * np.exp(-k / (0.012 * SR))

    e0, _ = BEATS["explosion"]
    i = int(e0 * SR)
    k = np.arange(int(2.5 * SR))
    boom = rng.normal(0, 0.9, len(k)) * np.exp(-k / (0.6 * SR))
    boom += 0.5 * np.sin(2 * np.pi * 45 * k / SR) * np.exp(-k / (0.8 * SR))
    a[i : i + len(k)] += boom

    c0, c1 = BEATS["chase"]
    i0, i1 = int(c0 * SR), int(c1 * SR)
    tc = t[i0:i1]
    freq = 90 + 30 * np.sin(2 * np.pi * 0.3 * tc)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    engine = 0.22 * (2 * ((phase / (2 * np.pi)) % 1.0) - 1)  # sawtooth
    a[i0:i1] += engine + rng.normal(0, 0.05, len(tc))
    return np.clip(a, -1, 1)


def _texture(rng: np.random.Generator) -> np.ndarray:
    base = rng.integers(0, 255, (H // 6 + 1, (W * 3) // 6 + 1), dtype=np.uint8)
    tex = np.kron(base, np.ones((6, 6), dtype=np.uint8))[:H, : W * 3].astype(np.float32)
    grad = np.linspace(40, 120, H, dtype=np.float32)[:, None]
    return 0.35 * tex + grad


def _frame(i: int, tex: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    t = i / FPS
    offset = int(t * 4)  # slow drift while calm
    shake = 0
    flash = 0.0
    tint = np.array([1.0, 1.0, 1.0], dtype=np.float32)

    s0, s1 = BEATS["shootout"]
    e0, e1 = BEATS["explosion"]
    c0, c1 = BEATS["chase"]
    if s0 <= t < s1:
        shake = int(rng.integers(-6, 7))
        flash = 0.5 if rng.random() < 0.4 else 0.0
    elif e0 <= t < e1:
        k = (t - e0) / (e1 - e0)
        shake = int(rng.integers(-18, 19) * (1 - k))
        flash = 1.6 * (1 - k)
        tint = np.array([1.0, 0.6, 0.25], dtype=np.float32)
    elif c0 <= t < c1:
        offset = int(c0 * 4 + (t - c0) * 300)  # fast scrolling scenery

    x = (offset + shake) % (tex.shape[1] - W)
    gray = tex[:, x : x + W]
    rgb = np.repeat(gray[:, :, None], 3, axis=2) * np.array([0.8, 0.9, 1.1], dtype=np.float32)
    if flash:
        rgb = rgb + 255 * flash * tint * 0.5
    return np.clip(rgb, 0, 255).astype(np.uint8)


def make_demo_video(out: Path, duration: float = 90.0, seed: int = 7) -> Path:
    rng = np.random.default_rng(seed)
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        pcm = (_audio(duration, rng) * 32767).astype("<i2")
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())

        cmd = [
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0",
            "-i", str(wav),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(out),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert proc.stdin is not None
        tex = _texture(rng)
        for i in range(int(duration * FPS)):
            proc.stdin.write(_frame(i, tex, rng).tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed to build the demo video")
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo.mp4")
    make_demo_video(target)
    print(f"Wrote {target}")
