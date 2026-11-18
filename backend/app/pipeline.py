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
from .media.ffmpeg import FFmpegError, SpriteSpec, decode_for_analysis, extract_frame
from .media import captions, importer
from .media.ffmpeg import probe
from .media.render import RenderOptions, join_segments, output_size, render_clip

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
        sprite_spec = SpriteSpec.for_duration(work / "sprite_%03d.jpg", duration)
        decode_for_analysis(
            src, audio_path, bool(video["has_audio"]), duration, acc.feed,
            progress=_Throttle(video_id, 0.0, 0.7, "Scanning gameplay for action"),
            sprites=sprite_spec,
        )
        sprite_meta = _publish_sprites(video_id, sprite_spec, duration)

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
        if sprite_meta:
            curves["sprites"] = sprite_meta  # type: ignore[assignment]
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


def import_video(video_id: str) -> None:
    """Download a linked video, then analyse it like an upload."""
    settings = get_settings()
    video = db.get_video(video_id)
    if video is None or not video.get("import_url"):
        return
    url = video["import_url"]
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        kind, source = importer.classify(url)
        progress = _Throttle(video_id, 0.0, 1.0, f"Downloading from {source}")
        db.update_video(video_id, status="downloading", error=None)
        stem = settings.uploads_dir / video_id
        title = None
        if kind == "platform":
            path, title = importer.download_platform(url, stem, limit, progress)
        else:
            ext = Path(url.split("?", 1)[0]).suffix.lower() or ".mp4"
            path = importer.download_direct(url, stem.with_suffix(ext), limit, progress)
        info = probe(path)
        if info.duration > importer.max_import_seconds():
            path.unlink(missing_ok=True)
            raise importer.ImportFailed("That video is too long to import")
        name = video["original_name"]
        if title:
            clean = "".join(ch for ch in title if ch.isprintable()).strip()[:110]
            name = f"{clean}{path.suffix}" if clean else name
        db.update_video(
            video_id, filename=path.name, original_name=name, size_bytes=path.stat().st_size,
            duration=info.duration, width=info.width, height=info.height, fps=info.fps,
            has_audio=info.has_audio, status="queued", stage="Queued", progress=0.0,
        )
    except importer.ImportFailed as e:
        db.update_video(video_id, status="failed", stage="Import failed", error=str(e))
        return
    except Exception as e:
        log.exception("Import failed for %s", video_id)
        db.update_video(video_id, status="failed", stage="Import failed",
                        error=f"Import failed: {e}"[:800])
        return
    analyze_video(video_id)


class _Progress:
    """Throttled clip progress, mapped into the current [lo, hi] span."""

    def __init__(self, clip_id: str):
        self.clip_id = clip_id
        self.lo, self.hi = 0.0, 1.0
        self._last = 0.0

    def span(self, lo: float, hi: float) -> "_Progress":
        self.lo, self.hi = lo, hi
        self(0.0)
        return self

    def __call__(self, frac: float) -> None:
        now = time.monotonic()
        if now - self._last >= 0.5 or frac >= 1.0:
            self._last = now
            db.update_clip(self.clip_id, progress=round(self.lo + (self.hi - self.lo) * frac, 4))


def _render_options(video: dict[str, Any], o: dict[str, Any], start: float, end: float,
                    title: str | None) -> RenderOptions:
    opts = RenderOptions(
        aspect=str(o.get("aspect", "vertical_blur")),
        crop_x=float(o.get("crop_x", 0.5)),
        title=(title or None) if o.get("title_overlay") else None,
        quality=str(o.get("quality", "high")),
        facecam=o.get("facecam") or None,
        watermark=(o.get("watermark") or "").strip() or None,
        normalize=bool(o.get("normalize", True)),
    )
    if opts.aspect == "vertical_facecam" and not opts.facecam:
        opts.aspect = "vertical_smart"  # no facecam marked: fall back to a smart crop
    if opts.aspect in ("vertical_smart", "vertical_facecam"):
        loaded = load_camera_path(video["id"])
        if loaded is not None:
            path, hop = loaded
            opts.crop_keys = keyframes(path, hop, start, end, every=max(0.5, (end - start) / 80))
    return opts


def _add_captions(src: Path, video: dict[str, Any], opts: RenderOptions, o: dict[str, Any],
                  start: float, end: float, work: Path, tag: str) -> tuple[str | None, str | None]:
    """Transcribe [start, end] (or use the user's edited words) and attach burned-in captions.

    Returns (transcript, warning).
    """
    edited = o.get("caption_words") if tag == "main" else None
    if edited:
        words = [captions.Word(float(w["start"]), float(w["end"]), str(w["text"])) for w in edited]
    else:
        try:
            words = captions.transcribe(src, start, end, work)
        except captions.CaptionError as e:
            return None, f"Captions skipped: {e}"[:300]
    if not words:
        return None, "No speech found for captions"
    out_w, out_h = output_size(opts.aspect, int(video["width"]), int(video["height"]))
    ass = work / f"captions_{tag}.ass"
    position = float(o.get("caption_position") or (0.85 if opts.aspect == "landscape" else 0.72))
    ass.write_text(captions.build_ass(
        words, out_w, out_h, end - start, position=min(0.92, max(0.3, position)),
        style=str(o.get("caption_style") or "bold"),
    ), encoding="utf-8")
    opts.captions_ass = ass
    return captions.transcript_text(words) or None, None


def _render_piece(src: Path, out: Path, video: dict[str, Any], o: dict[str, Any], start: float,
                  end: float, title: str | None, work: Path, prog: _Progress, lo: float,
                  hi: float, tag: str) -> tuple[str | None, str | None]:
    settings = get_settings()
    opts = _render_options(video, o, start, end, title)
    transcript = warning = None
    render_lo = lo
    if o.get("captions"):
        prog.span(lo, lo + (hi - lo) * 0.3)
        transcript, warning = _add_captions(src, video, opts, o, start, end, work, tag)
        render_lo = lo + (hi - lo) * 0.3
    prog.span(render_lo, hi)
    render_clip(src, out, start, end, int(video["width"]), int(video["height"]),
                float(video["fps"] or 30), bool(video["has_audio"]), opts, work / f"r_{tag}",
                settings.font_path, prog)
    return transcript, warning


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
    prog = _Progress(clip_id)
    db.update_clip(clip_id, status="rendering", progress=0.0, error=None, warning=None)
    try:
        work.mkdir(parents=True, exist_ok=True)
        if o.get("kind") == "montage":
            transcript, warning = _render_montage(src, out, video, o, work, prog)
        elif o.get("replay"):
            transcript, warning = _render_with_replay(src, out, clip, video, o, work, prog)
        else:
            transcript, warning = _render_piece(
                src, out, video, o, float(clip["start"]), float(clip["end"]), o.get("title"),
                work, prog, 0.0, 1.0, "main",
            )
        db.update_clip(clip_id, status="done", progress=1.0, filename=out_name,
                       size_bytes=out.stat().st_size, transcript=transcript, warning=warning)
    except Exception as e:
        log.exception("Render failed for clip %s", clip_id)
        db.update_clip(clip_id, status="failed", error=str(e)[:800])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def transcribe_range(transcript_id: str) -> None:
    """Background job: transcribe a range so the user can review/edit captions."""
    settings = get_settings()
    t = db.get_transcript(transcript_id)
    if t is None:
        return
    video = db.get_video(t["video_id"])
    if video is None:
        return
    work = settings.work_dir / f"tr_{transcript_id}"
    db.update_transcript(transcript_id, status="running", error=None)
    try:
        words = captions.transcribe(settings.uploads_dir / video["filename"], float(t["start"]),
                                    float(t["end"]), work)
        db.update_transcript(transcript_id, status="done",
                             words=[{"start": round(w.start, 3), "end": round(w.end, 3), "text": w.text}
                                    for w in words])
    except captions.CaptionError as e:
        db.update_transcript(transcript_id, status="failed", error=str(e)[:300])
    except Exception as e:
        log.exception("Transcription failed for %s", transcript_id)
        db.update_transcript(transcript_id, status="failed", error=f"Transcription failed: {e}"[:300])
    finally:
        shutil.rmtree(work, ignore_errors=True)


REPLAY_SECONDS = 3.0


def _replay_window(clip: dict[str, Any], start: float, end: float) -> tuple[float, float]:
    """Three seconds around the clip's peak (highlight peak, else loudest moment, else middle)."""
    peak = None
    if clip.get("highlight_id"):
        h = db.get_highlight(clip["highlight_id"])
        if h and start <= h["peak"] <= end:
            peak = float(h["peak"])
    if peak is None:
        t = db.get_timeline(clip["video_id"])
        exc = (t or {}).get("data", {}).get("excitement") if t else None
        if exc:
            hop = float(t["hop"])  # type: ignore[index]
            a, b = int(start / hop), max(int(start / hop) + 1, int(end / hop))
            window = exc[a:b]
            if window:
                peak = (a + max(range(len(window)), key=window.__getitem__) + 0.5) * hop
    if peak is None:
        peak = (start + end) / 2
    r0 = max(start, peak - REPLAY_SECONDS * 0.6)
    r1 = min(end, r0 + REPLAY_SECONDS)
    return r0, r1


def _render_with_replay(src: Path, out: Path, clip: dict[str, Any], video: dict[str, Any],
                        o: dict[str, Any], work: Path, prog: _Progress) -> tuple[str | None, str | None]:
    """The clip, a white flash, then its peak again at half speed."""
    start, end = float(clip["start"]), float(clip["end"])
    main = work / "main.mp4"
    transcript, warning = _render_piece(src, main, video, o, start, end, o.get("title"), work, prog,
                                        0.0, 0.7, "main")
    r0, r1 = _replay_window(clip, start, end)
    replay = work / "replay.mp4"
    replay_opts = {**o, "captions": False, "title_overlay": True}
    opts = _render_options(video, replay_opts, r0, r1, "SLOW-MO REPLAY")
    opts.speed = 0.5
    prog.span(0.7, 0.9)
    render_clip(src, replay, r0, r1, int(video["width"]), int(video["height"]),
                float(video["fps"] or 30), bool(video["has_audio"]), opts, work / "r_replay",
                get_settings().font_path, prog)
    prog.span(0.9, 1.0)
    join_segments([main, replay], out, "fadewhite", bool(video["has_audio"]), work, prog, fade=0.25)
    return transcript, warning


def _render_montage(src: Path, out: Path, video: dict[str, Any], o: dict[str, Any], work: Path,
                    prog: _Progress) -> tuple[str | None, str | None]:
    segments = o.get("segments") or []
    if not segments:
        raise ValueError("A montage needs at least one moment")
    n = len(segments)
    parts: list[Path] = []
    transcripts: list[str] = []
    warnings: set[str] = set()
    for i, seg in enumerate(segments):
        part = work / f"seg_{i:02d}.mp4"
        t, w = _render_piece(src, part, video, o, float(seg["start"]), float(seg["end"]),
                             seg.get("title"), work, prog, 0.9 * i / n, 0.9 * (i + 1) / n, f"s{i}")
        parts.append(part)
        if t:
            transcripts.append(t)
        if w:
            warnings.add(w)
    prog.span(0.9, 1.0)
    join_segments(parts, out, str(o.get("transition", "fade")), bool(video["has_audio"]), work, prog)
    return ("\n\n".join(transcripts) or None), ("; ".join(sorted(warnings)) or None)


def _publish_sprites(video_id: str, spec: SpriteSpec, duration: float) -> dict[str, Any] | None:
    """Move contact sheets into the (workspace-protected) thumbs folder."""
    thumbs = get_settings().thumbs_dir
    for old in thumbs.glob(f"{video_id}_sprite_*.jpg"):
        old.unlink(missing_ok=True)
    sheets = sorted(spec.pattern.parent.glob("sprite_*.jpg"))
    if not sheets:
        return None
    names = []
    for i, sheet in enumerate(sheets):
        name = f"{video_id}_sprite_{i:03d}.jpg"
        shutil.move(str(sheet), str(thumbs / name))
        names.append(name)
    return {
        "interval": spec.interval, "w": spec.w, "h": spec.h, "cols": spec.cols, "rows": spec.rows,
        "count": min(len(names) * spec.cols * spec.rows, int(duration // spec.interval) + 1),
        "sheets": [f"/media/thumbs/{n}" for n in names],
    }


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
    for leftover in settings.uploads_dir.glob(f"{video['id']}.*"):  # partial imports
        leftover.unlink(missing_ok=True)
    (settings.analysis_dir / f"{video['id']}.npz").unlink(missing_ok=True)
    for sheet in settings.thumbs_dir.glob(f"{video['id']}_sprite_*.jpg"):
        sheet.unlink(missing_ok=True)
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
