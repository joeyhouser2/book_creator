"""Rasterize interior PDF pages to PNG for in-browser preview (via PyMuPDF)."""

from __future__ import annotations

import fitz  # PyMuPDF


def page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_page(pdf_path: str, index: int, dpi: int = 130) -> bytes:
    """Return page `index` (0-based) as PNG bytes."""
    with fitz.open(pdf_path) as doc:
        index = max(0, min(index, doc.page_count - 1))
        pix = doc[index].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
