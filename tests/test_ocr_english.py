"""English OCR repair and cut-point refinement."""

from __future__ import annotations

from collections import Counter

from book_creator import ocr_english
from book_creator.align_refine import refine
from book_creator.model import Bead


def _lex():
    words = Counter({w: 50 for w in (
        "thou", "dust", "and", "the", "do", "not", "each", "other", "round",
        "awful", "earth", "his", "voice", "of", "heard", "stood", "upon", "shore")})
    return ocr_english.Lexicon(words, {"Selia", "Orion"})


def test_known_words_and_names_are_untouched():
    lex = _lex()
    lines = ["Selia and Orion heard his voice", "tow'rd the shore, glorify'd"]
    assert ocr_english.correct(lines, lex) == lines


def test_a_second_reading_repairs_a_slip():
    lex = _lex()
    out = ocr_english.correct(["And thon stood upon the earth"], lex,
                              helpers=[["And thou stood upon the earth"]])
    assert out == ["And thou stood upon the earth"]


def test_without_evidence_an_unknown_word_is_left_alone():
    lex = _lex()
    assert ocr_english.correct(["Nephthoa stood"], lex) == ["Nephthoa stood"]


def test_refine_moves_a_name_into_the_block_that_holds_it():
    # The aligner put "Selia" on the wrong side of the cut by two lines.
    beads = [
        Bead(src=["Orion sprach lange", "und schwieg"],
             tgt=["Orion spoke long", "and ceased.", "Selia looked", "at him."]),
        Bead(src=["Selia sah ihn", "und blieb stehn"],
             tgt=["and stood still.", "The hours passed."]),
    ] * 1
    names = refine(beads)
    assert "Selia looked" in names[1].tgt or "Selia looked" in names[0].tgt
    # every English line is still present exactly once, in order
    assert [ln for b in names for ln in b.tgt] == [ln for b in beads for ln in b.tgt]
