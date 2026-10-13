"""tgt_replace: whole-word fixes on the translation side only."""

from book_creator.model import Bead, Chapter
from book_creator.pipeline import apply_tgt_replace


def _book():
    return [Chapter(title="I", beads=[
        Bead(src=["Henri, roi de Navarre, et Médicis"],
             tgt=["Henri, king of Navarre, and Médicis; Henrietta; Henri's son"]),
        Bead(src=["Médicis"], tgt=["Medicis"]),
    ])]


def test_replaces_whole_words_on_the_translation_only():
    chapters = _book()
    n = apply_tgt_replace(chapters, {"Henri": "Henry", "Médicis": "Medici",
                                     "Medicis": "Medici"}, lambda m: None)
    b0, b1 = chapters[0].beads
    assert b0.tgt == ["Henry, king of Navarre, and Medici; Henrietta; Henry's son"]
    assert b1.tgt == ["Medici"]
    assert b0.src == ["Henri, roi de Navarre, et Médicis"]   # original untouched
    assert n == 4


def test_empty_mapping_is_a_no_op():
    chapters = _book()
    assert apply_tgt_replace(chapters, {}, lambda m: None) == 0
    assert chapters[0].beads[1].tgt == ["Medicis"]
