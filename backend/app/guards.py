"""Access checks (workspace ownership) and abuse limits shared by the routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException

from . import db
from .config import get_settings
from .workspace import current_workspace, same_workspace

Workspace = Depends(current_workspace)


def check_video_limits(ws: str, incoming_bytes: int = 0, global_queue: bool = True) -> None:
    s = get_settings()
    if global_queue and s.max_queue and db.queued_videos() >= s.max_queue:
        raise HTTPException(429, "ClipWizard is very busy right now. Please try again in a few minutes.",
                            headers={"Retry-After": "60"})
    usage = db.workspace_usage(ws)
    if s.max_active_videos and usage["busy_videos"] >= s.max_active_videos:
        n = usage["busy_videos"]
        raise HTTPException(429, f"You already have {n} video{'s' if n != 1 else ''} processing. "
                                 "Wait for one to finish, then try again.")
    quota = int(s.workspace_quota_gb * 1024**3)
    if quota and usage["stored_bytes"] + incoming_bytes > quota:
        raise HTTPException(413, f"Your workspace is full ({s.workspace_quota_gb:g} GB). "
                                 "Delete old sessions or clips to make room.")


def check_render_limits(ws: str, adding: int = 1) -> None:
    s = get_settings()
    usage = db.workspace_usage(ws)
    if s.max_active_renders and usage["busy_clips"] + adding > s.max_active_renders:
        n = usage["busy_clips"]
        raise HTTPException(429, f"You have {n} clip{'s' if n != 1 else ''} rendering. "
                                 "Wait for some to finish, then export more.")


def video_or_404(video_id: str, ws: str) -> dict[str, Any]:
    v = db.get_video(video_id)
    if v is None or not same_workspace(v.get("workspace"), ws):
        raise HTTPException(404, "Video not found")
    return v


def clip_or_404(clip_id: str, ws: str) -> dict[str, Any]:
    c = db.get_clip(clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    v = db.get_video(c["video_id"])
    if v is None or not same_workspace(v.get("workspace"), ws):
        raise HTTPException(404, "Clip not found")
    return c


def highlight_or_404(highlight_id: str, ws: str) -> dict[str, Any]:
    h = db.get_highlight(highlight_id)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    v = db.get_video(h["video_id"])
    if v is None or not same_workspace(v.get("workspace"), ws):
        raise HTTPException(404, "Highlight not found")
    return h


def upload_or_404(upload_id: str, ws: str) -> dict[str, Any]:
    u = db.get_upload(upload_id)
    if u is None or not same_workspace(u["workspace"], ws):
        raise HTTPException(404, "Upload not found")
    return u
