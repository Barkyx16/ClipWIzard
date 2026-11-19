"""Sessions (videos), highlights and the workspace key."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import db, jobs, pipeline
from ..config import get_settings
from ..guards import Workspace, check_video_limits, highlight_or_404, video_or_404
from ..media import ffmpeg, importer
from ..schemas import (
    ALLOWED_EXTENSIONS,
    MAX_CLIP_SECONDS,
    AnalyzeSettings,
    HighlightCreate,
    HighlightPatch,
    ImportRequest,
    LayoutUpdate,
    VideoPatch,
    WorkspaceSwitch,
)
from ..serializers import highlight_out, video_out
from ..workspace import set_cookie, valid_key, workspace_id

router = APIRouter()


@router.get("/api/workspace")
def get_workspace(request: Request) -> dict[str, str]:
    """The caller's workspace key, so they can open it on another device."""
    return {"key": request.state.workspace_key}


@router.post("/api/workspace")
def switch_workspace(body: WorkspaceSwitch, request: Request, response: Response) -> dict[str, Any]:
    if not valid_key(body.key):
        raise HTTPException(422, "That doesn't look like a workspace key")
    request.state.workspace_switched = True
    set_cookie(request, response, body.key)
    return {"ok": True, "videos": len(db.list_videos(workspace_id(body.key)))}


@router.get("/api/videos")
def list_videos(ws: str = Workspace) -> list[dict[str, Any]]:
    return [video_out(v) for v in db.list_videos(ws)]


@router.post("/api/videos", status_code=201)
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
    check_video_limits(ws, int(declared) if declared and declared.isdigit() else 0)
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


@router.post("/api/videos/import", status_code=201)
def import_link(body: ImportRequest, ws: str = Workspace) -> dict[str, Any]:
    """Download a video from YouTube/Twitch/... or a direct file link, then analyse it."""
    try:
        importer.classify(body.url)
    except importer.ImportFailed as e:
        raise HTTPException(400, str(e)) from e
    check_video_limits(ws)
    video_id = db.new_id()
    settings = AnalyzeSettings(**body.model_dump(exclude={"url"}))
    v = db.create_video(
        id=video_id, original_name=importer.display_name(body.url), filename=f"{video_id}.pending",
        size_bytes=0, status="downloading", stage="Waiting to download", progress=0.0,
        settings=settings.model_dump(), workspace=ws, import_url=body.url.strip(),
    )
    jobs.submit(pipeline.import_video, video_id)
    return video_out(v, include_children=True)


@router.get("/api/videos/{video_id}")
def get_video(video_id: str, ws: str = Workspace) -> dict[str, Any]:
    return video_out(video_or_404(video_id, ws), include_children=True)


@router.get("/api/videos/{video_id}/timeline")
def get_timeline(video_id: str, ws: str = Workspace) -> dict[str, Any]:
    video_or_404(video_id, ws)
    t = db.get_timeline(video_id)
    if t is None:
        return {"hop": 1.0, "excitement": [], "audio": [], "motion": [], "sprites": None}
    return {"hop": t["hop"], **t["data"]}


@router.post("/api/videos/{video_id}/reanalyze")
def reanalyze(video_id: str, body: AnalyzeSettings, ws: str = Workspace) -> dict[str, Any]:
    v = video_or_404(video_id, ws)
    if v["status"] in ("queued", "analyzing", "downloading"):
        raise HTTPException(409, "This video is already being processed")
    if not (get_settings().uploads_dir / v["filename"]).exists():
        raise HTTPException(409, "The video file is missing, so it can't be re-scanned")
    check_video_limits(ws)
    db.update_video(video_id, settings={**body.model_dump(), "auto_export": None}, status="queued", stage="Queued",
                    progress=0.0, error=None)
    jobs.submit(pipeline.analyze_video, video_id)
    return video_out(db.get_video(video_id), include_children=True)  # type: ignore[arg-type]


@router.patch("/api/videos/{video_id}")
def rename_video(video_id: str, body: VideoPatch, ws: str = Workspace) -> dict[str, Any]:
    video_or_404(video_id, ws)
    name = re.sub(r"[\x00-\x1f]", "", body.name).strip()
    if not name:
        raise HTTPException(422, "Name can't be empty")
    db.update_video(video_id, original_name=name[:200])
    return video_out(db.get_video(video_id), include_children=True)  # type: ignore[arg-type]


@router.put("/api/videos/{video_id}/layout")
def update_layout(video_id: str, body: LayoutUpdate, ws: str = Workspace) -> dict[str, Any]:
    """Save the facecam rectangle (normalised 0..1) used by the facecam layout."""
    v = video_or_404(video_id, ws)
    layout = dict(v.get("layout") or {})
    if body.facecam is None:
        layout.pop("facecam", None)
    else:
        layout["facecam"] = body.facecam.model_dump()
    db.update_video(video_id, layout=layout)
    return layout


@router.delete("/api/videos/{video_id}", status_code=204)
def delete_video(video_id: str, ws: str = Workspace) -> None:
    v = video_or_404(video_id, ws)
    if v["status"] in ("queued", "analyzing", "downloading") or db.video_has_active_jobs(video_id):
        raise HTTPException(409, "Wait for processing and renders to finish before deleting")
    pipeline.remove_video_files(v)
    db.delete_video(video_id)


@router.patch("/api/highlights/{highlight_id}")
def patch_highlight(highlight_id: str, body: HighlightPatch, ws: str = Workspace) -> dict[str, Any]:
    h = highlight_or_404(highlight_id, ws)
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


@router.post("/api/videos/{video_id}/highlights", status_code=201)
def create_highlight(video_id: str, body: HighlightCreate, ws: str = Workspace) -> dict[str, Any]:
    """Save a hand-picked range as a highlight."""
    v = video_or_404(video_id, ws)
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


@router.delete("/api/highlights/{highlight_id}", status_code=204)
def delete_highlight(highlight_id: str, ws: str = Workspace) -> None:
    h = highlight_or_404(highlight_id, ws)
    if h.get("thumbnail"):
        (get_settings().thumbs_dir / h["thumbnail"]).unlink(missing_ok=True)
    db.delete_highlight(highlight_id)
