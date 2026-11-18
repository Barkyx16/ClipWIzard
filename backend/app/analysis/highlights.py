"""Find the hype moments in a gameplay recording.

The detector fuses four cues, each measured *relative to the local baseline*
of the recording (so a loud stream with music doesn't drown everything):

* loudness spikes   - yelling, sirens, explosions
* transient bursts  - gunfire, impacts, crashes
* motion intensity  - high-speed driving, chaos on screen
* loudness jumps    - sudden "boom" moments

Peaks of the fused curve become clip candidates, which are then grown to
cover the surrounding action, padded with build-up/reaction time, snapped
away from hard scene cuts, de-overlapped, scored and labelled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .signals import Signals

LENGTH_PRESETS: dict[str, tuple[float, float]] = {
    # name: (min seconds, max seconds)
    "short": (12.0, 30.0),
    "medium": (25.0, 60.0),
    "long": (45.0, 90.0),
}

CATEGORIES = [
    "Shootout",
    "Big Impact",
    "Chase",
    "Hype Moment",
    "Action",
]


@dataclass
class DetectOptions:
    length: str = "short"
    max_clips: int = 12
    sensitivity: float = 0.5  # 0 = only the biggest moments, 1 = more clips

    @property
    def bounds(self) -> tuple[float, float]:
        return LENGTH_PRESETS.get(self.length, LENGTH_PRESETS["short"])


@dataclass
class Candidate:
    start: float
    end: float
    peak: float
    excitement: float
    score: float = 0.0
    category: str = "Action"
    signals: dict[str, float] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


# ------------------------------------------------------------ curve helpers


def smooth(x: np.ndarray, sigma_hops: float) -> np.ndarray:
    if len(x) == 0 or sigma_hops <= 0:
        return x.astype(np.float32)
    radius = max(1, int(3 * sigma_hops))
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma_hops) ** 2)
    k /= k.sum()
    padded = np.pad(x.astype(np.float64), radius, mode="edge")
    return np.convolve(padded, k, mode="valid").astype(np.float32)


def rolling_baseline(x: np.ndarray, window_hops: int) -> np.ndarray:
    """Approximate rolling median using block medians + interpolation."""
    n = len(x)
    if n == 0:
        return x.astype(np.float32)
    block = max(4, window_hops // 4)
    if n <= block * 2:
        return np.full(n, float(np.median(x)), dtype=np.float32)
    centers, medians = [], []
    for b0 in range(0, n, block):
        lo = max(0, b0 + block // 2 - window_hops // 2)
        hi = min(n, b0 + block // 2 + window_hops // 2)
        centers.append(b0 + block / 2)
        medians.append(float(np.median(x[lo:hi])))
    return np.interp(np.arange(n), centers, medians).astype(np.float32)


def robust_z(x: np.ndarray, window_hops: int, min_scale: float) -> np.ndarray:
    if len(x) == 0:
        return x.astype(np.float32)
    base = rolling_baseline(x, window_hops)
    resid = x - base
    mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826
    scale = max(mad, float(np.std(resid)) * 0.5, min_scale)
    return (resid / scale).astype(np.float32)


@dataclass
class Features:
    hop: float
    excitement: np.ndarray
    loud_z: np.ndarray
    onset_z: np.ndarray
    motion_z: np.ndarray
    jump_db: np.ndarray


def compute_features(sig: Signals) -> Features:
    hop = sig.hop
    n = len(sig)
    win = int(120 / hop)  # 2-minute local baseline

    motion_s = smooth(sig.motion, 0.5 / hop)
    motion_z = np.clip(robust_z(motion_s, win, 0.004), 0, 4)

    if sig.has_audio and n:
        loud_s = smooth(sig.loudness, 0.5 / hop)
        loud_z = np.clip(robust_z(loud_s, win, 1.5), 0, 4)
        onset_s = smooth(sig.onsets, 0.75 / hop)
        onset_z = np.clip(robust_z(onset_s, win, 1.0), 0, 4)
        # Biggest rise in loudness over the previous ~2 seconds.
        look = int(2.0 / hop)
        padded = np.pad(sig.loudness, (look, 0), mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, look + 1)
        jump_db = (sig.loudness - windows[:, :-1].min(axis=1)).astype(np.float32)
        jump_db = np.clip(jump_db, 0, 40)
        jump_term = np.clip((smooth(jump_db, 0.5 / hop) - 6.0) / 6.0, 0, 3)
        exc = 1.0 * loud_z + 0.9 * onset_z + 0.6 * motion_z + 0.6 * jump_term
    else:
        loud_z = np.zeros(n, np.float32)
        onset_z = np.zeros(n, np.float32)
        jump_db = np.zeros(n, np.float32)
        exc = 1.6 * motion_z

    exc = smooth(exc.astype(np.float32), 1.0 / hop)
    # Black / loading screens are never highlights.
    dark = smooth((sig.brightness < 0.04).astype(np.float32), 1.0 / hop)
    exc = exc * (1.0 - 0.85 * dark)
    return Features(hop=hop, excitement=exc.astype(np.float32), loud_z=loud_z,
                    onset_z=onset_z, motion_z=motion_z, jump_db=jump_db)


# ------------------------------------------------------------ detection


def _pick_peaks(exc: np.ndarray, min_gap: int, threshold: float, limit: int) -> list[int]:
    if len(exc) < 3:
        return []
    is_max = np.r_[False, (exc[1:-1] >= exc[:-2]) & (exc[1:-1] >= exc[2:]), False]
    cand = np.flatnonzero(is_max & (exc >= threshold))
    order = cand[np.argsort(-exc[cand])]
    chosen: list[int] = []
    for idx in order:
        if all(abs(int(idx) - c) >= min_gap for c in chosen):
            chosen.append(int(idx))
            if len(chosen) >= limit:
                break
    return chosen


def _grow_window(feat: Features, peak: int, min_len: float, max_len: float,
                 duration: float, cuts: np.ndarray) -> tuple[float, float]:
    exc, hop = feat.excitement, feat.hop
    n = len(exc)
    level = exc[peak] * 0.35
    max_pre, max_post = int(max_len * 0.7 / hop), int(max_len * 0.5 / hop)

    lo = peak
    while lo > 0 and peak - lo < max_pre and exc[lo - 1] > level:
        lo -= 1
    hi = peak
    while hi < n - 1 and hi - peak < max_post and exc[hi + 1] > level:
        hi += 1

    start = lo * hop - 3.0  # build-up
    end = (hi + 1) * hop + 2.0  # reaction
    peak_t = peak * hop

    length = end - start
    if length < min_len:
        extra = min_len - length
        start -= extra * 0.6
        end += extra * 0.4
    elif length > max_len:
        # Keep the peak about 65% of the way through the clip.
        start = max(start, peak_t - max_len * 0.65)
        end = start + max_len

    # Shift back inside the recording if we ran off either edge.
    if start < 0:
        end = min(duration, end - start)
        start = 0.0
    if end > duration:
        start = max(0.0, start - (end - duration))
        end = duration

    # Avoid opening/closing on a flash of an unrelated scene.
    cut_idx = np.flatnonzero(cuts > 0)
    if len(cut_idx):
        cut_t = cut_idx * hop
        near_start = cut_t[(cut_t > start) & (cut_t < start + 1.5) & (cut_t < peak_t - 2)]
        if len(near_start):
            start = float(near_start[-1])
        near_end = cut_t[(cut_t < end) & (cut_t > end - 1.5) & (cut_t > peak_t + 1)]
        if len(near_end):
            end = float(near_end[0])
    return round(start, 2), round(end, 2)


def _resolve_overlaps(cands: list[Candidate], max_len: float) -> list[Candidate]:
    # Highest excitement wins; lower ones get merged or trimmed.
    cands = sorted(cands, key=lambda c: -c.excitement)
    kept: list[Candidate] = []
    for c in cands:
        drop = False
        for k in kept:
            if c.start < k.end and k.start < c.end:
                merged_start, merged_end = min(c.start, k.start), max(c.end, k.end)
                if merged_end - merged_start <= max_len:
                    k.start, k.end = merged_start, merged_end
                    drop = True
                    break
                # Trim the weaker clip so it no longer overlaps.
                if c.peak < k.start:
                    c.end = k.start
                else:
                    c.start = k.end
                if c.end - c.start < 6.0 or not (c.start <= c.peak <= c.end):
                    drop = True
                    break
        if not drop:
            kept.append(c)
    return kept


def _summarize(feat: Features, sig: Signals, c: Candidate) -> None:
    hop = feat.hop
    a, b = int(c.start / hop), max(int(c.start / hop) + 1, int(c.end / hop))
    p = int(c.peak / hop)
    near = slice(max(0, p - int(2 / hop)), p + int(2 / hop) + 1)

    onset_near = float(np.mean(sig.onsets[near])) if sig.has_audio else 0.0
    onset_z_near = float(np.mean(feat.onset_z[near]))
    jump_max = float(np.max(feat.jump_db[a:b])) if b > a else 0.0
    motion_z = feat.motion_z[a:b]
    high_motion_secs = float(np.sum(motion_z > 1.2) * hop)
    loud_z_mean = float(np.mean(feat.loud_z[a:b])) if b > a else 0.0

    c.signals = {
        "audio": round(float(np.mean(feat.loud_z[near])) / 4.0, 3),
        "gunfire": round(onset_z_near / 4.0, 3),
        "motion": round(float(np.mean(motion_z)) / 4.0, 3) if len(motion_z) else 0.0,
        "impact_db": round(jump_max, 1),
        "onset_rate": round(onset_near, 2),
        "excitement": round(c.excitement, 3),
    }

    if onset_near >= 3.0 and onset_z_near >= 1.5:
        c.category = "Shootout"
    elif high_motion_secs >= 6.0 and float(np.mean(motion_z)) >= 1.0:
        # Sustained motion wins over a one-off loudness jump (engine revving up).
        c.category = "Chase"
    elif jump_max >= 15.0:
        c.category = "Big Impact"
    elif loud_z_mean >= 1.2:
        c.category = "Hype Moment"
    else:
        c.category = "Action"


def detect_highlights(sig: Signals, duration: float, opts: DetectOptions) -> tuple[Features, list[Candidate]]:
    feat = compute_features(sig)
    exc = feat.excitement
    if len(exc) == 0:
        return feat, []
    min_len, max_len = opts.bounds
    duration = max(duration, len(exc) * feat.hop)

    sens = float(np.clip(opts.sensitivity, 0.0, 1.0))
    pct = 90 - 25 * sens  # 90th percentile (strict) .. 65th (generous)
    floor = 1.6 - 0.9 * sens
    threshold = max(float(np.percentile(exc, pct)), floor)

    min_gap = int(min_len / feat.hop)
    peaks = _pick_peaks(exc, min_gap, threshold, limit=max(1, opts.max_clips) * 2)

    cands = []
    for p in peaks:
        start, end = _grow_window(feat, p, min_len, max_len, duration, sig.cuts)
        if end - start < 4.0:
            continue
        cands.append(Candidate(start=start, end=end, peak=round(p * feat.hop, 2),
                               excitement=float(exc[p])))

    cands = _resolve_overlaps(cands, max_len)
    cands = sorted(cands, key=lambda c: -c.excitement)[: opts.max_clips]

    top = max((c.excitement for c in cands), default=1.0) or 1.0
    for c in cands:
        rel = c.excitement / top
        absolute = 1.0 - math.exp(-c.excitement / 3.0)
        c.score = round(100.0 * (0.55 * rel + 0.45 * absolute), 1)
        _summarize(feat, sig, c)
    return feat, cands


def timeline(feat: Features, sig: Signals, max_points: int = 1200) -> tuple[float, dict[str, list[float]]]:
    """Downsample curves for the UI heat-strip (max-pooled, normalised 0..1)."""
    n = len(feat.excitement)
    if n == 0:
        return feat.hop, {"excitement": [], "audio": [], "motion": []}
    group = max(1, math.ceil(n / max_points))
    pad = (-n) % group

    def pool(x: np.ndarray) -> list[float]:
        x = np.pad(x.astype(np.float32), (0, pad), mode="edge").reshape(-1, group).max(axis=1)
        top = float(x.max()) or 1.0
        return [round(float(v) / top, 3) for v in x]

    return feat.hop * group, {
        "excitement": pool(feat.excitement),
        "audio": pool(feat.loud_z + feat.onset_z),
        "motion": pool(feat.motion_z),
    }
