"""Gale-Church length-based sentence alignment.

Reference: Gale & Church (1993), "A Program for Aligning Sentences in Bilingual
Corpora." Aligns two lists of segments using only their character lengths, so it
needs no dictionary and works across Latin / Greek / French / German <-> English.

We anchor on chapter boundaries (see pipeline) to keep the dynamic program from
drifting over long texts.
"""

from __future__ import annotations

import math

from .model import Bead

# Prior probability of each alignment category (Gale & Church, Table 5).
_PRIORS = {
    (1, 1): 0.89,
    (1, 0): 0.0099,
    (0, 1): 0.0099,
    (2, 1): 0.089,
    (1, 2): 0.089,
    (2, 2): 0.011,
}
_LOG_PRIORS = {k: -math.log(v) for k, v in _PRIORS.items()}

# Categories considered at each DP step, as (#src, #tgt).
_STEPS = [(1, 1), (1, 0), (0, 1), (2, 1), (1, 2), (2, 2)]


def run_dp(n: int, m: int, cost_fn, steps=None) -> list[tuple[int, int, int, int]]:
    """Generic monotone alignment DP shared by every backend.

    cost_fn(i, j, ds, dt) -> float gives the cost of aligning src[i:i+ds] with
    tgt[j:j+dt]. `steps` is the set of (#src, #tgt) moves allowed (defaults to
    the full Gale-Church set). Returns the path as a list of (i, j, ds, dt) beads.
    """
    steps = steps or _STEPS
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    for i in range(n + 1):
        for j in range(m + 1):
            if cost[i][j] == INF:
                continue
            base = cost[i][j]
            for (ds, dt) in steps:
                ni, nj = i + ds, j + dt
                if ni > n or nj > m:
                    continue
                val = base + cost_fn(i, j, ds, dt)
                if val < cost[ni][nj]:
                    cost[ni][nj] = val
                    back[ni][nj] = (i, j, ds, dt)

    path: list[tuple[int, int, int, int]] = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, ds, dt = back[i][j]
        path.append((pi, pj, ds, dt))
        i, j = pi, pj
    path.reverse()
    return path


def beads_from_path(src, tgt, path) -> list[Bead]:
    return [Bead(src=src[pi:pi + ds], tgt=tgt[pj:pj + dt]) for pi, pj, ds, dt in path]


def _norm_cdf(z: float) -> float:
    """Standard normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _length_cost(sl: int, tl: int, c: float, s2: float) -> float:
    """-log P(match | lengths). Lower is better."""
    if sl == 0 and tl == 0:
        return 0.0
    mean = sl * c
    var = max(sl * s2, 1.0)
    z = (tl - mean) / math.sqrt(var)
    # Two-tailed probability of a deviation at least this large.
    prob = 2.0 * (1.0 - _norm_cdf(abs(z)))
    prob = max(prob, 1e-12)
    return -math.log(prob)


def align_segments(src: list[str], tgt: list[str]) -> list[Bead]:
    """Gale-Church length-based alignment of two segment lists."""
    if not src and not tgt:
        return []
    if not src:
        return [Bead(src=[], tgt=tgt)]
    if not tgt:
        return [Bead(src=src, tgt=[])]

    s_len = [len(s) for s in src]
    t_len = [len(t) for t in tgt]
    c = (sum(t_len) or 1) / (sum(s_len) or 1)  # expected tgt chars per src char
    s2 = 6.8                                    # variance per char (G-C default)

    def cost_fn(i, j, ds, dt):
        sl = sum(s_len[i:i + ds])
        tl = sum(t_len[j:j + dt])
        return _length_cost(sl, tl, c, s2) + _LOG_PRIORS[(ds, dt)]

    path = run_dp(len(src), len(tgt), cost_fn)
    return beads_from_path(src, tgt, path)


# Backwards/forwards-compatible alias for the Gale-Church backend.
gale_church = align_segments
