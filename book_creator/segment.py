"""Segment cleaned text into sentences (prose) or lines (verse), with chapter splitting."""

from __future__ import annotations

import re

# Headings that mark a structural division, in the languages we target.
_CHAPTER_RE = re.compile(
    r"""^\s*(
        (chapter|book|canto|part|section|liber|caput|chapitre|livre|kapitel|buch|teil)
        \s+([ivxlcdm\d]+|[a-zÀ-ſ]+)
        | [IVXLCDM]+\.?            # bare roman numeral line
        | \d+\.?                   # bare arabic numeral line
    )\s*$""",
    re.I | re.X,
)

# Sentence terminators by language. Greek uses ';' as its question mark and
# '·' (ano teleia) as a colon (NOT a sentence end).
_TERMINATORS = {
    "grc": ".;!",   # . ; !
    "el": ".;!",
    "default": ".!?…",
}

# Lightweight abbreviation guard so "Mr." / "St." / "cf." don't split.
_ABBREV = {
    "mr", "mrs", "ms", "dr", "st", "vs", "etc", "cf", "ca", "no", "vol",
    "p", "pp", "fig", "e.g", "i.e", "viz", "al", "jr", "sr",
}


def detect_chapters(text: str) -> list[tuple[str, str]]:
    """Split text on chapter headings. Returns [(title, body), ...].

    If no headings are found, returns a single ("", whole_text) chapter.
    """
    lines = text.splitlines()
    chapters: list[tuple[str, list[str]]] = []
    current_title = ""
    current_body: list[str] = []

    for line in lines:
        if _CHAPTER_RE.match(line) and len(line.strip()) <= 40:
            if current_body:
                chapters.append((current_title, current_body))
            current_title = line.strip()
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        chapters.append((current_title, current_body))

    if not chapters:
        return [("", text)]
    return [(title, "\n".join(body).strip()) for title, body in chapters]


def segment_prose(text: str, lang: str = "default") -> list[str]:
    """Split prose into sentences. Paragraph breaks are treated as hard boundaries."""
    terminators = _TERMINATORS.get(lang, _TERMINATORS["default"])
    term_class = re.escape(terminators)

    # Collapse hard-wrapped lines within a paragraph into single spaces, but keep
    # blank-line paragraph breaks.
    paragraphs = re.split(r"\n\s*\n", text)
    sentences: list[str] = []
    splitter = re.compile(rf"(?<=[{term_class}])\s+")

    for para in paragraphs:
        flat = re.sub(r"\s+", " ", para).strip()
        if not flat:
            continue
        pieces = splitter.split(flat)
        merged: list[str] = []
        for piece in pieces:
            if merged and _is_abbrev_tail(merged[-1]):
                merged[-1] = merged[-1] + " " + piece
            else:
                merged.append(piece)
        sentences.extend(s.strip() for s in merged if s.strip())
    return sentences


def _is_abbrev_tail(sentence: str) -> bool:
    last = sentence.split()[-1] if sentence.split() else ""
    last = last.rstrip(".").lower()
    return last in _ABBREV


def segment_verse(text: str) -> list[str]:
    """One segment per non-empty line, preserving verse structure."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def segment(text: str, mode: str, lang: str = "default") -> list[str]:
    if mode == "verse":
        return segment_verse(text)
    return segment_prose(text, lang)
