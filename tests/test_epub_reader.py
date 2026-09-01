"""Reading a local EPUB, and refusing to pretend a bad scan is a book."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from book_creator import epub_reader, fetch


# --------------------------------------------------------------------------- #
# Fixtures: hand-built EPUBs, so the tests need no external files
# --------------------------------------------------------------------------- #
_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def _opf(docs, media="application/xhtml+xml", spine_order=None):
    items = "\n".join(
        f'<item id="d{i}" href="{name}" media-type="{media}"/>'
        for i, (name, _) in enumerate(docs))
    order = spine_order if spine_order is not None else range(len(docs))
    refs = "\n".join(f'<itemref idref="d{i}"/>' for i in order)
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">test</dc:identifier>
    <dc:title>Test</dc:title><dc:language>en</dc:language>
  </metadata>
  <manifest>{items}</manifest>
  <spine>{refs}</spine>
</package>"""


def _make_epub(path: Path, docs, images: int = 0,
               media: str = "application/xhtml+xml", spine_order=None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("content.opf", _opf(docs, media, spine_order))
        for name, html in docs:
            z.writestr(name, html)
        for i in range(images):
            z.writestr(f"img{i}.jpeg", b"\xff\xd8\xff\xe0" + b"0" * 200)
    return path


_FILLER = ("<p>Eorum una pars, quam Gallos obtinere dictum est, initium capit "
           "a flumine Rhodano, continetur Garumna flumine, Oceano, finibus "
           "Belgarum.</p>") * 6


@pytest.fixture
def good_epub(tmp_path):
    # Big enough to clear the "almost no extractable text" floor, which exists
    # to catch picture books and image-only scans.
    docs = [
        ("c1.html", "<html><body><h1>Chapter I</h1>"
                    "<p>Gallia est omnis divisa in partes tres.</p>"
                    "<p>Horum omnium fortissimi sunt Belgae.</p>"
                    + _FILLER + "</body></html>"),
        ("c2.html", "<html><body><h1>Chapter II</h1>"
                    "<p>Apud Helvetios longe nobilissimus fuit Orgetorix.</p>"
                    + _FILLER + "</body></html>"),
    ]
    return _make_epub(tmp_path / "good.epub", docs)


@pytest.fixture
def scanned_epub(tmp_path):
    """An Internet-Archive-style scan that admits its own OCR is bad."""
    docs = [
        (f"page_{i}.html",
         f"<html><body><p>Page {i} The text on this page is estimated to be "
         f"only 24.1% accurate</p><p>quawk of j az Such veises as</p></body></html>")
        for i in range(1, 6)
    ]
    return _make_epub(tmp_path / "scan.epub", docs, images=5)


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #
def test_inspect_counts_documents_and_text(good_epub):
    r = epub_reader.inspect(good_epub)
    assert r.documents == 2
    assert r.images == 0
    assert r.characters > 50
    assert r.usable
    assert r.warnings == []


def test_inspect_flags_a_bad_scan_as_unusable(scanned_epub):
    r = epub_reader.inspect(scanned_epub)
    assert r.ocr_pages == 5
    assert r.ocr_accuracy == pytest.approx(24.1)
    assert not r.usable
    # The warning has to say what to do, not just that something is wrong:
    # bad OCR survives alignment and gets read aloud verbatim.
    joined = " ".join(r.warnings)
    assert "Unusable" in joined
    assert "scan" in joined.lower()


def test_inspect_rejects_a_non_epub(tmp_path):
    bogus = tmp_path / "not.epub"
    bogus.write_text("just text, not a zip")
    with pytest.raises(epub_reader.EpubError, match="not a valid EPUB"):
        epub_reader.inspect(bogus)


def test_inspect_rejects_a_missing_file(tmp_path):
    with pytest.raises(epub_reader.EpubError, match="No such file"):
        epub_reader.inspect(tmp_path / "absent.epub")


def test_inspect_flags_an_image_only_archive(tmp_path):
    epub = _make_epub(tmp_path / "img.epub",
                      [("c1.html", "<html><body><p>.</p></body></html>")],
                      images=30)
    r = epub_reader.inspect(epub)
    assert not r.usable
    assert any("Unusable" in w for w in r.warnings)


def test_report_serializes_for_the_ui(good_epub):
    d = epub_reader.inspect(good_epub).as_dict()
    assert set(d) >= {"documents", "images", "characters", "warnings", "usable",
                      "ocr_accuracy", "chars_per_document", "size_mb"}


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_read_epub_preserves_headings_and_paragraphs(good_epub):
    text = epub_reader.read_epub(good_epub)
    assert "Chapter I" in text
    assert "Gallia est omnis divisa in partes tres." in text
    # Headings must sit on their own line or chapter detection cannot see them.
    lines = [ln.strip() for ln in text.splitlines()]
    assert "Chapter I" in lines
    # Paragraphs stay separate rather than running together.
    assert "tres.Horum" not in text.replace(" ", "")


def test_read_epub_feeds_chapter_detection(good_epub):
    from book_creator import segment
    divisions = segment.outline(epub_reader.read_epub(good_epub))
    titles = " ".join(d["title"] for d in divisions)
    assert "Chapter" in titles


def test_read_epub_strips_scan_apparatus(scanned_epub):
    text = epub_reader.read_epub(scanned_epub)
    # The per-page confidence note is apparatus; leaving it in would put it in
    # the printed book and in the narrator's mouth.
    assert "estimated to be only" not in text
    assert "accurate" not in text


def test_read_epub_warns_through_the_log(scanned_epub):
    msgs = []
    epub_reader.read_epub(scanned_epub, log=msgs.append)
    assert any("Unusable" in m for m in msgs)


def test_read_epub_handles_text_html_manifests(tmp_path):
    """Regression: EPUB2-style files declare chapters as text/html.

    ebooklib's ITEM_DOCUMENT only matches application/xhtml+xml, so relying on
    it returned a single document out of hundreds and the book came back
    empty — silently, which is the dangerous part.
    """
    docs = [("c1.html", "<html><body><h1>Chapter I</h1>"
                        "<p>Gallia est omnis divisa.</p>" + _FILLER + "</body></html>"),
            ("c2.html", "<html><body><h1>Chapter II</h1>"
                        "<p>Horum omnium fortissimi.</p>" + _FILLER + "</body></html>")]
    epub = _make_epub(tmp_path / "html.epub", docs, media="text/html")
    text = epub_reader.read_epub(epub)
    assert "Gallia est omnis divisa." in text
    assert "Horum omnium fortissimi." in text


def test_read_epub_follows_spine_order_not_manifest_order(tmp_path):
    # The manifest is an unordered bag; the spine defines reading order, and
    # chapters arriving shuffled would wreck alignment.
    docs = [("a.xhtml", "<html><body><p>SECOND part of the book.</p>"
                        + _FILLER + "</body></html>"),
            ("b.xhtml", "<html><body><p>FIRST part of the book.</p>"
                        + _FILLER + "</body></html>")]
    epub = _make_epub(tmp_path / "spine.epub", docs, spine_order=[1, 0])
    text = epub_reader.read_epub(epub)
    assert text.index("FIRST part") < text.index("SECOND part")


def test_read_epub_errors_on_a_textless_archive(tmp_path):
    empty = _make_epub(tmp_path / "empty.epub",
                       [("c1.html", "<html><body></body></html>")])
    with pytest.raises(epub_reader.EpubError):
        epub_reader.read_epub(empty)


# --------------------------------------------------------------------------- #
# Dispatch through fetch.load_text
# --------------------------------------------------------------------------- #
def test_load_text_dispatches_on_extension(good_epub, tmp_path):
    from_epub = fetch.load_text(path=str(good_epub))
    assert "Gallia" in from_epub

    plain = tmp_path / "plain.txt"
    plain.write_text("Gallia est omnis.", encoding="utf-8")
    assert fetch.load_text(path=str(plain)) == "Gallia est omnis."


def test_load_text_is_case_insensitive_about_the_suffix(good_epub):
    upper = good_epub.with_suffix(".EPUB")
    upper.write_bytes(good_epub.read_bytes())
    assert "Gallia" in fetch.load_text(path=str(upper))


# --------------------------------------------------------------------------- #
# Structural divisions
# --------------------------------------------------------------------------- #
def test_divisions_follow_headings_inside_a_document(tmp_path):
    """A converted EPUB routinely puts several chapters in one file."""
    path = _make_epub(tmp_path / "h.epub", [("c1.html",
        "<html><body><h1>Chapter One</h1><p>First body.</p>" + _FILLER +
        "<h1>Chapter Two</h1><p>Second body.</p>" + _FILLER + "</body></html>")])
    divs = epub_reader.read_divisions(path)
    titles = [t for t, _ in divs]
    assert "Chapter One" in titles and "Chapter Two" in titles


def test_document_boundaries_are_divisions(tmp_path):
    path = _make_epub(tmp_path / "d.epub", [
        ("a.html", "<html><body><p>Alpha body text.</p>" + _FILLER + "</body></html>"),
        ("b.html", "<html><body><p>Beta body text.</p>" + _FILLER + "</body></html>"),
    ])
    divs = epub_reader.read_divisions(path)
    assert len(divs) == 2


def test_empty_and_boilerplate_headings_are_not_titles(tmp_path):
    """Converters use <h1> for any large type, so a paperback's front matter
    arrives as headings. An empty one is pure spacing."""
    assert not epub_reader._is_title("")
    assert not epub_reader._is_title("   ")
    assert not epub_reader._is_title("PRINTED IN THE UNITED STATES OF AMERICA")
    assert not epub_reader._is_title("Copyright 1962")
    assert not epub_reader._is_title("x" * 200)
    assert epub_reader._is_title("THE SACRED TREE")
    assert epub_reader._is_title("Chapter One")


def test_a_heading_is_not_repeated_into_its_own_body(tmp_path):
    path = _make_epub(tmp_path / "r.epub", [("c.html",
        "<html><body><h1>Canto One</h1><p>The body follows.</p>"
        + _FILLER + "</body></html>")])
    divs = epub_reader.read_divisions(path)
    title, body = next((t, b) for t, b in divs if t == "Canto One")
    assert not body.startswith("Canto One")
