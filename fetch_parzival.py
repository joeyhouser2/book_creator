#!/usr/bin/env python
"""Assemble Jessie Weston's Parzival (1894) as sixteen clean books.

Weston's English is prose, in two Gutenberg volumes (#47297 books 1-9 and #47298
books 10-16), each book opening with a title, an ARGUMENT and then the book's
heading again before the text; each volume closes with appendices and notes
keyed to the books. Gutenberg's own file puts every heading and every note under
a 'BOOK n' line, so a loader that splits on them finds 60 divisions where the
poem has 16. This keeps only the text of each book:

    BOOK I
    GAMURET
    ARGUMENT ...             <- dropped
    BOOK I                   <- the text starts after this heading and its title
    GAMURET
    If unfaith in the heart ...

and writes each paragraph on a single line, so a block of it prints as
paragraphs rather than as the hard-wrapped lines of the Gutenberg file.

The Middle High German (input/parzival_mhg.txt, fetch_sources.py parzival) is
verse and Weston's English is prose, so the two cannot be paired line by line:
the book is set 'block' fashion, each book's German followed by its English.

Writes input/parzival_weston_en.txt with 'Buch n' headings to match the German.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
VOLUMES = [HERE / "cache" / "pg47297.txt", HERE / "cache" / "pg47298.txt"]
OUT = HERE / "input" / "parzival_weston_en.txt"
BOOK = re.compile(r"^\s*BOOK ([IVXL]+)\s*$")
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}
STOP = re.compile(r"^\s*(APPENDIX A|NOTES)\s*$|\*\*\* END OF")


def roman(tok: str) -> int:
    total, prev = 0, 0
    for c in reversed(tok):
        v = ROMAN[c]
        total += v if v >= prev else -v
        prev = max(prev, v)
    return total


def books(path: Path) -> dict[int, list[str]]:
    # split on newlines only: splitlines() also breaks on form feeds and U+2028,
    # which this file has, and the line numbers then no longer match the file's.
    lines = path.read_bytes().decode("utf-8").replace("\r", "").split("\n")
    # The table of contents lists the books too; the poem starts at the first
    # 'BOOK I' that is followed by an ARGUMENT.
    marks: list[tuple[int, int]] = []
    for i, ln in enumerate(lines):
        m = BOOK.match(ln)
        if m and any("ARGUMENT" in x for x in lines[i + 1:i + 8]):
            marks.append((i, roman(m.group(1))))
    end = next(i for i, ln in enumerate(lines) if i > marks[-1][0] and STOP.match(ln))
    out: dict[int, list[str]] = {}
    for k, (at, n) in enumerate(marks):
        stop = marks[k + 1][0] if k + 1 < len(marks) else end
        body = lines[at + 1:stop]
        # Skip to the second heading (the one above the text), then its title line.
        j = next(i for i, ln in enumerate(body) if BOOK.match(ln))
        body = body[j + 1:]
        while body and not body[0].strip():
            body = body[1:]
        body = body[1:]                         # the book's title ('GAMURET')
        paras: list[str] = []
        cur: list[str] = []
        for ln in body:
            if ln.strip():
                cur.append(ln.strip())
            elif cur:
                paras.append(re.sub(r"\[\d+\]", "", " ".join(cur)).strip())
                cur = []
        if cur:
            paras.append(re.sub(r"\[\d+\]", "", " ".join(cur)).strip())
        out[n] = paras
    return out


def main() -> int:
    allbooks: dict[int, list[str]] = {}
    for v in VOLUMES:
        allbooks.update(books(v))
    out: list[str] = []
    for n in sorted(allbooks):
        out += ["", f"Buch {n}", ""]
        for p in allbooks[n]:
            out += [p, ""]
        print(f"book {n}: {len(allbooks[n])} paragraphs", file=sys.stderr)
    OUT.write_text("\n".join(out), encoding="utf-8")
    return 0 if len(allbooks) == 16 else 1


if __name__ == "__main__":
    sys.exit(main())
