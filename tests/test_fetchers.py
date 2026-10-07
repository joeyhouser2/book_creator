"""The extraction scripts that turn a scan's OCR into a buildable text.

Each of these reads a book that was printed with something other than its poem
on the page -- running heads, margin numbers, footnotes, the facing translation
-- and each learned its rules from real damage. The tests keep the pure parts
honest: they do not touch the network or the cached OCR.
"""

from __future__ import annotations

import fetch_basinio
import fetch_cid
import fetch_franciade
import fetch_kudrun
import fetch_mireio


# --------------------------------------------------------------------------- #
# Basinio, Hesperis
# --------------------------------------------------------------------------- #
def test_basinio_drops_running_heads_page_numbers_and_signatures():
    page = "\n".join([
        "HESPERIDOS LIBER", "III.", "53", "A 3", "BASINII", "Bb2",
        "Maximus Aeneas heros unde ortus , et unde",
        "Inclytus Albanae memoratur conditor urbis",
    ])
    assert fetch_basinio.clean_lines(page) == [
        "Maximus Aeneas heros unde ortus , et unde",
        "Inclytus Albanae memoratur conditor urbis",
    ]


def test_basinio_restores_a_book_opening_whose_initial_the_ocr_lost():
    assert fetch_basinio.tidy("Ec minus interea Divûm pater , atque virorum ,") \
        == "Nec minus interea Divûm pater, atque virorum,"


def test_basinio_closes_up_space_before_punctuation():
    assert fetch_basinio.tidy("Cum primùm , et coelo Phaëton se tollet Eôo ;") \
        == "Cum primùm, et coelo Phaëton se tollet Eôo;"


# --------------------------------------------------------------------------- #
# Ronsard, Franciade
# --------------------------------------------------------------------------- #
def test_franciade_strips_margin_numbers_and_footnote_callouts():
    assert fetch_franciade.tidy("] Des roys françois yssus de Francion ,") \
        == "Des roys françois yssus de Francion ,"
    assert fetch_franciade.tidy("Soyez mon guide (â) et gardez d'abysmer") \
        == "Soyez mon guide et gardez d'abysmer"


def test_franciade_restores_the_first_line_of_a_book():
    assert fetch_franciade.tidy("luse^enten-moy des sommetsdc Parnasse,") \
        == "Muse, enten-moy des sommets de Parnasse,"


def test_franciade_drops_a_running_head_but_not_a_verse():
    assert fetch_franciade.tidy("48 La Francude.") == ""
    assert fetch_franciade.tidy("Estoit assise au sommet de la croupe") \
        == "Estoit assise au sommet de la croupe"


# --------------------------------------------------------------------------- #
# Kudrun
# --------------------------------------------------------------------------- #
def test_kudrun_anchors_leave_out_a_misread_number():
    # '2' was read as '9': the longest increasing run skips it, where a rule
    # that accepts anything plausible after the last number would not.
    tokens = [1, 9, 3, 4, 5, 6]
    assert fetch_kudrun.anchors(tokens) == [0, 2, 3, 4, 5]


def test_kudrun_anchors_ignore_unreadable_numbers():
    assert fetch_kudrun.anchors([1, None, 3, 4]) == [0, 2, 3]


def test_kudrun_parse_reads_strophes_and_not_the_commentary(tmp_path):
    ocr = tmp_path / "bartsch.txt"
    ocr.write_text("\n".join([
        "intro quotes: 1 Ez wuohs in der Einleitung nur",
        "",
        "1 Ez wuohs in Irlande — ein richer künic hér.",
        "geheizen was er Sigebant, — sin vater der hiez Gér.",
        "sin muoter diu hiez Uote — und was ein küniginne.",
        "durch ir hohe tugende — só gezam dem richen wol ir minne.",
        "",
        "1, 1 Dem Anfange des Nibelungenliedes nachgebildet; vgl. Nib. 2, 1.",
        "wuohs in Burgonden ein schene magedin; — 2 geheizen, genannt.",
        "",
        "2 Gére dem richen künige, — daz ist wol erkant,",
        "dienden vil der bürge; — er het siben fürsten lant.",
        "dar inne het er recken — vier tüsent oder mére,",
        "dá mite er tegelichen — mohte erwerben beide guot und ére,",
    ]), encoding="utf-8")
    strophes = fetch_kudrun.parse(ocr)
    assert sorted(strophes) == [1, 2]
    assert strophes[1][0].startswith("Ez wuohs in Irlande")
    assert all("stf" not in ln and "vgl" not in ln for blk in strophes.values() for ln in blk)


# --------------------------------------------------------------------------- #
# Mistral, Mireio
# --------------------------------------------------------------------------- #
def test_mireio_tells_provencal_verse_from_french_prose():
    assert fetch_mireio.is_provencal("Lou sabes : entre la verduro,")
    assert fetch_mireio.is_provencal("Au soulèu em'i bagnaduro,")
    assert not fetch_mireio.is_provencal(
        "Toi, Seigneur Dieu de ma patrie, — qui naquis parmi les pâtres,")
    assert not fetch_mireio.is_provencal(
        "et frais, ingénu, son visage, à fleur de joues, avait deux fossettes")


def test_mireio_reads_a_garbled_running_head_and_its_language():
    french = fetch_mireio.head("MIREILLE, CHANT III. lH")
    provencal = fetch_mireio.head("58 MIRÈIO, CANT II.")
    assert french is not None and french.group(1) == "H"
    assert provencal is not None and provencal.group(1) == ""


def test_mireio_does_not_take_verse_for_a_head():
    assert fetch_mireio.head("Lontèms après lou cant escoutavon enca.") is None


# --------------------------------------------------------------------------- #
# Cid
# --------------------------------------------------------------------------- #
def test_cid_assonance_is_the_vowels_from_the_last_stress():
    assert fetch_cid.assonance("Mió Cid movió de Bivar pora Burgos adelinado,") == "a-o"
    assert fetch_cid.assonance("assi dexa sus palafios yermos e desheredados.") == "a-o"
    assert fetch_cid.assonance("el que en buen ora nasció") == "o"          # stressed last syllable


def test_cid_cuts_a_laisse_where_the_assonance_changes_for_good():
    a = ["verso de lado"] * 8                  # a-o
    b = ["verso de fuera"] * 8                 # u-a? -> e-a
    stray = a[:4] + ["una linea rota"] + a[4:]
    pattern = [v for v in a + b]
    assert len(fetch_cid.laisses(pattern)) == 2
    # One spoiled verse inside a laisse does not split it.
    assert len(fetch_cid.laisses(stray + b)) == 2


def test_cid_folds_a_stub_laisse_into_the_one_before():
    a = ["verso de lado"] * 8
    stub = ["verso de fuera"] * 2
    assert len(fetch_cid.laisses(a + stub)) == 1
