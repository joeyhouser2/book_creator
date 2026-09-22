"""Guessing a text's language, so the narrator is not handed the wrong one."""

from __future__ import annotations

from book_creator import langid

ENGLISH = ("The Duke left the Hague on the eleventh and reached Brussels on the "
           "thirteenth. Here he discussed the military situation with Overkirk "
           "and the field-deputies, and directed the army to concentrate at "
           "Anderlecht on the outskirts of the city. The French were loudly "
           "boasting that they intended to quit their lines and to offer battle.")
LATIN = ("Gallia est omnis divisa in partes tres, quarum unam incolunt Belgae, "
         "aliam Aquitani, tertiam qui ipsorum lingua Celtae, nostra Galli "
         "appellantur. Hi omnes lingua, institutis, legibus inter se differunt. "
         "Gallos ab Aquitanis Garumna flumen, a Belgis Matrona et Sequana dividit.")
FRENCH = ("Le père Goriot était un homme de soixante-neuf ans environ qui "
          "s'était retiré dans cette pension après avoir quitté le commerce. "
          "Les pensionnaires de la maison ne savaient rien de sa fortune, mais "
          "ils en parlaient avec une curiosité qui ne se lassait pas du tout.")


def test_the_language_of_a_page_of_prose():
    assert langid.guess(ENGLISH) == "en"
    assert langid.guess(LATIN) == "la"
    assert langid.guess(FRENCH) == "fr"


def test_greek_is_told_by_its_alphabet_and_its_accents():
    ancient = "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν. " * 6
    modern = "Η γλώσσα και η ιστορία της χώρας μας είναι πολύ σημαντικές. " * 8
    assert langid.guess(ancient) == "grc"
    assert langid.guess(modern) == "el"


def test_it_says_nothing_rather_than_guess():
    """Leaving the language box alone beats setting it wrongly."""
    assert langid.guess("Hello there") is None            # too little to judge
    assert langid.guess("1921 1922 1923 " * 40) is None   # no words at all
    # Latin and Italian share words; a scrap of either says too little.
    assert langid.guess("in non est ad per " * 12) in (None, "la")


def test_a_scanned_books_ocr_is_still_readable_enough():
    """OCR of an old scan: "wliich" for "which", "alHes" for "allies"."""
    rough = ENGLISH.replace("which", "wliich").replace("the", "tlie", 3)
    assert langid.guess(rough) == "en"
