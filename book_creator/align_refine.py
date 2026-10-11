"""Nudge the cut points of a block alignment onto the text that fits them.

A block aligner scores six German lines against about nine English ones, and an
embedding cannot say where inside that window the passage really ends: tested
on Klopstock, its best cut for a boundary was spread evenly over +-6 lines.
So a name that opens one German block ("Selia endigte ...") could sit in the
English of the block before it.

Proper names are the exception, because they are the same word in both
languages. Each boundary is therefore re-cut, within a few lines of where the
aligner put it, to the place that keeps every name with the block that holds
it, preferring a place where an English sentence ends.

Only the English cut moves; the German blocks stay as the aligner set them.
"""

from __future__ import annotations

import re

from .model import Bead

_CAP = re.compile(r"\b[A-ZÄÖÜ][A-Za-zäöüß]{3,}\b")
_END = re.compile(r"[.!?;:]['\"”»«]*\s*$")


def _norm(word: str) -> str:
    """'Eloah'/'Eloa', 'Messias'/'Messiah': the same name, spelled two ways."""
    return re.sub(r"(h|s|n)$", "", word.lower())


def _names(lines: list[str]) -> set[str]:
    return {_norm(w) for line in lines for w in _CAP.findall(line)}


def shared_names(src_lines: list[str], tgt_lines: list[str]) -> set[str]:
    """Capitalised words, in both texts, that are not merely a German noun and
    its English twin sentence-initial: appears in both, and at least twice."""
    from collections import Counter
    a = Counter(_norm(w) for line in src_lines for w in _CAP.findall(line))
    b = Counter(_norm(w) for line in tgt_lines for w in _CAP.findall(line))
    return {w for w in a if a[w] >= 2 and b.get(w, 0) >= 2}


def refine(beads: list[Bead], reach: int = 8) -> list[Bead]:
    """Return the beads with each English cut moved to its best place."""
    src_all = [ln for b in beads for ln in b.src]
    tgt_all = [ln for b in beads for ln in b.tgt]
    names = shared_names(src_all, tgt_all)
    if not names or len(beads) < 2:
        return beads

    # Line-level view: every bead's English as a flat list, cuts as indices.
    tgt_lines = [list(b.tgt) for b in beads]
    flat = [ln for lines in tgt_lines for ln in lines]
    cuts = []
    pos = 0
    for lines in tgt_lines:
        pos += len(lines)
        cuts.append(pos)                       # cuts[t] = end (exclusive) of bead t

    gnames = [_names(b.src) & names for b in beads]
    lname = [_names([ln]) & names for ln in flat]

    def block(a: int, z: int) -> set[str]:
        out: set[str] = set()
        for i in range(a, z):
            out |= lname[i]
        return out

    for t in range(len(beads) - 1):
        a_set, b_set = gnames[t], gnames[t + 1]
        if not a_set and not b_set:
            continue
        e0 = cuts[t - 1] if t > 0 else 0
        e2 = cuts[t + 1]
        c0 = cuts[t]
        best, best_score = c0, None
        for c in range(max(e0 + 1, c0 - reach), min(e2 - 1, c0 + reach) + 1):
            left, right = block(e0, c), block(c, e2)
            score = (len(a_set & left) + len(b_set & right)
                     - len(a_set & right - left) - len(b_set & left - right))
            if _END.search(flat[c - 1]):
                score += 0.35
            score -= 0.03 * abs(c - c0)
            if best_score is None or score > best_score:
                best, best_score = c, score
        cuts[t] = best

    out = []
    start = 0
    for t, b in enumerate(beads):
        end = cuts[t]
        out.append(Bead(src=list(b.src), tgt=flat[start:end], lines=b.lines,
                        heading=b.heading, score=b.score))
        start = end
    return out
