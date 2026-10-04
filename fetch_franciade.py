#!/usr/bin/env python
"""Extract Ronsard's Franciade, books 1-4, from the 1858 Blanchemain edition.

Source: archive.org `oeuvrescompltes00ronsgoog` (Oeuvres completes, vol. 3).
The 1572 first edition's OCR reads long-s as 'f' and is unusable; this one is
clean Roman type. What it carries besides verse, and what is dropped here:
running heads, 'dby Google' page marks, prose arguments, and variant-reading
footnotes ('a. Var. : ...'), which run to the next page mark.

Writes input/franciade_fr.txt, one 'LIVRE n' heading per book.
"""
import re
import sys
import subprocess
from pathlib import Path

URL = "https://archive.org/download/oeuvrescompltes00ronsgoog/oeuvrescompltes00ronsgoog_djvu.txt"
CACHE = Path(__file__).parent / "cache" / "ronsard_1858_djvu.txt"
OUT = Path(__file__).parent / "input" / "franciade_fr.txt"

# First verse line of each book is found after its 'Neufiesme de ce nom.'
# dedication; each book ends at its FIN DU ... marker (or the next book head).
BOOK_HEAD = re.compile(r"^LE\s+(PREMIER|SECOND|TROISI\w*|[Qq]UATRI\w*)\s+LIVRE\s*$")
END = re.compile(r"^FIN\s+DU\b")
PAGEMARK = re.compile(r"d\s*by\s*Google|Digitized\s*by|^\s*Google\s*$", re.I)
RUNHEAD = re.compile(r"^\W*(\d+\s+)?La\s+Franciade\W*$"
                     r"|^\W*Livre\s+(premier|second|troisi|quatri)\w*.{0,8}$", re.I)
FOOT = re.compile(r"^\s*\S{1,3}[.,]?\s*([Vv][aàâ]r|Yar|Cf|Voy|Dans les|Ces vers)")


# Drop-capitals and margin line numbers come out of the OCR as debris, and the
# first line of each book loses its initial to it. These four are restored by
# hand from the verse itself.
OPENINGS = {
    "luse": "Muse, enten-moy des sommets de Parnasse,",
    "es pi": "Les puissans dieux, la plus gaillarde troupe",
    "'obsc": "L'obscure nuit, qui d'un sommeil enserre",
    ", Uand": "Quand la nouvelle au père fut venue,",
    "5pon": "Qu'on appeloit en sa jeunesse tendre",
}
RUNHEAD2 = re.compile(r"^[\dIl]*\s*L\W?\s*A?\s*Fran\w*\W*$|^Livre\s+\w+\W*\w{0,3}$", re.I)


def tidy(s: str) -> str:
    for head, fixed in OPENINGS.items():
        if s.startswith(head):
            return fixed
    if RUNHEAD2.match(s):
        return ""
    s = re.sub(r"^[^A-Za-zÀ-ÿ«\"'" + "’" + r"]+(?=[A-Za-zÀ-ÿ])", "", s)  # margin numbers, brackets
    s = re.sub(r"\s*\([a-f0-9â]\)", "", s)                       # footnote call-outs
    return s.replace("^", "").strip()


def main() -> int:
    if not CACHE.exists():
        # urllib trips on an expired certificate on one archive.org node; curl
        # does not, so let it do the download.
        CACHE.parent.mkdir(exist_ok=True)
        subprocess.run(["curl", "-sL", "-m", "300", "-o", str(CACHE), URL], check=True)
    raw = CACHE.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    books: list[list[str]] = []
    cur: list[str] | None = None
    in_foot = False
    seen_arg = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("ARGUMENT") or re.match(r"^DU\s+\w+\s+LIVRE", s):
            seen_arg = True
            cur = None
            continue
        if BOOK_HEAD.match(s) and "FRANCIADE" not in s:
            # Each book's head appears twice: before its prose argument, and
            # again above the verse. Only the second opens the book.
            if seen_arg:
                cur = []
                books.append(cur)
                in_foot = False
                seen_arg = False
            continue
        if END.match(s):
            cur = None
            continue
        if cur is None:
            continue
        if PAGEMARK.search(s):
            in_foot = False
            continue
        if FOOT.match(s):
            in_foot = True
            continue
        if in_foot or not s or RUNHEAD.match(s):
            continue
        if re.match(r"^(AU ROY|Neufiesme|LA F\s*RAN)", s):
            continue
        if len(s) < 8 and not re.search(r"[.,;:!?]$", s):
            continue  # OCR debris
        if re.match(r"^\d+[.)]\s", s):
            in_foot = True  # a numbered editorial note; runs to the page mark
            continue
        s = tidy(s)
        if s:
            cur.append(s)
    books = [b for b in books if len(b) > 300][:4]
    out = []
    for i, b in enumerate(books, 1):
        out.append(f"LIVRE {i}")
        out.extend(b)
        out.append("")
        print(f"book {i}: {len(b)} lines", file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
