"""Splitting a division at holes in the translation (pipeline._split_at_gaps)."""

from __future__ import annotations

from book_creator import pipeline
from book_creator.model import BookSpec


def _spec(gaps):
    return BookSpec(title="T", author="A", src_lang="de", tgt_lang="en",
                    mode="verse", verse_align="line", align_block=3,
                    translation_gaps=gaps)


SRC = ["Gesang und Lob dem Mittler der Welt, der heilig ist,",
       "Und die Engel verstummten vor seinem hohen Antlitz,",
       "Aber Satan sah es und knirschte in finsterer Tiefe,",
       "Oder ihr Ende, der Ungeheuren, mit anzusehen.",
       "Jetzo nähert' er sich mit säumendem Schritte den Engeln,",
       "Welche die Pforte bewachten. Wie war Dir, Abbadona,",
       "Da Du Abdiel sahst, den Getreuen, den Ewigen Liebling?",
       "Ins Unermeßliche fliehn; allein noch stand er mit Zittern,",
       "Finstrer Gedanke, Gedanke voll Qual! und Du, wilde Verzweiflung!",
       "Wüthe, Tyrannin, ha, wüthe nur fort! Wie bin ich so elend!",
       "Wär' ich nur nicht! Ich fluche Dir, Tag, da der Schaffende sagte:",
       "»Werde!« da er von Osten mit seiner Herrlichkeit ausging!"]
GAP = [{"after_src": SRC[3], "resume_src": SRC[8]}]


def test_splits_into_pair_hole_pair_with_the_marker_consumed():
    tgt = ["line 0", "line 1", "line 2", "line 3", "[about 90 lines lost: pages 1-2 ...]",
           "line 8", "line 9"]
    parts = pipeline._split_at_gaps(SRC, tgt, _spec(GAP), lambda m: None)
    assert [p[0] for p in parts] == ["pair", "hole", "pair"]
    assert parts[0][1] == SRC[:4] and parts[0][2] == tgt[:4]
    assert parts[1][1] == SRC[4:8] and parts[1][2] == []
    assert parts[2][1] == SRC[8:] and parts[2][2] == ["line 8", "line 9"]
    assert not any("[about" in t for p in parts for t in p[2])


def test_every_original_line_is_in_exactly_one_part():
    tgt = ["a", "b", "[about 5 lines lost: x]", "c"]
    parts = pipeline._split_at_gaps(SRC, tgt, _spec(GAP), lambda m: None)
    assert [ln for p in parts for ln in p[1]] == SRC


def test_no_gap_named_for_this_division_means_no_split():
    other = [{"after_src": "ganz andere Zeile in einem anderen Gesang",
              "resume_src": "und noch eine ganz andere Zeile"}]
    assert pipeline._split_at_gaps(SRC, ["a", "[about 9 lines lost]", "b"],
                                   _spec(other), lambda m: None) is None


def test_marker_count_must_match_gap_count():
    seen = []
    parts = pipeline._split_at_gaps(SRC, ["a", "b", "c"], _spec(GAP), seen.append)
    assert parts is None and seen and "marker" in seen[0]


def test_anchors_survive_ocr_noise_in_the_original():
    noisy = list(SRC)
    noisy[3] = SRC[3].replace("Ungeheuren", "Ungeheuien") + " ."
    parts = pipeline._split_at_gaps(noisy, ["a", "[about 9 lines lost]", "b"],
                                    _spec(GAP), lambda m: None)
    assert parts is not None and len(parts[0][1]) == 4


def test_find_line_refuses_a_poor_match():
    assert pipeline._find_line(SRC, "etwas völlig anderes") is None
    assert pipeline._find_line(SRC, SRC[5]) == 5
