#!/usr/bin/env python
"""Draw the desktop icon from the project's own cover art.

Reuses cover.py's laurel emblem rather than shipping a stock picture, so the
icon on the desktop is the same mark that goes on a Latin cover. Rendered at
every size Windows asks for, since it picks a different one for the desktop,
the taskbar and Alt-Tab, and a single large bitmap scaled down turns the
laurel into mush.

    python make_icon.py            # writes assets/book_creator.ico
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rcanvas

from book_creator import cover

OUT = Path("assets") / "book_creator.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = "#f4ead5"      # the parchment the covers use
ACCENT = "#7c2128"          # imperial oxblood, the Latin accent


def _render(size_px: int) -> "Image.Image":
    """One square of the icon: a ruled border with the laurel inside it."""
    import fitz
    from PIL import Image

    side = 72.0                      # points; rasterized to size_px below
    pdf = Path("assets") / "_icon.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)

    c = rcanvas.Canvas(str(pdf), pagesize=(side, side))
    c.setFillColor(HexColor(BACKGROUND))
    c.rect(0, 0, side, side, fill=1, stroke=0)

    accent = HexColor(ACCENT)
    c.setStrokeColor(accent)
    # The border is dropped at the smallest sizes: at 16px a double rule is
    # three grey pixels and only muddies the emblem.
    if size_px >= 32:
        inset = side * 0.10
        c.setLineWidth(side * 0.028)
        c.rect(inset, inset, side - 2 * inset, side - 2 * inset)

    cover._laurel(c, side / 2.0, side / 2.0, side * 0.62, accent)
    c.showPage()
    c.save()

    doc = fitz.open(str(pdf))
    # The page is 72pt square — exactly one inch — so rendering at `size_px`
    # dots per inch gives `size_px` pixels, with no rescaling to soften it.
    pix = doc[0].get_pixmap(dpi=int(size_px))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    pdf.unlink(missing_ok=True)
    if img.size != (size_px, size_px):
        img = img.resize((size_px, size_px), Image.LANCZOS)
    return img


def build(out: Path = OUT) -> Path:
    from PIL import Image  # noqa: F401  (checked here for a clear error)

    frames = [_render(s) for s in SIZES]
    out.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes every supplied size into one .ico when given `sizes`.
    frames[-1].save(out, format="ICO",
                    sizes=[(s, s) for s in SIZES])
    return out


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path} ({', '.join(f'{s}x{s}' for s in SIZES)}).")
