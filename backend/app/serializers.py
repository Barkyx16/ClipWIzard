"""Turn database rows into API responses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import db
from .config import get_settings
from .schemas import CHUNK_SIZE


def poster_path(clip_id: str) -> Path:
    """Preview image used by share links (written next to the clip)."""
    return get_settings().clips_dir / f"{clip_id}.jpg"


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
        "options": {k: v for k, v in (c["options"] or {}).items() if k != "caption_words"},
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


def transcript_out(t: dict[str, Any]) -> dict[str, Any]:
    return {"id": t["id"], "video_id": t["video_id"], "start": t["start"], "end": t["end"],
            "status": t["status"], "words": t["words"], "error": t["error"]}


def upload_out(u: dict[str, Any]) -> dict[str, Any]:
    return {"id": u["id"], "filename": u["filename"], "size": u["size"], "received": u["received"],
            "chunk_size": CHUNK_SIZE}
