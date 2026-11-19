"""ClipWizard HTTP API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, jobs, retention
from .config import FRONTEND_DIR, get_settings
from .media import captions, ffmpeg, importer
from .ratelimit import RateLimitMiddleware
from .routes import clips, media, share, uploads, videos
from .schemas import ALLOWED_EXTENSIONS
from .workspace import WorkspaceMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clipwizard")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ffmpeg.ensure_available()
    jobs.reopen()
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
app.add_middleware(RateLimitMiddleware)


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


for _router in (videos.router, uploads.router, clips.router, share.router, media.router):
    app.include_router(_router)

# The SPA catch-all must come after every API route.
_frontend = FRONTEND_DIR
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
