"""Explicit stanza pairing (pipeline._explicit_stanza_pairs)."""

from __future__ import annotations

import pytest

from book_creator import pipeline

SRC = [[f"G{i}a", f"G{i}b"] for i in range(1, 6)]     # 5 original stanzas
TGT = [[f"E{i}a"] for i in range(1, 4)]              # 3 translation stanzas


def test_pairs_are_built_in_order_with_empty_sides_allowed():
    beads = pipeline._explicit_stanza_pairs(
        SRC, TGT, [["1-2", None], ["3", "1"], ["4", "2-3"], ["5", None]])
    assert [(b.src, b.tgt) for b in beads] == [
        (["G1a", "G1b", "G2a", "G2b"], []),
        (["G3a", "G3b"], ["E1a"]),
        (["G4a", "G4b"], ["E2a", "E3a"]),
        (["G5a", "G5b"], []),
    ]
    assert all(b.lines for b in beads)


def test_a_missing_stanza_is_refused():
    with pytest.raises(ValueError, match="covers 4 of 5"):
        pipeline._explicit_stanza_pairs(SRC, TGT, [["1-2", None], ["3", "1"],
                                                   ["4", "2-3"]])


def test_a_stanza_out_of_order_or_repeated_is_refused():
    with pytest.raises(ValueError, match="where 2 was expected"):
        pipeline._explicit_stanza_pairs(SRC, TGT, [["1", None], ["3", "1"]])
    with pytest.raises(ValueError, match="where 2 was expected"):
        pipeline._explicit_stanza_pairs(SRC, TGT, [["1", "1"], ["1", "2"]])


def test_a_range_outside_the_poem_is_refused():
    with pytest.raises(ValueError, match="outside 1-3"):
        pipeline._explicit_stanza_pairs(SRC, TGT, [["1-5", "1-4"]])


def test_entries_must_be_pairs():
    with pytest.raises(ValueError, match="must be"):
        pipeline._explicit_stanza_pairs(SRC, TGT, [["1-5"]])
