"""Turn raw decoded media into per-hop feature curves.

Every curve is sampled on the same grid: one value per ``HOP`` seconds.

* ``loudness``   - RMS loudness in dBFS
* ``onsets``     - sharp transient onsets per second (gunfire, impacts)
* ``motion``     - mean absolute frame difference, 0..1 (driving, chaos)
* ``brightness`` - mean luma, 0..1 (used to spot black/loading screens)
* ``cuts``       - 1.0 where a hard scene cut happens
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..media.ffmpeg import ANALYSIS_FPS, ANALYSIS_H, ANALYSIS_W, AUDIO_SR

HOP = 1.0 / ANALYSIS_FPS  # 0.25 s
SUBFRAME = 0.01  # 10 ms energy frames for transient detection
CUT_THRESHOLD = 0.22


@dataclass
class Signals:
    hop: float
    loudness: np.ndarray
    onsets: np.ndarray
    motion: np.ndarray
    brightness: np.ndarray
    cuts: np.ndarray
    has_audio: bool

    def __len__(self) -> int:
        return len(self.motion)


class MotionAccumulator:
    """Collects motion/brightness from streamed grayscale frames."""

    def __init__(self) -> None:
        self._prev: np.ndarray | None = None
        self.motion: list[np.ndarray] = []
        self.brightness: list[np.ndarray] = []

    def feed(self, raw: bytes) -> None:
        frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, ANALYSIS_H, ANALYSIS_W)
        frames = frames.astype(np.float32) / 255.0
        if self._prev is None:
            prev = frames[:1]
        else:
            prev = self._prev[None]
        stacked = np.concatenate([prev, frames], axis=0)
        diffs = np.abs(np.diff(stacked, axis=0)).mean(axis=(1, 2))
        self.motion.append(diffs)
        self.brightness.append(frames.mean(axis=(1, 2)))
        self._prev = frames[-1]

    def result(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.motion:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        return np.concatenate(self.motion), np.concatenate(self.brightness)


def audio_features(audio_path: Path, n_hops: int) -> tuple[np.ndarray, np.ndarray]:
    """Loudness (dBFS) and onset rate per hop from a mono s16le file."""
    loud = np.full(n_hops, -90.0, dtype=np.float32)
    onsets = np.zeros(n_hops, dtype=np.float32)
    if not audio_path.exists() or audio_path.stat().st_size < 2:
        return loud, onsets

    samples = np.memmap(audio_path, dtype=np.int16, mode="r")
    hop_n = int(AUDIO_SR * HOP)
    sub_n = int(AUDIO_SR * SUBFRAME)
    subs_per_hop = hop_n // sub_n
    total_hops = min(n_hops, len(samples) // hop_n)
    chunk_hops = 2400  # 10 minutes per chunk keeps memory flat
    prev_tail = np.full(3, -90.0, dtype=np.float32)

    for h0 in range(0, total_hops, chunk_hops):
        h1 = min(total_hops, h0 + chunk_hops)
        x = np.asarray(samples[h0 * hop_n : h1 * hop_n], dtype=np.float32) / 32768.0
        frames = x.reshape(h1 - h0, hop_n)
        rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
        loud[h0:h1] = 20.0 * np.log10(rms + 1e-9)

        # Transients: high-passed energy in 10ms frames jumping sharply above
        # the recent past. Gunfire and impacts are broadband and impulsive.
        hp = np.diff(x, prepend=x[:1])
        sub = hp[: (h1 - h0) * subs_per_hop * sub_n].reshape(-1, sub_n)
        e_db = 10.0 * np.log10(np.mean(sub**2, axis=1) + 1e-10)
        padded = np.concatenate([prev_tail, e_db])
        recent = np.maximum.reduce([padded[2:-1], padded[1:-2], padded[:-3]])
        is_onset = (e_db - recent > 10.0) & (e_db > -50.0)
        counts = is_onset.reshape(h1 - h0, subs_per_hop).sum(axis=1)
        onsets[h0:h1] = counts / HOP
        prev_tail = padded[-3:]

    del samples
    return loud, onsets


def build_signals(audio_path: Path | None, motion_acc: MotionAccumulator,
                  has_audio: bool) -> Signals:
    motion, brightness = motion_acc.result()
    n = len(motion)
    if has_audio and audio_path is not None:
        loud, onsets = audio_features(audio_path, n)
    else:
        loud = np.full(n, -90.0, dtype=np.float32)
        onsets = np.zeros(n, dtype=np.float32)
    cuts = (motion > CUT_THRESHOLD).astype(np.float32)
    return Signals(hop=HOP, loudness=loud, onsets=onsets, motion=motion.astype(np.float32),
                   brightness=brightness.astype(np.float32), cuts=cuts, has_audio=has_audio)
