#!/usr/bin/env python
"""Extract Kudrun's 1,705 strophes from Bartsch's 1865 edition.

Source: archive.org `kudrun00bartgoog` (Google's scan of Deutsche Classiker des
Mittelalters, vol. 2), read by Tesseract's stock `lat` model. That model beat
GT4HistOCR here by a wide margin -- GT4HistOCR was trained on blackletter and
reads this Antiqua 'w' as 'v' ('vas' for 'was') -- and it keeps the MHG
diacritics (hér, künic, hóhe).

Bartsch prints each strophe, then a German commentary paragraph on it, so the
verse is interleaved with prose. What tells them apart:

    1 Ez wuohs in Irlande ...        <- strophe: bare number, then verse, after a blank
    1, 1 Dem Anfange des ...         <- commentary: 'strophe, line', then German

Strophes run 1..1705 without a break across all 32 Aventiuren, so the number is
the key: each is looked for in order, which keeps an OCR slip in one number
('9' for '2') from derailing the rest. A strophe the OCR lost is written as a
visible gap rather than skipped, so the count against Nichols' English stays
honest.

Aventiure headings come from the printed table of contents, and a division
opens where its heading is followed by Bartsch's German summary and then the
next strophe.

Writes input/kudrun_mhg.txt, one 'N. Aventiure' heading per division and one
strophe per blank-line-separated block.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).parent / "cache" / "ocr" / "bartsch_1865-db70a724febf78f5-lat-300.txt"
BACKUP = Path(__file__).parent / "cache" / "kudrun" / "bartsch_google_djvu.txt"
OUT_EN = Path(__file__).parent / "input" / "kudrun_en.txt"
NICHOLS = Path(__file__).parent / "cache" / "pg46109.txt"
OUT = Path(__file__).parent / "input" / "kudrun_mhg.txt"
LAST = 1705

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}
HEAD = re.compile(r"^\W*([IVXL1l|]{1,8})\W*\s*[ÁÂAÀÄ]*\s*V[EI]NTIU", re.I)
VERSE_START = re.compile(r"^(\d{1,4})\s+(?=[A-Za-zÄÖÜäöüÁÉÍÓÚáéíóúêôîû])")
# Debris the OCR leaves after a line ('/.212,3.', a stray '^' or '|' at the end).
# A '^' in the middle of a line is Bartsch's caesura mark, so it is only
# removed when little follows it.
NOISE_END = re.compile(r"\s+[\^~|]+\s*\S{0,14}\s*$|\s*/\.\s*\d.*$")


def roman_values(tok: str) -> set[int]:
    """What a printed numeral could be, allowing for OCR's I/1/l/L confusions."""
    vals = set()
    for variant in {tok, tok.replace("L", "I"), tok[:-1] if tok.endswith("L") else tok,
                    tok.replace("1", "I").replace("l", "I"),
                    tok.replace("1", "I").replace("l", "I").replace("L", "I")}:
        if not variant or any(c not in ROMAN for c in variant):
            continue
        total, prev = 0, 0
        for c in reversed(variant):
            v = ROMAN[c]
            total += v if v >= prev else -v
            prev = max(prev, v)
        vals.add(total)
    return vals


COMMENTARY = re.compile(r"^\d{1,4}\s?,\s?\d|\b(stf|stm|stn|swv|stv|swm|prät|präs|pret|praet|conj|adj|"
                        r"adv|gen|dat|acc|pl|sing|femin|neutr|vgl|vg\]|Nib|Handschrift|Strophe|"
                        r"infin|suin|part|imper|subst)\b\.?|[—–-]\s*\d{1,2}\b")
START = re.compile(r"^([0-9$§]{1,4})\s+(?=[A-Za-zÄÖÜäöüÁÉÍÓÚáéíóúêôîû.])")
PAGEHEAD = re.compile(r"KUDRUN|V[EI]NTIU|^\d+\s+[IVXL]+\.", re.I)


def read_number(tok: str, last: int, nxt: list[str] | None = None) -> int:
    """The strophe's number: as printed if that makes sense after `last`,
    otherwise simply the next one -- the OCR reads '2' as '9' and '5' as '$'.

    A longer jump is believed only when the *following two* strophes' printed
    numbers agree with it. That is what lets a run of lost strophes be crossed without
    renumbering everything after it, while '9' for '2' (whose successor is '3')
    is still refused.
    """
    if tok.isdigit():
        t = int(tok)
        if last < t <= last + 8:
            return t
        if last + 8 < t <= min(last + 80, LAST) and nxt and len(nxt) == 2                 and all(x.isdigit() for x in nxt)                 and t < int(nxt[0]) <= t + 8 and int(nxt[0]) < int(nxt[1]) <= int(nxt[0]) + 8:
            return t
    return last + 1


def next_token(lines: list[str], i: int) -> list[str]:
    """Printed numbers of the next two strophe-start lines after lines[i]."""
    found: list[str] = []
    for j in range(i + 1, min(i + 120, len(lines))):
        m = START.match(lines[j])
        if m:
            found.append(m.group(1))
            if len(found) == 2:
                break
    return found


def take_block(lines: list[str], i: int) -> list[str] | None:
    """The verse lines of the strophe that starts at lines[i], or None."""
    m = START.match(lines[i])
    block = [lines[i][m.end():].strip()]
    j = i + 1
    while j < len(lines) and len(block) < 6:
        ln = lines[j].strip()
        if not ln:
            j += 1
            continue
        if START.match(ln) and len(block) >= 3 or COMMENTARY.search(ln) or PAGEHEAD.search(ln):
            break
        block.append(ln)
        j += 1
    if len(block) < 3 or COMMENTARY.search(block[0]) or PAGEHEAD.search(block[0]):
        return None
    if sum(len(b) for b in block) / len(block) < 28:     # glosses are short
        return None
    return block


def anchors(tokens: list[int | None]) -> list[int]:
    """Indices of the printed numbers worth believing: the longest strictly
    increasing run, found by patience sorting.

    A strophe's number is believed if it fits the order the strophes are in.
    The OCR reads '2' as '9', and a forward-only rule that accepts anything
    plausible after the last number accepts that '9' and then renumbers every
    strophe after it. The longest increasing run simply leaves the 9 out.
    """
    import bisect

    tails: list[int] = []           # smallest tail value of a run of each length
    tail_idx: list[int] = []        # index in `tokens` of that tail
    prev: list[int] = [-1] * len(tokens)
    for i, t in enumerate(tokens):
        if t is None:
            continue
        k = bisect.bisect_left(tails, t)
        if k == len(tails):
            tails.append(t)
            tail_idx.append(i)
        else:
            tails[k] = t
            tail_idx[k] = i
        prev[i] = tail_idx[k - 1] if k else -1
    out: list[int] = []
    i = tail_idx[-1] if tail_idx else -1
    while i != -1:
        out.append(i)
        i = prev[i]
    return out[::-1]


def parse(path: Path) -> dict[int, list[str]]:
    """Strophes by number for one OCR text."""
    lines = path.read_text(encoding="utf-8").splitlines()
    # The introduction quotes strophes to discuss the metre, and the scan would
    # take them for the poem. Start at the poem's own first line.
    begin = next(i for i, l in enumerate(lines) if re.match(r"^1\s+E[zs]\s+wuohs", l))
    found: list[tuple[str, list[str]]] = []      # (printed number, verse lines), in order
    i = begin
    while i < len(lines):
        if START.match(lines[i]):
            blk = take_block(lines, i)
            if blk:
                kept = [b for b in (NOISE_END.sub("", x) for x in blk) if len(b) >= 8]  # a lone "D" reads as a heading
                found.append((START.match(lines[i]).group(1), kept))
        i += 1

    tokens = [int(t) if t.isdigit() and 0 < int(t) <= LAST else None for t, _ in found]
    keep = set(anchors(tokens))
    strophes: dict[int, list[str]] = {}
    last = 0
    for idx, (_, blk) in enumerate(found):
        if idx in keep:
            n = tokens[idx]
        else:
            # Between two anchors, a strophe with no believable number takes the
            # next one -- but never one the next anchor already owns.
            n = last + 1
            nxt = next((tokens[j] for j in sorted(keep) if j > idx), LAST + 1)
            if n >= nxt:
                continue
        if n <= LAST and n not in strophes:
            strophes[n] = blk
        last = n
    return strophes


def nichols() -> tuple[list[tuple[int, str]], str]:
    """Nichols' 32 tales: [(first stanza, title)], and the English as a file
    with one 'Adventure N' heading per tale and one stanza per block."""
    raw = NICHOLS.read_text(encoding="utf-8").splitlines()
    tale = re.compile(r"^\s*Tale the ([A-Za-z-]+)\.?\s*$")
    stanza_no = re.compile(r"^\s*\[(\d+)\]\s*$")
    tales: list[tuple[int, str]] = []
    stanzas: dict[int, list[str]] = {}
    cur = None
    title_next = False
    for ln in raw:
        if tale.match(ln):
            tales.append((0, ""))
            title_next = True
            continue
        if title_next and ln.strip():
            tales[-1] = (0, ln.strip())
            title_next = False
            continue
        m = stanza_no.match(ln)
        if m:
            cur = int(m.group(1))
            stanzas[cur] = []
            if tales and tales[-1][0] == 0:
                tales[-1] = (cur, tales[-1][1])
            continue
        if cur is not None and ln.strip():
            indent = len(ln) - len(ln.lstrip())
            if indent >= 8 and stanzas[cur]:
                stanzas[cur][-1] += " " + ln.strip()          # a wrapped fourth line
            elif indent >= 2 and len(stanzas[cur]) < 4:
                stanzas[cur].append(ln.strip())
            else:
                cur = None                                      # prose after the poem
    starts = {start: d for d, (start, _) in enumerate(tales, 1)}
    out: list[str] = []
    for n in range(1, LAST + 1):
        if n in starts:
            out += ["", f"Adventure {starts[n]}", ""]
        out += stanzas.get(n, []) + [""]
    return tales, "\n".join(out)


def main() -> int:
    strophes = parse(SRC)
    # Google's own OCR of the same scan reads some strophes the stock model
    # lost. It is the worse reader overall, so it only fills gaps.
    backup = parse(BACKUP)
    filled = [n for n in backup if n not in strophes]
    for n in filled:
        strophes[n] = backup[n]
    # Division boundaries come from Nichols, not from Bartsch's headings: the
    # strophe numbering is shared (1,705 each), Nichols' 32 'Tale the ...'
    # headings give the first stanza of each exactly, and Bartsch's running
    # heads are too easily misread to place a boundary within a strophe or two.
    # Using the one list for both files is what makes the pairing exact.
    tales, english = nichols()
    opens = {start: d for d, (start, _) in enumerate(tales, 1)}
    out: list[str] = []
    for n in range(1, LAST + 1):
        if n in opens:
            out += ["", f"Aventiure {opens[n]}", ""]
        out += strophes.get(n, ["[strophe lost to OCR]"]) + [""]
    missing = [n for n in range(1, LAST + 1) if n not in strophes]
    print(f"{len(strophes)} of {LAST} strophes recovered ({len(filled)} from the backup OCR); "
          f"{len(opens)} Aventiuren; first missing: {missing[:12]}", file=sys.stderr)
    OUT.write_text("\n".join(out), encoding="utf-8")
    OUT_EN.write_text(english, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
