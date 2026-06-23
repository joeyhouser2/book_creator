"""MT-pivot alignment (Bleualign-style).

Translate the source segments to rough English with a per-language translator,
then align those machine translations against the real English translation. Both
sides are English, so a simple monolingual similarity is reliable — the machine
translation only has to be good enough to match sentences, not to read well.

The emitted beads contain the ORIGINAL source and target text; the machine
translation is used only for scoring.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .align import beads_from_path, run_dp
from .model import Bead

# Same monotone moves as the embedding aligner; 2-2 excluded (decomposable).
_STEPS = [(1, 1), (1, 0), (0, 1), (2, 1), (1, 2)]
_MERGE_PENALTY = 0.15
_NULL_COST = 0.85

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _bag(text: str) -> Counter:
    return Counter(_WORD.findall(text.lower()))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    num = sum(a[t] * b[t] for t in common)
    da = math.sqrt(sum(v * v for v in a.values()))
    db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


def mt_align(src: list[str], tgt: list[str], *, translator, log=None) -> list[Bead]:
    if not src and not tgt:
        return []
    if not src:
        return [Bead(src=[], tgt=tgt)]
    if not tgt:
        return [Bead(src=src, tgt=[])]

    mt = translator(list(src))  # rough English for each source segment
    if len(mt) != len(src):
        raise ValueError(f"translator returned {len(mt)} items for {len(src)} inputs")

    sv = [_bag(t) for t in mt]
    tv = [_bag(t) for t in tgt]

    def pooled(vecs, start, count):
        c = Counter()
        for k in range(start, start + count):
            c.update(vecs[k])
        return c

    def cost_fn(i, j, ds, dt):
        if ds == 0 or dt == 0:
            return _NULL_COST
        sim = _cosine(pooled(sv, i, ds), pooled(tv, j, dt))
        return (1.0 - sim) + _MERGE_PENALTY * (ds + dt - 2)

    path = run_dp(len(src), len(tgt), cost_fn, steps=_STEPS)
    return beads_from_path(src, tgt, path)
