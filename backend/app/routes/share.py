"""Public share links and their link-preview page."""

from __future__ import annotations

import html
import os
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from .. import db, pipeline
from ..config import FRONTEND_DIR, get_settings
from ..media import ffmpeg
from ..media.render import output_size
from ..serializers import poster_path

router = APIRouter()


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


@router.get("/api/share/{token}")
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


@router.get("/share/{token}/video.mp4", include_in_schema=False)
def shared_video(token: str) -> FileResponse:
    _, path = _shared_clip(token)
    return FileResponse(path, media_type="video/mp4", headers={**NOINDEX, "Cache-Control": "public, max-age=3600"})


@router.get("/share/{token}/download", include_in_schema=False)
def shared_download(token: str) -> FileResponse:
    c, path = _shared_clip(token)
    return FileResponse(path, media_type="video/mp4", filename=f"clipwizard-{c['id']}.mp4", headers=NOINDEX)


@router.get("/share/{token}/poster.jpg", include_in_schema=False)
def shared_poster(token: str) -> FileResponse:
    """Preview image for link unfurls (Discord, X, iMessage...)."""
    c, path = _shared_clip(token)
    poster = poster_path(c["id"])
    if not poster.exists():
        tmp = poster.with_name(f"{c['id']}.{secrets.token_hex(4)}.tmp.jpg")
        try:
            ffmpeg.extract_frame(path, min(1.0, max(0.0, (c["end"] - c["start"]) / 3)), tmp, width=720)
            os.replace(tmp, poster)  # readers never see a half-written file
        except ffmpeg.FFmpegError as e:
            raise HTTPException(404, "No preview available") from e
        finally:
            tmp.unlink(missing_ok=True)
    return FileResponse(poster, media_type="image/jpeg", headers={**NOINDEX, "Cache-Control": "public, max-age=86400"})


def _public_base(request: Request) -> str:
    configured = os.environ.get("CLIPWIZARD_PUBLIC_URL", "").rstrip("/")
    if configured:
        return configured
    scheme, host = request.url.scheme, request.headers.get("host", request.url.netloc)
    if os.environ.get("CLIPWIZARD_TRUST_PROXY") == "1":
        scheme = request.headers.get("x-forwarded-proto", scheme).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host", host).split(",")[0].strip()
    return f"{scheme}://{host}"


def _share_meta(request: Request, token: str) -> str:
    """Open Graph / Twitter tags so a pasted share link shows the clip."""
    try:
        c, _ = _shared_clip(token)
    except HTTPException:
        return '<meta name="robots" content="noindex">'
    info = shared_info(token, Response())
    v = db.get_video(c["video_id"]) or {}
    w, h = output_size(str((c.get("options") or {}).get("aspect", "vertical_blur")),
                       int(v.get("width") or 1920), int(v.get("height") or 1080))
    base = _public_base(request)
    page, video, poster = f"{base}/s/{token}", f"{base}{info['video_url']}", f"{base}/share/{token}/poster.jpg"
    desc = info["caption"] or "Clipped with ClipWizard"
    tags = {
        "og:site_name": "ClipWizard", "og:type": "video.other", "og:title": info["title"],
        "og:description": desc, "og:url": page, "og:image": poster,
        "og:video": video, "og:video:url": video, "og:video:type": "video/mp4",
        "og:video:width": str(w), "og:video:height": str(h),
    }
    if base.startswith("https://"):
        tags["og:video:secure_url"] = video
    out = [f'<meta property="{k}" content="{html.escape(v, quote=True)}">' for k, v in tags.items()]
    out += [
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{html.escape(info["title"], quote=True)}">',
        f'<meta name="twitter:image" content="{html.escape(poster, quote=True)}">',
        '<meta name="robots" content="noindex">',
    ]
    return "\n".join(out)


@router.get("/s/{token}", include_in_schema=False)
def share_page(token: str, request: Request) -> HTMLResponse:
    """The SPA's share page, with link-preview tags filled in on the server."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        doc = index.read_text(encoding="utf-8")
    else:  # API-only deployments still get a working preview + link
        doc = ('<!doctype html><html><head><meta charset="utf-8"><title>ClipWizard</title></head>'
               f'<body><a href="/share/{html.escape(token)}/video.mp4">Watch the clip</a></body></html>')
    return HTMLResponse(doc.replace("</head>", _share_meta(request, token) + "\n</head>", 1),
                        headers={"Referrer-Policy": "no-referrer"})
