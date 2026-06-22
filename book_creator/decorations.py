"""Vector ornaments and a Flowable for chapter dividers.

Everything here draws onto a ReportLab canvas. Margin art is drawn per-page in
the document's onPage hook; chapter art is emitted into the story as an
OrnamentFlowable so it flows with the text.
"""

from __future__ import annotations

from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.platypus import Flowable


# --------------------------------------------------------------------------- #
# Low-level primitives
# --------------------------------------------------------------------------- #
def _diamond(c, x: float, y: float, r: float, fill: bool = True) -> None:
    p = c.beginPath()
    p.moveTo(x, y + r)
    p.lineTo(x + r, y)
    p.lineTo(x, y - r)
    p.lineTo(x - r, y)
    p.close()
    c.drawPath(p, fill=1 if fill else 0, stroke=0 if fill else 1)


def _corner_motif(c, x: float, y: float, size: float, sx: int, sy: int) -> None:
    """A corner ornament with its elbow at (x, y); arms run in directions sx/sy.

    sx, sy are +1 / -1 indicating which way the two arms extend.
    """
    L = size
    hook = size * 0.32
    c.setLineWidth(0.9)
    # Two straight arms.
    c.line(x, y, x + sx * L, y)
    c.line(x, y, x, y + sy * L)
    # A curl at the end of each arm.
    c.bezier(
        x + sx * L, y,
        x + sx * (L + hook * 0.5), y + sy * hook * 0.15,
        x + sx * (L + hook * 0.3), y + sy * hook * 0.8,
        x + sx * (L - hook * 0.15), y + sy * hook,
    )
    c.bezier(
        x, y + sy * L,
        x + sx * hook * 0.15, y + sy * (L + hook * 0.5),
        x + sx * hook * 0.8, y + sy * (L + hook * 0.3),
        x + sx * hook, y + sy * (L - hook * 0.15),
    )
    # A small filled diamond just inside the elbow.
    d = max(size * 0.10, 1.6)
    _diamond(c, x + sx * d * 1.6, y + sy * d * 1.6, d)


def _flourish_rule(c, cx: float, y: float, width: float) -> None:
    """A horizontal divider: line — center diamond — line, with diamond end-caps."""
    half = width / 2.0
    gap = width * 0.06 + 3
    c.setLineWidth(0.9)
    c.line(cx - half, y, cx - gap, y)
    c.line(cx + gap, y, cx + half, y)
    _diamond(c, cx, y, 3.2)
    _diamond(c, cx - half, y, 1.6)
    _diamond(c, cx + half, y, 1.6)
    # Tiny curls flanking the center diamond.
    for s in (-1, 1):
        c.bezier(
            cx + s * gap, y,
            cx + s * gap * 0.6, y + 4,
            cx + s * gap * 0.3, y + 4,
            cx + s * 1.5, y + 1.5,
        )


# --------------------------------------------------------------------------- #
# Per-page margin art
# --------------------------------------------------------------------------- #
def draw_margin(c, geom: dict, recto: bool, style: str, color: str,
                corner_image: str | None) -> None:
    """Draw margin decoration for one page.

    geom keys: left, right, top, bottom (text-block edges in points),
    page_w, outside.
    """
    if style == "none" and not corner_image:
        return
    c.saveState()
    ink = HexColor(color)
    c.setStrokeColor(ink)
    c.setFillColor(ink)

    left, right = geom["left"], geom["right"]
    top, bottom = geom["top"], geom["bottom"]

    if corner_image:
        _corner_images(c, left, right, top, bottom, corner_image)
    elif style == "corners":
        size = 0.28 * inch
        _corner_motif(c, left, top, size, +1, -1)    # top-left
        _corner_motif(c, right, top, size, -1, -1)    # top-right
        _corner_motif(c, left, bottom, size, +1, +1)  # bottom-left
        _corner_motif(c, right, bottom, size, -1, +1)  # bottom-right
    elif style == "frame":
        # Double rule rectangle with corner diamonds.
        c.setLineWidth(1.0)
        pad = 6
        c.rect(left - pad, bottom - pad, (right - left) + 2 * pad, (top - bottom) + 2 * pad)
        c.setLineWidth(0.5)
        ip = pad + 3
        c.rect(left - ip, bottom - ip, (right - left) + 2 * ip, (top - bottom) + 2 * ip)
        for cx in (left - pad, right + pad):
            for cy in (bottom - pad, top + pad):
                _diamond(c, cx, cy, 2.4)
    elif style == "rule":
        # A thin flourished vertical rule in the OUTER margin.
        outer_x = (right + 0.16 * inch) if recto else (left - 0.16 * inch)
        c.setLineWidth(0.8)
        c.line(outer_x, bottom + 6, outer_x, top - 6)
        for yy in (bottom + 6, top - 6):
            _diamond(c, outer_x, yy, 2.0)
        _diamond(c, outer_x, (top + bottom) / 2.0, 2.6)

    c.restoreState()


def _corner_images(c, left, right, top, bottom, path) -> None:
    """Place a corner PNG at all four corners, mirrored so each points inward."""
    size = 0.55 * inch
    placements = [
        (left, top, +1, -1),     # top-left
        (right, top, -1, -1),    # top-right
        (left, bottom, +1, +1),  # bottom-left
        (right, bottom, -1, +1),  # bottom-right
    ]
    for x, y, sx, sy in placements:
        c.saveState()
        c.translate(x, y)
        c.scale(sx, sy)
        # Image's natural orientation = top-left corner art.
        c.drawImage(path, 0, -size, width=size, height=size,
                    mask="auto", preserveAspectRatio=True, anchor="nw")
        c.restoreState()


# --------------------------------------------------------------------------- #
# Chapter / section ornaments (in-story flowables)
# --------------------------------------------------------------------------- #
class OrnamentFlowable(Flowable):
    """A flowable whose draw routine receives (canvas, avail_width, height)."""

    def __init__(self, height: float, draw_fn, color: str):
        super().__init__()
        self.height = height
        self._draw = draw_fn
        self._color = color
        self._aw = 0.0

    def wrap(self, avail_w, avail_h):
        self._aw = avail_w
        return avail_w, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        ink = HexColor(self._color)
        c.setStrokeColor(ink)
        c.setFillColor(ink)
        self._draw(c, self._aw, self.height)
        c.restoreState()


def chapter_ornament(style: str, color: str, width_hint: float = 2.4 * inch,
                     image: str | None = None) -> OrnamentFlowable | None:
    if image:
        def _draw_img(c, aw, h):
            iw = min(width_hint, aw)
            c.drawImage(image, (aw - iw) / 2.0, 0, width=iw, height=h - 4,
                        mask="auto", preserveAspectRatio=True, anchor="sw")
        return OrnamentFlowable(0.5 * inch, _draw_img, color)

    if style == "fleuron":
        def _draw(c, aw, h):
            _flourish_rule(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.6))
        return OrnamentFlowable(22, _draw, color)
    if style == "rule":
        def _draw(c, aw, h):
            cx, y = aw / 2.0, h / 2.0
            half = min(width_hint, aw * 0.5) / 2.0
            c.setLineWidth(0.8)
            c.line(cx - half, y, cx + half, y)
        return OrnamentFlowable(16, _draw, color)
    return None
