"""Structural-division heading detection.

The keyword and ordinal lists are shared by every book, so widening them for one
work risks inventing chapters in all the others. These tests pin both directions:
the headings that must be found, and the prose that must not be mistaken for one.
"""

from __future__ import annotations

import pytest

from book_creator.segment import _is_heading, detect_chapters

# --------------------------------------------------------------------------- #
# Headings that must be recognised
# --------------------------------------------------------------------------- #
HEADINGS = [
    # Keyword then number -- Latin and Romance word order.
    "CHAPTER IV.",
    "CHAPTER IV. THE INCONVENIENCES OF FOLLOWING A PRETTY WOMAN",
    "Chapter 3",
    "Liber II",
    "CAPUT III",
    "COMMENTARIUS PRIMUS",
    "LIVRE DEUXIÈME",
    "CHAPITRE PREMIER",
    "Kapitel 7",
    "BOOK SEVENTH",
    # French verse epics divide into chants (La Henriade, La Franciade).
    "Chant I",
    "Chant premier",
    "CHANT PREMIER.",
    "CHANT QUATRIÈME",
    # Romance epics number their cantos by ordinal word.
    "Canto Primeiro",          # Os Lusíadas
    "Canto Décimo",
    "Canto Sétimo",
    "Canto Primo",             # Gerusalemme Liberata
    "Canto Ottavo",
    "CANTO PRIMERO",           # La Araucana
    # Ordinal then keyword -- German, and the English translations that follow it.
    # The Nibelungenlied runs to 39, so the lists have to reach that far.
    "Erstes Abenteuer.",
    "Zwölftes Abenteuer.",
    "Dreizehntes Abenteuer.",
    "Neunzehntes Abenteuer.",
    "Zwanzigste Abenteuer.",
    "Einundzwanzigstes Abenteuer.",
    "Dreißigstes Abenteuer.",
    "Neununddreißigstes Abenteuer.",
    "Eilftes Abenteuer.",            # Simrock's archaic spelling of "elftes"
    "Erste Aventiure",
    "FIRST ADVENTURE",
    "FIRST ADVENTURE: Kriemhild's Dream.",
    "TWELFTH ADVENTURE",
    "TWENTIETH ADVENTURE",
    "TWENTY-FIRST ADVENTURE",
    "THIRTY-NINTH ADVENTURE",
]


@pytest.mark.parametrize("line", HEADINGS)
def test_heading_is_recognised(line):
    assert _is_heading(line)


# --------------------------------------------------------------------------- #
# Prose that must NOT be taken for a heading
# --------------------------------------------------------------------------- #
NOT_HEADINGS = [
    "",
    "   ",
    # Real lines from the scholarly apparatus of Gutenberg 14915 and 7321, which
    # sit in the same file as the headings above.
    "Die ersten neunzehn Abenteuer bilden den ersten Rheinischen Theil des",
    "1362, wo ein Lied und zugleich ein Abenteuer anfängt.",
    "gleichfalls keine und das Abenteuer mit Gelfrat und Else (Str.",
    "eingeschaltete Warnung vor einer Art Pulververschwörung (28. Abenteuer)",
    # An ordinal-first match must be ordinal-INITIAL, or ordinary prose that
    # happens to contain "second part" or "twentieth chapter" becomes a chapter.
    "he told of the second part of the journey",
    "and so the twentieth chapter of his life closed in sorrow",
    "it was mentioned in the first book of the series, at length",
    # A verse line ending in a division keyword followed by its column-aligned
    # stanza number. Burton's Lusiads is full of these, and they split cantos
    # in half until the trailing number was stripped before matching.
    "But Mars, for ever wont t’espouse the part      36",
    "“Compast our courses thence the greater part      10",
    # "chant" is an ordinary word in both French and English; only a heading
    # puts a numeral right after it on a short line.
    "il écoutait le chant des oiseaux dans les arbres du parc ce matin-là",
    "the chant rose and fell among the pillars of the dim cathedral nave",
    # "segundo"/"primeiro" are everyday words; only a heading puts one straight
    # after a division keyword on a short line.
    "o segundo dia de viagem foi mais calmo que o primeiro para todos",
    "y el segundo canto de las aves llenaba el aire de la mañana aquel día",
    # The lowercase-roman trap the original code guarded against: an elided "d"
    # must not read as a roman numeral after a French keyword.
    "...de la part d'un domestique?",
    # Too long to be a title line.
    "CHAPTER IV. " + "and so on " * 30,
]


@pytest.mark.parametrize("line", NOT_HEADINGS)
def test_prose_is_not_a_heading(line):
    assert not _is_heading(line)


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #
def test_german_epic_divides_on_its_aventiuren():
    text = "\n\n".join(
        f"{name} Abenteuer.\n\nSome verse line here.\nAnd another line."
        for name in ["Erstes", "Zweites", "Zwanzigste", "Neununddreißigstes"])
    titles = [t for t, _ in detect_chapters(text, mode="verse")]
    assert [t for t in titles if "Abenteuer" in t] == [
        "Erstes Abenteuer.", "Zweites Abenteuer.",
        "Zwanzigste Abenteuer.", "Neununddreißigstes Abenteuer."]


def test_english_translation_divides_on_the_same_count():
    """The two sides must produce equal counts, or they cannot be anchored."""
    de = "\n\n".join(f"{n} Abenteuer.\n\nZeile eins.\nZeile zwei."
                     for n in ["Erstes", "Zweites", "Drittes"])
    en = "\n\n".join(f"{n} ADVENTURE: A Title.\n\nLine one.\nLine two."
                     for n in ["FIRST", "SECOND", "THIRD"])
    assert (len(detect_chapters(de, mode="verse"))
            == len(detect_chapters(en, mode="verse")))
