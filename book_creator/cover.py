"""Generate a KDP wraparound cover (back + spine + front) with a per-language motif.

KDP wants a single PDF spanning the whole wrap, sized from the trim, the page
count (which sets the spine width), and the paper stock, plus 0.125" bleed all
round. Each source language gets its own accent colour and vector emblem.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, Paragraph

from . import decorations, fonts
from .model import FontSpec

BLEED = 0.125
# Inches of spine per interior page, by paper stock (KDP figures).
_PAPER_THICKNESS = {"white": 0.002252, "cream": 0.0025, "color": 0.002347}

# Per-language motif: accent colour + emblem drawing function (set below).
_MOTIFS: dict[str, dict] = {
    "la": {"name": "Latin", "color": "#7c2128"},     # imperial oxblood
    "grc": {"name": "Greek", "color": "#1f3d63"},     # Aegean blue
    "el": {"name": "Greek", "color": "#1f3d63"},
    "fr": {"name": "French", "color": "#27408b"},     # royal azure
    "de": {"name": "German", "color": "#3d5234"},     # forest/oak green
}
_DEFAULT_MOTIF = {"name": "", "color": "#5a4a2c"}


def cover_dimensions(trim, pages: int, paper: str = "white") -> tuple[float, float, float]:
    """Return (full_width_in, full_height_in, spine_in)."""
    tw, th = trim
    spine = max(0.06, pages * _PAPER_THICKNESS.get(paper, 0.002252))
    full_w = 2 * BLEED + 2 * tw + spine
    full_h = 2 * BLEED + th
    return full_w, full_h, spine


# --------------------------------------------------------------------------- #
# Language emblems (drawn centred at cx, cy within a box of height ~size)
# --------------------------------------------------------------------------- #
def _laurel(c, cx, cy, size, color):
    """Two laurel branches forming a wreath open at the top (Latin)."""
    c.setFillColor(color)
    c.setStrokeColor(color)
    R = size * 0.44
    leaf_l, leaf_w = size * 0.135, size * 0.044
    n = 9
    for side in (-1, 1):
        prev = None
        for t in range(n + 1):
            deg = -80 + (t / n) * 152              # sweep bottom -> top, gap at top
            a = math.radians(deg) if side == 1 else math.pi - math.radians(deg)
            px, py = cx + R * math.cos(a), cy + R * math.sin(a)
            if prev is not None:                   # thin branch arc
                c.setLineWidth(max(1.0, size * 0.014))
                c.line(prev[0], prev[1], px, py)
            prev = (px, py)
            if t == 0:
                continue
            c.saveState()                          # leaf radiating outward, fanned up
            c.translate(px, py)
            c.rotate(math.degrees(a) - 90 + side * 10)
            c.ellipse(-leaf_w, 0, leaf_w, leaf_l, fill=1, stroke=0)
            c.restoreState()
    for dx in (-0.045, 0.045):                     # berries where the branches meet
        c.circle(cx + dx * size, cy - R + size * 0.02, size * 0.02, fill=1, stroke=0)


def _meander(c, cx, cy, size, color):
    """A Greek key (meander) emblem — a square spiral (Greek)."""
    c.setStrokeColor(color)
    u = size / 6.0
    c.setLineWidth(max(1.4, u * 0.45))
    c.setLineJoin(0)
    # The path spans 0..4 units on both axes, so its centre is 2u in from
    # the origin -- offsetting by 2.5u left the key sitting up and to the
    # left of wherever it was asked to be drawn.
    x0, y0 = cx - 2.0 * u, cy - 2.0 * u
    pts = [(0, 4), (0, 0), (4, 0), (4, 4), (1, 4), (1, 1), (3, 1), (3, 3), (2, 3), (2, 2)]
    p = c.beginPath()
    p.moveTo(x0 + pts[0][0] * u, y0 + pts[0][1] * u)
    for gx, gy in pts[1:]:
        p.lineTo(x0 + gx * u, y0 + gy * u)
    c.drawPath(p, fill=0, stroke=1)


def _fleur(c, cx, cy, size, color):
    """A stylised fleur-de-lis (French)."""
    c.setFillColor(color)
    c.setStrokeColor(color)
    h, w = size, size * 0.72

    # central petal — full leaf rising to a point
    p = c.beginPath()
    p.moveTo(cx, cy + 0.02 * h)
    p.curveTo(cx + 0.18 * w, cy + 0.20 * h, cx + 0.10 * w, cy + 0.46 * h, cx, cy + 0.56 * h)
    p.curveTo(cx - 0.10 * w, cy + 0.46 * h, cx - 0.18 * w, cy + 0.20 * h, cx, cy + 0.02 * h)
    c.drawPath(p, fill=1, stroke=0)

    # side petals — tips splay UP and outward (the three-pronged crown)
    for s in (-1, 1):
        apex_x, apex_y = cx + s * 0.36 * w, cy + 0.42 * h
        p = c.beginPath()
        p.moveTo(cx, cy + 0.05 * h)
        p.curveTo(cx + s * 0.10 * w, cy + 0.28 * h,
                  cx + s * 0.28 * w, cy + 0.40 * h, apex_x, apex_y)
        p.curveTo(cx + s * 0.52 * w, cy + 0.18 * h,
                  cx + s * 0.36 * w, cy - 0.04 * h, cx + s * 0.07 * w, cy)
        c.drawPath(p, fill=1, stroke=0)

    # short flared foot below the band
    p = c.beginPath()
    p.moveTo(cx - 0.09 * w, cy)
    p.curveTo(cx - 0.12 * w, cy - 0.16 * h, cx - 0.07 * w, cy - 0.26 * h, cx, cy - 0.30 * h)
    p.curveTo(cx + 0.07 * w, cy - 0.26 * h, cx + 0.12 * w, cy - 0.16 * h, cx + 0.09 * w, cy)
    c.drawPath(p, fill=1, stroke=0)

    # horizontal tie band across the waist
    bw, bh = 0.52 * w, 0.08 * h
    c.roundRect(cx - bw / 2, cy - 0.05 * h, bw, bh, bh * 0.4, fill=1, stroke=0)


def _oak(c, cx, cy, size, color):
    """A single lobed oak leaf with two acorns at the base (German)."""
    c.setFillColor(color)
    c.setStrokeColor(color)
    H, maxw = size * 0.92, size * 0.30
    base_y, tip_y = cy - H * 0.42, cy + H * 0.58
    n = 48
    right = []
    for i in range(n + 1):
        f = i / n
        y = base_y + f * (tip_y - base_y)
        env = math.sin(math.pi * f) ** 0.6              # 0 at base & tip, full mid
        lobe = 0.5 + 0.5 * abs(math.cos(4 * math.pi * f))  # ~4 rounded lobes
        right.append((cx + maxw * env * lobe, y))
    p = c.beginPath()
    p.moveTo(cx, base_y)
    for x, y in right:
        p.lineTo(x, y)
    for x, y in reversed(right):
        p.lineTo(2 * cx - x, y)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    # short stem and two acorns at the base
    c.setLineWidth(max(1.4, size * 0.02))
    c.line(cx, base_y, cx, base_y - size * 0.14)
    for s in (-1, 1):
        ax, ay = cx + s * size * 0.13, base_y - size * 0.16
        c.ellipse(ax - size * 0.06, ay - size * 0.11, ax + size * 0.06, ay + size * 0.02,
                  fill=1, stroke=0)                       # nut
        c.ellipse(ax - size * 0.07, ay - size * 0.01, ax + size * 0.07, ay + size * 0.07,
                  fill=1, stroke=0)                       # cap


_EMBLEMS = {"la": _laurel, "grc": _meander, "el": _meander, "fr": _fleur, "de": _oak}


def _motif_for(src_lang: str, accent: str | None) -> dict:
    m = dict(_MOTIFS.get(src_lang, _DEFAULT_MOTIF))
    if accent:
        m["color"] = accent
    m["emblem"] = _EMBLEMS.get(src_lang)
    return m


def _draw_emblem(c, motif, cx, cy, size):
    fn = motif.get("emblem")
    if fn:
        c.saveState()
        fn(c, cx, cy, size, HexColor(motif["color"]))
        c.restoreState()


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def _wrap(c, text, font, size, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _centered(c, text, font, size, cx, top_y, color, max_w, leading=None):
    leading = leading or size * 1.15
    c.setFont(font, size)
    c.setFillColor(color)
    y = top_y
    for line in _wrap(c, text, font, size, max_w):
        c.drawCentredString(cx, y, line)
        y -= leading
    return y


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #
def _ornament_frame(c, x0, y0, w, h, color, inset):
    c.saveState()
    c.setStrokeColor(color)
    c.setFillColor(color)
    left, bottom = x0 + inset, y0 + inset
    right, top = x0 + w - inset, y0 + h - inset
    c.setLineWidth(1.4)
    c.rect(left, bottom, right - left, top - bottom)
    c.setLineWidth(0.6)
    ip = 4
    c.rect(left - ip, bottom - ip, (right - left) + 2 * ip, (top - bottom) + 2 * ip)
    size = 0.32 * inch
    decorations._corner_motif(c, left, top, size, +1, -1)
    decorations._corner_motif(c, right, top, size, -1, -1)
    decorations._corner_motif(c, left, bottom, size, +1, +1)
    decorations._corner_motif(c, right, bottom, size, -1, +1)
    c.restoreState()


def _edition_label(src_lang, motif, edition_line):
    if edition_line:
        return edition_line.upper()
    lang = motif.get("name") or src_lang.upper()
    return f"{lang}–English Parallel Edition".upper()


def _fitted(c, text, font, big, small, max_w):
    """The larger size if the text fits on about two lines at it, else the
    smaller. A long title set at the display size would otherwise stack into
    four or five lines and collide with whatever sits under it."""
    return big if c.stringWidth(text, font, big) <= max_w * 1.8 else small


def _bottom_label(c, label, font, cx, y0, accent, max_w, size=11.5):
    """The edition line, wrapped up from a fixed baseline near the foot.

    Wrapped rather than drawn as one line: the default label is short, but a
    custom edition_line can be any length and would otherwise run off the
    panel edge.
    """
    leading = size * 1.25
    n = len(_wrap(c, label, font, size, max_w))
    _centered(c, label, font, size, cx, y0 + 0.95 * inch + (n - 1) * leading,
              accent, max_w, leading=leading)


# --------------------------------------------------------------------------- #
# Front-cover styles
#
# Each draws the same four things -- title, author, emblem, edition line -- in
# a different register, because one house style cannot suit a scholastic Latin
# commentary and a book of Heine's love poems equally. They share the panel
# geometry so any of them can be dropped into the wraparound or rendered on
# its own as the ebook cover.
# --------------------------------------------------------------------------- #
def _front_ornament(c, x0, y0, tw, th, *, title, author, src_lang, motif, font,
                    accent, ink, edition_line=None):
    """The original: ruled frame, title above a flourish, emblem centred."""
    _ornament_frame(c, x0, y0, tw, th, accent, 0.45 * inch)
    cx = x0 + tw / 2.0
    max_w = tw - 1.4 * inch

    title_top = y0 + th - 1.5 * inch
    size = _fitted(c, title, font[2], 34, 27, max_w)
    y = _centered(c, title, font[2], size, cx, title_top, ink, max_w,
                  leading=size * 1.12)

    c.saveState()
    c.setStrokeColor(accent)
    c.setFillColor(accent)
    decorations._flourish_rule(c, cx, y - 8, tw * 0.5)
    c.restoreState()

    _centered(c, author, font[0], 16, cx, y - 34, ink, max_w)
    _draw_emblem(c, motif, cx, y0 + th * 0.40, 1.5 * inch)
    _bottom_label(c, _edition_label(src_lang, motif, edition_line), font[0],
                  cx, y0, accent, max_w)


def _front_plate(c, x0, y0, tw, th, *, title, author, src_lang, motif, font,
                 accent, ink, edition_line=None):
    """An engraved plate: emblem in a roundel over a ruled title panel.

    The formal, scholarly one -- a title page treated as a frontispiece, which
    suits a critical edition better than a decorative border does.
    """
    cx = x0 + tw / 2.0
    max_w = tw - 1.7 * inch
    inset = 0.5 * inch

    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(2.2)
    c.rect(x0 + inset, y0 + inset, tw - 2 * inset, th - 2 * inset)
    c.setLineWidth(0.7)
    c.rect(x0 + inset + 5, y0 + inset + 5, tw - 2 * inset - 10, th - 2 * inset - 10)
    c.restoreState()

    # Roundel: the emblem sits in a ruled circle above the title. Placed a
    # little below the upper third so the whole group -- roundel, title,
    # author -- reads as centred rather than stranded at the top.
    medal_cy = y0 + th * 0.62
    radius = min(tw, th) * 0.155
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.1)
    c.circle(cx, medal_cy, radius, stroke=1, fill=0)
    c.setLineWidth(0.5)
    c.circle(cx, medal_cy, radius - 4, stroke=1, fill=0)
    c.restoreState()
    _draw_emblem(c, motif, cx, medal_cy, radius * 1.15)

    # Title panel below the roundel, between two rules.
    rule_y = medal_cy - radius - 0.45 * inch
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.0)
    c.line(cx - tw * 0.30, rule_y, cx + tw * 0.30, rule_y)
    c.restoreState()

    size = _fitted(c, title, font[2], 30, 23, max_w)
    y = _centered(c, title, font[2], size, cx, rule_y - size - 10, ink, max_w,
                  leading=size * 1.14)
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.0)
    c.line(cx - tw * 0.30, y + 2, cx + tw * 0.30, y + 2)
    c.restoreState()
    y = _centered(c, author, font[1], 15, cx, y - 26, ink, max_w)

    # A small flourish closes the group, so the space below it reads as margin
    # rather than as something missing.
    c.saveState()
    c.setStrokeColor(accent)
    c.setFillColor(accent)
    decorations._flourish_rule(c, cx, y - 0.34 * inch, tw * 0.30)
    c.restoreState()

    _bottom_label(c, _edition_label(src_lang, motif, edition_line), font[0],
                  cx, y0, accent, max_w)


def _front_typographic(c, x0, y0, tw, th, *, title, author, src_lang, motif,
                       font, accent, ink, edition_line=None):
    """Type only -- no emblem, no border. Rules and scale do the work.

    For titles that are their own decoration, and for source languages with no
    emblem of their own, where the ornamental styles fall back to a generic
    mark that says nothing.
    """
    cx = x0 + tw / 2.0
    max_w = tw - 1.3 * inch

    # A broad accent rule high on the panel, and the language above it.
    top_rule = y0 + th - 1.35 * inch
    lang = (motif.get("name") or src_lang).upper()
    c.setFont(font[0], 11)
    c.setFillColor(accent)
    c.drawCentredString(cx, top_rule + 0.28 * inch, " ".join(lang))
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(3.0)
    c.line(x0 + 0.65 * inch, top_rule, x0 + tw - 0.65 * inch, top_rule)
    c.restoreState()

    size = _fitted(c, title, font[2], 46, 34, max_w)
    y = _centered(c, title, font[2], size, cx, y0 + th * 0.60, ink, max_w,
                  leading=size * 1.06)

    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.0)
    c.line(cx - tw * 0.16, y - 0.20 * inch, cx + tw * 0.16, y - 0.20 * inch)
    c.restoreState()
    _centered(c, author, font[1], 17, cx, y - 0.46 * inch, ink, max_w)

    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(3.0)
    c.line(x0 + 0.65 * inch, y0 + 1.35 * inch,
           x0 + tw - 0.65 * inch, y0 + 1.35 * inch)
    c.restoreState()
    _bottom_label(c, _edition_label(src_lang, motif, edition_line), font[0],
                  cx, y0, accent, max_w)


def _front_band(c, x0, y0, tw, th, *, title, author, src_lang, motif, font,
                accent, ink, edition_line=None):
    """A solid accent band across the middle carrying the title, reversed out.

    The boldest of the four and the most legible as a thumbnail, which is how
    an ebook cover is actually seen most of the time.
    """
    cx = x0 + tw / 2.0
    max_w = tw - 1.5 * inch

    _draw_emblem(c, motif, cx, y0 + th * 0.79, 1.25 * inch)

    size = _fitted(c, title, font[2], 34, 26, max_w)
    lines = _wrap(c, title, font[2], size, max_w)
    leading = size * 1.14
    band_h = len(lines) * leading + 0.62 * inch
    band_top = y0 + th * 0.60
    band_bottom = band_top - band_h

    c.saveState()
    c.setFillColor(accent)
    c.rect(x0, band_bottom, tw, band_h, fill=1, stroke=0)
    c.restoreState()

    # Reversed out of the band. Paper white rather than the page background:
    # the band is a solid ink area, so the type has to be the lightest thing
    # available or it greys out at thumbnail size.
    paper = HexColor("#faf6ec")
    _centered(c, title, font[2], size, cx, band_top - 0.42 * inch, paper, max_w,
              leading=leading)

    _centered(c, author, font[1], 16, cx, band_bottom - 0.42 * inch, ink, max_w)
    _bottom_label(c, _edition_label(src_lang, motif, edition_line), font[0],
                  cx, y0, accent, max_w)


def _front_emblem(c, x0, y0, tw, th, *, title, author, src_lang, motif, font,
                  accent, ink, edition_line=None):
    """The language emblem blown up as a pale ground, type over the lower half.

    The emblems are the most distinctive thing the generator has, and at
    1.5 inches they read as a small badge. At this size the laurel or the
    meander becomes the cover.
    """
    cx = x0 + tw / 2.0
    max_w = tw - 1.4 * inch

    # A washed-out copy of the accent, so type stays the darkest thing present.
    wash = Color(accent.red, accent.green, accent.blue, alpha=0.20)
    pale = dict(motif)
    pale["color"] = "#000000"          # unused: _draw_emblem re-reads the hex
    c.saveState()
    c.setFillColor(wash)
    c.setStrokeColor(wash)
    fn = motif.get("emblem")
    if fn:
        fn(c, cx, y0 + th * 0.60, min(tw, th) * 0.62, wash)
    c.restoreState()

    size = _fitted(c, title, font[2], 38, 29, max_w)
    y = _centered(c, title, font[2], size, cx, y0 + th * 0.34, ink, max_w,
                  leading=size * 1.10)
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.0)
    c.line(cx - tw * 0.18, y - 0.16 * inch, cx + tw * 0.18, y - 0.16 * inch)
    c.restoreState()
    _centered(c, author, font[1], 16, cx, y - 0.42 * inch, ink, max_w)
    _bottom_label(c, _edition_label(src_lang, motif, edition_line), font[0],
                  cx, y0, accent, max_w)


def _front_column(c, x0, y0, tw, th, *, title, author, src_lang, motif, font,
                  accent, ink, edition_line=None):
    """A solid accent column down the spine edge carrying the language.

    Asymmetric, and the only style here that is: it gives a series a strong
    shelf presence, because the column is what shows when the book is upright
    among others.
    """
    col_w = tw * 0.22
    c.saveState()
    c.setFillColor(accent)
    c.rect(x0, y0, col_w, th, fill=1, stroke=0)
    c.restoreState()

    # The language, set vertically up the column and reversed out of it.
    paper = HexColor("#faf6ec")
    lang = (motif.get("name") or src_lang).upper()
    c.saveState()
    c.translate(x0 + col_w * 0.62, y0 + th * 0.5)
    c.rotate(90)
    c.setFont(font[0], 13)
    c.setFillColor(paper)
    c.drawCentredString(0, 0, " ".join(lang))
    c.restoreState()
    # Reversed out of the column: the emblem's own accent colour on an
    # accent-filled column is invisible.
    _draw_emblem(c, {**motif, "color": "#faf6ec"},
                 x0 + col_w * 0.5, y0 + th * 0.10, col_w * 0.62)

    # Type ranges left in the remaining field, not centred on the whole panel.
    left = x0 + col_w + 0.45 * inch
    max_w = (x0 + tw - 0.5 * inch) - left
    cx = left + max_w / 2.0
    size = _fitted(c, title, font[2], 34, 26, max_w)
    y = _centered(c, title, font[2], size, cx, y0 + th * 0.72, ink, max_w,
                  leading=size * 1.10)
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.2)
    c.line(left, y - 0.18 * inch, left + max_w * 0.45, y - 0.18 * inch)
    c.restoreState()
    _centered(c, author, font[1], 16, cx, y - 0.44 * inch, ink, max_w)

    label = _edition_label(src_lang, motif, edition_line)
    _centered(c, label, font[0], 10.5, cx, y0 + 0.95 * inch, accent, max_w)


def _front_arch(c, x0, y0, tw, th, *, title, author, src_lang, motif, font,
                accent, ink, edition_line=None):
    """A temple front: two pilasters and an arch, the emblem in the tympanum."""
    cx = x0 + tw / 2.0
    inset = 0.7 * inch
    left, right = x0 + inset, x0 + tw - inset
    base = y0 + 1.25 * inch
    spring = y0 + th - 2.5 * inch          # where the arch springs
    max_w = (right - left) - 0.35 * inch

    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(1.3)
    c.line(left, base, left, spring)
    c.line(right, base, right, spring)
    p = c.beginPath()                      # semicircular head
    p.moveTo(left, spring)
    r = (right - left) / 2.0
    p.curveTo(left, spring + r * 0.62, cx - r * 0.62, spring + r,
              cx, spring + r)
    p.curveTo(cx + r * 0.62, spring + r, right, spring + r * 0.62,
              right, spring)
    c.drawPath(p, fill=0, stroke=1)
    c.setLineWidth(0.6)                    # a stylobate under the pilasters
    c.line(left - 10, base, right + 10, base)
    c.line(left - 10, base - 4, right + 10, base - 4)
    c.restoreState()

    _draw_emblem(c, motif, cx, spring + r * 0.44, r * 0.72)

    size = _fitted(c, title, font[2], 30, 24, max_w)
    y = _centered(c, title, font[2], size, cx, spring - 0.34 * inch, ink, max_w,
                  leading=size * 1.12)
    c.saveState()
    c.setStrokeColor(accent)
    c.setLineWidth(0.8)
    c.line(cx - max_w * 0.28, y - 0.16 * inch, cx + max_w * 0.28, y - 0.16 * inch)
    c.restoreState()
    _centered(c, author, font[1], 15, cx, y - 0.42 * inch, ink, max_w)
    _bottom_label(c, _edition_label(src_lang, motif, edition_line), font[0],
                  cx, y0, accent, tw - 1.4 * inch)


_FRONT_STYLES = {
    "ornament": _front_ornament,
    "plate": _front_plate,
    "typographic": _front_typographic,
    "band": _front_band,
    "emblem": _front_emblem,
    "column": _front_column,
    "arch": _front_arch,
}
ALL_COVER_STYLES = list(_FRONT_STYLES)
DEFAULT_COVER_STYLE = "ornament"

# What each looks like, for the UI's picker — the names alone say very little.
COVER_STYLE_LABELS = {
    "ornament": "Ornamental — ruled border, flourish, centred emblem",
    "plate": "Engraved plate — emblem in a roundel over a ruled title panel",
    "typographic": "Typographic — no emblem; rules and scale only",
    "band": "Banded — title reversed out of a solid accent band",
    "emblem": "Emblem — the language emblem enlarged as a pale ground",
    "column": "Column — a solid accent column down the spine edge",
    "arch": "Arch — a temple front, emblem in the tympanum",
}


def _draw_front(c, x0, y0, tw, th, *, title, author, src_lang, tgt_lang,
                motif, font, accent, ink, edition_line=None,
                style: str = DEFAULT_COVER_STYLE):
    draw = _FRONT_STYLES.get(style or DEFAULT_COVER_STYLE)
    if draw is None:
        raise ValueError(f"unknown cover style {style!r}; "
                         f"choose from {ALL_COVER_STYLES}")
    draw(c, x0, y0, tw, th, title=title, author=author, src_lang=src_lang,
         motif=motif, font=font, accent=accent, ink=ink,
         edition_line=edition_line)


def _draw_spine(c, x0, y0, spine, th, *, title, author, motif, font, accent, ink, bg):
    if spine < 0.18 * inch:
        return
    cx = x0 + spine / 2.0
    c.saveState()
    c.translate(cx, y0 + th / 2.0)
    c.rotate(90)
    c.setFillColor(ink)
    # Title then author along the spine (KDP allows spine text at ~100+ pages).
    c.setFont(font[2], min(spine * 0.62 / inch * 18, 15))
    c.drawCentredString(th * 0.12, -spine * 0.16, title)
    c.setFont(font[0], min(spine * 0.5 / inch * 18, 12))
    c.drawCentredString(-th * 0.30, -spine * 0.16, author)
    c.restoreState()
    # tiny diamond near the top of the spine
    c.setFillColor(accent)
    decorations._diamond(c, cx, y0 + th - 0.5 * inch, max(1.5, spine * 0.12))


def _draw_back(c, x0, y0, tw, th, *, blurb, motif, font, accent, ink, publisher):
    _ornament_frame(c, x0, y0, tw, th, accent, 0.45 * inch)
    cx = x0 + tw / 2.0
    _draw_emblem(c, motif, cx, y0 + th - 1.5 * inch, 0.95 * inch)
    if blurb:
        style = ParagraphStyle("blurb", fontName=font[0], fontSize=12.5,
                               leading=18, alignment=TA_CENTER, textColor=ink)
        fw, fh = tw - 1.6 * inch, th * 0.42
        frame = Frame(x0 + 0.8 * inch, y0 + th * 0.34, fw, fh, showBoundary=0)
        frame.addFromList([Paragraph(blurb, style)], c)
    # Publisher above the (reserved) barcode zone
    if publisher:
        c.setFont(font[0], 11)
        c.setFillColor(accent)
        c.drawCentredString(cx, y0 + 1.5 * inch, publisher)
    # Keep the bottom-right ~2x1.2in clear for the KDP barcode (no drawing there).


def render_cover(out_path: str, *, style: str = DEFAULT_COVER_STYLE,
                 title: str, author: str, src_lang: str,
                 tgt_lang: str, trim, pages: int, paper: str = "white",
                 font_spec: FontSpec | None = None, background: str = "#f4ead5",
                 accent: str | None = None, blurb: str = "",
                 publisher: str = "", edition_line: str | None = None) -> tuple[str, tuple]:
    full_w, full_h, spine = cover_dimensions(trim, pages, paper)
    W, H = full_w * inch, full_h * inch
    c = canvas.Canvas(out_path, pagesize=(W, H))

    font = fonts.register(font_spec.family if font_spec else None,
                          {"regular": getattr(font_spec, "regular", None),
                           "italic": getattr(font_spec, "italic", None),
                           "bold": getattr(font_spec, "bold", None)} if font_spec else None)
    motif = _motif_for(src_lang, accent)
    accent_color = HexColor(motif["color"])
    ink = HexColor("#241f1a")
    bg = HexColor(background)

    c.setFillColor(bg)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    bleed = BLEED * inch
    tw, th = trim[0] * inch, trim[1] * inch
    spine_pt = spine * inch
    y0 = bleed
    back_x0 = bleed
    spine_x0 = bleed + tw
    front_x0 = bleed + tw + spine_pt

    _draw_back(c, back_x0, y0, tw, th, blurb=blurb, motif=motif, font=font,
               accent=accent_color, ink=ink, publisher=publisher)
    _draw_spine(c, spine_x0, y0, spine_pt, th, title=title, author=author,
                motif=motif, font=font, accent=accent_color, ink=ink, bg=bg)
    _draw_front(c, front_x0, y0, tw, th, style=style, title=title, author=author,
                src_lang=src_lang, tgt_lang=tgt_lang, motif=motif, font=font,
                accent=accent_color, ink=ink, edition_line=edition_line)

    c.showPage()
    c.save()
    return out_path, (full_w, full_h, spine)


def render_ebook_cover(out_path: str, *, style: str = DEFAULT_COVER_STYLE,
                       title: str, author: str, src_lang: str,
                       tgt_lang: str, trim, font_spec: FontSpec | None = None,
                       background: str = "#f4ead5", accent: str | None = None,
                       dpi: int = 400, edition_line: str | None = None) -> str:
    """Render just the front-cover panel (no spine/back/bleed) as a PNG, for EPUB.

    Reuses _draw_front so the ebook cover matches the print wraparound's
    per-language motif. Requires PyMuPDF (see requirements-epub.txt) to
    rasterize the single-page PDF.
    """
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "render_ebook_cover needs PyMuPDF: pip install -r requirements-epub.txt"
        ) from exc

    tw, th = trim[0] * inch, trim[1] * inch
    font = fonts.register(font_spec.family if font_spec else None,
                          {"regular": getattr(font_spec, "regular", None),
                           "italic": getattr(font_spec, "italic", None),
                           "bold": getattr(font_spec, "bold", None)} if font_spec else None)
    motif = _motif_for(src_lang, accent)
    accent_color = HexColor(motif["color"])
    ink = HexColor("#241f1a")
    bg = HexColor(background)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = str(Path(tmp) / "front.pdf")
        c = canvas.Canvas(tmp_pdf, pagesize=(tw, th))
        c.setFillColor(bg)
        c.rect(0, 0, tw, th, fill=1, stroke=0)
        _draw_front(c, 0, 0, tw, th, style=style, title=title, author=author,
                    src_lang=src_lang, tgt_lang=tgt_lang, motif=motif, font=font,
                    accent=accent_color, ink=ink, edition_line=edition_line)
        c.showPage()
        c.save()

        doc = fitz.open(tmp_pdf)
        pix = doc[0].get_pixmap(dpi=dpi)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        pix.save(out_path)
        doc.close()
    return out_path
