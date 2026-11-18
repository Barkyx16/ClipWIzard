"""In-process background job runner.

Good enough for a single-server deployment. Swap for a real queue (RQ,
Celery, Arq...) when you need several machines doing the heavy lifting.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from . import db
from .config import get_settings

log = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max(1, get_settings().workers),
                                       thread_name_prefix="clipwizard-job")
    return _executor


def submit(fn: Callable[..., None], *args: object) -> Future:
    fut = executor().submit(fn, *args)

    def _log_error(f: Future) -> None:
        if f.exception() is not None:
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


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
