"""Line-level re-cut: the solver and the caching driver, with synthetic support."""

from __future__ import annotations

from book_creator import align_lines as al
from book_creator.model import Bead, Chapter


def _book(true_counts: list[int], shift: dict[int, int]) -> tuple[list[Bead], list[int]]:
    """Beads whose English was cut `shift[t]` lines too early (+) or late (-).

    Returns the displaced beads and, for each flat English line, the block it
    truly belongs to.
    """
    lines = []
    truth = []
    for t, c in enumerate(true_counts):
        for k in range(c):
            lines.append(f"b{t}l{k}")
            truth.append(t)
    # Cut positions: true cut + displacement.
    cuts, pos = [], 0
    for t, c in enumerate(true_counts):
        pos += c
        cuts.append(pos + shift.get(t, 0))
    beads, start = [], 0
    for t, cut in enumerate(cuts):
        beads.append(Bead(src=[f"de{t}a", f"de{t}b"], tgt=lines[start:cut]))
        start = cut
    return beads, truth


def _support(beads, truth, reach, right=5.0, wrong=0.0):
    jobs, origin = al.build_jobs(beads, reach)
    flat_index = {}
    n = 0
    for b, bead in enumerate(beads):
        for k in range(len(bead.tgt)):
            flat_index[(b, k)] = n
            n += 1
    sup = []
    for t, org in enumerate(origin):
        sup.append([right if truth[flat_index[(b, k)]] == t else wrong for (b, k, _) in org])
    return sup, origin


def _assignment_blocks(beads, assignment):
    out = [[] for _ in beads]
    flat = [ln for b in beads for ln in b.tgt]
    for ln, a in zip(flat, assignment):
        out[a].append(ln)
    return out


def test_window_has_neighbour_tail_own_and_next_head():
    beads, _ = _book([4, 4, 4], {})
    jobs, origin = al.build_jobs(beads, reach=2)
    assert jobs[1]["tgt"] == ["b0l2", "b0l3", "b1l0", "b1l1", "b1l2", "b1l3", "b2l0", "b2l1"]
    assert jobs[0]["tgt"][:4] == ["b0l0", "b0l1", "b0l2", "b0l3"]
    assert [o[:2] for o in origin[1][:2]] == [(0, 2), (0, 3)]


def test_a_displaced_boundary_is_put_back():
    # Block 1's English is cut 3 lines early: its first 3 lines sit in block 0.
    beads, truth = _book([6, 6, 6, 6], {0: 3})
    assert len(beads[0].tgt) == 9 and len(beads[1].tgt) == 3
    sup, origin = _support(beads, truth, reach=6)
    assign = al.solve(beads, sup, origin, lam=1.0, kappa=4.0)
    blocks = _assignment_blocks(beads, assign)
    assert [len(b) for b in blocks] == [6, 6, 6, 6]
    assert blocks[1][0] == "b1l0"


def test_a_displacement_the_other_way_is_put_back_too():
    beads, truth = _book([6, 6, 6], {0: -3})
    sup, origin = _support(beads, truth, reach=6)
    blocks = _assignment_blocks(beads, al.solve(beads, sup, origin, kappa=4.0))
    assert [len(b) for b in blocks] == [6, 6, 6]


def test_weak_evidence_does_not_move_a_line():
    beads, truth = _book([6, 6, 6], {0: 2})
    sup, origin = _support(beads, truth, reach=6, right=1.0, wrong=0.0)   # < lam
    assign = al.solve(beads, sup, origin, lam=2.0)
    assert _assignment_blocks(beads, assign) == [b.tgt for b in beads]


def test_no_block_is_left_empty():
    # The evidence says everything belongs to block 0; blocks must keep a line.
    beads, truth = _book([3, 3, 3], {})
    sup, origin = _support(beads, [0] * 9, reach=3, right=9.0)
    blocks = _assignment_blocks(beads, al.solve(beads, sup, origin, lam=0.1))
    assert all(len(b) >= 1 for b in blocks)


def test_a_bead_with_no_english_stays_empty_and_is_skipped():
    beads, truth = _book([4, 0, 4], {})
    sup, origin = _support(beads, [0] * 4 + [2] * 4, reach=3)
    assign = al.solve(beads, sup, origin)
    blocks = _assignment_blocks(beads, assign)
    assert blocks[1] == [] and len(blocks[0]) == 4 and len(blocks[2]) == 4


def test_missing_scores_leave_lines_where_they_were():
    beads, truth = _book([5, 5], {0: 2})
    jobs, origin = al.build_jobs(beads, reach=5)
    none_support = [[None] * len(j["tgt"]) for j in jobs]
    assign = al.solve(beads, none_support, origin)
    assert _assignment_blocks(beads, assign) == [b.tgt for b in beads]


def test_recut_chapters_applies_the_move_and_caches(tmp_path):
    beads, truth = _book([6, 6, 6, 6], {1: 3})
    ch = Chapter(title="I", beads=beads)
    calls = []

    def scorer(jobs):
        calls.append(len(jobs))
        sup, _ = _support(ch.beads, truth, reach=6)
        return sup

    stats = al.recut_chapters([ch], src_lang="de", tgt_lang="en", model="m", kappa=4.0,
                              reach=6, cache_dir=tmp_path, scorer=scorer, log=lambda m: None)
    assert [len(b.tgt) for b in ch.beads] == [6, 6, 6, 6]
    assert stats["moved"] == 3 and stats["beads"] == 2
    # Second run: nothing left to move, and the (new) text scores via its own key.
    before = [list(b.tgt) for b in ch.beads]
    al.recut_chapters([ch], src_lang="de", tgt_lang="en", model="m", reach=6,
                      kappa=4.0, cache_dir=tmp_path, scorer=scorer, log=lambda m: None)
    assert [b.tgt for b in ch.beads] == before


def test_cache_hit_skips_the_scorer(tmp_path):
    beads, truth = _book([6, 6, 6], {0: 2})
    ch = Chapter(title="I", beads=beads)
    sup, _ = _support(ch.beads, truth, reach=6)
    jobs, _ = al.build_jobs(ch.beads, 6)
    (tmp_path / f"{al._digest(jobs, 'm', 6)}.json").write_text(
        __import__("json").dumps(sup), encoding="utf-8")

    def boom(jobs):
        raise AssertionError("scorer must not run on a cache hit")

    al.recut_chapters([ch], src_lang="de", tgt_lang="en", model="m", reach=6,
                      kappa=4.0, cache_dir=tmp_path, scorer=boom, log=lambda m: None)
    assert [len(b.tgt) for b in ch.beads] == [6, 6, 6]


def test_a_gain_below_the_boundary_price_is_not_taken():
    # Two lines of weak evidence (2 x 3 nats, minus lam) cannot pay for kappa=12.
    beads, truth = _book([6, 6, 6], {0: 2})
    sup, origin = _support(beads, truth, reach=6, right=3.0)
    assign = al.solve(beads, sup, origin, lam=1.0, kappa=12.0)
    assert _assignment_blocks(beads, assign) == [b.tgt for b in beads]


def test_a_boundary_moves_once_whatever_its_length():
    beads, truth = _book([8, 8, 8], {0: 5})
    sup, origin = _support(beads, truth, reach=8, right=4.0)
    cheap = al.solve(beads, sup, origin, lam=0.0, kappa=12.0)    # 5 lines x 4 = 20 > 12
    assert [len(b) for b in _assignment_blocks(beads, cheap)] == [8, 8, 8]


def test_length_prior_stops_a_block_being_starved():
    # Evidence mildly prefers giving block 1's lines to block 0, but doing so
    # would leave block 1 with one English line for four German lines.
    beads = [Bead(src=[f"d{t}{i}" for i in range(4)],
                  tgt=[f"b{t}l{k}" for k in range(6)]) for t in range(3)]
    # Window 0 likes block 1's first 5 lines slightly more than window 1 does.
    jobs, origin = al.build_jobs(beads, reach=6)
    sup = []
    for t, org in enumerate(origin):
        row = []
        for (b, k, _) in org:
            row.append(4.0 if b == t else (5.0 if (b == 1 and t == 0 and k < 5) else 0.0))
        sup.append(row)
    free = al.solve(beads, sup, origin, lam=0.0, kappa=0.0, mu=0.0)
    kept = al.solve(beads, sup, origin, lam=0.0, kappa=0.0, mu=10.0)
    n_free = sum(1 for a in free if a == 1)
    n_kept = sum(1 for a in kept if a == 1)
    assert n_free < n_kept and n_kept >= 5
