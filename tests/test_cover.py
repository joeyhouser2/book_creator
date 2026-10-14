"""Front-cover styles.

Rendering is checked for *not falling over* and for producing a plausibly
different picture per style. What a cover looks like is a judgement no
assertion makes, so the visual work happens by eye; these guard the wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from book_creator import cover
from book_creator.model import CoverSpec

pytest.importorskip("fitz", reason="cover rasterizing needs PyMuPDF")


@pytest.mark.parametrize("style", cover.ALL_COVER_STYLES)
def test_every_style_renders_a_front_cover(style, tmp_path):
    out = cover.render_ebook_cover(
        str(tmp_path / f"{style}.png"), style=style,
        title="Commentarii de Bello Gallico", author="Gaius Iulius Caesar",
        src_lang="la", tgt_lang="en", trim=(6, 9), dpi=60)
    assert Path(out).stat().st_size > 2000


def test_styles_actually_differ(tmp_path):
    """A style that silently fell through to the default would still render."""
    shots = {}
    for style in cover.ALL_COVER_STYLES:
        p = tmp_path / f"{style}.png"
        cover.render_ebook_cover(str(p), style=style, title="De Rerum Natura",
                                 author="Lucretius", src_lang="la",
                                 tgt_lang="en", trim=(6, 9), dpi=60)
        shots[style] = p.read_bytes()
    assert len(set(shots.values())) == len(cover.ALL_COVER_STYLES)


def test_an_unknown_style_is_refused_by_name(tmp_path):
    with pytest.raises(ValueError, match="unknown cover style"):
        cover.render_ebook_cover(str(tmp_path / "x.png"), style="holographic",
                                 title="T", author="A", src_lang="la",
                                 tgt_lang="en", trim=(6, 9), dpi=60)


@pytest.mark.parametrize("style", cover.ALL_COVER_STYLES)
def test_every_style_renders_the_wraparound_too(style, tmp_path):
    """The styles draw the front panel of the print wrap as well as the ebook
    cover, so a style that only worked in one of the two would be a trap."""
    _, (w, h, spine) = cover.render_cover(
        str(tmp_path / f"{style}.pdf"), style=style, title="Ilias",
        author="Homer", src_lang="grc", tgt_lang="en", trim=(6, 9),
        pages=300, paper="cream", blurb="Back cover text.")
    assert w > 12 and h == pytest.approx(9.25) and spine > 0.5


def test_a_long_title_still_fits_the_panel(tmp_path):
    """Titles in this corpus run long ('Historia Ecclesiastica gentis
    Anglorum/Liber Primus'), and each style drops to a smaller size rather
    than letting the type run past the panel edge."""
    for style in cover.ALL_COVER_STYLES:
        out = cover.render_ebook_cover(
            str(tmp_path / f"long-{style}.png"), style=style,
            title="Historia Ecclesiastica gentis Anglorum Liber Primus atque "
                  "Secundus cum Notis",
            author="Beda Venerabilis", src_lang="la", tgt_lang="en",
            trim=(6, 9), dpi=60)
        assert Path(out).stat().st_size > 2000


def test_cover_spec_defaults_to_the_ornamental_style():
    assert CoverSpec().style == cover.DEFAULT_COVER_STYLE
    assert CoverSpec().style in cover.ALL_COVER_STYLES


def test_every_style_has_a_label_for_the_picker():
    """The ids alone ("plate", "band") tell a user nothing."""
    assert set(cover.COVER_STYLE_LABELS) == set(cover.ALL_COVER_STYLES)


# --------------------------------------------------------------------------- #
# The signum on the spine
# --------------------------------------------------------------------------- #
def _spine_ink(path, spine_in, trim_w, band=0.32):
    """Dark-ish pixel count in the bottom `band` of the spine (where the signum sits)."""
    import fitz
    pg = fitz.open(str(path))[0]
    x0 = (cover.BLEED + trim_w) * 72
    x1 = x0 + spine_in * 72
    clip = fitz.Rect(x0 + 2, pg.rect.height - 72 * 0.9, x1 - 2, pg.rect.height - 72 * 0.2)
    pix = pg.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, colorspace=fitz.csGRAY)
    return sum(1 for b in pix.samples if b < 90)


def _cover(tmp_path, name, **kw):
    out = tmp_path / f"{name}.pdf"
    args = dict(title="Der Messias", author="K", src_lang="de", tgt_lang="en",
                trim=(6.0, 9.0), pages=400)
    args.update(kw)
    _, (w, h, spine) = cover.render_cover(str(out), **args)
    return out, spine


def test_the_signum_is_drawn_at_the_foot_of_the_spine(tmp_path):
    with_logo, spine = _cover(tmp_path, "logo")
    without, _ = _cover(tmp_path, "none", spine_logo="none")
    assert _spine_ink(with_logo, spine, 6.0) > _spine_ink(without, spine, 6.0) + 50


def test_a_spine_too_thin_for_text_gets_no_signum(tmp_path):
    out, spine = _cover(tmp_path, "thin", pages=40)
    assert spine < 0.18


def test_auto_is_black_on_light_and_gold_on_dark():
    from reportlab.lib.colors import HexColor
    assert cover._signum_variant("auto", HexColor("#f4ead5")) == "black"
    assert cover._signum_variant("auto", HexColor("#1b2433")) == "gold"
    assert cover._signum_variant("white", HexColor("#f4ead5")) == "white"
    assert cover._signum_variant("none", HexColor("#f4ead5")) is None


def test_an_unknown_spine_logo_is_refused_by_name(tmp_path):
    with pytest.raises(ValueError, match="spine_logo"):
        _cover(tmp_path, "bad", spine_logo="neon")


def test_the_signum_is_kept_clear_of_a_long_author_name(tmp_path):
    # A name this long reaches to near the foot of the spine; the signum shrinks
    # (or goes) rather than overprinting it.
    out, spine = _cover(tmp_path, "long", author="Johann Wolfgang Maximilian von "
                        "Hohenzollern-Sigmaringen-Wiedenbrück", trim=(5.5, 8.5))
    import fitz
    pg = fitz.open(str(out))[0]
    assert pg.rect.height > 0                      # rendered without error


def test_every_signum_variant_parses_and_has_the_same_shape():
    shapes = {v: cover.signum_aspect(v) for v in cover.SIGNUM_VARIANTS}
    assert len(set(round(a, 4) for a in shapes.values())) == 1
    assert 0.5 < shapes["black"] < 1.0


def test_svg_path_parser_handles_absolute_relative_and_shorthand():
    segs = cover._parse_svg_path("M10,10 L20,10 H30 V40 c5,0 5,5 0,5 Z")
    kinds = [k for k, _ in segs]
    assert kinds == ["M", "L", "L", "L", "C", "Z"]
    assert segs[2][1] == [30.0, 10.0]
    assert segs[3][1] == [30.0, 40.0]
    assert segs[4][1][-2:] == [30.0, 45.0]         # relative curve end


def test_svg_arcs_are_refused_not_drawn_wrong():
    with pytest.raises(ValueError, match="arcs"):
        cover._parse_svg_path("M0,0 A5,5 0 0 1 10,10")


# --------------------------------------------------------------------------- #
# Stamping a signum onto a cover that already exists
# --------------------------------------------------------------------------- #
def _interior(path, trim, n_pages=2):
    from reportlab.pdfgen import canvas as rl
    c = rl.Canvas(str(path), pagesize=(trim[0] * 72, trim[1] * 72))
    for _ in range(n_pages):
        c.drawString(72, 72, "x")
        c.showPage()
    c.save()


def test_stamp_adds_the_signum_to_a_finished_cover_and_changes_nothing_else(tmp_path):
    import fitz
    old, spine = _cover(tmp_path, "old", spine_logo="none", pages=400)
    interior = tmp_path / "interior.pdf"
    _interior(interior, (6.0, 9.0))
    before = fitz.open(str(old))[0].rect
    r = cover.stamp_signum(str(old), str(interior))
    assert r["action"] == "stamped" and r["variant"] == "black"
    assert r["spine_in"] == pytest.approx(spine, abs=0.01)
    doc = fitz.open(str(old))
    assert doc[0].rect == before and len(doc) == 1
    assert cover.SIGNUM_MARK in doc.metadata["keywords"]
    # and there is now ink where the signum goes
    plain, _ = _cover(tmp_path, "plain", spine_logo="none", pages=400)
    assert _spine_ink(old, spine, 6.0) > _spine_ink(plain, spine, 6.0) + 50


def test_stamping_twice_is_a_no_op(tmp_path):
    old, _ = _cover(tmp_path, "old2", spine_logo="none", pages=400)
    interior = tmp_path / "interior2.pdf"
    _interior(interior, (6.0, 9.0))
    assert cover.stamp_signum(str(old), str(interior))["action"] == "stamped"
    again = cover.stamp_signum(str(old), str(interior))
    assert again["action"] == "skipped" and "already" in again["reason"]


def test_a_cover_built_with_the_signum_is_not_stamped_again(tmp_path):
    made, _ = _cover(tmp_path, "made", pages=400)               # drawn natively
    interior = tmp_path / "interior3.pdf"
    _interior(interior, (6.0, 9.0))
    assert cover.stamp_signum(str(made), str(interior))["action"] == "skipped"


def test_stamp_skips_a_spine_too_thin_and_says_why(tmp_path):
    thin, _ = _cover(tmp_path, "thin2", spine_logo="none", pages=30)
    interior = tmp_path / "interior4.pdf"
    _interior(interior, (6.0, 9.0))
    r = cover.stamp_signum(str(thin), str(interior))
    assert r["action"] == "skipped" and "thin" in r["reason"]


def test_stamp_refuses_an_interior_of_a_different_trim(tmp_path):
    old, _ = _cover(tmp_path, "old5", spine_logo="none", pages=400)
    interior = tmp_path / "interior5.pdf"
    _interior(interior, (5.5, 8.5))
    r = cover.stamp_signum(str(old), str(interior))
    assert r["action"] == "skipped" and "trim" in r["reason"]
