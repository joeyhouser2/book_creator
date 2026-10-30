#!/usr/bin/env python
"""Fetch the pictures the cover roundel can carry in place of a drawn emblem
(cover: {emblem: <name>}, or assets/emblems/books.yaml by slug), cut to a
circle and toned to the cover's ink and ground.

Every picture is public domain and published by its holder without
restriction: the Art Institute of Chicago and the Metropolitan Museum release
theirs as CC0, and the Theuerdank woodcut is the Bayerische Staatsbibliothek's
copy under the Public Domain Mark. assets/emblems/README.md says what each is.

Writes assets/emblems/<name>.jpg, a square whose inscribed circle is the
picture.

    python fetch_cover_art.py [name ...]
"""
import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

HERE = Path(__file__).parent
OUT = HERE / "assets" / "emblems"
SIZE = 1000                      # px across: over 500 dpi in a 1.9-inch roundel
INK = (36, 31, 26)               # cover.py's ink, #241f1a
PAPER = (244, 234, 213)          # the default cover ground, #f4ead5

# name -> (source, frame, toned). The source is ("aic", IIIF image id),
# ("met", object id) or ("file", a path under the repo) for something another
# fetcher already wrote. The frame is the picture's circle as (centre x,
# centre y, radius) in fractions of the image's width -- the servers may send
# a smaller size than asked, so nothing is in pixels -- or "auto" for a coin
# or medal photographed on a plain ground, which is found by its edge. A toned
# picture is re-inked to the cover's ink and ground; an untoned one keeps its
# colour (the hand-coloured Theuerdank).
ART = {
    "godfrey": (("aic", "1e69fcfb-eef9-d11c-423d-c5736eeee4e4"), (0.510, 0.760, 0.250), True),
    "maximilian": (("aic", "a32685e0-e1ed-cb87-c51b-9850e295c491"), (0.66, 0.55, 0.32), True),
    "henri-iv": (("aic", "e620b211-03ad-6647-2a89-83953fd440a6"), (0.50, 0.54, 0.29), True),
    "baudelaire": (("met", 270956), (0.47, 0.47, 0.33), True),
    "balzac": (("met", 191843), (0.53, 0.57, 0.42), True),
    "hugo": (("met", 239523), "auto", True),
    "stryge": (("met", 360188), (0.52, 0.55, 0.36), True),
    "stendhal": (("met", 188467), (0.495, 0.48, 0.37), True),
    "knight": (("met", 377280), (0.50, 0.55, 0.38), True),
    "pontano": (("met", 460942), (0.483, 0.392, 0.275), True),
    "sigismondo": (("met", 461143), "auto", True),
    "honorius": (("met", 468736), "auto", True),
    "daric": (("met", 324243), "auto", True),
    "elizabeth": (("met", 825978), "auto", True),
    "cid": (("met", 359939), (0.52, 0.30, 0.20), True),
    # python fetch_woodcuts.py writes it.
    "theuerdank": (("file", "cache/theuerdank/woodcuts/wc_117.jpg"), (0.44, 0.54, 0.36), False),
}


def get(url: str) -> bytes:
    r = subprocess.run(["curl", "-sL", "-m", "180", "-A", "book_creator", url],
                       capture_output=True)
    if r.returncode or not r.stdout:
        raise RuntimeError(f"could not fetch {url}")
    return r.stdout


def load(source) -> Image.Image:
    kind, ref = source
    if kind == "aic":
        data = get(f"https://www.artic.edu/iiif/2/{ref}/full/1686,/0/default.jpg")
    elif kind == "met":
        obj = json.loads(get(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{ref}"))
        if not obj.get("isPublicDomain"):
            raise RuntimeError(f"Met {ref} is no longer marked public domain")
        data = get(obj["primaryImage"])
    else:
        path = HERE / ref
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing: run the fetcher that writes it")
        data = path.read_bytes()
    return Image.open(io.BytesIO(data)).convert("RGB")


def find_disc(im: Image.Image) -> tuple[int, int, int]:
    """The coin or medal on its plain ground: everything far enough from the
    border's colour, then the largest square that fits inside it, a little in
    from the rim so no ground shows at the edge."""
    a = np.asarray(im.convert("L"), dtype=float)
    border = np.concatenate([a[:8].ravel(), a[-8:].ravel(), a[:, :8].ravel(), a[:, -8:].ravel()])
    mask = np.abs(a - np.median(border)) > 18
    rows = np.where(mask.mean(axis=1) > 0.03)[0]
    cols = np.where(mask.mean(axis=0) > 0.03)[0]
    y0, y1, x0, x1 = rows[0], rows[-1], cols[0], cols[-1]
    r = int(min(x1 - x0, y1 - y0) / 2 * 0.95)
    return (x0 + x1) // 2, (y0 + y1) // 2, r


def main(names) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names or ART:
        source, frame, toned = ART[name]
        im = load(source)
        if frame == "auto":
            cx, cy, r = find_disc(im)
        else:
            cx, cy, r = (round(f * im.width) for f in frame)
        im = im.crop((cx - r, cy - r, cx + r, cy + r)).resize((SIZE, SIZE), Image.LANCZOS)
        if toned:
            # Re-inked: the darkest line to the cover's ink, the lightest
            # ground to its paper, so the picture sits in the roundel as if
            # engraved there rather than pasted in.
            im = ImageOps.autocontrast(im.convert("L"), cutoff=1)
            im = ImageOps.colorize(im, black=INK, white=PAPER)
        path = OUT / f"{name}.jpg"
        im.save(path, quality=90)
        print(f"{path.relative_to(HERE)}  {SIZE}x{SIZE}")


if __name__ == "__main__":
    main(sys.argv[1:])
