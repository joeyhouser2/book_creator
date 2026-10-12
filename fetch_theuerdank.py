#!/usr/bin/env python
"""Extract the poem of Theuerdank (1517) from Haltaus's 1836 edition.

Source: archive.org `bub_gb_UDhTAAAAcAAJ` (Google Books scan), vol. 2 of the
*Bibliothek der gesammten deutschen National-Literatur*, Quedlinburg and
Leipzig, Basse, 1836.  Haltaus keeps the 1517 spelling and sets it in Fraktur.

The item's own text layer read that Fraktur as Latin type, so every long s is
an 'f' and every 'st' ligature a 'ß' -- "fchwert" for "schwert", "iß" for
"ist" -- and a repair would have to guess.  ocr_theuerdank.py instead re-reads
the page images with Tesseract's Fraktur model, which gets the long s right
and keeps the two columns of each page apart.  This script cleans that text.

What a page carries besides verse, and what is dropped here:

  * a running head ("TEWRDANNCK X, 130 - 196"), sometimes split in two, and a
    page number;
  * at the foot, the variant readings of the 1519 editions
    ("Vers 54) leichtlichen B. 57) Ernholb C, Druckfehler.");
  * the chapter's rubric, a printed summary of two to four lines, which is
    kept, as the chapter's heading.

The verse is set in columns about 32 characters wide, so a verse often takes
two physical lines, and every fifth verse ends with its number.  Those numbers
rebuild the verses: between two of them there are exactly five, so the
physical lines in between need `lines - 5` joins, which go first to lines that
follow a hyphen and then to the shortest remaining lines.

Writes input/theuerdank_de.txt: 'CAPITEL n', the rubric on one line, then the
chapter's verses, one per line.  ſ is written s.

    python fetch_theuerdank.py [--stats]
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
OCR_DIR = HERE / "cache" / "theuerdank" / "ocr"
OUT = HERE / "input" / "theuerdank_de.txt"

N_CHAPTERS = 118
ROMAN = [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
         (5, "V"), (4, "IV"), (1, "I")]
HEAD_ROMAN = re.compile(r"^[\W_]*([IVXLCl1i|]{1,10})\s*[.,;:]?\W*$")
RANGE = re.compile(r"([IVXLCl1i|]+)\s*[.,]\s*(\d+)\s*[—–-]+\s*(\d+)")
FOOT_MARK = re.compile(r"(?:^|\s)\d{1,3}\s*\)\s")
NOTE_WORDS = re.compile(
    r"B\s*u\s*C|B\s*n\s*C|Druckf|aufgekleb|aufgeleim|Anmerkung|^R[uvd][bdr]+\.|"
    r"Ausgabe|Holzschnitt|umgekehrt|Zettel|^[VFT]e?[rt]s\.?\s*\d|Codex|Handschrift")
WIDE = 40  # rubric lines run 45-55 characters, verse lines 32 at most


def roman(n: int) -> str:
    s = ""
    for v, r in ROMAN:
        while n >= v:
            s += r
            n -= v
    return s


def norm_roman(s: str) -> str:
    return re.sub(r"[l1i|]", "I", s).upper()


def clean_line(l: str) -> str:
    return (l.replace("ſ", "s").replace("ﬅ", "st").replace("ﬀ", "ff")
             .replace("ﬁ", "fi").replace("ﬂ", "fl"))


def page_lines(text: str) -> list[str]:
    """One page's verse and rubric lines, with the running head, the page
    number and the variant readings gone.

    Tesseract flows the left column and then the right.  On about 17 pages it
    fuses one row of each into a single line with a "|" between; the halves
    are kept as two lines, in place, which misplaces that one verse of the
    right column.
    """
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    lines: list[str] = []
    for p in paras:
        ls = [l.strip() for l in p.splitlines() if l.strip()]
        joined = " ".join(ls)
        # a block of variant readings: "Vers 54) leichtlichen B. 57) ..."
        if FOOT_MARK.search(" " + joined) and NOTE_WORDS.search(joined):
            continue
        lines.extend(ls)
    out = []
    for l in lines:
        for piece in re.split(r"\s+\|\s+", l):
            piece = piece.strip(" |	")
            if len(piece) <= 3:
                continue                  # page numbers, detached verse numbers, debris
            if NOTE_WORDS.search(piece) or FOOT_MARK.search(" " + piece):
                continue
            if re.search(r"[A-Z]{4,}", piece) and not HEAD_ROMAN.match(piece):
                continue                  # "TEWRDANNCK", "TewRDANNCK X, 130 - 196."
            if RANGE.search(piece) and len(piece) < 40:
                continue                  # "XI, 1 - 60."
            if re.fullmatch(r"[IVXLCl1i]{1,6}[,.]\s*\d+\s*u\.?\s*\d+\.?", piece):
                continue                  # "II, 1 u. 2."
            out.append(clean_line(piece))
    return out


def head_totals(texts: list[str]) -> dict[int, int]:
    """Chapter number -> its last verse number, read from the running heads."""
    want = {norm_roman(roman(n)): n for n in range(1, N_CHAPTERS + 1)}
    tot: dict[int, int] = {}
    for t in texts:
        for m in RANGE.finditer(t):
            n = want.get(norm_roman(m.group(1)))
            if n:
                tot[n] = max(tot.get(n, 0), int(m.group(3)))
    return tot


def anchor(line: str, expected: int) -> tuple[str, int | None]:
    """Split a trailing verse number off a line."""
    m = re.search(r"^(.*?\S)\s*[,.;:!?]?\s*(\d{1,3})$", line)
    if not m or not re.search(r"\D", m.group(1)):
        return line, None
    rest, num = m.group(1), int(m.group(2))
    if num % 5 or not expected <= num <= expected + 20:
        # An OCR slip in the number ("6o", "130"): take the next one due.
        if num % 5 == 0 or expected - 5 <= num <= expected + 5:
            return line[: m.start(2)].rstrip(), expected
        return line, None
    return line[: m.start(2)].rstrip(), num


def reflow(lines: list[tuple[str, int | None]], total: int | None) -> list[str]:
    """Physical lines (with verse-number anchors) -> verses."""
    verses: list[str] = []
    seg: list[str] = []
    prev = 0

    def flush(count: int | None) -> None:
        nonlocal seg
        if not seg:
            return
        joined = [seg[0]]
        # forced joins: a line that follows a hyphen
        cont = [False] * len(seg)
        for i in range(1, len(seg)):
            if seg[i - 1].endswith("-"):
                cont[i] = True
        need = (len(seg) - count - sum(cont)) if count else None
        if need is None:
            # No count: join only the clear cases, a short tail after a full line.
            for i in range(1, len(seg)):
                if (not cont[i] and len(seg[i]) <= 10 and len(seg[i - 1]) >= 26
                        and not re.search(r"[.!?:;]$", seg[i - 1])):
                    cont[i] = True
        elif need > 0:
            cands = [i for i in range(1, len(seg))
                     if not cont[i] and len(seg[i - 1]) >= 20]
            cands.sort(key=lambda i: (len(seg[i]), i))
            for i in cands[:need]:
                cont[i] = True
        for i in range(1, len(seg)):
            if cont[i]:
                a = joined[-1]
                joined[-1] = (a[:-1] if a.endswith("-") else a + " ") + seg[i]
            else:
                joined.append(seg[i])
        verses.extend(joined)
        seg = []

    for text, num in lines:
        seg.append(text)
        if num is not None:
            flush(num - prev)
            prev = num
    flush((total - prev) if total and total > prev else None)
    return verses


MODERN = re.compile(r"\b(?:und|dass|deshalb|wird|sind|nicht|Gedichts?|Ehrenhold|Ausgabe|"
                    r"Beweis|richtiger|Worte|darunter|zusammen)\b")


def trailing_number(line: str) -> int | None:
    m = re.search(r"(?<!\d)(\d{1,3})\s*$", line)
    if m and re.search(r"\D", line[: m.start()]):
        v = int(m.group(1))
        if v % 5 == 0 and v >= 5:
            return v
    return None


def chapter_starts(body: list[str]) -> list[tuple[int, bool]]:
    """(index, has_rubric) of each chapter's first line.

    A rubric is a run of wide lines (45-55 characters, against 32 for verse)
    that is followed by the verse numbered 5.  A few rubrics are set narrower,
    or their numeral is lost; those chapters are found instead by the verse
    numbers starting over at 5 in the middle of what looked like one chapter.
    """
    n = len(body)
    starts: list[tuple[int, bool]] = []
    i = 0
    while i < n:
        if len(body[i]) >= WIDE:
            j = i
            while j + 1 < n and len(body[j + 1]) >= WIDE:
                j += 1
            if not MODERN.search(" ".join(body[i:j + 1])):
                nxt = next((trailing_number(body[k]) for k in range(j + 1, min(n, j + 40))
                            if trailing_number(body[k]) is not None), None)
                if i == 0 or (nxt is not None and nxt <= 20):
                    if not starts or i - starts[-1][0] > 3:
                        starts.append((i, True))
            i = j + 1
        else:
            i += 1
    # Numbering that starts over inside a chapter: a 5 (or 10, 15, when the
    # first numbers were misread) after anchors that had reached 30 or more,
    # with the next number following close behind.
    out: list[tuple[int, bool]] = []
    for k, (s, rub) in enumerate(starts):
        out.append((s, rub))
        end = starts[k + 1][0] if k + 1 < len(starts) else n
        prev_val, prev_idx = 0, s
        for i in range(s + 4, end):
            v = trailing_number(body[i])
            if v is None:
                continue
            if (v <= 15 and prev_val >= v + 20 and i - prev_idx < 30 and end - i > 12
                    and any(trailing_number(body[j]) == v + 5 for j in range(i + 1, min(end, i + 14)))):
                out.append((prev_idx + 1, False))
            prev_val, prev_idx = v, i
    # A numeral line ("XLVI.") the rubric detection missed: the scan is damaged
    # there and the rubric's lines are out of order, but the numeral is intact.
    have = [s for s, _ in out]
    for i, l in enumerate(body):
        m = HEAD_ROMAN.match(l)
        if (m and len(l) >= 4 and numeral_value(norm_roman(m.group(1))) is not None
                and all(abs(i - h) > 8 for h in have)):
            out.append((i, False))
            have.append(i)
    return sorted(out)


def numeral_value(r: str) -> int | None:
    """The number a clean roman numeral stands for, else None."""
    d = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    if not r or any(c not in d for c in r):
        return None
    t = 0
    for a, b in zip(r, r[1:] + " "):
        t += -d[a] if d[a] < d.get(b, 0) else d[a]
    return t if roman(t) == r and 1 < t <= N_CHAPTERS else None


def main() -> int:
    stats = "--stats" in sys.argv
    files = sorted(OCR_DIR.glob("p*.txt"))
    if not files:
        print("no OCR yet: run ocr_theuerdank.py first", file=sys.stderr)
        return 1
    texts = [f.read_text(encoding="utf-8") for f in files]
    totals = head_totals(texts)
    body: list[str] = []
    for t in texts:
        body.extend(page_lines(t))
    # Chapter 1 opens at its rubric, "Wie Künig Romreich ..."; the poem ends
    # at "Darnach die ewig seligkeit!", before Pfintzing's prose epilogue.
    first = next(i for i, l in enumerate(body) if l.startswith("Wie Künig Romreich"))
    last = next(i for i, l in enumerate(body) if "ewig seligkeit" in l and i > first + 5000)
    body = body[first:last + 1]
    starts = chapter_starts(body)
    starts[0] = (0, True)
    # a "chapter" under 8 lines is a stray wide line, not a chapter (XCVII is
    # a real one of 10 verses, which a limit of 20 dropped)
    ends = [x for x, _ in starts[1:]] + [len(body)]
    starts = [st for st, e in zip(starts, ends) if st is starts[0] or e - st[0] >= 8]
    print(f"{len(starts)} chapters ({sum(1 for _, r in starts if not r)} "
          f"without a rubric); the poem has {N_CHAPTERS}", file=sys.stderr)
    out: list[str] = []
    built: list[dict] = []
    number = 0
    for idx, (s, has_rubric) in enumerate(starts):
        n = number + 1
        for j in range(max(0, s - 4), s + 1):
            m = HEAD_ROMAN.match(body[j])
            v = numeral_value(norm_roman(m.group(1))) if m and len(body[j]) >= 3 else None
            if v and v > number:
                n = v
        number = n
        e = starts[idx + 1][0] if idx + 1 < len(starts) else len(body)
        ch = body[s:e]
        # The rubric is a run of wide lines (45-55 characters, against 32 for
        # verse) and a short tail; a rubric set narrower runs to its full stop.
        k = 0
        if has_rubric:
            if ch and len(ch[0]) >= WIDE:
                while k < len(ch) and len(ch[k]) >= WIDE and k < 6:
                    k += 1
                if k < len(ch) and not ch[k - 1].endswith("."):
                    k += 1                # "gen ward," -- the rubric's last short line
            else:
                k = next((i + 1 for i, l in enumerate(ch[:7]) if l.endswith(".")), 1)
        rubric = re.sub(r"^\W*(?:[A-Za-z]{1,2}\s+)?(?=[A-ZÄÖÜ])", "",
                        " ".join(ch[:k]).replace("- ", ""))
        if rubric and not rubric.endswith((".", "!", "?")):
            # so that sentence-by-sentence translation ends the rubric here
            # and does not run it into the first verses
            rubric = rubric.rstrip(" ,;:") + "."
        exp = 5
        phys: list[tuple[str, int | None]] = []
        for l in ch[k:]:
            if HEAD_ROMAN.match(l) and len(l) >= 3:
                continue                  # a numeral line left in the verse
            text, num = anchor(l, exp)
            if num is not None:
                exp = num + 5
            phys.append((text, num))
        if rubric.startswith("Der beschluss"):
            n = N_CHAPTERS                # the closing chapter, whatever came before
        verses = [tidy(v) for v in reflow(phys, totals.get(n))]
        if stats:
            anchors = sum(1 for _, a in phys if a is not None)
            print(f"{n:3d} lines {len(phys):4d} verses {len(verses):4d} "
                  f"anchors {anchors}  {rubric[:50]}", file=sys.stderr)
        built.append({"n": n, "rubric": tidy(rubric), "verses": verses})
    patch_damaged(built)
    for ch in built:
        out.append(f"Kapitel {ch['n']}")
        out.append(ch["rubric"])
        out.extend(ch["verses"])
        out.append("")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    return 0


# Six chapters whose rubric the scan or the OCR damaged, mended by hand from
# what the page does carry. Each entry: the chapter number, the verse lines it
# opens with as OCR'd (a mismatch skips the patch, so a changed OCR cannot be
# silently mis-patched), the rubric to put in their place, any verses to put
# after it, and verses that are the end of the PREVIOUS chapter.
DAMAGED = {
    7: (["Wie drey hauptlewt verdruss", "Edlen Tewrdanck schicket", "den Helden in das lanndt"],
        "Wie drey hauptlewt verdruss, das die Künigin nach dem Edlen Tewrdanck "
        "schicket, vnd vnnderstünden sich, den Helden in das lanndt nicht zulassen.", [], []),
    46: (["Tewrdannckh windters", "licheit auf eim gefrorn", "Eyss sein scheff", "eim grossen sturm"],
         "Wie Tewrdannckh windters zeit in ein geferlicheit auf eim gefrorn wasser "
         "furet, vnnd Im das Eyss sein scheff zerschneyd in eim grossen sturm windt.", [], []),
    101: (["TewBD1NNecKx CI", "1 —", "Wie Tewrdannck der Edel", "Held mit dem ersten Ritter"],
          "Wie Tewrdannck der Edel Held mit dem ersten Ritter scharpf rennet.",
          ["As nun kam die anngesetzt zeit,", "Tewrdannck sich in rennzeüg anleyt,"], []),
    111: (["Als Fürwittig sein red het tan", "Allzdann das vrteyl", "e et", "Wie Vnfallo gehenckt ward"],
          "Wie Vnfallo gehenckt ward.", ["Am morgen ward Vnfalo gefürt"],
          ["Als Fürwittig sein red het tan,", "Da kniet nider der arm Man,",
           "Da ward Im abgeschlagen sein hanbt,", "Allzdann das vrteyl het erlaubt.",
           "Also die fürwitzig sach nam", "Ein enndt, Vnfalo hernach kam."]),
    112: (["Wie Neydelhart ward zu todt"],
          "Wie Neydelhart ward zu todt geworffen.", [], []),
    114: (["Sy hette In thun erwelen", "Wie der Ernhold sein wirbt", "ná leo", "potschafft an den Tewrdannckh"],
          "Wie der Ernhold sein wirbt potschafft an den Tewrdannckh.", [],
          ["Sy hette In thun erwelen", "Zü sandt Iörgen rays als ein Man,",
           "Der Tewr wer, dorsft solchs nemen an."]),
}


def patch_damaged(built: list[dict]) -> None:
    by_n = {ch["n"]: i for i, ch in enumerate(built)}
    for n, (opening, rubric, after, to_prev) in DAMAGED.items():
        i = by_n.get(n)
        if i is None:
            continue
        v = built[i]["verses"]
        if len(v) < len(opening) or any(not v[k].startswith(o) for k, o in enumerate(opening)):
            print(f"  ! chapter {n}: OCR no longer opens as expected; not patched", file=sys.stderr)
            continue
        if built[i]["rubric"].strip() and built[i]["rubric"].startswith("Wie"):
            continue                      # the extractor found its rubric after all
        built[i]["rubric"] = rubric
        built[i]["verses"] = after + v[len(opening):]
        if to_prev and i:
            built[i - 1]["verses"] += to_prev


def tidy(l: str) -> str:
    """Fraktur OCR habits: the superscript e of an umlaut comes out as æ/œ."""
    l = re.sub(r"eœæ|œæ|œ", "ö", l)
    l = re.sub(r"æ", "ä", l)
    l = re.sub(r"[‘’“”„‹›«»]+|[\^~*_]", "", l)
    return re.sub(r"^- ", "", re.sub(r"\s{2,}", " ", l)).strip(" |")


if __name__ == "__main__":
    sys.exit(main())
