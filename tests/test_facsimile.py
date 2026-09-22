"""A scanned book re-presented as a modern print edition (facsimile.py)."""

from __future__ import annotations

import fitz
import numpy as np

from book_creator import facsimile as fx


def _text(i: int, n: int | None, body: str = "the allied army marched on through the rain"):
    head = "" if n is None else (f"{n} THE WARS OF MARLBOROUGH " if n % 2 == 0
                                 else f"ALMANZA, STOLLHOFEN, AND TOULON {n} ")
    return fx.PageInfo(index=i, kind="text", words=40, text=head + body)


# --------------------------------------------------------------------------- #
# Page numbers and sides
# --------------------------------------------------------------------------- #
def test_the_printed_page_number_is_read_from_the_running_head():
    assert fx.printed_number("2 THE WARS OF MARLBOROUGH 25,400 men, of whom") == 2
    assert fx.printed_number("ALMANZA, STOLLHOFEN, AND TOULON 3 If Marlborough") == 3
    assert fx.printed_number("viii INTRODUCTION might shine upon them") == 8
    # A figure in the text is not a page number.
    assert fx.printed_number("25,400 men, of whom 11,900 were French") is None


def test_every_page_keeps_its_side_and_one_misread_number_moves_nothing():
    pages = [_text(i, n) for i, n in enumerate([None, 2, 3, 4, 5, 6, 7, 8, 9, 10])]
    pages[6] = _text(6, 12)                  # "7" misread as an even number
    sides = fx.sides(pages)
    assert sides[0] == "recto" and sides[1] == "verso" and sides[6] == "recto"


def test_a_fold_out_does_not_count_as_a_leaf():
    pages = [_text(0, 1), _text(1, 2),
             fx.PageInfo(index=2, kind="blank"),                        # its stub
             fx.PageInfo(index=3, kind="plate", odd_size=True, ink=0.01),
             _text(4, 3), _text(5, 4)]
    sides = fx.sides(pages)
    assert sides[4] == "recto" and sides[5] == "verso"


def test_a_blank_goes_back_only_where_a_side_needs_one():
    # A plate between pages 2 and 3 takes a leaf; page 3 must still be a recto.
    pages = [_text(0, 1), _text(1, 2),
             fx.PageInfo(index=2, kind="plate", ink=0.05),
             _text(3, 3), _text(4, 4)]
    slots = fx.plan(pages, front_pages=2)
    order = [(s.kind, s.index) for s in slots]
    assert order[:2] == [("front", None), ("front", None)]
    where = {s.index: n for n, s in enumerate(slots) if s.kind == "page"}
    assert where[0] % 2 == 0 and where[3] % 2 == 0      # rectos on even slots
    assert len(slots) % 2 == 0


# --------------------------------------------------------------------------- #
# Overrides and margins
# --------------------------------------------------------------------------- #
def test_overrides_are_read_from_plain_lines(tmp_path):
    f = tmp_path / "scan-pages.md"
    f.write_text("# my notes\n- drop 5, 9\nkeep 576\nplate 8\ndrop 2-4\n", encoding="utf-8")
    got = fx.read_overrides(f)
    assert got[5] == got[9] == got[3] == "dropped"
    assert got[576] == "text" and got[8] == "plate"


def test_the_gutter_follows_kdps_table():
    assert fx.gutter_for(120) == 0.375
    assert fx.gutter_for(494) == 0.625
    assert fx.gutter_for(570) == 0.75


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def _page(words: str, paper=(0.93, 0.88, 0.74)):
    doc = fitz.open()
    pg = doc.new_page(width=333, height=558)
    pg.draw_rect(pg.rect, color=None, fill=paper)
    pg.insert_text((90, 270), words, fontsize=12)
    return doc, pg


def test_a_nearly_empty_page_comes_out_white_not_grey():
    """The half-title: stretching its levels by its own darkest pixel, which
    was paper, turned the whole page grey."""
    _, pg = _page("THE WARS OF MARLBOROUGH")
    img = np.asarray(fx.clean_image(pg))
    assert np.median(img) == 255
    assert img.min() < 60                      # and the print stays black


def test_yellowed_paper_is_whitened_under_print():
    body = "the allied army marched on through the rain towards the river"
    _, pg = _page(body)
    img = np.asarray(fx.clean_image(pg))
    assert (img == 255).mean() > 0.9


def test_a_text_page_is_stored_as_sixteen_greys_and_reads_back(tmp_path):
    """PyMuPDF's own insertion widened 16 greys to 8 bits (370 KB a page),
    and writing the stream raw once lost its filter, turning pages to noise."""
    _, pg = _page("the allied army marched on")
    img = fx.clean_image(pg)
    enc = fx.encode(img)
    assert not enc.jpeg
    book = fitz.open()
    out = book.new_page(width=333, height=558)
    fx._place(book, out, out.rect, enc)
    book.save(tmp_path / "t.pdf")
    back = fitz.open(tmp_path / "t.pdf")
    info = back[0].get_images(full=True)[0]
    assert info[4] == 4 and info[5] == "DeviceGray"          # bits, colour space
    shown = back[0].get_pixmap(dpi=72, colorspace=fitz.csGRAY)
    grey = np.frombuffer(shown.samples, dtype=np.uint8)
    assert np.median(grey) == 255 and grey.min() < 80        # white page, black type


def test_a_grey_wedge_at_the_edge_goes_but_type_and_maps_stay():
    """A folded corner is lighter than print and touches the edge; the type
    never does. A map's lines run to the edge, so a plate is left alone."""
    doc, pg = _page("the allied army marched on")
    corner = fitz.Point(pg.rect.width, 0)
    pg.draw_polyline([corner, corner + (-60, 0), corner + (0, 60), corner],
                     color=None, fill=(0.55, 0.52, 0.45))
    img = np.asarray(fx.clean_image(pg))
    h, w = img.shape
    assert img[5, w - 5] == 255                      # the wedge is paper again
    assert img.min() < 60                            # the type is still black
    kept = np.asarray(fx.clean_image(pg, edges=False))
    assert kept[5, w - 5] < 255                      # a plate keeps what it has


def test_a_perforated_library_stamp_goes_but_dots_that_are_type_stay():
    """"UNIV. OF CALIFORNIA AT LOS ANGELES LIBRARY" is punched through the
    title page as letters of round holes. A full stop is a round dot too, and
    a contents page's leaders are a row of them."""
    doc, pg = _page("Contents of Vol. II.")
    for row in range(6):                       # the stamp: dots above and beside
        for col in range(12):
            # A hole is about 9 px across at 300 dpi: 1.1 points.
            c = fitz.Point(60 + col * 7, 360 + row * 7)
            pg.draw_circle(c, 1.1, color=None, fill=(0.45, 0.45, 0.45))
    for col in range(14):                      # leader dots, in one line only
        pg.draw_circle(fitz.Point(60 + col * 12, 430), 1.0, color=None, fill=(0, 0, 0))
    img = np.asarray(fx.clean_image(pg))
    band = lambda y0, y1: (img[y0:y1] < 200).sum()
    dpi = fx.DPI / 72.0
    assert band(int(355 * dpi), int(400 * dpi)) == 0        # the stamp is gone
    assert band(int(425 * dpi), int(436 * dpi)) > 0         # the leaders are not
    assert img.min() < 60                                   # nor is the type
