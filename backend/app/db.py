"""Tiny SQLite persistence layer.

Each call opens its own connection so it is safe to use from the API threads
and the background worker threads at the same time.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    duration REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    has_audio INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    settings TEXT NOT NULL DEFAULT '{}',
    thumbnail TEXT,
    ai_used INTEGER NOT NULL DEFAULT 0,
    workspace TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS timelines (
    video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    hop REAL NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS highlights (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    peak REAL NOT NULL,
    score REAL NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    caption TEXT,
    hashtags TEXT NOT NULL DEFAULT '[]',
    signals TEXT NOT NULL DEFAULT '{}',
    thumbnail TEXT,
    ai_enriched INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_highlights_video ON highlights(video_id);

CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    highlight_id TEXT,
    start REAL NOT NULL,
    end REAL NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    filename TEXT,
    size_bytes INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_video ON clips(video_id);
"""

_JSON_FIELDS = {"settings", "hashtags", "signals", "options", "data", "layout"}
_BOOL_FIELDS = {"has_audio", "ai_used", "ai_enriched"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _db_path() -> Path:
    return get_settings().db_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    ("videos", "workspace", "TEXT"),
    ("videos", "layout", "TEXT NOT NULL DEFAULT '{}'"),
    ("clips", "transcript", "TEXT"),
    ("clips", "warning", "TEXT"),
    ("videos", "import_url", "TEXT"),
]


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_workspace ON videos(workspace)")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for k in list(out):
        if k in _JSON_FIELDS and isinstance(out[k], str):
            out[k] = json.loads(out[k])
        elif k in _BOOL_FIELDS and out[k] is not None:
            out[k] = bool(out[k])
    return out


def _encode(values: dict[str, Any]) -> dict[str, Any]:
    enc = {}
    for k, v in values.items():
        if k in _JSON_FIELDS and not isinstance(v, str):
            enc[k] = json.dumps(v)
        elif k in _BOOL_FIELDS and isinstance(v, bool):
            enc[k] = int(v)
        else:
            enc[k] = v
    return enc


def _insert(table: str, values: dict[str, Any]) -> None:
    values = _encode(values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    with connect() as conn:
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))


def _update(table: str, row_id: str, values: dict[str, Any]) -> None:
    if not values:
        return
    values = _encode(values)
    sets = ", ".join(f"{k} = ?" for k in values)
    with connect() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))


# ---------------------------------------------------------------- videos


def create_video(**fields: Any) -> dict[str, Any]:
    now = time.time()
    fields.setdefault("id", new_id())
    fields.setdefault("status", "uploaded")
    fields.update(created_at=now, updated_at=now)
    _insert("videos", fields)
    return get_video(fields["id"])  # type: ignore[return-value]


def get_video(video_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone())


def list_videos(workspace: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE workspace = ? ORDER BY created_at DESC", (workspace,)
        ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def update_video(video_id: str, **fields: Any) -> None:
    fields["updated_at"] = time.time()
    _update("videos", video_id, fields)


def delete_video(video_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))


def videos_with_status(*statuses: str) -> list[dict[str, Any]]:
    marks = ", ".join("?" for _ in statuses)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM videos WHERE status IN ({marks})", statuses).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


# ---------------------------------------------------------------- timeline


def save_timeline(video_id: str, hop: float, data: dict[str, list[float]]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO timelines (video_id, hop, data) VALUES (?, ?, ?)",
            (video_id, hop, json.dumps(data)),
        )


def get_timeline(video_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(
            conn.execute("SELECT * FROM timelines WHERE video_id = ?", (video_id,)).fetchone()
        )


# ---------------------------------------------------------------- highlights


def replace_highlights(video_id: str, highlights: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM highlights WHERE video_id = ?", (video_id,))
        for h in highlights:
            values = _encode({**h, "video_id": video_id})
            cols = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            conn.execute(
                f"INSERT INTO highlights ({cols}) VALUES ({marks})", tuple(values.values())
            )


def list_highlights(video_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM highlights WHERE video_id = ? ORDER BY rank ASC", (video_id,)
        ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_highlight(highlight_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(
            conn.execute("SELECT * FROM highlights WHERE id = ?", (highlight_id,)).fetchone()
        )


def update_highlight(highlight_id: str, **fields: Any) -> None:
    _update("highlights", highlight_id, fields)


def insert_highlight(video_id: str, highlight: dict[str, Any]) -> None:
    values = _encode({**highlight, "video_id": video_id})
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    with connect() as conn:
        conn.execute(f"INSERT INTO highlights ({cols}) VALUES ({marks})", tuple(values.values()))


def delete_highlight(highlight_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT video_id FROM highlights WHERE id = ?", (highlight_id,)).fetchone()
        conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
        if row:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM highlights WHERE video_id = ? ORDER BY rank ASC", (row["video_id"],))]
            for rank, hid in enumerate(ids):
                conn.execute("UPDATE highlights SET rank = ? WHERE id = ?", (rank, hid))


def videos_older_than(cutoff: float) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE updated_at < ? AND status NOT IN ('queued', 'analyzing', 'downloading')",
            (cutoff,),
        ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


# ---------------------------------------------------------------- clips


def create_clip(**fields: Any) -> dict[str, Any]:
    now = time.time()
    fields.setdefault("id", new_id())
    fields.setdefault("status", "queued")
    fields.update(created_at=now, updated_at=now)
    _insert("clips", fields)
    return get_clip(fields["id"])  # type: ignore[return-value]


def get_clip(clip_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone())


def list_clips(video_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM clips WHERE video_id = ? ORDER BY created_at DESC", (video_id,)
        ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def update_clip(clip_id: str, **fields: Any) -> None:
    fields["updated_at"] = time.time()
    _update("clips", clip_id, fields)


def delete_clip(clip_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))


def clips_with_status(*statuses: str) -> list[dict[str, Any]]:
    marks = ", ".join("?" for _ in statuses)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM clips WHERE status IN ({marks})", statuses).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]
