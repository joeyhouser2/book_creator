#!/usr/bin/env python
"""Extract Musurus' Ode to Plato (1513) and Roscoe's English of it (1805).

Greek: the 154 lines of the ode as Dijkstra & Hermans print them, Akroterion 60
(2015), which follow Legrand's 1885 edition. The poem is Musurus' and the text
Legrand's; only the article's own translation and commentary are in copyright,
and neither is taken. Lines are picked out of cache/musurus_akroterion.pdf as
those that are nearly all Greek letters and at least 18 long.

English: William Roscoe, Life and Pontificate of Leo the Tenth (London 1805),
vol. 2 pp. 241-247, archive.org `lifepontificate02rosc`. Roscoe renders the
whole ode in rhymed quatrains rather than line for line, so it does not pair
with the Greek couplets one to one: the pairing is by block. The OCR's debris
is stripped: running heads ('CHAP. XI.', 'A. D. 1513.'), catchwords at the foot
of a page (a lone 'But' that begins the next page), signature marks
('H H 2') and the opening quotation marks Roscoe's speech carries on each line.

Writes input/musurus_grc.txt and input/musurus_en.txt.
"""
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).parent
PDF = HERE / "cache" / "musurus_akroterion.pdf"
ROSCOE = HERE / "cache" / "roscoe_leo_x_vol2_djvu.txt"
OUT_GRC = HERE / "input" / "musurus_grc.txt"
OUT_EN = HERE / "input" / "musurus_en.txt"

GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
HEADS = re.compile(r"^(?:CHAP\.?\s*XI\.?|A\.\s*[Dn]\.?\s*1513\.?|A\.\s*\S+\s*38\.?|[Aa]\.\s*[Dd]\.\s*1513\.?)\s+", re.I)
TAILS = re.compile(r"\s+(?:chap\.\s*xi\.?|a\.\s*d\.\s*1513\.?|A\.\s*\^?[A-Za-z]*\.?\s*[0-9sS]+\.?|\^[\"'^A-Za-z. ]*)\s*$", re.I)


def greek() -> list[str]:
    doc = fitz.open(PDF)
    out: list[str] = []
    for n in range(5, 19):                      # the ode's pages; the rest is commentary
        for ln in doc[n].get_text().splitlines():
            s = ln.strip()
            letters = [c for c in s if c.isalpha()]
            if len(letters) >= 18 and sum(bool(GREEK.match(c)) for c in letters) / len(letters) > 0.9 \
                    and not s.startswith("("):
                out.append(s)
    return out


def english() -> list[str]:
    raw = [re.sub(r"\s+", " ", l).strip() for l in ROSCOE.read_text(encoding="utf-8").splitlines()]
    start = next(i for i, l in enumerate(raw) if l.startswith("Spirit divine, who"))
    end = next(i for i, l in enumerate(raw) if i > start and l.startswith("The friend of peace, the light of human kind"))
    out: list[str] = []
    for s in raw[start:end + 1]:
        if not s or re.fullmatch(r"\d{3}", s) or re.fullmatch(r"[A-Z] ?[A-Z]? ?\d?", s):
            continue
        if re.match(r"^(VOL\.|No\.|\(a\)|A\. Pont)", s) or re.fullmatch(r"[A-Z][a-z]+", s):   # catchword
            continue
        s = re.sub(r"^H H 2 ", "", HEADS.sub("", s))
        s = re.sub(r"^A\.\s*\S{1,3}\s+\d{2,4}J?\.\s*", "", s)           # 'A. n 151J.' for 'A. D. 1513.'
        s = TAILS.sub("", s)
        s = re.sub(r"^[\"'`•»“”]+\s*", "", s)
        if re.search(r"Translation of the Greek", s) or len(s) < 8:
            continue
        out.append(s)
    return out


def main() -> int:
    g = greek()
    OUT_GRC.write_text("\n".join(g[i] + ("\n" if i % 2 else "") for i in range(len(g))), encoding="utf-8")
    e = english()
    OUT_EN.write_text("\n".join(e[i] + ("\n" if i % 4 == 3 else "") for i in range(len(e))), encoding="utf-8")
    print(f"{len(g)} Greek lines (the ode has 154); {len(e)} English lines "
          f"= {len(e) / 4:.1f} quatrains", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
