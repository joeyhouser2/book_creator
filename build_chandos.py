#!/usr/bin/env python
"""Build the dual-language Chandos Herald from the Pope & Lodge edition PDF.

`input/Chandos Herald - la vie du prince noir.pdf` is a scan of *Life of the
Black Prince by the Herald of Sir John Chandos* (Pope & Lodge, Oxford 1910):
Anglo-Norman verse, the editors' English prose translation, and a great deal
of apparatus. Only two of those belong in a reading edition, and they are not
laid out as facing pages, so this does not go through pipeline.build_book().

What the source actually looks like, page by page:

    12- 67   introduction, in English                    -- dropped
    70-202   the poem, in TWO columns: the manuscript
             transcription (left, abbreviated: "ffiltz
             monf Robt Dartois") and the editors'
             normalised text (right: "ffilz monseignour
             Robert d'Artois"), with the line number
             every fifth line
   204-239   the editors' English prose translation,
             carrying the poem's line numbers in the
             margin -- but only every 40-50 lines
   240-325   critical notes, historical notes, glossary,
             index, all in English                       -- dropped

So the two sides are joined on the line numbers both of them print. The poem
gives one every five lines and the translation one every forty-odd, which
fixes the pairing to within a block. Inside each block a local language model
(qwen3:14b, through Ollama) reads the verse and the English and says where
each sentence's passage begins: on a block checked by hand against the page it
put all eight passages within two lines of the truth, five exactly. Without
Ollama the build falls back to matching by embeddings and shared names, which
only gets the stanza right.

The manuscript transcription is what gets printed opposite the English, and
the normalised text is what the pairing reads -- it is the text the
translation was made from, and the one OCR reads accurately.

What the scan itself cannot supply is listed, page by page, in
`<slug>-proofread.md`: the handful of lines missing from the scan entirely,
and the manuscript lines that still look misread, each beside the editors'
normalised reading. A diplomatic transcription can only be finished by reading
it against the page; the build fixes everything the page's own structure can
prove and lists the rest rather than guessing.

    python build_chandos.py --inspect     # extraction report, writes nothing
    python build_chandos.py               # build the book (needs Ollama for
                                          # the best pairing; ~2h first time,
                                          # minutes after, answers are cached)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent))

SRC_PDF = Path("input/Chandos Herald - la vie du prince noir.pdf")

# The poem proper ends on page 200 with the Herald's sign-off (line 4188).
# Pages 201-203 carry a list of names and the epitaph on the Prince's tomb,
# which the edition's translation does not cover -- it ends "And here
# finishes the poem" -- so a parallel text has no English to set them with.
POEM_PAGES = range(70, 200)
TRANSLATION_PAGES = range(204, 240)

# The gutter between the two columns of a poem page. Verse sits at x≈40 (the
# manuscript) and x≈230 (the normalised text); the numbers of the normalised
# column sit out at x≈408, beyond any text.
COLUMN_SPLIT = 215.0
RIGHT_NUMBER_X = 395.0
# A running head sits above this; a folio mark ("f. 15'") to the left of it.
HEAD_Y = 55.0
FOLIO_X = 20.0
# Two extracted fragments this close together vertically are one printed line
# that the scan's OCR broke into pieces.
SAME_LINE = 6.0

# OCR reads the small marginal numerals loosely: 1040 comes back as "104°",
# 1050 as "i°5°", 905 as "9°5". The digits are recoverable because the numbers
# only ever increase.
_DIGIT_FIXES = str.maketrans({"°": "0", "o": "0", "O": "0", "i": "1", "I": "1",
                              "l": "1", "^": "1", "<": "1", ">": "1", "S": "5",
                              "s": "5", "$": "5"})

HEAD_WORDS = ("THE BLACK PRINCE", "TRANSLATION", "LIFE OF THE BLACK PRINCE",
              "CRITICAL NOTES", "HISTORICAL NOTES", "GLOSSARY")


@dataclass
class VerseLine:
    """One printed line of the poem, in both of the versions on the page."""

    number: int | None      # the line number, on every fifth line
    manuscript: str         # left column, as the scribe wrote it
    normalised: str         # right column, as the editors printed it
    page: int | None = None  # page of the scan it was read from, 1-based


# --------------------------------------------------------------------------- #
# Reading the page
# --------------------------------------------------------------------------- #
# Twenty-two pages inside the poem carry no text layer at all -- the scan's
# own OCR gave up on them -- and they are ordinary verse pages, some five
# hundred lines in total. Tesseract reads them accurately with English data,
# because the manuscript column is a diplomatic transcription: no accents, no
# diacritics, nothing that needs a French model.
OCR_LANG = "eng"
OCR_DPI = 300
MIN_TEXT = 200          # characters below which a page counts as text-less
# Column crops for the OCR fallback, in PDF points on a 462-wide page.
OCR_CROPS = ((18.0, 215.0), (215.0, 445.0))


def _ocr_fragments(page) -> list[tuple[float, float, str]]:
    """Read a page whose text layer is missing, one column at a time.

    Each column is cropped and read separately rather than letting Tesseract
    decide the layout: on a two-column page it will otherwise read straight
    across the gutter and interleave the manuscript with its normalised twin.
    Positions come back in page coordinates, so the caller cannot tell these
    fragments from ones the PDF supplied.
    """
    import subprocess

    from book_creator import ocr

    exe = ocr.tesseract_exe()
    if not exe:
        return []
    # Tesseract needs its "tsv" renderer config as well as the language, and
    # the two do not always live together: this repo keeps spare traineddata
    # in cache/tessdata, which has no configs/ directory, so asking that copy
    # for word positions fails with "Can't open tsv" and silently returns
    # plain text instead.
    own = ocr._own_tessdata(exe)
    tessdata = ocr.tessdata_dir()
    if own and (Path(own) / "configs").is_dir() and \
            (Path(own) / f"{OCR_LANG}.traineddata").exists():
        tessdata = Path(own)
    env = {"TESSDATA_PREFIX": str(Path(tessdata).resolve())} if tessdata else None
    scale = 72.0 / OCR_DPI
    out: list[tuple[float, float, str]] = []
    for x0, x1 in OCR_CROPS:
        clip = fitz.Rect(x0, HEAD_Y, x1, page.rect.height - 30)
        png = page.get_pixmap(dpi=OCR_DPI, clip=clip).tobytes("png")
        run = subprocess.run([exe, "-", "-", "-l", OCR_LANG, "--psm", "6", "tsv"],
                             input=png, capture_output=True, env=env)
        rows: dict[tuple, list[tuple[float, str]]] = {}
        for line in run.stdout.decode("utf-8", "replace").splitlines()[1:]:
            f = line.split("\t")
            if len(f) < 12 or not f[11].strip():
                continue
            try:
                conf = float(f[10])
            except ValueError:
                continue
            if conf < 40:               # Tesseract's own doubt about the word
                continue
            key = (f[2], f[3], f[4])    # block, paragraph, line
            rows.setdefault(key, []).append(
                (float(f[6]), f[11].strip(), float(f[7]) + float(f[9]) / 2))
        for parts in rows.values():
            parts.sort()
            x = x0 + parts[0][0] * scale
            y = HEAD_Y + parts[0][2] * scale
            out.append((x, y, " ".join(p[1] for p in parts)))
    return out


# A folio mark in the margin -- "f. 15'", "f. iv" -- as OCR reads it: the f
# often comes back as "t" or "£", the numeral as letters. Left in, it sits
# level with the line beside it and drags that row out to the margin, which
# is how two rubrics were split and printed as verse ("t. 46' Castillayn",
# "t.iV ⁊ en cel temps Lymoges").
# "f. 45'" has also come back as "f. as'": letters for digits are allowed
# only with the closing mark, so a word after "t." is never taken for one.
_FOLIO = re.compile(r"^[ft£][.,\-]\s*(?:[\dIiVvlLoO]{1,3}['’\"”]?"
                    r"|[\dIiVvlLoOaAsS]{1,3}['’\"”])(?:\s+|$)")


def _strip_folio(text: str) -> str:
    return _FOLIO.sub("", text.strip(), count=1).strip()


def _fragments(page) -> list[tuple[float, float, str]]:
    """(x, y, text) for every piece of text on a page, heads and marks gone."""
    if len(page.get_text().strip()) < MIN_TEXT:
        return [(x, y, _strip_folio(t)) for x, y, t in _ocr_fragments(page)
                if t.upper().strip(" .|") not in HEAD_WORDS and x >= FOLIO_X
                and _strip_folio(t)]
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            x0, y0, x1, y1 = line["bbox"]
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text or y0 < HEAD_Y:
                continue
            if x0 < FOLIO_X:
                continue                        # in the far margin: a folio mark
            text = _strip_folio(text)
            if not text:
                continue                        # nothing but a folio mark
            if text.upper().strip(" .|") in HEAD_WORDS:
                continue
            # The line's centre, not its top: a word set a size smaller or a
            # hair higher has a different top but sits on the same line.
            out.append((x0, (y0 + y1) / 2, text))
    return out


# Fragments whose centres are this close are one printed line. Lines of this
# edition sit about 12 points apart and the pieces of one line within 3.
ROW_GAP = 5.0


def _rows(pieces: list[tuple[float, float, str]]) -> dict[int, tuple[float, str]]:
    """Reassemble fragments into printed lines, keyed by height on the page.

    The text layer breaks a line wherever the scan's OCR hesitated -- "Et |
    si estoit le Court | Daunmartyn" is one line in three pieces -- so pieces
    at the same height belong together. They are grouped by closeness, not by
    rounding the height into fixed bands: two pieces of one line a point
    apart can fall either side of a band's edge, and the line then comes out
    as two, interleaved with its neighbours. That is what turned "the Count of
    Dammartin. Very goodly was his array" into "the Count of Very goodly was
    his ... Dammartin. array," in the translation.

    The key is the line's height in points, kept because it is also what
    pairs the poem's two columns: the edition prints a line and its
    normalised twin level with each other.
    """
    clusters: list[list[tuple[float, float, str]]] = []
    for piece in sorted(pieces, key=lambda p: p[1]):
        if clusters and piece[1] - clusters[-1][0][1] <= ROW_GAP:
            clusters[-1].append(piece)
        else:
            clusters.append([piece])
    out: dict[int, tuple[float, str]] = {}
    for parts in clusters:
        parts.sort()
        y = sum(p[1] for p in parts) / len(parts)
        out[round(y)] = (parts[0][0], " ".join(p[2] for p in parts))
    return out


def _number(text: str) -> tuple[int | None, str]:
    """Split a leading line number (and any folio mark before it) off a line."""
    text = re.sub(r"^f[-.,]\s*\d+\S*\s+", "", text)      # "f. 3' 195 Au Roi..."
    m = re.match(r"^([\dioIl°^<>]{2,4})\s+(.+)$", text)
    if not m:
        return None, text
    try:
        n = int(m.group(1).translate(_DIGIT_FIXES))
    except ValueError:
        return None, text
    # The edition numbers every fifth line, so a real line number is always a
    # multiple of five. "893" and "583" -- misreadings of 895 and 585 -- are
    # not, and taking them at face value is what made two stretches look as
    # if they held lines they did not. It is still a number, so it still
    # comes off the verse.
    return (n if n % 5 == 0 else None), m.group(2)


# Verse is set at the column's margin: x≈40, or x≈22 when a line number hangs
# in front of it. Anything that starts further in is something else -- a
# rubric centred across the page, or the tail of a verse line the OCR split
# because one word sat a hair above the rest.
VERSE_MAX_X = 75.0
# A fragment this close below a verse line is that line's tail, not a heading.
CONTINUATION = 9.0


# The edition marks a line lost from the manuscript with a row of dots.
_LACUNA = re.compile(r"[\s.·•]{7,}")
LACUNA = ". . . . . ."
# How far a normalised line may start from its column's verse margin and
# still be a twin. A heading's right half starts wherever the centring puts
# it, which is almost never at the margin.
TWIN_SLACK = 8.0


def _verse_margin(rows: dict[int, tuple[float, str]]) -> float | None:
    """Where verse starts in this column on this page.

    Measured, not fixed: the text block sits some 16 points further right on
    one page of a spread than the other, so a fixed position is wrong for
    half the book. Most rows are verse, so the commonest start is the margin.
    """
    from collections import Counter

    starts = Counter(round(x / 2) * 2 for x, _ in rows.values())
    common = [x for x, n in starts.most_common() if n >= 3]
    return float(common[0]) if common else None


def _twin(right: dict[int, tuple[float, str]], key: int,
          margin: float | None) -> str | None:
    """The normalised line level with a manuscript line, or None if none is.

    None, not "": no twin at all is the evidence that a row is a heading
    rather than verse, so it must not look like an empty twin.
    """
    if margin is None:
        return None
    level = [k for k in right if abs(k - key) <= ROW_GAP
             and abs(right[k][0] - margin) <= TWIN_SLACK]
    if not level:
        return None
    return _number(right[min(level, key=lambda k: abs(k - key))][1])[1]


def _junk(text: str) -> bool:
    """Signature marks, stray sigla, the odd letter the scan left behind."""
    s = text.strip(" .,;:|•'")
    if len(s) < 3:
        return True
    # The editors' apparatus at the foot of a page: "Line 1728 lapparaille,
    # marginal correction a." It is not the poem, and left in it gets read as
    # part of the next rubric.
    # OCR reads "Line" as "IJjie" or "Lzne", so the notes' English gives
    # them away too: "luy added in the margin", "a omitted and superscript".
    if re.search(r"\b(margin|omitted|added|erased|\w*perscript)\b", s.lower()):
        return True
    if re.match(r"^Lines?\s+\d", s) or "correction" in s.lower()             or "corrected" in s.lower():
        return True
    return s.upper() in ("BLACK PRINCE", "THE BLACK PRINCE") or \
        re.fullmatch(r"[\dioIl°^<>]{1,5}", s) is not None


def read_poem(doc) -> tuple[list[VerseLine], dict[int, str]]:
    """Every verse line of the poem, plus the rubrics that head its sections.

    Positions decide what a row is, not its length: the rubrics are centred
    across both columns, so a short heading such as "De la bataille" would
    pass any length test as a line of verse. The line numbers then check the
    result -- between two of them there are exactly five lines -- and any
    stretch that still has too many loses its least verse-like rows.
    """
    lines: list[VerseLine] = []
    rubrics: dict[int, str] = {}          # index into `lines` -> heading
    pending: list[str] = []               # rubric fragments not yet placed
    for page_no in POEM_PAGES:
        page = doc[page_no]
        pieces = _fragments(page)
        left = _rows([p for p in pieces if p[0] < COLUMN_SPLIT])
        right = _rows([p for p in pieces
                       if COLUMN_SPLIT <= p[0] < RIGHT_NUMBER_X])
        margin = _verse_margin(right)
        _recover_dropped_lines(page, left, right, margin)
        prev_y = None
        last_y = None
        at_margin = False       # has a verse row at the margin come yet?
        for key in sorted(left):
            x, text = left[key]
            y = key
            at_margin = at_margin or x <= VERSE_MAX_X
            gap = y - prev_y if prev_y is not None else None
            prev_y = y
            twin = _twin(right, key, margin)
            number, body = _number(text)
            if _LACUNA.fullmatch(body):
                # A line the manuscript lost, which the edition prints as a row
                # of dots in both columns. It is still a line of the poem --
                # the numbering counts it -- so it stays, as the dots.
                lines.append(VerseLine(number, LACUNA, LACUNA, page_no + 1))
                last_y = y
                continue
            if _junk(text):
                continue
            if x > VERSE_MAX_X:
                # Set in from the margin: a heading, or a verse line whose
                # opening words the text layer dropped ("en Constantyn" for
                # "Illariua en Constantyn"). A heading is set across both
                # columns with space above it; a verse line keeps the verse's
                # rhythm and has a normalised twin level with it. A heading's
                # right half can happen to start at the twin margin, so the
                # spacing decides before the twin does.
                # Indented rows above a page's first verse line are a heading
                # too: the work's own title opens page 70 that way.
                heading = pending or twin is None or not at_margin or \
                    (gap is not None and gap > RUBRIC_GAP)
                if heading:
                    if not pending and twin is None and lines and \
                            last_y is not None and y - last_y <= CONTINUATION:
                        lines[-1].manuscript += " " + text   # a split verse line
                    else:
                        pending.append(_across(text, key, right))
                    continue
            if pending:
                rubrics[len(lines)] = _join_heading(pending)
                pending = []
            lines.append(VerseLine(number, _drop_misread_number(body, twin),
                                   twin or "", page_no + 1))
            last_y = y
    return _fit_to_numbers(lines, rubrics), rubrics


def _join_heading(rows: list[str]) -> str:
    """A heading's rows as one line, with words the line end split rejoined."""
    text = " ".join(rows)
    text = re.sub(r"(\w)-\s+(?=[a-z])", r"\1", text)      # "Daqui- taine"
    return re.sub(r"\s+", " ", text).strip()


def _drop_misread_number(body: str, twin: str | None) -> str:
    """Remove a line number too mangled to be read as one.

    "1S5 Tiel meruaille", "t10 ffist guerre", "aSs Cils de Maiole": the
    number every fifth line carries came through OCR as something the number
    reader does not recognise, and stayed at the head of the verse. The
    normalised twin settles it -- it begins "Tel merveille", "ffist guerre",
    "Cil de Maiole" -- so when the line's second word matches the twin's
    first and its first word does not, the first word is the number.
    """
    import difflib

    words = body.split()
    if not twin or len(words) < 2 or len(words[0]) > 4:
        return body
    first = _fold_word(twin.split()[0]) if twin.split() else ""
    if not first:
        return body

    def like(w: str) -> float:
        return difflib.SequenceMatcher(None, _fold_word(w), first).ratio()

    if like(words[1]) >= 0.5 and like(words[1]) > like(words[0]) + 0.2:
        return " ".join(words[1:])
    return body


def _fold_word(w: str) -> str:
    return re.sub(r"[^a-z]", "", w.lower().replace("ff", "f"))


# More space than this above an indented row marks it as a heading: verse
# lines sit 12 points apart, a rubric has a blank line's worth above it.
RUBRIC_GAP = 18.0


def _across(text: str, key: int, right: dict[int, tuple[float, str]]) -> str:
    """A heading line in full: its left half plus whatever of it the gutter
    split off into the right column.

    The edition sets rubrics across both columns, so cutting the page at the
    gutter halves them: "De la passage du Roy" | "et du Prince son filtz".
    """
    level = [k for k in right if abs(k - key) <= ROW_GAP]
    if not level:
        return text
    return f"{text} {right[min(level, key=lambda k: abs(k - key))][1]}"


def _recover_dropped_lines(page, left: dict[int, tuple[float, str]],
                           right: dict[int, tuple[float, str]],
                           margin: float | None) -> None:
    """Read back manuscript lines the scan's text layer dropped.

    Where the normalised column has a verse line and the manuscript column
    has nothing level with it, the manuscript line is on the page but not in
    the text layer -- "De sa vie et de sa joenece" sits on page 72 with no
    manuscript twin. That strip of the left column is read with Tesseract and
    put where the line belongs.
    """
    if margin is None:
        return
    lm = _verse_margin(left) or 40.0
    for key, (x, text) in list(right.items()):
        if abs(x - margin) > TWIN_SLACK or _junk(text):
            continue
        if any(abs(key - k) <= ROW_GAP for k in left):
            continue
        read = _ocr_strip(page, key)
        if read and not _junk(read):
            left[key] = (lm, read)


def _ocr_strip(page, y: float) -> str:
    """One line of the manuscript column, read by Tesseract."""
    import subprocess

    from book_creator import ocr

    exe = ocr.tesseract_exe()
    if not exe:
        return ""
    own = ocr._own_tessdata(exe)
    env = {"TESSDATA_PREFIX": str(Path(own).resolve())} if own else None
    clip = fitz.Rect(OCR_CROPS[0][0], y - 8, COLUMN_SPLIT, y + 8)
    png = page.get_pixmap(dpi=OCR_DPI, clip=clip).tobytes("png")
    run = subprocess.run([exe, "-", "-", "-l", OCR_LANG, "--psm", "7"],
                         input=png, capture_output=True, env=env)
    return run.stdout.decode("utf-8", "replace").strip()


def _fit_to_numbers(lines: list[VerseLine],
                    rubrics: dict[int, str]) -> list[VerseLine]:
    """Trim stretches that hold more lines than their numbers allow.

    Between printed line numbers n and n+5 there are exactly five lines. A
    stretch with more has kept something that is not verse; the shortest rows
    go first, because a stray fragment is short and a line of octosyllables is
    not. A stretch with fewer is left alone -- lines the scan lost cannot be
    invented, and the gap is reported rather than papered over.
    """
    nums = repair_positional([l.number if l.number and l.number <= LAST_LINE
                              else None for l in lines])
    anchors = [i for i, n in enumerate(nums) if n]
    drop: set[int] = set()
    for i, j in zip(anchors, anchors[1:]):
        want = nums[j] - nums[i]
        extra = (j - i) - want
        if extra <= 0:
            continue
        inner = sorted(range(i + 1, j), key=lambda k: len(lines[k].manuscript))
        drop.update(inner[:extra])
    if not drop:
        return lines
    # Rubric positions are indexes into `lines`, so they move with the trim.
    shift = {old: old - sum(1 for d in drop if d < old) for old in list(rubrics)}
    moved = {shift[k]: v for k, v in rubrics.items()}
    rubrics.clear()
    rubrics.update(moved)
    return [l for k, l in enumerate(lines) if k not in drop]


def read_translation(doc) -> list[tuple[int | None, str]]:
    """The English prose, as (line number seen here, text) in reading order."""
    out: list[tuple[int | None, str]] = []
    for page_no in TRANSLATION_PAGES:
        rows = _rows(_fragments(doc[page_no]))
        for key in sorted(rows):
            _, text = rows[key]
            # A marginal number sits alone, or is welded to the end of a line.
            if re.fullmatch(r"[\dioIl°^<>]{2,5}", text):
                out.append((_digits(text), ""))
                continue
            # ...or opens it, set in the left margin ("145 The English army").
            lead = re.match(r"^([\dioIl°^]{3,4})\s+(?=[A-Z'‘“(])", text)
            if lead:
                out.append((_digits(lead.group(1)), text[lead.end():].strip()))
                continue
            m = re.search(r"\s([\dioIl°^]{3,4})$", text)
            if m:
                out.append((_digits(m.group(1)), text[:m.start()].strip()))
            else:
                out.append((None, text))
    return out


def _digits(text: str) -> int | None:
    try:
        return int(text.translate(_DIGIT_FIXES))
    except ValueError:
        return None


def repair(numbers: list[int | None], *, step: int) -> list[int | None]:
    """Keep the largest set of anchors that agree with one another.

    OCR turns a marginal numeral into something else often enough that some
    anchors are simply wrong, and a wrong one would drag a whole block of
    translation against the wrong stretch of verse. Walking the list and
    keeping whatever increases is no good: one number misread high ("104°"
    for 1040, early) then rejects every true number behind it. So this takes
    the longest strictly increasing subsequence instead, which lets a bad
    reading lose the argument to the many good ones around it.
    """
    spots = [i for i, n in enumerate(numbers) if n]
    values = [numbers[i] for i in spots]
    if not values:
        return list(numbers)

    # Longest increasing subsequence. Quadratic, over a few hundred anchors.
    length = [1] * len(values)
    came_from = [-1] * len(values)
    for j in range(len(values)):
        for i in range(j):
            # Anchors are printed every `step` lines, so a jump much larger
            # than the gap between their positions is a misreading, not a gap.
            span = (spots[j] - spots[i]) * step * 3 + step * 4
            if values[i] < values[j] <= values[i] + span and length[i] + 1 > length[j]:
                length[j] = length[i] + 1
                came_from[j] = i
    keep, at = set(), max(range(len(values)), key=lambda k: length[k])
    while at != -1:
        keep.add(spots[at])
        at = came_from[at]
    return [n if i in keep else None for i, n in enumerate(numbers)]


def repair_positional(numbers: list[int | None], *, window: int = 4,
                      slack: int = 2) -> list[int | None]:
    """Repair line numbers that are printed on every line they belong to.

    `repair` keeps any number that increases, which is not enough: OCR reads
    "17^°" (1720) as 1710, and 1710 still increases, so it survived and made
    five lines look like fifteen -- a stretch "missing ten lines" that had
    lost none. Where the list is one entry per printed line, as the poem's
    is, a true number and its position differ by the same amount as its
    neighbours' do; a misread one disagrees with them. So each number is
    checked against the median of that difference over the numbers around
    it, and dropped if it is out by more than `slack`.

    That check runs first, on every reading, and the increasing-run repair
    only after. The other way round, two readings of "1710" -- the true one
    and the misread 1720 -- reach the run repair together, it can keep
    either, and it kept the wrong one.
    """
    # Agreement is judged against the immediate neighbours, not a median over a
    # window. Where the scan genuinely lost lines the offset legitimately
    # shifts, and a window straddling the shift puts its median on the far
    # side and throws out good numbers next to it. A misread number disagrees
    # with the numbers on both sides of it; one beside a real gap still
    # agrees with one of them.
    spots = [i for i, n in enumerate(numbers) if n]
    offsets = [numbers[i] - i for i in spots]
    agreed: list[int | None] = [None] * len(numbers)
    for k, i in enumerate(spots):
        sides = [offsets[j] for j in (k - 1, k + 1) if 0 <= j < len(offsets)]
        if not sides or any(abs(offsets[k] - o) <= slack for o in sides):
            agreed[i] = numbers[i]
    return repair(agreed, step=5)



# --------------------------------------------------------------------------- #
# Joining the poem to its translation
# --------------------------------------------------------------------------- #
# The poem's last line: the Herald's sign-off, three lines after the last
# printed number (4185). Anything numbered past the end fell outside every
# block and silently vanished from the book, sign-off included.
LAST_LINE = 4188
GROUP = 5                   # verse lines per bead: the edition numbers in fives
CHAPTER_LINES = 250         # roughly; a chapter always ends at a rubric

# The manuscript's Tironian et (⁊) comes through OCR in half a dozen
# disguises. Each was checked against the editors' normalised line beside it,
# which spells the word out: where the manuscript has a lone "%" the twin has
# "et" 96% of the time, "t" 91%, "+" 95%, and "*", "4" and "¢" every time. A
# lone "p" (35%) is a different abbreviation and "|" (50%) a mark the edition
# prints, so those are left alone.
_TIRONIAN = re.compile(r"(?<!\S)[%4t+*¢^](?!\S)")


def _manuscript(text: str) -> str:
    # A mangled line number can survive at the start of a line as debris with
    # no letters in it ("^- ®°^ Et de monp Guilliam", ". 1' Pur ce voil").
    # Every such token goes except a lone siglum, which the next step turns
    # into the ⁊ it stands for.
    text = re.sub(r"^(?:(?![%4+*¢^]\s)[^\sA-Za-z]+\s+)+", "", text.strip())
    return re.sub(r"\s+", " ", _TIRONIAN.sub("⁊", text)).strip()


def number_lines(lines: list[VerseLine]) -> list[int]:
    """A line number for every line, from the ones printed every fifth line."""
    printed = [n if n and n <= LAST_LINE else None for n in
               (l.number for l in lines)]
    anchors = [(i, n) for i, n in enumerate(repair_positional(printed)) if n]
    out = [0] * len(lines)
    first_i, first_n = anchors[0]
    for k in range(first_i + 1):
        out[k] = first_n - (first_i - k)
    for (i, a), (j, _) in zip(anchors, anchors[1:] + [(len(lines), None)]):
        for k in range(i, j):
            out[k] = a + (k - i)
    return out


def _clean_english(piece: str) -> str:
    """Remove what the scan left in the prose that is not the translation.

    Marginal line numbers the anchor reader missed ("his 107 father", "194'i
    at Bayonne"), a running head misread into the text ("BLACK PKINCE"), and
    the caret OCR puts where the edition printed é ("B^ziers", "P^rigord").
    Done line by line, before the stream is joined, so no anchor's character
    offset moves.
    """
    # A running head misread into the text, and the translation's own title
    # on its first page ("THE LIFE OF THE BLACK PRINCE (Translation)").
    piece = re.sub(r"(THE\s+LIFE\s+OF\s+THE\s+)?\bBLACK\s+P[RK]INCE\b"
                   r"(\s*\(Translation\))?", " ", piece)
    # ...which the first page sets over three lines, so its pieces arrive apart.
    piece = re.sub(r"^\s*THE\s*$|\(Translation\)", " ", piece)
    piece = re.sub(r"(?<=[A-Za-z])\^(?=[a-z])", "é", piece)
    piece = re.sub(r"(?<!\S)['\"’]?\d{1,4}['\"’]?[a-z]?(?!\S)", " ", piece)
    return re.sub(r"\s{2,}", " ", piece).strip()


def translation_stream(doc) -> tuple[str, list[tuple[int, int]]]:
    """The English as one string, with (character offset, poem line) anchors.

    Only the printed line numbers anchor the two texts. The obvious finer
    anchor -- the translation starts a paragraph at most rubrics -- was tried
    and measured worse: matching rubrics to paragraphs by meaning (LaBSE) made
    bad anchors often enough to cut same-bead name agreement from 70% to 59%,
    and even restricted to matches a shared proper name vouched for it came
    out at 68%. A wrong anchor starves a whole block of its English, so the
    numbers alone do better -- once the misread ones are found, which is what
    _fit_translation_anchors is for.
    """
    rows = read_translation(doc)
    text, raw = "", []
    for n, piece in rows:
        if n and n <= LAST_LINE:
            raw.append((len(text), n))
        piece = _clean_english(piece)
        if not piece:
            continue
        if text.endswith("-") and piece[:1].islower():
            text = text[:-1] + piece                 # a word broken at the margin
        else:
            text = f"{text} {piece}" if text else piece
    anchors = _fit_translation_anchors(raw, len(text))
    return text, [(0, 1)] + anchors + [(len(text), LAST_LINE + 1)]


# OCR's usual confusions between the digits of a small marginal numeral.
_DIGIT_SWAPS = {"2": "3", "3": "28", "8": "036", "5": "6", "6": "58",
                "1": "7", "7": "1", "0": "8", "4": "9", "9": "4"}
# How far a stretch's English may run from the book's average density, in
# characters per verse line, before its anchors are in doubt. The 1910
# translation condenses lists and expands speeches, but never by this much.
RATE_BAND = 3.0


def _fit_translation_anchors(raw: list[tuple[int, int]],
                             total: int) -> list[tuple[int, int]]:
    """Choose the translation's line-number anchors, correcting misreadings.

    The translation's marginal numbers are misread in a way the increasing-
    run repair cannot see: on one page "225" and "277" both came through as
    "325" and "377", consistent with each other and still increasing. What
    gives them away is the English between them -- 130 verse lines translated
    in 865 characters, then 8 lines in 3,055 -- when the translation runs at
    a steady thirty-odd characters a line. So the anchors are chosen as the
    longest chain in which every stretch keeps a plausible density, where each
    number may be read as printed or with one digit swapped for its usual OCR
    confusion; a swap is taken only when it buys a longer chain.
    """
    if not raw:
        return []
    rate = total / LAST_LINE
    lo, hi = rate / RATE_BAND, rate * RATE_BAND

    nodes = [(0, 1, 0)]                             # (offset, line, swaps)
    for off, n in raw:
        nodes.append((off, n, 0))
        s = str(n)
        for i, ch in enumerate(s):
            for alt in _DIGIT_SWAPS.get(ch, ""):
                v = int(s[:i] + alt + s[i + 1:])
                if 1 < v <= LAST_LINE and (i or alt != "0"):
                    nodes.append((off, v, 1))
    nodes.append((total, LAST_LINE + 1, 0))
    nodes.sort(key=lambda t: (t[0], t[1]))

    def fits(a, b) -> bool:
        return b[0] > a[0] and b[1] > a[1] and lo <= (b[0] - a[0]) / (b[1] - a[1]) <= hi

    # best[i]: (anchors kept, -swaps, previous node) for chains ending at i.
    best: list[tuple[int, int, int] | None] = [None] * len(nodes)
    best[0] = (0, 0, -1)
    for i in range(1, len(nodes)):
        for j in range(i):
            if best[j] is None or not fits(nodes[j], nodes[i]):
                continue
            kept = best[j][0] + (0 if i == len(nodes) - 1 else 1)
            score = (kept, best[j][1] - nodes[i][2], j)
            if best[i] is None or score[:2] > best[i][:2]:
                best[i] = score
    if best[-1] is None:
        # Nothing reaches the end at this tolerance; the plain repair is
        # better than no anchors at all.
        kept = repair([n for _, n in raw], step=45)
        return [(o, n) for (o, _), n in zip(raw, kept) if n]
    chain, at = [], best[-1][2]
    while at > 0:
        chain.append(nodes[at][:2])
        at = best[at][2]
    return sorted(chain)


# Merges the aligner may make inside a block. The English is periodic prose:
# one sentence can carry fifteen lines of verse, so a single sentence is
# allowed to cover up to four five-line groups, and a group up to three
# sentences.
_STEPS = [(1, 1), (1, 2), (2, 1), (1, 3), (3, 1), (2, 2), (4, 1), (1, 0), (0, 1)]


# How much a shared proper name is worth to the aligner. The multilingual
# model is weak on Old French, and names are the one thing that survives
# translation nearly untouched -- "Warrewic" is plainly "Warwick" -- so they
# decide what the embeddings cannot. A name that matches a *different*
# sentence of the block is as telling the other way.
NAME_BONUS = 0.30
NAME_ELSEWHERE = 0.25
_NAME_STOP = {"dieux", "dieu", "roy", "rois", "roi", "prince", "princes",
              "conte", "contes", "counte", "seigniour", "sire", "france",
              "ffrance", "franchois", "englois", "engleterre", "gales",
              "chevalier", "chevaliers", "saint", "baron", "barons", "king",
              "earl", "lord", "lady", "count", "english", "french", "god",
              "then", "there", "thereupon", "when", "know", "sire", "this"}


def _fold(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if c.isalpha() and not unicodedata.combining(c))


def _names_fr(lines_: list[str]) -> set[str]:
    """Capitalised words that are not the first word of their verse line."""
    out = set()
    for line in lines_:
        for w in re.findall(r"(?<=\s)(?:d'|l')?([A-Z][a-zA-Z]{3,})", " " + line)[0:]:
            if _fold(w) not in _NAME_STOP:
                out.add(_fold(w))
    return out


def _names_en(text: str) -> set[str]:
    return {_fold(w) for w in re.findall(r"\b([A-Z][a-zA-Z']{3,})", text)
            if _fold(w) not in _NAME_STOP}


def _same_name(a: str, b: str) -> bool:
    import difflib
    return a[:2] == b[:2] and difflib.SequenceMatcher(None, a, b).ratio() >= 0.62


def _align_block(src_lines: list[list[str]], tgt: list[str]):
    """Align verse groups to English sentences: meaning plus shared names.

    Returns a path of (i, j, ds, dt) as align.run_dp does.
    """
    import numpy as np

    from book_creator.align import run_dp
    from book_creator.align_embed import _MERGE_PENALTY, _NULL_COST, _get_model

    model = _get_model("sentence-transformers/LaBSE")
    src = [" ".join(g) for g in src_lines]
    se = model.encode(src, normalize_embeddings=True, convert_to_numpy=True)
    te = model.encode(tgt, normalize_embeddings=True, convert_to_numpy=True)

    fr = [_names_fr(g) for g in src_lines]
    en = [_names_en(s) for s in tgt]
    # shared[i][j]: names group i and sentence j have in common.
    shared = [[sum(1 for a in fr[i] if any(_same_name(a, b) for b in en[j]))
               for j in range(len(tgt))] for i in range(len(src))]
    anywhere = [sum(1 for a in fr[i] if any(_same_name(a, b) for s in en for b in s))
                for i in range(len(src))]

    def pooled(mat, start, count):
        vec = mat[start:start + count].mean(axis=0)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def cost(i, j, ds, dt):
        if ds == 0 or dt == 0:
            return _NULL_COST
        sim = float(np.dot(pooled(se, i, ds), pooled(te, j, dt)))
        here = sum(shared[a][b] for a in range(i, i + ds) for b in range(j, j + dt))
        placed = sum(min(anywhere[a], sum(shared[a][b] for b in range(j, j + dt)))
                     for a in range(i, i + ds))
        elsewhere = sum(anywhere[a] for a in range(i, i + ds)) - placed
        return ((1.0 - sim) + _MERGE_PENALTY * (ds + dt - 2)
                - NAME_BONUS * min(here, 3) + NAME_ELSEWHERE * elsewhere)

    return run_dp(len(src), len(tgt), cost, steps=_STEPS)


def _groups(lines: list[VerseLine], rubrics: dict[int, str],
            numbers: list[int]) -> list[dict]:
    """The verse in fives, each carrying any rubric that stands before it."""
    out: list[dict] = []
    for k in range(len(lines)):
        fresh = (not out or k in rubrics or
                 (numbers[k] - 1) // GROUP != (numbers[out[-1]["idx"][0]] - 1) // GROUP)
        if fresh:
            out.append({"idx": [], "rubric": rubrics.get(k), "first": numbers[k]})
        out[-1]["idx"].append(k)
    return out


def _sentences(english: str) -> list[tuple[int, str]]:
    """English sentences with their offsets in the stream."""
    from book_creator import segment

    out, at = [], 0
    for s in segment.segment_prose(english, "en"):
        s = s.strip()
        if not s:
            continue
        found = english.find(s[:40], at)
        at = found if found != -1 else at
        out.append((at, s))
        at += len(s)
    return out


def build_chapters(lines: list[VerseLine], rubrics: dict[int, str],
                   english: str, anchors: list[tuple[int, int]]):
    """Beads of manuscript verse, each over the English that translates it.

    The printed line numbers fix the pairing to within a block of forty-odd
    lines; inside a block the five-line groups and the English sentences are
    matched by meaning (align_embed, LaBSE), using the editors' normalised
    text rather than the manuscript's, because that is what the translation
    was made from and the spelling a multilingual model can read.
    """
    numbers = number_lines(lines)
    sentences = _sentences(english)
    use_llm = _llm_available()
    print(f"  pairing inside blocks by "
          f"{'reading (' + LLM_MODEL + ')' if use_llm else 'embeddings (LaBSE)'}")

    units: list[tuple[list[int], list[str]]] = []      # (line indexes, english)
    for (a_off, a_n), (b_off, b_n) in zip(anchors, anchors[1:]):
        idx = [k for k in range(len(lines)) if a_n <= numbers[k] < b_n]
        ss = [s for off, s in sentences if a_off <= off < b_off]
        if not idx:
            if units and ss:
                units[-1][1].extend(ss)
            continue
        if not ss:                                  # verse the translation skips
            units.extend((idx[i:i + GROUP], []) for i in range(0, len(idx), GROUP))
            continue
        paired = None
        if use_llm:
            paired = _pair_by_reading(lines, numbers, idx, ss, a_n, b_n)
        if paired is None:
            paired = _pair_by_embedding(lines, rubrics, numbers, idx, ss)
        units.extend(paired)
    # Every line of the poem must be printed exactly once. Lines have gone
    # missing silently more than once -- numbered past the end, trimmed to
    # fit a misread number -- so this is checked, not assumed.
    placed = sorted(k for idx, _ in units for k in idx)
    if placed != list(range(len(lines))):
        lost = sorted(set(range(len(lines))) - set(placed))
        raise RuntimeError(
            f"{len(lost)} verse line(s) would not be printed, e.g. "
            f"{[lines[k].manuscript for k in lost[:3]]}; "
            f"{len(placed) - len(set(placed))} would be printed twice")
    return _chapters_from_units(lines, rubrics, numbers, units)


def _chapters_from_units(lines, rubrics, numbers, units):
    """Beads and chapters from (line indexes, English) runs, in poem order.

    A rubric stands in the manuscript between two lines of verse, so it prints
    there, in the manuscript's own words -- which can mean cutting a run in
    two, with the English going to the longer part.

    No verse is left without English. The 1910 translation condenses -- a
    list of knights becomes "and others, more than I could tell you" -- so a
    stretch of verse with no sentence of its own is still translated, by the
    English beside it. It joins the neighbouring passage on its own side of
    any rubric: the one before it, or the one after if a rubric stands
    between it and the one before.
    """
    from book_creator.model import Bead, Chapter

    pieces: list[tuple[list[int], list[str]]] = []
    for idx, eng in units:
        cuts = [0] + [p for p, k in enumerate(idx) if p and k in rubrics] + [len(idx)]
        parts = [idx[a:b] for a, b in zip(cuts, cuts[1:]) if idx[a:b]]
        longest = max(range(len(parts)), key=lambda p: len(parts[p])) if parts else 0
        for p, part in enumerate(parts):
            pieces.append((part, eng if p == longest else []))
    pieces = _join_untranslated(pieces, rubrics)

    chapters: list[Chapter] = []
    beads: list[Bead] = []
    start = numbers[0]
    for part, eng in pieces:
        first = part[0]
        if first in rubrics:
            if numbers[first] - start >= CHAPTER_LINES and beads:
                chapters.append(Chapter(
                    title=f"Lines {start}–{numbers[first] - 1}", beads=beads))
                beads, start = [], numbers[first]
            beads.append(Bead(src=[_manuscript(rubrics[first])], tgt=[],
                              heading=True))
        beads.append(Bead(src=[_manuscript(lines[k].manuscript) for k in part],
                          tgt=[" ".join(eng)] if eng else [], lines=True))
    if beads:
        chapters.append(Chapter(title=f"Lines {start}–{numbers[-1]}", beads=beads))
    return chapters


def _join_untranslated(pieces: list[tuple[list[int], list[str]]],
                       rubrics: dict[int, str]) -> list[tuple[list[int], list[str]]]:
    """Fold each passage that has no English into a neighbour that does.

    A passage's first line opening a rubric is the one wall it cannot cross:
    verse joins the passage before it unless it starts a new section, in
    which case it joins the passage after, provided that one does not start a
    section of its own. Two passes, so a run of several bare passages all
    reach an English one.
    """
    out = [(list(idx), list(eng)) for idx, eng in pieces]
    for _ in range(2):
        merged: list[tuple[list[int], list[str]]] = []
        i = 0
        while i < len(out):
            idx, eng = out[i]
            if eng:
                merged.append((idx, eng))
                i += 1
                continue
            opens_section = idx[0] in rubrics
            if merged and not opens_section:
                merged[-1] = (merged[-1][0] + idx, merged[-1][1])
            elif i + 1 < len(out) and out[i + 1][0][0] not in rubrics:
                nxt_idx, nxt_eng = out[i + 1]
                out[i + 1] = (idx + nxt_idx, nxt_eng)
            else:
                merged.append((idx, eng))     # walled in by rubrics on both sides
            i += 1
        out = merged
    return out


def _pair_by_embedding(lines, rubrics, numbers, idx, ss):
    """The fallback: five-line groups matched to sentences by LaBSE and names."""
    # A five-line group can straddle an anchor that is not a multiple of five,
    # so each is cut to this block's lines: otherwise its head is lost to the
    # block before and its tail printed twice.
    inside = set(idx)
    groups = [g for g in ({**g, "idx": [k for k in g["idx"] if k in inside]}
                          for g in _groups(lines, rubrics, numbers)) if g["idx"]]
    src = [[lines[k].normalised or lines[k].manuscript for k in g["idx"]]
           for g in groups]
    out: list[tuple[list[int], list[str]]] = []
    for i, j, ds, dt in _align_block(src, ss):
        took = [k for g in groups[i:i + ds] for k in g["idx"]]
        if not took:
            if out:
                out[-1][1].extend(ss[j:j + dt])
            continue
        out.append((took, list(ss[j:j + dt])))
    return out


# --------------------------------------------------------------------------- #
# Pairing by reading
# --------------------------------------------------------------------------- #
# A local language model reads the normalised verse and the English and says
# where each sentence's passage begins. On a block checked by hand against the
# page it put all eight passages within two lines of the truth, five exactly;
# the embedding aligner could only get the stanza right. Answers are cached,
# so a rebuild asks again only about blocks whose text has changed.
LLM_MODEL = "qwen3:14b"
LLM_HOST = "http://localhost:11434"
LLM_CACHE = Path("cache") / "chandos-pairing.json"


def _llm_available() -> bool:
    import requests

    try:
        tags = requests.get(f"{LLM_HOST}/api/tags", timeout=5).json()
    except Exception:  # noqa: BLE001 - not running is an answer, not an error
        return False
    return any(m.get("name", "").startswith(LLM_MODEL) for m in tags.get("models", []))


def _llm_starts(verse: list[tuple[int, str]], sentences: list[str]) -> list:
    """Ask the model where each English sentence's passage begins."""
    import hashlib

    import requests

    key = hashlib.sha1(json.dumps([LLM_MODEL, verse, sentences],
                                  ensure_ascii=False).encode()).hexdigest()
    cache = {}
    if LLM_CACHE.exists():
        cache = json.loads(LLM_CACHE.read_text(encoding="utf-8"))
    if key in cache:
        return cache[key]

    prompt = (
        "Below is a passage of 14th-century Anglo-Norman verse, each line with "
        "its line number, followed by a faithful English prose translation of "
        "the same passage, split into numbered sentences.\n"
        "For EACH English sentence, give the line number of the verse line "
        "where the part of the poem it translates BEGINS. The numbers must "
        "never decrease. Answer only with JSON of the form "
        '{"S1": <line>, "S2": <line>, ...}.\n\nVERSE:\n'
        + "\n".join(f"{n}: {t}" for n, t in verse)
        + "\n\nENGLISH:\n"
        + "\n".join(f"S{i + 1}: {s}" for i, s in enumerate(sentences)))
    # The answer is a dozen numbers. Without a cap on its length, JSON mode can
    # finish the object and then go on emitting whitespace until the context
    # is full -- one block ran for more than twenty minutes that way.
    reply = requests.post(f"{LLM_HOST}/api/chat", json={
        "model": LLM_MODEL, "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0, "num_ctx": 16384,
                    "num_predict": 24 + 14 * len(sentences)},
        "messages": [{"role": "user", "content": prompt}]}, timeout=900).json()
    content = reply["message"]["content"]
    try:
        answer = json.loads(content)
    except json.JSONDecodeError:
        # Cut short mid-object by the cap: keep the pairs that did finish.
        answer = {k: int(v) for k, v in re.findall(r'"(S\d+)"\s*:\s*(\d+)', content)}
    starts = [answer.get(f"S{i + 1}") for i in range(len(sentences))]
    cache[key] = starts
    LLM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    LLM_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return starts


def _clean_starts(raw: list, lo: int, hi: int) -> list[int]:
    """Make the model's answers usable: in range, never decreasing, complete.

    An answer out of order is dropped rather than trusted, by keeping the
    longest non-decreasing run of them; a missing one takes its predecessor's
    value, so its sentence joins the one before. The first sentence starts
    the block, since the printed line number says that is where it begins.
    """
    vals = []
    for v in raw:
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = None
        vals.append(v if v is not None and lo <= v <= hi else None)
    spots = [i for i, v in enumerate(vals) if v is not None]
    length = [1] * len(spots)
    came = [-1] * len(spots)
    for j in range(len(spots)):
        for i in range(j):
            if vals[spots[i]] <= vals[spots[j]] and length[i] + 1 > length[j]:
                length[j], came[j] = length[i] + 1, i
    keep = set()
    if spots:
        at = max(range(len(spots)), key=lambda k: length[k])
        while at != -1:
            keep.add(spots[at])
            at = came[at]
    out, last = [], lo
    for i, v in enumerate(vals):
        last = v if i in keep else last
        out.append(last)
    if out:
        out[0] = lo
    return out


def _pair_by_reading(lines, numbers, idx, ss, a_n, b_n):
    """Runs of verse, each with the English sentences that translate them.

    Returns None if the model cannot be asked, so the caller can fall back.
    """
    verse = [(numbers[k], lines[k].normalised or lines[k].manuscript) for k in idx]
    try:
        raw = _llm_starts(verse, ss)
    except Exception as exc:  # noqa: BLE001 - fall back rather than fail a build
        print(f"  !  model unavailable for lines {a_n}-{b_n - 1} ({exc}); "
              "using embeddings there")
        return None
    starts = _clean_starts(raw, a_n, b_n - 1)
    # Sentences that begin on the same line translate one passage together,
    # so they are grouped by where they begin before any verse is assigned.
    groups: list[tuple[int, list[str]]] = []
    for begin, s in zip(starts, ss):
        if groups and groups[-1][0] == begin:
            groups[-1][1].append(s)
        else:
            groups.append((begin, [s]))
    out: list[tuple[list[int], list[str]]] = []
    for g, (begin, sentences) in enumerate(groups):
        end = groups[g + 1][0] if g + 1 < len(groups) else b_n
        # Selected from the block's own lines rather than looked up by number,
        # so every line of the block lands in exactly one run.
        out.append(([k for k in idx if begin <= numbers[k] < end], sentences))
    return out


# --------------------------------------------------------------------------- #
# What still needs a human
# --------------------------------------------------------------------------- #
# Characters the manuscript column never legitimately contains, and a capital
# inside a word ("I^e" for "Le", "hono^"): what OCR leaves behind.
_MISREAD = re.compile(r"[0-9^°®¢$@{}\[\]\<>~_=«»§()]|[a-z][A-Z]")


def proofread(lines: list[VerseLine], chapters) -> str:
    """A worklist of everything the build could not settle by itself.

    Each entry names the page of the scan to check it against. The build
    fixes what the page's own structure can prove -- line numbers, headings,
    the Tironian et, lines the text layer dropped -- and lists the rest here
    rather than guessing: a misread in a diplomatic transcription can only be
    corrected by someone reading the manuscript column on the page.
    """
    numbers = number_lines(lines)
    out = ["# The Life of the Black Prince — proofreading list", "",
           "Pages are pages of the scan, `input/Chandos Herald - la vie du "
           "prince noir.pdf`, counted from 1.", ""]

    # 1. Lines the scan lost outright.
    nums = repair_positional([l.number if l.number and l.number <= LAST_LINE
                              else None for l in lines])
    marks = [(i, n) for i, n in enumerate(nums) if n]
    lost = [(a, b, (b - a) - (j - i), lines[i].page)
            for (i, a), (j, b) in zip(marks, marks[1:]) if (j - i) < (b - a)]
    out += [f"## Lines missing from the scan ({sum(x[2] for x in lost)})", ""]
    if lost:
        out.append("The printed line numbers show a line is missing between "
                   "them; the scan has no text for it. Type it in from the page.")
        out.append("")
        for a, b, n, page in lost:
            out.append(f"- lines {a}–{b}: {n} missing (page {page})")
    else:
        out.append("None.")

    # 2. Manuscript lines that still look misread.
    suspect = [(numbers[k], l) for k, l in enumerate(lines)
               if l.manuscript != LACUNA and _MISREAD.search(_manuscript(l.manuscript))]
    out += ["", f"## Manuscript lines that look misread ({len(suspect)})", "",
            "Each shows the line as printed in this book, then the editors' "
            "normalised reading of it, which is usually enough to see the fix.",
            ""]
    for n, l in suspect:
        out.append(f"- **{n}** (page {l.page}): `{_manuscript(l.manuscript)}`  ")
        out.append(f"  normalised: {l.normalised or '—'}")

    # 3. Verse printed with no English beside it.
    bare = []
    for ch in chapters:
        for b in ch.beads:
            if b.lines and not b.tgt:
                bare.append((ch.title, len(b.src), b.src[0]))
    out += ["", f"## Verse printed without English ({len(bare)} passages, "
            f"{sum(x[1] for x in bare)} lines)", "",
            "Usually where the 1910 translation condenses the verse -- a list of "
            "knights becomes 'and others, more than I could tell you'. Worth a "
            "glance to confirm none is a pairing slip.", ""]
    for title, n, first in bare:
        out.append(f"- {title}: {n} line(s) from “{_manuscript(first)[:50]}”")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Checking the extraction
# --------------------------------------------------------------------------- #
def inspect(doc) -> None:
    """Report what came out of the PDF, before anything is built from it."""
    lines, rubrics = read_poem(doc)
    numbered = [(i, l.number) for i, l in enumerate(lines) if l.number]
    kept = repair([n for _, n in numbered], step=5)
    good = [n for n in kept if n]

    print(f"poem: {len(lines)} verse lines from {len(POEM_PAGES)} pages")
    print(f"  line numbers: {len(numbered)} printed, {len(good)} survive repair")
    print(f"  numbering runs {good[0]} -> {good[-1]}"
          f" (the edition ends at 4185)")
    blank_norm = sum(1 for l in lines if not l.normalised)
    print(f"  lines missing their normalised twin: {blank_norm}")
    print(f"  rubrics (section headings): {len(rubrics)}")
    for i, (at, title) in enumerate(sorted(rubrics.items())[:4]):
        print(f"     line {at}: {title[:62]}")

    print("\n  sample, manuscript | normalised:")
    for l in lines[600:606]:
        print(f"     {l.number or '':>5}  {l.manuscript[:34]:<36} | {l.normalised[:34]}")

    trans = read_translation(doc)
    anchors = [n for n, _ in trans if n]
    kept_t = [n for n in repair(anchors, step=45) if n]
    words = sum(len(t.split()) for _, t in trans)
    print(f"\ntranslation: {len(trans)} lines, {words:,} words")
    print(f"  anchors: {len(anchors)} printed, {len(kept_t)} survive repair")
    print(f"  they run {kept_t[0]} -> {kept_t[-1]}")
    gaps = [b - a for a, b in zip(kept_t, kept_t[1:])]
    print(f"  spacing: min {min(gaps)}, median {sorted(gaps)[len(gaps)//2]}, "
          f"max {max(gaps)} poem lines apart")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspect", action="store_true",
                    help="report what the extraction found and write nothing")
    ap.add_argument("--pdf", default=str(SRC_PDF))
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)

    doc = fitz.open(args.pdf)
    if args.inspect:
        inspect(doc)
        return 0
    return build(doc, out_dir=Path(args.out))


CACHE = Path("cache") / "chandos-poem.json"


def read_poem_cached(doc) -> tuple[list[VerseLine], dict[int, str]]:
    """read_poem, remembered: 22 of its pages go through Tesseract each time.

    Keyed on the PDF and on the source of the extraction functions -- not on
    this whole file, or every change to the aligner would OCR the pages again.
    """
    import hashlib
    import inspect as _inspect

    src = Path(doc.name)
    code = "".join(_inspect.getsource(f) for f in (
        _fragments, _ocr_fragments, _rows, _number, _junk, read_poem,
        _fit_to_numbers, repair, repair_positional, _twin, _verse_margin,
        _across, _recover_dropped_lines, _ocr_strip, _join_heading,
        _drop_misread_number, _strip_folio))
    # And on the settings they read: narrowing POEM_PAGES once left the names
    # list from page 202 in a stale cache, numbered on past the last line.
    code += repr((POEM_PAGES, LAST_LINE, COLUMN_SPLIT, RIGHT_NUMBER_X, HEAD_Y,
                  FOLIO_X, SAME_LINE, HEAD_WORDS, OCR_LANG, OCR_DPI, MIN_TEXT,
                  OCR_CROPS, _FOLIO.pattern, ROW_GAP, VERSE_MAX_X, CONTINUATION,
                  _LACUNA.pattern, TWIN_SLACK, RUBRIC_GAP))
    key = (f"{src.stat().st_size}:{src.stat().st_mtime_ns}:"
           + hashlib.sha1(code.encode()).hexdigest()[:12])
    if CACHE.exists():
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        if data.get("key") == key:
            print("Reading the poem (cached)...")
            return ([VerseLine(**l) for l in data["lines"]],
                    {int(k): v for k, v in data["rubrics"].items()})
    print("Reading the poem (22 pages need OCR; this takes a minute)...")
    lines, rubrics = read_poem(doc)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"key": key,
                                 "lines": [vars(l) for l in lines],
                                 "rubrics": rubrics}, ensure_ascii=False),
                     encoding="utf-8")
    return lines, rubrics


# Lines the scan lost, typed in by hand from the page. Kept in input/, not
# output/: the proofreading list in output/ is rewritten on every build, and
# anything typed into it would be gone with the next one.
CORRECTIONS = Path("input") / "chandos-corrections.md"


def read_supplied(path: Path) -> list[tuple[int, int, int, list[str]]]:
    """(first, last, page, typed lines) for each stretch filled in by hand.

    Read from the "Lines missing from the scan" section of the proofreading
    list, in the shape the build writes it: a "- lines A–B: N missing (page
    P)" entry, then the text typed beneath it, indented.
    """
    if not path.exists():
        return []
    out: list[tuple[int, int, int, list[str]]] = []
    section = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("## "):
            section = raw.startswith("## Lines missing")
            continue
        if not section:
            continue
        head = re.match(r"^- lines (\d+)\D+(\d+).*?page (\d+)", raw)
        if head:
            out.append((int(head[1]), int(head[2]), int(head[3]), []))
        elif out and raw.startswith("  ") and raw.strip():
            # Drop a note the proofreader left at the end: "... - line 930".
            text = re.sub(r"\s+[-–—]+\s*line\s*\d+\s*$", "", raw.strip())
            out[-1][3].append(text)
    return out


def _same_line(a: str, b: str) -> float:
    import difflib

    fold = lambda s: re.sub(r"[^a-z]", "", s.lower().replace("ff", "f"))
    return difflib.SequenceMatcher(None, fold(a), fold(b)).ratio()


# How alike a typed line and an extracted one must be to count as the same.
# Typed lines are in the editors' spelling and are compared with both
# columns, since a line whose normalised twin the scan lost still has its
# manuscript text.
MATCH = 0.5


def _align_typed(typed: list[str], have: list[tuple[str, str]]) -> dict[int, int]:
    """Match typed lines to extracted ones, in order: typed index -> have index.

    A proper sequence alignment rather than a greedy scan: greedily, one
    early typed line matched in the wrong place shifts every match after it,
    which is how a line already on the page got inserted a second time.
    """
    m, n = len(typed), len(have)
    sim = [[max(_same_line(a, b) for b in pair if b) if any(pair) else 0.0
            for pair in have] for a in typed]
    score = [[0.0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            best = max(score[i - 1][j], score[i][j - 1])
            if sim[i - 1][j - 1] >= MATCH:
                best = max(best, score[i - 1][j - 1] + sim[i - 1][j - 1])
            score[i][j] = best
    pairs, i, j = {}, m, n
    while i and j:
        took = score[i - 1][j - 1] + sim[i - 1][j - 1]
        if sim[i - 1][j - 1] >= MATCH and score[i][j] == took:
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif score[i][j] == score[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return pairs


def apply_supplied(lines: list[VerseLine], rubrics: dict[int, str],
                   supplied) -> tuple[list[VerseLine], dict[int, str]]:
    """Put the lines typed in by hand where they belong.

    What was typed covers a whole stretch in the editors' spelling -- more
    than the missing lines, and sometimes running on into the next stretch --
    so it is aligned against both columns of what was extracted. A typed line
    that matches nothing, and sits between two that do, is missing from the
    scan and goes in before the line that follows it.

    The printed line numbers only find the neighbourhood. They are OCR'd too
    -- on the first stretch typed in, "585" came through as 583 -- so they
    cannot be trusted to say how many lines are missing or where; the typed
    text, read off the page, is what says which lines are there. The typed
    text is printed as typed.
    """
    if not supplied:
        return lines, rubrics
    numbers = number_lines(lines)
    inserts: list[tuple[int, VerseLine]] = []
    dropped: set[int] = set()
    for first, last, page, typed in supplied:
        window = [k for k in range(len(lines)) if first - 25 <= numbers[k] <= last + 25]
        have = [(lines[k].normalised, lines[k].manuscript) for k in window]
        pairs = _align_typed(typed, have)
        matched = sorted(pairs)
        chosen = []
        for i, text in enumerate(typed):
            if i in pairs:
                continue
            after = next((pairs[x] for x in matched if x > i), None)
            before = next((pairs[x] for x in reversed(matched) if x < i), None)
            if after is None or before is None:
                continue                    # context typed around the stretch
            chosen.append((window[after], text))
            # On an OCR'd page a verse line can be read as a rubric -- both
            # its columns run together, "sen ala a voir entendre s'en ala, au
            # voir entendre" -- and would print twice beside the typed one.
            for r in [r for r in rubrics if window[0] <= r <= window[-1]]:
                if _same_line(text, rubrics[r]) >= MATCH:
                    dropped.add(r)
        inserts += [(k, VerseLine(None, text, text, page)) for k, text in chosen]
        print(f"  supplied lines {first}–{last}: {len(chosen)} inserted"
              + (f" ({'; '.join(c[1][:30] for c in chosen)})" if chosen else ""))
    if not inserts:
        return lines, rubrics
    before_line: dict[int, list[VerseLine]] = {}
    for k, v in inserts:
        before_line.setdefault(k, []).append(v)
    out: list[VerseLine] = []
    moved: dict[int, str] = {}
    for k, line in enumerate(lines):
        if k in rubrics and k not in dropped:
            # A heading before this line stays before what is now inserted
            # ahead of it: the missing line belongs to the section it opens.
            moved[len(out)] = rubrics[k]
        out.extend(before_line.get(k, []))
        out.append(line)
    return out, moved


TITLE = "The Life of the Black Prince"
AUTHOR = "Chandos Herald"
SLUG = "life-of-the-black-prince"


def build(doc, *, out_dir: Path) -> int:
    from book_creator import render_epub, render_pdf
    from book_creator.model import CopyrightSpec, DecorSpec, FontSpec

    lines, rubrics = read_poem_cached(doc)
    lines, rubrics = apply_supplied(lines, rubrics, read_supplied(CORRECTIONS))
    print(f"  {len(lines)} verse lines, {len(rubrics)} rubrics")
    english, anchors = translation_stream(doc)
    print(f"  {len(english.split()):,} words of translation, "
          f"{len(anchors) - 2} line-number anchors")
    chapters = build_chapters(lines, rubrics, english, anchors)
    beads = sum(len(c.beads) for c in chapters)
    print(f"  {len(chapters)} chapters, {beads} beads")

    font = FontSpec(family="Cardo")
    decor = DecorSpec(margin="none", chapter="medieval")
    copyright = CopyrightSpec(
        holder="Joey Houser", year=2026,
        translator="Mildred K. Pope and Eleanor C. Lodge",
        rights=(
            "The Anglo-Norman poem, written by the Herald of Sir John Chandos "
            "about 1385, and the English translation by Mildred K. Pope and "
            "Eleanor C. Lodge (Oxford, Clarendon Press, 1910) are in the public "
            "domain. The verse is printed as the editors transcribed it from "
            "the manuscript. This edition's arrangement, typography and design "
            "are copyright &copy; 2026 Joey Houser."),
    )
    edition_line = ("Anglo-Norman text with English translation — "
                    "after the edition of Pope & Lodge, 1910")

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"{SLUG}.pdf"
    chars = sum(len(b.src_text) + len(b.tgt_text) for c in chapters for b in c.beads)
    print(f"Rendering PDF -> {pdf}")
    _, pages = render_pdf.render(
        chapters, out_path=str(pdf), title=TITLE, author=AUTHOR,
        src_lang="xno", tgt_lang="en", trim=(6.0, 9.0), first="src",
        estimated_pages=max(24, chars // 1400), font_spec=font, decor=decor,
        copyright=copyright, include_toc=True, edition_line=edition_line)
    print(f"  {pages} pages")

    epub_path = out_dir / f"{SLUG}.epub"
    print(f"Rendering EPUB -> {epub_path}")
    render_epub.render(chapters, out_path=str(epub_path), title=TITLE,
                       author=AUTHOR, src_lang="xno", tgt_lang="en",
                       font_spec=font, decor=decor, copyright=copyright,
                       edition_line=edition_line)

    # The pairing written out in full, for proofreading against the scan.
    review = out_dir / f"{SLUG}-pairs.json"
    review.write_text(json.dumps(
        [{"chapter": c.title, "src": b.src, "tgt": b.tgt}
         for c in chapters for b in c.beads], ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"Pairs for proofreading -> {review}")

    report = out_dir / f"{SLUG}-proofread.md"
    report.write_text(proofread(lines, chapters), encoding="utf-8")
    print(f"What still needs an eye  -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
