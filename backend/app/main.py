"""ClipWizard HTTP API."""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import db, jobs, pipeline
from .config import get_settings
from .media import ffmpeg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clipwizard")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".flv"}
MAX_CLIP_SECONDS = 180


@asynccontextmanager
async def lifespan(_: FastAPI):
    ffmpeg.ensure_available()
    db.init_db()
    jobs.resume_interrupted()
    s = get_settings()
    log.info("ClipWizard ready. Data dir: %s. AI enrichment: %s (%s)",
             s.data_dir, "on" if s.ai_enabled else "off", s.claude_model)
    yield
    jobs.shutdown()


app = FastAPI(title="ClipWizard", version="0.1.0", lifespan=lifespan)

_cors = os.environ.get("CLIPWIZARD_CORS_ORIGINS")
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ------------------------------------------------------------------ schemas


class AnalyzeSettings(BaseModel):
    length: Literal["short", "medium", "long"] = "short"
    max_clips: int = Field(12, ge=1, le=30)
    sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    use_ai: bool = True


class ClipCreate(BaseModel):
    highlight_id: str | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    aspect: Literal["landscape", "vertical_blur", "vertical_crop", "square"] = "vertical_blur"
    crop_x: float = Field(0.5, ge=0.0, le=1.0)
    title_overlay: bool = False
    title: str | None = Field(None, max_length=120)
    quality: Literal["high", "fast"] = "high"

    @model_validator(mode="after")
    def _check_range(self) -> "ClipCreate":
        if self.end <= self.start + 0.5:
            raise ValueError("Clip end must be at least 0.5s after its start")
        if self.end - self.start > MAX_CLIP_SECONDS:
            raise ValueError(f"Clips can be at most {MAX_CLIP_SECONDS} seconds long")
        return self


class ExportAll(BaseModel):
    aspect: Literal["landscape", "vertical_blur", "vertical_crop", "square"] = "vertical_blur"
    title_overlay: bool = True
    top: int = Field(5, ge=1, le=30)
    quality: Literal["high", "fast"] = "high"


class HighlightPatch(BaseModel):
    title: str | None = Field(None, max_length=120)
    caption: str | None = Field(None, max_length=600)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, gt=0)


# ------------------------------------------------------------------ serializers


def _media_url(kind: str, name: str | None) -> str | None:
    return f"/media/{kind}/{name}" if name else None


def video_out(v: dict[str, Any], include_children: bool = False) -> dict[str, Any]:
    out = {
        "id": v["id"],
        "name": v["original_name"],
        "size_bytes": v["size_bytes"],
        "duration": v["duration"],
        "width": v["width"],
        "height": v["height"],
        "fps": v["fps"],
        "has_audio": v["has_audio"],
        "status": v["status"],
        "stage": v["stage"],
        "progress": v["progress"],
        "error": v["error"],
        "settings": v["settings"],
        "ai_used": v["ai_used"],
        "created_at": v["created_at"],
        "source_url": _media_url("uploads", v["filename"]),
        "thumbnail_url": _media_url("thumbs", v.get("thumbnail")),
    }
    if include_children:
        out["highlights"] = [highlight_out(h) for h in db.list_highlights(v["id"])]
        out["clips"] = [clip_out(c) for c in db.list_clips(v["id"])]
    return out


def highlight_out(h: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": h["id"],
        "video_id": h["video_id"],
        "rank": h["rank"],
        "start": h["start"],
        "end": h["end"],
        "peak": h["peak"],
        "score": h["score"],
        "category": h["category"],
        "title": h["title"],
        "description": h["description"],
        "caption": h["caption"],
        "hashtags": h["hashtags"],
        "signals": h["signals"],
        "ai_enriched": h["ai_enriched"],
        "thumbnail_url": _media_url("thumbs", h.get("thumbnail")),
    }


def clip_out(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["id"],
        "video_id": c["video_id"],
        "highlight_id": c["highlight_id"],
        "start": c["start"],
        "end": c["end"],
        "options": c["options"],
        "status": c["status"],
        "progress": c["progress"],
        "error": c["error"],
        "size_bytes": c["size_bytes"],
        "created_at": c["created_at"],
        "url": _media_url("clips", c.get("filename")),
        "download_url": f"/api/clips/{c['id']}/download" if c.get("filename") else None,
    }


def _video_or_404(video_id: str) -> dict[str, Any]:
    v = db.get_video(video_id)
    if v is None:
        raise HTTPException(404, "Video not found")
    return v


# ------------------------------------------------------------------ routes


@app.get("/api/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "ok": True,
        "ai_enabled": s.ai_enabled,
        "model": s.claude_model if s.ai_enabled else None,
        "max_upload_mb": s.max_upload_mb,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
    }


@app.get("/api/videos")
def list_videos() -> list[dict[str, Any]]:
    return [video_out(v) for v in db.list_videos()]


@app.post("/api/videos", status_code=201)
async def upload_video(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    length: Literal["short", "medium", "long"] = "short",
    max_clips: int = Query(12, ge=1, le=30),
    sensitivity: float = Query(0.5, ge=0.0, le=1.0),
    use_ai: bool = True,
) -> dict[str, Any]:
    """Upload a recording as the raw request body (streamed straight to disk)."""
    s = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: "
                                 + ", ".join(sorted(ALLOWED_EXTENSIONS)))
    declared = request.headers.get("content-length")
    limit = s.max_upload_mb * 1024 * 1024
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"File is larger than the {s.max_upload_mb} MB limit")

    video_id = db.new_id()
    stored = f"{video_id}{ext}"
    dest = s.uploads_dir / stored
    size = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File is larger than the {s.max_upload_mb} MB limit")
                f.write(chunk)
        if size == 0:
            raise HTTPException(400, "The uploaded file is empty")
        try:
            info = ffmpeg.probe(dest)
        except ffmpeg.FFmpegError as e:
            raise HTTPException(400, str(e)) from e
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

    clean_name = re.sub(r"[\x00-\x1f]", "", Path(filename).name)[:255]
    settings = AnalyzeSettings(length=length, max_clips=max_clips,
                               sensitivity=sensitivity, use_ai=use_ai)
    v = db.create_video(
        id=video_id, original_name=clean_name, filename=stored, size_bytes=size,
        duration=info.duration, width=info.width, height=info.height, fps=info.fps,
        has_audio=info.has_audio, status="queued", stage="Queued", progress=0.0,
        settings=settings.model_dump(),
    )
    jobs.submit(pipeline.analyze_video, video_id)
    return video_out(v, include_children=True)


@app.get("/api/videos/{video_id}")
def get_video(video_id: str) -> dict[str, Any]:
    return video_out(_video_or_404(video_id), include_children=True)


@app.get("/api/videos/{video_id}/timeline")
def get_timeline(video_id: str) -> dict[str, Any]:
    _video_or_404(video_id)
    t = db.get_timeline(video_id)
    if t is None:
        return {"hop": 1.0, "excitement": [], "audio": [], "motion": []}
    return {"hop": t["hop"], **t["data"]}


@app.post("/api/videos/{video_id}/reanalyze")
def reanalyze(video_id: str, body: AnalyzeSettings) -> dict[str, Any]:
    v = _video_or_404(video_id)
    if v["status"] in ("queued", "analyzing"):
        raise HTTPException(409, "This video is already being analysed")
    db.update_video(video_id, settings=body.model_dump(), status="queued", stage="Queued",
                    progress=0.0, error=None)
    jobs.submit(pipeline.analyze_video, video_id)
    return video_out(db.get_video(video_id), include_children=True)  # type: ignore[arg-type]


@app.delete("/api/videos/{video_id}", status_code=204)
def delete_video(video_id: str) -> None:
    v = _video_or_404(video_id)
    if v["status"] in ("queued", "analyzing"):
        raise HTTPException(409, "Wait for analysis to finish before deleting")
    pipeline.remove_video_files(v)
    db.delete_video(video_id)


@app.patch("/api/highlights/{highlight_id}")
def patch_highlight(highlight_id: str, body: HighlightPatch) -> dict[str, Any]:
    h = db.get_highlight(highlight_id)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    changes = body.model_dump(exclude_none=True)
    start, end = changes.get("start", h["start"]), changes.get("end", h["end"])
    if end <= start + 0.5:
        raise HTTPException(422, "Highlight end must be after its start")
    db.update_highlight(highlight_id, **changes)
    return highlight_out(db.get_highlight(highlight_id))  # type: ignore[arg-type]


def _queue_clip(v: dict[str, Any], body: ClipCreate) -> dict[str, Any]:
    if v["status"] != "ready" and body.highlight_id:
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
    options = body.model_dump(include={"aspect", "crop_x", "title_overlay", "title", "quality"})
    c = db.create_clip(video_id=v["id"], highlight_id=body.highlight_id, start=round(start, 3),
                       end=round(end, 3), options=options)
    jobs.submit(pipeline.render, c["id"])
    return clip_out(c)


@app.post("/api/videos/{video_id}/clips", status_code=201)
def create_clip(video_id: str, body: ClipCreate) -> dict[str, Any]:
    return _queue_clip(_video_or_404(video_id), body)


@app.post("/api/videos/{video_id}/export-all", status_code=201)
def export_all(video_id: str, body: ExportAll) -> list[dict[str, Any]]:
    v = _video_or_404(video_id)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    out = []
    for h in db.list_highlights(video_id)[: body.top]:
        out.append(_queue_clip(v, ClipCreate(
            highlight_id=h["id"], start=h["start"], end=h["end"], aspect=body.aspect,
            title_overlay=body.title_overlay, title=h["title"], quality=body.quality,
        )))
    return out


@app.get("/api/videos/{video_id}/clips")
def list_clips(video_id: str) -> list[dict[str, Any]]:
    _video_or_404(video_id)
    return [clip_out(c) for c in db.list_clips(video_id)]


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str) -> dict[str, Any]:
    c = db.get_clip(clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    return clip_out(c)


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: str) -> FileResponse:
    c = db.get_clip(clip_id)
    if c is None or c["status"] != "done" or not c.get("filename"):
        raise HTTPException(404, "Clip is not ready")
    path = pipeline.safe_path(get_settings().clips_dir, c["filename"])
    if path is None:
        raise HTTPException(404, "Clip file is missing")
    v = db.get_video(c["video_id"])
    title = ""
    if c.get("highlight_id"):
        h = db.get_highlight(c["highlight_id"])
        title = h["title"] if h else ""
    base = title or (Path(v["original_name"]).stem if v else "clip")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()[:60] or "clip"
    return FileResponse(path, media_type="video/mp4", filename=f"clipwizard-{slug}-{clip_id}.mp4")


@app.delete("/api/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: str) -> None:
    c = db.get_clip(clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    if c["status"] in ("queued", "rendering"):
        raise HTTPException(409, "Wait for the render to finish before deleting")
    if c.get("filename"):
        (get_settings().clips_dir / c["filename"]).unlink(missing_ok=True)
    db.delete_clip(clip_id)


# ------------------------------------------------------------------ static files

app.mount("/media", StaticFiles(directory=get_settings().media_dir), name="media")

_frontend = Path(os.environ.get(
    "CLIPWIZARD_FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"
))
if (_frontend / "index.html").exists():
    if (_frontend / "assets").exists():
        app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "media/")):
            raise HTTPException(404)
        candidate = (_frontend / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_frontend.resolve()):
            return FileResponse(candidate)
        return FileResponse(_frontend / "index.html")
