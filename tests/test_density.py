"""Line spacing: a denser setting must fit more verse on a page, and still sit
inside the same text block."""

from __future__ import annotations

import pytest

from book_creator import render_pdf
from book_creator.model import Bead, Chapter


def _verse(n=240):
    return [Chapter(title="Canto I", beads=[
        Bead(src=["Sing', unsterbliche Seele, der sündigen Menschen Erlösung,"],
             tgt=["My soul, degenerate man's redemption sing,"], lines=True)
        for _ in range(n)])]


def _pages(tmp_path, density):
    _, n = render_pdf.render(_verse(), out_path=str(tmp_path / f"{density}.pdf"),
                             title="T", author="A", src_lang="de", tgt_lang="en",
                             trim=(6.0, 9.0), density=density)
    return n


def test_denser_settings_use_fewer_pages(tmp_path):
    normal, compact, tight = (_pages(tmp_path, d) for d in ("normal", "compact", "tight"))
    assert tight < compact < normal


def test_unknown_density_falls_back_to_normal(tmp_path):
    assert _pages(tmp_path, "nonsense") == _pages(tmp_path, "normal")
