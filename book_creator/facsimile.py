"""A scanned book, re-presented as a modern print edition.

Library scans -- the Internet Archive's above all -- carry the whole object:
the cloth covers, the patterned endpapers, blank leaves with pencil marks, the
library's date-due slip and barcode. And they are cropped to the paper, so
the text runs almost to the edge of the page and a printer's margins are
nowhere. Printed as they are, they make a poor book.

This keeps every page of the book itself exactly as it was printed -- so its
contents, index, errata and cross-references still point at the right page --
and changes only what surrounds it:

1. each page is classified, from its picture and the scan's own text layer:
   cover, endpaper, library furniture, blank, plate, or a page of the book;
2. the kept pages are cleaned -- yellowed paper whitened, bleed-through and
   pencil faded -- and set in greyscale unless colour is asked for;
3. each is placed at its original size on a modern trim, with a proper gutter,
   recto and verso alternating as they did in the original: a blank is put
   back wherever a page would otherwise land on the wrong side;
4. a new title page and a copyright page for this edition go in front.

Every decision can be overridden from a plain file in input/, and a contact
sheet shows them all.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
# What a library adds to a book: its date-due slip, bookplate, barcode label.
_LIBRARY = re.compile(
    r"date (due|stamped)|due on the last date|renew|library|libraries|"
    r"university of|form l\d|return this|circulation|regional .{0,20}facility|"
    r"this book is", re.I)
# The publisher's own notice on the back of the title page. The new edition
# carries its own, so the old one goes when it stands alone on its page.
_IMPRINT = re.compile(
    r"copyright|all rights reserved|printed in|printed by|first published|"
    r"reprinted|made in", re.I)
_WORD = re.compile(r"[A-Za-z]{3,}")
# Characters OCR produces from a pattern or a picture, and type never shows.
_JUNK = re.compile(r"[\^<>%«»■•|{}~\\]|[a-z][A-Z]{2,}|[A-Z]{2,}[a-z][A-Z]")

KINDS = ("cover", "endpaper", "library", "blank", "imprint", "plate", "text")
KEPT = ("plate", "text")


@dataclass
class PageInfo:
    index: int              # 0-based, in the scan
    kind: str = "text"
    reason: str = ""
    words: int = 0          # real words in the scan's text layer
    junk: float = 0.0       # share of OCR tokens with characters print never has
    ink: float = 0.0        # share of the page printed on
    colour: float = 0.0     # mean saturation: cloth covers, coloured maps
    odd_size: bool = False  # not the book's page: a fold-out, photographed whole
    text: str = ""

    @property
    def readable(self) -> bool:
        """Text, not OCR of a pattern: an endpaper reads "'^/^8MINn JVAN".

        Judged by the junk, not by the share of words -- an index is mostly
        page numbers ("ii. 302, 314, 318") and is as readable as a page gets.
        """
        return self.words >= 3 and self.junk < 0.2


def _measure(page) -> tuple[float, float]:
    """(ink, colour) from a small rendering of the page.

    Ink is measured against the page's own paper, not against white: a
    yellowed page is not a printed one, and bleed-through from the other side
    is far fainter than print.
    """
    import numpy as np

    pix = page.get_pixmap(dpi=40)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
    rgb = rgb.astype(np.float32)
    # A margin's worth in from the edge: scanner shadows and the page edge
    # are not the page.
    h, w = rgb.shape[:2]
    rgb = rgb[h // 20: h - h // 20, w // 16: w - w // 16]
    grey = rgb.mean(axis=2)
    paper = np.percentile(grey, 90)
    ink = float((grey < paper - 70).mean())
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    colour = float(((mx - mn) / np.maximum(mx, 1)).mean())
    return ink, colour


def _measure_one(job: tuple[str, int, int]) -> list[tuple[float, float]]:
    import fitz

    src, lo, hi = job
    doc = fitz.open(src)
    return [_measure(doc[i]) for i in range(lo, hi)]


def _measure_all(doc) -> list[tuple[float, float]]:
    """(ink, colour) for every page, measured in parallel.

    Rendering a page means decoding its full scan, however small the
    rendering: 580 pages took two and a half minutes one after another.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor

    n = len(doc)
    if not doc.name or n < 40:
        return [_measure(doc[i]) for i in range(n)]
    step = 20
    jobs = [(doc.name, lo, min(n, lo + step)) for lo in range(0, n, step)]
    out: list[tuple[float, float]] = []
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
        for part in pool.map(_measure_one, jobs):
            out.extend(part)
    return out


def classify_cached(src) -> list[PageInfo]:
    """classify(), remembered on disk by the scan's size and date."""
    import json

    import fitz

    src = Path(src)
    st = src.stat()
    cache = Path("cache") / "facsimile" / f"{src.stem}-{st.st_size}-{st.st_mtime_ns}.json"
    if cache.exists():
        return [PageInfo(**d) for d in json.loads(cache.read_text(encoding="utf-8"))]
    infos = classify(fitz.open(str(src)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([vars(p) for p in infos]), encoding="utf-8")
    return infos


def _real_words(text: str) -> int:
    """Words that look like words: OCR of a bookplate or a pattern is not."""
    words = _WORD.findall(text)
    good = [w for w in words if w.islower() or w.istitle() or w.isupper()]
    vowels = [w for w in good if re.search(r"[aeiouyAEIOUY]", w)]
    return len(vowels)


def classify(doc) -> list[PageInfo]:
    """What each page of a scan is."""
    from collections import Counter

    sizes = Counter((round(pg.rect.width / 10), round(pg.rect.height / 10)) for pg in doc)
    usual = sizes.most_common(1)[0][0]
    measured = _measure_all(doc)
    infos: list[PageInfo] = []
    for i, page in enumerate(doc):
        text = " ".join(page.get_text().split())
        ink, colour = measured[i]
        size = (round(page.rect.width / 10), round(page.rect.height / 10))
        odd = abs(size[0] - usual[0]) > 2 or abs(size[1] - usual[1]) > 2
        tokens = text.split()
        junk = sum(bool(_JUNK.search(t)) for t in tokens) / max(1, len(tokens))
        infos.append(PageInfo(index=i, words=_real_words(text), junk=junk,
                              ink=ink, colour=colour, odd_size=odd, text=text))

    def content(p: PageInfo) -> bool:
        return p.readable and not _library(p) and not p.odd_size

    # The book block: from its first printed page to its last. Everything
    # outside it -- covers, endpapers, the slip and the barcode -- is binding.
    first = next((p.index for p in infos if content(p)), 0)
    last = next((p.index for p in reversed(infos) if content(p)), len(infos) - 1)

    # Maps bound in at the back, after the index, are the book's too. The
    # block runs on over pictures, and over the blank stubs between fold-outs,
    # until it meets the binding.
    def picture(p: PageInfo) -> bool:
        return not _library(p) and p.colour < 0.5 and (
            (p.odd_size and p.ink >= 0.001) or (p.ink >= 0.02 and not p.readable))

    k = last + 1
    while k < len(infos) and (picture(infos[k]) or (infos[k].ink < 0.004 and k + 1 < len(infos)
                                                    and picture(infos[k + 1]))):
        if picture(infos[k]):
            last = k
        k += 1
    for p in infos:
        if p.index < first or p.index > last:
            if p.colour > 0.5:
                p.kind, p.reason = "cover", "solid colour outside the book block"
            elif _library(p):
                p.kind, p.reason = "library", "library slip or label"
            elif p.ink < 0.004:
                p.kind, p.reason = "blank", "blank leaf outside the book block"
            else:
                p.kind, p.reason = "endpaper", "outside the book block"
        elif _library(p) and p.words < 40:
            p.kind, p.reason = "library", "library slip or label"
        elif p.odd_size and p.ink >= 0.001:
            p.kind, p.reason = "plate", "a fold-out, photographed whole"
        elif p.ink < 0.004 and not p.readable:
            p.kind, p.reason = "blank", "no print (bleed-through, pencil and fold stubs ignored)"
        elif p.words < 12 and p.ink >= 0.02:
            p.kind, p.reason = "plate", "a picture with little text: map or plate"
        elif p.words < 60 and _IMPRINT.search(p.text) and p.index < first + 12:
            p.kind, p.reason = "imprint", "the original publisher's notice"
        else:
            p.kind, p.reason = "text", ""
    return infos


def _library(p: PageInfo) -> bool:
    return bool(_LIBRARY.search(p.text)) and p.words < 80


# --------------------------------------------------------------------------- #
# Sides: every page lands where it did in the original
# --------------------------------------------------------------------------- #
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def _roman(s: str) -> int | None:
    s = s.lower()
    if not s or any(ch not in _ROMAN for ch in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = _ROMAN[a]
        total += -v if b in _ROMAN and _ROMAN[b] > v else v
    return total


def printed_number(text: str) -> int | None:
    """The page number printed in a running head: "2 THE WARS ..." or
    "ALMANZA, STOLLHOFEN, AND TOULON 3 ...", arabic or roman ("viii").

    Only a number beside a run of capitals counts, so a figure in the first
    line of the text ("25,400 men") is never taken for one.
    """
    tokens = text.split()[:12]
    if len(tokens) < 2:
        return None

    def num(t):
        t = t.strip(".,")
        if re.fullmatch(r"\d{1,3}", t):
            return int(t)
        return _roman(t) if re.fullmatch(r"[ivxlc]{1,6}", t) else None

    caps = lambda t: bool(re.fullmatch(r"[A-Z][A-Z,.'’\-]*|OF|AND|THE", t))
    n = num(tokens[0])
    if n is not None and caps(tokens[1]):
        return n
    k = 0
    while k < len(tokens) and caps(tokens[k]):
        k += 1
    if 0 < k < len(tokens):
        return num(tokens[k])
    return None


def sides(infos: list[PageInfo]) -> dict[int, str]:
    """"recto" or "verso" for each kept page, where the original had it.

    The book's leaves are counted from its first page to its last, blanks
    included -- a blank verso is still a side -- but not the fold-outs and
    their stubs, which were photographed as extra images, nor any plate. Each printed page
    number says which side its page is on; the side of every page follows
    from its place in that count, by the local majority of its numbered
    neighbours, so one misread number ("12" as "i3") cannot move a page.
    """
    block = [p for p in infos if p.kind in KEPT or p.kind == "blank"]
    if not block:
        return {}
    lo, hi = block[0].index, block[-1].index
    inside = infos[lo:hi + 1]

    def stub(p: PageInfo) -> bool:
        near = [q for q in infos[max(0, p.index - 1): p.index + 2] if q is not p]
        return p.kind == "blank" and any(q.odd_size and q.kind == "plate" for q in near)

    # A plate is tipped in: it takes no number in the book's count, and nor
    # does the blank back of a fold-out.
    leaves = [p for p in inside if p.kind in ("text", "blank") and not stub(p)]
    votes: list[tuple[int, int]] = []           # (leaf position, parity offset)
    for k, p in enumerate(leaves):
        if p.kind != "text":
            continue
        n = printed_number(p.text)
        if n is not None:
            votes.append((k, (k + (0 if n % 2 else 1)) % 2))
    out: dict[int, str] = {}
    if not votes:
        return out
    for k, p in enumerate(leaves):
        if p.kind != "text":
            continue
        near = sorted(votes, key=lambda v: abs(v[0] - k))[:9]
        offset = 1 if sum(v[1] for v in near) * 2 > len(near) else 0
        out[p.index] = "recto" if (k - offset) % 2 == 0 else "verso"
    return out


@dataclass
class Slot:
    """One page of the new book."""
    kind: str               # "page", "blank", "front"
    index: int | None = None
    note: str = ""


def plan(infos: list[PageInfo], *, front_pages: int = 2) -> list[Slot]:
    """The new book's pages, blanks put back only where a side needs one."""
    side_of = sides(infos)
    slots: list[Slot] = [Slot("front", note=n) for n in ("title", "copyright")[:front_pages]]
    for p in infos:
        if p.kind not in KEPT:
            continue
        want = side_of.get(p.index)
        here = "recto" if len(slots) % 2 == 0 else "verso"
        if want and want != here:
            slots.append(Slot("blank", note=f"so scan page {p.index + 1} stays a {want}"))
        slots.append(Slot("page", p.index, p.kind))
    if len(slots) % 2:
        slots.append(Slot("blank", note="the last leaf's back"))
    return slots


# --------------------------------------------------------------------------- #
# Overrides: input/<scan>-pages.md
# --------------------------------------------------------------------------- #
def read_overrides(path: Path) -> dict[int, str]:
    """{scan page (1-based): kind} from lines like "drop 5", "keep 576",
    "plate 8" -- the classification is a guess, and the person holding the
    book decides."""
    out: dict[int, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*[-*]?\s*(drop|keep|text|plate)\s+([\d ,\-–]+)", line, re.I)
        if not m:
            continue
        kind = {"drop": "dropped", "keep": "text"}.get(m.group(1).lower(), m.group(1).lower())
        for part in re.split(r"[ ,]+", m.group(2).strip()):
            if not part:
                continue
            a, _, b = part.replace("–", "-").partition("-")
            for n in range(int(a), int(b or a) + 1):
                out[n] = kind
    return out


def apply_overrides(infos: list[PageInfo], overrides: dict[int, str]) -> None:
    for p in infos:
        kind = overrides.get(p.index + 1)
        if kind:
            p.kind, p.reason = kind, "set by hand"


# --------------------------------------------------------------------------- #
# Cleaning a page
# --------------------------------------------------------------------------- #
DPI = 300


def clean_image(page, *, colour: bool = False, edges: bool = True):
    """The page as print wants it: paper white, ink black, stains gone.

    Levels are set from the page itself -- its paper and its darkest print --
    so a yellowed page and a fresh one come out alike, and what is fainter
    than print (bleed-through, foxing, pencil) fades towards the white.
    """
    import fitz
    import numpy as np
    from PIL import Image

    cs = fitz.csRGB if colour else fitz.csGRAY
    pix = page.get_pixmap(dpi=DPI, colorspace=cs)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    arr = arr.astype(np.float32)
    grey = arr.mean(axis=2) if arr.shape[2] > 1 else arr[..., 0]
    paper = float(np.percentile(grey, 88))
    # On a page with almost nothing printed -- a half-title -- the darkest
    # percentile is paper, and stretching it turned the whole page grey. Print
    # is at least this much darker than its paper, whatever the page.
    # And printer's ink is black: never lighter than about 80 in 255, however
    # much of the darkest half-percent of a page is a shadow at its corner.
    ink = min(float(np.percentile(grey, 0.5)), paper - 110.0, 80.0)
    span = max(paper - ink - 6.0, 30.0)
    out = np.clip((arr - ink) / span, 0.0, 1.0)
    if edges:                   # never on a map: its lines run to the edge
        out = _clear_edges(out)
        out = _clear_perforations(out)
    # Near-white is paper: the grain of it, the scanner's edge of the page,
    # the ghost of the other side. Made pure white, it also costs nothing to
    # store -- the grain is what made a 570-page book 400 MB.
    out[out > 0.86] = 1.0
    out = (out ** 1.15) * 255.0          # keep thin strokes from washing out
    out = out.astype(np.uint8)
    if out.shape[2] == 1:
        return Image.fromarray(out[..., 0], "L")
    return Image.fromarray(out, "RGB")


def _clear_edges(out):
    """Whiten grey that reaches the edge of the picture.

    A folded corner, the shadow of the scanner's lid, the fold of a map: grey
    wedges at the page's edge, darker than paper and lighter than print, that
    whitening the paper leaves behind. Type never touches the edge and is
    darker than they are, so what is grey and connected to the border goes.
    """
    import numpy as np

    try:
        from scipy import ndimage
    except ImportError:          # a nicety: without scipy the wedges stay
        return out
    grey = out.mean(axis=2) if out.shape[2] > 1 else out[..., 0]
    mid = (grey > 0.3) & (grey < 0.95)
    labels, n = ndimage.label(mid)
    if not n:
        return out
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge = edge[edge > 0]
    if edge.size:
        out[np.isin(labels, edge)] = 1.0
    return out


def _clusters(points: list[tuple[float, float]], reach: float) -> list[list[tuple[float, float]]]:
    """Points grouped with whatever lies within `reach` of them."""
    import numpy as np

    if not points:
        return []
    pts = np.array(points, dtype=float)
    seen = np.zeros(len(pts), dtype=bool)
    groups = []
    for start in range(len(pts)):
        if seen[start]:
            continue
        queue, group = [start], []
        seen[start] = True
        while queue:
            i = queue.pop()
            group.append((float(pts[i][0]), float(pts[i][1])))
            d = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1])
            for j in np.nonzero((d < reach) & ~seen)[0]:
                seen[j] = True
                queue.append(int(j))
        groups.append(group)
    return groups


def _clear_perforations(out, dpi: int = DPI):
    """Whiten a library's perforated stamp: "UNIV. OF CALIFORNIA ... LIBRARY"
    punched through the title page as letters made of round holes.

    A hole is a small round dot, but so is a full stop, so is a contents
    page's leader, and so are the letters o, e and c at the size a book sets
    them. What tells a stamp apart is that its holes are a grid: dozens of
    them, evenly spaced, with nothing else between them. Only a cluster that
    is both regular and almost purely dots is taken -- and inside it, the
    faint rims and half-holes that whitening the paper leaves behind.
    """
    import numpy as np

    try:
        from scipy import ndimage
    except ImportError:          # a nicety: without scipy the stamp stays
        return out
    grey = out.mean(axis=2) if out.shape[2] > 1 else out[..., 0]
    # Fainter than print: a stamp's holes can be, and whole words of one can
    # be nearly invisible. Nothing is removed on the strength of being faint
    # -- the geometry below is what decides.
    labels, n = ndimage.label(grey < 0.9)
    if not n:
        return out
    scale = dpi / 300.0
    boxes = ndimage.find_objects(labels)
    areas = np.bincount(labels.ravel())
    dots, centres = [], []
    for k, box in enumerate(boxes, start=1):
        if box is None:
            continue
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start
        cy, cx = (box[0].start + box[0].stop) / 2, (box[1].start + box[1].stop) / 2
        centres.append((cy, cx, k, max(h, w)))
        if not (4 * scale <= h <= 22 * scale and 4 * scale <= w <= 22 * scale):
            continue
        # Round, and reasonably filled: a faint hole comes back as a ring
        # rather than a disc, so this is generous. The geometry decides.
        if max(h, w) > 1.6 * min(h, w) or areas[k] < 0.3 * h * w:
            continue
        dots.append((k, cy, cx))
    if len(dots) < 25:
        return out

    reach = 40 * scale
    groups = [g for g in _clusters([(y, x) for _, y, x in dots], reach) if len(g) >= 25]
    if not groups:
        return out
    pts = np.array([(y, x) for _, y, x in dots])
    mask = np.zeros(labels.shape, dtype=bool)
    pad = round(20 * scale)
    took = False
    for group in groups:
        g = np.array(group)
        # Evenly spaced, as punched holes are and letters are not: each hole's
        # nearest neighbour is the same distance away as every other's.
        steps = []
        for y, x in group:
            d = np.hypot(g[:, 0] - y, g[:, 1] - x)
            steps.append(d[d > 0].min())
        steps = np.array(steps)
        if steps.mean() <= 0 or steps.std() / steps.mean() > 0.35:
            continue
        # Several rows deep, as a stamp's letters are: a line of small
        # capitals is evenly spaced too, and one row of it is not a stamp.
        step = steps.mean()
        if np.ptp(g[:, 0]) < 3 * step or np.ptp(g[:, 1]) < 3 * step:
            continue
        y0, y1 = max(0, round(g[:, 0].min()) - pad), round(g[:, 0].max()) + pad
        x0, x1 = max(0, round(g[:, 1].min()) - pad), round(g[:, 1].max()) + pad
        # And with the place to themselves: a line of type has letters in it
        # that are nothing like a hole, and is left alone.
        inside = [(k, big) for cy, cx, k, big in centres if y0 <= cy <= y1 and x0 <= cx <= x1]
        holes = {k for k, y, x in dots if y0 <= y <= y1 and x0 <= x <= x1}
        # Mostly holes: a faint stamp breaks into fragments as well, so this
        # is loose. What keeps type out is the size test below -- no letter a
        # book sets is as small as a hole.
        if len(inside) and len(holes) < 0.5 * len(inside):
            continue
        if any(big > 26 * scale for _, big in inside):
            continue                           # something larger than a hole
        took = True
        mask[y0:y1, x0:x1] |= np.isin(labels[y0:y1, x0:x1], list(holes))
        # The rims and half-holes among them, whatever their shape.
        block = out[y0:y1, x0:x1]
        block[grey[y0:y1, x0:x1] > 0.45] = 1.0
    if not took:
        return out
    mask = ndimage.binary_dilation(mask, iterations=max(1, round(2 * scale)))
    out[mask] = 1.0
    return out


def _jpeg(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82, dpi=(DPI, DPI), optimize=True)
    return buf.getvalue()


@dataclass
class Encoded:
    """A page image ready for the PDF: a JPEG, or raw 4-bit grey rows."""
    data: bytes
    width: int
    height: int
    jpeg: bool


def encode(img) -> Encoded:
    """A page image as the PDF will store it.

    Type on white is the worst case for JPEG: 585 KB a page. Sixteen greys
    keep the edges of the letters smooth, and stored as a 4-bit grey image --
    which PDF has, and which PyMuPDF's own insertion would widen to 8 bits --
    a page costs about 250 KB. A colour plate stays a JPEG.
    """
    import zlib

    import numpy as np

    if img.mode == "RGB":
        return Encoded(_jpeg(img), img.width, img.height, True)
    a = (np.asarray(img, dtype=np.uint8) // 17).astype(np.uint8)       # 0..15
    if a.shape[1] % 2:
        a = np.pad(a, ((0, 0), (0, 1)), constant_values=15)
    packed = (a[:, 0::2] << 4) | a[:, 1::2]
    # Level 6, not 9: a few percent larger, many times faster over 500 pages.
    return Encoded(zlib.compress(packed.tobytes(), 6), img.width, img.height, False)


def _place(book, page, rect, enc: Encoded) -> None:
    """Draw an encoded image on a page of `book` (PyMuPDF)."""
    import fitz

    if enc.jpeg:
        page.insert_image(rect, stream=enc.data)
        return
    xref = book.get_new_xref()
    book.update_object(xref, (
        f"<< /Type /XObject /Subtype /Image /Width {enc.width} /Height {enc.height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 4 /Filter /FlateDecode >>"))
    book.update_stream(xref, enc.data, compress=False)
    # update_stream takes the filter off an uncompressed write; the data was
    # deflated in the worker, so it goes back on.
    book.xref_set_key(xref, "Filter", "/FlateDecode")
    page.insert_image(rect, xref=xref)
    del fitz


def _prepare(job: tuple[str, int, bool, bool, float]) -> tuple[int, Encoded, float, float]:
    """One page cleaned and encoded, in a worker process: (index, image,
    width, height in points as it will be drawn before scaling)."""
    import fitz

    src, index, colour, plate, room_w = job
    page = fitz.open(src)[index]
    img = clean_image(page, colour=colour, edges=not plate)
    iw, ih = page.rect.width, page.rect.height
    if plate and iw > ih and iw > room_w:
        img = img.rotate(90, expand=True)                 # a fold-out, turned
        iw, ih = ih, iw
    return index, encode(img), iw, ih


# --------------------------------------------------------------------------- #
# The new book
# --------------------------------------------------------------------------- #
# KDP's minimum inside margin by page count (inches).
_GUTTER = ((150, 0.375), (300, 0.5), (500, 0.625), (700, 0.75), (828, 0.875))
OUTSIDE_MIN = 0.4


def gutter_for(pages: int) -> float:
    return next((g for n, g in _GUTTER if pages <= n), _GUTTER[-1][1])


@dataclass
class Edition:
    title: str
    author: str
    subtitle: str = ""          # "Volume II · 1707–1709"
    editor: str = ""
    source: str = ""            # "Oxford: Basil Blackwell, 1921"
    holder: str = ""
    year: int = 2026
    publisher: str = ""
    credit: str = ""            # where the scan came from


def _lines(c, text, font, size, max_w):
    words, out, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if c.stringWidth(t, font, size) <= max_w or not cur:
            cur = t
        else:
            out.append(cur)
            cur = wd
    return out + ([cur] if cur else [])


def _front_matter(c, which: str, ed: Edition, font, w: float, h: float) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import inch

    ink = HexColor("#241f1a")
    c.setFillColor(ink)
    cx = w / 2
    if which == "title":
        y = h - 2.4 * inch
        for line in _lines(c, ed.title.upper(), font[2], 26, w - 1.6 * inch):
            c.setFont(font[2], 26)
            c.drawCentredString(cx, y, line)
            y -= 34
        if ed.subtitle:
            c.setFont(font[0], 14)
            c.drawCentredString(cx, y - 8, ed.subtitle)
            y -= 30
        c.setStrokeColor(ink)
        c.setLineWidth(0.6)
        c.line(cx - 0.6 * inch, y - 6, cx + 0.6 * inch, y - 6)
        c.setFont(font[0], 15)
        c.drawCentredString(cx, y - 44, ed.author)
        if ed.editor:
            c.setFont(font[1], 11.5)
            c.drawCentredString(cx, y - 66, f"edited by {ed.editor}")
        c.setFont(font[1], 10.5)
        c.drawCentredString(cx, 1.5 * inch, "A facsimile of the edition")
        if ed.source:
            c.drawCentredString(cx, 1.5 * inch - 15, f"published {ed.source}")
        return

    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Frame, Paragraph

    style = ParagraphStyle("c", fontName=font[0], fontSize=9, leading=12.5,
                           textColor=ink, alignment=TA_LEFT, spaceAfter=7)
    holder = ed.holder or "the publisher"
    paras = [
        f"<i>{ed.title}</i>{' — ' + ed.subtitle if ed.subtitle else ''}, by {ed.author}"
        + (f", edited by {ed.editor}" if ed.editor else "") + ".",
        f"First published {ed.source}. The text of that edition is in the public "
        "domain, and is reproduced here in facsimile, page for page: its contents, "
        "index and references keep their original page numbers.",
        ed.credit,
        "This edition — its selection, cleaning and arrangement of the pages, and "
        f"its new matter — © {ed.year} {holder}.",
        ed.publisher,
    ]
    frame = Frame(0.9 * inch, 0.9 * inch, w - 1.8 * inch, 3.2 * inch, showBoundary=0)
    frame.addFromList([Paragraph(p, style) for p in paras if p], c)


@dataclass
class Result:
    pdf: str
    pages: int
    trim: tuple[float, float]
    gutter: float
    infos: list[PageInfo] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)


def build(src, out, ed: Edition, *, trim: tuple[float, float] = (6.0, 9.0),
          colour_plates: bool = False, overrides: Path | None = None,
          font_family: str = "Cardo", log=print, on_progress=None) -> Result:
    """The scan at `src`, as a print-ready interior at `out`."""
    import fitz
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    from . import fonts

    doc = fitz.open(str(src))
    infos = classify_cached(src)
    if overrides:
        apply_overrides(infos, read_overrides(overrides))
    slots = plan(infos)
    counts = {k: sum(p.kind == k for p in infos) for k in (*KINDS, "dropped")}
    log(f"• {Path(src).name}: {len(doc)} scanned pages — "
        + ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        + f"; {sum(s.kind == 'blank' for s in slots)} blank(s) put back.")

    W, H = trim[0] * inch, trim[1] * inch
    gutter = gutter_for(len(slots)) * inch
    outside = OUTSIDE_MIN * inch
    font = fonts.register(font_family)
    # The new pages are typeset by ReportLab, in the book's embedded font --
    # never its default Helvetica, which KDP rejects unembedded.
    fronts = [s.note for s in slots if s.kind == "front"]
    front_pdf = io.BytesIO()
    c = canvas.Canvas(front_pdf, pagesize=(W, H), initialFontName=font[0])
    for which in fronts:
        _front_matter(c, which, ed, font, W, H)
        c.showPage()
    c.save()
    front = fitz.open("pdf", front_pdf.getvalue())

    # The scanned pages are placed by PyMuPDF, which stores a sixteen-grey PNG
    # as it is; ReportLab would expand it back to full greys first.
    room_w, room_h = W - gutter - outside, H - 2 * outside
    # Cleaning is the slow part -- a second a page -- and pages are independent.
    import os
    from concurrent.futures import ProcessPoolExecutor

    jobs = [(str(src), s.index, colour_plates and infos[s.index].kind == "plate",
             infos[s.index].kind == "plate", room_w) for s in slots if s.kind == "page"]
    ready: dict[int, tuple[Encoded, float, float]] = {}
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
        for k, (index, data, iw, ih) in enumerate(pool.map(_prepare, jobs, chunksize=8)):
            ready[index] = (data, iw, ih)
            if on_progress:
                on_progress(k + 1, len(jobs))
            elif log and (k + 1) % 100 == 0:
                log(f"  … {k + 1} of {len(jobs)} pages cleaned")

    book = fitz.open()
    reduced = []
    f = 0
    for n, slot in enumerate(slots):
        recto = n % 2 == 0
        if slot.kind == "front":
            book.insert_pdf(front, from_page=f, to_page=f)
            f += 1
            continue
        pg = book.new_page(width=W, height=H)
        if slot.kind != "page":
            continue
        data, iw, ih = ready[slot.index]                      # points, as printed
        scale = min(1.0, room_w / iw, room_h / ih)
        if scale < 0.999:
            reduced.append(slot.index + 1)
        dw, dh = iw * scale, ih * scale
        # Centred in the room the margins leave, the gutter on the spine side.
        x = (gutter if recto else outside) + (room_w - dw) / 2
        y = (H - dh) / 2                                      # from the top, for fitz
        _place(book, pg, fitz.Rect(x, y, x + dw, y + dh), data)
    book.set_metadata({"title": f"{ed.title}{' — ' + ed.subtitle if ed.subtitle else ''}",
                       "author": ed.author})
    book.save(str(out), garbage=3, deflate=True)
    log(f"• {out}: {len(slots)} pages on {trim[0]:g} × {trim[1]:g} in, "
        f"{gutter / inch:g} in gutter"
        + (f"; page(s) {', '.join(map(str, reduced))} reduced to fit" if reduced else "")
        + ".")
    return Result(str(out), len(slots), trim, gutter / inch, infos, slots)


# --------------------------------------------------------------------------- #
# What was decided, for a person to check
# --------------------------------------------------------------------------- #
_SHEET_COLOURS = {"text": (46, 125, 50), "plate": (21, 101, 192), "cover": (183, 28, 28),
                  "endpaper": (183, 28, 28), "library": (183, 28, 28),
                  "blank": (158, 158, 158), "imprint": (230, 81, 0), "dropped": (183, 28, 28)}


def contact_sheet(src, infos: list[PageInfo], out, cols: int = 20) -> str:
    """Every scanned page, framed by what was decided about it."""
    import fitz
    from PIL import Image, ImageDraw

    doc = fitz.open(str(src))
    tw, th = 60, 96
    rows = -(-len(infos) // cols)
    sheet = Image.new("RGB", (cols * (tw + 8) + 8, rows * (th + 22) + 8), "white")
    draw = ImageDraw.Draw(sheet)
    for p in infos:
        pm = doc[p.index].get_pixmap(dpi=14)
        im = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        im.thumbnail((tw, th))
        x = 8 + (p.index % cols) * (tw + 8)
        y = 8 + (p.index // cols) * (th + 22)
        colour = _SHEET_COLOURS.get(p.kind, (0, 0, 0))
        sheet.paste(im, (x, y + 12))
        draw.rectangle([x - 2, y + 10, x + im.width + 1, y + 13 + im.height],
                       outline=colour, width=2)
        draw.text((x, y - 1), f"{p.index + 1} {p.kind[:5]}", fill=colour)
    sheet.save(str(out))
    return str(out)


def report(src, result: Result) -> str:
    """A plain account of every page left out and every blank put back."""
    name = Path(src).stem
    lines = [f"# {Path(src).name}: pages of the facsimile", "",
             f"{result.pages} pages, {result.trim[0]:g} × {result.trim[1]:g} in, "
             f"{result.gutter:g} in gutter.", "",
             "To change a decision, write lines like `drop 5`, `keep 576` or "
             f"`plate 8` (ranges too: `drop 2-4`) in `input/{name}-pages.md` "
             "and build again.", "", "## Left out", ""]
    lines += [f"- page {p.index + 1}: {p.kind}" + (f" — {p.reason}" if p.reason else "")
              for p in result.infos if p.kind not in KEPT]
    lines += ["", "## Plates", ""]
    lines += [f"- page {p.index + 1}: {p.reason}" for p in result.infos if p.kind == "plate"]
    lines += ["", "## Blanks put back", ""]
    lines += [f"- new page {i + 1}: {s.note}" for i, s in enumerate(result.slots)
              if s.kind == "blank"]
    return "\n".join(lines) + "\n"


def cloth_colour(src, infos: list[PageInfo]) -> str | None:
    """The colour of the original binding, for the new cover's accent.

    The scan photographed the cloth; its median colour, darkened until white
    type reads on it, carries the old book's look onto the new one.
    """
    import colorsys

    import fitz
    import numpy as np

    covers = [p for p in infos if p.kind == "cover"]
    if not covers:
        return None
    pix = fitz.open(str(src))[covers[0].index].get_pixmap(dpi=20)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
    r, g, b = (float(np.median(rgb[..., k])) / 255 for k in range(3))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(l, 0.32), s)
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (r, g, b)))


def overrides_path(src) -> Path:
    """Where a person's page decisions for a scan are kept: input/, beside it,
    so a rebuild never overwrites them."""
    return Path("input") / f"{Path(src).stem}-pages.md"


def write_overrides(path: Path, overrides: dict[int, str]) -> None:
    """The decisions file, rewritten from {scan page: kind}."""
    word = {"dropped": "drop", "text": "keep", "plate": "plate"}
    lines = ["# Pages of the scan decided by hand (read by book_creator.facsimile).",
             "# One per line: `drop 5`, `keep 576`, `plate 8`; ranges like `drop 2-4`.", ""]
    lines += [f"{word[k]} {n}" for n, k in sorted(overrides.items()) if k in word]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make(src, ed: Edition, *, trim=(6.0, 9.0), colour_plates=False,
         cover_style="typographic", blurb="", accent="", out: Path | None = None,
         log=print, on_progress=None) -> dict:
    """Interior, cover, contact sheet and report for a scan: {name: path}."""
    src = Path(src)
    out = Path(out or Path("output") / f"{src.stem}-facsimile.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    res = build(src, out, ed, trim=trim, colour_plates=colour_plates,
                overrides=overrides_path(src), log=log, on_progress=on_progress)
    made = {"pdf": str(out), "pages": res.pages}
    if cover_style and cover_style != "none":
        from . import cover
        from .model import FontSpec

        # Sized from the finished interior: the spine is the page count.
        wrap = out.with_name(f"{src.stem}-cover.pdf")
        _, (cw, ch, spine) = cover.render_cover(
            str(wrap), style=cover_style, title=ed.title, author=ed.author,
            src_lang="en", tgt_lang="en", trim=trim, pages=res.pages,
            font_spec=FontSpec(family="Cardo"), blurb=blurb,
            accent=accent or cloth_colour(src, res.infos),
            edition_line=ed.subtitle or None)
        log(f"• Cover → {wrap} ({cw:.3f} × {ch:.3f} in, spine {spine:.3f} in)")
        made["cover"] = str(wrap)
    made["sheet"] = contact_sheet(src, res.infos, out.with_name(f"{src.stem}-pages.png"))
    rep_path = out.with_name(f"{src.stem}-pages.md")
    rep_path.write_text(report(src, res), encoding="utf-8")
    made["report"] = str(rep_path)
    log(f"• Contact sheet → {made['sheet']}\n• Decisions → {rep_path}")
    return made


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="A scanned book as a modern print edition.")
    ap.add_argument("pdf")
    ap.add_argument("--classify", action="store_true",
                    help="only decide what each page is, and remember it")
    ap.add_argument("--title", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--editor", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--holder", default="")
    ap.add_argument("--credit", default="")
    ap.add_argument("--trim", default="6x9")
    ap.add_argument("--colour-plates", action="store_true")
    ap.add_argument("--cover-style", default="typographic",
                    help="a cover.py style; 'none' for no cover")
    ap.add_argument("--blurb", default="")
    ap.add_argument("--accent", default="",
                    help="cover accent colour; by default, the original cloth's")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    import sys

    # Its log has arrows and ellipses; a Windows console's code page has not.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.classify:
        infos = classify_cached(a.pdf)
        print(f"• classified {len(infos)} pages", flush=True)
        return 0
    if not (a.title and a.author):
        ap.error("--title and --author are needed to build")
    tw, th = (float(v) for v in a.trim.lower().split("x"))
    ed = Edition(a.title, a.author, a.subtitle, a.editor, a.source, a.holder,
                 credit=a.credit)
    def progress(done: int, total: int) -> None:
        # One line in ten pages: what the web app reads for its progress bar.
        if done % 10 == 0 or done == total:
            print(f"  … {done} of {total} pages cleaned", flush=True)

    make(a.pdf, ed, trim=(tw, th), colour_plates=a.colour_plates,
         cover_style=a.cover_style, blurb=a.blurb, accent=a.accent,
         out=Path(a.out) if a.out else None,
         log=lambda m: print(m, flush=True), on_progress=progress)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
