#!/usr/bin/env python
"""Fetch the engravings the cover roundel can carry in place of a drawn emblem
(cover: {emblem: <name>}), cut to the roundel and toned to the cover's ink.

godfrey: Nicolaes de Bruyn, Godfrey of Bouillon, plate nine of The Nine
Worthies (1594), published by Assuerus van Londerseel. Art Institute of
Chicago 185115, public domain, image CC0. Godfrey wears the crown of thorns:
he would not wear gold where Christ had worn thorns. Tasso's captain.

Writes assets/emblems/<name>.jpg, a square whose inscribed circle is the
picture.

    python fetch_cover_art.py
"""
import io
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).parent
OUT = HERE / "assets" / "emblems"
SIZE = 1000                      # px across: over 500 dpi in a 1.9-inch roundel
INK = (36, 31, 26)               # cover.py's ink, #241f1a
PAPER = (244, 234, 213)          # the default cover ground, #f4ead5

# name -> (IIIF image id, width to ask for, (centre x, centre y, radius) of the
# picture's own round frame, inside its rule, as fractions of the width). The
# server may answer a size it would rather send -- 843 px for 2000 -- so the
# frame is placed relative to whatever arrives.
ART = {
    "godfrey": ("1e69fcfb-eef9-d11c-423d-c5736eeee4e4", 1686, (0.510, 0.760, 0.250)),
}


def get(url: str) -> bytes:
    r = subprocess.run(["curl", "-sL", "-m", "180", "-A", "book_creator", url],
                       capture_output=True)
    if r.returncode or not r.stdout:
        raise RuntimeError(f"could not fetch {url}")
    return r.stdout


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (image_id, width, frame) in ART.items():
        url = f"https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg"
        im = Image.open(io.BytesIO(get(url))).convert("L")
        cx, cy, r = (round(f * im.width) for f in frame)
        im = im.crop((cx - r, cy - r, cx + r, cy + r)).resize((SIZE, SIZE), Image.LANCZOS)
        # Black on cream laid paper, re-inked: the darkest line to the cover's
        # ink, the paper to the cover's ground, so the print sits in the
        # roundel as if engraved there rather than pasted in.
        im = ImageOps.autocontrast(im, cutoff=1)
        im = ImageOps.colorize(im, black=INK, white=PAPER)
        path = OUT / f"{name}.jpg"
        im.save(path, quality=90)
        print(f"{path}  {SIZE}x{SIZE}")


if __name__ == "__main__":
    main()
