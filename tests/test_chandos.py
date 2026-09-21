"""The Chandos Herald build: extraction helpers, and verse that keeps its lines."""

from __future__ import annotations

import fitz
import pytest

import build_chandos as bc
from book_creator import render_pdf
from book_creator.model import Bead, Chapter


# --------------------------------------------------------------------------- #
# Line numbers
# --------------------------------------------------------------------------- #
def test_one_misread_number_cannot_poison_the_rest():
    """The first version walked the list keeping whatever increased, so an
    early "104°" read as 1040 rejected every true number behind it and only 19
    of 694 anchors survived. The longest increasing run lets the many good
    readings outvote the bad one."""
    numbers = [15, 20, 1040, 30, 35, 40, 45, 50]
    kept = bc.repair(numbers, step=5)
    assert kept == [15, 20, None, 30, 35, 40, 45, 50]


def test_marginal_numerals_are_read_through_ocr_noise():
    assert bc._number("104° De trestoutz les meillos escus") == (
        1040, "De trestoutz les meillos escus")
    assert bc._number("i°5° Dauoir la bataille partie")[0] == 1050
    # A folio mark sharing the line is not the line number.
    assert bc._number("f. 3' 195 Au Roi de Beaume manda") == (
        195, "Au Roi de Beaume manda")


def test_a_line_without_a_number_is_left_alone():
    assert bc._number("Et lui Counte de longeville") == (
        None, "Et lui Counte de longeville")


# --------------------------------------------------------------------------- #
# What counts as verse
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("junk", ["BLACK PRINCE", "t", "|", "•", "1060"])
def test_page_debris_is_not_verse(junk):
    assert bc._junk(junk)


def test_a_short_real_word_is_not_debris():
    # "fit" (did, made) is Anglo-Norman. A stray three-letter row is left to
    # the line-count trim, which has the line numbers to check it against;
    # the junk filter must not guess and delete verse.
    assert not bc._junk("fit")


@pytest.mark.parametrize("verse", ["Et lui Counte de longeville",
                                   "Qui ot le coer preu et hardy",
                                   "Oues lui ce est chose voire"])
def test_verse_is_kept(verse):
    assert not bc._junk(verse)


def test_the_tironian_et_is_restored():
    """⁊ comes through OCR as "%" on some pages and "4" on others; neither is
    ever a word in the manuscript column once line numbers are stripped."""
    assert bc._manuscript("Adonqes il fist moult % desrois") == \
        "Adonqes il fist moult ⁊ desrois"
    assert bc._manuscript("La matiere | 4 plus destourbee") == \
        "La matiere | ⁊ plus destourbee"


def test_a_number_inside_a_word_is_not_mistaken_for_the_siglum():
    assert "⁊" not in bc._manuscript("Bien CCCC4 chiualx armez")


# --------------------------------------------------------------------------- #
# The English
# --------------------------------------------------------------------------- #
def test_scan_debris_is_cleaned_from_the_translation():
    assert bc._clean_english("the noble King his 107 father") == \
        "the noble King his father"
    assert bc._clean_english("took Carcassonne and B^ziers") == \
        "took Carcassonne and Béziers"
    assert bc._clean_english("to his honour.' BLACK PKINCE they were") == \
        "to his honour.' they were"


def test_words_that_contain_digits_or_carets_survive_cleaning():
    # Only isolated numerals are marginalia; the English of this edition
    # spells its numbers out, but it must not lose a real word to the rule.
    assert bc._clean_english("the Count de L'Isle came") == \
        "the Count de L'Isle came"


def test_names_match_across_spellings():
    """The aligner's strongest evidence: a name survives translation almost
    untouched even when the spelling does not."""
    assert bc._same_name("warrewic", "warwick")
    assert bc._same_name("salesbiri", "salisbury")
    assert not bc._same_name("warrewic", "salisbury")


# --------------------------------------------------------------------------- #
# Verse that keeps its lines on the page
# --------------------------------------------------------------------------- #
def _render(tmp_path, bead: Bead) -> str:
    out = tmp_path / "t.pdf"
    render_pdf.render([Chapter(title="I", beads=[bead])], out_path=str(out),
                      title="T", author="A", src_lang="xno", tgt_lang="en",
                      trim=(6.0, 9.0), include_toc=False)
    doc = fitz.open(out)
    return "\n".join(doc[i].get_text() for i in range(doc.page_count))


def test_a_verse_bead_prints_one_line_per_line(tmp_path):
    verse = ["Et lui Counte de longeville", "Cils deux si estoient sanz gille",
             "ffiltz monf Robt Dartois"]
    text = _render(tmp_path, Bead(src=verse, tgt=["And the Count of Longueville."],
                                  lines=True))
    lines = [l.strip() for l in text.splitlines()]
    assert all(v in lines for v in verse), lines


def test_a_prose_bead_still_runs_together(tmp_path):
    """Off by default: a prose bead's segments are sentences, one paragraph."""
    text = _render(tmp_path, Bead(src=["First sentence.", "Second sentence."],
                                  tgt=["Translation."]))
    assert "First sentence. Second sentence." in " ".join(text.split())


def test_anglo_norman_is_named_on_the_page():
    assert render_pdf._lang_name("xno") == "Anglo-Norman"


# --------------------------------------------------------------------------- #
# Reading the page: lines, twins, headings
# --------------------------------------------------------------------------- #
def test_one_printed_line_split_by_the_scan_comes_back_whole():
    """Grouping by fixed height bands split a line whose pieces straddled a
    band's edge, and scrambled "the Count of Dammartin. Very goodly was his
    array" into "the Count of Very goodly was his ... Dammartin. array,"."""
    pieces = [(41.0, 522.4, "was also with him the noble Count of"),
              (41.9, 539.6, "Dammartin."), (95.0, 541.2, "Very goodly was his"),
              (200.0, 540.1, "array,")]
    rows = bc._rows(pieces)
    assert [t for _, t in (rows[k] for k in sorted(rows))] == [
        "was also with him the noble Count of",
        "Dammartin. Very goodly was his array,"]


def test_a_misread_number_that_still_increases_is_caught():
    """"17^°" (1720) read as 1710 increases, so plain repair kept it and made
    five lines look like fifteen. Its offset from its position disagrees with
    its neighbours', which is what gives it away."""
    numbers = [None] * 40
    for i, n in ((0, 1700), (5, 1705), (10, 1710), (15, 1710), (20, 1725),
                 (25, 1730), (30, 1735)):
        numbers[i] = n
    kept = bc.repair_positional(numbers)
    assert kept[15] is None
    assert kept[10] == 1710 and kept[20] == 1725


def test_the_verse_margin_is_measured_on_each_page():
    """The text block sits 16 points further right on one page of a spread
    than the other; a fixed margin lost the normalised twin of 1,078 lines."""
    rows = {100 + 12 * i: (242.6 + (i % 2) * 0.4, "verse") for i in range(10)}
    rows[400] = (265.0, "a heading's right half")
    assert abs(bc._verse_margin(rows) - 242.0) <= 2


def test_a_heading_half_is_not_taken_for_a_twin():
    right = {411: (245.2, "et du Prince son filtz"), 444: (242.4, "Ore ay je volu")}
    assert bc._twin(right, 444, 242.0) == "Ore ay je volu"
    # Level with nothing at the margin: no twin, which marks a heading.
    assert bc._twin({411: (290.0, "du Prince son filtz")}, 411, 242.0) is None


def test_a_heading_split_at_the_line_end_is_rejoined():
    assert bc._join_heading(["tres noble Prince de Gales et Daqui-", "taine quauoit"]) \
        == "tres noble Prince de Gales et Daquitaine quauoit"


def test_a_lacuna_is_kept_as_a_line():
    """The edition prints a lost manuscript line as dots, and numbers it."""
    assert bc._LACUNA.fullmatch(". . . . . . . .")
    assert not bc._LACUNA.fullmatch("La ot maint bon chiualer fyn")


def test_a_mangled_line_number_is_dropped_by_its_twin():
    assert bc._drop_misread_number("1S5 Tiel meruaille ot ceste chose voire",
                                   "Tel merveille ot ceste chose voire") == \
        "Tiel meruaille ot ceste chose voire"
    # A real short opening word matches the twin and stays.
    assert bc._drop_misread_number("Et si estoit a ceste foitz",
                                   "Et s'i estoit, a ceste fois,") == \
        "Et si estoit a ceste foitz"


def test_debris_before_the_verse_goes_but_a_siglum_stays():
    assert bc._manuscript(". 1' Pur ce voil je mettre") == "Pur ce voil je mettre"
    assert bc._manuscript("% le Prince vint") == "⁊ le Prince vint"


# --------------------------------------------------------------------------- #
# Pairing by reading
# --------------------------------------------------------------------------- #
def test_the_models_answers_are_made_usable():
    """Out of range, out of order and missing answers are all repaired, and
    the first sentence starts the block, as its printed number says."""
    raw = ["1022", 1031, "9999", 1027, None, 1053, "x", 1058]
    starts = bc._clean_starts(raw, 1015, 1060)
    assert starts[0] == 1015
    assert starts == sorted(starts)
    assert starts[-1] == 1058


def test_every_line_of_a_block_lands_in_exactly_one_run(monkeypatch):
    lines = [bc.VerseLine(None, f"ms {n}", f"norm {n}") for n in range(100, 120)]
    numbers = list(range(100, 120))
    idx = list(range(20))
    monkeypatch.setattr(bc, "_llm_starts", lambda verse, ss: [100, 104, 104, 111])
    runs = bc._pair_by_reading(lines, numbers, idx,
                               ["S1.", "S2.", "S3.", "S4."], 100, 120)
    covered = [k for span, _ in runs for k in span]
    assert covered == idx
    # Two sentences starting on the same line share one run.
    assert [len(eng) for _, eng in runs] == [1, 2, 1]


def test_a_rubric_prints_as_a_heading_not_as_verse(tmp_path):
    """Centred and in italic: set in the verse style, a two-line rubric reads
    as two more lines of the poem."""
    out = tmp_path / "r.pdf"
    render_pdf.render([Chapter(title="I", beads=[
        Bead(src=["De la passage du Roy en Normandie."], tgt=[], heading=True),
        Bead(src=["Ore ay ie volu recorder"], tgt=["Now I have wished."], lines=True)])],
        out_path=str(out), title="T", author="A", src_lang="xno", tgt_lang="en",
        trim=(6.0, 9.0), include_toc=False)
    doc = fitz.open(out)
    spans = [s for p in doc for b in p.get_text("dict")["blocks"]
             for l in b.get("lines", []) for s in l["spans"]]
    rubric = next(s for s in spans if "passage du Roy" in s["text"])
    verse = next(s for s in spans if "Ore ay ie" in s["text"])
    assert "Italic" in rubric["font"] and "Italic" not in verse["font"]
    assert rubric["bbox"][0] > verse["bbox"][0] + 20        # centred, not flush


# --------------------------------------------------------------------------- #
# Folio marks, line numbers, lines typed in by hand
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mark", ["f. 46'", "t. 46'", "t.iV", "£.24'", "f. 15'", "f. as'"])
def test_a_folio_mark_is_taken_off_in_any_disguise(mark):
    """A folio mark level with a rubric dragged the row to the margin, and
    the middle of two rubrics printed as verse ("t. 46' Castillayn")."""
    assert bc._strip_folio(f"{mark} Castillayn ⁊ apres ceo refiert") == \
        "Castillayn ⁊ apres ceo refiert"
    assert bc._strip_folio(mark) == ""


def test_a_verse_line_is_not_mistaken_for_a_folio_mark():
    assert bc._strip_folio("tut bon fait darmes eit lieu") == "tut bon fait darmes eit lieu"
    assert bc._strip_folio("t. as vous") == "t. as vous"    # letters need the mark


@pytest.mark.parametrize("note", ["IJjie 337, luy added in the margin.",
                                  "Lzne I beau, a omitted and stiperscript."])
def test_the_editors_notes_are_not_verse_however_line_is_misread(note):
    """Left in, "Lzne I beau..." was taken for a rubric and cut three lines
    of verse off from the English that translates them."""
    assert bc._junk(note)


def test_a_line_number_that_is_not_a_multiple_of_five_is_a_misreading():
    """Numbers stand on every fifth line. "893" (for 895) taken at face value
    made a stretch look two lines long, and the trim deleted two real lines."""
    assert bc._number("893 Chescun p deuers son costee") == (None, "Chescun p deuers son costee")
    assert bc._number("895 Chescun p deuers son costee")[0] == 895


def test_typed_lines_are_read_from_the_corrections_file(tmp_path):
    f = tmp_path / "c.md"
    f.write_text(
        "# list\n\n## Lines missing from the scan (2)\n\n"
        "- lines 583–595: 2 missing (page 87)\n"
        "  Et lour vitailles sanz nul si\n"
        "  Moult par fu riches li arrois\n"
        "- lines 923–930: 1 missing (page 97)\n"
        "  Chescuns, sanz point de demoeree - line 930\n\n"
        "## Manuscript lines that look misread (1)\n\n- **1** (page 1): `x`\n",
        encoding="utf-8")
    got = bc.read_supplied(f)
    assert [(a, b, p) for a, b, p, _ in got] == [(583, 595, 87), (923, 930, 97)]
    assert got[1][3] == ["Chescuns, sanz point de demoeree"]


def test_a_typed_line_goes_in_only_where_the_page_has_nothing():
    lines = [bc.VerseLine(580 if i == 0 else None, f"ms {t}", t, 87) for i, t in
             enumerate(["Pour toutes lour nefs assambler", "Et lour vitailles sanz nul si",
                        "Apres le terme de deux mois", "Il prist congie du roy son pere",
                        "Et de la Roine sa mere"])]
    typed = ["Et lour vitailles sanz nul si", "Moult par fu riches li arrois",
             "Apres le terme de deux mois", "Il prist congie du roy son pere"]
    out, _ = bc.apply_supplied(lines, {}, [(581, 584, 87, typed)])
    assert [l.normalised for l in out][1:4] == [
        "Et lour vitailles sanz nul si", "Moult par fu riches li arrois",
        "Apres le terme de deux mois"]
    assert len(out) == len(lines) + 1


def test_a_typed_line_replaces_a_rubric_that_was_really_that_line():
    """On an OCR'd page the verse line came back as a rubric, both columns
    run together, and printed again beside the line typed in for it."""
    lines = [bc.VerseLine(1775 if i == 0 else None, f"ms {t}", t, 83) for i, t in
             enumerate(["La matere et alongeroie?", "Dans Petro n'osa plus attendre,",
                        "Trestout droit a Seville lors,", "Ou demorez fu ses tresors."])]
    rubrics = {2: "sen ala a voir entendre s’en ala, au voir entendre,"}
    typed = ["La matere et alongeroie?", "Dans Petro n'osa plus attendre,",
             "Einz s'en ala, au voir entendre,", "Trestout droit a Seville lors,"]
    out, moved = bc.apply_supplied(lines, rubrics, [(1776, 1780, 83, typed)])
    assert [l.normalised for l in out][2] == "Einz s'en ala, au voir entendre,"
    assert moved == {}


def test_verse_without_english_joins_its_neighbour_but_not_across_a_rubric():
    pieces = [([0, 1], ["S1."]), ([2, 3], []), ([4, 5], ["S2."]),
              ([6], []), ([7, 8], ["S3."])]
    # A rubric opens line 6: that bare line cannot join the passage before it.
    out = bc._join_untranslated(pieces, {6: "Coment..."})
    assert out == [([0, 1, 2, 3], ["S1."]), ([4, 5], ["S2."]), ([6, 7, 8], ["S3."])]
