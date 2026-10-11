#!/usr/bin/env python
"""Extract G. H. C. Egestorff's English verse Messiah (Hamburg/London, 1826).

Source: archive.org `klopstocksmessi00klopgoog` (cantos I-X) and
`klopstocksmessi01klopgoog` (cantos XI-XX), Google's scans of the 4-volume
translation bound as two parts, read by Google's own OCR. It is blank verse and
complete, which the machine translation this replaces was not: Opus-MT kept only
one sentence of every German line that held two.

What the OCR leaves around the verse, and how it is told apart:

  * Every fifth line carries its number at the line end ('... restored.  5.').
    Numbers restart at each canto and run to ~1,600, so a trailing token that
    holds a digit (or is nothing but symbols) is a line number, however the OCR
    garbled it ('$5', '1£5', '1*j0').
  * Page heads: "Klopstock's Messiah." and "Canto III. <gothic gibberish> 305".
    The gibberish is the printer's black-letter running title read as Latin.
  * Canto headings are a standalone "Canto N." Where the OCR lost one (XX), the
    first running head naming the expected number marks the start instead.
  * Blank lines between every line: dropped; the English is one verse per line.

Writes input/messias_en_egestorff.txt, 'Canto N' heading per division.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "egestorff"
OUT = ROOT / "input" / "messias_en_egestorff.txt"
# (archive.org id, cantos, use the archive's own OCR?). Part 1's Google text is
# already good (~6% unrecognised words, mostly names) and Tesseract is a shade
# worse on it; part 2's is poor (12-27%) and Tesseract cuts that roughly in half.
PARTS = [("klopstocksmessi00klopgoog", range(1, 11), True),
         ("klopstocksmessi01klopgoog", range(11, 21), False)]

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
         "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]

CANTO = re.compile(r"(?i)\bcanto\W+([ivxlu1|h]{1,7})\W*$")
GARBLED = re.compile(r"(?i)^\W*c\w{2,4}\W{1,5}([ivxlu1|]{1,7})\b")
STANDALONE = re.compile(r"(?i)^\W*canto\W+([ivxlu1|h]{1,7})\W*$")
# The printer's head reads "Canto", "Cahto" or "CAHTO", depending on the page.
RUNNING = re.compile(r"(?i)\bc[a-z]{2}to\b\W*[a-z0-9|]{1,7}\b")
# One- and two-letter words that really end a line of verse.
SHORT = {"a", "i", "o", "to", "of", "in", "on", "at", "as", "by", "he", "me", "my",
         "we", "us", "so", "no", "or", "if", "it", "is", "be", "do", "go", "up",
         "an", "am", "ye", "thy", "oh", "ah", "lo", "ev", "'d"}
STOP = re.compile(r"(?i)^\W*(errata|end of the|finis\b)")
TITLE = re.compile(r"(?i)^\W*klopstocks?\W{0,3}\s*messiah\W*$")
TRAIL = re.compile(r"\s+(?=\S*\d)\S{1,6}$|\s+[^\w\s'\"“”‘’.,;:!?()—-]{1,4}$")


def norm_numeral(tok: str) -> str:
    return re.sub(r"[1lL|]", "I", tok.upper().replace("U", "I").replace("H", "I"))


def _download(ident: str, name: str) -> Path:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        url = f"https://archive.org/download/{ident}/{name}"
        print(f"fetching {url}")
        import requests
        r = requests.get(url, timeout=900)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def _tesseract_pages(ident: str) -> list[str]:
    """Re-read the page scans with Tesseract's English model.

    Google's OCR of part 2 (cantos XI-XX) is poor -- about 1 word in 5 is not
    English ("Bad slowly been revcd^riog") -- and the ABBYY layer archive.org
    carries is no better. Tesseract on the same TIFFs reads the page properly,
    which is why this is the default.
    """
    import concurrent.futures as cf
    import subprocess
    import zipfile
    sys.path.insert(0, str(ROOT))
    from book_creator.ocr import tesseract_exe
    exe = tesseract_exe()
    if not exe:
        raise SystemExit("Tesseract is not installed; pass --google-ocr to use "
                         "the archive's own text instead.")
    work = CACHE / f"ocr-{ident}"
    tifs = CACHE / f"tif-{ident}"
    zpath = _download(ident, f"{ident}_tif.zip")
    if not tifs.exists():
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                z.extract(name, tifs)
    work.mkdir(parents=True, exist_ok=True)
    pages = sorted(tifs.rglob("*.tif"))

    def one(tif: Path) -> Path:
        out = work / tif.stem
        if not out.with_suffix(".txt").exists():
            subprocess.run([exe, str(tif), str(out), "-l", "eng", "--psm", "6"],
                           capture_output=True, check=True)
        return out.with_suffix(".txt")

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        texts = list(ex.map(one, pages))
    lines: list[str] = []
    for t in texts:
        lines.extend(t.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines


def fetch(ident: str, google_ocr: bool = False) -> list[str]:
    if not google_ocr:
        return _tesseract_pages(ident)
    path = _download(ident, f"{ident}_djvu.txt")
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def starts(lines: list[str], numbers) -> dict[int, int]:
    """Line index at which each canto opens, found in order."""
    found, at = {}, 0
    for n in numbers:
        want = ROMAN[n - 1]
        for i in range(at, len(lines)):
            s = re.sub(r"\s+", " ", lines[i].strip())
            m = STANDALONE.match(s)
            if m and norm_numeral(m.group(1)) == want:
                found[n], at = i, i + 1
                break
        else:
            # Heading garbled ("CANtt) XX."): the first line that opens like
            # one and names the right numeral, else the first running head.
            for i in range(at, len(lines)):
                s = re.sub(r"\s+", " ", lines[i].strip())
                m = GARBLED.match(s) or CANTO.search(s)
                if m and norm_numeral(m.group(1)) == want:
                    found[n], at = i, i + 1
                    break
            else:
                raise SystemExit(f"canto {want}: no heading found")
    return found


def clean_line(raw: str) -> str | None:
    s = raw.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s.replace(" ", " ")).strip()
    if not s or TITLE.match(s):
        return None
    if RUNNING.search(s) or re.match(r"^\d{1,4}\s+\S.*\bc[a-z]{2}to\b", s, re.I):
        return None                              # running head
    s = re.sub(r"^[|jJ\-.,_*•]+\s*(?=[A-Z\"'“‘])", "", s)   # leading debris: 'jOf the'
    for _ in range(4):
        # Line number, however garbled, and the margin specks Tesseract reads
        # as one- and two-letter words ("oy ;", "Z |") after the verse.
        before = s
        s = TRAIL.sub("", s).strip()
        toks = s.split(" ")
        if len(toks) >= 4:
            last = toks[-1]
            bare = re.sub(r"\W", "", last)
            if (len(bare) <= 2 and bare.lower() not in SHORT
                    and not re.search(r"[.!?;:,]$", last)) or not bare and last not in ("—", "-"):
                s = " ".join(toks[:-1]).strip()
        if s == before:
            break
    s = re.sub(r"(?<=\s)\d{1,4}\b[.,]?(?=\s|$)", "", s)    # a line number read mid-line
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[':;,.]\s+", "", s)                       # stray speck before the line
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"(\w) - (\w)", r"\1-\2", s)
    letters = sum(c.isalpha() for c in s)
    if letters < 3 or letters / max(1, len(s.replace(" ", ""))) < 0.72:
        return None                              # page number or print debris
    if not re.search(r"[A-Za-z]{2,}", s):
        return None
    return s



SPECKS = re.compile(r"[\^~|_°}{\[\]¢¥£©•■@=+<>\\$«»#]")


def finish_line(s: str) -> str | None:
    """Last pass over a verse line: print specks the page scan read as marks.

    A '*' at the end of a line is the full stop or comma the scan lost; inside
    a line it is a speck. The rest are never part of this text.
    """
    if re.search(r"(?i)\bklopstock", s):
        return None                               # a running head that got through
    s = re.sub(r"\*+(?=\s*$)", ".", s)
    s = re.sub(r"(?<=\w)\*+(?=[.,;:!?])", "", s)
    s = re.sub(r"(?<=[A-Za-z])/(?=\s|$)", "!", s)
    s = s.replace("*", "")
    s = SPECKS.sub("", s)
    s = re.sub(r"[:;,.]{2,}", lambda m: m.group(0)[-1], s)        # ":::" left by a speck
    s = re.sub(r"(?<=[.,;:!?])\s+[^aeiouyAEIOUY\s.,;:!?'\"]{1,4}$", "", s)   # "tjM"
    s = re.sub(r"(?<=\w)[.,;:]{2,}$", ".", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return s if re.search(r"[A-Za-z]{2}", s) else None


def cantos(ident: str, numbers, google: bool) -> dict[int, list[str]]:
    """Each canto's cleaned verse lines, read from one OCR engine."""
    lines = fetch(ident, google_ocr=google)
    begin = starts(lines, numbers)
    order = sorted(begin.items())
    res = {}
    for k, (n, a) in enumerate(order):
        b = order[k + 1][1] if k + 1 < len(order) else len(lines)
        body = []
        for i in range(a + 1, b):
            if STOP.match(re.sub(r"\s+", " ", lines[i].strip())):
                break
            c = clean_line(lines[i])
            if c:
                body.append(c)
        res[n] = body
    return res


def english_corpus() -> list[str]:
    """Clean English already in the repo: what a word has to look like."""
    texts = []
    for f in list((ROOT / "input").glob("*.txt")) + list((ROOT / "cache").glob("pg*.txt")):
        if "egestorff" in f.name:
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        w = re.findall(r"[a-z]+", t.lower())
        if len(w) > 5000 and sum(x in ("the", "and", "of", "to", "with", "his", "her")
                                  for x in w) / len(w) > 0.08:
            texts.append(t)
    return texts


NL = chr(10)
NL2 = chr(10) * 2


def finish_existing() -> None:
    """Apply only the print-speck cleanup to the text already written."""
    out = []
    for line in OUT.read_text(encoding="utf-8").split(NL):
        if re.fullmatch(r"Canto [IVXL]+", line) or not line.strip():
            out.append(line)
        else:
            f = finish_line(line)
            if f:
                out.append(f)
    OUT.write_text(NL.join(out), encoding="utf-8")
    print(f"finished {OUT}")


def main() -> None:
    if "--finish-only" in sys.argv:
        return finish_existing()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "cache" / "pylib"))   # pyspellchecker, if put there
    from book_creator import ocr_english
    correct = "--no-correct" not in sys.argv
    base = {}
    helper = {}
    for ident, numbers, google in PARTS:
        base.update(cantos(ident, numbers, google))
        try:
            helper.update(cantos(ident, numbers, not google))
        except (SystemExit, Exception) as exc:              # noqa: BLE001
            print(f"  no second reading of {ident}: {exc}")
    if correct:
        part1 = NL.join(NL.join(base[n]) for n in range(1, 11))
        german = (ROOT / "input" / "messias_de.txt").read_text(encoding="utf-8")
        everything = NL.join(NL.join(v) for v in base.values())
        lex = ocr_english.default_lexicon(english_corpus(), names_from=part1,
                                          german=german, english_all=everything)
        try:
            scorer = ocr_english.LMScorer("Qwen/Qwen2.5-0.5B-Instruct")
        except Exception as exc:                            # noqa: BLE001
            print(f"  no language model ({exc}); only a second reading will correct")
            scorer = None
    out = []
    for n in sorted(base):
        body = base[n]
        if correct:
            log: list = []
            body = ocr_english.correct(body, lex, helpers=[helper[n]] if n in helper else [],
                                       log=log, scorer=scorer)
            print(f"Canto {ROMAN[n - 1]:<5} {len(body):5d} lines, {len(log)} words repaired",
                  flush=True)
        else:
            print(f"Canto {ROMAN[n - 1]:<5} {len(body):5d} lines")
        body = [x for x in (finish_line(b) for b in body) if x]
        out.append(f"Canto {ROMAN[n - 1]}{NL2}" + NL.join(body))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(NL2.join(out) + NL, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
