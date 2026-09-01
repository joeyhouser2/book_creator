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


def _is_isolated_title(line: str, prev_gap: int, next_gap: int) -> bool:
    """Verse-mode extra heuristic: a standalone poem's title, printed on its
    own line with no numeral. Buch der Lieder's poems are already caught by
    the bare-numeral heading above, because that collection numbers every
    poem in one continuous I..CCXXVII run. Other collections (e.g. Les Fleurs
    du Mal) only number *multi-part* poem cycles that way, restarting at I
    each time, and otherwise give each standalone poem just a short title
    line — no numeral at all — so the numeral-only check above misses most of
    them and lets a handful of poems collapse into one undivided blob.

    A single flanking blank line is NOT a safe signal by itself — some
    Gutenberg editions (Heine's included) double-space every verse line, so
    "blank on both sides" would match nearly every line in the poem. The
    actual signal is a *bigger* gap: within a poem, lines within a stanza sit
    one blank line apart at most, while a real break (between stanzas, or
    around a title) runs two or more blank lines. Requiring 2+ on both sides
    catches titles without firing on ordinary verse. A trailing comma or
    semicolon is excluded too — a title doesn't trail off mid-clause.
    """
    s = line.strip()
    if not s or len(s) > 60 or len(s.split()) > 6:
        return False
    if s[-1] in ",;":
        return False
    return prev_gap >= 2 and next_gap >= 2

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


def detect_chapters(text: str, mode: str = "prose", poem_titles: bool = False) -> list[tuple[str, str]]:
    """Split text on chapter headings. Returns [(title, body), ...].

    If no headings are found, returns a single ("", whole_text) chapter.
    `poem_titles` (verse mode only) also splits on an isolated untitled-poem
    title line (see _is_isolated_title) — opt-in, since it helps collections
    that title standalone poems by name (Les Fleurs du Mal) but adds nothing
    for ones already numbered continuously (Buch der Lieder) besides risk.
    """
    lines = text.splitlines()

    def blank_run(start: int, step: int) -> int:
        """Count consecutive blank lines starting at `start`, walking by `step`."""
        n = 0
        i = start
        while 0 <= i < len(lines) and not lines[i].strip():
            n += 1
            i += step
        return n

    chapters: list[tuple[str, list[str]]] = []
    current_title = ""
    current_body: list[str] = []

    for i, line in enumerate(lines):
        is_head = _is_heading(line)
        if not is_head and mode == "verse" and poem_titles:
            is_head = _is_isolated_title(line, blank_run(i - 1, -1), blank_run(i + 1, 1))
        if is_head:
            # Only flush/start a new division if there's real content since the
            # last one — otherwise a numeral heading immediately followed by
            # its own title line (e.g. "I" then "LES TÉNÈBRES") would spawn a
            # spurious empty division between them.
            if any(b.strip() for b in current_body):
                chapters.append((current_title, current_body))
            current_title = line.strip()
            current_body = []
        else:
            current_body.append(line)
    if any(b.strip() for b in current_body):
        chapters.append((current_title, current_body))

    if not chapters:
        return [("", text)]
    return [(title, "\n".join(body).strip()) for title, body in chapters]


def outline(text: str, mode: str = "prose", poem_titles: bool = False) -> list[dict]:
    """Structural divisions of a text, for UI display and range selection.

    Returns [{index, title, chars}], index 1-based. Index 1 is usually the
    front matter (text before the first heading).
    """
    return outline_of(detect_chapters(text, mode=mode, poem_titles=poem_titles))


def outline_of(divisions: list[tuple[str, str]]) -> list[dict]:
    """The same shape, for divisions a caller has already loaded.

    Split out so a source that carries its own structure -- an EPUB's spine and
    headings -- can be listed in the range picker without being flattened back
    to text and re-detected, which is what reduced a whole novel to one row.
    """
    return [
        {"index": i + 1, "title": title or "(front matter / untitled)",
         "chars": len(body)}
        for i, (title, body) in enumerate(divisions)
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


def subdivide(divisions: list[tuple[str, str]], max_chars: int,
              log=None) -> list[tuple[str, str]]:
    """Break divisions longer than `max_chars` into parts at paragraph breaks.

    Some books have no internal marks to split on. Pale Fire's Commentary runs
    to 190,000 characters without a heading; a continuous scholarly text can be
    the whole book. Printed, that is one very long chapter; narrated, it is a
    single chapter marker four hours wide, which makes an audiobook impossible
    to navigate or to resume.

    Splits only ever fall on a blank line, so a part never begins mid-sentence.
    A paragraph longer than the limit on its own is left whole rather than cut:
    an oversized part is a much smaller problem than a severed sentence.

    Off unless asked for (`max_chars` of 0 returns the input untouched): for a
    printed book these parts are invented structure, not the author's, and
    that is the caller's decision to make.
    """
    if not max_chars or max_chars <= 0:
        return divisions

    out: list[tuple[str, str]] = []
    untitled = 0
    split_count = 0
    for title, body in divisions:
        if len(body) <= max_chars:
            out.append((title, body))
            continue

        paras = re.split(r"\n\s*\n", body)
        parts: list[str] = []
        buf = ""
        for para in paras:
            if buf and len(buf) + len(para) + 2 > max_chars:
                parts.append(buf)
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            parts.append(buf)

        split_count += 1
        for i, part in enumerate(parts, start=1):
            if title:
                out.append((f"{title} ({i} of {len(parts)})", part))
            else:
                untitled += 1
                out.append((f"Part {untitled}", part))

    if log and split_count:
        log(f"• Split {split_count} long division(s) into parts of at most "
            f"{max_chars:,} characters — {len(divisions)} division(s) became "
            f"{len(out)}.")
    return out
