#!/usr/bin/env python
"""Fetch the 118 woodcuts of the 1517 Theuerdank from the Bayerische
Staatsbibliothek's digitised first edition.

Source: BSB Rar. 325 a, https://www.digitale-sammlungen.de/en/details/bsb00013106
(Public Domain Mark; 591 images). It is the hand-coloured copy. The manifest's
table of contents lists each woodcut by the page it sits on, 118 of them, so
nothing has to be guessed about which page is which.

A page carries a rubric and verse as well as the woodcut, so each is fetched
twice: once small, to find the woodcut's black frame, and then only that
rectangle at full resolution through the IIIF region parameter.

Writes cache/theuerdank/woodcuts/wc_<NNN>.jpg (the woodcut, colour, frame
included) and woodcuts.json (chapter -> canvas, page size, box).

    python fetch_woodcuts.py [--limit N]
"""
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ITEM = "bsb00013106"
BASE = "https://api.digitale-sammlungen.de/iiif"
HERE = Path(__file__).parent
OUT = HERE / "cache" / "theuerdank" / "woodcuts"
THUMB = 1000


def get(url: str) -> bytes:
    # curl rather than urllib: one archive.org node has an expired certificate,
    # and this keeps the fetchers alike.
    r = subprocess.run(["curl", "-sL", "-m", "180", url], capture_output=True)
    if r.returncode or not r.stdout:
        raise RuntimeError(f"fetch failed: {url}")
    return r.stdout


def longest_run(mask: np.ndarray) -> np.ndarray:
    """Per row, the longest run of True."""
    best = np.zeros(mask.shape[0], int)
    for i, row in enumerate(mask):
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        s, e = np.where(d == 1)[0], np.where(d == -1)[0]
        if len(s):
            best[i] = (e - s).max()
    return best


def find_frame(img: Image.Image) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of the woodcut, in pixels.

    A woodcut is the one block of the page that is mostly not paper: its rows
    are 40% or more ink and colour, where a line of script is under a quarter.
    The page's own edge is dark too (the book's fore-edge on the right), so the
    search keeps off the outer few percent.
    """
    a = np.asarray(img.convert("RGB"))
    h, w, _ = a.shape
    x0, x1, y0, y1 = int(0.04 * w), int(0.90 * w), int(0.03 * h), int(0.97 * h)
    ink = a[y0:y1, x0:x1].min(axis=2) < 185
    dens = ink.mean(axis=1)
    rows = np.where(dens >= 0.22)[0]
    if len(rows) < 0.1 * h:
        return None
    # the longest band of such rows, allowing a few thin gaps
    bands, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > 10:
            bands.append((start, prev))
            start = r
        prev = r
    bands.append((start, prev))
    top, bottom = max(bands, key=lambda b: b[1] - b[0])
    if bottom - top < 0.15 * h:
        return None
    cdens = ink[top:bottom + 1].mean(axis=0)
    # the longest run of inked columns, so a stray dark column at the page's
    # edge (the binding shows on a few leaves) does not stretch the box
    cols = np.where(cdens >= 0.3)[0]
    runs, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > 6:
            runs.append((start, prev))
            start = c
        prev = c
    runs.append((start, prev))
    left, right = max(runs, key=lambda r: r[1] - r[0])
    return int(left) + x0, int(top) + y0, int(right) + x0, int(bottom) + y0


def main() -> int:
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    OUT.mkdir(parents=True, exist_ok=True)
    man = OUT / "manifest.json"
    if not man.exists():
        man.write_bytes(get(f"{BASE}/presentation/v2/{ITEM}/manifest"))
    m = json.loads(man.read_text(encoding="utf-8"))
    canvases = {c["@id"]: c for c in m["sequences"][0]["canvases"]}
    cuts = []
    for s in m["structures"]:
        lab = s.get("label")
        mm = re.match(r"Kupferstich\s+(\d+)", lab if isinstance(lab, str) else "")
        if mm and s.get("canvases"):
            cuts.append((int(mm.group(1)), s["canvases"][0]))
    cuts.sort()
    print(f"{len(cuts)} woodcuts indexed", file=sys.stderr)
    index = {}
    for n, cid in cuts[:limit]:
        c = canvases[cid]
        W, H = c["width"], c["height"]
        page = c["images"][0]["resource"]["service"]["@id"]
        dst = OUT / f"wc_{n:03d}.jpg"
        if not dst.exists():
            thumb = Image.open(io.BytesIO(get(f"{page}/full/{THUMB},/0/default.jpg")))
            box = find_frame(thumb)
            if box is None:
                print(f"  ! woodcut {n}: no frame found on {cid.rsplit('/', 1)[-1]}", file=sys.stderr)
                continue
            k = W / thumb.width
            x0, y0, x1, y1 = (int(round(v * k)) for v in box)
            pad = int(8 * k)
            x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
            data = get(f"{page}/{x0},{y0},{x1 - x0},{y1 - y0}/full/0/default.jpg")
            dst.write_bytes(data)
            index[n] = {"canvas": cid, "box": [x0, y0, x1, y1]}
        else:
            index[n] = {"canvas": cid}
        im = Image.open(dst)
        print(f"{n:3d} {im.width}x{im.height}", file=sys.stderr, flush=True)
    (OUT / "woodcuts.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
