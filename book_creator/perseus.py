"""Perseus Digital Library as a source: the classical canon, already paired.

Gutenberg has almost no classical originals, and the `latin` corpus pairs its
sources with *machine* translation. Perseus has both sides: for ~789 works it
publishes the Greek or Latin text **and** a human English translation, as TEI
XML under one work directory.

That matters three ways:

* The English is a real translation, so nothing has to be disclosed as machine
  output on the copyright page.
* Both editions carry the same CTS citation structure (book / chapter /
  section), so the two sides can be anchored on their *own* reference scheme
  instead of being aligned statistically. See `pair_divisions`.
* The CTS metadata names the edition and its year, which is exactly what the
  pre-1929 public-domain check needs -- Gutendex never had that.

Two GitHub API calls index the whole catalogue; per-work metadata comes from
raw.githubusercontent, which is a CDN rather than the rate-limited API.
"""

from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests

CACHE_DIR = Path("cache")
DB_PATH = CACHE_DIR / "perseus.db"
USER_AGENT = "book_creator/0.1 (personal POD project; Perseus index)"

REPOS = {"greekLit": "grc", "latinLit": "lat"}
TREE_API = "https://api.github.com/repos/PerseusDL/canonical-{repo}/git/trees/master?recursive=1"
RAW = "https://raw.githubusercontent.com/PerseusDL/canonical-{repo}/master/data/{path}"

_CTS_NS = {"ti": "http://chs.harvard.edu/xmlns/cts"}
_TEI_NS = {"t": "http://www.tei-c.org/ns/1.0"}

# data/<textgroup>/<work>/<textgroup>.<work>.<edition>.xml
_WORK_FILE = re.compile(r"^data/([^/]+)/([^/]+)/\1\.\2\.([^.]+)\.xml$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id         TEXT PRIMARY KEY,     -- greekLit:tlg0032.tlg006
    repo       TEXT NOT NULL,
    textgroup  TEXT NOT NULL,
    work       TEXT NOT NULL,
    author     TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    language   TEXT NOT NULL DEFAULT '',
    src_file   TEXT NOT NULL DEFAULT '',
    src_desc   TEXT NOT NULL DEFAULT '',
    tgt_file   TEXT NOT NULL DEFAULT '',
    tgt_desc   TEXT NOT NULL DEFAULT '',
    tgt_year   INTEGER,
    search     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_works_lang ON works(language);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class PerseusError(RuntimeError):
    """The Perseus catalogue or a text could not be fetched."""


def searchable(text: str) -> str:
    """Fold to lowercase Latin for matching -- see pg_catalog.searchable."""
    from .pg_catalog import searchable as _fold
    return _fold(text)


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
def _connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def available(db_path: str | Path = DB_PATH) -> bool:
    if not Path(db_path).is_file():
        return False
    try:
        with _connect(db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def status(db_path: str | Path = DB_PATH) -> dict:
    if not available(db_path):
        return {"available": False, "works": 0, "age_days": None,
                "path": str(db_path)}
    with _connect(db_path) as conn:
        works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        by_lang = {r["language"]: r["n"] for r in conn.execute(
            "SELECT language, COUNT(*) n FROM works GROUP BY language")}
        row = conn.execute(
            "SELECT value FROM meta WHERE key='built_at'").fetchone()
    built = float(row["value"]) if row else 0.0
    return {"available": True, "works": works, "by_language": by_lang,
            "path": str(db_path), "built_at": built,
            "age_days": round((time.time() - built) / 86400, 1) if built else None}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _tree(repo: str, sess: requests.Session) -> list[str]:
    r = sess.get(TREE_API.format(repo=repo), timeout=90)
    if r.status_code != 200:
        raise PerseusError(
            f"Could not list canonical-{repo} (HTTP {r.status_code}). The "
            "GitHub API allows 60 unauthenticated requests an hour; if you have "
            "been rebuilding repeatedly, wait and retry.")
    data = r.json()
    if data.get("truncated"):
        raise PerseusError(f"canonical-{repo}'s file listing came back truncated.")
    return [x["path"] for x in data.get("tree", [])]


def _paired_works(paths: list[str]) -> dict[tuple[str, str], dict]:
    """Works that have BOTH a source edition and an English translation.

    A source-only work is no use here: this project exists to print the two
    side by side, and the corpus already covers machine-translating what has
    no English.
    """
    found: dict[tuple[str, str], dict] = {}
    for p in paths:
        m = _WORK_FILE.match(p)
        if not m:
            continue
        tg, wk, edition = m.groups()
        slot = found.setdefault((tg, wk), {"src": [], "tgt": []})
        if "-eng" in edition:
            slot["tgt"].append(p)
        elif "-grc" in edition or "-lat" in edition:
            slot["src"].append(p)
    return {k: v for k, v in found.items() if v["src"] and v["tgt"]}


def _text(node) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


_YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")


def _parse_work_cts(xml: str) -> dict:
    """Title, and the edition/translation descriptions with their years."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    out = {"title": _text(root.find("ti:title", _CTS_NS))}
    for tag, key in (("ti:edition", "src"), ("ti:translation", "tgt")):
        node = root.find(tag, _CTS_NS)
        if node is None:
            continue
        desc = _text(node.find("ti:description", _CTS_NS))
        out[f"{key}_desc"] = desc
        years = _YEAR.findall(desc)
        if years:
            out[f"{key}_year"] = int(years[-1])
    return out


def build(*, refresh: bool = False, db_path: str | Path = DB_PATH,
          log=None, workers: int = 16) -> dict:
    """Index every Perseus work that has a source text and an English pair."""
    def say(msg: str) -> None:
        if log:
            log(msg)

    if available(db_path) and not refresh:
        return status(db_path)

    sess = _session()
    rows: list[tuple] = []
    for repo, lang in REPOS.items():
        say(f"• Listing canonical-{repo}…")
        paired = _paired_works(_tree(repo, sess))
        say(f"• {len(paired)} work(s) in {repo} have an English translation; "
            "fetching their metadata…")

        def one(item, repo=repo, lang=lang):
            (tg, wk), files = item
            meta = {}
            try:
                r = sess.get(RAW.format(repo=repo, path=f"{tg}/{wk}/__cts__.xml"),
                             timeout=30)
                if r.status_code == 200:
                    meta = _parse_work_cts(r.text)
            except requests.RequestException:
                pass
            return (tg, wk), files, meta

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, paired.items()))

        # Author names live one level up, and there are far fewer textgroups
        # than works, so they are fetched once each rather than per work.
        groups = sorted({tg for (tg, _), _, _ in results})
        say(f"• Fetching {len(groups)} author name(s)…")

        def group_name(tg, repo=repo):
            try:
                r = sess.get(RAW.format(repo=repo, path=f"{tg}/__cts__.xml"),
                             timeout=30)
                if r.status_code == 200:
                    return tg, _text(ET.fromstring(r.text).find(
                        "ti:groupname", _CTS_NS))
            except (requests.RequestException, ET.ParseError):
                pass
            return tg, ""

        with ThreadPoolExecutor(max_workers=workers) as pool:
            authors = dict(pool.map(group_name, groups))

        for (tg, wk), files, meta in results:
            title = meta.get("title") or wk
            author = authors.get(tg, "")
            rows.append((
                f"{repo}:{tg}.{wk}", repo, tg, wk, author, title, lang,
                sorted(files["src"])[0], meta.get("src_desc", ""),
                sorted(files["tgt"])[0], meta.get("tgt_desc", ""),
                meta.get("tgt_year"),
                searchable(f"{title} {author} {tg} {wk}"),
            ))

    if not rows:
        raise PerseusError("No paired works found — the catalogue looks empty.")

    with _connect(db_path) as conn:
        conn.execute("DELETE FROM works")
        conn.executemany(
            "INSERT OR REPLACE INTO works (id, repo, textgroup, work, author, "
            "title, language, src_file, src_desc, tgt_file, tgt_desc, tgt_year, "
            "search) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES "
                     "('built_at', ?)", (str(time.time()),))
        conn.commit()

    out = status(db_path)
    say(f"✓ Perseus index ready: {out['works']} paired work(s) — "
        + ", ".join(f"{n} {lang}" for lang, n in out["by_language"].items()))
    return out


# --------------------------------------------------------------------------- #
# Searching
# --------------------------------------------------------------------------- #
def search(query: str = "", language: str | None = None, page: int = 1, *,
           limit: int = 40, db_path: str | Path = DB_PATH) -> dict:
    """Search indexed works. Same result shape the other sources use."""
    if not available(db_path):
        raise PerseusError(
            "No Perseus index yet. Build one with "
            "`python make_book.py --update-perseus`.")

    q = (query or "").strip()
    where, params = [], []
    if q:
        where.append("(search LIKE ? OR title LIKE ? OR author LIKE ?)")
        params += [f"%{searchable(q)}%", f"%{q}%", f"%{q}%"]
    if language:
        where.append("language = ?")
        params.append(language)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with _connect(db_path) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM works {clause}", params).fetchone()[0]
        offset = max(0, (max(1, page) - 1) * limit)
        rows = conn.execute(f"""
            SELECT * FROM works {clause}
             ORDER BY CASE WHEN search LIKE ? THEN 0 ELSE 1 END,
                      author, title LIMIT ? OFFSET ?
        """, [*params, f"{searchable(q)}%", limit, offset]).fetchall()

    return {"count": total, "has_next": offset + limit < total,
            "source": "perseus",
            "results": [_row_dict(r) for r in rows]}


def _row_dict(r: sqlite3.Row) -> dict:
    year = r["tgt_year"]
    return {
        "id": r["id"], "title": r["title"], "author": r["author"] or "Unknown",
        "language": r["language"],
        "source_edition": r["src_desc"], "translation_edition": r["tgt_desc"],
        "translation_year": year,
        # US public domain is publication before 1929. Reported, never assumed:
        # a missing year is "unknown", not "fine".
        "pd_status": ("ok" if year and year < 1929
                      else "check" if year else "unknown"),
    }


def get(work_id: str, *, db_path: str | Path = DB_PATH) -> dict:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM works WHERE id = ?",
                           (work_id,)).fetchone()
    if row is None:
        raise PerseusError(f"No Perseus work {work_id!r} in the index.")
    out = _row_dict(row)
    out.update({"repo": row["repo"], "src_file": row["src_file"],
                "tgt_file": row["tgt_file"]})
    return out


# --------------------------------------------------------------------------- #
# Fetching the texts
# --------------------------------------------------------------------------- #
@dataclass
class Division:
    """One citable unit, identified by its full citation path.

    `path` is the work's own reference, outermost first -- ("1", "2", "3") is
    book 1, chapter 2, section 3. Matching on this is what makes the two
    editions line up exactly.
    """

    path: tuple[str, ...]
    title: str
    text: str

    @property
    def ref(self) -> str:
        return ".".join(self.path)

    @property
    def top(self) -> str:
        """The outermost reference — the book, for grouping into chapters."""
        return self.path[0] if self.path else ""


def fetch_xml(repo: str, path: str, *, sess: requests.Session | None = None) -> str:
    sess = sess or _session()
    url = RAW.format(repo=repo, path=path.removeprefix("data/"))
    r = sess.get(url, timeout=60)
    if r.status_code != 200:
        raise PerseusError(f"Could not fetch {url} (HTTP {r.status_code}).")
    r.encoding = "utf-8"
    return r.text


def divisions(xml: str) -> list[Division]:
    """Split a TEI edition into its FINEST citable units.

    Perseus nests structure as `<div type="textpart" subtype="book|chapter|
    section" n="...">`. Taking the deepest level rather than the outermost is
    the whole point: Xenophon's Anabasis has 7 books but 1,469 sections, and a
    section is one to three sentences. Anchoring there means a sentence
    aligner never works over more than a few sentences at a time, so the
    off-by-one drift that length-based alignment accumulates over a whole book
    simply cannot happen.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise PerseusError(f"Malformed TEI: {exc}") from exc

    body = root.find(".//t:text/t:body", _TEI_NS)
    if body is None:
        raise PerseusError("TEI has no <body>.")

    leaves: list[Division] = []
    _collect_leaves(body, (), leaves)
    if not leaves:
        # Some editions carry no textpart divisions at all; treat the whole
        # body as one unit rather than losing the text.
        return [Division(path=("1",), title="", text=_tei_text(body))]
    return leaves


def _collect_leaves(node, path: tuple[str, ...], out: list) -> None:
    """Depth-first walk emitting only textparts that contain no textparts."""
    for child in node:
        tag = child.tag.split("}")[-1]
        if tag == "div" and child.get("type") == "textpart":
            ref = child.get("n") or str(len(out) + 1)
            here = path + (ref,)
            if _has_textpart_child(child):
                _collect_leaves(child, here, out)
            else:
                head = child.find("t:head", _TEI_NS)
                out.append(Division(path=here, title=_text(head),
                                    text=_tei_text(child)))
        else:
            _collect_leaves(child, path, out)


def _has_textpart_child(node) -> bool:
    for child in node.iter():
        if child is node:
            continue
        if child.tag.split("}")[-1] == "div" and child.get("type") == "textpart":
            return True
    return False


# Editorial apparatus that is not part of the text being read.
_DROP_TAGS = {"note", "bibl", "ref", "milestone", "pb", "gap", "orig", "sic",
              "del", "figure", "teiHeader"}


def _tei_text(node) -> str:
    """Readable text from a TEI subtree, paragraphs kept apart.

    Notes, apparatus and page-break milestones are dropped: they belong to the
    edition, not the work, and would otherwise be printed and read aloud.
    """
    pieces: list[str] = []

    def walk(el):
        tag = el.tag.split("}")[-1]
        if tag in _DROP_TAGS:
            if el.tail and el.tail.strip():
                pieces.append(el.tail)
            return
        if tag in ("p", "l", "lg", "div", "head", "sp", "quote"):
            pieces.append("\n\n" if tag in ("p", "lg", "div", "head") else "\n")
        if el.text:
            pieces.append(el.text)
        for child in el:
            walk(child)
        if el.tail:
            pieces.append(el.tail)

    walk(node)
    text = "".join(pieces)
    # Perseus marks Greek elision with U+02BC MODIFIER LETTER APOSTROPHE,
    # which several otherwise-excellent Greek faces lack (GFS Didot among
    # them), so it prints as a missing-glyph box. U+2019 is typographically
    # the same mark and is present in every font shipped here.
    text = text.replace("ʼ", "’")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def pair_divisions(src: list[Division], tgt: list[Division],
                   log=None) -> list[tuple[Division, Division]]:
    """Match the two editions on their own citation references.

    This is the payoff of using Perseus: both sides are numbered by the work's
    canonical scheme, so "Book 3" on one side is "Book 3" on the other by
    definition. No statistical alignment is involved at this level, and a
    division present on only one side is skipped rather than being smeared
    across its neighbours.
    """
    by_ref = {d.ref: d for d in tgt}
    paired = [(s, by_ref[s.ref]) for s in src if s.ref in by_ref]

    if log:
        if paired:
            depth = len(paired[0][0].path)
            unit = {1: "division", 2: "chapter", 3: "section"}.get(depth, "unit")
            log(f"• Anchored {len(paired)} {unit}(s) on the CTS citation scheme "
                "— exact, not statistical. Sentence alignment now runs inside "
                "each one, so it cannot drift across the book.")
        missing = len(src) - len(paired)
        if missing:
            log(f"  ⚠  {missing} source division(s) have no counterpart in the "
                "translation and were skipped.")
    if not paired:
        # Refs disagree entirely (different citation schemes); fall back to
        # order, which is what the Gutenberg path would have done anyway.
        n = min(len(src), len(tgt))
        if log:
            log("  ⚠  The two editions use different citation schemes; "
                f"pairing the first {n} division(s) by order instead.")
        paired = list(zip(src[:n], tgt[:n]))
    return paired


def fetch_pair(work_id: str, *, db_path: str | Path = DB_PATH,
               log=None) -> tuple[list[Division], list[Division], dict]:
    """Download both editions of a work and split them into divisions."""
    meta = get(work_id, db_path=db_path)
    sess = _session()
    if log:
        log(f"• Fetching Perseus {work_id} (source + translation)…")
    src = divisions(fetch_xml(meta["repo"], meta["src_file"], sess=sess))
    tgt = divisions(fetch_xml(meta["repo"], meta["tgt_file"], sess=sess))
    if log:
        log(f"• {len(src)} source division(s), {len(tgt)} translation division(s).")
    return src, tgt, meta
