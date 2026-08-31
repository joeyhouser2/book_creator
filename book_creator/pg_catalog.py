"""Search Project Gutenberg from its own catalog, with no third-party API.

`fetch.search_gutenberg` normally goes through Gutendex, which is a small
volunteer-run service and does go down -- when it does, the Gutenberg tab is
dead even though gutenberg.org itself is fine and every book is still
downloadable.

Gutenberg publishes its whole catalog as one gzipped CSV (~5.6 MB, 79k rows).
Fetched once and indexed into SQLite, it answers searches locally in
milliseconds and keeps working whether or not Gutendex is up.

What it does NOT have, versus Gutendex: download counts, a separate
translator field (the CSV folds translators into Authors), and per-book format
lists. Those are conveniences; the ebook id, title, author and language -- the
things a build actually needs -- are all here.
"""

from __future__ import annotations

import csv
import gzip
import io
import sqlite3
import time
from pathlib import Path

import requests

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"
CACHE_DIR = Path("cache")
DB_PATH = CACHE_DIR / "pg_catalog.db"
USER_AGENT = "book_creator/0.1 (personal POD project; local catalog index)"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id        INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    authors   TEXT NOT NULL DEFAULT '',
    language  TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL DEFAULT '',
    subjects  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_books_lang ON books(language);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class CatalogError(RuntimeError):
    """The catalog could not be fetched or indexed."""


# --------------------------------------------------------------------------- #
# Building the index
# --------------------------------------------------------------------------- #
def _connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def available(db_path: str | Path = DB_PATH) -> bool:
    """Whether a usable local index exists."""
    if not Path(db_path).is_file():
        return False
    try:
        with _connect(db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def status(db_path: str | Path = DB_PATH) -> dict:
    """Row count and age, so the UI can offer to refresh a stale index."""
    if not available(db_path):
        return {"available": False, "books": 0, "age_days": None,
                "path": str(db_path)}
    with _connect(db_path) as conn:
        books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    built = float(row["value"]) if row else 0.0
    return {"available": True, "books": books, "path": str(db_path),
            "built_at": built,
            "age_days": round((time.time() - built) / 86400, 1) if built else None}


def build(*, refresh: bool = False, db_path: str | Path = DB_PATH,
          log=None) -> dict:
    """Download the catalog and index it. Returns status().

    Idempotent: an existing index is left alone unless `refresh` is set.
    """
    def say(msg: str) -> None:
        if log:
            log(msg)

    if available(db_path) and not refresh:
        return status(db_path)

    say(f"• Downloading the Gutenberg catalog ({CATALOG_URL})…")
    try:
        resp = requests.get(CATALOG_URL, timeout=120,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        text = gzip.decompress(resp.content).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - network, gzip, or encoding
        raise CatalogError(f"Could not fetch the Gutenberg catalog: {exc}") from exc

    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            gid = int(r["Text#"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((gid, (r.get("Title") or "").strip(),
                     (r.get("Authors") or "").strip(),
                     (r.get("Language") or "").strip(),
                     (r.get("Type") or "").strip(),
                     (r.get("Subjects") or "").strip()))

    if not rows:
        raise CatalogError("The catalog downloaded but contained no rows.")

    say(f"• Indexing {len(rows):,} catalog entries…")
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM books")
        conn.executemany(
            "INSERT OR REPLACE INTO books (id, title, authors, language, kind, "
            "subjects) VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES "
                     "('built_at', ?)", (str(time.time()),))
        conn.commit()
    out = status(db_path)
    say(f"✓ Local catalog ready: {out['books']:,} books in {out['path']}")
    return out


# --------------------------------------------------------------------------- #
# Searching
# --------------------------------------------------------------------------- #
def search(query: str, language: str | None = None, page: int = 1, *,
           limit: int = 32, db_path: str | Path = DB_PATH) -> dict:
    """Search the local index, in the shape `fetch.search_gutenberg` returns.

    Results are ordered by how well the title matches -- exact, then prefix,
    then anything containing the query -- because without download counts
    there is no popularity signal to fall back on, and a bare substring match
    buries the obvious answer.
    """
    if not available(db_path):
        raise CatalogError(
            "No local Gutenberg catalog yet. Build one with "
            "`python make_book.py --update-catalog`.")

    q = (query or "").strip()
    where, params = ["kind = 'Text'"], []
    if q:
        where.append("(title LIKE ? OR authors LIKE ?)")
        params += [f"%{q}%"] * 2
    if language:
        where.append("(language = ? OR language LIKE ?)")
        params += [language, f"%{language}%"]
    clause = " AND ".join(where)

    with _connect(db_path) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM books WHERE {clause}", params).fetchone()[0]
        offset = max(0, (max(1, page) - 1) * limit)
        rows = conn.execute(f"""
            SELECT * FROM books WHERE {clause}
             ORDER BY CASE
                 WHEN LOWER(title) = LOWER(?) THEN 0
                 WHEN LOWER(title) LIKE LOWER(?) THEN 1
                 ELSE 2 END,
                 LENGTH(title), id
             LIMIT ? OFFSET ?
        """, [*params, q, f"{q}%", limit, offset]).fetchall()

    results = [{
        "id": r["id"],
        "title": r["title"] or "(untitled)",
        # The CSV folds translators in with authors; splitting on ';' and
        # taking the first is the closest honest guess at the author proper.
        "authors": r["authors"].split(";")[0].strip() or "Unknown",
        "translators": "; ".join(p.strip() for p in r["authors"].split(";")[1:]),
        "languages": [x.strip() for x in r["language"].split(",") if x.strip()],
        "downloads": 0,          # not in the CSV
        "has_text": True,        # kind == 'Text' was required above
    } for r in rows]

    out = {"count": total, "results": results,
           "has_next": offset + limit < total, "source": "local-catalog"}
    if not results:
        out["hint"] = (
            "No match in the local Gutenberg catalog. It matches substrings of "
            "the title or author, so try the work's original-language title "
            "('de bello gallico', not 'gallic war') or just a surname.")
    return out
