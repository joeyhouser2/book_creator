"""Generate a KDP wraparound cover (back + spine + front) with a per-language motif.

KDP wants a single PDF spanning the whole wrap, sized from the trim, the page
count (which sets the spine width), and the paper stock, plus 0.125" bleed all
round. Each source language gets its own accent colour and vector emblem.
"""

from __future__ import annotations

import math

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
    x0, y0 = cx - 2.5 * u, cy - 2.5 * u
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


def _draw_front(c, x0, y0, tw, th, *, title, author, src_lang, tgt_lang,
                motif, font, accent, ink):
    _ornament_frame(c, x0, y0, tw, th, accent, 0.45 * inch)
    cx = x0 + tw / 2.0
    max_w = tw - 1.4 * inch

    # Title block (upper third)
    title_top = y0 + th - 1.5 * inch
    size = 34 if c.stringWidth(title, font[2], 34) <= max_w * 1.8 else 27
    y = _centered(c, title, font[2], size, cx, title_top, ink, max_w, leading=size * 1.12)

    # fleuron divider
    c.saveState()
    c.setStrokeColor(accent)
    c.setFillColor(accent)
    decorations._flourish_rule(c, cx, y - 8, tw * 0.5)
    c.restoreState()

    _centered(c, author, font[0], 16, cx, y - 34, ink, max_w)

    # Central emblem
    _draw_emblem(c, motif, cx, y0 + th * 0.40, 1.5 * inch)

    # Edition line near the bottom
    lang = motif.get("name") or src_lang.upper()
    label = f"{lang}–English Parallel Edition".upper()
    c.setFont(font[0], 11.5)
    c.setFillColor(accent)
    c.drawCentredString(cx, y0 + 0.95 * inch, label)


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


def render_cover(out_path: str, *, title: str, author: str, src_lang: str,
                 tgt_lang: str, trim, pages: int, paper: str = "white",
                 font_spec: FontSpec | None = None, background: str = "#f4ead5",
                 accent: str | None = None, blurb: str = "",
                 publisher: str = "") -> tuple[str, tuple]:
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
    _draw_front(c, front_x0, y0, tw, th, title=title, author=author,
                src_lang=src_lang, tgt_lang=tgt_lang, motif=motif, font=font,
                accent=accent_color, ink=ink)

    c.showPage()
    c.save()
    return out_path, (full_w, full_h, spine)
