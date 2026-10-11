#!/usr/bin/env python
"""Extract Anastasius Grün's *Der letzte Ritter* (1830) from Projekt Gutenberg-DE.

Source: projekt-gutenberg.org/authors/anton-alexander-graf-von-auersperg/books/
der-letzte-ritter, 21 divisions: the dedication, a prologue, 18 Romanzen
(Maximilian I from cradle to grave) and an epilogue.

On the page each stanza is a <p> inside a <table class="poem">, its lines
separated by <br />. Footnotes, mottos and the author's historical notes sit in
cells classed "note"; the note to a Romanze's title is carried in its heading
element, and those are dropped here (the notes are prose, in German, and a
machine translation would make a poor job of them).

Writes input/letzte_ritter_de.txt: "Kapitel N. <title>" per division (the site's
title page has no verse and is skipped, so N runs 1-20), stanzas
separated by blank lines, so the pipeline's heading detection finds each one.
"""
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "gruen" / "lr"
OUT = ROOT / "input" / "letzte_ritter_de.txt"
BASE = ("https://projekt-gutenberg.org/authors/anton-alexander-graf-von-auersperg/"
        "books/der-letzte-ritter/chapter/")
N = 21


def _page(i: int) -> str:
    path = CACHE / f"c{i}.html"
    if not path.exists():
        import requests
        CACHE.mkdir(parents=True, exist_ok=True)
        r = requests.get(BASE + str(i), timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path.read_text(encoding="utf8", errors="replace")


def _clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def chapter(i: int) -> tuple[str, list[str]]:
    t = _page(i)
    m = re.search(r'<h2 class="book-reader__chapter-heading">(.*?)</h2>', t, re.S)
    title = _clean(m.group(1)) if m else ""
    body = re.search(r'<div class="book-reader__chapter-text">(.*?)</main>', t, re.S)
    body = body.group(1) if body else ""
    stanzas = []
    for tbl in re.findall(r'<table class="poem">.*?</table>', body, re.S):
        for td in re.findall(r"<td(?: [^>]*)?>(.*?)</td>", tbl, re.S):
            if re.search(r"<td[^>]*class=\"note", tbl) and "<p>" not in td:
                continue
            for p in re.findall(r"<p>(.*?)</p>", td, re.S):
                txt = _clean(p)
                if txt:
                    stanzas.append(txt)
    return title, stanzas


def main() -> None:
    out = []
    total = 0
    number = 0
    for i in range(1, N + 1):
        title, stanzas = chapter(i)
        # A long title is a short one plus the editor's historical note.
        short = title.split(".")[0].strip() if len(title) > 60 else title
        print(f"{i:2d} {short[:40]!r}: {len(stanzas)} stanzas", file=sys.stderr)
        if not stanzas:
            continue
        number += 1
        # The site's second division carries no title of its own: it is the
        # author's verse preface "In unsern weichen, seid'nen Zeiten".
        if re.fullmatch(r"Kapitel \d+", short):
            short = "Vorwort"
        out.append(f"Kapitel {number}. {short}".rstrip(". ") + ".")
        out.append("")
        for s in stanzas:
            out.append(s)
            out.append("")
            total += 1
    OUT.write_text("\n".join(out), encoding="utf8")
    print(f"wrote {OUT} ({total} stanzas)", file=sys.stderr)


if __name__ == "__main__":
    main()
