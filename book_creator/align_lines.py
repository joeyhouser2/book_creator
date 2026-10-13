"""Re-cut a block alignment line by line, using what a translation model says
each English line is translating.

`align_refine` moves a boundary by shared proper names, within a few lines. That
cannot fix a block whose English sits wholly in its neighbour's tail, which is
what proofreading Klopstock found: the German block's English was displaced by
2-12 lines, so a six-line German block faced one English line while the block
before it overflowed.

The German blocks stay as the aligner set them. Only English lines move, and
only across a boundary to the adjacent block:

  1. For each German block t, a window is cut from the English: the whole of
     bead t, the tail of bead t-1 and the head of bead t+1 (`reach` lines).
  2. A translation model scores every line of the window against block t alone:
     log P(line | block) - log P(line | no source), summed over tokens. That is
     the evidence, in nats, that the block is what the line translates.
  3. A line can sit in its own bead or, if it is in the head/tail of one, the
     neighbour's. Choosing a block for every line, in order, to maximise total
     evidence is a small monotone DP. Each block must keep at least one line,
     and moving a line costs `lam` nats, so a doubtful line stays where it was.

The scoring runs on the GPU in a subprocess (proofread_pairs `--support`) and
is cached on the text, so rebuilding a book costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from .model import Bead, Chapter

DEFAULT_REACH = 24
DEFAULT_LAMBDA = 1.0
# Weight of the block-length prior: nats per squared log-ratio of English lines
# to what the German block's size warrants.
DEFAULT_MU = 10.0
# Nats of evidence needed to move a *boundary* at all. Per-line scores are
# noisy, and choosing the best of ~25 candidate cuts per boundary always finds
# some noise that looks like a gain; a fixed price per moved boundary is what
# keeps a correct cut where it is. Chosen on Klopstock by sweeping kappa and mu
# against an independent measure (LaBSE similarity and drift, not used in the
# objective): 6 / 10 gave the most improved beads with the fewest regressions
# that still moved all but one of the hand-checked defects.
DEFAULT_KAPPA = 6.0


def build_jobs(beads: list[Bead], reach: int) -> tuple[list[dict], list[int]]:
    """One scoring window per bead, over the flat run of English lines.

    Block t's window is every English line from `reach` lines before its
    current start to `reach` lines after its current end (within the chapter),
    however many beads that crosses. The second return is each window's first
    flat line index, so window position p is flat line origin[t] + p.
    """
    flat = [ln for b in beads for ln in b.tgt]
    jobs: list[dict] = []
    origin: list[int] = []
    end = 0
    for b in beads:
        start, end = end, end + len(b.tgt)
        lo, hi = max(0, start - reach), min(len(flat), end + reach)
        jobs.append({"src": list(b.src), "tgt": flat[lo:hi]})
        origin.append(lo)
    return jobs, origin


def solve(beads: list[Bead], support: list[list[float | None]],
          origin: list[int], lam: float = DEFAULT_LAMBDA,
          kappa: float = DEFAULT_KAPPA, mu: float = DEFAULT_MU,
          reach: int = DEFAULT_REACH) -> list[int]:
    """The block each English line belongs to, as one list over the flat
    English of `beads` in order.

    The English is one run of lines and the blocks tile it, so the whole
    answer is the set of boundary positions c_0 < c_1 < ... between blocks.
    Each boundary may sit anywhere within `reach` lines of where it was, and
    the best set maximises

        sum over blocks t of  [ evidence that block t is what its lines
                                translate  -  length prior(t) ]
        - lam * (lines moved)  -  kappa * (boundaries moved)

    where the evidence for a line in block t is the support window t gave it
    (`support[t][p]` is flat line `origin[t] + p`). The length prior
    keeps a block from being left with far fewer English lines than its German
    warrants, which the evidence alone will happily do.
    """
    n = len(beads)
    sizes = [len(b.tgt) for b in beads]
    total = sum(sizes)
    if total == 0 or n == 0:
        return [0] * total
    off = [0]
    for s_ in sizes:
        off.append(off[-1] + s_)
    orig_cut = off[1:]                       # orig_cut[t] = end of block t
    g = [max(1, len(b.src)) for b in beads]
    ratio = total / max(1, sum(g))

    # prefix[e - lo] = evidence block t has for lines lo .. e-1 of its window
    def prefix_for(t: int) -> tuple[int, list[float]]:
        row = support[t] if t < len(support) else []
        lo = origin[t] if t < len(origin) else 0
        pre = [0.0]
        for v in row:
            pre.append(pre[-1] + (v if v is not None else 0.0))
        return lo, pre

    def evidence(t: int, lo: int, pre: list[float], a: int, z: int) -> float:
        a_, z_ = max(a, lo) - lo, min(z, lo + len(pre) - 1) - lo
        return pre[z_] - pre[a_] if z_ > a_ else 0.0

    def length_cost(t: int, count: int) -> float:
        if sizes[t] == 0 and count == 0:
            return 0.0
        want = ratio * g[t]
        return mu * math.log((count + 1.0) / (want + 1.0)) ** 2

    NEG = float("-inf")
    # f[c] = best value with the current block ending at c
    f: dict[int, tuple[float, int | None]] = {0: (0.0, None)}
    back: list[dict[int, int | None]] = []
    for t in range(n):
        lo, pre = prefix_for(t)
        if t == n - 1:
            ends = [total]
        else:
            ends = list(range(max(0, orig_cut[t] - reach), min(total, orig_cut[t] + reach) + 1))
        nf: dict[int, tuple[float, int | None]] = {}
        empty_ok = sizes[t] == 0
        for c in ends:
            best, arg = NEG, None
            for a, (v, _) in f.items():
                if c < a or (c == a and not empty_ok):
                    continue
                score = v + evidence(t, lo, pre, a, c) - length_cost(t, c - a)
                if score > best:
                    best, arg = score, a
            if arg is None:
                continue
            moved = abs(c - orig_cut[t]) if t < n - 1 else 0
            best -= lam * moved + (kappa if moved else 0.0)
            nf[c] = (best, arg)
        if not nf:                            # no legal cut: keep the original
            nf = {orig_cut[t]: (max(v for v, _ in f.values()), min(f))}
        back.append({c: a for c, (_, a) in nf.items()})
        f = nf

    # Walk back from the end to recover each boundary.
    cut = total
    cuts = [0] * n
    for t in range(n - 1, -1, -1):
        cuts[t] = cut
        a = back[t].get(cut)
        cut = a if a is not None else (orig_cut[t - 1] if t > 0 else 0)
    out = [0] * total
    start = 0
    for t in range(n):
        for e in range(start, cuts[t]):
            out[e] = t
        start = cuts[t]
    return out


def _digest(jobs: list[dict], model: str, reach: int) -> str:
    h = hashlib.sha1()
    h.update(json.dumps([model, reach, jobs], ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:20]


def recut_beads(beads: list[Bead], assignment: list[int]) -> int:
    """Rewrite `beads[*].tgt` from a flat per-line assignment. Returns the
    number of lines that changed block."""
    flat = [ln for b in beads for ln in b.tgt]
    owners = [i for i, b in enumerate(beads) for _ in b.tgt]
    moved = sum(1 for o, a in zip(owners, assignment) if o != a)
    new: list[list[str]] = [[] for _ in beads]
    for ln, a in zip(flat, assignment):
        new[a].append(ln)
    for b, lines in zip(beads, new):
        b.tgt = lines
    return moved


def recut_chapters(chapters: list[Chapter], *, src_lang: str, tgt_lang: str,
                   model: str, reach: int = DEFAULT_REACH, lam: float = DEFAULT_LAMBDA,
                   kappa: float = DEFAULT_KAPPA, mu: float = DEFAULT_MU,
                   device: str = "auto", quant: str = "auto", batch_size: int = 3,
                   cache_dir: str | Path = "cache/recut",
                   scorer: Callable | None = None,
                   log: Callable[[str], None] = print) -> dict:
    """Re-cut every chapter's English in place; return statistics."""
    work = [(ci, ch) for ci, ch in enumerate(chapters)
            if len(ch.beads) >= 2 and any(b.tgt for b in ch.beads)]
    jobs: list[dict] = []
    spans: list[tuple[int, int, int]] = []        # (chapter, first job, job count)
    origins: list[int] = []
    for ci, ch in work:
        j, o = build_jobs(ch.beads, reach)
        spans.append((ci, len(jobs), len(j)))
        jobs += j
        origins += o
    if not jobs:
        return {"moved": 0, "beads": 0, "chapters": 0}

    key = _digest(jobs, model, reach)
    cache = Path(cache_dir) / f"{key}.json"
    support = None
    if cache.exists():
        try:
            support = json.loads(cache.read_text(encoding="utf-8"))
            log(f"  re-cut: using cached line support ({len(support)} windows)")
        except (OSError, ValueError):
            support = None
    if support is None or len(support) != len(jobs):
        if scorer is None:
            from . import proofread_pairs as pp
            opts = {"src_lang": src_lang, "tgt_lang": tgt_lang, "model": model,
                    "quant": quant, "device": device, "batch_size": batch_size}
            log(f"  re-cut: scoring {len(jobs)} windows with {model}")
            support = pp.run_worker(jobs, opts, log, mode="--support")
        else:
            support = scorer(jobs)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(support), encoding="utf-8")

    moved = changed = 0
    for ci, start, count in spans:
        beads = chapters[ci].beads
        before = [list(b.tgt) for b in beads]
        assign = solve(beads, support[start:start + count], origins[start:start + count],
                       lam, kappa, mu, reach)
        moved += recut_beads(beads, assign)
        changed += sum(1 for b, old in zip(beads, before) if b.tgt != old)
    return {"moved": moved, "beads": changed, "chapters": len(work)}
