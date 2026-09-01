"""Page geometry: the text block, the margin art, and the gap between them.

These guard two defects that reached a printed book. Both were invisible in
code review and obvious on the page, so they are checked the way a reader
would: by rasterizing and looking for ink where none belongs.
"""

from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz", reason="needs PyMuPDF to inspect the PDF")
np = pytest.importorskip("numpy")

from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rcanvas

from book_creator import decorations, render_pdf
from book_creator.model import Bead, Chapter, DecorSpec

# KDP: nothing that matters may sit closer than this to the trimmed edge.
SAFE_MARGIN = 0.25 * inch


def _book(n_chapters=4, beads=14):
    """Enough text to run to several pages, so recto/verso both get exercised."""
    return [
        Chapter(title=f"Caput {i + 1}",
                beads=[Bead(src="Gallia est omnis divisa in partes tres, "
                            "quarum unam incolunt Belgae. " * 2,
                            tgt="All Gaul is divided into three parts, one of "
                                "which the Belgae inhabit. " * 2)
                       for _ in range(beads)])
        for i in range(n_chapters)
    ]


def _page_ink(page, dpi=150):
    pix = page.get_pixmap(dpi=dpi)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    return (a[:, :, :3].min(axis=2) < 200), dpi / 72.0


# --------------------------------------------------------------------------- #
# The gutter side must follow the page number
# --------------------------------------------------------------------------- #
def test_text_block_alternates_sides_every_single_page(tmp_path):
    """Odd pages are right-hand pages and carry the gutter on the left.

    The two page templates used to chain with ReportLab's autoNextPageTemplate,
    which PageBreaks and the TOC's extra multiBuild passes knocked out of step:
    the frame ended up alternating every *two* pages, so half the book was
    printed with the gutter on the wrong edge and the margin art -- which used
    the page number -- ruled through the text.
    """
    # The gutter only differs from the outside margin once a book is long
    # enough to need a wider one (KDP scales it with page count). At the
    # default 200-page estimate the two are both 0.5in, the mirrored frames
    # coincide, and a side swap would be invisible.
    out, pages = render_pdf.render(
        _book(), out_path=str(tmp_path / "b.pdf"), title="T", author="A",
        src_lang="la", tgt_lang="en", trim=(6, 9), estimated_pages=400,
        decor=DecorSpec(margin="frame"), include_toc=True)

    doc = fitz.open(out)
    lefts = {}
    for n in range(pages):
        blocks = [b for b in doc[n].get_text("blocks")
                  if b[4].strip() and not b[4].strip().isdigit()]
        if blocks:
            lefts[n + 1] = round(min(b[0] for b in blocks), 1)

    body = {p: x for p, x in lefts.items() if p >= 4}
    assert len(set(body.values())) == 2, "expected exactly two frame positions"
    odd = {x for p, x in body.items() if p % 2}
    even = {x for p, x in body.items() if p % 2 == 0}
    assert len(odd) == 1 and len(even) == 1, (
        f"a page side is not determined by its number: odd={odd} even={even}")
    # Odd (recto) pages carry the wider gutter on the left.
    assert odd.pop() > even.pop()


# --------------------------------------------------------------------------- #
# Margin art must not print over the text
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("style", [s for s in decorations.ALL_MARGIN_STYLES
                                   if s != "none"])
def test_margin_art_leaves_the_text_area_blank(style, tmp_path):
    """Drawn alone on a page, no style may put ink inside the text block.

    render_pdf reserves reserved_band() points around the text for exactly this,
    so a style can be added or widened without anyone having to re-check that
    it still misses the text.
    """
    w, h = 6 * inch, 9 * inch
    # Geometry comes from the document itself, not recomputed here. An earlier
    # version rebuilt it from margin_inset(), which is what a style *asks* for
    # — so it tested a page that never ships, and missed three styles drawing
    # 4pt outside the band the renderer had actually reserved for them.
    doc = render_pdf._BookDoc(str(tmp_path / "geom.pdf"), (6, 9), 0.5 * inch,
                              "T", DecorSpec(margin=style))
    geom = doc._geom_recto

    path = str(tmp_path / f"{style}.pdf")
    c = rcanvas.Canvas(path, pagesize=(w, h))
    decorations.draw_margin(c, geom, True, style, "#000000", None)
    c.showPage()
    c.save()

    ink, scale = _page_ink(fitz.open(path)[0])
    x0, x1 = int(geom["left"] * scale), int(geom["right"] * scale)
    y0, y1 = int((h - geom["top"]) * scale), int((h - geom["bottom"]) * scale)
    intruding = ink[y0 + 2:y1 - 2, x0 + 2:x1 - 2].sum()
    assert intruding == 0, f"{style} put {intruding} pixels inside the text area"


@pytest.mark.parametrize("style", [s for s in decorations.ALL_MARGIN_STYLES
                                   if s != "none"])
def test_margin_art_stays_clear_of_the_trim(style, tmp_path):
    """Ornaments used to sit 0.21in from the edge, inside the trim tolerance,
    where a print run can cut them in half."""
    w, h = 6 * inch, 9 * inch
    # Geometry comes from the document itself, not recomputed here. An earlier
    # version rebuilt it from margin_inset(), which is what a style *asks* for
    # — so it tested a page that never ships, and missed three styles drawing
    # 4pt outside the band the renderer had actually reserved for them.
    doc = render_pdf._BookDoc(str(tmp_path / "geom.pdf"), (6, 9), 0.5 * inch,
                              "T", DecorSpec(margin=style))
    geom = doc._geom_recto

    path = str(tmp_path / f"{style}.pdf")
    c = rcanvas.Canvas(path, pagesize=(w, h))
    decorations.draw_margin(c, geom, True, style, "#000000", None)
    c.showPage()
    c.save()

    ink, scale = _page_ink(fitz.open(path)[0])
    ys, xs = np.nonzero(ink)
    assert len(xs), f"{style} drew nothing at all"
    closest = min(xs.min(), ys.min(),
                  ink.shape[1] - 1 - xs.max(), ink.shape[0] - 1 - ys.max()) / scale
    assert closest >= SAFE_MARGIN, (
        f"{style} draws {closest:.1f}pt from the trim, inside the "
        f"{SAFE_MARGIN:.0f}pt safe area")


def test_a_decorated_page_reserves_more_room_than_a_plain_one(tmp_path):
    """The text block gives up the space, rather than the art being drawn on
    top of it — which is what "confined within the border" means."""
    widths = {}
    for style in ("none", "corners"):
        out, _ = render_pdf.render(
            _book(2, 8), out_path=str(tmp_path / f"{style}.pdf"), title="T",
            author="A", src_lang="la", tgt_lang="en", trim=(6, 9),
            estimated_pages=400, decor=DecorSpec(margin=style),
            include_toc=False)
        doc = fitz.open(out)
        blocks = [b for pg in doc for b in pg.get_text("blocks")
                  if b[4].strip() and not b[4].strip().isdigit()]
        widths[style] = max(b[2] for b in blocks) - min(b[0] for b in blocks)
    assert widths["corners"] < widths["none"], (
        "a margin style that needs room must shrink the text block")


def test_every_bead_separator_style_renders(tmp_path):
    """The separator used to accept only 'fleuron' while nine ornaments
    existed; each of them has to actually draw."""
    for style in decorations.ALL_BEAD_SEPARATORS:
        if style == "none":
            continue
        assert decorations.chapter_ornament(style, "#8a7a5c") is not None, style


@pytest.mark.parametrize("style", [s for s in decorations.ALL_MARGIN_STYLES
                                   if s != "none"])
def test_art_is_drawn_inside_the_band_that_was_reserved(style, tmp_path):
    """The reserve and the drawing must be the same number.

    They were not: three styles asked for 22pt, the page could only spare 18,
    and the art was still drawn at 22 — 4pt outside the space set aside for it.
    Nothing caught it, because both the trim check and the text check still
    passed at that size. The invariant worth asserting is the agreement itself.
    """
    doc = render_pdf._BookDoc(str(tmp_path / "g.pdf"), (6, 9), 0.5 * inch, "T",
                              DecorSpec(margin=style))
    geom = doc._geom_recto
    band = geom["band"]
    assert band == decorations.reserved_band(
        style, None, geom["outside"] - band, (9 * inch) - geom["top"] - band)

    w, h = 6 * inch, 9 * inch
    path = str(tmp_path / f"{style}.pdf")
    c = rcanvas.Canvas(path, pagesize=(w, h))
    decorations.draw_margin(c, geom, True, style, "#000000", None)
    c.showPage()
    c.save()

    ink, scale = _page_ink(fitz.open(path)[0])
    ys, xs = np.nonzero(ink)
    # No ink further out than the band, on any of the four sides.
    assert xs.min() / scale >= geom["left"] - band - 1
    assert xs.max() / scale <= geom["right"] + band + 1
    assert ys.min() / scale >= (h - geom["top"]) - band - 1
    assert ys.max() / scale <= (h - geom["bottom"]) + band + 1
