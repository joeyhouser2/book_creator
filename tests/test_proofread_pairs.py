"""Pair proofreading: the analysis and report, with a fake scorer (no GPU)."""

from __future__ import annotations

import random

from book_creator import proofread_pairs as pp
from book_creator.model import Bead, Chapter


def _items(n: int, tgt_len: int = 60) -> list[dict]:
    out = []
    for i in range(n):
        src, tgt = "word " * 12, "term " * (tgt_len // 5)
        out.append({"src": src, "tgt": tgt, "src_lines": [src], "tgt_lines": [tgt],
                    "chapter_index": 0, "chapter_title": "I", "bead_index": i})
    return out


def _blocks(n: int, k: int = 4) -> list[dict]:
    """Beads of k lines a side, like verse blocks."""
    out = []
    for i in range(n):
        sl = [f"line {j} of the original block {i} text here" for j in range(k)]
        tl = [f"verse {j} of the rendering of block {i} here too" for j in range(k)]
        out.append({"src": " ".join(sl), "tgt": " ".join(tl), "src_lines": sl,
                    "tgt_lines": tl, "chapter_index": 0, "chapter_title": "I",
                    "bead_index": i})
    return out


def _line_metrics(n: int, k: int = 4, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    ms = _healthy(n, seed)
    for m in ms:
        m["fwd_lines"] = [1.5 + rng.uniform(-0.3, 0.3) for _ in range(k)]
        m["rev_lines"] = [1.4 + rng.uniform(-0.3, 0.3) for _ in range(k)]
    return ms


def _healthy(n: int, seed: int = 1) -> list[dict]:
    rng = random.Random(seed)
    return [{"labse": 0.80 + rng.uniform(-0.04, 0.04),
             "labse_prev": 0.30, "labse_next": 0.30,
             "fwd_pmi": 1.5 + rng.uniform(-0.2, 0.2),
             "rev_pmi": 1.4 + rng.uniform(-0.2, 0.2)} for _ in range(n)]


def test_robust_z_ignores_outliers_when_scaling():
    z = pp.robust_z([1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 1.0, 1.02, 50.0])
    assert z[-1] > 100            # the outlier cannot widen its own yardstick
    assert abs(z[0]) < 2


def test_robust_z_needs_enough_values():
    assert pp.robust_z([1.0, 2.0, 3.0]) == [None, None, None]


def test_clean_book_flags_nothing():
    assert pp.analyse(_items(40), _healthy(40)) == []


def test_unsupported_translation_is_flagged_with_its_span():
    m = _healthy(40)
    m[7].update(fwd_pmi=-2.0, fwd_span="and the king wept")
    found = pp.analyse(_items(40), m)
    assert [f.bead_index for f in found] == [7]
    assert any("and the king wept" in r for r in found[0].reasons)


def test_drift_is_named_as_drift():
    m = _healthy(40)
    m[12].update(labse=0.55, labse_next=0.82)
    found = pp.analyse(_items(40), m)
    assert any("drift" in r for f in found for r in f.reasons if f.bead_index == 12)


def test_two_signals_make_it_high():
    m = _healthy(40)
    m[3].update(labse=0.15, fwd_pmi=-1.0, fwd_span="x")
    f = pp.analyse(_items(40), m)[0]
    assert f.severity == "high" and len(f.reasons) >= 2


def test_short_pairs_are_not_judged_on_similarity():
    items = _items(40)
    items[5].update(src="Amen.", tgt="So be it.")
    m = _healthy(40)
    m[5].update(labse=0.05)
    assert pp.analyse(items, m) == []


def test_length_outlier_is_reported():
    items = _items(40)
    items[9]["tgt"] = "term " * 120
    found = pp.analyse(items, _healthy(40))
    assert [f.bead_index for f in found] == [9]
    assert "length" in found[0].reasons[0]


def test_report_orders_high_first_and_carries_suggestion():
    m = _healthy(40)
    m[2].update(fwd_pmi=0.9, fwd_span="s")
    m[20].update(labse=0.1, rev_pmi=-1.5, rev_span="t", suggestion="A fair reading.")
    found = pp.analyse(_items(40), m)
    text = pp.format_report(found, scanned=40, model="stub")
    assert text.index("[HIGH]") < text.index("[MEDIUM]")
    assert "MODEL READS: A fair reading." in text
    assert "2 of 40" in text


def test_check_chapters_skips_one_sided_beads_and_uses_scorer():
    ch = Chapter(title="I", beads=[
        Bead(src=["a b c d"], tgt=["w x y z"]),
        Bead(src=["only source here"], tgt=[]),
        Bead(src=["e f g h"], tgt=["p q r s"]),
    ])
    seen = {}

    def fake(pairs, opts, log):
        seen["pairs"], seen["opts"] = pairs, opts
        return [{"labse": 0.8} for _ in pairs]

    found, scanned = pp.check_chapters([ch], src_lang="de", tgt_lang="en",
                                       scorer=fake, log=lambda m: None)
    assert scanned == 2 and found == []
    assert seen["opts"]["directions"] == "both"      # German is a Tower language
    found, _ = pp.check_chapters([ch], src_lang="la", tgt_lang="en",
                                 scorer=fake, log=lambda m: None)
    assert seen["opts"]["directions"] == "fwd"       # Latin: forward only


def test_drift_and_weak_match_are_one_signal():
    m = _healthy(40)
    m[12].update(labse=0.70, labse_next=0.82)     # weak AND drifted
    found = pp.analyse(_items(40), m)
    assert len(found) == 1 and found[0].bead_index == 12
    assert len(found[0].reasons) == 1             # one bullet, not two
    assert "drift" in found[0].reasons[0] and "weak match" in found[0].reasons[0]
    assert found[0].severity == "medium"          # one signal, not extreme


def test_a_clean_block_book_flags_nothing():
    assert pp.analyse(_blocks(40), _line_metrics(40)) == []


def test_an_unsupported_line_is_named_by_number_and_text():
    items, m = _blocks(40), _line_metrics(40)
    m[9]["fwd_lines"][2] = -1.2
    found = pp.analyse(items, m)
    assert [f.bead_index for f in found] == [9]
    assert "translation line 3" in found[0].reasons[0]
    assert "verse 2 of the rendering of block 9" in found[0].reasons[0]


def test_an_uncarried_original_line_is_named():
    items, m = _blocks(40), _line_metrics(40)
    m[20]["rev_lines"][0] = -1.0
    found = pp.analyse(items, m)
    assert [f.bead_index for f in found] == [20]
    assert "line 1 of the original has no counterpart" in found[0].reasons[0]


def test_line_scores_do_not_double_report_the_bead_score():
    items, m = _blocks(40), _line_metrics(40)
    m[5]["fwd_lines"][1] = -1.2
    m[5]["fwd_pmi"] = -0.5                        # bead mean is also an outlier
    found = pp.analyse(items, m)
    assert [f.bead_index for f in found] == [5]
    assert not any("says more than the source" in r for r in found[0].reasons)


class _Tok:
    """A character-level stand-in: one token per character."""
    pad_token_id = 0

    def encode(self, text, add_special_tokens=False):
        return [ord(c) for c in text]

    def __call__(self, text, add_special_tokens=False):
        class R:
            input_ids = [ord(c) for c in text]
        return R()

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


def test_seg_ids_gives_each_line_its_span_and_separates_with_newline():
    ids, spans = pp._seg_ids(_Tok(), ["abc", "de", "f"])
    assert spans == [(0, 3), (4, 6), (7, 8)]
    newline = ord("\n")
    assert ids[3] == newline and ids[6] == newline


def test_seg_ids_drops_lines_past_the_cap_and_blank_lines():
    ids, spans = pp._seg_ids(_Tok(), ["abcd", "", "efgh", "ij"], cap=9)
    assert spans[0] == (0, 4) and spans[1] == (0, 0)
    assert spans[2] == (5, 9)                     # exactly fills the cap
    assert spans[3] == (0, 0)                     # would overflow


def test_pmi_from_logprobs_scores_lines_and_finds_the_worst_window():
    tok = _Tok()
    ids, spans = pp._seg_ids(tok, ["aaaa", "bbbb"])
    n = len(ids)
    base = [-3.0] * n
    cond = [-1.0] * n                             # +2.0 PMI everywhere ...
    for k in range(5, 9):                         # ... except line 2
        cond[k] = -3.5
    r = pp._pmi_from_logprobs(tok, ids, spans, cond, base)
    assert abs(r["lines"][0] - 2.0) < 1e-9
    assert r["lines"][1] < 0
    assert r["span"].endswith("bbbb")             # the window reaches the bad line


def test_cap_lines_trims_total_length_and_drops_blanks():
    lines = ["x" * 600, "", "y" * 600, "z" * 600]
    out = pp._cap_lines(lines)
    assert out == ["x" * 600, "y" * 600]
