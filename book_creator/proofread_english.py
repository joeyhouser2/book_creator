"""Proofread English OCR where two readings of the same page disagree.

`ocr_english.correct` repairs words that are not words. What it cannot see is
a real word standing where another real word belongs: the first line of the
Messiah reads "Sly Soul" because the scan's M was taken for an S and "Sly" is
English. A dictionary has no opinion. Two OCR engines reading the same page
often do: where they disagree and both readings are words, a language model
that reads the line chooses.

For every token at which a second (or third) reading differs from the text we
hold, both being known words, the line is scored with each reading in place and
the best is kept. A switch needs the model to prefer it by `margin` nats, so a
coin-flip stays as it was; those near misses are written out for a person.
"""

from __future__ import annotations

import re
from collections import Counter

from . import ocr_english as oe


def _variants(token: str, readings: list[str], lex: oe.Lexicon) -> list[str]:
    """The distinct, known readings of one place, the held one first."""
    out, seen = [token], {token.lower()}
    for r in readings:
        if not r or r.lower() in seen or len(r) < 2 or not lex.known(r):
            continue
        # A reading that is merely a spelling-list entry ("Lhe", "TH") is not a
        # word anyone meant: it must be a common word, or a name.
        if r.lower() not in lex.common and r.lower() not in lex.names:
            continue
        # Egestorff elides ("E'en", "glorify'd"); another engine dropping the
        # mark does not make his spelling wrong.
        if r.replace("'", "").lower() == token.replace("'", "").lower():
            continue
        seen.add(r.lower())
        out.append(oe._match_case(token, r))
    return out


def proofread(lines: list[str], lex: oe.Lexicon, helpers: list[list[str]],
              scorer: "oe.LMScorer", margin: float = 2.5,
              changes: list | None = None, unsure: list | None = None) -> list[str]:
    """Return `lines`, with a word swapped for another engine's reading where
    the language model clearly prefers it in context."""
    votes = [oe.vote_sources(lines, h) for h in helpers]
    out: list[str] = []
    for li, line in enumerate(lines):
        if line.startswith("["):
            out.append(line)                     # an editorial marker
            continue
        cur = line
        for m in list(oe._WORD.finditer(line)):
            tok = m.group(0)
            if (len(tok) < 2 or "'" in tok or tok.lower() in lex.names
                    or not lex.known(tok)):
                continue                         # unknown words are `correct`'s job
            readings = [v.get(li, {}).get(tok) for v in votes]
            opts = _variants(tok, [r for r in readings if r], lex)
            if len(opts) < 2:
                continue
            # The same token, wherever it now sits in the (possibly edited) line.
            at = cur.find(tok)
            if at < 0:
                continue
            texts = [cur[:at] + o + cur[at + len(tok):] for o in opts]
            ctx = out[-1] if out and not out[-1].startswith("[") else ""
            sc = scorer.score(ctx, texts)
            best = max(range(len(sc)), key=lambda k: sc[k])
            gain = sc[best] - sc[0]
            if best != 0 and gain >= margin:
                cur = texts[best]
                if changes is not None:
                    changes.append((li, tok, opts[best], round(gain, 1)))
            elif best != 0 and unsure is not None and gain >= 0.5:
                unsure.append((li, tok, opts[best], round(gain, 1)))
        out.append(cur)
    return out
