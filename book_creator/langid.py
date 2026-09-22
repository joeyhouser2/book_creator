"""Guess what language a text is in, from its commonest words.

The app began as a Latin tool, so its language box starts at Latin. Nothing
read the text to see whether that was true, and an English history of
Marlborough went to the narrator as Latin -- which has no voice of its own,
so twenty-one hours of English prose were about to be read with an Italian
one. A book's own words say what it is: no language of these gets far
without "the", "et", "der", "di" or "que".

Deliberately small and dependency-free. It is used to set a box the person
can still change, not to decide anything behind their back.
"""

from __future__ import annotations

import re
from collections import Counter

# The commonest words of each language this app can set, chosen to overlap as
# little as possible. Latin and Italian share "in" and "non"; Greek is written
# in its own alphabet and needs no word list at all.
_WORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "in", "that", "was", "he", "it", "his",
           "with", "for", "as", "had", "which", "but", "not", "they", "were"},
    "fr": {"le", "la", "les", "des", "du", "et", "que", "qui", "dans", "pour",
           "est", "une", "sur", "pas", "par", "plus", "avec", "ils", "leur"},
    "de": {"der", "die", "das", "und", "den", "von", "zu", "mit", "sich",
           "des", "auf", "für", "ist", "nicht", "ein", "eine", "als", "auch"},
    "it": {"il", "la", "che", "di", "del", "della", "per", "una", "con",
           "sono", "come", "alla", "dei", "nel", "gli", "anche", "più"},
    "es": {"el", "la", "los", "las", "de", "que", "por", "con", "una", "del",
           "para", "como", "pero", "sus", "este", "muy", "son", "fue"},
    "la": {"et", "in", "est", "non", "cum", "ad", "quod", "qui", "sed", "ut",
           "ex", "per", "atque", "esse", "enim", "autem", "sunt", "quae"},
    "nl": {"de", "het", "een", "van", "en", "dat", "die", "in", "te", "voor",
           "met", "zijn", "niet", "aan", "ook", "maar", "door"},
    "pt": {"de", "que", "do", "da", "em", "para", "com", "uma", "por", "dos",
           "como", "mas", "foi", "seu", "sua", "ele", "pelo"},
}
# Ancient and modern Greek are told apart by their accents: polytonic Greek
# uses breathings and the circumflex, monotonic Greek only the acute.
_GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
_POLYTONIC = re.compile(r"[ἀ-῿]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def guess(text: str, *, least: float = 0.06, margin: float = 1.3) -> str | None:
    """The language code, or None when the text does not say clearly enough.

    `least` is the share of words that must be among a language's commonest
    for it to count at all, and `margin` how far ahead of the runner-up it
    has to be. Both are deliberately cautious: leaving the box alone is
    better than setting it wrongly.
    """
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 40:
        return None
    greek = len(_GREEK.findall(text))
    if greek > 0.2 * sum(len(w) for w in words):
        return "grc" if len(_POLYTONIC.findall(text)) > 0.02 * greek else "el"
    counts = Counter(words)
    total = len(words)
    scores = {lang: sum(counts[w] for w in vocab) / total
              for lang, vocab in _WORDS.items()}
    best, second = sorted(scores.items(), key=lambda kv: -kv[1])[:2]
    if best[1] < least or best[1] < margin * second[1]:
        return None
    return best[0]


LANGUAGES = {"en": "English", "fr": "French", "de": "German", "it": "Italian",
             "es": "Spanish", "la": "Latin", "nl": "Dutch", "pt": "Portuguese",
             "grc": "Ancient Greek", "el": "Greek"}


def name(code: str) -> str:
    return LANGUAGES.get(code, code)
