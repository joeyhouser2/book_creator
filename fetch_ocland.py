#!/usr/bin/env python
"""Prepare Ocland's Anglorum Praelia and Sharrock's 1585 English for a build.

English: the EEBO-TCP transcription A08452 (public domain since 2015), kept in
ocr-texts/. The transcription carries the damage of the microfilm it was keyed
from, in two forms:

  inline gap   <gap extent="1+ letters"/> or "1 word": a word or part of one is
               illegible. Kept as a visible "[...]" inside the line.
  lacuna       <gap extent="2+ pages"/> or "1 page" between lines: whole pages
               are missing. Nothing is written for them. The aligner then finds
               Latin with no English beside it, and `fill_missing` machine-
               translates exactly that, marked with a dagger.

Both books of Anglorum Praelia and then Elizabetha are kept, in the order the
Latin prints them. Notes and apparatus are dropped.

Latin: input/ocland_la.txt (fetch_sources.py ocland) from the 1580 edition,
from the poem's first line. Everything before it -- title page, list of kings,
dedication, commendatory verses -- is cut, so it is not machine-translated into
the middle of the book.

Writes input/ocland_la_poem.txt and input/ocland_sharrock_en.txt.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
TEI = HERE / "ocr-texts" / "ocland_sharrock_1585_eebo_tcp_A08452.xml"
LATIN = HERE / "input" / "ocland_la.txt"
OUT_LA = HERE / "input" / "ocland_la_poem.txt"
OUT_EN = HERE / "input" / "ocland_sharrock_en.txt"

POEM_STARTS = re.compile(r"^\W*\w{0,3}\s*Spe\s*ra\s+qua\s+valido")
GAP_MARK = "[...]"


def tag(e: ET.Element) -> str:
    return e.tag.split("}")[-1]


def text_of(e: ET.Element) -> str:
    """The text of a line, with gaps shown and notes and descriptions left out."""
    out = [e.text or ""]
    for c in e:
        t = tag(c)
        if t == "gap":
            out.append(f" {GAP_MARK} ")
        elif t not in ("note", "desc"):
            out.append(text_of(c))
        out.append(c.tail or "")
    return "".join(out)


def sharrock() -> tuple[list[str], int]:
    root = ET.parse(TEI).getroot()
    lines: list[str] = []
    lacunae = 0
    for div in root.iter():
        if tag(div) != "div" or div.get("type") not in ("book", "text"):
            continue
        for e in div.iter():
            t = tag(e)
            if t == "l":
                s = re.sub(r"\s+", " ", text_of(e)).strip()
                if s:
                    lines.append(s)
            elif t == "gap" and "page" in (e.get("extent") or ""):
                lacunae += 1
    return lines, lacunae


def latin() -> list[str]:
    raw = [l.strip() for l in LATIN.read_text(encoding="utf-8").splitlines() if l.strip()]
    start = next(i for i, l in enumerate(raw) if POEM_STARTS.match(l))
    return raw[start:]


def main() -> int:
    en, lacunae = sharrock()
    la = latin()
    OUT_EN.write_text("\n".join(en) + "\n", encoding="utf-8")
    OUT_LA.write_text("\n".join(la) + "\n", encoding="utf-8")
    inline = sum(GAP_MARK in l for l in en)
    print(f"Sharrock: {len(en)} lines, {inline} with an illegible gap, {lacunae} missing-page "
          f"gap(s) in the TEI (some fall in front matter); Latin: {len(la)} lines from the poem's first line",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
