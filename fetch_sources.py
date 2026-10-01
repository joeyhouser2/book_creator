#!/usr/bin/env python
"""Fetch public-domain originals that Gutenberg does not have, into input/.

    python fetch_sources.py            # everything
    python fetch_sources.py henriade   # one source

Gutenberg covers almost none of the Franco-Germanic verse epics: of the obvious
candidates it has the Nibelungenlied's German beside three English translations
and then stops. The originals below come from elsewhere, and each one needed
something undoing before it could be built -- which is why this is a script and
not a note. Every quirk here cost a wrong book first:

* Bibliotheca Augustana serves UTF-8 but writes Middle High German diacritics as
  HTML entities (`&icirc;` for î), so a naive `apparent_encoding` guess mangles
  every long vowel. Its verse is in <h3> and its line numbers in <h6>, so the
  numbers come off cleanly rather than being glued to the verse ("5unverzaget").

* fr.wikisource's Henriade sets each chant's real heading in caps above the
  verse, with its own page title in mixed case ABOVE that -- anchoring on the
  word "Chant" finds the wrong one. Worse, chant 4's heading is scanned as
  "CHANR QUATRIÈME", so anchoring on the word at all silently drops a whole
  canto. Anchor on the metadata blob that ends the chrome instead. Voltaire's
  footnotes sit at the foot of each chant and only their FIRST line carries the
  ↑ backlink, so dropping ↑ lines alone leaves every continuation behind as
  apparent verse.

* zeno.org declares **iso-8859-1**. Decoding it as UTF-8 turns every umlaut into
  a replacement character -- "sündigen" becomes "s?ndigen" -- and the build logs
  nothing, so the first Messias came out corrupted and looked fine. Its
  bracketed numerals are two different things: [53] is the 1879 edition's
  running page number and [68] a footnote reference. Both are stripped
  everywhere, not just at line starts, or the footnote markers end up
  machine-translated as part of the hexameter.

The texts themselves are not committed (see .gitignore: source texts are inputs,
not code). Re-run this to get them back.
"""

from __future__ import annotations

import html
import re
import sys
import time
from pathlib import Path

import requests

# This script's whole job is non-ASCII text, and a Windows console defaults to
# cp1252 — which raised UnicodeEncodeError on the "✓" of the first success
# message, after the file had already been written, so the run died looking like
# a fetch failure. Reconfigure rather than drop the characters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

OUT = Path("input")
AGENT = "book_creator/1.0 (personal public-domain text collection)"
ROMAN = ("I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII "
         "XIX XX").split()


# A tag, with quoted attribute values treated as opaque. The naive `<[^>]+>`
# stops at the first ">" INSIDE an attribute, which matters because Wikisource
# serves Parsoid markup whose data-mw attributes carry the page's raw wikitext --
# <ref> footnotes, {{templates}}, escaped newlines and all. With the naive
# pattern the tail of each attribute leaked out as if it were verse, doubling
# the Henriade and salting it with wikitext that still looked French.
_TAG = re.compile(r"""<[a-zA-Z/!?][^>"']*(?:(?:"[^"]*"|'[^']*')[^>"']*)*>""")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = AGENT
    return s


def _strip_tags(fragment: str, *, drop: str, split: str) -> list[str]:
    """Visible lines of an HTML fragment, entities resolved.

    `drop` and `split` are per-source on purpose. Unifying them into one shared
    set looked like tidying and silently broke the Henriade: adding <h4> to the
    dropped elements removed a line, which shifted the index of the metadata
    blob the chrome anchor counts from, so the chrome stayed in AND the footnote
    cut missed — a file twice the right size that still looked like French verse.
    These two strings are the ones each source was actually verified against.
    """
    fragment = re.sub(rf"(?is)<({drop}).*?</\1>", "", fragment)
    fragment = re.sub(rf"(?is){split}", "\n", fragment)
    text = html.unescape(_TAG.sub("", fragment))
    return [l.replace("\xa0", " ").strip() for l in text.splitlines() if l.strip()]


def _write(name: str, parts: list[str], label: str) -> None:
    text = "\n\n\n".join(parts) + "\n"
    path = OUT / name
    path.write_text(text, encoding="utf-8")
    lines = sum(1 for l in text.splitlines() if l.strip())
    print(f"✓ {label}: {lines:,} lines, {len(text):,} chars → {path}")


# --------------------------------------------------------------------------- #
def parzival() -> None:
    """Wolfram's Parzival, Middle High German, 16 books (Bibliotheca Augustana)."""
    s = _session()
    base = ("https://www.tha.de/~harsch/germanica/Chronologie/13Jh/Wolfram/"
            "wol_pa{:02d}.html")
    parts = []
    for n in range(1, 17):
        # Explicit utf-8: letting requests guess mangles every î/â/æ.
        page = s.get(base.format(n), timeout=90).content.decode("utf-8")
        # Verse is <h3>; the <h6> cells hold Lachmann's line numbers.
        verse = [html.unescape(re.sub(r"<[^>]+>", "", m)).strip()
                 for m in re.findall(r"(?s)<h3[^>]*>(.*?)</h3>", page)]
        parts.append(f"Buch {ROMAN[n - 1]}\n\n" + "\n".join(v for v in verse if v))
        time.sleep(0.4)
    _write("parzival_mhg.txt", parts, "Parzival (Middle High German)")


def henriade() -> None:
    """Voltaire's La Henriade, French, 10 chants (fr.wikisource)."""
    s = _session()
    parts = []
    for n in range(1, 11):
        r = s.get(f"https://fr.wikisource.org/wiki/La_Henriade/Chant_{n}", timeout=60)
        r.encoding = "utf-8"
        m = (re.search(r'(?s)<div class="prp-pages-output"[^>]*>(.*?)<div class="printfooter"', r.text)
             or re.search(r'(?s)<div class="mw-parser-output">(.*?)<div class="printfooter"', r.text))
        lines = _strip_tags(m.group(1), drop="script|style|table|sup",
                            split=r"<br\s*/?>|</p>|</div>|</dd>|</li>")
        blob = next(i for i, l in enumerate(lines) if "djvu" in l)
        body = lines[blob + 2:]                 # +2 also drops the heading line
        cut = next((i for i, l in enumerate(body) if l.startswith("↑")), len(body))
        body = [l for l in body[:cut] if not re.match(r"(?i)^(variantes|◄|►)", l)]
        parts.append(f"Chant {ROMAN[n - 1]}\n\n" + "\n".join(body))
        time.sleep(0.4)
    _write("henriade_fr.txt", parts, "La Henriade (French)")


def messias() -> None:
    """Klopstock's Der Messias, German, 20 cantos (zeno.org, Berlin 1879)."""
    s = _session()
    root = ("http://www.zeno.org/Literatur/M/Klopstock,+Friedrich+Gottlieb/"
            "Gedichte/Der+Messias")

    def get(url: str) -> str:
        return s.get(url, timeout=90).content.decode("iso-8859-1")

    links, seen = [], set()
    for href in re.findall(r'href="(/Literatur/M/Klopstock[^"]*Gesang[^"]*)"', get(root)):
        if href not in seen:
            seen.add(href)
            links.append(href)
    if len(links) != 20:
        raise SystemExit(f"expected 20 cantos, found {len(links)} — site changed?")

    bracket = re.compile(r"\[\d+\]")     # page numbers AND footnote references
    parts = []
    for n, href in enumerate(links, 1):
        page = get("http://www.zeno.org" + href)
        m = (re.search(r'(?s)<div class="zenoCOMain">(.*?)</div>\s*<div', page)
             or re.search(r"(?s)<body[^>]*>(.*?)</body>", page))
        body = []
        for line in _strip_tags(m.group(1), drop="script|style|h4|table",
                                split=r"<br\s*/?>|</p>|</div>|</li>"):
            line = re.sub(r"\s{2,}", " ", bracket.sub("", line)).strip()
            if (line and "zeno.org" not in line.lower()
                    and not line.startswith("Klopstock:")
                    and not re.fullmatch(r"\w+ Gesang", line)):
                body.append(line)
        parts.append(f"Gesang {ROMAN[n - 1]}\n\n" + "\n".join(body))
        time.sleep(0.45)
    _write("messias_de.txt", parts, "Der Messias (German)")


SOURCES = {"parzival": parzival, "henriade": henriade, "messias": messias}


def main(argv: list[str]) -> int:
    OUT.mkdir(exist_ok=True)
    wanted = argv or list(SOURCES)
    unknown = [w for w in wanted if w not in SOURCES]
    if unknown:
        print(f"Unknown source(s): {', '.join(unknown)}. "
              f"Known: {', '.join(SOURCES)}.", file=sys.stderr)
        return 2
    for name in wanted:
        print(f"• Fetching {name}…")
        SOURCES[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
