"""Repair OCR of early printed Latin against a reference vocabulary.

A historical-print model (GT4HistOCR) reads a 1513 page far better than stock
`lat`, but its mistakes are different in kind as well as degree. Where stock
Tesseract produced unrecoverable noise -- "y» Extrematng; omnes peull liíüc
depellice pete," -- the historical model produces words that are nearly right:
"proeul" for *procul*, "angica" for *anglica*, "fara" for *fata*. One character
out, in a word otherwise correct.

That is what this fixes, and it is only safe because of how narrow it is. Each
unknown token is matched against the corpus vocabulary at an edit distance of
one (two, for a long word), and a correction is accepted ONLY when exactly one
vocabulary word is that close. A token with several equally near neighbours is
left alone and counted, because choosing between them would be guessing -- and
guessing is precisely what makes a vision model's output untrustworthy
(it offered "defendite armis" for *defendite ab oris*, inventing a word that is
not on the page). A wrong word a reader can spot beats a plausible word they
cannot.

The vocabulary is the `latin` repo's corpus, exported to cache/latin_vocab.tsv
by way of ingest.ocr_fix.build_reference_vocab -- 392,757 forms with frequency,
so a tie can be broken by how common a word actually is in real Latin.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

VOCAB_PATH = "cache/latin_vocab.tsv"

# Early printers' abbreviations, expanded the way an editor would. Only the
# unambiguous ones: a nasal bar over a vowel can stand for m or n and needs the
# word to decide, so it is left to the vocabulary match rather than guessed at.
ABBREVIATIONS = {
    "ſ": "s", "ẜ": "s", "ꝓ": "pro", "ꝑ": "per", "ꝗ": "qui",
    "⁊": "et", "ꝛ": "r", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe",
}
_QUE = re.compile(r"q;|q₃")
_WORD = re.compile(r"[A-Za-z]+")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


@dataclass
class Repair:
    """The corrected text, and an honest account of what was left undone."""

    text: str
    corrected: dict[str, str] = field(default_factory=dict)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (f"{len(self.corrected)} corrected, {len(self.ambiguous)} left "
                f"ambiguous, {len(self.unknown)} unknown")


def expand_abbreviations(text: str) -> str:
    """Resolve printers' shorthand and drop marks that are ink, not orthography.

    Classical Latin has no acute accents, so every one a scanner reports is the
    typeface or the ink bleeding -- "patríís" is *patriis*. Folding them is
    safe here in a way it would not be for, say, French.
    """
    for glyph, plain in ABBREVIATIONS.items():
        text = text.replace(glyph, plain)
    text = _QUE.sub("que", text)
    folded = unicodedata.normalize("NFD", text)
    return "".join(c for c in folded if unicodedata.category(c) != "Mn")


def fold(word: str) -> str:
    """The key a word is looked up under, with u/v and i/j treated as one.

    Early print and the corpus disagree about these: a 1513 page sets "vestris"
    where the corpus has "uestris", and both are the same word. Without folding,
    every correctly-read v on the page was "corrected" into a u -- the pass
    rewriting right answers into a different editorial convention.
    """
    return word.lower().replace("v", "u").replace("j", "i")


def load_vocab(path: str | Path = VOCAB_PATH) -> dict[str, int]:
    """Word -> frequency, from the latin repo's corpus."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"No Latin vocabulary at {p}. Export one from the latin repo:\n"
            "  from core.store import Store\n"
            "  from ingest.ocr_fix import build_reference_vocab\n"
            "  build_reference_vocab(Store('data/corpus.db'))")
    vocab: dict[str, int] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        word, _, count = line.partition("\t")
        if word:
            vocab[word] = int(count or 1)
    return vocab


def _edits1(word: str) -> set[str]:
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    return {
        *(a + b[1:] for a, b in splits if b),                              # delete
        *(a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1),       # transpose
        *(a + c + b[1:] for a, b in splits if b for c in _ALPHABET),       # replace
        *(a + c + b for a, b in splits for c in _ALPHABET),                # insert
    }


def _candidates(word: str, vocab: dict[str, int], distance: int) -> list[str]:
    near = {w for w in _edits1(word) if w in vocab}
    if not near and distance > 1:
        near = {w2 for w1 in _edits1(word) for w2 in _edits1(w1) if w2 in vocab}
    return sorted(near, key=lambda w: -vocab[w])


def correct(text: str, vocab: dict[str, int] | None = None, *,
            min_length: int = 4, far_length: int = 8,
            frequency_margin: int = 20) -> Repair:
    """Correct what the vocabulary can vouch for, and report what it cannot.

    `min_length` keeps the pass off short words, where an edit of one reaches
    half the dictionary and "a" could become anything. `far_length` is where a
    word is long enough that two edits are still a safe bet. `frequency_margin`
    settles a tie only when one candidate is overwhelmingly commoner than the
    rest -- otherwise the token is recorded as ambiguous and left as it is.
    """
    vocab = load_vocab() if vocab is None else vocab
    # Looked up folded, so the page's own u/v convention is never "corrected".
    folded: dict[str, int] = {}
    for w, n in vocab.items():
        k = fold(w)
        folded[k] = folded.get(k, 0) + n
    result = Repair(text="")
    seen: dict[str, str | None] = {}

    def fix(match: re.Match) -> str:
        word = match.group(0)
        lower = fold(word)
        if lower in folded or len(lower) < min_length:
            return word
        if lower not in seen:
            cands = _candidates(lower, folded, 2 if len(lower) >= far_length else 1)
            # A candidate much shorter than the token is not a correction but a
            # deletion: "Atsaltem" is *At saltem* run together, and answering
            # "saltem" throws a word away. Those are left for a human.
            cands = [c for c in cands if len(c) >= len(lower) - 1]
            if not cands:
                result.unknown.append(word)
                seen[lower] = None
            elif len(cands) == 1 or folded[cands[0]] >= frequency_margin * folded[cands[1]]:
                seen[lower] = cands[0]
                result.corrected[word] = cands[0]
            else:
                result.ambiguous[word] = cands[:4]
                seen[lower] = None
        best = seen[lower]
        if best is None:
            return word
        # Keep the case the page actually printed.
        return best.capitalize() if word[:1].isupper() else best

    result.text = _WORD.sub(fix, text)
    return result


def repair(text: str, vocab: dict[str, int] | None = None, **kwargs) -> Repair:
    """Expand the abbreviations, then correct against the vocabulary."""
    return correct(expand_abbreviations(text), vocab, **kwargs)
