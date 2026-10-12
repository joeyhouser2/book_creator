"""Proofreading English OCR where two readings of a page disagree."""

from __future__ import annotations

from collections import Counter

from book_creator import ocr_english, proofread_english


class _Scorer:
    """Prefers whichever line contains the most of a fixed set of good words."""

    def __init__(self, good):
        self.good = good

    def score(self, context, variants):
        return [float(sum(w in v for w in self.good)) * 10 for v in variants]


def _lex():
    words = Counter({w: 5000 for w in (
        "my", "sly", "soul", "degenerate", "the", "he", "be", "his", "bis",
        "and", "heard", "voice", "of", "man", "but", "bat", "e'en", "even")})
    lex = ocr_english.Lexicon(words, set())
    lex.common = set(words)            # every test word counts as a common word
    return lex


def test_a_real_word_is_replaced_by_the_reading_the_model_prefers():
    out = proofread_english.proofread(
        ["Sly Soul, degenerate man"], _lex(),
        helpers=[["My Soul, degenerate man"]], scorer=_Scorer(["My Soul"]), margin=2.0)
    assert out == ["My Soul, degenerate man"]


def test_a_close_call_leaves_the_text_alone():
    changes, unsure = [], []
    out = proofread_english.proofread(
        ["Sly Soul"], _lex(), helpers=[["My Soul"]],
        scorer=_Scorer([]), margin=2.0, changes=changes, unsure=unsure)
    assert out == ["Sly Soul"] and not changes


def test_elisions_are_not_undone_and_markers_pass_through():
    marker = "[about 34 lines lost: this page is illegible in the scan]"
    out = proofread_english.proofread(
        ["E'en so", marker], _lex(), helpers=[["Even so", marker]],
        scorer=_Scorer(["Even"]), margin=2.0)
    assert out == ["E'en so", marker]
