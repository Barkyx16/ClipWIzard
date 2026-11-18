"""Background jobs: analysing uploaded videos and rendering clips."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import db
from .analysis import ai
from .analysis.highlights import DetectOptions, detect_highlights, timeline
from .analysis.smartcrop import camera_path, keyframes
from .analysis.signals import MotionAccumulator, build_signals
from .config import get_settings
from .media.ffmpeg import FFmpegError, decode_for_analysis, extract_frame
from .media.render import RenderOptions, render_clip

log = logging.getLogger(__name__)


def _fmt_ts(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


HEURISTIC_TITLES = {
    "Shootout": "Shootout erupts",
    "Big Impact": "Massive impact",
    "Chase": "High-speed chase",
    "Hype Moment": "Hype moment",
    "Action": "Action moment",
}

DEFAULT_TAGS = ["gta6", "gtavi", "gaming", "gta", "clips"]


class _Throttle:
    """Avoid hammering SQLite with progress updates."""

    def __init__(self, video_id: str, lo: float, hi: float, stage: str):
        self.video_id, self.lo, self.hi, self.stage = video_id, lo, hi, stage
        self._last = 0.0
        db.update_video(video_id, stage=stage, progress=lo)

    def __call__(self, frac: float) -> None:
        now = time.monotonic()
        if now - self._last < 0.5 and frac < 1.0:
            return
        self._last = now
        db.update_video(self.video_id, progress=round(self.lo + (self.hi - self.lo) * frac, 4))


def analyze_video(video_id: str) -> None:
    settings = get_settings()
    video = db.get_video(video_id)
    if video is None:
        return
    src = settings.uploads_dir / video["filename"]
    work = settings.work_dir / video_id
    work.mkdir(parents=True, exist_ok=True)
    opts_raw: dict[str, Any] = video.get("settings") or {}
    opts = DetectOptions(
        length=str(opts_raw.get("length", "short")),
        max_clips=int(opts_raw.get("max_clips", 12)),
        sensitivity=float(opts_raw.get("sensitivity", 0.5)),
    )
    use_ai = bool(opts_raw.get("use_ai", True)) and settings.ai_enabled

    db.update_video(video_id, status="analyzing", error=None, progress=0.0)
    try:
        duration = float(video["duration"])
        audio_path = work / "audio.s16le"
        acc = MotionAccumulator()
        decode_for_analysis(
            src, audio_path, bool(video["has_audio"]), duration, acc.feed,
            progress=_Throttle(video_id, 0.0, 0.7, "Scanning gameplay for action"),
        )

        _Throttle(video_id, 0.7, 0.75, "Listening for gunfire and explosions")
        sig = build_signals(audio_path, acc, bool(video["has_audio"]))
        audio_path.unlink(missing_ok=True)

        _Throttle(video_id, 0.75, 0.8, "Picking the best moments")
        feat, cands = detect_highlights(sig, duration, opts)
        hop, curves = timeline(feat, sig)
        if sig.focus_x is not None and len(sig.focus_x):
            path = camera_path(sig.focus_x, sig.focus_conf, sig.hop)
            save_camera_path(video_id, path, sig.hop)
            # 1 Hz copy for the editor's live crop preview.
            step = max(1, int(round(1.0 / sig.hop)))
            curves["crop_hop"] = sig.hop * step  # type: ignore[assignment]
            curves["crop_path"] = [round(float(v), 3) for v in path[::step]]
        db.save_timeline(video_id, hop, curves)

        ai_results: dict[int, dict[str, Any]] = {}
        if use_ai and cands:
            ai_results = ai.enrich(
                src, cands, work,
                progress=_Throttle(video_id, 0.8, 0.95, "AI is watching your clips"),
            )

        thumbs = _Throttle(video_id, 0.95, 1.0, "Generating thumbnails")
        rows = []
        for i, c in enumerate(cands):
            hid = db.new_id()
            thumb_name = f"{video_id}_{hid}.jpg"
            try:
                extract_frame(src, c.peak, settings.thumbs_dir / thumb_name, width=480)
            except FFmpegError:
                thumb_name = None
            res = ai_results.get(i)
            row = {
                "id": hid,
                "start": c.start,
                "end": c.end,
                "peak": c.peak,
                "score": c.score,
                "category": c.category,
                "title": f"{HEURISTIC_TITLES.get(c.category, 'Highlight')} at {_fmt_ts(c.peak)}",
                "description": None,
                "caption": None,
                "hashtags": DEFAULT_TAGS,
                "signals": c.signals,
                "thumbnail": thumb_name,
                "ai_enriched": False,
            }
            if res:
                hype = max(0, min(100, int(res.get("hype_score", 50))))
                score = 0.5 * c.score + 0.5 * hype
                if not res.get("is_gameplay", True):
                    score *= 0.3
                row.update(
                    score=round(score, 1),
                    category=res.get("category") or c.category,
                    title=(res.get("title") or row["title"]).strip()[:90],
                    description=(res.get("description") or "").strip()[:400] or None,
                    caption=(res.get("caption") or "").strip()[:500] or None,
                    hashtags=ai.clean_hashtags(res.get("hashtags") or []) or DEFAULT_TAGS,
                    ai_enriched=True,
                    signals={**c.signals, "ai_hype": hype, "is_gameplay": bool(res.get("is_gameplay", True))},
                )
            rows.append(row)
            thumbs((i + 1) / max(1, len(cands)))

        rows.sort(key=lambda r: -r["score"])
        for rank, r in enumerate(rows):
            r["rank"] = rank
        db.replace_highlights(video_id, rows)
        db.update_video(
            video_id,
            status="ready",
            stage="Done",
            progress=1.0,
            ai_used=bool(ai_results),
            thumbnail=rows[0]["thumbnail"] if rows else video.get("thumbnail"),
        )
    except Exception as e:  # report any failure to the UI
        log.exception("Analysis failed for %s", video_id)
        db.update_video(video_id, status="failed", stage="Failed", error=str(e)[:800])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render(clip_id: str) -> None:
    settings = get_settings()
    clip = db.get_clip(clip_id)
    if clip is None:
        return
    video = db.get_video(clip["video_id"])
    if video is None:
        db.update_clip(clip_id, status="failed", error="Source video was deleted")
        return
    src = settings.uploads_dir / video["filename"]
    work = settings.work_dir / f"clip_{clip_id}"
    out_name = f"{clip_id}.mp4"
    out = settings.clips_dir / out_name
    o = clip.get("options") or {}
    opts = RenderOptions(
        aspect=str(o.get("aspect", "vertical_blur")),
        crop_x=float(o.get("crop_x", 0.5)),
        title=(o.get("title") or None) if o.get("title_overlay") else None,
        quality=str(o.get("quality", "high")),
    )
    if opts.aspect == "vertical_smart":
        loaded = load_camera_path(video["id"])
        if loaded is not None:
            path, hop = loaded
            dur = float(clip["end"]) - float(clip["start"])
            opts.crop_keys = keyframes(path, hop, float(clip["start"]), float(clip["end"]),
                                       every=max(0.5, dur / 80))
    db.update_clip(clip_id, status="rendering", progress=0.0, error=None)
    last = [0.0]

    def progress(frac: float) -> None:
        now = time.monotonic()
        if now - last[0] >= 0.5 or frac >= 1.0:
            last[0] = now
            db.update_clip(clip_id, progress=round(frac, 4))

    try:
        render_clip(
            src, out, float(clip["start"]), float(clip["end"]),
            int(video["width"]), int(video["height"]), float(video["fps"] or 30),
            bool(video["has_audio"]), opts, work, settings.font_path, progress,
        )
        db.update_clip(clip_id, status="done", progress=1.0, filename=out_name,
                       size_bytes=out.stat().st_size)
    except Exception as e:
        log.exception("Render failed for clip %s", clip_id)
        db.update_clip(clip_id, status="failed", error=str(e)[:800])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def save_camera_path(video_id: str, path: np.ndarray, hop: float) -> None:
    np.savez_compressed(get_settings().analysis_dir / f"{video_id}.npz", path=path, hop=hop)


def load_camera_path(video_id: str) -> tuple[np.ndarray, float] | None:
    f = get_settings().analysis_dir / f"{video_id}.npz"
    if not f.exists():
        return None
    with np.load(f) as data:
        return data["path"].astype(np.float32), float(data["hop"])


def remove_video_files(video: dict[str, Any]) -> None:
    settings = get_settings()
    (settings.uploads_dir / video["filename"]).unlink(missing_ok=True)
    (settings.analysis_dir / f"{video['id']}.npz").unlink(missing_ok=True)
    for h in db.list_highlights(video["id"]):
        if h.get("thumbnail"):
            (settings.thumbs_dir / h["thumbnail"]).unlink(missing_ok=True)
    for c in db.list_clips(video["id"]):
        if c.get("filename"):
            (settings.clips_dir / c["filename"]).unlink(missing_ok=True)
    shutil.rmtree(settings.work_dir / video["id"], ignore_errors=True)


def safe_path(base: Path, name: str) -> Path | None:
    p = (base / name).resolve()
    return p if p.is_relative_to(base.resolve()) and p.exists() else None
