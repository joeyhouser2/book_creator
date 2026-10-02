"""Repairing OCR of early printed Latin against the corpus vocabulary.

The point of this pass is what it REFUSES. A vision model offered "defendite
armis" for *defendite ab oris* -- a real Latin word that is not on the page, and
one no reader would catch. So every test here that pins a refusal is pinning the
feature, not a limitation.
"""

from __future__ import annotations

import pytest

from book_creator import ocr_correct


@pytest.fixture
def vocab():
    """A small stand-in for the corpus's 392,757 forms, with frequencies."""
    return {
        "communia": 500, "pectore": 900, "patriae": 1200, "libertate": 400,
        "infensos": 60, "procul": 800, "anglica": 30, "antica": 25,
        "saltem": 700, "uestris": 650, "manus": 1500, "toto": 1100,
        "hostes": 900, "defendite": 120, "oris": 300, "et": 9000,
    }


# --------------------------------------------------------------------------- #
# Abbreviations and marks
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("printed,expanded", [
    ("ſpectate", "spectate"),          # long s, the commonest of all
    ("ꝓcul", "procul"),                # pro
    ("ꝑ", "per"),
    ("⁊", "et"),
    ("q;", "que"),
    ("æternus", "aeternus"),
])
def test_printers_abbreviations_are_expanded(printed, expanded):
    assert ocr_correct.expand_abbreviations(printed) == expanded


def test_acute_accents_are_folded_away():
    # Classical Latin has no acutes; "patríís" is the typeface or the ink, and
    # every one the scanner reports is an artefact.
    assert ocr_correct.expand_abbreviations("patríís ínferre") == "patriis inferre"


# --------------------------------------------------------------------------- #
# Looking a word up
# --------------------------------------------------------------------------- #
def test_u_and_v_are_one_letter_for_lookup():
    """The corpus spells classically ("uestris"), a 1513 page sets "vestris".
    Without folding, every correctly-read v was "corrected" into a u -- the pass
    rewriting right answers into a different editorial convention."""
    assert ocr_correct.fold("vestris") == ocr_correct.fold("uestris")
    assert ocr_correct.fold("Jam") == ocr_correct.fold("iam")


def test_a_word_the_page_got_right_is_left_alone(vocab):
    out = ocr_correct.correct("uestris hostes", vocab)
    assert out.text == "uestris hostes"
    assert not out.corrected


def test_the_pages_own_spelling_survives_correction(vocab):
    # "vestris" is not in the vocabulary as spelled, but folds to one that is.
    out = ocr_correct.correct("vestris hostes", vocab)
    assert out.text == "vestris hostes", "rewrote the page's v into the corpus's u"


# --------------------------------------------------------------------------- #
# Correcting
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("wrong,right", [
    ("comsmunia", "communia"),     # an inserted letter
    ("peckore", "pectore"),        # ct misread
    ("parriae", "patriae"),        # rr for tr
    ("libettate", "libertate"),
])
def test_a_single_slip_is_corrected(wrong, right, vocab):
    out = ocr_correct.correct(wrong, vocab)
    assert out.text == right
    assert out.corrected == {wrong: right}


def test_case_of_the_printed_page_is_kept(vocab):
    assert ocr_correct.correct("Peckore", vocab).text == "Pectore"


def test_a_missing_first_letter_is_recovered(vocab):
    # Tesseract drops the initial capital of a decorated line often enough.
    assert ocr_correct.correct("nfensos", vocab).text == "infensos"


# --------------------------------------------------------------------------- #
# Refusing — the part that matters
# --------------------------------------------------------------------------- #
def test_an_equally_near_pair_is_left_for_a_human(vocab):
    """"angica" is one edit from both *anglica* and *antica*. Choosing would be
    guessing, and a guess that reads well is worse than a visible error."""
    out = ocr_correct.correct("angica", vocab)
    assert out.text == "angica"
    assert set(out.ambiguous["angica"]) >= {"anglica", "antica"}
    assert not out.corrected


def test_a_correction_may_not_delete_a_word(vocab):
    """"Atsaltem" is *At saltem* run together. Answering "saltem" throws a word
    away, which is a loss dressed up as a fix."""
    out = ocr_correct.correct("Atsaltem", vocab)
    assert out.text == "Atsaltem"
    assert "saltem" not in out.corrected.values()


def test_short_words_are_not_touched(vocab):
    # At three letters an edit of one reaches half the dictionary.
    out = ocr_correct.correct("ab qd", vocab)
    assert out.text == "ab qd"
    assert not out.corrected


def test_a_word_with_no_near_neighbour_is_reported_not_invented(vocab):
    out = ocr_correct.correct("xqzzyrw", vocab)
    assert out.text == "xqzzyrw"
    assert "xqzzyrw" in out.unknown
    assert not out.corrected


def test_summary_counts_all_three_outcomes(vocab):
    out = ocr_correct.correct("peckore angica xqzzyrw", vocab)
    assert "1 corrected" in out.summary
    assert "1 left ambiguous" in out.summary
    assert "1 unknown" in out.summary


def test_repair_runs_both_stages(vocab):
    # Long s expanded first, then the vocabulary consulted.
    assert ocr_correct.repair("peckore ſaltem", vocab).text == "pectore saltem"


def test_missing_vocabulary_file_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_reference_vocab"):
        ocr_correct.load_vocab(tmp_path / "nope.tsv")
