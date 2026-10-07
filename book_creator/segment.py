"""Segment cleaned text into sentences (prose) or lines (verse), with chapter splitting."""

from __future__ import annotations

import re
from collections import Counter

# Division keywords across the languages we target. "abenteuer"/"aventiure" and
# their English "adventure" are the Middle High German epics' canto word: the
# Nibelungenlied's 39 divisions are Âventiuren, and without them both the German
# ("Erstes Abenteuer.") and the English ("FIRST ADVENTURE: Kriemhild's Dream.")
# collapse into one 595,000-character division with no structure to anchor on.
_DIV_KW = (r"book|chapter|chap|part|canto|section|argument|adventure|chant"
           r"|liber|caput|commentarius|chapitre|livre|partie|kapitel|buch|teil"
           r"|abenteuer|aventiure|gesang")
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
# "BOOK" divisions by word instead of roman numeral throughout). These and the
# German ones run to 39 and beyond, because that is how long the
# medieval epics are: the Nibelungenlied has 39 Âventiuren, numbered by word in
# both Simrock's German ("Neununddreißigstes Abenteuer.") and Needler's English
# ("THIRTY-NINTH ADVENTURE"). Stopping at "twelfth" left the last 27 divisions of
# each side undetected, which collapsed them into one 400,000-character block.
# Composed rather than enumerated, since the compounds are regular.
_EN_UNITS = ("first second third fourth fifth sixth seventh eighth ninth tenth "
             "eleventh twelfth thirteenth fourteenth fifteenth sixteenth "
             "seventeenth eighteenth nineteenth").split()
_EN_TENS = "twentieth thirtieth fortieth fiftieth sixtieth".split()
_EN_TENS_STEM = "twenty thirty forty fifty sixty".split()
_EN_ORD = "|".join(
    # Longest first: "twenty-first" must win over a bare "first".
    [rf"{t}[- ]{u}" for t in _EN_TENS_STEM for u in _EN_UNITS[:9]]
    + _EN_TENS + _EN_UNITS)

# German ordinals decline ("Erstes Abenteuer", "Erste Aventiure", "Zwanzigste
# Abenteuer"), so the stem is matched and the ending left optional below.
# "eilft" is Simrock's archaic spelling of "elft".
_DE_UNITS = ("erst zweit dritt viert fünft fuenft sechst siebent siebt acht "
             "neunt zehnt elft eilft zwölft zwoelft dreizehnt vierzehnt "
             "fünfzehnt fuenfzehnt sechzehnt siebzehnt achtzehnt neunzehnt").split()
_DE_TENS = ("zwanzigst dreißigst dreissigst vierzigst fünfzigst fuenfzigst "
            "sechzigst").split()
_DE_JOIN = "ein zwei drei vier fünf fuenf sechs sieben acht neun".split()
_DE_ORD = "|".join(
    [rf"{u}und{t}" for t in _DE_TENS for u in _DE_JOIN] + _DE_TENS + _DE_UNITS)
# Portuguese, Spanish and Italian ordinals, which the Romance epics number their
# cantos by: "Canto Primeiro" (Os Lusiadas), "Canto Primo" (Gerusalemme
# Liberata). Written out in both genders rather than stemmed, because the
# keyword-first branch below matches an ordinal to a word boundary and a stem
# like "primeir" would not reach the "o" of "Primeiro".
_ROM_ORD = ("primeiro|primeira|primero|primera|primo|prima"
            "|segundo|segunda|secondo|seconda"
            "|terceiro|terceira|tercero|tercera|terzo|terza"
            "|quarto|quarta|cuarto|cuarta"
            "|quinto|quinta|sexto|sexta|sesto|sesta"
            "|sétimo|setimo|séptimo|septimo|settimo|settima"
            "|oitavo|oitava|octavo|octava|ottavo|ottava"
            "|nono|nona|noveno|novena"
            "|décimo|decimo|décima|decima")
_ORDINALS = rf"{_LAT_ORD}|{_FR_ORD}|{_EN_ORD}|{_DE_ORD}|{_ROM_ORD}"

# A "<keyword> <number>" group appearing anywhere in a short heading line. This
# catches "BOOK I", "CHAPTER 3", "Liber II", and "C. IULI ... COMMENTARIUS
# PRIMUS". The keyword and ordinal words are matched case-insensitively, but
# the roman numeral itself must be uppercase: keywords like "part"/"livre" are
# common lowercase French/German words, and a case-insensitive roman class
# would let a lowercase elision like "d'un" (the bare "d") masquerade as a
# chapter number (e.g. "...de la part d'un domestique?").
# Both word orders, because they split along language lines: Romance and Latin
# headings put the number after the keyword ("LIVRE DEUXIÈME", "CAPUT III"),
# while German and the English translations that follow it put the ordinal first
# ("Erstes Abenteuer", "FIRST ADVENTURE"). An ordinal-first heading must be
# ordinal-INITIAL on the line, so prose that merely says "the second part of the
# journey" is not read as a division.
_HEADING_KW_RE = re.compile(
    rf"(?i:\b(?:{_DIV_KW})\b\.?)\s+(?:[IVXLCDM]+|\d+|(?i:{_ORDINALS}))\b"
    rf"|^(?i:(?:{_ORDINALS})\w{{0,3}})\s+(?i:\b(?:{_DIV_KW})\b)"
)
# A line consisting only of a roman numeral, e.g. a bare "IV." chapter marker.
# Bare arabic numbers are intentionally excluded — they're too often footnote
# markers, page numbers, or list items in back matter.
_BARE_NUM_RE = re.compile(r"^[IVXLCDM]{1,7}\.?$")


_NUM_TAIL_RE = re.compile(r"\s{2,}\(?\d{1,4}\)?\.?\s*$")


def _is_heading(line: str) -> bool:
    """Heuristic: is this physical line a structural-division heading?"""
    s = line.strip()
    if not s or len(s) > 140:
        return False
    if _BARE_NUM_RE.match(s):
        return True
    # A column-aligned number at the end of a line is a stanza or line number,
    # not part of a heading -- the same mark segment.stanzas() strips. Taking it
    # off BEFORE matching stops a verse line that happens to end in a division
    # keyword from reading as one: Burton's Lusiads prints
    # "But Mars, for ever wont t'espouse the part      36", where "part" plus
    # that 36 looked exactly like "BOOK 36" and split a canto in half.
    s = _NUM_TAIL_RE.sub("", s).strip()
    if not s:
        return False
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
    # The opening and closing words say where a narration would begin and end
    # better than a title can: "(front matter / untitled)" could be anything.
    return [
        {"index": i + 1, "title": title or "(front matter / untitled)",
         "chars": len(body), "opening": _words(body, 110),
         "closing": _words(body, 120, end=True)}
        for i, (title, body) in enumerate(divisions)
    ]


def _words(text: str, n: int, *, end: bool = False) -> str:
    """About n characters from one end of a text, cut at a word."""
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    if end:
        cut = text[-n:]
        return "…" + cut[cut.find(" ") + 1:] if " " in cut else "…" + cut
    cut = text[:n]
    return (cut[:cut.rfind(" ")] if " " in cut else cut) + "…"


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


def sentence_groups(lines: list[str], max_lines: int = 8) -> list[list[str]]:
    """Group consecutive verse lines into sentences, for translation.

    A translation model is trained on sentences. Handed one hexameter at a
    time it gets half a clause -- the verb in one line, its object in the next
    -- and invents the rest ("The old, new trembling shone"). Verse runs on, so
    the unit that means something is the stretch between full stops.

    A group closes on a line ending in . ? ! ; or the Greek raised dot (a Greek question
    mark is already ;) and never runs past
    `max_lines`: a long period is cut at the cap rather than handed to the
    model whole, which it would summarise.
    """
    groups: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        cur.append(ln)
        if re.search(r"[.?!;··]['\"”’)]*\s*$", ln) or len(cur) >= max_lines:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


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


# A strophe number printed with the verse: at the end of a line, after a wide
# gap (Simrock's Nibelungenlied), or alone on a line between stanzas (Needler's
# English of it). Editions number differently -- Simrock has 2495 strophes to
# Needler's 2379 -- so the numbers are stripped rather than printed: setting
# "288" beside "241" would assert a correspondence that is not there.
# A stanza number alone on a line, in either numbering an edition might use:
# arabic (Needler's Nibelungenlied) or roman (Fairfax's Tasso, where every
# one of the 1,927 stanzas is headed "IX" and the like).
_NUM_LINE_RE = re.compile(r"^[\[(]?(?:\d{1,4}|[IVXLCDM]{1,7})[\])]?\.?$")


def stanzas(text: str, *, drop_numbering: bool = True) -> list[list[str]]:
    """Group verse lines into stanzas, one list of lines each.

    Stanza breaks are found by measuring the text rather than by assuming a
    layout: a Gutenberg verse file may be single-spaced with a blank line
    between stanzas, or double-spaced with three. So the *commonest* gap
    between consecutive lines is taken to be the within-stanza gap, and only a
    wider gap starts a new stanza. Both editions of the Nibelungenlied come out
    right under that rule, and they are spaced differently from each other.

    Returns one stanza when the text has no wider gap to break on -- verse with
    no stanza structure, or a division short enough to hold a single stanza.
    Callers should treat that as "no stanzas here" rather than as one huge one.
    """
    rows: list[tuple[int, str]] = []   # (blank lines before this line, line)
    gap = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip():
            rows.append((gap, line))
            gap = 0
        else:
            gap += 1
    if not rows:
        return []

    gaps = Counter(g for g, _ in rows[1:])
    within = gaps.most_common(1)[0][0] if gaps else 0

    groups: list[list[str]] = [[]]
    for i, (g, line) in enumerate(rows):
        if i and g > within:
            groups.append([])
        if drop_numbering:
            line = _NUM_TAIL_RE.sub("", line)
        groups[-1].append(line.strip())

    # A line that is only a strophe number is a label, not verse. Needler prints
    # them on their own line between stanzas, where the wide gap makes each one
    # its own group -- left in, they would double the stanza count and offset
    # every pairing by one. They are dropped wherever they fall, since an edition
    # that sets them at the same gap as the verse would otherwise print them.
    out: list[list[str]] = []
    for grp in groups:
        lines = [l for l in grp if l]
        if drop_numbering:
            lines = [l for l in lines if not _NUM_LINE_RE.match(l)]
        if lines:
            out.append(lines)
    return out
