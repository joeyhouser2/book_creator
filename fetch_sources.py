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
# A line that is only a stanza number, in either numbering.
_NUM_ONLY = re.compile(r"^[\[(]?(?:\d{1,4}|[IVXLCDM]{1,7})[\])]?\.?$")
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


def lusiadas_en() -> None:
    """Burton's Lusiads, English, 10 cantos (Gutenberg 77660 + 77661).

    Assembled rather than used as fetched. Burton's two volumes interleave each
    canto's verse with its prose argument and its endnotes, all three titled
    "CANTO N.", so the verse bodies are not a contiguous range and --tgt-range
    cannot isolate them. For each canto the LARGEST division with that title is
    the verse -- the argument runs about 1,300 characters against the verse's
    40,000 -- which also sidesteps picking the right one by position.

    Worth the trouble because Burton kept Camoes' ottava rima, 8 lines to the
    stanza, so this pairs stanza for stanza against the Portuguese. Mickle's
    translation (32528) is one clean file but renders the whole poem in running
    heroic couplets, which can only pair canto against canto.
    """
    from book_creator import fetch, segment

    want = re.compile(r"^CANTO\s+([IVX]+)\.?$", re.I)
    best: dict[int, str] = {}
    for gid in (77660, 77661):
        text = fetch.strip_gutenberg_boilerplate(fetch.fetch_gutenberg(gid))
        for title, body in segment.detect_chapters(text, mode="verse"):
            m = want.match(title.strip())
            if not m:
                continue
            n = ROMAN.index(m.group(1).upper()) + 1
            if len(body) > len(best.get(n, "")):
                best[n] = body
    if sorted(best) != list(range(1, 11)):
        raise SystemExit(f"expected cantos 1-10, found {sorted(best)}")
    parts = [f"Canto {ROMAN[n - 1]}\n\n" + best[n].strip() for n in range(1, 11)]
    _write("lusiadas_en.txt", parts, "Os Lusiadas, Burton's English")


def gerusalemme() -> None:
    """Tasso's Gerusalemme Liberata: Italian (it.wikisource) and Fairfax's
    English (Gutenberg 392), both as 20 cantos.

    Both sides are assembled rather than used as fetched. Fairfax numbers every
    one of his ~1,900 stanzas with a bare roman numeral on its own line, which
    the division detector reads as a chapter marker -- the file comes through as
    1,925 divisions instead of 20. And his ARGUMENT is a verse summary he wrote
    himself, with no counterpart in Tasso, so leaving it in would offset every
    stanza pairing in the canto.

    Worth it because Fairfax translated into Tasso's own ottava rima, so the two
    sides pair stanza for stanza.
    """
    from book_creator import fetch

    # Italian. The index links are absolute URLs, not /wiki/ paths.
    s = _session()
    idx = s.get("https://it.wikisource.org/wiki/Gerusalemme_liberata", timeout=60)
    idx.encoding = "utf-8"
    links = []
    for href in re.findall(r'href="(https://it\.wikisource\.org/wiki/'
                           r'Gerusalemme_liberata/Canto_[^"#]+)"', idx.text):
        if href not in links:
            links.append(href)
    if len(links) != 20:
        raise SystemExit(f"expected 20 cantos, found {len(links)} - site changed?")

    it_parts = []
    for n, href in enumerate(links, 1):
        r = s.get(href, timeout=60)
        r.encoding = "utf-8"
        # Each ottava is its own <div class="poem">, its lines separated by
        # <br/>. Matching those divs with a non-greedy </div> does not work --
        # they contain nested divs and spans, so the match ends early and most
        # stanzas come back as a line or two. Instead the DIV END becomes a
        # blank line, which is exactly the stanza boundary segment.stanzas()
        # looks for. Without it a whole canto reads as one 1,200-line stanza.
        m = (re.search(r'(?s)<div class="prp-pages-output"[^>]*>(.*?)<div class="printfooter"', r.text)
             or re.search(r'(?s)<div class="mw-parser-output">(.*?)<div class="printfooter"', r.text))
        frag = re.sub(r"(?is)<(script|style|table|sup).*?</\1>", "", m.group(1))
        frag = re.sub(r"(?is)</div>", "\n\n", frag)
        frag = re.sub(r"(?is)<br\s*/?>|</p>|</dd>|</li>", "\n", frag)
        text = html.unescape(_TAG.sub("", frag))
        stanzas, cur = [], []
        for raw in text.splitlines():
            line = raw.replace("\xa0", " ").strip()
            if not line:
                if len(cur) >= 2:
                    stanzas.append("\n".join(cur))
                cur = []
                continue
            if (_NUM_ONLY.match(line)
                    or re.match(r"(?i)^(canto\b|gerusalemme|torquato|indice)", line)
                    or "djvu" in line):
                continue
            # Wikisource's every-fourth-line numbering ({{R|20}}) renders hard
            # against the first word, so the verse arrives as "20I più schivi".
            # Only strip a number that runs straight into a capital: a digit
            # followed by a space could be the poet's own.
            line = re.sub(r"^\d{1,4}(?=[A-ZÀ-Þ])", "", line)
            cur.append(line)
        if len(cur) >= 2:
            stanzas.append("\n".join(cur))
        if len(stanzas) < 50:
            raise SystemExit(f"canto {n}: only {len(stanzas)} stanzas found")
        it_parts.append(f"Canto {ROMAN[n - 1]}" + "\n\n" + "\n\n".join(stanzas))
        time.sleep(0.4)
    _write("gerusalemme_it.txt", it_parts, "Gerusalemme Liberata (Italian)")

    # English: split Fairfax on "<ORDINAL> BOOK", dropping each argument.
    b = fetch.strip_gutenberg_boilerplate(fetch.fetch_gutenberg(392))
    marks = list(re.finditer(r"(?m)^[ \t]*([A-Z]+)\s+BOOK[ \t]*$", b))
    if len(marks) != 20:
        raise SystemExit(f"expected 20 Fairfax books, found {len(marks)}")
    en_parts = []
    for k, m in enumerate(marks):
        body = b[m.end(): marks[k + 1].start() if k + 1 < len(marks) else len(b)]
        a = re.search(r"(?mi)^\s*THE ARGUMENT\.?\s*$", body)
        if a:
            after = body[a.end():]
            n = re.search(r"(?m)^\s*[IVXLCDM]{1,7}\.?\s*$", after)
            body = after[n.start():] if n else after
        # Fairfax's bare roman stanza numbers read as 1,904 chapter headings
        # otherwise, because a line that is only a roman numeral is exactly how
        # some editions DO mark a division.
        kept = [l for l in body.splitlines() if not _NUM_ONLY.match(l.strip())]
        en_parts.append(f"Canto {ROMAN[k]}" + "\n\n" + "\n".join(kept).strip())
    _write("gerusalemme_en.txt", en_parts, "Gerusalemme Liberata (Fairfax's English)")


def maldon() -> None:
    """The Battle of Maldon: Old English (en.wikisource, Bright's Reader) and
    Garnett's line-for-line English (Gutenberg 15879).

    Garnett's volume prints five poems, and its contents list repeats every
    title, so "BYRHTNOTH, OR THE FIGHT AT MALDON" matches twice before the poem
    itself; the text runs from the last such heading to "THE DREAM OF THE ROOD",
    and his numbered notes at the foot are not verse.

    The poem survives without its opening, which is why both sides begin
    mid-sentence ("brocen wurde" / "was broken").
    """
    from book_creator import fetch

    # Old English. The naive tag regex leaks Parsoid's data-mw attribute, which
    # carries the page's whole wikitext -- see _TAG.
    s = _session()
    r = s.get("https://en.wikisource.org/wiki/Bright%27s_Anglo-Saxon_Reader/"
              "The_Battle_of_Maldon", timeout=60)
    r.encoding = "utf-8"
    m = re.search(r'(?s)<div[^>]*id="mw-content-text".*?>(.*?)<div class="printfooter"', r.text)
    frag = re.sub(r"(?is)<(script|style|table|sup).*?</\1>", "", m.group(1))
    frag = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>", "\n", frag)
    lines = [l.replace("\xa0", " ").strip()
             for l in html.unescape(_TAG.sub("", frag)).splitlines()]
    lines = [l for l in lines if l]
    # The verse is bounded by lines carrying Old English letters, but five lines
    # INSIDE it carry none ("folc and foldan; feallan sceolon"), so the letters
    # locate the region and everything within it is kept. The poem survives
    # without its opening, which Bright marks "[...] brocen wurde;" -- that is
    # the first line, and it sits just outside the lettered region.
    letters = re.compile(r"[þðæāēīōūȳǣ]")
    first = next(i for i, l in enumerate(lines) if letters.search(l))
    last = len(lines) - 1 - next(i for i, l in enumerate(reversed(lines))
                                 if letters.search(l))
    opening = first - 1
    if opening >= 0 and lines[opening].startswith("[..."):
        first = opening
    oe = [re.sub(r"\s{2,}", "   ", re.sub(r"^\[\.\.\.\]\s*", "", l))
          for l in lines[first:last + 1]]
    if len(oe) < 320:
        raise SystemExit(f"expected ~325 Old English lines, got {len(oe)}")
    _write("maldon_ang.txt", ["The Battle of Maldon" + "\n\n" + "\n".join(oe)],
           "The Battle of Maldon (Old English)")

    # Garnett's English.
    b = fetch.strip_gutenberg_boilerplate(fetch.fetch_gutenberg(15879))
    marks = list(re.finditer(r"(?m)^[ \t]*THE FIGHT AT MALDON\.?\s*$", b))
    end = re.search(r"(?m)^[ \t]*THE DREAM OF THE ROOD\.?\s*$", b[marks[-1].end():])
    body = b[marks[-1].end(): marks[-1].end() + end.start()]
    en, seen_verse = [], False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\[\d+\]", line):      # his notes begin; the verse is done
            break
        if not seen_verse:
            # Skip the prose argument that precedes the verse.
            if line.startswith("*"):
                seen_verse = True
            else:
                continue
        en.append(re.sub(r"\s{2,}", " ", line))
    if len(en) < 300:
        raise SystemExit(f"expected ~325 English lines, got {len(en)}")
    _write("maldon_en.txt", ["The Battle of Maldon" + "\n\n" + "\n".join(en)],
           "The Battle of Maldon (Garnett's English)")


def africa() -> None:
    """Petrarch's Africa, Latin, 9 books (poetiditalia.it, Festa's text).

    The poem Petrarch was crowned laureate for, and the one almost nobody
    reads. No English translation is in the public domain -- Bergin and
    Wilson's 1977 Yale version is still in copyright -- so this is the
    original alone, for the machine-translation path to face.

    Each verse line is its own <p class="c_v">, which is as clean as these
    sources get: no stanza numbering to strip and no apparatus mixed into the
    verse.
    """
    s = _session()
    parts = []
    for n in range(1, 10):
        r = s.get(f"https://www.poetiditalia.it/texts/PETRARCA|afri|{n:03d}", timeout=60)
        r.encoding = "utf-8"
        lines = [html.unescape(_TAG.sub("", m)).replace("\xa0", " ").strip()
                 for m in re.findall(r'(?s)<p class="c_v">(.*?)</p>', r.text)]
        lines = [l for l in lines if l]
        if len(lines) < 100:
            raise SystemExit(f"book {n}: only {len(lines)} verse lines found")
        parts.append(f"Liber {ROMAN[n - 1]}" + "\n\n" + "\n".join(lines))
        time.sleep(0.4)
    _write("africa_la.txt", parts, "Petrarch's Africa (Latin)")


SOURCES = {"parzival": parzival, "henriade": henriade, "messias": messias,
           "lusiadas_en": lusiadas_en,
           "gerusalemme": gerusalemme,
           "maldon": maldon,
           "africa": africa}


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
