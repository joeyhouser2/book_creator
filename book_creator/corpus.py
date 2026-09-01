"""Read a work out of the `latin` repo's corpus as a ready-made parallel text.

The sibling project at github.com/joeyhouser2/latin maintains a SQLite corpus
(`data/corpus.db`) of Latin and Greek works whose segments are *already* one
sentence per row with their English alongside:

    documents -> sections -> segments(latin_text, english_text, english_styled)

Because that pipeline translates per-segment, Latin segment *i* already
corresponds to English segment *i*. So a corpus-sourced book skips fetch,
clean, segment, and align entirely: each row becomes one Bead directly, with
no statistical alignment and therefore no drift to proofread for.

The database is opened **read-only** (SQLite URI `mode=ro`) -- this project
never writes to the corpus.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import settings
from .model import Bead, Chapter

# Where to look for the latin repo, in order. Override with LATIN_REPO.
_REPO_CANDIDATES = (
    "../latin",
    "~/Documents/GitHub/latin",
)
_DB_RELATIVE = Path("data") / "corpus.db"

# Licences safe to publish from without further checking. Everything else is
# surfaced to the user as-is, because the corpus deliberately records awkward
# cases ("no explicit license published", CC BY-NC-ND, ...) rather than
# pretending they are free.
_PERMISSIVE_MARKERS = ("public domain", "cc0", "cc by-sa", "cc-by-sa", "cc by ")
_RESTRICTIVE_MARKERS = ("nc-nd", "-nc", "noncommercial", "non-commercial",
                        "no explicit license", "research use", "check per-text",
                        "paywall")


class CorpusError(RuntimeError):
    """The corpus database is missing, unreadable, or has nothing usable."""


# --------------------------------------------------------------------------- #
# Locating and opening the database
# --------------------------------------------------------------------------- #
# Settings keys the corpus honours (written by the UI, see webapp/server.py).
# LATIN_REPO stays supported for CLI and CI use; a stored setting wins because
# it is the more deliberate of the two -- someone typed it into this app.
SETTING_REPO = "latin_repo"
SETTING_DB = "corpus_db"


def _as_db(p: Path) -> Path:
    """Interpret a path as *the database*, or as a checkout containing one.

    Decided on what the path actually is rather than on its suffix: the latin
    repo's snapshots are named `corpus.db.bak-preOcrFix-20260720201447`, whose
    suffix is the timestamp, not `.db`. A suffix test would take those for
    directories and go looking for `data/corpus.db` inside them.
    """
    if p.is_file():
        return p
    if p.is_dir():
        return p / _DB_RELATIVE
    # Neither exists: guess from the name so the error names the right thing.
    return p if ".db" in p.name else p / _DB_RELATIVE


def _configured() -> tuple[str | None, str | None]:
    """(repo, database) as stored by the settings UI, if anything is."""
    stored = settings.load()
    return stored.get(SETTING_REPO), stored.get(SETTING_DB)


def find_db(path: str | None = None) -> Path:
    """Resolve the corpus database path, or raise CorpusError.

    Accepts either the repo root or the .db file itself, so `LATIN_REPO` can
    point at a checkout and `--corpus-db` at a copied-out database.

    Order: an explicit argument, then the stored setting, then LATIN_REPO, then
    the usual sibling locations. A location that was *named* -- by argument or
    by setting -- is never silently replaced by one found elsewhere: reading a
    different corpus than the one you chose would make every count and every
    build quietly wrong.
    """
    named: list[tuple[Path, str]] = []
    repo_setting, db_setting = _configured()
    if path:
        named.append((Path(path).expanduser(), "the path given"))
    if db_setting:
        named.append((Path(db_setting).expanduser(), f"the {SETTING_DB} setting"))
    elif repo_setting:
        named.append((Path(repo_setting).expanduser(), f"the {SETTING_REPO} setting"))

    for p, source in named:
        cand = _as_db(p)
        if cand.is_file():
            return cand.resolve()
        raise CorpusError(f"{source} ({p}) has no corpus database: "
                          f"expected {cand} to exist.")

    candidates = [_as_db(Path(raw).expanduser())
                  for raw in (os.environ.get("LATIN_REPO"), *_REPO_CANDIDATES) if raw]
    for c in candidates:
        if c.is_file():
            return c.resolve()

    tried = "\n  ".join(str(c) for c in candidates)
    raise CorpusError(
        "Could not find the latin corpus database. Set LATIN_REPO to the "
        "latin repo checkout (or pass an explicit path). Tried:\n  " + tried)


def databases(repo: str | Path | None = None) -> list[dict]:
    """Every corpus database file in a checkout's data/ directory.

    The latin repo keeps dated `.bak-*` snapshots beside the live database, so
    a reader can be pointed at one to see the corpus as it was. Only the live
    `corpus.db` can be *written* to, though -- the latin repo's scripts open
    `data/corpus.db` by name -- so each entry says whether passes can run
    against it, and the UI refuses to offer them for the rest.
    """
    root = Path(repo).expanduser() if repo else None
    if root is None:
        try:
            root = find_db().parent.parent
        except CorpusError:
            return []
    data_dir = root if root.name == "data" else root / "data"
    if not data_dir.is_dir():
        return []

    out = []
    for p in sorted(data_dir.glob("corpus.db*")):
        # -wal and -shm are SQLite's own sidecars, not databases to choose.
        if p.suffix in (".db-wal", ".db-shm") or p.name.endswith(("-wal", "-shm")):
            continue
        out.append({
            "path": str(p.resolve()),
            "name": p.name,
            "size_mb": round(p.stat().st_size / 1024 ** 2, 1),
            "live": p.name == "corpus.db",
            "writable": p.name == "corpus.db",
        })
    return out


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open the corpus read-only. The caller owns closing it."""
    db = find_db(path)
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def licence_risk(licence: str | None) -> str:
    """Classify a document's licence string: ok | check | unknown.

    Advisory only -- it never blocks a build, it just tells the UI which
    sources need a human to read the terms before publishing.
    """
    if not licence:
        return "unknown"
    low = licence.lower()
    if any(m in low for m in _RESTRICTIVE_MARKERS):
        return "check"
    if any(m in low for m in _PERMISSIVE_MARKERS):
        return "ok"
    return "unknown"


# --------------------------------------------------------------------------- #
# Browsing
# --------------------------------------------------------------------------- #
@dataclass
class CorpusDoc:
    """One work in the corpus, with its translation coverage counted."""

    id: int
    title: str
    author: str
    language: str            # "la" | "grc"
    language_stage: str
    century: int | None
    genre: str
    source: str
    license: str
    translation_status: str
    segments: int = 0
    translated: int = 0
    styled: int = 0
    sections: int = 0

    @property
    def coverage(self) -> float:
        return (self.translated / self.segments) if self.segments else 0.0

    @property
    def pending_translation(self) -> int:
        """Segments with no English yet -- the work a translate pass would do."""
        return max(0, self.segments - self.translated)

    @property
    def pending_styling(self) -> int:
        """Translated segments the stylizer has not been over yet.

        Counted against `translated`, not `segments`: the stylizer rewrites an
        existing English crib, so untranslated segments are not work it can do.
        """
        return max(0, self.translated - self.styled)

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in (
            "id", "title", "author", "language", "language_stage", "century",
            "genre", "source", "license", "translation_status", "segments",
            "translated", "styled", "sections")}
        d["coverage"] = round(self.coverage, 3)
        d["pending_translation"] = self.pending_translation
        d["pending_styling"] = self.pending_styling
        d["license_risk"] = licence_risk(self.license)
        return d


def _row_to_doc(r: sqlite3.Row, counts: dict) -> CorpusDoc:
    return CorpusDoc(
        id=r["id"], title=r["title"], author=r["author"] or "Unknown",
        language=r["language"], language_stage=r["language_stage"],
        century=r["century"], genre=r["genre"] or "",
        source=r["source"] or "", license=r["license"] or "",
        translation_status=r["translation_status"],
        segments=counts.get("segments") or 0,
        translated=counts.get("translated") or 0,
        styled=counts.get("styled") or 0,
        sections=counts.get("sections") or 0,
    )


def _count_for_docs(conn: sqlite3.Connection, doc_ids: list[int]) -> dict[int, dict]:
    """Segment / translation / style counts for a handful of documents.

    Counted only for the page of documents actually being shown: the corpus has
    ~1.3M segments, so aggregating all of them for every search would be slow,
    while aggregating for 40 ids rides the doc_id + section_id indexes.
    """
    if not doc_ids:
        return {}
    marks = ",".join("?" * len(doc_ids))
    rows = conn.execute(f"""
        SELECT sec.doc_id                     AS doc_id,
               COUNT(s.id)                    AS segments,
               COUNT(DISTINCT sec.id)         AS sections,
               SUM(CASE WHEN s.english_text IS NOT NULL
                         AND TRIM(s.english_text) <> '' THEN 1 ELSE 0 END)
                                              AS translated,
               SUM(CASE WHEN s.english_styled IS NOT NULL
                         AND TRIM(s.english_styled) <> '' THEN 1 ELSE 0 END)
                                              AS styled
          FROM sections sec
          LEFT JOIN segments s ON s.section_id = sec.id
         WHERE sec.doc_id IN ({marks})
         GROUP BY sec.doc_id
    """, doc_ids).fetchall()
    return {r["doc_id"]: dict(r) for r in rows}


def facets(*, conn: sqlite3.Connection | None = None,
           db_path: str | None = None, top_authors: int = 60) -> dict:
    """The values worth filtering on, with counts, for the UI's dropdowns.

    Substring search over 13k works is a poor way to find anything when you do
    not already know the Latin form of a name, so author / genre / stage /
    century are offered as picklists instead. Authors are capped at the most
    prolific, because the long tail is thousands of single-work entries.
    """
    own = conn is None
    conn = conn or connect(db_path)
    try:
        def group(column: str, limit: int | None = None) -> list[dict]:
            sql = (f"SELECT {column} AS v, COUNT(*) AS n FROM documents "
                   f"WHERE {column} IS NOT NULL AND TRIM({column}) <> '' "
                   f"GROUP BY v ORDER BY n DESC")
            if limit:
                sql += f" LIMIT {int(limit)}"
            return [{"value": r["v"], "count": r["n"]} for r in conn.execute(sql)]

        centuries = [
            {"value": r["v"], "count": r["n"]}
            for r in conn.execute(
                "SELECT century AS v, COUNT(*) AS n FROM documents "
                "WHERE century IS NOT NULL GROUP BY v ORDER BY v")
        ]
        return {
            "languages": group("language"),
            "stages": group("language_stage"),
            "genres": group("genre"),
            "authors": group("author", top_authors),
            "centuries": centuries,
        }
    finally:
        if own:
            conn.close()


def search_documents(query: str = "", *, language: str | None = None,
                     stage: str | None = None, author: str | None = None,
                     genre: str | None = None,
                     century_from: int | None = None,
                     century_to: int | None = None,
                     translated_only: bool = True, styled_only: bool = False,
                     needs: str | None = None,
                     limit: int = 40, offset: int = 0,
                     conn: sqlite3.Connection | None = None,
                     db_path: str | None = None) -> dict:
    """Search the corpus by title/author substring, with optional facet filters.

    `translated_only` drops works with no English at all -- the usual case,
    since a parallel-text book needs both sides; `styled_only` narrows further
    to works the stylizer has been over.

    `needs` looks the other way, at what is *un*finished, so a work can be
    found in order to be worked on rather than printed (see corpus_jobs.py):
    "translation" keeps works with segments that have no English yet, and
    "styling" keeps works whose English exists but has not been through the
    Victorian stylizer. Most of the corpus is unfinished, so these are the
    filters that matter when queueing a pass rather than choosing a book.

    All of them are applied *after* counting (coverage is not stored on the
    document row), so the returned `count` is the number of documents matching
    the text/metadata filters.
    """
    own = conn is None
    conn = conn or connect(db_path)
    try:
        where, params = [], []
        if query.strip():
            where.append("(d.title LIKE ? OR IFNULL(d.author,'') LIKE ?)")
            params += [f"%{query.strip()}%"] * 2
        if language:
            where.append("d.language = ?")
            params.append(language)
        if stage:
            where.append("d.language_stage = ?")
            params.append(stage)
        if author:
            where.append("d.author = ?")
            params.append(author)
        if genre:
            where.append("d.genre = ?")
            params.append(genre)
        if century_from is not None:
            where.append("d.century >= ?")
            params.append(int(century_from))
        if century_to is not None:
            where.append("d.century <= ?")
            params.append(int(century_to))
        clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM documents d {clause}", params).fetchone()[0]

        # Over-fetch when filtering on coverage, so a page is not left
        # near-empty by untranslated works being dropped after the fact.
        post_filtered = translated_only or styled_only or needs
        fetch = limit * 4 if post_filtered else limit
        rows = conn.execute(f"""
            SELECT d.* FROM documents d {clause}
             ORDER BY d.id LIMIT ? OFFSET ?
        """, [*params, fetch, offset]).fetchall()

        counts = _count_for_docs(conn, [r["id"] for r in rows])
        docs: list[CorpusDoc] = []
        for r in rows:
            doc = _row_to_doc(r, counts.get(r["id"], {}))
            if translated_only and not doc.translated:
                continue
            if styled_only and not doc.styled:
                continue
            # "Needs styling" deliberately requires something to style: a work
            # with no English at all needs translating first, and listing it
            # here would offer a pass that has nothing to do.
            if needs == "translation" and doc.translated >= doc.segments:
                continue
            if needs == "styling" and not (doc.translated and doc.styled < doc.translated):
                continue
            docs.append(doc)
            if len(docs) >= limit:
                break

        out = {
            "count": total,
            "results": [d.as_dict() for d in docs],
            "has_next": offset + fetch < total,
        }
        if not docs:
            out["hint"] = (
                "No match. Free-text search is a substring of title or author, "
                "so try the Latin form of a name ('Augustinus', not "
                "'Augustine') — or drop the text and use the author / genre / "
                "period filters instead. Unticking 'only works that already "
                "have English' reveals works still awaiting translation, which "
                "an original-only edition can still print.")
        return out
    finally:
        if own:
            conn.close()


def document(doc_id: int, *, conn: sqlite3.Connection | None = None,
             db_path: str | None = None) -> CorpusDoc:
    """Full metadata (with counts) for one document."""
    own = conn is None
    conn = conn or connect(db_path)
    try:
        r = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if r is None:
            raise CorpusError(f"No document {doc_id} in the corpus.")
        return _row_to_doc(r, _count_for_docs(conn, [doc_id]).get(doc_id, {}))
    finally:
        if own:
            conn.close()


def pending(doc_id: int, *, section_range: tuple[int, int] | None = None,
            conn: sqlite3.Connection | None = None,
            db_path: str | None = None) -> dict:
    """How much work each pass has left, over a range of sections or all of it.

    The whole-document counts on CorpusDoc answer "is this work finished"; this
    answers "is there anything to do in the part I am about to print", which is
    a different number as soon as a range is chosen -- and the one worth
    checking before spending a model load. Section numbering matches `outline`:
    1-based over `ord`, inclusive.
    """
    own = conn is None
    conn = conn or connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM sections WHERE doc_id = ? ORDER BY ord",
            (doc_id,)).fetchall()
        if section_range:
            first, last = section_range
            rows = rows[max(1, first) - 1:min(len(rows), last)]
        ids = [r["id"] for r in rows]
        if not ids:
            return {"segments": 0, "translation": 0, "styling": 0}

        marks = ",".join("?" * len(ids))
        row = conn.execute(f"""
            SELECT COUNT(*) AS segments,
                   SUM(CASE WHEN english_text IS NULL OR TRIM(english_text) = ''
                            THEN 1 ELSE 0 END) AS translation,
                   SUM(CASE WHEN english_text IS NOT NULL
                             AND TRIM(english_text) <> ''
                             AND (english_styled IS NULL
                                  OR TRIM(english_styled) = '')
                            THEN 1 ELSE 0 END) AS styling
              FROM segments WHERE section_id IN ({marks})
        """, ids).fetchone()
        return {"segments": row["segments"] or 0,
                "translation": row["translation"] or 0,
                "styling": row["styling"] or 0}
    finally:
        if own:
            conn.close()


def outline(doc_id: int, *, conn: sqlite3.Connection | None = None,
            db_path: str | None = None) -> list[dict]:
    """Sections of a document, 1-based, for the same range picker Gutenberg uses."""
    own = conn is None
    conn = conn or connect(db_path)
    try:
        rows = conn.execute("""
            SELECT sec.id, sec.label, sec.ord,
                   COUNT(s.id) AS segments,
                   SUM(CASE WHEN s.english_text IS NOT NULL
                             AND TRIM(s.english_text) <> '' THEN 1 ELSE 0 END)
                       AS translated
              FROM sections sec
              LEFT JOIN segments s ON s.section_id = sec.id
             WHERE sec.doc_id = ?
             GROUP BY sec.id
             ORDER BY sec.ord
        """, (doc_id,)).fetchall()
        return [{"index": i, "title": r["label"],
                 "segments": r["segments"] or 0,
                 "translated": r["translated"] or 0}
                for i, r in enumerate(rows, start=1)]
    finally:
        if own:
            conn.close()


# The source column to read the original from. Critical and epigraphic editions
# wrap letters in editorial sigla -- "<A>ltus", "Imp(erator)", "[Aug]ustus" --
# which the latin repo keeps in `latin_text` for scholarly display and strips
# into `embed_text` (letters kept, brackets dropped). A printed parallel text
# wants the letters without the apparatus, and a narrator certainly does, so
# the stripped copy is preferred where one exists. `embed_text` is only stored
# when stripping actually changed something, hence COALESCE.
_SRC_CLEAN = "COALESCE(NULLIF(TRIM(s.embed_text), ''), s.latin_text)"
_SRC_RAW = "s.latin_text"


def _src_column(strip_markup: bool, alias: str = "s") -> str:
    col = _SRC_CLEAN if strip_markup else _SRC_RAW
    return col.replace("s.", f"{alias}.")


def sample(doc_id: int, *, limit: int = 12, prefer_styled: bool = True,
           strip_markup: bool = True, conn: sqlite3.Connection | None = None,
           db_path: str | None = None) -> list[dict]:
    """First few aligned pairs, so the UI can show what the book will look like."""
    own = conn is None
    conn = conn or connect(db_path)
    try:
        rows = conn.execute(f"""
            SELECT {_src_column(strip_markup)} AS src,
                   s.latin_text, s.english_text, s.english_styled
              FROM segments s JOIN sections sec ON s.section_id = sec.id
             WHERE sec.doc_id = ?
             ORDER BY sec.ord, s.ord LIMIT ?
        """, (doc_id, limit)).fetchall()
        out = []
        for r in rows:
            styled = (r["english_styled"] or "").strip()
            plain = (r["english_text"] or "").strip()
            out.append({
                "src": (r["src"] or "").strip(),
                "tgt": (styled if (prefer_styled and styled) else plain),
                "styled": bool(styled),
                "marked_up": (r["src"] or "") != (r["latin_text"] or ""),
            })
        return out
    finally:
        if own:
            conn.close()


# --------------------------------------------------------------------------- #
# Loading a work as pre-aligned chapters
# --------------------------------------------------------------------------- #
@dataclass
class CorpusLoad:
    """A work pulled from the corpus, ready to render."""

    doc: CorpusDoc
    chapters: list[Chapter] = field(default_factory=list)
    beads: int = 0
    styled_used: int = 0
    untranslated: int = 0
    demarked: int = 0


def load_chapters(doc_id: int, *, section_range: tuple[int, int] | None = None,
                  prefer_styled: bool = True, skip_untranslated: bool = True,
                  strip_markup: bool = True,
                  conn: sqlite3.Connection | None = None,
                  db_path: str | None = None) -> CorpusLoad:
    """Build Chapters straight from the corpus -- one Bead per stored segment.

    `prefer_styled` uses `english_styled` (the latin repo's Victorian stylizer
    output) when a segment has it, falling back to plain `english_text`.
    `skip_untranslated` drops segments with no English at all; turn it off to
    print those source-only, the way an unmatched alignment insertion is.
    `strip_markup` prints the letters without the editorial apparatus (see
    _SRC_CLEAN); turn it off for a scholarly edition that should show sigla.
    """
    own = conn is None
    conn = conn or connect(db_path)
    try:
        doc = document(doc_id, conn=conn)
        sections = conn.execute(
            "SELECT id, label, ord FROM sections WHERE doc_id = ? ORDER BY ord",
            (doc_id,)).fetchall()
        if not sections:
            raise CorpusError(f"Document {doc_id} ({doc.title}) has no sections.")

        if section_range:
            first, last = section_range
            sections = sections[max(1, first) - 1:min(len(sections), last)]

        load = CorpusLoad(doc=doc)
        for sec in sections:
            rows = conn.execute(f"""
                SELECT {_src_column(strip_markup)} AS src,
                       s.latin_text, s.english_text, s.english_styled
                  FROM segments s WHERE s.section_id = ? ORDER BY s.ord
            """, (sec["id"],)).fetchall()

            beads: list[Bead] = []
            src_segments: list[str] = []
            tgt_segments: list[str] = []
            for r in rows:
                src = (r["src"] or "").strip()
                if not src:
                    continue
                if src != (r["latin_text"] or "").strip():
                    load.demarked += 1
                styled = (r["english_styled"] or "").strip()
                plain = (r["english_text"] or "").strip()
                tgt = styled if (prefer_styled and styled) else plain
                if not tgt:
                    load.untranslated += 1
                    if skip_untranslated:
                        continue
                elif prefer_styled and styled:
                    load.styled_used += 1
                beads.append(Bead(src=[src], tgt=[tgt] if tgt else []))
                src_segments.append(src)
                if tgt:
                    tgt_segments.append(tgt)

            if not beads:
                continue
            load.chapters.append(Chapter(
                title=sec["label"], src_segments=src_segments,
                tgt_segments=tgt_segments, beads=beads))
            load.beads += len(beads)

        if not load.chapters:
            why = ("has no translated segments in the selected range — build it "
                   "as an original-only edition (sides: src) to print it without "
                   "English" if skip_untranslated else
                   "has no segments in the selected range")
            raise CorpusError(f"Document {doc_id} ({doc.title}) {why}.")
        return load
    finally:
        if own:
            conn.close()


def source_note(doc: CorpusDoc, *, translated: bool = True) -> str:
    """Provenance line for the copyright page.

    Corpus English is machine translation produced by the latin repo's own
    NLLB fine-tunes, so no third-party translator holds copyright on it -- but
    that has to be *disclosed*, not quietly passed off as a human translation,
    so say so plainly. Pass translated=False for an original-only edition,
    where there is no English in the book to disclose anything about.
    """
    bits = []
    if doc.source:
        bits.append(f"Original text: {doc.source}.")
    if doc.license:
        bits.append(f"Source licence: {doc.license}.")
    if translated:
        bits.append("The English rendering is machine translation, not a "
                    "previously published human translation.")
    return " ".join(bits)
