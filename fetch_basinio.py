#!/usr/bin/env python
"""Extract Basinio's Hesperis from Drudi's 1794 edition (Google Books AuzlAAAAMAAJ).

Source: input/Hesperis_Astronomicon_Meleagris_Argonaut.pdf, downloaded by hand
(Google Books will not serve it to a script). Google's own OCR text layer is
good on this print -- every line of verse is a line of text -- so no
recogniser is run. What the layer carries besides verse, and what is dropped:
running heads ('HESPERIDOS LIBER III.'), page and margin line numbers, the
prose argument before book 1, and the library stamps at the front.

Book openings need repair. The printer set each book's first letter as a
display capital, which the OCR reads as a separate line, or loses:

    INTEREA            <- display word, then the line with its first letter gone
    NTEREA ipse furens murorum impulsor anhelos

Writes input/hesperis_la.txt with one 'LIBER n' heading per book.
"""
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

PDF = Path(__file__).parent / "input" / "Hesperis_Astronomicon_Meleagris_Argonaut.pdf"
OUT = Path(__file__).parent / "input" / "hesperis_la.txt"

FIRST_PAGE, LAST_PAGE = 42, 339          # 1-based PDF pages: book 1 title .. end of book 13
TITLE = re.compile(r"BASINI\s*PARMENSIS\W+HESPERIDOS\W+LIBER", re.S)

# Lines that are not verse: numbers, running heads, OCR debris.
NOISE = re.compile(
    r"^[\W\d_]*$"                                 # '3', '245', ':', '$ $ $'
    r"|HESPERIDOS|BASIN\s*\.?\s*PARM|^LIBER\b|^[IVXLi1l]{1,6}\s*[.,:]?$"
    r"|^BASINII?\s*(PARMENSIS)?\W*$|^PARMENSIS$"
    r"|^[A-Z][a-z]{0,2}\s?\d{1,2}\*?$"                 # quire signatures: A 3, Bb2
    r"|^(PRIMVS|SECVNDVS|TERTIVS|QVARTVS|QVINTVS|SEXTVS|SEPTIMVS|OCTAVVS|NONV\s?S|DECIMVS"
    r"|VNDECIMVS|DVODECIMVS|DECIMVS)\W*$",
    re.I)

# Display initials the OCR split from, or lost out of, the first verse of a book.
# Restored from the verse itself; keyed by what the OCR actually produced.
OPENINGS = {
    "NTEREA ipse furens": "Interea ipse furens",
    "Ec minus interea": "Nec minus interea",
    "XTULIT interea": "Extulit interea",
    "AVERAT Oceano": "Laverat Oceano",
    "NTEREA totum volitans": "Interea totum volitans",
    "A BSTULERAT": "Abstulerat",
    "VIGAT interea": "Navigat interea",
}


def clean_lines(text: str) -> list[str]:
    out: list[str] = []
    raw = [ln.strip() for ln in text.splitlines()]
    for i, ln in enumerate(raw):
        if not ln or NOISE.search(ln) or len(ln) < 10 or re.match(r"BAS[IİL]N", ln):
            continue  # a hexameter is never under ten characters
        # A lone display word directly above its own truncated first line.
        nxt = next((x for x in raw[i + 1:] if x and not NOISE.search(x)), "")
        if ln.isupper() and " " not in ln and len(ln) <= 10 and nxt[:1].isupper() \
                and nxt.lower().startswith(ln[1:].lower()[:3]):
            continue
        if len(ln) == 1 and ln.isupper():
            continue
        out.append(ln)
    return out


def tidy(line: str) -> str:
    for broken, fixed in OPENINGS.items():
        if line.startswith(broken):
            line = fixed + line[len(broken):]
            break
    line = re.sub(r"^([A-Z]) ([A-Z]{2,})", r"\1\2", line)   # 'A BSTULERAT'
    line = re.sub(r"\s+([,.;:!?])", r"\1", line)               # OCR spaces before marks
    return re.sub(r"\s{2,}", " ", line).strip()


def main() -> int:
    doc = fitz.open(PDF)
    books: list[list[str]] = []
    for n in range(FIRST_PAGE, LAST_PAGE + 1):
        text = doc[n - 1].get_text()
        if TITLE.search(re.sub(r"\s+", " ", text)):
            books.append([])
        if not books:
            continue
        fresh = not books[-1]
        lines = [tidy(ln) for ln in clean_lines(text)]
        if fresh and lines:
            # The book's first word is set in capitals ('LABITUR', 'TAlia').
            first, _, rest = lines[0].partition(" ")
            lines[0] = (first.capitalize() + " " + rest).strip()
        books[-1].extend(lines)
    out = []
    for i, b in enumerate(books, 1):
        out.append(f"LIBER {i}")
        out.extend(b)
        out.append("")
        print(f"book {i}: {len(b)} lines", file=sys.stderr)
    OUT.write_text("\n".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
