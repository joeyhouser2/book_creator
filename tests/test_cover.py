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
