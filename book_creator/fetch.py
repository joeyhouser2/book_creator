"""Download and clean Project Gutenberg plain-text files."""

from __future__ import annotations

import re
from pathlib import Path

import requests

CACHE_DIR = Path("cache")
USER_AGENT = "book_creator/0.1 (personal POD project; contact via local use)"

GUTENDEX_API = "https://gutendex.com/books"

# Gutenberg wraps every text in a START/END license banner. These markers are
# stable across the corpus.
_START_RE = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
_END_RE = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)


def _candidate_urls(gid: int) -> list[str]:
    return [
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}-0.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}.txt",
    ]


def fetch_gutenberg(gid: int, *, refresh: bool = False) -> str:
    """Return the cleaned body text for a Gutenberg ebook id, caching the raw file."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"pg{gid}.txt"

    if cache_file.exists() and not refresh:
        raw = cache_file.read_text(encoding="utf-8", errors="replace")
    else:
        raw = _download(gid)
        cache_file.write_text(raw, encoding="utf-8")

    return strip_gutenberg_boilerplate(raw)


def _download(gid: int) -> str:
    last_err: Exception | None = None
    for url in _candidate_urls(gid):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            if resp.status_code == 200 and resp.text.strip():
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            last_err = exc
    raise RuntimeError(f"Could not download Gutenberg #{gid}: {last_err}")


def load_text(*, path: str | None = None, gid: int | None = None, log=None) -> str:
    """Load from a local file or a Gutenberg id.

    A local `.epub` is unpacked into plain text (see epub_reader); anything
    else is read as already-clean text.
    """
    if path:
        p = Path(path)
        if p.suffix.lower() == ".epub":
            from . import epub_reader
            return epub_reader.read_epub(p, log=log)
        return p.read_text(encoding="utf-8", errors="replace")
    if gid is not None:
        return fetch_gutenberg(gid)
    raise ValueError("Either path or gid must be provided.")


def search_gutenberg(query: str, language: str | None = None, page: int = 1, *,
                     fallback: bool = True, log=None) -> dict:
    """Search the Project Gutenberg catalog via the Gutendex JSON API.

    Gutendex (https://gutendex.com) is a free, read-only API over the
    Gutenberg catalog; the `id` it returns IS the ebook id `fetch_gutenberg`
    needs. Shared by the web UI (webapp/gutendex.py) and the librarian agent
    (librarian.py).

    Gutendex is a small volunteer service and does go down. When it does --
    and only then -- this falls back to a local index of Gutenberg's own
    published catalog (see pg_catalog), building it on first need. gutenberg.org
    itself being up is what actually matters, since that is where the texts
    come from; losing the *search* to a third party's outage is not a good
    enough reason to be unable to build a book.
    """
    try:
        return _search_gutendex(query, language, page)
    except requests.RequestException as exc:
        if not fallback:
            raise
        return _search_local(query, language, page, reason=exc, log=log)


def _search_local(query: str, language: str | None, page: int, *,
                  reason: Exception, log=None) -> dict:
    from . import pg_catalog

    def say(msg: str) -> None:
        if log:
            log(msg)

    say(f"  ⚠  Gutendex is not responding ({type(reason).__name__}); "
        "using the local Gutenberg catalog instead.")
    try:
        if not pg_catalog.available():
            pg_catalog.build(log=log)
        out = pg_catalog.search(query, language, page)
    except pg_catalog.CatalogError as exc:
        raise RuntimeError(
            f"Gutendex is down ({reason}), and the local catalog fallback also "
            f"failed: {exc}. The Latin corpus and Local files tabs do not need "
            "either service.") from exc
    out["degraded"] = (
        "Gutendex is down, so these results come from Gutenberg's own catalog. "
        "Download counts are unavailable and translators are folded in with "
        "authors; ids, titles and languages are exact.")
    return out


def _search_gutendex(query: str, language: str | None, page: int) -> dict:
    params: dict = {"search": query, "page": page}
    if language:
        params["languages"] = language
    resp = requests.get(GUTENDEX_API, params=params, headers={"User-Agent": USER_AGENT},
                        timeout=20)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for b in data.get("results", []):
        formats = b.get("formats", {})
        has_text = any(mime.startswith("text/plain") for mime in formats)
        results.append({
            "id": b["id"],
            "title": b.get("title", "(untitled)"),
            "authors": ", ".join(a["name"] for a in b.get("authors", [])) or "Unknown",
            "translators": ", ".join(a["name"] for a in b.get("translators", [])),
            "languages": b.get("languages", []),
            "downloads": b.get("download_count", 0),
            "has_text": has_text,
        })
    out = {
        "count": data.get("count", 0),
        "has_next": bool(data.get("next")),
        "results": results,
        "source": "gutendex",
    }
    if not results:
        out["hint"] = (
            "No matches. Gutendex search is close to a literal substring match on "
            "title/author, not semantic — try a broader query, e.g. just the "
            "author's surname. The English edition of a foreign work is often "
            "catalogued under its original-language title."
        )
    return out


def gutenberg_metadata(gid: int) -> dict:
    """Look up a single Gutenberg edition's catalog metadata (title, real
    author/translator names, language) via Gutendex — the ground truth for
    who actually translated it, so callers don't have to guess from the text.
    """
    resp = requests.get(f"{GUTENDEX_API}/{gid}", headers={"User-Agent": USER_AGENT},
                        timeout=20)
    resp.raise_for_status()
    b = resp.json()
    return {
        "id": b.get("id", gid),
        "title": b.get("title", "(untitled)"),
        "authors": ", ".join(a["name"] for a in b.get("authors", [])) or "Unknown",
        "translators": ", ".join(a["name"] for a in b.get("translators", [])),
        "languages": b.get("languages", []),
    }


def strip_gutenberg_boilerplate(text: str) -> str:
    """Remove the Gutenberg license header/footer, keeping only the work itself."""
    start = _START_RE.search(text)
    if start:
        text = text[start.end():]
        # The line after START is usually a "Produced by..." credit; drop the
        # remainder of that physical line.
        text = text.split("\n", 1)[-1] if "\n" in text else text
    end = _END_RE.search(text)
    if end:
        text = text[: end.start()]
    return text.strip()


def load_divisions(*, path: str | None = None, gid: int | None = None,
                   mode: str = "prose", poem_titles: bool = False,
                   log=None) -> list[tuple[str, str]]:
    """Load a source as its divisions: [(title, body), ...].

    An EPUB is asked for its own structure -- the spine orders its content
    documents and headings mark divisions inside them -- because flattening it
    to one string and then recovering headings with a regex loses exactly the
    information the file already carries. Everything else is plain text, where
    heading detection is the only option there has ever been.

    Falls back to detecting headings in the flattened text when an EPUB's own
    structure yields nothing useful: a file converted so poorly that every
    document is one blob may still have "CHAPTER I" lines in it.
    """
    from . import segment

    if path and Path(path).suffix.lower() == ".epub":
        from . import epub_reader
        divisions = epub_reader.read_divisions(path, log=log)
        if len(divisions) > 1:
            return divisions
        text = divisions[0][1]
        detected = segment.detect_chapters(text, mode=mode,
                                           poem_titles=poem_titles)
        if len(detected) > 1 and log:
            log(f"• The EPUB has no usable structure of its own; found "
                f"{len(detected)} division(s) in its text instead.")
        return detected

    text = load_text(path=path, gid=gid, log=log)
    return segment.detect_chapters(text, mode=mode, poem_titles=poem_titles)
