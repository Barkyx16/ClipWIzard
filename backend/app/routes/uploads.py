"""Resumable chunked uploads."""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from .. import db, jobs, pipeline
from ..config import get_settings
from ..guards import Workspace, check_video_limits, upload_or_404
from ..media import ffmpeg
from ..schemas import ALLOWED_EXTENSIONS, MAX_CHUNK, AnalyzeSettings, UploadStart
from ..serializers import upload_out, video_out

router = APIRouter()


_upload_locks: dict[str, asyncio.Lock] = {}


_complete_locks: dict[str, threading.Lock] = {}


def _partial(upload_id: str) -> Path:
    return get_settings().partial_dir / f"{upload_id}.part"


@router.post("/api/uploads", status_code=201)
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
    if existing and existing["size"] != body.size:
        _partial(existing["id"]).unlink(missing_ok=True)  # same name, different file: start over
        db.delete_upload(existing["id"])
        existing = None
    if not existing:
        check_video_limits(ws, body.size)
        open_limit = max(3, s.max_active_videos)
        if db.workspace_usage(ws)["open_uploads"] >= open_limit:
            raise HTTPException(429, f"You have {open_limit} unfinished uploads. Finish or cancel one first.")
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


@router.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str, ws: str = Workspace) -> dict[str, Any]:
    return upload_out(upload_or_404(upload_id, ws))


@router.put("/api/uploads/{upload_id}")
async def put_chunk(upload_id: str, request: Request, offset: int = Query(..., ge=0),
                    ws: str = Workspace) -> dict[str, Any]:
    """Append one chunk. ``offset`` must equal the bytes already received."""
    u = upload_or_404(upload_id, ws)
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


@router.post("/api/uploads/{upload_id}/complete", status_code=201)
def complete_upload(upload_id: str, ws: str = Workspace) -> dict[str, Any]:
    upload_or_404(upload_id, ws)
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
    # The upload was admitted at start; don't throw away gigabytes now because the queue is long.
    check_video_limits(ws, global_queue=False)
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


@router.delete("/api/uploads/{upload_id}", status_code=204)
def cancel_upload(upload_id: str, ws: str = Workspace) -> None:
    upload_or_404(upload_id, ws)
    _partial(upload_id).unlink(missing_ok=True)
    db.delete_upload(upload_id)
    _upload_locks.pop(upload_id, None)
