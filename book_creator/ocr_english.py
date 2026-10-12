"""Repair OCR slips in English verse without touching real words.

Built for G. H. C. Egestorff's 1826 Messiah, whose page scans are speckled: a
reader sees "thon" for thou, "awfal" for awful, "carth" for earth. The text is
poetry full of names and contractions (tow'rd, glorify'd, Abbadona) that no
dictionary has, so the rule is conservative: a token is only ever changed when
it is not a known word, and only to a word that is.

Two sources of correction, in order of trust:

  1. A second reading. Where another OCR engine's text lines up with this one
     and carries a known word within edit distance two of the unknown token,
     that word wins. Two engines rarely make the same slip.
  2. The spelling list. The nearest known word by an edit distance in which the
     confusions OCR actually makes (u/n, o/a, c/e, h/b, l/i, rn/m) are cheap.
     Frequency breaks ties.

A token fused by a lost space ("donot", "eachother") is split in two when both
halves are known words.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter

# Pairs OCR trades for one another, by shape. Substituting within a pair is
# cheap; any other substitution costs a whole edit.
_CONFUSED = [("u", "n"), ("o", "a"), ("c", "e"), ("h", "b"), ("l", "i"),
             ("t", "l"), ("f", "s"), ("o", "e"), ("a", "e"), ("i", "j"),
             ("v", "y"), ("w", "m"), ("n", "r"), ("c", "o"), ("l", "1"),
             ("i", "t"), ("u", "o"), ("d", "cl"), ("m", "rn"), ("h", "li"),
             ("a", "u"), ("n", "a")]
_CHEAP = {}
for a, b in _CONFUSED:
    _CHEAP[(a, b)] = _CHEAP[(b, a)] = 0.4

_ELISIONS = ("heav'n", "ev'n", "ev'ry", "o'er", "e'er", "ne'er", "e'en",
             "tow'rd", "pow'r", "pow'rs", "flow'r", "flow'rs", "th'", "o'erwhelm'd")

_CAPITALISED = re.compile(r"\b[A-Z][a-z]{3,}\b")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")


def _cost(a: str, b: str, limit: float = 1.6) -> float:
    """Weighted Levenshtein between two lowercase words, or `limit`+ if farther."""
    if abs(len(a) - len(b)) > 2:
        return limit + 1
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        best = cur[0]
        for j, cb in enumerate(b, 1):
            sub = 0.0 if ca == cb else _CHEAP.get((ca, cb), 1.0)
            v = min(prev[j] + 1.0, cur[j - 1] + 1.0, prev[j - 1] + sub)
            cur.append(v)
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


class Lexicon:
    """What counts as a known word."""

    def __init__(self, words: Counter, names: set[str] | None = None):
        self.freq = words
        self.names = {n.lower() for n in (names or set())}
        # The twelve thousand commonest words: the only halves a fused token is
        # allowed to be split into ("do"+"not"), or "tender"+"icy" is a word.
        self.common = {w for w, _ in self.freq.most_common(12000)}
        self._by_len: dict[int, list[str]] = {}
        for w in self.freq:
            self._by_len.setdefault(len(w), []).append(w)
        self._first: dict[tuple[int, str], list[str]] = {}
        for w in self.freq:
            self._first.setdefault((len(w), w[0]), []).append(w)

    def known(self, token: str) -> bool:
        w = token.lower()
        if w in self.freq or w in self.names:
            return True
        # Poetic elision: exclaim'd, glorify'd, pow'r, tow'rd, o'er, th'
        forms = {w.replace("'", "")}
        if w.endswith("'d"):
            forms |= {w[:-2] + "ed", w[:-2] + "d"}
        if w.endswith("'st"):
            forms |= {w[:-3] + "est", w[:-3]}
        if w.endswith("'s"):
            forms.add(w[:-2])
        if "'r" in w:
            forms.add(w.replace("'r", "er"))
        if "'d" in w:
            forms.add(w.replace("'d", "ed"))
        if "'n" in w:
            forms.add(w.replace("'n", "en"))
        if "'ring" in w:
            forms.add(w.replace("'ring", "ering"))
        if w.startswith("th'"):
            return True
        if w in {"o'er", "e'er", "ne'er", "e'en", "ev'n", "heav'n", "tow'rd",
                 "ev'ry", "pow'r", "pow'rs", "flow'r", "flow'rs", "ow'n"}:
            return True
        return any(f in self.freq or f in self.names for f in forms)

    def nearest(self, token: str, limit: float = 1.0) -> tuple[str | None, float]:
        w = token.lower().replace("'", "")
        best, best_cost, best_freq = None, limit + 1, 0
        for ln in range(len(w) - 2, len(w) + 3):
            for cand in self._by_len.get(ln, ()):
                if cand[0] != w[0] and (len(w) < 4 or cand[-1] != w[-1]):
                    continue                    # both ends wrong: not a slip
                c = _cost(w, cand, limit)
                if c > limit:
                    continue
                f = self.freq[cand]
                if c < best_cost or (c == best_cost and f > best_freq):
                    best, best_cost, best_freq = cand, c, f
        return best, best_cost


def _match_case(src: str, new: str) -> str:
    if src.isupper() and len(src) > 1:
        return new.upper()
    if src[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def _split_fused(token: str, lex: Lexicon) -> str | None:
    w = token.lower()
    if len(w) < 6 or "'" in w or token[:1].isupper():
        return None
    best, best_score = None, 0.0
    for i in range(2, len(w) - 1):
        a, b = w[:i], w[i:]
        if a in lex.common and b in lex.common and len(a) > 1 and len(b) > 1:
            if (len(a) < 3 and a not in {"to", "of", "in", "on", "at", "as", "by",
                                         "he", "me", "my", "we", "us", "so", "no",
                                         "or", "if", "it", "is", "be", "do", "go",
                                         "up", "an", "am", "oh", "ye"}):
                continue
            score = min(lex.freq[a], lex.freq[b])
            if score > best_score:
                best, best_score = f"{a} {b}", score
    return _match_case(token, best) if best else None


def vote_sources(lines: list[str], other: list[str]) -> dict[int, dict[str, str]]:
    """For each line index, a map from this engine's word to the other's word at
    the same place, where the two texts line up one token for one."""
    toks, where = [], []
    for li, line in enumerate(lines):
        for m in _WORD.finditer(line):
            toks.append(m.group(0).lower())
            where.append((li, m.group(0)))
    otoks = [m.group(0).lower() for line in other for m in _WORD.finditer(line)]
    sm = difflib.SequenceMatcher(None, toks, otoks, autojunk=False)
    out: dict[int, dict[str, str]] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                li, orig = where[i1 + k]
                out.setdefault(li, {})[orig] = otoks[j1 + k]
    return out


class LMScorer:
    """Log-likelihood of a line of verse under a small causal language model.

    Used to choose between candidate repairs *in context*: "dumay" is "dismay"
    after "with sadness and" and nothing a spelling list could say about the
    letters alone.
    """

    def __init__(self, model: str = "Qwen/Qwen2.5-0.5B", device: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(model)
        self.model = AutoModelForCausalLM.from_pretrained(
            model, torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
        ).to(self.device).eval()

    def score(self, context: str, variants: list[str]) -> list[float]:
        torch = self.torch
        pre = self.tok(context + chr(10), return_tensors="pt").input_ids[0] if context else None
        outs = []
        for v in variants:
            ids = self.tok(v, return_tensors="pt").input_ids[0]
            full = torch.cat([pre, ids]) if pre is not None else ids
            with torch.no_grad():
                logits = self.model(full.unsqueeze(0).to(self.device)).logits[0].float()
            lp = torch.log_softmax(logits[:-1], -1)
            tgt = full[1:].to(self.device)
            tok_lp = lp.gather(1, tgt.unsqueeze(1)).squeeze(1)
            n = len(ids) if pre is None else len(ids)
            outs.append(float(tok_lp[-n:].sum()) if pre is not None else float(tok_lp.sum()))
        return outs


def _archaic(token: str, lex: Lexicon) -> bool:
    """A spelling of its day, not a slip: tremour, honour, controul."""
    w = token.lower()
    return any(old in w and w.replace(old, new) in lex.freq
               for old, new in (("our", "or"), ("ou", "o"), ("ick", "ic"),
                                ("ize", "ise"), ("ise", "ize")))


def candidates(tok: str, lex: Lexicon, votes: list[str], max_near: int = 6) -> list[str]:
    seen, out = set(), []

    def add(c: str) -> None:
        if c and c not in seen:
            seen.add(c)
            out.append(c)

    for v in votes:
        if v != tok.lower() and lex.known(v):
            add(_match_case(tok, v))
    sp = _split_fused(tok, lex)
    if sp:
        add(sp)
    lw = tok.lower()
    # Egestorff elides ("view'd", "heav'n"); the scan often loses the mark.
    if lw.endswith("d") and "'" not in lw and len(lw) > 3:
        if lw[:-1] + "'d" and lex.known(lw[:-1] + "'d") or lw[:-1] in lex.freq:
            add(_match_case(tok, lw[:-1] + "'d"))
    for el in _ELISIONS:
        if abs(len(el) - len(lw)) <= 1 and _cost(lw, el, 1.0) <= 1.0:
            add(_match_case(tok, el))
    if len(tok) >= 4:
        limit = 0.5 if tok[0].isupper() else 1.0
        scored = []
        w = tok.lower().replace("'", "")
        for ln in range(len(w) - 2, len(w) + 3):
            for cand in lex._by_len.get(ln, ()):
                if cand[0] != w[0] and cand[-1] != w[-1]:
                    continue
                c = _cost(w, cand, limit)
                if c <= limit:
                    scored.append((c, -lex.freq[cand], cand))
        scored.sort()
        for _, _, cand in scored[:max_near]:
            add(_match_case(tok, cand))
    return out


def correct(lines: list[str], lex: Lexicon, helpers: list[list[str]] | None = None,
            log: list | None = None, scorer: "LMScorer | None" = None,
            margin: float = 3.0) -> list[str]:
    """Return `lines` with unknown words repaired where a repair is sure enough.

    Without a scorer only another engine's reading is trusted. With one, every
    candidate is tried in the line and kept only if it beats the original token
    by `margin` nats.
    """
    votes = [vote_sources(lines, h) for h in (helpers or [])]
    out: list[str] = []
    for li, line in enumerate(lines):
        if line.startswith("["):
            out.append(line)         # an editorial marker, not verse
            continue
        cur = line
        pos = 0
        while True:
            m = None
            for mm in _WORD.finditer(cur, pos):
                tok = mm.group(0)
                if len(tok) >= 2 and not lex.known(tok) and not _archaic(tok, lex):
                    m = mm
                    break
            if m is None:
                break
            tok = m.group(0)
            vs = [v.get(li, {}).get(tok) for v in votes]
            cands = candidates(tok, lex, [x for x in vs if x])
            best = None
            if cands:
                if scorer is None:
                    vote_c = [c for c in cands if c.lower() in [x for x in vs if x]]
                    best = vote_c[0] if vote_c else None
                else:
                    variants = [cur] + [cur[:m.start()] + c + cur[m.end():] for c in cands]
                    ctx = out[-1] if out else ""
                    sc = scorer.score(ctx, variants)
                    j = max(range(1, len(sc)), key=lambda k: sc[k])
                    if sc[j] - sc[0] >= margin:
                        best = cands[j - 1]
            if best is not None:
                if log is not None:
                    log.append((tok, best, f"{li}"))
                cur = cur[:m.start()] + best + cur[m.end():]
                pos = m.start() + len(best)
            else:
                pos = m.end()
        out.append(cur)
    return out


def default_lexicon(corpus_texts: list[str], names_from: str = "",
                    german: str = "", english_all: str = "") -> Lexicon:
    """A spelling list (pyspellchecker's, when installed) plus every word that
    occurs three times in the given clean English texts, plus the capitalised
    words (names) that occur three times in `names_from`."""
    freq: Counter = Counter()
    try:
        from spellchecker import SpellChecker
        for w, c in SpellChecker().word_frequency.dictionary.items():
            if w.isalpha():
                freq[w] = c
    except ImportError:
        pass
    for text in corpus_texts:
        for w, c in Counter(re.findall(r"[a-z]+", text.lower())).items():
            if c >= 3:
                freq[w] += c
    names = {w for w, c in Counter(re.findall(r"\b[A-Z][a-z]{3,}\b", names_from)).items()
             if c >= 3}
    if german and english_all:
        # A capitalised word both texts use three times is a name, however the
        # scan has spelled it in places: Golgatha, Gethsemane, Abbadona.
        g = Counter(_CAPITALISED.findall(german))
        e = Counter(_CAPITALISED.findall(english_all))
        names |= {w for w in e if e[w] >= 3 and g.get(w, 0) >= 3}
    return Lexicon(freq, names)
