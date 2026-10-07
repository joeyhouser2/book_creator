#!/usr/bin/env python
"""Extract the Poema de mio Cid (Old Spanish) and Rose's English, laisse by laisse.

Spanish: Menendez Pidal, Cantar de Mio Cid: texto, gramatica y vocabulario,
vol. 3 (Madrid 1911), archive.org `CantarDeMioCidMenend3`. It is the critical
edition, so the verse is surrounded by margin headings, variant notes at the
foot of each page and Pidal's apparatus. They are told apart by shape:

    verse        one line each, 26-76 characters
    margin head  a few words, well under 33 characters
    notes        long running prose, from a line like '3573. Restori ...' or
                 '1 <<grado>> en la Cron ...' to the next page break

Laisses are NOT numbered in this edition, and are not set off by anything the
OCR keeps -- a laisse is a run of verses on one assonance. So they are cut by
measuring it: the vowels from the last stressed syllable of each verse's last
word ('adelinado' and 'desheredados' are both a-o), with i/e and u/o merged in
the final syllable as Old Spanish assonance does. A new laisse opens where
three of the next four verses agree on a different assonance, so one verse the
OCR spoiled does not split a laisse.

English: Rose's 1919 translation (Gutenberg #6088) numbers its laisses in Roman
numerals (I ... CLII), under three cantares. The Spanish is cut into the same
three divisions at the laisse where Rose's cantares begin.

Writes input/cid_es.txt and input/cid_en.txt: 'Canto n' headings, one laisse
per block.
"""
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "cache" / "cid_pidal_vol3_djvu.txt"
URL = "https://archive.org/download/CantarDeMioCidMenend3/Cantar_de_Mio_Cid_Menend_3_djvu.txt"
ROSE = HERE / "cache" / "pg6088.txt"
OUT_ES = HERE / "input" / "cid_es.txt"
OUT_EN = HERE / "input" / "cid_en.txt"

FIRST = "Comienza el"          # 'Comienza el manuscrito de Per Abbat': verse 1 follows
LAST_VERSE = 3730
# The margin numbers stop reading before the end (the last page is mostly notes),
# so the poem is cut where the final page's verses end: line 24,110 of the djvu
# text, just above the note on v. 3726 and the apparatus that follows it.
POEM_END = 24110
MIN_LAISSE = 5

PAGEBREAK = re.compile(r"Digitized by|Original from|UNIVERSITY OF MICHIGAN", re.I)
NOTE_START = re.compile(r"^\d{1,4}[.,]\s+\S|^\d\s+[«(\[<»]")
APPARATUS = re.compile(r"Cr[oó]n|edic|\bms\b|p\.\s*\d|cap\.|Nac\.|fol\.|Restori|Bello|Lidforss|Staaff")
LABEL = re.compile(r"^(\d{2,4})\s+(?=\S)")
STRONG, WEAK = "aeo", "iu"


def verses(lines: list[str]) -> list[str]:
    start = next(i for i, l in enumerate(lines) if FIRST in l) + 3
    out: list[str] = []
    in_note = False
    for s in lines[start:POEM_END]:
        if PAGEBREAK.search(s):
            in_note = False
            continue
        if not s or in_note:
            continue
        if NOTE_START.match(s) and len(s) >= 40:
            in_note = True
            continue
        m = LABEL.match(s)
        label = int(m.group(1)) if m else 0
        if m:
            s = s[m.end():]
        letters = [c for c in s if c.isalpha()]
        shouting = letters and sum(c.isupper() for c in letters) / len(letters) > 0.5   # running heads
        if 26 <= len(s) <= 76 and not shouting and not APPARATUS.search(s):
            out.append(clean(s))
        if LAST_VERSE <= label <= LAST_VERSE + 20 and label % 5 == 0:
            break              # the margin number of the last verse; a stray year is not
    return out


def clean(s: str) -> str:
    s = re.sub(r"[»>\s]+$", "", re.sub(r"^[•»«<>*€\s]+", "", s))            # quotation marks the OCR turned to bullets
    s = re.sub(r"[\s*]+\d{0,2}$", "", s)             # a footnote call-out
    return re.sub(r"\s+([,.;:!?])", r"\1", s.replace(" *", "")).strip()


def assonance(verse: str) -> str:
    """Vowels from the last stressed syllable of the verse's last word."""
    words = re.findall(r"[^\W\d_]+", verse)
    if not words:
        return ""
    w = words[-1].lower()
    plain = unicodedata.normalize("NFD", w)
    accented = {c for c in plain if c == "́"}
    base = "".join(c for c in plain if not unicodedata.combining(c))
    ends_in_s = base.endswith("s") and len(base) > 3
    if ends_in_s:
        base = base[:-1]
    # nuclei: runs of vowels, a diphthong counting as its strong vowel
    nuclei = [m.group() for m in re.finditer(r"[aeiou]+", base)]
    def head(n: str) -> str:
        strong = [c for c in n if c in STRONG]
        return strong[0] if strong else n[-1]
    vowels = [head(n) for n in nuclei]
    if not vowels:
        return ""
    if w[-1] in "áéíóú" or (ends_in_s and w[-2:-1] in ("á", "é", "í", "ó", "ú")):
        pat = vowels[-1:]                          # a written accent on the last vowel: stress falls there
    elif base[-1] in "aeiou":
        pat = vowels[-2:] if len(vowels) >= 2 else vowels
    else:
        pat = vowels[-1:]                          # ends on a consonant: stress on the last syllable
    pat = [{"i": "e", "u": "o"}.get(pat[-1], pat[-1]) if k == len(pat) - 1 and len(pat) > 1 else v
           for k, v in enumerate(pat)]
    return "-".join(pat)


def laisses(vs: list[str]) -> list[list[str]]:
    pats = [assonance(v) for v in vs]
    out: list[list[str]] = []
    cur: list[str] = []
    cur_pat = None
    for i, v in enumerate(vs):
        p = pats[i]
        if cur_pat is None:
            cur_pat = p
        elif p != cur_pat:
            window = Counter(pats[i:i + 4])
            new, n = window.most_common(1)[0]
            if new != cur_pat and n >= 3 and p == new:
                out.append(cur)
                cur, cur_pat = [], new
        cur.append(v)
    if cur:
        out.append(cur)
    # A "laisse" of a few verses is a patch of OCR damage, or a stray rhyme in a
    # longer one: fold it into the laisse before it.
    merged: list[list[str]] = []
    for lz in out:
        if merged and len(lz) < MIN_LAISSE:
            merged[-1].extend(lz)
        else:
            merged.append(lz)
    return merged


def rose() -> tuple[list[str], list[int]]:
    """Rose's laisses as blocks, and the laisse index each cantar opens at."""
    raw = ROSE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(raw) if l.strip() == "CANTAR I")
    blocks: list[list[str]] = []
    opens: list[int] = []
    for ln in raw[start:]:
        s = ln.strip()
        if "END OF THE PROJECT GUTENBERG" in s:
            break
        if re.fullmatch(r"CANTAR (I|II|III)", s):
            opens.append(len(blocks))
            continue
        m = re.fullmatch(r"([IVXLC]+)\.", s)
        if m:
            blocks.append([])
            continue
        if blocks and s and not s.isupper():
            blocks[-1].append(s)
    return ["\n".join(b) for b in blocks if b], opens


def main() -> int:
    if not SRC.exists():
        import subprocess
        SRC.parent.mkdir(exist_ok=True)
        subprocess.run(["curl", "-sL", "-m", "300", "-o", str(SRC), URL], check=True)
    lines = [re.sub(r"\s+", " ", l).strip() for l in SRC.read_text(encoding="utf-8", errors="replace").splitlines()]
    vs = verses(lines)
    ls = laisses(vs)
    en, opens = rose()
    print(f"{len(vs)} verses (the poem has 3,730); {len(ls)} laisses cut by assonance; "
          f"Rose has {len(en)} laisses, cantares opening at laisse {[o + 1 for o in opens]}", file=sys.stderr)

    def write(path: Path, blocks: list[str], cuts: list[int]) -> None:
        out: list[str] = []
        for i, b in enumerate(blocks):
            if i in cuts:
                out += ["", f"CANTO {cuts.index(i) + 1}", ""]
            out += [b, ""]
        path.write_text("\n".join(out), encoding="utf-8")

    # Our laisse count differs from Rose's, so the Spanish cantares open at the
    # same *fraction* of the way through, not at the same laisse number.
    es_cuts = [round(o * len(ls) / len(en)) for o in opens]
    write(OUT_ES, ["\n".join(b) for b in ls], es_cuts)
    write(OUT_EN, en, opens)
    return 0


if __name__ == "__main__":
    sys.exit(main())
