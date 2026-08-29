"""Vector ornaments and a Flowable for chapter dividers.

Everything here draws onto a ReportLab canvas. Margin art is drawn per-page in
the document's onPage hook; chapter art is emitted into the story as an
OrnamentFlowable so it flows with the text.
"""

from __future__ import annotations

import math

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


def _leaf(c, x: float, y: float, size: float, angle_deg: float) -> None:
    """A slender pointed ivy leaf, tip pointing along angle_deg, base at (x, y)."""
    c.saveState()
    c.translate(x, y)
    c.rotate(angle_deg)
    w = size * 0.34
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(w, size * 0.22, w * 0.55, size * 0.68, 0, size)
    p.curveTo(-w * 0.55, size * 0.68, -w, size * 0.22, 0, 0)
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()


def _medieval_vine(c, cx: float, y: float, width: float) -> None:
    """Illuminated-manuscript marginalia: a wavy vine with alternating ivy leaves
    and a small quatrefoil at the center."""
    half = width / 2.0
    segs = 6
    seg_w = width / segs
    amp = 3.2
    x0 = cx - half
    pts = []
    for i in range(segs + 1):
        x = x0 + i * seg_w
        yy = y if i in (0, segs) else y + (amp if i % 2 else -amp)
        pts.append((x, yy))
    c.setLineWidth(1.0)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        c.bezier(x1, y1, (x1 + x2) / 2.0, y1, (x1 + x2) / 2.0, y2, x2, y2)

    leaf_size = min(13.0, width * 0.055)
    for i, (x, yy) in enumerate(pts[1:-1], start=1):
        side = 1 if i % 2 == 0 else -1
        _leaf(c, x, yy, leaf_size, 90 * side - side * 18)

    # Small quatrefoil at the center, astride the vine.
    r = 4.0
    for ang in (0, 90, 180, 270):
        px = cx + r * math.cos(math.radians(ang))
        py = y + r * math.sin(math.radians(ang))
        c.circle(px, py, r * 0.62, fill=1, stroke=0)
    c.circle(cx, y, r * 0.4, fill=1, stroke=0)

    _diamond(c, x0, y, 2.0)
    _diamond(c, x0 + width, y, 2.0)


def _acanthus_scroll(c, x: float, y: float, size: float, mirror: int) -> None:
    """One side of a symmetric Victorian scrollwork flourish, a curling frond."""
    c.saveState()
    c.translate(x, y)
    c.scale(mirror, 1)
    c.setLineWidth(1.2)
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(size * 0.35, size * 0.5, size * 0.95, size * 0.42, size * 1.15, 0.0)
    p.curveTo(size * 1.32, -size * 0.32, size * 0.98, -size * 0.58, size * 0.62, -size * 0.34)
    c.drawPath(p, fill=0, stroke=1)
    for t in (0.32, 0.62, 0.88):
        lx = size * 1.15 * t
        ly = size * 0.45 * math.sin(math.pi * t)
        _leaf(c, lx, ly, size * 0.22, 55)
    c.restoreState()


def _victorian_ornament(c, cx: float, y: float, width: float) -> None:
    """An ornate Victorian type ornament: central rosette flanked by mirrored
    acanthus scrollwork."""
    half = width / 2.0
    r = 6.5
    c.setLineWidth(1.0)
    c.circle(cx, y, r * 0.85, fill=0, stroke=1)
    c.circle(cx, y, r * 0.36, fill=1, stroke=0)
    for k in range(8):
        ang = math.radians(k * 45)
        px = cx + r * 1.5 * math.cos(ang)
        py = y + r * 1.5 * math.sin(ang)
        c.circle(px, py, r * 0.22, fill=1, stroke=0)

    scroll = min(0.42 * half, 26.0)
    _acanthus_scroll(c, cx + r * 1.9, y, scroll, mirror=1)
    _acanthus_scroll(c, cx - r * 1.9, y, scroll, mirror=-1)
    _diamond(c, cx - half, y, 2.0)
    _diamond(c, cx + half, y, 2.0)


def _laurel_leaflet(c, x: float, y: float, size: float, angle_deg: float) -> None:
    """A rounded laurel leaf (blunter than the ivy leaf), tip along angle_deg."""
    c.saveState()
    c.translate(x, y)
    c.rotate(angle_deg)
    w = size * 0.42
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(w, size * 0.35, w * 0.7, size * 0.85, 0, size)
    p.curveTo(-w * 0.7, size * 0.85, -w, size * 0.35, 0, 0)
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()


def _classical_laurel(c, cx: float, y: float, width: float) -> None:
    """Greco-Roman divider: two laurel branches flanking a sunburst medallion —
    fits Latin/Greek antiquity texts (Caesar, Marcus Aurelius)."""
    half = width / 2.0
    stem0 = width * 0.075
    branch_len = half * 0.8
    n = 5
    leaf_size = min(11.0, width * 0.05)
    arc = leaf_size * 0.9  # gentle upward curve, like a real sprig
    c.setLineWidth(0.9)
    for side in (-1, 1):
        x0 = cx + side * stem0
        pts = [(x0 + side * t * branch_len, y + arc * math.sin(t * math.pi))
               for t in (i / 12 for i in range(13))]
        p = c.beginPath()
        p.moveTo(*pts[0])
        for px, py in pts[1:]:
            p.lineTo(px, py)
        c.drawPath(p, fill=0, stroke=1)
        for i in range(n):
            t = (i + 1) / (n + 1)
            bx = x0 + side * t * branch_len
            by = y + arc * math.sin(t * math.pi)
            up = i % 2 == 0
            base_ang = 0 if side > 0 else 180
            _laurel_leaflet(c, bx, by, leaf_size, base_ang + (40 if up else -40))

    # Central sunburst medallion.
    r = 4.5
    for k in range(8):
        ang = math.radians(k * 45 + 22.5)
        x1, y1 = cx + r * 0.55 * math.cos(ang), y + r * 0.55 * math.sin(ang)
        x2, y2 = cx + r * 1.3 * math.cos(ang), y + r * 1.3 * math.sin(ang)
        c.setLineWidth(0.8)
        c.line(x1, y1, x2, y2)
    c.circle(cx, y, r * 0.5, fill=1, stroke=0)
    _diamond(c, cx - half, y, 2.0)
    _diamond(c, cx + half, y, 2.0)


def _shell_fan(c, cx: float, y: float, r: float) -> None:
    """A stylized scallop-shell fan (baroque cartouche crest), apex up."""
    n = 7
    c.setLineWidth(0.7)
    pts = []
    for i in range(n):
        a = math.radians(200 + i * (140 / (n - 1)))
        x2, y2 = cx + r * math.cos(a), y + r * math.sin(a)
        c.line(cx, y, x2, y2)
        pts.append((x2, y2))
    c.setLineWidth(1.1)
    p = c.beginPath()
    p.moveTo(*pts[0])
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        p.curveTo(x1, y1, x2, y2, x2, y2)
    c.drawPath(p, fill=0, stroke=1)


def _baroque_scroll(c, x: float, y: float, size: float, mirror: int) -> None:
    """A heavier double-coiled rocaille scroll (baroque), one side of the pair."""
    c.saveState()
    c.translate(x, y)
    c.scale(mirror, 1)
    c.setLineWidth(1.3)
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(size * 0.4, size * 0.55, size * 1.0, size * 0.5, size * 1.1, size * 0.1)
    p.curveTo(size * 1.18, size * -0.22, size * 0.9, size * -0.4, size * 0.75, size * -0.18)
    p.curveTo(size * 0.63, size * -0.02, size * 0.78, size * 0.14, size * 0.95, size * 0.08)
    c.drawPath(p, fill=0, stroke=1)
    _laurel_leaflet(c, size * 1.05, size * 0.35, size * 0.28, 55)
    c.restoreState()


def _baroque_ornament(c, cx: float, y: float, width: float) -> None:
    """An ornate baroque cartouche: a scallop-shell crest flanked by mirrored
    rocaille scrollwork — fits 17th-18th century French texts (Molière,
    Racine, Voltaire)."""
    half = width / 2.0
    _shell_fan(c, cx, y, 7.0)
    scroll = min(0.42 * half, 24.0)
    _baroque_scroll(c, cx + 8.0, y, scroll, mirror=1)
    _baroque_scroll(c, cx - 8.0, y, scroll, mirror=-1)
    _diamond(c, cx - half, y, 2.0)
    _diamond(c, cx + half, y, 2.0)


def _nouveau_bud(c, x: float, y: float, size: float, angle_deg: float) -> None:
    """A slender, asymmetric Art Nouveau bud, tip along angle_deg."""
    c.saveState()
    c.translate(x, y)
    c.rotate(angle_deg)
    w = size * 0.3
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(w * 1.3, size * 0.18, w * 0.4, size * 0.75, 0, size)
    p.curveTo(-w * 0.5, size * 0.6, -w * 0.8, size * 0.2, 0, 0)
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()


def _nouveau_whiplash(c, x: float, y: float, size: float, mirror: int) -> None:
    """A flowing Art Nouveau 'whiplash' curve terminating in a bud."""
    c.saveState()
    c.translate(x, y)
    c.scale(mirror, 1)
    c.setLineWidth(1.1)
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(size * 0.5, size * 0.55, size * 0.3, size * 1.05, size * 0.9, size * 1.15)
    p.curveTo(size * 1.3, size * 1.22, size * 1.35, size * 0.85, size * 1.05, size * 0.7)
    c.drawPath(p, fill=0, stroke=1)
    _nouveau_bud(c, size * 0.9, size * 1.15, size * 0.4, 25)
    c.restoreState()


def _art_nouveau_ornament(c, cx: float, y: float, width: float) -> None:
    """A flowing Art Nouveau divider: mirrored whiplash tendrils around a
    small five-petaled flower — fits fin-de-siècle French texts (Baudelaire,
    Huysmans)."""
    half = width / 2.0
    scale = min(0.35 * half, 18.0)
    _nouveau_whiplash(c, cx + 6, y - 5, scale, mirror=1)
    _nouveau_whiplash(c, cx - 6, y - 5, scale, mirror=-1)
    r = 5.2
    for ang in (90, 162, 234, 306, 18):
        px = cx + r * math.cos(math.radians(ang))
        py = y + r * math.sin(math.radians(ang))
        c.circle(px, py, r * 0.5, fill=1, stroke=0)
    c.circle(cx, y, r * 0.4, fill=1, stroke=0)
    _diamond(c, cx - half, y, 2.0)
    _diamond(c, cx + half, y, 2.0)


def _rococo_spray(c, cx: float, y: float, size: float) -> None:
    """A small, asymmetric flower spray (rococo centerpiece) — three uneven
    stems radiating upward, each tipped with a round bloom."""
    stems = [(-22, size * 0.85), (4, size * 1.15), (26, size * 0.7)]
    c.setLineWidth(0.6)
    for ang, length in stems:
        a = math.radians(90 + ang)
        x2, y2 = cx + length * math.cos(a), y + length * math.sin(a)
        c.line(cx, y, x2, y2)
        c.circle(x2, y2, size * 0.16, fill=1, stroke=0)
    c.circle(cx, y, size * 0.22, fill=1, stroke=0)


def _rococo_scroll(c, x: float, y: float, size: float, mirror: int) -> None:
    """A delicate, single asymmetric C-scroll — thinner and looser than the
    baroque double-coil."""
    c.saveState()
    c.translate(x, y)
    c.scale(mirror, 1)
    c.setLineWidth(0.9)
    p = c.beginPath()
    p.moveTo(0, 0)
    p.curveTo(size * 0.3, size * 0.5, size * 0.85, size * 0.55, size * 1.0, size * 0.15)
    p.curveTo(size * 1.1, size * -0.15, size * 0.85, size * -0.35, size * 0.65, size * -0.2)
    c.drawPath(p, fill=0, stroke=1)
    _laurel_leaflet(c, size * 0.15, size * 0.05, size * 0.22, 100)
    c.restoreState()


def _rococo_ornament(c, cx: float, y: float, width: float) -> None:
    """An asymmetric rococo flourish: a small flower spray flanked by
    unevenly-sized, delicate C-scrolls — lighter and more playful than
    baroque, fits Louis XV-era French texts."""
    half = width / 2.0
    _rococo_spray(c, cx, y + 4, 9.0)
    scroll = min(0.4 * half, 20.0)
    _rococo_scroll(c, cx + 7, y - 2, scroll * 1.1, mirror=1)
    _rococo_scroll(c, cx - 7, y - 2, scroll * 0.82, mirror=-1)  # deliberately asymmetric
    _diamond(c, cx - half, y, 2.0)
    _diamond(c, cx + half, y, 2.0)


def _deco_sunburst(c, cx: float, y: float, r: float) -> None:
    """A stepped Art Deco sunburst fan, alternating long/short rays."""
    n = 9
    c.setLineWidth(1.3)
    for i in range(n):
        a = math.radians(20 + i * (140 / (n - 1)))
        length = r if i % 2 == 0 else r * 0.62
        x2, y2 = cx + length * math.cos(a), y + length * math.sin(a)
        c.line(cx, y, x2, y2)


def _deco_chevron(c, x: float, y: float, size: float, mirror: int) -> None:
    """Nested stepped chevron wedges (Art Deco), pointing outward from center,
    one side of the pair."""
    c.saveState()
    c.translate(x, y)
    c.scale(mirror, 1)
    c.setLineWidth(1.3)
    for r in (0.45, 0.72, 1.0):
        p = c.beginPath()
        p.moveTo(0, size * 0.34 * r)
        p.lineTo(size * r, 0)
        p.lineTo(0, -size * 0.34 * r)
        c.drawPath(p, fill=0, stroke=1)
    c.restoreState()


def _art_deco_ornament(c, cx: float, y: float, width: float) -> None:
    """A geometric Art Deco divider: a stepped sunburst fan flanked by
    stacked chevrons — bold, symmetric, 1920s-30s in feel."""
    half = width / 2.0
    _deco_sunburst(c, cx, y - 2, 10.5)
    chevron_w = min(0.32 * half, 20.0)
    _deco_chevron(c, cx + 14, y, chevron_w, mirror=1)
    _deco_chevron(c, cx - 14, y, chevron_w, mirror=-1)
    _diamond(c, cx - half, y, 2.2)
    _diamond(c, cx + half, y, 2.2)


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
        # Anchored OUTSIDE the text frame, in the blank margin, with the arms
        # pointing back toward (but stopping short of) the frame corner — so
        # the ornament never overlaps text even on a page that's fully packed
        # top-to-bottom. `off > size` keeps the arm tip, and its curl's slight
        # overshoot, clear of the frame edge.
        size = 0.22 * inch
        off = size * 1.3
        _corner_motif(c, left - off, top + off, size, +1, -1)     # top-left
        _corner_motif(c, right + off, top + off, size, -1, -1)    # top-right
        _corner_motif(c, left - off, bottom - off, size, +1, +1)  # bottom-left
        _corner_motif(c, right + off, bottom - off, size, -1, +1)  # bottom-right
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
    if style == "medieval":
        def _draw(c, aw, h):
            _medieval_vine(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.62))
        return OrnamentFlowable(26, _draw, color)
    if style == "victorian":
        def _draw(c, aw, h):
            _victorian_ornament(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.68))
        return OrnamentFlowable(30, _draw, color)
    if style == "classical":
        def _draw(c, aw, h):
            _classical_laurel(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.68))
        return OrnamentFlowable(26, _draw, color)
    if style == "baroque":
        def _draw(c, aw, h):
            _baroque_ornament(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.68))
        return OrnamentFlowable(30, _draw, color)
    if style == "nouveau":
        def _draw(c, aw, h):
            _art_nouveau_ornament(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.62))
        return OrnamentFlowable(30, _draw, color)
    if style == "rococo":
        def _draw(c, aw, h):
            _rococo_ornament(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.62))
        return OrnamentFlowable(30, _draw, color)
    if style == "artdeco":
        def _draw(c, aw, h):
            _art_deco_ornament(c, aw / 2.0, h / 2.0, min(width_hint, aw * 0.62))
        return OrnamentFlowable(28, _draw, color)
    return None


# Every ornamented (non-"none") chapter style, for `chapter: random` — a
# deterministic per-chapter pick (see pick_random_style) so the PDF and EPUB
# editions of the same book agree, and repeat builds are reproducible.
ALL_CHAPTER_STYLES = ["fleuron", "rule", "medieval", "victorian", "classical",
                      "baroque", "nouveau", "rococo", "artdeco"]


def pick_random_style(seed_key) -> str:
    """Deterministically pick a style for `chapter: random`, keyed by e.g. the
    chapter index — same key always yields the same style, so a rebuild (or
    the PDF vs EPUB edition of the same book) stays consistent."""
    import random
    return random.Random(seed_key).choice(ALL_CHAPTER_STYLES)


# --------------------------------------------------------------------------- #
# Rasterized ornaments (for EPUB — a font glyph is never guaranteed to exist
# on a given e-reader, but a picture always renders. Reuses the exact same
# vector drawing routines as the PDF, so both editions match visually.)
# --------------------------------------------------------------------------- #
def render_ornament_png(style: str, color: str, out_path: str, *,
                        width_pt: float = 200.0, height_pt: float = 40.0,
                        dpi: int = 300) -> str | None:
    """Rasterize a chapter-ornament style to a transparent PNG. None for
    styles with no vector art (none/rule — "rule" is a plain CSS <hr> in EPUB,
    which needs no image)."""
    draw_fn = {
        "fleuron": lambda c, w, h: _flourish_rule(c, w / 2.0, h / 2.0, w * 0.85),
        "medieval": lambda c, w, h: _medieval_vine(c, w / 2.0, h / 2.0, w * 0.85),
        "victorian": lambda c, w, h: _victorian_ornament(c, w / 2.0, h / 2.0, w * 0.85),
        "classical": lambda c, w, h: _classical_laurel(c, w / 2.0, h / 2.0, w * 0.85),
        "baroque": lambda c, w, h: _baroque_ornament(c, w / 2.0, h / 2.0, w * 0.85),
        "nouveau": lambda c, w, h: _art_nouveau_ornament(c, w / 2.0, h / 2.0, w * 0.78),
        "rococo": lambda c, w, h: _rococo_ornament(c, w / 2.0, h / 2.0, w * 0.78),
        "artdeco": lambda c, w, h: _art_deco_ornament(c, w / 2.0, h / 2.0, w * 0.78),
    }.get(style)
    if draw_fn is None:
        return None

    import tempfile
    from pathlib import Path

    import fitz
    from reportlab.pdfgen import canvas as _canvas

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = str(Path(tmp) / "orn.pdf")
        c = _canvas.Canvas(tmp_pdf, pagesize=(width_pt, height_pt))
        ink = HexColor(color)
        c.setStrokeColor(ink)
        c.setFillColor(ink)
        draw_fn(c, width_pt, height_pt)
        c.showPage()
        c.save()

        doc = fitz.open(tmp_pdf)
        pix = doc[0].get_pixmap(dpi=dpi, alpha=True)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        pix.save(out_path)
        doc.close()
    return out_path


def render_margin_png(style: str, color: str, out_path: str, *,
                      corner_image: str | None = None,
                      trim: tuple[float, float] = (6.0, 9.0),
                      dpi: int = 60, recto: bool = True) -> str | None:
    """Rasterize page-margin art onto a miniature page, for previewing.

    Margin styles are the hardest part of the design to picture from a word:
    "corners" and "frame" differ subtly, and both are gutter-aware, so the
    only honest preview is an actual page. Ruled lines stand in for text so
    the relationship between the art and the text block is visible.

    Returns None when there is nothing to draw.
    """
    if style == "none" and not corner_image:
        return None

    import tempfile
    from pathlib import Path

    import fitz
    from reportlab.pdfgen import canvas as _canvas

    page_w, page_h = trim[0] * inch, trim[1] * inch
    gutter, outside, vertical = 0.88 * inch, 0.5 * inch, 0.75 * inch
    geom = ({"left": gutter, "right": page_w - outside}
            if recto else {"left": outside, "right": page_w - gutter})
    geom |= {"top": page_h - vertical, "bottom": vertical,
             "page_w": page_w, "outside": outside}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = str(Path(tmp) / "margin.pdf")
        c = _canvas.Canvas(tmp_pdf, pagesize=(page_w, page_h))

        # A hint of text, so the art is seen in relation to the text block
        # rather than floating on an empty sheet.
        c.saveState()
        c.setStrokeColor(HexColor("#cccccc"))
        c.setLineWidth(2.2)
        y = geom["top"] - 10
        while y > geom["bottom"] + 6:
            width = (geom["right"] - geom["left"]) * (0.72 if y < geom["bottom"] + 26 else 1.0)
            c.line(geom["left"], y, geom["left"] + width, y)
            y -= 13
        c.restoreState()

        draw_margin(c, geom, recto, style, color, corner_image)
        c.showPage()
        c.save()

        doc = fitz.open(tmp_pdf)
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        pix.save(out_path)
        doc.close()
    return out_path
