"""Workspace-protected media files (uploads, thumbnails, renders)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import db, pipeline
from ..config import get_settings
from ..guards import Workspace
from ..workspace import same_workspace

router = APIRouter()


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


@router.get("/media/{kind}/{name}", include_in_schema=False)
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
