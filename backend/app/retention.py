"""Optional automatic cleanup of old uploads for public deployments.

Set CLIPWIZARD_RETENTION_DAYS to delete sessions (source video, analysis,
thumbnails and rendered clips) that haven't been touched for that many days.
0 (the default) keeps everything forever.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time

from . import db
from .config import get_settings
from .pipeline import remove_video_files

log = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def retention_days() -> float:
    try:
        return max(0.0, float(os.environ.get("CLIPWIZARD_RETENTION_DAYS", "0")))
    except ValueError:
        return 0.0


def cleanup_once(days: float | None = None, now: float | None = None) -> int:
    """Delete sessions idle for more than ``days``. Returns how many were removed."""
    days = retention_days() if days is None else days
    if days <= 0:
        return 0
    cutoff = (now or time.time()) - days * 86400
    removed = 0
    for video in db.videos_older_than(cutoff):
        if any(c["status"] in ("queued", "rendering") for c in db.list_clips(video["id"])):
            continue
        remove_video_files(video)
        db.delete_video(video["id"])
        removed += 1
    if removed:
        log.info("Retention cleanup removed %d session(s) older than %g days", removed, days)
    return removed


def clear_stale_work() -> None:
    """Leftover scratch folders from jobs killed mid-way, and abandoned uploads."""
    settings = get_settings()
    work = settings.work_dir
    for child in work.iterdir() if work.exists() else []:
        if child.is_dir() and time.time() - child.stat().st_mtime > 6 * 3600:
            shutil.rmtree(child, ignore_errors=True)
    for up in db.uploads_older_than(time.time() - 2 * 86400):
        (settings.partial_dir / f"{up['id']}.part").unlink(missing_ok=True)
        db.delete_upload(up["id"])


def _loop() -> None:
    while not _stop.wait(3600):
        try:
            cleanup_once()
            clear_stale_work()
        except Exception:
            log.exception("Retention cleanup failed")


def start() -> None:
    global _thread
    try:
        clear_stale_work()
        cleanup_once()
    except Exception:
        log.exception("Initial cleanup failed")
    if retention_days() > 0 and _thread is None:
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="clipwizard-retention", daemon=True)
        _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _thread = None
