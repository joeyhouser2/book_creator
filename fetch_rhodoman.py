#!/usr/bin/env python
"""Extract Rhodoman's verse from the pages of rhodomanologia.de.

Source: the site's own HTML (cache/rhodoman/html/, downloaded with curl; the
site's EPUB export leaves out several works, among them the Arion). Each work is
one TEI-rendered page whose verse lines look like

    <span class="l">
      <span class="main-grc">Greek text of the line ...</span>
      <span class="appMetric-grc">scansion</span>
      <span class="transMain-de">the editors' German translation</span>
      <span class="app">apparatus</span>
    </span>

Only the original-language text of each line is taken, from `main-grc` (Greek)
or `main-la` (Latin). The German translation and the apparatus are the
editors' own work and are left out; so are the metrical scansion and the
margin notes. The licence of the site is unresolved (see WANTED.md), so these
files stay in the working tree for translation and are not a release.

Writes input/rhodoman/<slug>_<lang>.txt, one verse line per row, and
input/rhodoman/index.tsv (slug, language, lines, title).
"""
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).parent
SRC = HERE / "cache" / "rhodoman" / "html"
OUT = HERE / "input" / "rhodoman"
MIN_LINES = 40                      # a page of fewer verse lines is a fragment, not a work


def text_of(span) -> str:
    for junk in span.select(".appMetric-grc, .appMetric-la, .label, .marg-grc, .marg-la, .app"):
        junk.decompose()
    return re.sub(r"\s+", " ", span.get_text(" ")).strip()


def verse(soup: BeautifulSoup, lang: str) -> list[str]:
    cls = "main-grc" if lang == "grc" else "main-la"
    out: list[str] = []
    for line in soup.select("span.lg span.l"):
        span = line.find("span", class_=cls, recursive=False)
        if span is not None:
            s = text_of(span)
            s = re.sub(r"\s+([,.;:·!?])", r"\1", s)
            if s:
                out.append(s)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[str] = []
    for page in sorted(SRC.glob("*.html")):
        soup = BeautifulSoup(page.read_text(encoding="utf-8", errors="replace"), "lxml")
        h1 = soup.find("h1")
        title = re.sub(r"\s+", " ", h1.get_text(" ")).strip() if h1 else page.stem
        for lang in ("grc", "la"):
            lines = verse(soup, lang)
            if len(lines) >= MIN_LINES:
                slug = page.stem
                (OUT / f"{slug}_{lang}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                index.append(f"{slug}\t{lang}\t{len(lines)}\t{title}")
                print(f"{slug:<28} {lang:<3} {len(lines):>5} lines  {title[:60]}", file=sys.stderr)
    (OUT / "index.tsv").write_text("\n".join(index) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
