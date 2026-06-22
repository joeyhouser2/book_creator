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

    # Collapse hard-wrapped lines within a paragraph into single spaces, keeping
    # paragraph breaks (handles double-spaced sources too).
    paragraphs = _paragraphs(text)
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


def _paragraphs(text: str) -> list[str]:
    """Split text into paragraphs, joining hard-wrapped lines.

    Handles both normally-spaced text (paragraphs separated by a blank line) and
    double-spaced sources (a blank line after *every* wrapped line, common in
    older Gutenberg files). For double-spaced text a single blank line is a wrap,
    not a paragraph break — otherwise sentences shatter at line boundaries.
    """
    lines = text.split("\n")

    # Measure blank-line runs between content lines to detect double-spacing.
    runs: list[int] = []
    run = 0
    seen = False
    for line in lines:
        if line.strip() == "":
            if seen:
                run += 1
        else:
            if seen and run:
                runs.append(run)
            run = 0
            seen = True
    double_spaced = bool(runs) and runs.count(1) > len(runs) / 2
    threshold = 2 if double_spaced else 1

    paragraphs: list[str] = []
    buffer: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip() == "":
            blanks += 1
            continue
        if buffer and blanks >= threshold:
            paragraphs.append(" ".join(buffer))
            buffer = []
        buffer.append(line.strip())
        blanks = 0
    if buffer:
        paragraphs.append(" ".join(buffer))
    return paragraphs


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
