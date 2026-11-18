"""Turn noisy per-frame "where is the action" estimates into a smooth
virtual-camera path for vertical crops.

The path is centred unless the detector is confident the action is off to one
side; it is heavily smoothed, pans no faster than ``MAX_PAN_PER_SEC`` (in
frame widths), and moves slightly *ahead* of the action so the subject isn't
cut off while the camera catches up.
"""

from __future__ import annotations

import numpy as np

from .highlights import smooth

MAX_PAN_PER_SEC = 0.25
SMOOTH_SECONDS = 1.5


def _rate_limit(x: np.ndarray, max_step: float) -> np.ndarray:
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] + np.clip(out[i] - out[i - 1], -max_step, max_step)
    return out


def camera_path(focus_x: np.ndarray, focus_conf: np.ndarray, hop: float) -> np.ndarray:
    """Per-hop horizontal crop centre in 0..1."""
    if len(focus_x) == 0:
        return np.zeros(0, np.float32)
    conf = smooth(np.clip(focus_conf, 0, 1), 0.75 / hop)
    target = 0.5 + (np.clip(focus_x, 0, 1) - 0.5) * conf
    target = smooth(target, SMOOTH_SECONDS / hop)
    step = MAX_PAN_PER_SEC * hop
    fwd = _rate_limit(target, step)
    bwd = _rate_limit(target[::-1], step)[::-1]  # anticipates upcoming moves
    return np.clip((fwd + bwd) / 2.0, 0.0, 1.0).astype(np.float32)


def keyframes(path: np.ndarray, hop: float, start: float, end: float,
              every: float = 0.5) -> list[tuple[float, float]]:
    """(time since clip start, centre) pairs covering [start, end]."""
    if len(path) == 0:
        return [(0.0, 0.5)]
    out = []
    t = 0.0
    duration = max(0.0, end - start)
    while True:
        idx = min(len(path) - 1, max(0, int(round((start + t) / hop))))
        out.append((round(t, 3), float(path[idx])))
        if t >= duration:
            break
        t = min(duration, t + every)
    return out


def crop_x_expression(keys: list[tuple[float, float]], src_w: int, crop_w: int) -> str:
    """Piecewise-linear ffmpeg expression giving the crop's left edge for time t."""
    max_x = max(0, src_w - crop_w)

    def px(c: float) -> float:
        return float(np.clip(c * src_w - crop_w / 2, 0, max_x))

    if len(keys) == 1:
        return f"{px(keys[0][1]):.1f}"
    # Build from the end so nesting depth equals the number of segments.
    expr = f"{px(keys[-1][1]):.1f}"
    for (t0, c0), (t1, c1) in reversed(list(zip(keys, keys[1:]))):
        x0, x1 = px(c0), px(c1)
        span = max(1e-3, t1 - t0)
        seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{span:.3f}"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return expr
