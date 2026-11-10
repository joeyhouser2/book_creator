#!/usr/bin/env python
"""A second OCR of Mirèio's Provençal, to correct the archive.org text layer.

fetch_mireio.py cuts the poem out of archive.org's own OCR of the 1861 Avignon
edition (`mireillepomepr00mistuoft`), which misreads a good deal of the
Provençal ('cbato' for chato, 'frcscour' for frescour, l for I) and drops
lines, so that several cantos do not divide into seven-line stanzas. This
script re-reads the Provençal pages with Tesseract twice -- the Occitan model
alone (`oci`, which keeps the ç) and with French (`oci+fra`, which reads the
dashes and some consonants better) -- and merges the three readings line by
line:

  * the three are aligned per canto (a global alignment on fuzzy line
    similarity), so a line of the first OCR finds its twin in the others;
  * of the readings of a line, the one the others agree with most and whose
    words are most often met elsewhere in the poem is kept -- every line comes
    whole from one of the OCRs, nothing is composed from pieces;
  * a line both new readings have and the first OCR lacks is restored;
  * stray marks from the gutter at a line's ends ('^', '|', '-') that the other
    readings do not have are trimmed.

    python ocr_mireio.py          # fetch pages, OCR them (cached), write input/mireio_oc.txt
    python ocr_mireio.py --report # the same, and print sample corrections

The item's _jp2.zip goes to cache/mireio_jp2/, the Provençal pages decoded from
it to cache/mireio_pages/, OCR text to cache/mireio_ocr/{oci,oci_fra}/.
Once those exist, `python fetch_mireio.py` applies the merge by itself.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rapidfuzz import fuzz, process

ROOT = Path(__file__).parent
PAGES = ROOT / "cache" / "mireio_pages"
OCR = ROOT / "cache" / "mireio_ocr"
TESSDATA = ROOT / "cache" / "tessdata"
ITEM = "mireillepomepr00mistuoft"
ZIP = ROOT / "cache" / "mireio_jp2" / f"{ITEM}_jp2.zip"
ZIP_URL = f"https://archive.org/download/{ITEM}/{ITEM}_jp2.zip"
MODELS = {"oci": "oci", "oci_fra": "oci+fra"}
MODEL_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata"

# Scan files (1-based, as in the item's _jp2.zip) of each canto's Provençal
# pages: from the title page to the last page of verse, every other leaf --
# the French faces each one. Notes, the Magali melody, front and back matter
# are left out. Found from the running heads of the item's _djvu.xml.
CANTO_PAGES = {
    1: (16, 56), 2: (64, 98), 3: (102, 140), 4: (144, 180), 5: (184, 224), 6: (228, 274),
    7: (280, 320), 8: (330, 362), 9: (366, 396), 10: (400, 432), 11: (436, 474), 12: (478, 510),
}


def pages(n: int) -> list[int]:
    a, b = CANTO_PAGES[n]
    return list(range(a, b + 1, 2))


# --- fetching and OCR -------------------------------------------------------

def fetch_models() -> None:
    TESSDATA.mkdir(parents=True, exist_ok=True)
    for lang in ("oci", "fra"):
        dst = TESSDATA / f"{lang}.traineddata"
        if not dst.exists():
            subprocess.run(["curl", "-sL", "-m", "600", "-o", str(dst), MODEL_URL.format(lang=lang)], check=True)


def fetch_zip() -> None:
    """The item's page images, all in one archive (162 MB): archive.org's IIIF
    server times out on every few pages when they are asked for one by one."""
    if not ZIP.exists():
        ZIP.parent.mkdir(parents=True, exist_ok=True)
        part = ZIP.with_suffix(".part")
        subprocess.run(["curl", "-sL", "-m", "3600", "-o", str(part), ZIP_URL], check=True)
        part.rename(ZIP)


def fetch_page(n: int) -> Path:
    """Page `n` as a greyscale PNG, decoded from its JP2 in the archive."""
    dst = PAGES / f"p{n:04d}.png"
    if not dst.exists():
        import io
        import zipfile
        from PIL import Image
        with zipfile.ZipFile(ZIP) as z:
            data = z.read(f"{ITEM}_jp2/{ITEM}_{n:04d}.jp2")
        tmp = dst.with_suffix(".tmp")
        Image.open(io.BytesIO(data)).convert("L").save(tmp, format="PNG")
        tmp.rename(dst)
    return dst


def tesseract() -> str:
    from book_creator import ocr
    exe = ocr.tesseract_exe()
    if not exe:
        raise SystemExit("tesseract not found")
    return exe


def ocr_page(n: int, exe: str) -> None:
    img = fetch_page(n)
    for key, lang in MODELS.items():
        dst = OCR / key / f"p{n:04d}.txt"
        if dst.exists() and dst.stat().st_size > 0:
            continue
        # --psm 4: one column of text of variable sizes, which keeps the
        # verse lines whole and the title and argument apart.
        r = subprocess.run([exe, str(img), "stdout", "--tessdata-dir", str(TESSDATA),
                            "-l", lang, "--psm", "4"], capture_output=True)
        dst.write_text(r.stdout.decode("utf-8"), encoding="utf-8")


def run_ocr() -> None:
    fetch_models()
    fetch_zip()
    PAGES.mkdir(parents=True, exist_ok=True)
    for key in MODELS:
        (OCR / key).mkdir(parents=True, exist_ok=True)
    exe = tesseract()
    todo = [n for c in CANTO_PAGES for n in pages(c)]
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for _ in ex.map(lambda n: ocr_page(n, exe), todo):
            done += 1
            if done % 20 == 0:
                print(f"ocr {done}/{len(todo)}", file=sys.stderr, flush=True)


def available() -> bool:
    files = [OCR / key / f"p{n:04d}.txt" for key in MODELS for c in CANTO_PAGES for n in pages(c)]
    return all(f.exists() and f.stat().st_size > 0 for f in files)


# --- reading the new OCR ----------------------------------------------------

JUNK_TOKEN = re.compile(r"^[\W\d_]*$")
KEEP_END = set(".,;:!?…»")


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s.replace("’", "'").strip())
    # The dash that opens speech, read as a hyphen or two.
    s = re.sub(r"^(?:--?|=)\s+", "— ", s)
    s = re.sub(r"\s(?:--?|=)\s", " — ", s)
    # Marks from the gutter or the page edge: a token with no letters at the
    # end (but not the punctuation French typography sets off with a space:
    # ; : ! ?), or a stray mark at the start.
    toks = s.split(" ")
    while len(toks) > 1 and JUNK_TOKEN.match(toks[-1]) and not set(toks[-1]) <= set(";:!?»…"):
        toks.pop()
    # A short lower-case scrap after a full stop at the end ('la fam. sab').
    while len(toks) > 2 and re.fullmatch(r"[a-zà-ÿ]{1,3}", toks[-1]) and re.search(r"[.!?]$", toks[-2]):
        toks.pop()
    while len(toks) > 1 and re.fullmatch(r"[|^'`*•■)_~:;,.=+-]+", toks[0]):
        toks.pop(0)
    # A doubled spaced mark ('l'aresto ; ;').
    while len(toks) > 2 and toks[-1] == toks[-2] and JUNK_TOKEN.match(toks[-1]):
        toks.pop()
    s = " ".join(toks)
    # Every verse line opens on a capital; a lower-case l there is an I.
    if re.match(r"l(?:'|é|e\b|è)", s):
        s = "I" + s[1:]
    return s


def page_lines(text: str) -> list[str]:
    import fetch_mireio as fm
    raw = [ln.strip() for ln in text.splitlines() if ln.strip()]
    at = 0
    # The title page: MIRÈIO / CANT PROUMIÉ / the canto's name / the argument,
    # a paragraph set full measure, wider than any line of verse. It ends on
    # a short line, which carries on the sentence in lower case, where every
    # line of verse opens on a capital.
    if any(fm.TITLE.match(ln) or re.match(r"^\W*[CTG]ANT\s+[A-Z]", ln) for ln in raw[:8]):
        wide = [i for i in range(min(30, len(raw))) if len(raw[i]) >= 52]
        if wide:
            at = wide[-1] + 1
            # Its last line: lower case, or a new sentence after a dash
            # ('... — Escaufèstre e separacioun di calignaire.').
            if at < len(raw) and (re.match(r"[a-zà-ÿ]", raw[at])
                                  or re.search(r"[—=-]$", raw[at - 1]) and raw[at].endswith(".")):
                at += 1
    out = []
    for ln in raw[at:]:
        s = tidy(ln)
        if not s or fm.head(s) or fm.capitals(s):
            continue
        if not re.search(r"[^\W\d_]{2}", s):
            continue
        if re.fullmatch(r"[IVXLHT1l\d\s.,]{1,8}", s):
            continue
        out.append(s)
    return out


def canto_lines(n: int, key: str) -> list[str]:
    out: list[str] = []
    for p in pages(n):
        out += page_lines((OCR / key / f"p{p:04d}.txt").read_text(encoding="utf-8"))
    return out


# --- alignment and choice ---------------------------------------------------

def norm(s: str) -> str:
    return " ".join(re.findall(r"[^\W\d_]+", s.lower()))


def align(xs: list[str], ys: list[str], cut: float = 55.0) -> list[tuple[int | None, int | None]]:
    """Global alignment of two line lists: a pair scores its similarity above
    `cut`, a gap scores nothing, so dissimilar lines are left unpaired."""
    if not xs or not ys:
        return [(i, None) for i in range(len(xs))] + [(None, j) for j in range(len(ys))]
    sim = process.cdist([norm(x) for x in xs], [norm(y) for y in ys], scorer=fuzz.ratio)
    n, m = len(xs), len(ys)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        back[i][0] = 1
    for j in range(1, m + 1):
        back[0][j] = 2
    for i in range(1, n + 1):
        row, prev, simrow = score[i], score[i - 1], sim[i - 1]
        brow = back[i]
        for j in range(1, m + 1):
            best, b = prev[j], 1                        # x unpaired
            if row[j - 1] > best:
                best, b = row[j - 1], 2                 # y unpaired
            s = simrow[j - 1]
            if s >= cut and prev[j - 1] + (s - cut) > best:
                best, b = prev[j - 1] + (s - cut), 0
            row[j], brow[j] = best, b
    out = []
    i, j = n, m
    while i or j:
        b = back[i][j]
        if b == 0:
            out.append((i - 1, j - 1)); i -= 1; j -= 1
        elif b == 1:
            out.append((i - 1, None)); i -= 1
        else:
            out.append((None, j - 1)); j -= 1
    return out[::-1]


def bare(w: str) -> str:
    """A word without its accents: the two OCRs disagree on ò/ô/ó."""
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", w) if not unicodedata.combining(ch))


BAD_CHARS = set("^|~_{}[]<>*•■$#@\\/«»0123456789%&=+")


class Lexicon:
    """How often each word occurs in the new OCR of the whole poem: a word
    met three times or more is taken as real Provençal, a misreading is
    rarely made the same way that often."""

    def __init__(self, texts: list[str]):
        self.c = Counter(w for t in texts for w in norm(t).split())
        self.bare = {bare(w) for w in self.c}

    def score(self, s: str) -> float:
        words = norm(s).split()
        if not words:
            return 0.0
        return sum(self.c[w] >= 3 for w in words) / len(words)


def choose(readings: dict[str, str], lex: Lexicon) -> str:
    """The reading of a line to keep: agreement with the other readings,
    plus the share of its words found elsewhere in the poem, less stray marks.
    Ties go to the Occitan model, then oci+fra, then the old text."""
    order = {"oci": 0.002, "oci_fra": 0.001, "old": 0.0}
    best, top = None, -1e9
    for k, r in readings.items():
        agree = sum(fuzz.ratio(r, o) for kk, o in readings.items() if kk != k) / 100
        if len(readings) > 1:
            agree /= len(readings) - 1
        bad = sum(ch in BAD_CHARS for ch in r)
        sc = agree + 2 * lex.score(r) - 0.3 * bad + order[k]
        if sc > top:
            best, top = r, sc
    return best


def trim_to_consensus(chosen: str, others: list[str]) -> str:
    """Drop an end token of the chosen line that no other reading has there:
    gutter marks the new OCR picked up ('fam. sab', 'maduro, :')."""
    if not others:
        return chosen
    toks = chosen.split(" ")
    ends = {o.split(" ")[-1] for o in others if o}
    starts = {o.split(" ")[0] for o in others if o}
    if len(toks) > 2 and toks[-1] not in ends and len(norm(toks[-1])) <= 3 \
            and re.search(r"[.,;:!?]$", toks[-2]) and all(norm(o).split()[-1:] != norm(toks[-1]).split()
                                                           for o in others if norm(o)):
        toks.pop()
    if len(toks) > 2 and toks[0] not in starts and len(toks[0]) == 1 and not toks[0].isalpha() \
            and toks[0] not in {"—", "-", "«"}:
        toks.pop(0)
    return " ".join(toks)


# Words no reading got: the one place a word is supplied by hand, each from
# Mistral's own facing French. Canto VIII, "Lando, lando ! Si pèd to=^2*0n pas
# lou sòu..." -- "Ses pieds ne touchaient pas le sol" -- is toucavon.
BY_HAND = {"to=^2*0n": "toucavon"}


def polish(s: str) -> str:
    """The marks every reading got wrong alike, so that choosing between them
    could not fix: an apostrophe read as a backtick ('`mé', '`n pau', or
    doubled, '`'mé'), and one at the head of a line where there is none
    ('`La terro'); a capital I read as a bracket ('[éu ai senti'); an A read
    as a caret ('Mèste ^ mbroi'); an apostrophe as an asterisk ('i*a'); and
    the dash that opens speech read as '=' or '-_' with a speck of print
    after it ('=Q Èi morto!', '-_Â Iéu noun!', '=Jéu?', '=Ê regardas', where
    the speck is the E itself)."""
    for bad, good in BY_HAND.items():
        s = s.replace(bad, good)
    s = re.sub(r"^`+('?)", r"\1", s)                 # "`'Mé li relicle" keeps its '
    s = re.sub(r"`+'?|'`+", "'", s)
    # The vocative O read as a zero: '0 moun paure Vincèn', '—0!'.
    s = re.sub(r"(^|— ?|—)0(?=[\s!,.])", lambda m: m.group(1).rstrip() + (" " if m.group(1) else "") + "O", s)
    s = re.sub(r"^\[(?=[a-zéè])", "I", s)
    s = re.sub(r"\^ ?(?=[a-z])", "A", s)
    s = re.sub(r"(?<=[a-z])\*(?=[a-z])", "'", s)
    def dash(m: re.Match) -> str:
        speck = m.group(1) or ""
        return {"Ê": "— E ", "J": "— I"}.get(speck, "— ")

    s = re.sub(r"(?:^|(?<=\s)|(?<=[!?.]))(?:=|-_|_-)\s*(Ê(?=\s)|J(?=[éè])|[QÂ](?=\s))?\s*", dash, s)
    s = re.sub(r"(?<=\.)- ", " — ", s)              # '...- E pièi'
    s = re.sub(r"(?<=[!?.…])—", " —", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def merge(n: int, old: list[str], lex: Lexicon, log: dict | None = None) -> list[str]:
    """Canto `n`'s verse, the old reading `old` corrected from the new OCR."""
    b, c = canto_lines(n, "oci"), canto_lines(n, "oci_fra")
    rows = [(None if i is None else b[i], None if j is None else c[j]) for i, j in align(b, c)]
    # Align the old lines against the new rows, by the better of the two.
    keys = [x if x is not None else y for x, y in rows]
    out: list[str] = []
    for i, j in align(old, keys):
        a = None if i is None else old[i]
        x, y = (None, None) if j is None else rows[j]
        if a is not None and x is None and y is None:
            # The new OCR has no such line. It read every Provençal page, so
            # a line it lacks is as often French the text layer let through
            # ('Mireille, naissance de son amour.') as verse it missed: kept
            # only when its words are the poem's own.
            import fetch_mireio as fm
            french = sum(w in fm.FRENCH for w in norm(a).split())
            # ...and every longer word of it is met in the new OCR's poem
            # ('Saintes d'or !' is French, the Provençal says Santo).
            unknown = [w for w in norm(a).split() if len(w) >= 4 and bare(w) not in lex.bare]
            if lex.score(a) >= 0.6 and len(a) >= 12 and len(norm(a).split()) >= 3 \
                    and (french == 0 or fm.strongly_provencal(a)) and not unknown:
                out.append(a)
                if log is not None:
                    log.setdefault("old_only", []).append((n, a))
            elif log is not None:
                log.setdefault("old_dropped", []).append((n, a))
            continue
        if a is None:
            # A line only the new OCR has: restore it when both its readings
            # have it, alike, and it reads as verse.
            if x is None or y is None or fuzz.ratio(norm(x), norm(y)) < 80:
                if log is not None:
                    log.setdefault("new_rejected", []).append((n, x if x is not None else y))
                continue
            line = trim_to_consensus(choose({"oci": x, "oci_fra": y}, lex), [x, y])
            # Both readings agree, so this is print, not noise; only scraps
            # (a marginal 'S6', the closing 'FIN.') are left out.
            if len(line) < 12 or len(norm(line).split()) < 3:
                if log is not None:
                    log.setdefault("new_rejected", []).append((n, line))
                continue
            out.append(line)
            if log is not None:
                log.setdefault("restored", []).append((n, line))
            continue
        readings = {"old": a}
        if x is not None:
            readings["oci"] = x
        if y is not None:
            readings["oci_fra"] = y
        line = choose(readings, lex)
        line = trim_to_consensus(line, [r for r in readings.values() if r is not line])
        out.append(line)
        if log is not None and line != a:
            log.setdefault("changed", []).append((n, a, line))
    return [polish(line) for line in out]


def lexicon() -> Lexicon:
    return Lexicon([ln for n in CANTO_PAGES for key in MODELS for ln in canto_lines(n, key)])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    run_ocr()
    import fetch_mireio
    return fetch_mireio.main(report="--report" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
