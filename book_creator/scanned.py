"""Turn a page-per-document scan back into a book.

Internet Archive EPUBs are built from a scan: one XHTML document per printed
page, each holding that page's OCR as a single paragraph. The text is often
good. Everything around it is wrong for a reader or a narrator:

- every page opens with its running head and page number -- "6 THE WARS OF
  MARLBOROUGH", "DUNKIRK, GHENT, AND BRUGES 95" -- which a narrator reads out
  four hundred times;
- footnotes sit at the foot of the page, in the middle of whatever sentence
  runs on to the next one;
- the book's chapters exist only as headings in the text, so the file's own
  structure is 571 untitled "chapters", one per page;
- bookplates, maps and the index are pages like any other.

None of it can be fixed by a fixed list of patterns, because OCR spells the
same furniture a dozen ways ("101" comes back as "loi", "181" as "l8i"). What
the book does give is repetition: a running head recurs on every other page,
so it can be learned from the book itself. The same goes for OCR confusions
("wliich", "EngHsh"): the right spelling is the one the rest of the book uses.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

# A printed page number as OCR reads it: digits, with 1 often read as i or l,
# 0 as o, and a stray mark in front ("* 291"). Letters alone count only when
# short ("iii" is 111, "loi" is 101), so a real word is never taken for one.
_PAGE_NUMBER = re.compile(r"^[*^]?(?=.*\d)[\dilIoO$S^]{1,4}$|^[ilIoO]{2,3}\d?$")
# A word in capitals, as running heads and chapter headings are set.
_CAPS = re.compile(r"^[A-Z0-9(][A-Z0-9,.'’()\-—&^]*$|^[—\-&^.]+$|^\^?\.?[—\-]+$")
# "XIX.- DUNKIRK", "XXL— LILLE", "APPENDIX I ^.— THE BRITISH INFANTRY".
# A chapter numeral as OCR sets it: "XIX.-", "v.—" in lower case, "XII .—"
# with a space before the stop.
_NUMERAL = r"(?:[XVIL]{1,7}|[xvil]{1,7})\s?\.?\s?[—\-]"
_NUMBERED = re.compile(r"^(?:" + _NUMERAL + r"|APPENDIX\b|CHAPTER\b|BOOK\b|PART\b)")
# Divisions that are apparatus, not text: nobody wants the index read aloud.
_APPARATUS = re.compile(
    r"^(general\s+)?index|^index of|^bibliography|^errata|^contents|"
    r"^list of (maps|illustrations|plates)|^illustrations", re.I)
# Apparatus headings: they open a division of their own even where the book
# is too short in them for their running head to have been learned.
_LISTING = re.compile(
    r"^\W*(CONTENTS|LIST OF (?:ILLUSTRATIONS|MAPS|PLATES)|ILLUSTRATIONS|"
    r"(?:GENERAL )?INDEX(?: OF [A-Z]+(?: [A-Z]+)*?)?|BIBLIOGRAPHY|ERRATA)\b\W*")
# A footnote's own words: what separates a note from the sentence before it.
_CITATION = re.compile(
    r"\b(pp?|vol|vols|ibid|op|cit|ch|chap|ed|MSS?|fol|n)\b\.|\bIbid\b|"
    r"\b1[5-9]\d\d\b|\b(Letters|Memoirs?|M[ée]moires|Dispatches|Correspondence|"
    r"History|Life|Journal|Papers|Coxe|Lediard)\b")


# Front matter is numbered in lower-case roman ("INTRODUCTION ix"). Only a
# well-formed numeral counts, so "civil" or "mix" never does.
_ROMAN_PAGE = re.compile(r"^(?=[ivxlc])c{0,3}(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")


def is_page_number(token: str) -> bool:
    t = token.strip(".,:;-")
    return bool(_PAGE_NUMBER.match(t) or (len(t) >= 2 and _ROMAN_PAGE.match(t)))


# Beside a running head the book has already confirmed, a page number can be
# read more loosely: "no" is 110 and "igS" is 198 there, and nowhere else.
_LOOSE_NUMBER = re.compile(r"^[*^]?[\dilIoOnSsgzZB$|]{1,4}$")


def _beside_head(token: str, *, letters: bool = True) -> bool:
    # Never a single letter: "MEMOIR OF FRANK TAYLOR When I think" is a
    # title and its first words, and "I" is not page 1. After a head, where
    # the text begins, letters alone are not a number: "On the morning".
    t = token.strip(".,:;")
    if is_page_number(t):
        return True
    return len(t) >= 2 and bool(_LOOSE_NUMBER.match(t)) and (letters or bool(re.search(r"\d", t)))


def _norm(s: str) -> str:
    """A heading reduced to what OCR reliably reads: letters and digits."""
    return re.sub(r"[^A-Z0-9]", "", s.upper().replace("0", "O"))


def _same_head(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a) and bool(b) and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _ends_run(tokens: list[str], at: int) -> bool:
    t = tokens[at].strip(".,:;")
    return (is_page_number(t) and len(t) <= 3
            and not re.fullmatch(r"CHAPTER|APPENDIX|BOOK|PART", tokens[at - 1]))


def _caps_run(tokens: list[str], start: int = 0) -> int:
    """How many tokens from `start` are set in capitals.

    A lone capital letter ends the run unless more capitals follow it: "I"
    and "A" begin plenty of sentences, but "APPENDIX I THE ..." is a heading.
    """
    end = start
    # A page number ends it: "PREFACE 9 the fifteen million ..." is a head
    # and its number, not a title "PREFACE 9". Not the numeral a chapter word
    # takes ("CHAPTER II"), and not a year ("CHAPTER I 1914 — 1916").
    while end < len(tokens) and _CAPS.match(tokens[end]) and \
            not (end > start and _ends_run(tokens, end)):
        end += 1
    while end > start and len(re.sub(r"[^A-Z]", "", tokens[end - 1])) == 1 \
            and not re.fullmatch(r"[XVIL]+\.?", tokens[end - 1]):
        end -= 1
    return end - start


@dataclass
class Page:
    """One printed page: what was cut from its head, and what is left."""

    text: str
    head: str = ""
    heading: str = ""
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Running heads
# --------------------------------------------------------------------------- #
def learn_heads(pages: list[str], least: int = 2) -> list[str]:
    """The running heads of a book: words beside a page number, recurring.

    Two shapes, the verso's and the recto's: "6 THE WARS OF MARLBOROUGH ..."
    and "ALMANZA, STOLLHOFEN, AND TOULON 7 ...". A head set in capitals has
    to recur on `least` pages, each time beside a page number, to count --
    which keeps the first words of a page that merely happens to start in
    capitals from being taken for one. A head set in small capitals comes
    back from OCR in mixed case ("12 A subaltern's war"), and is told from
    the first words of the page only by recurring far more often.
    """
    seen: Counter[str] = Counter()
    spelled: dict[str, Counter] = {}
    phrases: Counter[str] = Counter()
    phrase_spelled: dict[str, Counter] = {}
    for text in pages:
        tokens = text.split()[:14]
        if not tokens:
            continue
        runs = []
        if is_page_number(tokens[0]):
            n = _caps_run(tokens, 1)
            if n:
                runs.append(" ".join(tokens[1:1 + n]))
        n = _caps_run(tokens)
        # Numbers-only heads ("1708-1709 271") are caps runs too.
        k = n
        while k > 0 and not (k < len(tokens) and is_page_number(tokens[k])):
            k -= 1
        if k and k < len(tokens) and is_page_number(tokens[k]):
            runs.append(" ".join(tokens[:k]))
        elif n and n < len(tokens) and re.match(r"^[*^]?\d", tokens[n]):
            runs.append(" ".join(tokens[:n]))       # "LILLE 153extent"
        for run in runs:
            key = _norm(run)
            if len(key) >= 3:
                seen[key] += 1
                spelled.setdefault(key, Counter())[run] += 1
        # Any case: every run of words beside a page number is a candidate.
        cands = []
        if is_page_number(tokens[0]):
            cands += [" ".join(tokens[1:1 + k]) for k in range(1, 7) if 1 + k <= len(tokens)]
        for j in range(1, 8):
            if j < len(tokens) and is_page_number(tokens[j]):
                cands.append(" ".join(tokens[:j]))
                break
        for c in cands:
            key = _norm(c)
            if len(key) >= 5 and re.match(r"^[^A-Za-z]*[A-Z]", c):
                phrases[key] += 1
                phrase_spelled.setdefault(key, Counter())[c] += 1
    # A phrase recurring on a few percent of all pages is a head; of nested
    # ones ("A subaltern's", "A subaltern's war"), the longest that recurs
    # nearly as often, since the head is the whole of it.
    floor = max(3, round(0.03 * len(pages)))
    frequent = {k: c for k, c in phrases.items() if c >= floor}
    for key, count in frequent.items():
        if any(o != key and o.startswith(key) and c >= 0.7 * count
               for o, c in frequent.items()):
            continue
        if key not in seen:
            seen[key] = count
            spelled[key] = phrase_spelled[key]
    # Fold OCR variants of one head together before counting.
    merged: list[tuple[str, int]] = []
    for key, count in seen.most_common():
        for i, (k, c) in enumerate(merged):
            if difflib.SequenceMatcher(None, k, key).ratio() >= 0.8:
                merged[i] = (k, c + count)
                break
        else:
            merged.append((key, count))
    # "APPENDIX I" looks like a head beside page number 1, and a chapter's
    # numbered title can recur; a numbered heading is never furniture.
    keys = [k for k, c in merged if c >= least
            and not _NUMBERED.match(spelled[k].most_common(1)[0][0])]
    return [spelled[k].most_common(1)[0][0] for k in keys]


def _junk_number(token: str) -> bool:
    """What is left of a page number OCR could not read: "ZF", "19]", "yd"."""
    t = token.strip(".,:;")
    return 0 < len(t) <= 4 and (bool(re.search(r"[\d\[\]|{}]", t))
                                or (len(t) <= 3 and not t.islower() and t.isalpha()
                                    and t.isupper())
                                or (len(t) <= 2 and t.isalpha()))


def strip_head(text: str, heads: list[str],
               seen: set | None = None) -> tuple[str, str, bool]:
    """Cut a running head and its page number off the start of a page.

    Returns (head, rest, numbered): numbered is whether a page number was
    cut with the head, which tells furniture from a book's title standing
    over a chapter. A head is cut with a page number beside it, and
    added to `seen`. Once seen, it is cut even where OCR has lost the number
    ("RACE WAR IN HIGH SCHOOL ZF disagreed ...") -- otherwise it would read
    as a chapter's title. A head not yet seen without a number is left: a
    chapter's first page has no running head, and its first capitals are its
    title ("MEMOIR OF FRANK TAYLOR When I think ...").
    """
    seen = seen if seen is not None else set()
    tokens = text.split(" ")
    # A page that opens with a chapter numeral opens the chapter, however
    # much its title looks like the head the chapter's pages carry.
    if not tokens or _NUMBERED.match(text):
        return "", text, False
    for head in sorted(heads, key=len, reverse=True):
        width = len(head.split())
        known = head in seen
        # Verso: number, then head. What passes for a garbled number must not
        # be the head's own first word: "THE BEGINNING 19" is "THE" and a
        # head, read wrongly, and "A SUBALTERN'S WAR" is not page A.
        first = _norm(head.split()[0])
        if _beside_head(tokens[0]) or (known and _junk_number(tokens[0])
                                       and _norm(tokens[0]) != first):
            for w in (width, width - 1, width + 1):
                if 0 < w and 1 + w <= len(tokens) and \
                        _same_head(" ".join(tokens[1:1 + w]), head):
                    seen.add(head)
                    return " ".join(tokens[:1 + w]), " ".join(tokens[1 + w:]), True
        # Recto: head, then number -- sometimes run into the first word.
        for w in (width, width - 1, width + 1):
            if not 0 < w < len(tokens) or not _same_head(" ".join(tokens[:w]), head):
                continue
            nxt = tokens[w]
            if nxt in ("*", "^") and w + 1 < len(tokens):
                w, nxt = w + 1, tokens[w + 1]
            if _beside_head(nxt, letters=False):
                seen.add(head)
                return " ".join(tokens[:w + 1]), " ".join(tokens[w + 1:]), True
            glued = re.match(r"^[*^]?[\dilIoO]{1,4}(?=[a-z])", nxt)
            if glued and re.search(r"\d", glued.group(0)):
                seen.add(head)
                rest = [nxt[glued.end():]] + tokens[w + 1:]
                return " ".join(tokens[:w]) + " " + glued.group(0), " ".join(rest), True
            if known:
                if _junk_number(nxt):
                    return " ".join(tokens[:w + 1]), " ".join(tokens[w + 1:]), True
                return " ".join(tokens[:w]), " ".join(tokens[w:]), False
    return "", text, False


# The words that open a division, in whatever case the book sets them.
# Capitalised, never lower case: "the union chapter to demand ..." is a
# sentence that happens to start a page.
_OPENER = re.compile(
    r"^(Chapter|CHAPTER|Appendix|APPENDIX|Book|BOOK|Part|PART)\s+(\S{1,8})(?:\s|$)|"
    r"^(Preface|PREFACE|Introduction|INTRODUCTION|Foreword|FOREWORD|Prologue|PROLOGUE|"
    r"Epilogue|EPILOGUE|Afterword|AFTERWORD|Conclusion|CONCLUSION)\b")


def is_division(title: str) -> bool:
    """Whether a title opens the book's text proper, not its front matter."""
    return bool(_NUMBERED.match(title) or _OPENER.match(title))


def split_heading(text: str, heads: list[str], seen: set | None = None) -> tuple[str, str]:
    """A chapter's title off the top of its first page, if it opens one.

    A page opens a division when it starts with a chapter word ("Chapter 2
    Prelude", "EPILOGUE", "APPENDIX II") or a chapter numeral ("XIX.-"), or
    in capitals that are a running head the following pages carry and the
    book has not shown yet ("MEMOIR OF FRANK TAYLOR").
    """
    seen = seen or set()
    tokens = text.split(" ")
    # "PREFACE 9 the fifteen million": a head the book uses too seldom to
    # learn, but a chapter word with a page number after it is furniture.
    m = _OPENER.match(text)
    if m and m.group(3) and len(tokens) > 1 and is_page_number(tokens[1]):
        return "", " ".join(tokens[2:])
    # A numeral OCR set in lower case, "v.— THE STRIFE OF PARTIES", begins no
    # run of capitals, so it is taken here with the capitals after it.
    m = re.match(r"^[xvil]{1,7}\s?\.?\s?[—\-]\s*", text)
    if m:
        after = text[m.end():].split(" ")
        width = _caps_run(after)
        if width:
            return (text[:m.end()] + " ".join(after[:width])).strip(), " ".join(after[width:])
    n = _caps_run(tokens)
    if n and n < len(tokens) and is_page_number(tokens[n]) and not _OPENER.match(text):
        return "", text
    run = " ".join(tokens[:n])
    # The book's own title can stand above the first chapter's heading:
    # "A SUBALTERN'S WAR CHAPTER I 1914 — 1916 BEGINNING ...".
    m = re.search(r"\b(?:" + _NUMERAL + r"|APPENDIX\b|CHAPTER\b)", run)
    if m and m.start():
        skip = len(run[:m.start()].split())
        tokens, n = tokens[skip:], n - skip
        run = " ".join(tokens[:n])
    if n and (_NUMBERED.match(run) or _OPENER.match(run)):
        return run, " ".join(tokens[n:])
    # Set in upper and lower case, the title's own words cannot be told from
    # the text's; the chapter word and number are title enough, with any
    # capitals after them ("Appendix A LANE SCHOOL CENSUS 1958-1969").
    m = _OPENER.match(text)
    if m:
        width = 2 if m.group(1) else 1
        more = _caps_run(tokens, width)
        width += more if more >= 2 or (more == 1 and len(tokens[width]) > 3) else 0
        return " ".join(tokens[:width]), " ".join(tokens[width:])
    if not n:
        return "", text
    for head in heads:
        if head in seen:
            continue
        if _norm(run).startswith(_norm(head)) and len(_norm(head)) >= 5:
            # Only the head's words: "BIBLIOGRAPHY CONTEMPORARY OR ALMOST ..."
            # is the title and then the first line of the list.
            width = len(head.split())
            return " ".join(tokens[:width]), " ".join(tokens[width:])
    return "", text


def roman_value(s: str) -> int | None:
    """The value of a well-formed roman numeral, or None."""
    if not re.fullmatch(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})", s or "") \
            or not s:
        return None
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        total += -v if b in vals and vals[b] > v else v
    return total


def tidy_title(run: str) -> str:
    """A heading as a chapter title: "XIX.- DUNKIRK, GHENT, AND BRUGES" ->
    "XIX. Dunkirk, Ghent, and Bruges"."""
    run = re.sub(r"\^", "", run)
    run = re.sub(r"^([xvil]+)\b", lambda m: m.group(1).upper(), run)
    run = re.sub(r"\s*\.?\s*[—\-]+\s*", ". ", run, count=1) \
        if re.match(r"^" + _NUMERAL, run) else run
    run = re.sub(r"\s*\.\s*[—\-]+\s*", ". ", run)
    run = re.sub(r"^(APPENDIX|CHAPTER|BOOK|PART)\s+([XVIL]+|\d+|[A-Z])\.?\s+(?=\S)", r"\1 \2. ",
                 run, flags=re.I)
    run = re.sub(r"^(PREFACE|INTRODUCTION|FOREWORD|PROLOGUE|EPILOGUE|AFTERWORD|CONCLUSION)"
                 r"\s+(?=\S)", r"\1. ", run, flags=re.I)
    run = re.sub(r"\s{2,}", " ", run)
    small = {"of", "and", "the", "at", "in", "on", "to", "for", "a", "an", "or", "by"}
    words = []
    for i, w in enumerate(run.split()):
        core = w.strip(".,;:()")
        if re.fullmatch(r"[XVIL]+|XXL", core) or re.search(r"\d", core) or \
                (i == 1 and re.fullmatch(r"[A-Z]\.?", w)):
            words.append(w.replace("XXL", "XXI"))
        elif i and core.lower() in small and not words[-1].endswith("."):
            words.append(w.lower())
        else:
            words.append(w[:1] + w[1:].lower())
    return " ".join(words).strip(" .")


# --------------------------------------------------------------------------- #
# Footnotes
# --------------------------------------------------------------------------- #
# A note's marker, as OCR reads a superscript: "*", "1", "1-", "^", "2".
# It can follow a word as well as a full stop, because the page so often
# ends in the middle of a sentence that finishes overleaf.
# "I" is a 1 as often as not, and a figure can be glued to the last word
# when that word breaks across the page: "Aude1 Hare MSS.", "con^ Lediard".
_NOTE_MARK = r"(?:[*†‡§I'’]|[1-9]-?|\^)"
_NOTE_START = re.compile(
    r"(?:\s(" + _NOTE_MARK + r")|(?<=[a-z])([1-9]|\^))\s+(?=[A-Z\"“])")
# "Ibid." as OCR spells it at the foot of a page: "J^id.", "jud.", "Jbid.".
_IBID = re.compile(r"^[IJjl1][\w^]{1,3}\.?$")


def split_notes(text: str) -> tuple[str, list[str]]:
    """Take the footnotes off the foot of a page.

    A note begins with its marker ("*", "2") and says where something came
    from: "Coxe, vol. ii., p. 69." The block is taken only when every note
    in it reads like that, so the last sentence of the page is never
    mistaken for one.
    """
    starts = [m for m in _NOTE_START.finditer(text) if m.start() > len(text) * 0.35]
    for m in starts:
        block = text[m.start():].strip()
        notes = [n.strip() for n in re.split(r"\s(?=" + _NOTE_MARK + r"\s+[A-Z\"“])",
                                              " " + block) if n.strip()]
        cites = [bool(_CITATION.search(n) or _IBID.match(n.split(None, 1)[-1]))
                 for n in notes]
        # A note can discuss rather than cite ("Every student of the Waterloo
        # campaign ..."), so the first must cite and most of the rest.
        if notes and len(block) < 1500 and cites[0] and                 sum(cites) * 2 >= len(cites) and all(len(n) < 600 for n in notes):
            return text[:m.start()].rstrip(), notes
    return text, []


def drop_markers(text: str) -> str:
    """Footnote references in the running text: "attacked."^ -> "attacked.".

    OCR reads a superscript figure as a caret, and prose never has one, so
    every caret goes, with the hyphen OCR sometimes puts before it.
    """
    return re.sub(r" {2,}", " ", re.sub(r"-?\^+[\d$]?", "", text))


# --------------------------------------------------------------------------- #
# Words the scan broke
# --------------------------------------------------------------------------- #
# Letter shapes OCR confuses, most of all in old type: "wliich" for "which",
# "EngHsh" for "English", "tfie" for "the", "rnen" for "men".
_CONFUSIONS = (("li", "h"), ("h", "li"), ("H", "li"), ("fi", "h"), ("rn", "m"),
               ("tl", "th"), ("ii", "u"), ("vv", "w"), ("VV", "W"))


def mend_words(text: str) -> str:
    """Rejoin words split by a lost hyphen, and undo OCR letter confusions.

    The book is its own dictionary: "Lou vain" is joined because "Louvain"
    appears elsewhere and more often than "Lou" or "vain" alone do, so "in
    to" -- where both halves are everywhere -- is left as it is. A misread
    word is replaced only by a spelling the book uses far more often.
    """
    words = re.findall(r"[A-Za-z]+", text)
    vocab = Counter(words)

    def join(m):
        a, b = m.group(1), m.group(2)
        whole = vocab[a + b]
        if whole >= 2 and whole > min(vocab[a], vocab[b]) and len(a) >= 2 and len(b) >= 2:
            return a + b
        return m.group(0)

    text = re.sub(r"\b([A-Z]?[a-z]+) ([a-z]+)\b", join, text)

    def fix(m):
        w = m.group(0)
        if len(w) < 3:
            return w
        best, best_n = w, 0
        for wrong, right in _CONFUSIONS:
            at = w.find(wrong)
            while at != -1:
                cand = w[:at] + right + w[at + len(wrong):]
                # A misreading can recur ("alHes" a dozen times), but the
                # right spelling is still at least twice as common.
                if vocab[cand] >= 5 and vocab[cand] > max(best_n, 2 * vocab[w]):
                    best, best_n = cand, vocab[cand]
                at = w.find(wrong, at + 1)
        return best

    return re.sub(r"[A-Za-z]+", fix, text)


def join_pages(texts: list[str]) -> str:
    """Pages into running text: a word broken at the foot of one page is
    joined to its end at the top of the next."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if out.endswith("-") and t[:1].islower():
            out = out[:-1] + t
        else:
            out = (out + " " + t) if out else t
    return out


# --------------------------------------------------------------------------- #
# The whole book
# --------------------------------------------------------------------------- #
@dataclass
class ScanReport:
    pages: int = 0
    unreadable: int = 0
    heads_cut: int = 0
    notes_cut: int = 0
    front_pages: int = 0
    apparatus: list[str] = field(default_factory=list)


def rebuild(pages: list[tuple[str, bool]], *, keep_apparatus: bool = False,
            log=None) -> tuple[list[tuple[str, str]], ScanReport]:
    """[(page text, readable)] in reading order -> [(title, text)] divisions.

    Pages the scan itself marks unreadable (bookplates, maps) are left out.
    Everything before the first chapter heading is front matter -- title
    page, contents, errata -- and is left out too, as are the index and
    bibliography unless `keep_apparatus`.
    """
    report = ScanReport(pages=len(pages))
    readable = [re.sub(r"\s+", " ", t).strip() for t, ok in pages if ok]
    report.unreadable = len(pages) - len(readable)
    heads = learn_heads(readable)

    divisions: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for text in readable:
        head, body, numbered = strip_head(text, heads, seen)
        report.heads_cut += bool(head)
        # A chapter can open under the book's title, set like its running
        # head but with no page number: "A SUBALTERN'S WAR CHAPTER I 1914".
        # Under a numbered head the page is running text, whatever it says
        # -- a contents page, a memo quoted in full, "the union chapter".
        title, rest = split_heading(body, heads, seen)
        if title and (not head or (not numbered and is_division(title))):
            body = rest
        else:
            title = ""
        # A contents page or list of plates inside the book -- between the
        # preface and the first chapter -- opens a division of its own, to be
        # left out with the index rather than read at the end of the preface.
        m = _LISTING.match(body)
        if not title and m:
            title, body = m.group(1), body[m.end():]
        body, notes = split_notes(body)
        report.notes_cut += len(notes)
        body = drop_markers(body)
        if title:
            divisions.append((title, [body]))
        elif divisions:
            divisions[-1][1].append(body)
        else:
            report.front_pages += 1

    # A title page carries the book's title, which is also a running head, so
    # it reads as a heading. When the book numbers its chapters, the text
    # starts at the first numbered one; what comes before is front matter.
    numbered = [i for i, (title, _) in enumerate(divisions) if is_division(title)]
    if numbered and numbered[0]:
        report.front_pages += sum(len(b) for _, b in divisions[:numbered[0]])
        divisions = divisions[numbered[0]:]

    if not divisions:
        # No headings found: better the whole text, furniture cut, than none.
        body = join_pages([drop_markers(split_notes(strip_head(t, heads)[1])[0])
                           for t in readable])
        return [("", mend_words(body))], report

    out = []
    chapters, letter, numeral = 0, "", 0
    for title, bodies in divisions:
        # OCR reads a numeral's last I as L: "VIL.", "VIIL.", "XL." for XI.
        # The chapter before says which number this one must be.
        m = re.match(r"^([XVILxvil]+)(\s?\.?\s?[—\-].*)$", title)
        if m:
            seen_as = m.group(1).upper()
            value = roman_value(seen_as)
            if numeral and value != numeral + 1:
                fixed = seen_as.replace("L", "I")
                if roman_value(fixed) == numeral + 1:
                    seen_as, value = fixed, numeral + 1
            title = seen_as + m.group(2)
            numeral = value or numeral
        # "Chapter |", "Chapter &": a number OCR could not read is the
        # chapter's place in the book.
        m = re.match(r"^(chapter)\s+(\S+)(.*)$", title, re.I)
        if m:
            chapters += 1
            if not re.fullmatch(r"\d+|[IVXLC]+", m.group(2)):
                title = f"{m.group(1)} {chapters}{m.group(3)}"
        # "Appendix DO" after "Appendix C" is Appendix D.
        m = re.match(r"^(appendix)\s+(\S+)(.*)$", title, re.I)
        if m:
            label = m.group(2).strip(".")
            if re.fullmatch(r"[A-Z]", label):
                letter = label
            elif letter and not re.fullmatch(r"\d+|[IVXLC]+", label):
                letter = chr(ord(letter) + 1)
                title = f"{m.group(1)} {letter}{m.group(3)}"
        text = title + " " + " ".join(bodies)
        figures = sum(ch.isdigit() for ch in text) / max(1, sum(not ch.isspace() for ch in text))
        # A statistical appendix -- a census, an attendance table -- is
        # figures in columns, and read aloud it is a string of numbers.
        if (_APPARATUS.match(tidy_title(title)) or figures > 0.2) and not keep_apparatus:
            if tidy_title(title) not in report.apparatus:
                report.apparatus.append(tidy_title(title))
            continue
        out.append((tidy_title(title), mend_words(join_pages(bodies))))
    if log:
        log(f"• Scanned book: {report.pages} pages, {report.unreadable} unreadable "
            f"(maps, plates) left out, {report.front_pages} of front matter, "
            f"{report.heads_cut} running heads and {report.notes_cut} footnotes cut; "
            f"{len(out)} division(s)"
            + (f"; left out {', '.join(report.apparatus)}" if report.apparatus else "")
            + ".")
    return out, report
