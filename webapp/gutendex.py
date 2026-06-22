"""Search the Project Gutenberg catalog via the Gutendex JSON API.

Gutendex (https://gutendex.com) is a free, read-only API over the Gutenberg
catalog. The `id` it returns IS the Gutenberg ebook id our fetch module needs.
"""

from __future__ import annotations

import requests

API = "https://gutendex.com/books"
_HEADERS = {"User-Agent": "book_creator/0.1 (local UI)"}


def search(query: str, language: str | None = None, page: int = 1) -> dict:
    params: dict = {"search": query, "page": page}
    if language:
        params["languages"] = language
    resp = requests.get(API, params=params, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for b in data.get("results", []):
        formats = b.get("formats", {})
        has_text = any(
            mime.startswith("text/plain") for mime in formats
        )
        results.append({
            "id": b["id"],
            "title": b.get("title", "(untitled)"),
            "authors": ", ".join(a["name"] for a in b.get("authors", [])) or "Unknown",
            "languages": b.get("languages", []),
            "downloads": b.get("download_count", 0),
            "has_text": has_text,
        })
    return {
        "count": data.get("count", 0),
        "has_next": bool(data.get("next")),
        "results": results,
    }
