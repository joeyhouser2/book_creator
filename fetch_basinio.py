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

Writes input/<poem>_la.txt (hesperis, astronomicon, meleagris, argonauticon) with one 'LIBER n' heading per book.
"""
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

PDF = Path(__file__).parent / "input" / "Hesperis_Astronomicon_Meleagris_Argonaut.pdf"
HERE = Path(__file__).parent

# poem -> (the name as it is printed in the running head, first and last PDF
# page, output file). The same 1794 volume holds all four; pages are 1-based.
POEMS = {
    "hesperis": ("HESPERIDOS", 42, 339, "hesperis_la.txt"),
    "astronomicon": ("ASTRONOMICON", 346, 398, "astronomicon_la.txt"),
    "meleagris": ("MELEAGRIDOS", 400, 500, "meleagris_la.txt"),
    "argonauticon": ("ARGONAVTICON", 508, 560, "argonauticon_la.txt"),
}

# Lines that are not verse: numbers, running heads, OCR debris.
NOISE = re.compile(
    r"^[\W\d_]*$"                                 # '3', '245', ':', '$ $ $'
    r"|HESPERIDOS|ASTRONOMICON|MELEAGRIDOS|ARGONAV?TICON|BASIN\s*\.?\s*PARM|^LIBER\b|^[IVXLi1l]{1,6}\s*[.,:]?$"
    r"|^BASINII?\s*(PARMENSIS)?\W*$|^PARMENSIS$"
    r"|^[A-Z][a-z]{0,2}\s?\d{1,2}\*?$"                 # quire signatures: A 3, Bb2
    r"|^(PRIMVS|SECVNDVS|TERTIVS|QVARTVS|QVINTVS|SEXTVS|SEPTIMVS|OCTAVVS|NONV\s?S|DECIMVS"
    r"|VNDECIMVS|DVODECIMVS|DECIMVS|TERTIVS DECIMVS)\W*$",
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


# Words where Google's text layer and an independent Tesseract `lat` read of the
# same page disagree, Google's word is not Latin and Tesseract's is. Found by
# comparing the two line by line (6,907 of 6,970 lines match up) and keeping
# only a one-letter difference where the vocabulary decides; of the eight such
# disagreements two were rejected on reading the verse ('si marte domares' is a
# correct subjunctive; 'variumque' is unsettled). Everything else the two OCRs
# agree on, which is the better evidence that the text layer is sound.
SECOND_OCR = {"faturis": "futuris", "illine": "illinc", "Acarides": "Aeacides",
              "aestis": "aestus", "Italian": "Italiam", "fulvuin": "fulvum"}


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
    line = re.sub(r"\b(" + "|".join(SECOND_OCR) + r")\b", lambda m: SECOND_OCR[m.group(1)], line)
    for broken, fixed in OPENINGS.items():
        if line.startswith(broken):
            line = fixed + line[len(broken):]
            break
    line = re.sub(r"^([A-Z]) ([A-Z]{2,})", r"\1\2", line)   # 'A BSTULERAT'
    line = re.sub(r"\s+([,.;:!?])", r"\1", line)               # OCR spaces before marks
    return re.sub(r"\s{2,}", " ", line).strip()


ORDINALS = {"PRIM": 1, "SECV": 2, "TERT": 3, "QVAR": 4, "QVIN": 5, "SEXT": 6, "SEPT": 7,
            "OCTA": 8, "NONV": 9, "DECI": 10, "VNDE": 11, "DVOD": 12}


def ordinal(words: str) -> int:
    """The number a title's ordinal names ('NONV S' -> 9, 'TERTIVS DECIMVS' -> 13), or 0.

    Running heads repeat the poem's name above every page, with a numeral; only
    a heading naming the *next* book in order opens one."""
    toks = words.split()
    if len(toks) > 1 and toks[0].startswith("TERT") and toks[1].startswith("DECI"):
        return 13
    return ORDINALS.get(toks[0][:4], 0) if toks else 0



def extract(poem: str) -> list[list[str]]:
    """The books of one poem, as lists of verse lines."""
    name, first, last, _ = POEMS[poem]
    title = re.compile(r"BASINI\s*PARMENSIS\W+" + name + r"\W+LIBER\s+((?:[A-Z]{1,8}\s*){1,3})", re.S)
    doc = fitz.open(PDF)
    books: list[list[str]] = []
    for n in range(first, last + 1):
        text = doc[n - 1].get_text()
        m = title.search(re.sub(r"\s+", " ", text))
        if m and ordinal(m.group(1)) == len(books) + 1:
            books.append([])
        if not books:
            continue
        fresh = not books[-1]
        lines = [tidy(ln) for ln in clean_lines(text)]
        if fresh and lines:
            # The book's first word is set in capitals ('LABITUR', 'TAlia').
            head, _, rest = lines[0].partition(" ")
            lines[0] = (head.capitalize() + " " + rest).strip()
        books[-1].extend(lines)
    return books


def main() -> int:
    wanted = sys.argv[1:] or list(POEMS)
    for poem in wanted:
        books = extract(poem)
        out = []
        for i, b in enumerate(books, 1):
            out.append(f"LIBER {i}")
            out.extend(b)
            out.append("")
            print(f"{poem} book {i}: {len(b)} lines", file=sys.stderr)
        (HERE / "input" / POEMS[poem][3]).write_text("\n".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
