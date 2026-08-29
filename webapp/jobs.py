"""Persist build jobs so a server restart doesn't lose them.

A narration can run for hours. Keeping jobs in a plain dict meant that
restarting the server -- or it crashing -- threw away the log, the progress,
and the links to everything that had already been written to disk, even though
the files themselves were fine. This keeps the record in SQLite alongside the
in-memory view, so the UI can list past builds and reopen a finished book.

Writes are throttled: the log grows by a line every few hundred milliseconds
during a build and there is no reason to hit the disk for each one.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    log        TEXT NOT NULL DEFAULT '[]',
    artifacts  TEXT NOT NULL DEFAULT '{}',
    progress   TEXT,
    pages      INTEGER NOT NULL DEFAULT 0,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""

# Fields that live in a job dict and are mirrored to their own column.
_COLUMNS = ("title", "status", "pages", "error")


class JobStore:
    """Thread-safe SQLite-backed job record."""

    def __init__(self, db_path: str = "cache/jobs.db", *, min_write_gap: float = 2.0):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()
        self._last_write: dict[str, float] = {}
        self._min_gap = min_write_gap
        self._reap_interrupted()

    def _reap_interrupted(self) -> None:
        """A job marked running at startup died with the previous process.

        Saying so is better than showing a spinner forever; the files it
        managed to write are still on disk, and the TTS cache means restarting
        it is cheap.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'interrupted', updated_at = ? "
                "WHERE status = 'running'", (time.time(),))
            self._conn.commit()

    # ----------------------------------------------------------------- #
    def create(self, job_id: str, title: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs (id, title, status, created_at, "
                "updated_at) VALUES (?, ?, 'running', ?, ?)",
                (job_id, title, now, now))
            self._conn.commit()
        self._last_write[job_id] = now

    def save(self, job_id: str, job: dict, *, force: bool = False) -> None:
        """Mirror a job dict to the database, throttled unless forced.

        Always force on a status change: a finished build that shows as
        running because its write was throttled away is the one state that
        actually misleads.
        """
        now = time.time()
        if not force and now - self._last_write.get(job_id, 0.0) < self._min_gap:
            return
        self._last_write[job_id] = now
        values = {k: job.get(k) for k in _COLUMNS}
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET title = ?, status = ?, pages = ?, error = ?, "
                "log = ?, artifacts = ?, progress = ?, updated_at = ? WHERE id = ?",
                (values["title"] or "", values["status"] or "running",
                 int(values["pages"] or 0), values["error"],
                 json.dumps(job.get("log", [])),
                 json.dumps(job.get("artifacts", {}), default=str),
                 json.dumps(job["progress"]) if job.get("progress") else None,
                 now, job_id))
            self._conn.commit()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def recent(self, limit: int = 25) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        out = []
        for r in rows:
            job = _row_to_job(r)
            art = job.get("artifacts") or {}
            out.append({
                "id": job["id"], "title": job["title"], "status": job["status"],
                "created_at": job["created_at"], "pages": job["pages"],
                "error": job["error"],
                "has_pdf": bool(art.get("pdf")),
                "has_cover": bool(art.get("cover")),
                "has_epub": bool(art.get("epub")),
                "audio": (art.get("audio") or {}).get("format")
                         if art.get("audio") else None,
            })
        return out

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _row_to_job(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "pages": row["pages"],
        "error": row["error"],
        "log": json.loads(row["log"] or "[]"),
        "artifacts": json.loads(row["artifacts"] or "{}"),
        "progress": json.loads(row["progress"]) if row["progress"] else None,
    }
