"""Segment cleaned text into sentences (prose) or lines (verse), with chapter splitting."""

from __future__ import annotations

import re

# Division keywords across the languages we target.
_DIV_KW = (r"book|chapter|chap|part|canto|section|argument"
           r"|liber|caput|commentarius|chapitre|livre|partie|kapitel|buch|teil")
_ROMAN = r"[ivxlcdm]+"
# Latin ordinals (used in headings like "COMMENTARIUS PRIMUS").
_LAT_ORD = (r"primus|secundus|tertius|quartus|quintus|sextus|septimus"
            r"|octavus|nonus|decimus|undecimus|duodecimus")
# French ordinals (used in headings like "CHAPITRE PREMIER", "LIVRE DEUXIÈME"
# — French names divisions 1-11 by word, then (for chapters) switches to roman
# numerals from II onward; multi-book works like Notre-Dame de Paris keep
# naming "LIVRE" divisions by ordinal word throughout).
_FR_ORD = (r"première|premier|deuxième|troisième|quatrième"
           r"|cinquième|sixième|septième|huitième"
           r"|neuvième|dixième|onzième|douzième")
# English ordinals (used in headings like "BOOK SEVENTH" — some editions name
# "BOOK" divisions by word instead of roman numeral throughout).
_EN_ORD = (r"first|second|third|fourth|fifth|sixth|seventh|eighth"
           r"|ninth|tenth|eleventh|twelfth")

# A "<keyword> <number>" group appearing anywhere in a short heading line. This
# catches "BOOK I", "CHAPTER 3", "Liber II", and "C. IULI ... COMMENTARIUS
# PRIMUS". The keyword and ordinal words are matched case-insensitively, but
# the roman numeral itself must be uppercase: keywords like "part"/"livre" are
# common lowercase French/German words, and a case-insensitive roman class
# would let a lowercase elision like "d'un" (the bare "d") masquerade as a
# chapter number (e.g. "...de la part d'un domestique?").
_HEADING_KW_RE = re.compile(
    rf"(?i:\b(?:{_DIV_KW})\b\.?)\s+(?:[IVXLCDM]+|\d+|(?i:{_LAT_ORD}|{_FR_ORD}|{_EN_ORD}))\b"
)
# A line consisting only of a roman numeral, e.g. a bare "IV." chapter marker.
# Bare arabic numbers are intentionally excluded — they're too often footnote
# markers, page numbers, or list items in back matter.
_BARE_NUM_RE = re.compile(r"^[IVXLCDM]{1,7}\.?$")


def _is_heading(line: str) -> bool:
    """Heuristic: is this physical line a structural-division heading?"""
    s = line.strip()
    if not s or len(s) > 140:
        return False
    if _BARE_NUM_RE.match(s):
        return True
    # A keyword+number heading, but only on a short-ish title-like line (so a
    # prose sentence that merely mentions "book i" isn't treated as a
    # heading). Generous enough for descriptive chapter titles printed inline
    # ("CHAPTER IV. THE INCONVENIENCES OF FOLLOWING A PRETTY WOMAN...") —
    # the keyword+numeral must still be immediately adjacent, which already
    # rules out most incidental prose mentions.
    return bool(_HEADING_KW_RE.search(s)) and len(s.split()) <= 20

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
        if _is_heading(line):
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


def outline(text: str) -> list[dict]:
    """Structural divisions of a text, for UI display and range selection.

    Returns [{index, title, chars}], index 1-based. Index 1 is usually the
    front matter (text before the first heading).
    """
    divs = detect_chapters(text)
    return [
        {"index": i + 1, "title": title or "(front matter / untitled)", "chars": len(body)}
        for i, (title, body) in enumerate(divs)
    ]


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
