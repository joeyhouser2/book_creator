#!/usr/bin/env python
"""Extract Ercilla's La Araucana as octavas: part 1 (cantos 1-15) and parts 2-3 (16-37).

Sources, both on archive.org:

  part 1     `laaraucanapoema01erciuoft`, the 1911 edition in modern orthography,
             which a translation model reads better than the 1803 printing
             ('ia' for 'ya', capitalised nouns).
  parts 2-3  `laaraucana02erci`, volume 2 of the 1803 Madrid (Sancha) edition,
             cantos 16-37. The 1911 edition's later volumes are not on archive.org,
             and this is the only complete run of the second and third parts that
             came with a usable text layer. Its OCR reads 'CANTO XXII' as
             'CANTO XXIt', so the cantos are numbered by their order, not by
             their numerals.

Each octava is a block of eight lines set off by blank lines, so the poem needs
little cleaning beyond the running heads, the prose argument at the head of each
canto, and an octava a page break has split in two.

The poem has 37 cantos in three parts (1569, 1578, 1589). No public-domain English
exists (Lancaster and Manchester's 1945 translation is in copyright), so the
English is machine translation, made octava by octava because a stanza is the unit
that holds a sentence.

Writes input/araucana_es.txt (cantos 1-15) and input/araucana2_es.txt (16-37):
'CANTO n' headings, one octava per block.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "cache" / "araucana"
BASE = "https://archive.org/download/{id}/{id}_djvu.txt"

# part -> (archive.org id, first canto, last canto, output file)
PARTS = {
    1: ("laaraucanapoema01erciuoft", 1, 15, "araucana_es.txt"),
    2: ("laaraucana02erci", 16, 37, "araucana2_es.txt"),
}

HEAD = re.compile(r"^C[AO]NTO\b[\sIVXLilt1.,rl]*$", re.I)
RUNHEAD = re.compile(r"^(LA\s+A[RK]AUCANA\b.*|\d+\s+LA\s+A[RK]AUCANA.*|TOMO\b.*|[\W\d]{0,6})$", re.I)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


def roman(tok: str) -> int:
    total, prev = 0, 0
    for c in reversed(tok):
        v = ROMAN[c]
        total += v if v >= prev else -v
        prev = max(prev, v)
    return total


def blocks(lines: list[str]) -> list[list[str]]:
    out: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        s = re.sub(r"\s+", " ", ln).strip()
        if RUNHEAD.match(s):
            if not s:
                if cur:
                    out.append(cur)
                    cur = []
            continue                          # a running head is dropped, and the break stays
        cur.append(s)
    if cur:
        out.append(cur)
    # An octava a page break cut in two: the halves add up to eight.
    merged: list[list[str]] = []
    i = 0
    while i < len(out):
        b = out[i]
        if len(b) < 8 and i + 1 < len(out) and len(b) + len(out[i + 1]) == 8:
            b = b + out[i + 1]
            i += 1
        merged.append(b)
        i += 1
    return merged


def headings(lines: list[str]) -> list[int]:
    """Line numbers of the cantos' headings, in order. A heading is a short
    line that is 'CANTO' and a numeral, however the OCR garbled the numeral;
    the table of contents (if any) is skipped by starting after the front matter."""
    found = [i for i, l in enumerate(lines)
             if HEAD.match(re.sub(r"\s+", " ", l).strip()) and len(l.strip()) < 40]
    return found


def extract(part: int) -> str:
    ident, first, last, _ = PARTS[part]
    path = CACHE / f"{ident}.txt"
    if not path.exists() or path.stat().st_size < 100_000:
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-sL", "-m", "300", "-o", str(path), BASE.format(id=ident)], check=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = headings(lines)
    if part == 1:
        # The 1911 volume repeats each canto number in its table of contents; the
        # poem's heading is the first of each numeral.
        seen: dict[int, int] = {}
        for i in starts:
            tok = re.sub(r"[^IVXL]", "", re.sub(r"\s+", " ", lines[i]).strip().upper().replace("CANTO", ""))
            if tok:
                seen.setdefault(roman(tok), i)
        order = sorted((i, n) for n, i in seen.items())
    else:
        order = [(i, first + k) for k, i in enumerate(starts[: last - first + 1])]
    out: list[str] = []
    for k, (at, n) in enumerate(order):
        if n > last:
            break
        stop = order[k + 1][0] if k + 1 < len(order) else len(lines)
        octavas = [b for b in blocks(lines[at + 1:stop]) if len(b) == 8]
        print(f"canto {n:>2}: {len(octavas)} octavas", file=sys.stderr)
        out += ["", f"CANTO {n}", ""]
        for b in octavas:
            out += b + [""]
    return "\n".join(out)


def main() -> int:
    wanted = [int(a) for a in sys.argv[1:]] or list(PARTS)
    for part in wanted:
        (HERE / "input" / PARTS[part][3]).write_text(extract(part), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
