#!/usr/bin/env python
"""Re-read the poem pages of Haltaus's Theuerdank with Tesseract's Fraktur model.

Google's text layer for this scan read the Fraktur as Latin type: every long s
came out as 'f' and every 'st' ligature as 'ß', so "ſchwert" became "fchwert".
The Fraktur model reads the long s correctly and keeps the two columns apart
under --psm 3, so the poem is re-read from the page images instead of repaired.

Writes cache/theuerdank/ocr/p<NNN>.txt, one file per PDF page, and skips pages already done, so an interrupted run resumes.  --psm 3
keeps the two columns apart, except on about 17 pages where it fuses a row of
the left column with the same row of the right, with a "|" between the halves.

    python ocr_theuerdank.py [lang]      # default lang: Fraktur
"""
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from book_creator import ocr  # noqa: E402

ITEM = "bub_gb_UDhTAAAAcAAJ"
URL = f"https://archive.org/download/{ITEM}/{ITEM}.pdf"
PDF = Path(__file__).parent / "cache" / "theuerdank" / "haltaus_1836.pdf"
DPI = 600  # the scan is 2500 px wide; the page is 4.2 in


def poem_pages(doc) -> range:
    """PDF pages from the first chapter to the page the key starts on."""
    first = last = None
    for i, page in enumerate(doc):
        t = page.get_text()
        if first is None and "liyrael" in t:
            first = i
        if "Dies der Schl" in t:
            last = i
            break
    if first is None or last is None:
        raise SystemExit("could not find the poem in the PDF's text layer")
    return range(first - 1, last + 1)  # one page early, for the dedication


def main() -> int:
    lang = sys.argv[1] if len(sys.argv) > 1 else "Fraktur"
    if not PDF.exists():
        PDF.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-sL", "-m", "900", "-o", str(PDF), URL], check=True)
    exe = ocr.tesseract_exe()
    doc = fitz.open(str(PDF))
    pages = poem_pages(doc)
    out_dir = PDF.parent / ("ocr" if lang == "Fraktur" else f"ocr_{lang}")
    out_dir.mkdir(exist_ok=True)
    print(f"pages {pages.start}-{pages.stop - 1} ({len(pages)}), lang {lang}", file=sys.stderr)

    def one(i: int) -> int:
        dst = out_dir / f"p{i:03d}.txt"
        if dst.exists():
            return i
        png = fitz.open(str(PDF))[i].get_pixmap(dpi=DPI, colorspace=fitz.csGRAY).tobytes("png")
        dst.write_text(ocr._run_tesseract(png, lang, exe, 3), encoding="utf-8")
        return i

    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i in ex.map(one, pages):
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(pages)}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
