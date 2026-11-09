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
    9: ("NOUV", "NEUV"), 10: ("DESE", "DIXI"), 11: ("VOUN", "ONZI"), 12: ("DOUG", "DOUZ"),
}
# Capitals only: the titles are set in them, and a verse line that happens to
# open "Tant" must not read as one. The OCR takes the C for a T or a G
# ('TANT SIÈISEN', 'GANT DESEN') and the V of NOUVEN for a Y.
TITLE = re.compile(r"^\W*[CTG(]?H?ANT\.?\s+([A-ZÏÈÉÎÊ]{4})")
NOTES = re.compile(r"^\W*NOTES\s*$")
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
        word = (m.group(1).replace("Ï", "I").replace("È", "E").replace("É", "E")
                .replace("Ê", "E").replace("Î", "I").replace("Y", "V"))
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
    if s[:1].isupper():
        # A short line with a capital is verse unless it is plainly French:
        # the facing prose is set full measure, and its short lines end a
        # paragraph mid-sentence, in lower case. One shared word ('que' in
        # "Coume la chato que se raubo,") is no evidence.
        return not (fs >= 2 and fs > ps)
    if ps or fs:
        return ps >= fs
    return len(s) >= 14           # no evidence either way: a short line of verse


def capitals(s: str) -> bool:
    """A line set in capitals: a running head the OCR garbled past what head()
    knows ('14 HIRÈIO, GANT I', 'MIREILLE, CIIANT II. M', 'C(5 MlRfnO, C\\NT
    II.'), a canto's subtitle ('LOU MAS DI FALABREGO'), or the back matter's
    titles. Mistral's verse is set in upper and lower case, so no line of it
    is mostly capitals."""
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) >= 0.55


# PROV less the words French spells the same way ('tout', 'quand', 'mai').
ONLY_PROV = PROV - {"tout", "toutes", "quand", "mai"}


def strongly_provencal(s: str) -> bool:
    """Provencal by words French does not share, not merely by being short:
    for the lines a capital cannot vouch for ('un linceul de neige quand la
    nature dort' has 'quand', and is French)."""
    words = re.findall(r"[a-zàâçèéêëîïôûù']+", s.lower())
    ps = sum(w.split("'")[-1] in ONLY_PROV or w in ONLY_PROV for w in words)
    fs = sum(w in FRENCH for w in words)
    return ps >= 1 and ps > fs


def provencal(lines: list[str]) -> list[str]:
    """The verse lines of `lines`, with heads, numbers and French prose removed.

    Every line of the verse is printed with a capital, so a line that starts
    in lower case is either a capital I the OCR read as l ('léu' for Iéu,
    'l'a' for I'a), which is put back, or the tail of a line of the facing
    French ('vaises rumeurs ;'), which goes unless its words say Provencal.
    Both texts open speech with a dash, but only the French quotes it in
    guillemets, so a line carrying them is French.
    """
    out: list[str] = []
    for ln in lines:
        s = re.sub(r"\s+", " ", ln.strip())
        if not s or head(s) or capitals(s) or re.fullmatch(r"[\W\d]{0,6}", s):
            continue
        if re.fullmatch(r"[IVXLHT1l\d\s.,]{1,8}", s):    # a section numeral, 'XI 11'
            continue
        # 'le' is a French article as often as a misread Provencal 'Ie', so
        # only l' and lé are restored on sight.
        if re.match(r"l(?:'|é)", s) or re.match(r"le\b", s) and strongly_provencal(s):
            s = "I" + s[1:]
        elif re.match(r"[a-zàâçèéêëîïôûù]", s) and not strongly_provencal(s):
            continue
        elif re.search(r"(^|\s)«|»(\s|$)", s):
            # The French quotes; Mistral's verse uses dashes. Inside a word a
            # guillemet is the OCR's misreading of a letter ('di«as-me').
            continue
        if is_provencal(s):
            out.append(s)
    return out


def skip_argument(lines: list[str], at: int, stop: int) -> int:
    """Where a canto's verse begins, past the prose argument under its title.

    The argument is a paragraph of the canto's matter in sentences joined by
    dashes ("A l'aubo, très pourcatié trovon Vincèn ... — L'aduson à la
    brasseto au Mas di Falabrego. — ..."), set full measure, so its lines are
    longer than any line of verse, all but its last, which is short and ends
    with a full stop ("famiho pèr avé Mirèio."). It starts within the first
    few lines -- after the title and the canto's name -- and that is the only
    place it is looked for, so a long line of verse further on is safe; the
    facing French is not a run of lines that starts there either.
    """
    nonblank = [i for i in range(at, min(stop, at + 120)) if lines[i].strip()]
    width = lambda i: len(re.sub(r"\s+", " ", lines[i].strip()))
    k = next((k for k in range(min(5, len(nonblank))) if width(nonblank[k]) >= 50), None)
    if k is None:
        return at
    while k < len(nonblank) and width(nonblank[k]) >= 50:
        k += 1
    if k < len(nonblank) and lines[nonblank[k]].strip().endswith("."):
        k += 1
    return nonblank[k] if k < len(nonblank) else stop


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
    # The poem ends on Mistral's dateline ("Maiano [Bouco-déu-Rose], Lou ...
    # jour de la Candelouso, de l'an 1859"); after it come notes, Seguin's
    # melody for Magali, the table of contents and the library's slip.
    end = next(i for i, ln in enumerate(lines) if i > order[-1][1] and ln.strip().startswith("Maiano"))
    for k, (n, at) in enumerate(order):
        stop = order[k + 1][1] if k + 1 < len(order) else end
        # Mistral's French notes follow each canto, under "NOTES"; some lines
        # of them (and a Dante quotation) would pass for verse.
        stop = next((i for i in range(at, stop) if NOTES.match(lines[i])), stop)
        verse = provencal(lines[skip_argument(lines, at, stop):stop])
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
