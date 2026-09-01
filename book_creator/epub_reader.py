"""Read an EPUB you already own as a source text.

Gutenberg and the latin corpus both hand over clean text. A local EPUB does
not: it is a ZIP of XHTML documents, so it needs unpacking into the same kind
of plain text with blank-line paragraph breaks and recognizable headings that
`segment.detect_chapters` expects.

The other job here is honesty about quality. A large share of EPUBs in the
wild are page scans wrapped around OCR, and bad OCR is worse than useless in
this pipeline: it survives alignment (which only compares lengths or
embeddings), reaches the page looking like text, and gets read aloud
literally. `inspect()` reports what a file actually contains before you spend
a build on it.
"""

from __future__ import annotations

import re
import statistics
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Internet Archive scans carry a per-page confidence note. It is boilerplate,
# not content, and it also happens to be an honest quality signal.
_IA_ACCURACY = re.compile(
    r"The text on this page is estimated to be only\s*([\d.]+)%\s*accurate",
    re.I)
_IA_PAGE_HEAD = re.compile(r"^\s*Page\s+\d+\s*", re.I)

# Block-level elements become line breaks so paragraphs survive as paragraphs.
_BLOCK_TAGS = ("p", "div", "br", "li", "tr", "blockquote", "section",
               "article", "h1", "h2", "h3", "h4", "h5", "h6")
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


class EpubError(RuntimeError):
    """The file is not a readable EPUB, or has no extractable text."""


def _require_deps():
    try:
        import bs4  # noqa: F401
        import ebooklib  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise EpubError(
            "Reading EPUB input needs ebooklib and beautifulsoup4 "
            "(pip install -r requirements-epub.txt)") from exc


# --------------------------------------------------------------------------- #
# Quality inspection
# --------------------------------------------------------------------------- #
@dataclass
class EpubReport:
    """What a file actually contains, before committing a build to it."""

    path: str
    documents: int = 0
    images: int = 0
    characters: int = 0
    size_mb: float = 0.0
    # Mean of the accuracy figures an OCR scan reports about itself, if any.
    ocr_accuracy: float | None = None
    ocr_pages: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def chars_per_document(self) -> int:
        return round(self.characters / self.documents) if self.documents else 0

    @property
    def usable(self) -> bool:
        """Whether this is worth building from at all."""
        return self.characters > 500 and not any(
            w.startswith("Unusable") for w in self.warnings)

    def as_dict(self) -> dict:
        return {
            "path": self.path, "documents": self.documents,
            "images": self.images, "characters": self.characters,
            "size_mb": round(self.size_mb, 1),
            "chars_per_document": self.chars_per_document,
            "ocr_accuracy": self.ocr_accuracy, "ocr_pages": self.ocr_pages,
            "warnings": self.warnings, "usable": self.usable,
        }


def inspect(path: str | Path) -> EpubReport:
    """Report on an EPUB's contents without fully parsing it.

    Deliberately reads the ZIP directly rather than going through ebooklib:
    this has to work on malformed files too, since a file being broken is
    exactly what the caller wants to be told.
    """
    p = Path(path)
    if not p.is_file():
        raise EpubError(f"No such file: {p}")

    report = EpubReport(path=str(p), size_mb=p.stat().st_size / 1024 ** 2)
    try:
        zf = zipfile.ZipFile(p)
    except zipfile.BadZipFile as exc:
        raise EpubError(f"{p.name} is not a valid EPUB (not a ZIP archive).") from exc

    accuracies: list[float] = []
    with zf:
        for info in zf.infolist():
            name = info.filename.lower()
            if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                report.images += 1
            elif name.endswith((".html", ".xhtml", ".htm")):
                report.documents += 1
                try:
                    raw = zf.read(info).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - a bad member is not fatal
                    continue
                report.characters += len(_strip_tags(raw))
                for m in _IA_ACCURACY.finditer(raw):
                    accuracies.append(float(m.group(1)))

    report.ocr_pages = len(accuracies)
    if accuracies:
        report.ocr_accuracy = round(statistics.fmean(accuracies), 1)

    _add_warnings(report)
    return report


def _add_warnings(r: EpubReport) -> None:
    if r.documents == 0:
        r.warnings.append("Unusable: no text documents found in the archive.")
        return
    if r.characters < 500:
        r.warnings.append(
            "Unusable: almost no extractable text — this is probably a "
            "picture book or an image-only scan.")
    if r.ocr_accuracy is not None:
        # The file is telling you outright how bad its own OCR is.
        level = ("Unusable: " if r.ocr_accuracy < 80 else "")
        r.warnings.append(
            f"{level}the file reports its own OCR as {r.ocr_accuracy:.0f}% "
            f"accurate across {r.ocr_pages} page(s). Below about 95% the text "
            "is not worth printing or narrating — a narrator reads the errors "
            "aloud. Find a real ebook rather than a scan.")
    elif r.images >= max(10, r.documents * 0.8):
        r.warnings.append(
            f"{r.images} images against {r.documents} text documents — this "
            "looks like a page scan. Check the preview before building.")
    if r.chars_per_document and r.chars_per_document < 400 and not r.warnings:
        r.warnings.append(
            "Very little text per document; the extraction may be incomplete.")


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _strip_tags(html: str) -> str:
    """Cheap tag strip for measurement only (extraction uses a real parser)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def read_epub(path: str | Path, *, log=None) -> str:
    """Extract an EPUB's text in reading order as plain text.

    Headings are kept on their own lines and paragraphs separated by blank
    lines, because that is what `segment.detect_chapters` looks for -- the
    same shape a Gutenberg plain-text file arrives in.
    """
    _require_deps()
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    p = Path(path)
    report = inspect(p)
    if log:
        for w in report.warnings:
            log(f"  ⚠  {p.name}: {w}")

    try:
        book = epub.read_epub(str(p))
    except Exception as exc:  # noqa: BLE001 - ebooklib raises assorted types
        raise EpubError(f"Could not read {p.name}: {exc}") from exc

    parts: list[str] = []
    for item in _documents_in_reading_order(book):
        try:
            html = item.get_content().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        text = _document_text(BeautifulSoup(html, "html.parser"))
        if text.strip():
            parts.append(text)

    body = "\n\n".join(parts)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body:
        raise EpubError(
            f"No text could be extracted from {p.name}. If it is a scan, it "
            "has no text layer to read.")
    if log:
        log(f"• Extracted {len(body):,} characters from {p.name} "
            f"({report.documents} document(s)).")
    return body


_HTML_MEDIA = ("application/xhtml+xml", "text/html", "application/html")
_HTML_SUFFIX = (".xhtml", ".html", ".htm")


def _is_html(item) -> bool:
    """Whether an EPUB manifest item is a content document.

    Not the same as ebooklib's ITEM_DOCUMENT: that classifies purely on
    media type, and only `application/xhtml+xml` counts. Plenty of real EPUBs
    -- EPUB2 files and anything converted by older tooling -- declare their
    chapters as `text/html`, and those would silently come back as zero
    documents.
    """
    media = (getattr(item, "media_type", "") or "").lower()
    if media in _HTML_MEDIA:
        return True
    return (item.get_name() or "").lower().endswith(_HTML_SUFFIX)


def _documents_in_reading_order(book) -> list:
    """Content documents, in spine order.

    The spine is what defines reading order; the manifest is an unordered bag,
    so iterating it can shuffle chapters. Anything the spine misses is appended
    afterwards rather than dropped, since losing a chapter is worse than
    getting one slightly out of place.
    """
    ordered, seen = [], set()
    for entry in (getattr(book, "spine", None) or []):
        idref = entry[0] if isinstance(entry, (tuple, list)) else entry
        item = book.get_item_with_id(idref)
        if item is not None and _is_html(item):
            ordered.append(item)
            seen.add(item.get_id())
    for item in book.get_items():
        if _is_html(item) and item.get_id() not in seen:
            ordered.append(item)
    return ordered


def _document_text(soup) -> str:
    """One XHTML document as plain text, block structure preserved."""
    for tag in soup(["script", "style"]):
        tag.decompose()

    # A heading on its own line is what makes chapter detection possible.
    for tag in soup.find_all(_HEADING_TAGS):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")

    text = soup.get_text()
    # Internet Archive scans prefix every page with a running head and a
    # confidence note; both are apparatus, not text.
    text = _IA_ACCURACY.sub(" ", text)
    text = "\n".join(_IA_PAGE_HEAD.sub("", line) for line in text.splitlines())

    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- #
# Structural divisions
#
# An EPUB already knows where its chapters are: the spine orders its content
# documents, and headings mark divisions inside them. Flattening all of that to
# one string and then hunting for headings with a regex throws the structure
# away and then tries to guess it back -- which is how a 457,000-character
# novel ends up as a single division, and a single chapter marker in a
# nine-hour audiobook.
# --------------------------------------------------------------------------- #

# Headings that are not chapter titles. Converted EPUBs routinely use <h1> for
# any large type, so the front matter of a paperback arrives as headings.
_NON_TITLE = re.compile(
    r"^(printing|printed in\b|copyright\b|all rights reserved|isbn\b|"
    r"first (published|edition)|contents|book)\b", re.I)


def _is_title(text: str) -> bool:
    """Whether a heading looks like a division title rather than furniture.

    Empty headings are common in converted files (used purely for spacing),
    and a "heading" running to a paragraph's length is a styling artefact, not
    a title.
    """
    t = (text or "").strip()
    return bool(t) and len(t) <= 100 and not _NON_TITLE.match(t)


def _split_document(soup) -> list[tuple[str, str]]:
    """One content document as [(title, text)], split at credible headings.

    Text before the first heading stays as its own untitled division rather
    than being attached to the heading that follows it: it belongs to what
    came before, and in practice it is a run-on from the previous document.
    """
    for tag in soup(["script", "style"]):
        tag.decompose()

    heads = [h for h in soup.find_all(_HEADING_TAGS)
             if _is_title(h.get_text(" ", strip=True))]
    if not heads:
        text = _document_text(soup)
        return [("", text)] if text.strip() else []

    # Mark each kept heading so the flattened text can be cut at it again.
    marks = {}
    for i, h in enumerate(heads):
        token = f"\n\n@@BCDIV{i}@@\n\n"
        marks[i] = h.get_text(" ", strip=True)
        h.insert_before(token)

    text = _document_text(soup)
    out: list[tuple[str, str]] = []
    pieces = re.split(r"@@BCDIV(\d+)@@", text)
    lead = pieces[0].strip()
    if lead:
        out.append(("", lead))
    for idx, body in zip(pieces[1::2], pieces[2::2]):
        title = marks[int(idx)]
        body = body.strip()
        # The heading's own text leads the body it introduces; drop that copy
        # so the title is not read out twice.
        if body.startswith(title):
            body = body[len(title):].strip()
        if body:
            out.append((title, body))
    return out


def read_divisions(path: str | Path, *, log=None) -> list[tuple[str, str]]:
    """An EPUB as [(title, body), ...], following the book's own structure.

    Falls back to a single untitled division only when the file genuinely has
    no usable structure, so callers can always treat the result as the book's
    divisions.
    """
    _require_deps()
    from bs4 import BeautifulSoup
    from ebooklib import epub

    p = Path(path)
    report = inspect(p)
    if log:
        for w in report.warnings:
            log(f"  ⚠  {p.name}: {w}")
    try:
        book = epub.read_epub(str(p))
    except Exception as exc:  # noqa: BLE001 - ebooklib raises assorted types
        raise EpubError(f"Could not read {p.name}: {exc}") from exc

    divisions: list[tuple[str, str]] = []
    for item in _documents_in_reading_order(book):
        try:
            html = item.get_content().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        divisions.extend(_split_document(BeautifulSoup(html, "html.parser")))

    if not divisions:
        raise EpubError(
            f"No text could be extracted from {p.name}. If it is a scan, it "
            "has no text layer to read.")
    if log:
        chars = sum(len(b) for _, b in divisions)
        titled = sum(1 for t, _ in divisions if t)
        log(f"• Extracted {chars:,} characters from {p.name} "
            f"({report.documents} document(s), {len(divisions)} division(s), "
            f"{titled} titled).")
    return divisions
