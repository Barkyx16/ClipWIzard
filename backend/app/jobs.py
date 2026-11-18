"""In-process background job runner.

Good enough for a single-server deployment. Swap for a real queue (RQ,
Celery, Arq...) when you need several machines doing the heavy lifting.

Two pools:
* ``default`` - analysis, imports and renders (CLIPWIZARD_WORKERS threads)
* ``transcribe`` - speech-to-text, one at a time, so transcripts waiting on
  the speech model never tie up the workers everyone else needs
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Literal

from . import db
from .config import get_settings

log = logging.getLogger(__name__)

Pool = Literal["default", "transcribe"]

_pools: dict[str, ThreadPoolExecutor] = {}
_lock = threading.Lock()
_closed = False
_users = 0  # app lifespans currently running (more than one only in tests)


class JobsClosed(RuntimeError):
    """Raised when work is submitted while the server is shutting down."""


def executor(pool: Pool = "default") -> ThreadPoolExecutor:
    with _lock:
        if _closed:
            raise JobsClosed("The server is shutting down")
        if pool not in _pools:
            workers = max(1, get_settings().workers) if pool == "default" else 1
            _pools[pool] = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"clipwizard-{pool}")
        return _pools[pool]


def submit(fn: Callable[..., None], *args: object, pool: Pool = "default") -> Future:
    fut = executor(pool).submit(fn, *args)

    def _log_error(f: Future) -> None:
        if not f.cancelled() and f.exception() is not None:
            log.error("Background job crashed", exc_info=f.exception())

    fut.add_done_callback(_log_error)
    return fut


def resume_interrupted() -> None:
    """Re-queue work that was in flight when the server last stopped."""
    from .pipeline import analyze_video, import_video, render

    for v in db.videos_with_status("downloading"):
        db.update_video(v["id"], stage="Download resumed", progress=0.0)
        submit(import_video, v["id"])
    for v in db.videos_with_status("queued", "analyzing"):
        db.update_video(v["id"], status="queued", stage="Queued (resumed)", progress=0.0)
        submit(analyze_video, v["id"])
    for c in db.clips_with_status("queued", "rendering"):
        db.update_clip(c["id"], status="queued", progress=0.0)
        submit(render, c["id"])
    # Transcripts are short and interactive: ask the user to retry rather than resume.
    for t in db.transcripts_with_status("queued", "running"):
        db.update_transcript(t["id"], status="failed", error="Interrupted by a server restart. Try again.")


def shutdown() -> None:
    """Stop accepting work once the last app lifespan has ended."""
    global _closed, _users
    with _lock:
        _users = max(0, _users - 1)
        if _users:
            return
        _closed = True
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.shutdown(wait=False, cancel_futures=True)


def reopen() -> None:
    """Called when the app starts: accept submissions."""
    global _closed, _users
    with _lock:
        _users += 1
        _closed = False
