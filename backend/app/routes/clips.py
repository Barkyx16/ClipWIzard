"""Clips, montages, transcripts, the clips library and zip downloads."""

from __future__ import annotations

import io
import re
import secrets
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from .. import db, jobs, pipeline
from ..config import get_settings
from ..guards import Workspace, check_render_limits, clip_or_404, video_or_404
from ..schemas import (
    MAX_CLIP_SECONDS,
    MAX_MONTAGE_SECONDS,
    ClipCreate,
    ExportAll,
    MontageCreate,
    TranscriptCreate,
)
from ..serializers import clip_out, poster_path, transcript_out

router = APIRouter()


def _queue_clip(v: dict[str, Any], body: ClipCreate) -> dict[str, Any]:
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    duration = float(v["duration"] or 0)
    start = min(body.start, max(0.0, duration - 0.5))
    end = min(body.end, duration) if duration else body.end
    if end <= start + 0.5:
        raise HTTPException(422, "Clip range is outside the video")
    if body.highlight_id:
        h = db.get_highlight(body.highlight_id)
        if h is None or h["video_id"] != v["id"]:
            raise HTTPException(404, "Highlight not found for this video")
    options = body.model_dump(
        include={"aspect", "crop_x", "title_overlay", "title", "quality", "captions", "caption_style",
                 "caption_position", "watermark", "replay", "normalize", "caption_words"}
    )
    if not options.get("caption_words"):
        options.pop("caption_words", None)
    if body.aspect == "vertical_facecam":
        facecam = (v.get("layout") or {}).get("facecam")
        if not facecam:
            raise HTTPException(422, "Mark your facecam on the video first")
        options["facecam"] = facecam
    c = db.create_clip(video_id=v["id"], highlight_id=body.highlight_id, start=round(start, 3),
                       end=round(end, 3), options=options)
    jobs.submit(pipeline.render, c["id"])
    return clip_out(c)


@router.post("/api/videos/{video_id}/clips", status_code=201)
def create_clip(video_id: str, body: ClipCreate, ws: str = Workspace) -> dict[str, Any]:
    v = video_or_404(video_id, ws)
    check_render_limits(ws)
    return _queue_clip(v, body)


@router.post("/api/videos/{video_id}/export-all", status_code=201)
def export_all(video_id: str, body: ExportAll, ws: str = Workspace) -> list[dict[str, Any]]:
    v = video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    check_render_limits(ws, min(body.top, len(db.list_highlights(video_id))))
    out = []
    for h in db.list_highlights(video_id)[: body.top]:
        if not (0.5 < h["end"] - h["start"] <= MAX_CLIP_SECONDS):
            continue
        out.append(_queue_clip(v, ClipCreate(
            highlight_id=h["id"], start=h["start"], end=h["end"], aspect=body.aspect,
            title_overlay=body.title_overlay, title=h["title"], quality=body.quality,
            captions=body.captions, caption_style=body.caption_style,
            caption_position=body.caption_position, watermark=body.watermark, replay=body.replay,
            normalize=body.normalize,
        )))
    return out


@router.post("/api/videos/{video_id}/montage", status_code=201)
def create_montage(video_id: str, body: MontageCreate, ws: str = Workspace) -> dict[str, Any]:
    """Stitch several highlights into one compilation video."""
    v = video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    if len(set(body.highlight_ids)) != len(body.highlight_ids):
        raise HTTPException(422, "Each moment can only be used once")
    check_render_limits(ws)
    by_id = {h["id"]: h for h in db.list_highlights(video_id)}
    picked = []
    for hid in body.highlight_ids:
        if hid not in by_id:
            raise HTTPException(404, "Highlight not found for this video")
        picked.append(by_id[hid])
    if body.order == "timeline":
        picked.sort(key=lambda h: h["start"])
    elif body.order == "score":
        picked.sort(key=lambda h: -h["score"])
    total = sum(h["end"] - h["start"] for h in picked)
    if total > MAX_MONTAGE_SECONDS:
        raise HTTPException(422, f"Montages can be at most {MAX_MONTAGE_SECONDS // 60} minutes long")
    options: dict[str, Any] = {
        "kind": "montage",
        "segments": [{"highlight_id": h["id"], "start": h["start"], "end": h["end"], "title": h["title"]}
                     for h in picked],
        "transition": body.transition,
        "aspect": body.aspect,
        "crop_x": 0.5,
        "title_overlay": body.title_overlay,
        "title": f"Top {len(picked)} moments",
        "captions": body.captions,
        "caption_style": body.caption_style,
        "caption_position": body.caption_position,
        "quality": body.quality,
        "watermark": body.watermark,
        "normalize": body.normalize,
    }
    if body.aspect == "vertical_facecam":
        facecam = (v.get("layout") or {}).get("facecam")
        if not facecam:
            raise HTTPException(422, "Mark your facecam on the video first")
        options["facecam"] = facecam
    c = db.create_clip(video_id=video_id, highlight_id=None, start=0.0, end=round(total, 3),
                       options=options)
    jobs.submit(pipeline.render, c["id"])
    return clip_out(c)


@router.post("/api/videos/{video_id}/transcripts", status_code=201)
def create_transcript(video_id: str, body: TranscriptCreate, ws: str = Workspace) -> dict[str, Any]:
    """Transcribe a range in the background so captions can be reviewed before export."""
    v = video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    if not v["has_audio"]:
        raise HTTPException(422, "This video has no audio to transcribe")
    check_render_limits(ws)
    t = db.create_transcript(video_id=video_id, start=body.start, end=min(body.end, float(v["duration"])))
    jobs.submit(pipeline.transcribe_range, t["id"], pool="transcribe")
    return transcript_out(t)


@router.get("/api/transcripts/{transcript_id}")
def get_transcript(transcript_id: str, ws: str = Workspace) -> dict[str, Any]:
    t = db.get_transcript(transcript_id)
    if t is None:
        raise HTTPException(404, "Transcript not found")
    video_or_404(t["video_id"], ws)
    return transcript_out(t)


@router.get("/api/videos/{video_id}/clips")
def list_clips(video_id: str, ws: str = Workspace) -> list[dict[str, Any]]:
    video_or_404(video_id, ws)
    return [clip_out(c) for c in db.list_clips(video_id)]


@router.get("/api/videos/{video_id}/clips.zip")
def download_all_clips(video_id: str, ws: str = Workspace) -> FileResponse:
    """Every finished clip of a session in one zip (stored, not recompressed)."""
    v = video_or_404(video_id, ws)
    done = [c for c in db.list_clips(video_id) if c["status"] == "done" and c.get("filename")]
    if not done:
        raise HTTPException(404, "No finished clips to download yet")
    s = get_settings()
    titles = {h["id"]: h["title"] for h in db.list_highlights(video_id)}
    used: set[str] = set()
    entries: list[tuple[Path, str]] = []
    for i, c in enumerate(reversed(done), start=1):
        path = pipeline.safe_path(s.clips_dir, c["filename"])
        if path is None:
            continue
        o = c.get("options") or {}
        base = "montage" if o.get("kind") == "montage" else (titles.get(c.get("highlight_id") or "")
                                                             or o.get("title") or "clip")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()[:50] or "clip"
        name = f"{i:02d}-{slug}.mp4"
        while name in used:
            name = f"{i:02d}-{slug}-{c['id'][:4]}.mp4"
        used.add(name)
        entries.append((path, name))
    if not entries:
        raise HTTPException(404, "No finished clips to download yet")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", Path(v["original_name"]).stem).strip("-").lower()[:40] or "session"
    return StreamingResponse(
        _stream_zip(entries), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="clipwizard-{stem}.zip"'},
    )


class _ZipSink(io.RawIOBase):
    """Write-only, non-seekable file that hands zip bytes to a generator."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.pos = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        data = bytes(b)
        self.chunks.append(data)
        self.pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self.pos

    def take(self) -> bytes:
        out = b"".join(self.chunks)
        self.chunks.clear()
        return out


def _stream_zip(entries: list[tuple[Path, str]]):
    """Zip (stored) built on the fly: no temp copy on disk, constant memory."""
    sink = _ZipSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path, name in entries:
            try:
                src = open(path, "rb")
            except FileNotFoundError:  # deleted while downloading: skip it
                continue
            with src, zf.open(zipfile.ZipInfo.from_file(path, arcname=name), "w", force_zip64=True) as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
                    yield sink.take()
            yield sink.take()
    yield sink.take()


@router.get("/api/clips")
def library(ws: str = Workspace) -> list[dict[str, Any]]:
    """Every finished clip in this workspace, newest first (the clips library)."""
    out = []
    for c in db.workspace_clips(ws):
        o = c.get("options") or {}
        title = (f"Montage: {len(o.get('segments') or [])} moments" if o.get("kind") == "montage"
                 else c.get("highlight_title") or o.get("title") or "Custom clip")
        out.append({**clip_out(c), "title": title, "video_name": c["video_name"]})
    return out


@router.get("/api/clips/{clip_id}")
def get_clip(clip_id: str, ws: str = Workspace) -> dict[str, Any]:
    return clip_out(clip_or_404(clip_id, ws))


@router.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: str, ws: str = Workspace) -> FileResponse:
    c = clip_or_404(clip_id, ws)
    if c["status"] != "done" or not c.get("filename"):
        raise HTTPException(404, "Clip is not ready")
    path = pipeline.safe_path(get_settings().clips_dir, c["filename"])
    if path is None:
        raise HTTPException(404, "Clip file is missing")
    v = db.get_video(c["video_id"])
    title = ""
    if c.get("highlight_id"):
        h = db.get_highlight(c["highlight_id"])
        title = h["title"] if h else ""
    if (c.get("options") or {}).get("kind") == "montage":
        title = "montage"
    base = title or (Path(v["original_name"]).stem if v else "clip")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()[:60] or "clip"
    return FileResponse(path, media_type="video/mp4", filename=f"clipwizard-{slug}-{clip_id}.mp4")


@router.post("/api/clips/{clip_id}/share")
def share_clip(clip_id: str, ws: str = Workspace) -> dict[str, Any]:
    """Create (or return) a public, unguessable link to a finished clip."""
    c = clip_or_404(clip_id, ws)
    if c["status"] != "done":
        raise HTTPException(409, "The clip isn't finished yet")
    if not c.get("share_token"):
        db.update_clip(clip_id, share_token=secrets.token_urlsafe(16))
    return clip_out(db.get_clip(clip_id))  # type: ignore[arg-type]


@router.delete("/api/clips/{clip_id}/share")
def unshare_clip(clip_id: str, ws: str = Workspace) -> dict[str, Any]:
    clip_or_404(clip_id, ws)
    db.update_clip(clip_id, share_token=None)
    return clip_out(db.get_clip(clip_id))  # type: ignore[arg-type]


@router.delete("/api/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: str, ws: str = Workspace) -> None:
    c = clip_or_404(clip_id, ws)
    if c["status"] in ("queued", "rendering"):
        raise HTTPException(409, "Wait for the render to finish before deleting")
    if c.get("filename"):
        (get_settings().clips_dir / c["filename"]).unlink(missing_ok=True)
    poster_path(clip_id).unlink(missing_ok=True)
    db.delete_clip(clip_id)
