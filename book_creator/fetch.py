"""Download and clean Project Gutenberg plain-text files."""

from __future__ import annotations

import re
from pathlib import Path

import requests

CACHE_DIR = Path("cache")
USER_AGENT = "book_creator/0.1 (personal POD project; contact via local use)"

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


def load_text(*, path: str | None = None, gid: int | None = None) -> str:
    """Load from a local file (already-clean text) or a Gutenberg id."""
    if path:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    if gid is not None:
        return fetch_gutenberg(gid)
    raise ValueError("Either path or gid must be provided.")


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
