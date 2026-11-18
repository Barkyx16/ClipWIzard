"""ClipWizard HTTP API."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import db, jobs, pipeline, retention
from .config import get_settings
from .media import captions, ffmpeg, importer
from .workspace import (
    WorkspaceMiddleware,
    current_workspace,
    same_workspace,
    set_cookie,
    valid_key,
    workspace_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clipwizard")

CaptionStyle = Literal["bold", "neon", "clean"]
Aspect = Literal[
    "landscape", "vertical_blur", "vertical_crop", "vertical_smart", "vertical_facecam", "square"
]
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".flv"}
MAX_CLIP_SECONDS = 180


@asynccontextmanager
async def lifespan(_: FastAPI):
    ffmpeg.ensure_available()
    db.init_db()
    jobs.resume_interrupted()
    retention.start()
    s = get_settings()
    log.info("ClipWizard ready. Data dir: %s. AI enrichment: %s (%s)",
             s.data_dir, "on" if s.ai_enabled else "off", s.claude_model)
    yield
    retention.stop()
    jobs.shutdown()


app = FastAPI(title="ClipWizard", version="0.2.0", lifespan=lifespan)
app.add_middleware(WorkspaceMiddleware)
Workspace = Depends(current_workspace)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Like FastAPI's default 422, minus the echoed input (which may be Infinity/NaN,
    or large, and isn't needed by the UI)."""
    errors = [{k: v for k, v in e.items() if k in ("type", "loc", "msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

_cors = os.environ.get("CLIPWIZARD_CORS_ORIGINS")
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ------------------------------------------------------------------ schemas


class ApiModel(BaseModel):
    """Base for request bodies: JSON allows Infinity/NaN, we don't."""

    model_config = ConfigDict(allow_inf_nan=False)


class AnalyzeSettings(ApiModel):
    length: Literal["short", "medium", "long"] = "short"
    max_clips: int = Field(12, ge=1, le=30)
    sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    use_ai: bool = True


class CaptionWord(ApiModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=40)


class TranscriptCreate(ApiModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_range(self) -> "TranscriptCreate":
        if not (0.5 < self.end - self.start <= MAX_CLIP_SECONDS):
            raise ValueError(f"Pick a range between 0.5 and {MAX_CLIP_SECONDS} seconds")
        return self


class ClipCreate(ApiModel):
    highlight_id: str | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    aspect: Aspect = "vertical_blur"
    crop_x: float = Field(0.5, ge=0.0, le=1.0)
    title_overlay: bool = False
    title: str | None = Field(None, max_length=120)
    quality: Literal["high", "fast"] = "high"
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    watermark: str | None = Field(None, max_length=40)
    replay: bool = False
    normalize: bool = True
    # Captions the user reviewed/edited (times relative to the clip start).
    caption_words: list[CaptionWord] | None = Field(None, max_length=3000)

    @model_validator(mode="after")
    def _check_range(self) -> "ClipCreate":
        if self.end <= self.start + 0.5:
            raise ValueError("Clip end must be at least 0.5s after its start")
        if self.end - self.start > MAX_CLIP_SECONDS:
            raise ValueError(f"Clips can be at most {MAX_CLIP_SECONDS} seconds long")
        return self


class ExportAll(ApiModel):
    aspect: Aspect = "vertical_blur"
    title_overlay: bool = True
    top: int = Field(5, ge=1, le=30)
    replay: bool = False
    normalize: bool = True
    quality: Literal["high", "fast"] = "high"
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    watermark: str | None = Field(None, max_length=40)


class Rect(ApiModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0.02, le=1)
    h: float = Field(gt=0.02, le=1)

    @model_validator(mode="after")
    def _inside(self) -> "Rect":
        if self.x + self.w > 1.001 or self.y + self.h > 1.001:
            raise ValueError("Rectangle must be inside the frame")
        return self


class LayoutUpdate(ApiModel):
    facecam: Rect | None = None


class ImportRequest(AnalyzeSettings):
    url: str = Field(min_length=8, max_length=2000)


class UploadStart(AnalyzeSettings):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    fingerprint: str = Field(min_length=1, max_length=400)


class WorkspaceSwitch(ApiModel):
    key: str = Field(min_length=32, max_length=64)


class MontageCreate(ApiModel):
    highlight_ids: list[str] = Field(min_length=2, max_length=20)
    normalize: bool = True
    order: Literal["as_given", "timeline", "score"] = "as_given"
    transition: Literal["fade", "fadeblack", "slideleft", "cut"] = "fade"
    aspect: Aspect = "vertical_blur"
    title_overlay: bool = True
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    quality: Literal["high", "fast"] = "high"
    watermark: str | None = Field(None, max_length=40)


class VideoPatch(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class HighlightCreate(ApiModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def _check_range(self) -> "HighlightCreate":
        if self.end <= self.start + 1:
            raise ValueError("A highlight must be at least 1 second long")
        if self.end - self.start > MAX_CLIP_SECONDS:
            raise ValueError(f"Highlights can be at most {MAX_CLIP_SECONDS} seconds long")
        return self


class HighlightPatch(ApiModel):
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
        "layout": v.get("layout") or {},
        "import_url": v.get("import_url"),
        "queue_ahead": db.queue_ahead(v) if v["status"] == "queued" else 0,
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
        "transcript": c.get("transcript"),
        "warning": c.get("warning"),
        "created_at": c["created_at"],
        "url": _media_url("clips", c.get("filename")),
        "share_url": f"/s/{c['share_token']}" if c.get("share_token") else None,
        "download_url": f"/api/clips/{c['id']}/download" if c.get("filename") else None,
    }


def _check_video_limits(ws: str, incoming_bytes: int = 0) -> None:
    s = get_settings()
    usage = db.workspace_usage(ws)
    if s.max_active_videos and usage["busy_videos"] >= s.max_active_videos:
        raise HTTPException(429, f"You already have {usage['busy_videos']} videos processing. "
                                 "Wait for one to finish, then try again.")
    quota = int(s.workspace_quota_gb * 1024**3)
    if quota and usage["stored_bytes"] + incoming_bytes > quota:
        raise HTTPException(413, f"Your workspace is full ({s.workspace_quota_gb:g} GB). "
                                 "Delete old sessions or clips to make room.")


def _check_render_limits(ws: str, adding: int = 1) -> None:
    s = get_settings()
    usage = db.workspace_usage(ws)
    if s.max_active_renders and usage["busy_clips"] + adding > s.max_active_renders:
        raise HTTPException(429, f"You have {usage['busy_clips']} clips rendering. "
                                 "Wait for some to finish, then export more.")


def _video_or_404(video_id: str, ws: str) -> dict[str, Any]:
    v = db.get_video(video_id)
    if v is None or not same_workspace(v.get("workspace"), ws):
        raise HTTPException(404, "Video not found")
    return v


def _clip_or_404(clip_id: str, ws: str) -> dict[str, Any]:
    c = db.get_clip(clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    v = db.get_video(c["video_id"])
    if v is None or not same_workspace(v.get("workspace"), ws):
        raise HTTPException(404, "Clip not found")
    return c


def _highlight_or_404(highlight_id: str, ws: str) -> dict[str, Any]:
    h = db.get_highlight(highlight_id)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    v = db.get_video(h["video_id"])
    if v is None or not same_workspace(v.get("workspace"), ws):
        raise HTTPException(404, "Highlight not found")
    return h


# ------------------------------------------------------------------ routes


@app.get("/api/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "ok": True,
        "ai_enabled": s.ai_enabled,
        "model": s.claude_model if s.ai_enabled else None,
        "max_upload_mb": s.max_upload_mb,
        "captions_available": captions.available(),
        "import_sites": list(dict.fromkeys(importer.PLATFORMS.values())),
        "retention_days": retention.retention_days(),
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
    }


@app.get("/api/workspace")
def get_workspace(request: Request) -> dict[str, str]:
    """The caller's workspace key, so they can open it on another device."""
    return {"key": request.state.workspace_key}


@app.post("/api/workspace")
def switch_workspace(body: WorkspaceSwitch, request: Request, response: Response) -> dict[str, Any]:
    if not valid_key(body.key):
        raise HTTPException(422, "That doesn't look like a workspace key")
    request.state.workspace_switched = True
    set_cookie(request, response, body.key)
    return {"ok": True, "videos": len(db.list_videos(workspace_id(body.key)))}


@app.get("/api/videos")
def list_videos(ws: str = Workspace) -> list[dict[str, Any]]:
    return [video_out(v) for v in db.list_videos(ws)]


@app.post("/api/videos", status_code=201)
async def upload_video(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    length: Literal["short", "medium", "long"] = "short",
    max_clips: int = Query(12, ge=1, le=30),
    sensitivity: float = Query(0.5, ge=0.0, le=1.0),
    use_ai: bool = True,
    ws: str = Workspace,
) -> dict[str, Any]:
    """Upload a recording as the raw request body (streamed straight to disk)."""
    s = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: "
                                 + ", ".join(sorted(ALLOWED_EXTENSIONS)))
    declared = request.headers.get("content-length")
    _check_video_limits(ws, int(declared) if declared and declared.isdigit() else 0)
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
        settings=settings.model_dump(), workspace=ws,
    )
    jobs.submit(pipeline.analyze_video, video_id)
    return video_out(v, include_children=True)


@app.post("/api/videos/import", status_code=201)
def import_link(body: ImportRequest, ws: str = Workspace) -> dict[str, Any]:
    """Download a video from YouTube/Twitch/... or a direct file link, then analyse it."""
    try:
        importer.classify(body.url)
    except importer.ImportFailed as e:
        raise HTTPException(400, str(e)) from e
    _check_video_limits(ws)
    video_id = db.new_id()
    settings = AnalyzeSettings(**body.model_dump(exclude={"url"}))
    v = db.create_video(
        id=video_id, original_name=importer.display_name(body.url), filename=f"{video_id}.pending",
        size_bytes=0, status="downloading", stage="Waiting to download", progress=0.0,
        settings=settings.model_dump(), workspace=ws, import_url=body.url.strip(),
    )
    jobs.submit(pipeline.import_video, video_id)
    return video_out(v, include_children=True)


# ------------------------------------------------------------ resumable uploads

CHUNK_SIZE = int(float(os.environ.get("CLIPWIZARD_UPLOAD_CHUNK_MB", "16")) * 1024 * 1024)
MAX_CHUNK = 64 * 1024 * 1024
_upload_locks: dict[str, asyncio.Lock] = {}
_complete_locks: dict[str, threading.Lock] = {}


def upload_out(u: dict[str, Any]) -> dict[str, Any]:
    return {"id": u["id"], "filename": u["filename"], "size": u["size"], "received": u["received"],
            "chunk_size": CHUNK_SIZE}


def _upload_or_404(upload_id: str, ws: str) -> dict[str, Any]:
    u = db.get_upload(upload_id)
    if u is None or not same_workspace(u["workspace"], ws):
        raise HTTPException(404, "Upload not found")
    return u


def _partial(upload_id: str) -> Path:
    return get_settings().partial_dir / f"{upload_id}.part"


@app.post("/api/uploads", status_code=201)
def start_upload(body: UploadStart, ws: str = Workspace) -> dict[str, Any]:
    """Begin (or resume) a chunked upload. Re-sending the same fingerprint resumes."""
    s = get_settings()
    ext = Path(body.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: "
                                 + ", ".join(sorted(ALLOWED_EXTENSIONS)))
    if body.size > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than the {s.max_upload_mb} MB limit")
    existing = db.find_upload(ws, body.fingerprint)
    if not existing:
        _check_video_limits(ws, body.size)
    if existing and existing["size"] == body.size:
        part = _partial(existing["id"])
        on_disk = part.stat().st_size if part.exists() else 0
        if on_disk < existing["received"]:
            db.update_upload(existing["id"], received=on_disk)
            existing["received"] = on_disk
        return upload_out(existing)
    settings = AnalyzeSettings(**body.model_dump(include=set(AnalyzeSettings.model_fields)))
    u = db.create_upload(workspace=ws, fingerprint=body.fingerprint, filename=Path(body.filename).name,
                         size=body.size, received=0, settings=settings.model_dump())
    _partial(u["id"]).touch()
    return upload_out(u)


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str, ws: str = Workspace) -> dict[str, Any]:
    return upload_out(_upload_or_404(upload_id, ws))


@app.put("/api/uploads/{upload_id}")
async def put_chunk(upload_id: str, request: Request, offset: int = Query(..., ge=0),
                    ws: str = Workspace) -> dict[str, Any]:
    """Append one chunk. ``offset`` must equal the bytes already received."""
    u = _upload_or_404(upload_id, ws)
    lock = _upload_locks.setdefault(upload_id, asyncio.Lock())
    async with lock:
        u = db.get_upload(upload_id) or u
        if offset != u["received"]:
            raise HTTPException(409, detail={"message": "Offset mismatch", "received": u["received"]})
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_CHUNK:
            raise HTTPException(413, "Chunk too large")
        part = _partial(upload_id)
        written = 0
        with open(part, "r+b" if part.exists() else "w+b") as f:
            f.truncate(offset)  # drop any bytes from an interrupted attempt
            f.seek(offset)
            async for data in request.stream():
                written += len(data)
                if written > MAX_CHUNK or offset + written > u["size"]:
                    f.truncate(offset)
                    raise HTTPException(413, "Chunk goes past the end of the file")
                f.write(data)
        db.update_upload(upload_id, received=offset + written)
        u["received"] = offset + written
    return upload_out(u)


@app.post("/api/uploads/{upload_id}/complete", status_code=201)
def complete_upload(upload_id: str, ws: str = Workspace) -> dict[str, Any]:
    _upload_or_404(upload_id, ws)
    lock = _complete_locks.setdefault(upload_id, threading.Lock())
    try:
        with lock:
            return _complete_upload_locked(upload_id, ws)
    finally:
        _complete_locks.pop(upload_id, None)


def _complete_upload_locked(upload_id: str, ws: str) -> dict[str, Any]:
    u = db.get_upload(upload_id)
    if u is None:
        raise HTTPException(409, "This upload was already completed")
    part = _partial(upload_id)
    if u["received"] != u["size"] or not part.exists() or part.stat().st_size != u["size"]:
        raise HTTPException(409, detail={"message": "Upload is not finished", "received": u["received"]})
    _check_video_limits(ws)
    video_id = db.new_id()
    ext = Path(u["filename"]).suffix.lower()
    dest = get_settings().uploads_dir / f"{video_id}{ext}"
    part.replace(dest)
    try:
        info = ffmpeg.probe(dest)
    except ffmpeg.FFmpegError as e:
        dest.unlink(missing_ok=True)
        db.delete_upload(upload_id)
        raise HTTPException(400, str(e)) from e
    v = db.create_video(
        id=video_id, original_name=re.sub(r"[\x00-\x1f]", "", u["filename"])[:255], filename=dest.name,
        size_bytes=u["size"], duration=info.duration, width=info.width, height=info.height,
        fps=info.fps, has_audio=info.has_audio, status="queued", stage="Queued", progress=0.0,
        settings=u["settings"], workspace=ws,
    )
    db.delete_upload(upload_id)
    _upload_locks.pop(upload_id, None)
    jobs.submit(pipeline.analyze_video, video_id)
    return video_out(v, include_children=True)


@app.delete("/api/uploads/{upload_id}", status_code=204)
def cancel_upload(upload_id: str, ws: str = Workspace) -> None:
    _upload_or_404(upload_id, ws)
    _partial(upload_id).unlink(missing_ok=True)
    db.delete_upload(upload_id)
    _upload_locks.pop(upload_id, None)


@app.get("/api/videos/{video_id}")
def get_video(video_id: str, ws: str = Workspace) -> dict[str, Any]:
    return video_out(_video_or_404(video_id, ws), include_children=True)


@app.get("/api/videos/{video_id}/timeline")
def get_timeline(video_id: str, ws: str = Workspace) -> dict[str, Any]:
    _video_or_404(video_id, ws)
    t = db.get_timeline(video_id)
    if t is None:
        return {"hop": 1.0, "excitement": [], "audio": [], "motion": [], "sprites": None}
    return {"hop": t["hop"], **t["data"]}


@app.post("/api/videos/{video_id}/reanalyze")
def reanalyze(video_id: str, body: AnalyzeSettings, ws: str = Workspace) -> dict[str, Any]:
    v = _video_or_404(video_id, ws)
    if v["status"] in ("queued", "analyzing", "downloading"):
        raise HTTPException(409, "This video is already being processed")
    if not (get_settings().uploads_dir / v["filename"]).exists():
        raise HTTPException(409, "The video file is missing, so it can't be re-scanned")
    _check_video_limits(ws)
    db.update_video(video_id, settings=body.model_dump(), status="queued", stage="Queued",
                    progress=0.0, error=None)
    jobs.submit(pipeline.analyze_video, video_id)
    return video_out(db.get_video(video_id), include_children=True)  # type: ignore[arg-type]


@app.patch("/api/videos/{video_id}")
def rename_video(video_id: str, body: VideoPatch, ws: str = Workspace) -> dict[str, Any]:
    _video_or_404(video_id, ws)
    name = re.sub(r"[\x00-\x1f]", "", body.name).strip()
    if not name:
        raise HTTPException(422, "Name can't be empty")
    db.update_video(video_id, original_name=name[:200])
    return video_out(db.get_video(video_id), include_children=True)  # type: ignore[arg-type]


@app.put("/api/videos/{video_id}/layout")
def update_layout(video_id: str, body: LayoutUpdate, ws: str = Workspace) -> dict[str, Any]:
    """Save the facecam rectangle (normalised 0..1) used by the facecam layout."""
    v = _video_or_404(video_id, ws)
    layout = dict(v.get("layout") or {})
    if body.facecam is None:
        layout.pop("facecam", None)
    else:
        layout["facecam"] = body.facecam.model_dump()
    db.update_video(video_id, layout=layout)
    return layout


@app.delete("/api/videos/{video_id}", status_code=204)
def delete_video(video_id: str, ws: str = Workspace) -> None:
    v = _video_or_404(video_id, ws)
    if v["status"] in ("queued", "analyzing", "downloading") or db.video_has_active_jobs(video_id):
        raise HTTPException(409, "Wait for processing and renders to finish before deleting")
    pipeline.remove_video_files(v)
    db.delete_video(video_id)


@app.patch("/api/highlights/{highlight_id}")
def patch_highlight(highlight_id: str, body: HighlightPatch, ws: str = Workspace) -> dict[str, Any]:
    h = _highlight_or_404(highlight_id, ws)
    changes = body.model_dump(exclude_none=True)
    v = db.get_video(h["video_id"])
    duration = float((v or {}).get("duration") or 0)
    start, end = changes.get("start", h["start"]), changes.get("end", h["end"])
    if duration:
        end = min(end, duration)
    if end <= start + 0.5:
        raise HTTPException(422, "Highlight end must be after its start")
    if end - start > MAX_CLIP_SECONDS:
        raise HTTPException(422, f"Highlights can be at most {MAX_CLIP_SECONDS} seconds long")
    if "start" in changes or "end" in changes:
        changes.update(start=round(start, 3), end=round(end, 3))
    db.update_highlight(highlight_id, **changes)
    return highlight_out(db.get_highlight(highlight_id))  # type: ignore[arg-type]


@app.post("/api/videos/{video_id}/highlights", status_code=201)
def create_highlight(video_id: str, body: HighlightCreate, ws: str = Workspace) -> dict[str, Any]:
    """Save a hand-picked range as a highlight."""
    v = _video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    duration = float(v["duration"] or 0)
    start, end = min(body.start, max(0.0, duration - 1)), min(body.end, duration)
    if end <= start + 1:
        raise HTTPException(422, "Highlight range is outside the video")
    score = 50.0
    t = db.get_timeline(video_id)
    if t and t["data"].get("excitement"):
        exc, hop = t["data"]["excitement"], float(t["hop"])
        window = exc[int(start / hop): max(int(start / hop) + 1, int(end / hop))]
        if window:
            score = round(100 * max(window), 1)
    hid = db.new_id()
    peak = round((start + end) / 2, 2)
    thumb: str | None = f"{video_id}_{hid}.jpg"
    try:
        ffmpeg.extract_frame(get_settings().uploads_dir / v["filename"], peak,
                             get_settings().thumbs_dir / thumb, width=480)  # type: ignore[operator]
    except ffmpeg.FFmpegError:
        thumb = None
    rank = len(db.list_highlights(video_id))
    db.insert_highlight(video_id, {
        "id": hid, "rank": rank, "start": round(start, 2), "end": round(end, 2), "peak": peak,
        "score": score, "category": "Custom",
        "title": (body.title or "").strip() or f"My clip at {int(start // 60)}:{int(start % 60):02d}",
        "description": None, "caption": None, "hashtags": ["gta6", "gtavi", "gaming", "gta", "clips"],
        "signals": {}, "thumbnail": thumb, "ai_enriched": False,
    })
    return highlight_out(db.get_highlight(hid))  # type: ignore[arg-type]


@app.delete("/api/highlights/{highlight_id}", status_code=204)
def delete_highlight(highlight_id: str, ws: str = Workspace) -> None:
    h = _highlight_or_404(highlight_id, ws)
    if h.get("thumbnail"):
        (get_settings().thumbs_dir / h["thumbnail"]).unlink(missing_ok=True)
    db.delete_highlight(highlight_id)


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


@app.post("/api/videos/{video_id}/clips", status_code=201)
def create_clip(video_id: str, body: ClipCreate, ws: str = Workspace) -> dict[str, Any]:
    v = _video_or_404(video_id, ws)
    _check_render_limits(ws)
    return _queue_clip(v, body)


@app.post("/api/videos/{video_id}/export-all", status_code=201)
def export_all(video_id: str, body: ExportAll, ws: str = Workspace) -> list[dict[str, Any]]:
    v = _video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    _check_render_limits(ws, min(body.top, len(db.list_highlights(video_id))))
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


MAX_MONTAGE_SECONDS = 600


@app.post("/api/videos/{video_id}/montage", status_code=201)
def create_montage(video_id: str, body: MontageCreate, ws: str = Workspace) -> dict[str, Any]:
    """Stitch several highlights into one compilation video."""
    v = _video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    if len(set(body.highlight_ids)) != len(body.highlight_ids):
        raise HTTPException(422, "Each moment can only be used once")
    _check_render_limits(ws)
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


def transcript_out(t: dict[str, Any]) -> dict[str, Any]:
    return {"id": t["id"], "video_id": t["video_id"], "start": t["start"], "end": t["end"],
            "status": t["status"], "words": t["words"], "error": t["error"]}


@app.post("/api/videos/{video_id}/transcripts", status_code=201)
def create_transcript(video_id: str, body: TranscriptCreate, ws: str = Workspace) -> dict[str, Any]:
    """Transcribe a range in the background so captions can be reviewed before export."""
    v = _video_or_404(video_id, ws)
    if v["status"] != "ready":
        raise HTTPException(409, "Video analysis has not finished yet")
    if not v["has_audio"]:
        raise HTTPException(422, "This video has no audio to transcribe")
    _check_render_limits(ws)
    t = db.create_transcript(video_id=video_id, start=body.start, end=min(body.end, float(v["duration"])))
    jobs.submit(pipeline.transcribe_range, t["id"])
    return transcript_out(t)


@app.get("/api/transcripts/{transcript_id}")
def get_transcript(transcript_id: str, ws: str = Workspace) -> dict[str, Any]:
    t = db.get_transcript(transcript_id)
    if t is None:
        raise HTTPException(404, "Transcript not found")
    _video_or_404(t["video_id"], ws)
    return transcript_out(t)


@app.get("/api/videos/{video_id}/clips")
def list_clips(video_id: str, ws: str = Workspace) -> list[dict[str, Any]]:
    _video_or_404(video_id, ws)
    return [clip_out(c) for c in db.list_clips(video_id)]


@app.get("/api/videos/{video_id}/clips.zip")
def download_all_clips(video_id: str, ws: str = Workspace) -> FileResponse:
    """Every finished clip of a session in one zip (stored, not recompressed)."""
    v = _video_or_404(video_id, ws)
    done = [c for c in db.list_clips(video_id) if c["status"] == "done" and c.get("filename")]
    if not done:
        raise HTTPException(404, "No finished clips to download yet")
    s = get_settings()
    tmp = s.work_dir / f"zip_{db.new_id()}.zip"
    titles = {h["id"]: h["title"] for h in db.list_highlights(video_id)}
    used: set[str] = set()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
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
            zf.write(path, arcname=name)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", Path(v["original_name"]).stem).strip("-").lower()[:40] or "session"
    return FileResponse(tmp, media_type="application/zip", filename=f"clipwizard-{stem}.zip",
                        background=BackgroundTask(tmp.unlink, missing_ok=True))


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str, ws: str = Workspace) -> dict[str, Any]:
    return clip_out(_clip_or_404(clip_id, ws))


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: str, ws: str = Workspace) -> FileResponse:
    c = _clip_or_404(clip_id, ws)
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


@app.post("/api/clips/{clip_id}/share")
def share_clip(clip_id: str, ws: str = Workspace) -> dict[str, Any]:
    """Create (or return) a public, unguessable link to a finished clip."""
    c = _clip_or_404(clip_id, ws)
    if c["status"] != "done":
        raise HTTPException(409, "The clip isn't finished yet")
    if not c.get("share_token"):
        db.update_clip(clip_id, share_token=secrets.token_urlsafe(16))
    return clip_out(db.get_clip(clip_id))  # type: ignore[arg-type]


@app.delete("/api/clips/{clip_id}/share")
def unshare_clip(clip_id: str, ws: str = Workspace) -> dict[str, Any]:
    _clip_or_404(clip_id, ws)
    db.update_clip(clip_id, share_token=None)
    return clip_out(db.get_clip(clip_id))  # type: ignore[arg-type]


NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}


def _shared_clip(token: str) -> tuple[dict[str, Any], Path]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
        raise HTTPException(404, "This link doesn't exist or was turned off")
    c = db.clip_by_share_token(token)
    if c is None or c["status"] != "done" or not c.get("filename"):
        raise HTTPException(404, "This link doesn't exist or was turned off")
    path = pipeline.safe_path(get_settings().clips_dir, c["filename"])
    if path is None:
        raise HTTPException(404, "This link doesn't exist or was turned off")
    return c, path


@app.get("/api/share/{token}")
def shared_info(token: str, response: Response) -> dict[str, Any]:
    """Public metadata for a shared clip (no workspace needed)."""
    c, _ = _shared_clip(token)
    response.headers.update(NOINDEX)
    o = c.get("options") or {}
    h = db.get_highlight(c["highlight_id"]) if c.get("highlight_id") else None
    if o.get("kind") == "montage":
        title = f"Top {len(o.get('segments') or [])} moments"
    else:
        title = (h["title"] if h else None) or o.get("title") or "GTA 6 clip"
    return {
        "title": title,
        "caption": h["caption"] if h else None,
        "hashtags": h["hashtags"] if h else ["gta6", "gtavi", "gaming"],
        "duration": round(c["end"] - c["start"], 2),
        "aspect": o.get("aspect"),
        "video_url": f"/share/{token}/video.mp4",
        "download_url": f"/share/{token}/download",
    }


@app.get("/share/{token}/video.mp4", include_in_schema=False)
def shared_video(token: str) -> FileResponse:
    _, path = _shared_clip(token)
    return FileResponse(path, media_type="video/mp4", headers={**NOINDEX, "Cache-Control": "public, max-age=3600"})


@app.get("/share/{token}/download", include_in_schema=False)
def shared_download(token: str) -> FileResponse:
    c, path = _shared_clip(token)
    return FileResponse(path, media_type="video/mp4", filename=f"clipwizard-{c['id']}.mp4", headers=NOINDEX)


@app.delete("/api/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: str, ws: str = Workspace) -> None:
    c = _clip_or_404(clip_id, ws)
    if c["status"] in ("queued", "rendering"):
        raise HTTPException(409, "Wait for the render to finish before deleting")
    if c.get("filename"):
        (get_settings().clips_dir / c["filename"]).unlink(missing_ok=True)
    db.delete_clip(clip_id)


# ------------------------------------------------------------------ static files

MEDIA_KINDS = {"uploads", "thumbs", "clips"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _media_owner(kind: str, name: str) -> dict[str, Any] | None:
    stem = name.split(".", 1)[0]
    if kind == "uploads":
        return db.get_video(stem)
    if kind == "thumbs":
        return db.get_video(stem.split("_", 1)[0])
    clip = db.get_clip(stem)
    return db.get_video(clip["video_id"]) if clip else None


@app.get("/media/{kind}/{name}", include_in_schema=False)
def media(kind: str, name: str, ws: str = Workspace) -> FileResponse:
    """Serves uploads, thumbnails and renders, but only to their owner."""
    if kind not in MEDIA_KINDS or not _SAFE_NAME.match(name):
        raise HTTPException(404)
    owner = _media_owner(kind, name)
    if owner is None or not same_workspace(owner.get("workspace"), ws):
        raise HTTPException(404)
    path = pipeline.safe_path(get_settings().media_dir / kind, name)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})

_frontend = Path(os.environ.get(
    "CLIPWIZARD_FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"
))
if (_frontend / "index.html").exists():
    if (_frontend / "assets").exists():
        app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "media/", "share/")):
            raise HTTPException(404)
        candidate = (_frontend / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_frontend.resolve()):
            return FileResponse(candidate)
        return FileResponse(_frontend / "index.html")
