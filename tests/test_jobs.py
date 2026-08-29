"""Build records surviving a restart."""

from __future__ import annotations

import time

import pytest

from webapp.jobs import JobStore


@pytest.fixture
def store(tmp_path):
    s = JobStore(str(tmp_path / "jobs.db"), min_write_gap=0.0)
    yield s
    s.close()


def _job(**kw):
    base = {"title": "Test Book", "status": "running", "pages": 0,
            "error": None, "log": [], "artifacts": {}, "progress": None}
    base.update(kw)
    return base


def test_create_and_read_back(store):
    store.create("abc", "Carmina")
    got = store.get("abc")
    assert got["title"] == "Carmina"
    assert got["status"] == "running"
    assert got["log"] == []


def test_unknown_job_is_none(store):
    assert store.get("nope") is None


def test_save_round_trips_log_and_artifacts(store):
    store.create("abc", "Carmina")
    store.save("abc", _job(status="done", pages=12,
                           log=["• one", "✓ two"],
                           artifacts={"pdf": "output/x.pdf",
                                      "audio": {"duration": "1h", "book": "x.m4b"}}))
    got = store.get("abc")
    assert got["status"] == "done"
    assert got["pages"] == 12
    assert got["log"] == ["• one", "✓ two"]
    assert got["artifacts"]["audio"]["duration"] == "1h"


def test_save_is_throttled_but_force_always_writes(tmp_path):
    store = JobStore(str(tmp_path / "j.db"), min_write_gap=60.0)
    store.create("abc", "T")
    store.save("abc", _job(status="done", pages=5))
    # Throttled away: create() counts as the last write.
    assert store.get("abc")["status"] == "running"

    store.save("abc", _job(status="done", pages=5), force=True)
    # A finished build showing as running is the one genuinely misleading
    # state, so completion always forces the write.
    assert store.get("abc")["status"] == "done"
    store.close()


def test_running_jobs_are_reaped_on_restart(tmp_path):
    db = str(tmp_path / "j.db")
    first = JobStore(db, min_write_gap=0.0)
    first.create("abc", "Long narration")
    first.close()

    # A new process finds a job that no thread is working on any more.
    second = JobStore(db, min_write_gap=0.0)
    assert second.get("abc")["status"] == "interrupted"
    second.close()


def test_recent_is_newest_first_and_summarizes_artifacts(store):
    store.create("old", "Older")
    store.save("old", _job(status="done", artifacts={"pdf": "a.pdf"}), force=True)
    time.sleep(0.01)
    store.create("new", "Newer")
    store.save("new", _job(status="done",
                           artifacts={"pdf": "b.pdf", "epub": "b.epub",
                                      "cover": "b-cover.pdf",
                                      "audio": {"format": "m4b"}}), force=True)

    rows = store.recent()
    assert [r["id"] for r in rows] == ["new", "old"]
    assert rows[0]["has_pdf"] and rows[0]["has_epub"] and rows[0]["has_cover"]
    assert rows[0]["audio"] == "m4b"
    assert rows[1]["has_epub"] is False
    assert rows[1]["audio"] is None


def test_recent_respects_the_limit(store):
    for i in range(6):
        store.create(f"j{i}", f"Book {i}")
    assert len(store.recent(3)) == 3


def test_delete(store):
    store.create("abc", "T")
    store.delete("abc")
    assert store.get("abc") is None


def test_error_is_preserved(store):
    store.create("abc", "T")
    store.save("abc", _job(status="error", error="boom"), force=True)
    got = store.get("abc")
    assert got["status"] == "error"
    assert got["error"] == "boom"
