#!/usr/bin/env python
"""Extract Mistral's Mireio (Provencal) from the 1861 Avignon bilingual edition.

Source: archive.org `mireillepomepr00mistuoft`, "Mireille, poeme provencal; avec la
traduction litterale en regard". Provencal stands on the left-hand page and
Mistral's own literal French on the right, so the OCR alternates:

    4  MIREIO, CANT I          <- a Provencal page: verse, one line per row
    ...
    MIREILLE, CHANT I.  5      <- a French page: prose, with ' -- ' for line breaks

Only the Provencal pages are kept. Pages are told apart by their running head
('CANT' against 'CHANT'), which the OCR garbles often enough ('MllrE.IO,
CANT L') that the head is matched loosely: a short line that starts with an M,
ends in CANT or CHANT, and carries a numeral.

Cantos are cut at the printed titles. A Provencal title the OCR lost
(SIEISEN, DESEN and ENDESEN) is found from its French twin instead (SIXIEME,
DIXIEME, ONZIEME), which sits at the same place.

Mistral's stanza is seven lines, and the OCR double-spaces its lines
unevenly, so blank lines cannot mark a stanza; the lines of each canto are
counted off in sevens instead. A canto whose count does not divide by seven is
reported, since a dropped or doubled line shifts every stanza after it.

Writes input/mireio_oc.txt and input/mireio_en.txt (Preston, PG 56008): 'CANTO n'
headings, one stanza per block.
"""
import re
import sys
from pathlib import Path

CACHE = Path(__file__).parent / "cache" / "mistral_1861_djvu.txt"
URL = "https://archive.org/download/mireillepomepr00mistuoft/mireillepomepr00mistuoft_djvu.txt"
OUT = Path(__file__).parent / "input" / "mireio_oc.txt"
OUT_EN = Path(__file__).parent / "input" / "mireio_en.txt"
PRESTON = Path(__file__).parent / "cache" / "pg56008.txt"

# First letters of each canto's title word, Provencal then French.
TITLES = {
    1: ("PROU", "PREM"), 2: ("SEGO", "DEUX"), 3: ("TRES", "TROI"), 4: ("QUAT", "QUAT"),
    5: ("CINQ", "CINQ"), 6: ("SIEI", "SIXI"), 7: ("SETE", "SEPT"), 8: ("VUEC", "HUIT"),
    9: ("NOUV", "NEUV"), 10: ("DESE", "DIXI"), 11: ("ENDE", "ONZI"), 12: ("DOUG", "DOUZ"),
}
TITLE = re.compile(r"^\W*C?H?ANT\.?\s+([A-ZÏÈÉÎ]{4})", re.I)
HEAD = re.compile(r"C(H?)ANT(?![A-Za-zà-ÿ]).{0,16}$")


def head(line: str):
    """A running head: short, mostly capitals, ending in CANT/CHANT and a numeral.
    Returns the match (group 1 is 'H' for French) or None. Verse that merely
    contains the word ('Lontems apres lou cant escoutavon') is lowercase."""
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    if len(s) > 48 or len(letters) < 8 or sum(c.isupper() for c in letters) / len(letters) < 0.6:
        return None
    return HEAD.search(s)


STANZA = 7


def canto_starts(lines: list[str]) -> dict[int, int]:
    """First line of each canto. The table of contents after the poem repeats
    the titles, so only the body (before the 'CHANT' of the table) is searched."""
    end = next((i for i, ln in enumerate(lines) if i > 12000 and re.match(r"^\s*CHANT\s*$", ln)), len(lines))
    starts: dict[int, int] = {}
    for i, ln in enumerate(lines[:end]):
        m = TITLE.match(ln.strip())
        if not m:
            continue
        word = m.group(1).upper().replace("Ï", "I")
        for n, keys in TITLES.items():
            if word[:4] in keys and n not in starts:
                starts[n] = i
    return starts


PROV = set("lou li lis dins emé em pèr soun uno èro èi dôu dóu di dis mai noun aquelo aquéu aquéli vese "
           "fai sus eu éu quand pièi tout toutes touto lèu ounte ounto sian sias vèn mounte".split())
FRENCH = set("le les des dans et que qui elle il est sont avec pour sur ses son ce cette une du où était "
             "fit dit lui leur nous vous je tu mon ma mes ne pas ni comme mais alors aux".split())


def is_provencal(s: str) -> bool:
    """Whether a line is Provencal verse rather than French prose or a head.

    Running heads are too garbled to sort pages by, so each line is sorted on
    its own: Provencal function words against French ones, and the shape of the
    line -- the French is justified prose, long, with ' -- ' for each verse
    break, where a line of verse is short.
    """
    if " — " in s or " -- " in s or s.endswith(("—", "-")) and len(s) > 40:
        return False
    words = re.findall(r"[a-zàâçèéêëîïôûù']+", s.lower())
    ps = sum(w.split("'")[-1] in PROV or w in PROV for w in words)
    fs = sum(w in FRENCH for w in words)
    if len(s) >= 46:
        return ps > fs + 1
    if ps or fs:
        return ps >= fs
    return len(s) >= 14           # no evidence either way: a short line of verse


def provencal(lines: list[str]) -> list[str]:
    """The verse lines of `lines`, with heads, numbers and French prose removed."""
    out: list[str] = []
    for ln in lines:
        s = re.sub(r"\s+", " ", ln.strip())
        if not s or head(s) or re.fullmatch(r"[\W\d]{0,6}", s):
            continue
        if is_provencal(s):
            out.append(s)
    return out


def preston() -> str:
    """Preston's 1872 English, in its own 6-line stanzas, one CANTO heading each."""
    raw = PRESTON.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    n = 0
    for ln in raw:
        if re.match(r"^CANTO [IVXL]+\.$", ln) and n < 12 and raw.index(ln) > 450:
            n += 1
            out += ["", f"CANTO {n}", ""]
            continue
        if n == 0 or ln.startswith("***") or "Gresham Press" in ln:
            if "Gresham Press" in ln:
                break
            continue
        if re.match(r"^_.*_$", ln.strip()):        # the canto's italic subtitle
            continue
        if ln.strip().startswith("*  "):           # a section break
            continue
        out.append(ln.strip() if ln.startswith("    ") else "")
    return "\n".join(out)


def main() -> int:
    if not CACHE.exists():
        import subprocess
        CACHE.parent.mkdir(exist_ok=True)
        subprocess.run(["curl", "-sL", "-m", "300", "-o", str(CACHE), URL], check=True)
    lines = CACHE.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = canto_starts(lines)
    missing = [n for n in TITLES if n not in starts]
    if missing:
        print(f"no title found for canto(s) {missing}", file=sys.stderr)
        return 1
    order = sorted(starts.items())
    out: list[str] = []
    for k, (n, at) in enumerate(order):
        stop = order[k + 1][1] if k + 1 < len(order) else len(lines)
        verse = provencal(lines[at:stop])
        stanzas = [verse[i:i + STANZA] for i in range(0, len(verse), STANZA)]
        flag = "" if len(verse) % STANZA == 0 else f"  <-- {len(verse) % STANZA} line(s) over"
        print(f"canto {n:>2}: {len(verse):>4} lines = {len(stanzas):>3} stanzas{flag}", file=sys.stderr)
        out += ["", f"CANTO {n}", ""]
        for st in stanzas:
            out += st + [""]
    OUT.write_text("\n".join(out), encoding="utf-8")
    OUT_EN.write_text(preston(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
