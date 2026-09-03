"""Reading text off page images.

Tesseract is an external binary, like LilyPond: not bundled, not installed by
this project. Tests that need it skip rather than fail, so the suite still
means something on a machine without it — the same bargain conftest makes for
the corpus and the fonts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from book_creator import ocr

fitz = pytest.importorskip("fitz", reason="needs PyMuPDF to make test PDFs")

HAVE_TESSERACT = ocr.available()[0]
needs_tesseract = pytest.mark.skipif(
    not HAVE_TESSERACT, reason=f"tesseract unavailable: {ocr.available()[1]}")


# A real page of prose runs to thousands of characters; the "does this have a
# text layer" floor is set against that, so a fixture with one line on a page
# is indistinguishable from a scan and would test the wrong thing.
_PARA = ("Gallia est omnis divisa in partes tres, quarum unam incolunt Belgae, "
         "aliam Aquitani, tertiam qui ipsorum lingua Celtae, nostra Galli "
         "appellantur. ")


def _text_pdf(path: Path, pages: int = 2) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 720),
                            f"Page {i + 1}. " + _PARA * 12, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _scan_pdf(path: Path, pages: int = 2) -> Path:
    """A PDF that is only pictures — no text layer at all, like a real scan."""
    src = fitz.open()
    for i in range(pages):
        page = src.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 720),
                            f"Page {i + 1}. " + _PARA * 4, fontsize=16)
    out = fitz.open()
    for i in range(pages):
        pix = src[i].get_pixmap(dpi=200)
        page = out.new_page(width=pix.width * 72 / 200,
                            height=pix.height * 72 / 200)
        page.insert_image(page.rect, pixmap=pix)
    out.save(str(path))
    src.close()
    out.close()
    return path


# --------------------------------------------------------------------------- #
# Telling a scan from a digital file
# --------------------------------------------------------------------------- #
def test_a_pdf_with_text_does_not_need_ocr(tmp_path):
    info = ocr.inspect_pdf(_text_pdf(tmp_path / "digital.pdf"))
    assert not info.needs_ocr
    assert info.pages == 2 and info.characters > 0


def test_a_scan_needs_ocr(tmp_path):
    """No text layer means every later stage would see an empty book."""
    info = ocr.inspect_pdf(_scan_pdf(tmp_path / "scan.pdf"))
    assert info.needs_ocr
    assert info.pages == 2 and info.characters == 0 and info.images == 2


def test_an_unreadable_file_is_reported_not_raised_bare(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(ocr.OcrError):
        ocr.inspect_pdf(bad)


# --------------------------------------------------------------------------- #
# Availability, without needing the binary
# --------------------------------------------------------------------------- #
def test_missing_tesseract_is_explained_not_crashed(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_exe", lambda: None)
    ok, reason = ocr.available()
    assert not ok and "Tesseract" in reason
    # And it must not be raised from a bare import path either.
    assert ocr.languages() == []
    assert ocr.tessdata_dir() is None


def test_status_lists_what_it_can_handle():
    st = ocr.status()
    assert ".pdf" in st["suffixes"] and ".epub" in st["suffixes"]


def test_an_unsupported_file_type_is_refused(tmp_path):
    txt = tmp_path / "already.txt"
    txt.write_text("plain text", encoding="utf-8")
    with pytest.raises(ocr.OcrError, match="neither"):
        ocr.run(txt)


# --------------------------------------------------------------------------- #
# Actually running it
# --------------------------------------------------------------------------- #
@needs_tesseract
def test_ocr_reads_a_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "cache")
    dest = ocr.run(_scan_pdf(tmp_path / "scan.pdf"), lang="eng", dpi=200)
    text = dest.read_text(encoding="utf-8").lower()
    assert "gallia" in text, text[:200]


@needs_tesseract
def test_a_second_run_uses_the_cache(tmp_path, monkeypatch):
    """A real book is twenty minutes of work; nobody should pay it twice."""
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "cache")
    scan = _scan_pdf(tmp_path / "scan.pdf")
    first = ocr.run(scan, lang="eng", dpi=200)
    marker = "SENTINEL"
    first.write_text(marker, encoding="utf-8")
    again = ocr.run(scan, lang="eng", dpi=200)
    assert again == first
    assert again.read_text(encoding="utf-8") == marker, "it re-OCRed instead"


@needs_tesseract
def test_pages_that_already_have_text_are_kept(tmp_path, monkeypatch):
    """A part-scanned book should cost only the pages that need the work."""
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "cache")
    logs: list[str] = []
    ocr.run(_text_pdf(tmp_path / "digital.pdf"), lang="eng", dpi=200,
            on_log=logs.append)
    assert any("kept from the existing text layer" in m for m in logs), logs


@needs_tesseract
def test_stopping_keeps_what_was_read(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "cache")
    seen: list[int] = []

    def stop_after_one():
        return len(seen) >= 1

    text = ocr.ocr_pdf(_scan_pdf(tmp_path / "scan.pdf", pages=4), lang="eng",
                       dpi=200, on_progress=lambda d, t: seen.append(d),
                       should_stop=stop_after_one)
    assert len(seen) < 4, "it ran every page despite being asked to stop"
    assert text.strip(), "the pages already read should still come back"
