"""Render aligned beads to a KDP print-ready interior PDF using ReportLab."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.lib.styles import ParagraphStyle

from . import decorations, fonts
from .model import Bead, Chapter, DecorSpec, FontSpec


def _register_font(spec: FontSpec | None) -> tuple[str, str, str]:
    """Register the requested font via the dynamic fonts registry.

    Returns (regular, italic, bold) registered font names; falls back to the
    built-in Times family (no Greek coverage) when fonts/ is empty.
    """
    spec = spec or FontSpec()
    overrides = {"regular": spec.regular, "italic": spec.italic, "bold": spec.bold}
    return fonts.register(spec.family, overrides)


def _gutter_for_page_count(pages: int) -> float:
    """KDP minimum inside (gutter) margin grows with page count."""
    if pages <= 150:
        return 0.375 * inch
    if pages <= 300:
        return 0.5 * inch
    if pages <= 500:
        return 0.625 * inch
    if pages <= 700:
        return 0.75 * inch
    return 0.875 * inch


class _BookDoc(BaseDocTemplate):
    """Two mirrored page templates (recto/verso) for correct gutter placement."""

    def __init__(self, filename, trim, gutter, title, decor: DecorSpec, **kw):
        w, h = trim[0] * inch, trim[1] * inch
        self.book_title = title
        self.decor = decor or DecorSpec()
        super().__init__(filename, pagesize=(w, h), **kw)

        outside = 0.5 * inch
        top = 0.6 * inch
        bottom = 0.6 * inch
        text_w = w - gutter - outside
        text_h = h - top - bottom
        self._page_w = w
        self._outside = outside
        # Text-block edges for each side, consumed by the margin renderer.
        self._geom_recto = {"left": gutter, "right": w - outside,
                            "top": h - top, "bottom": bottom,
                            "page_w": w, "outside": outside}
        self._geom_verso = {"left": outside, "right": w - gutter,
                            "top": h - top, "bottom": bottom,
                            "page_w": w, "outside": outside}

        # Recto (odd / right-hand): gutter on the LEFT.
        recto = Frame(gutter, bottom, text_w, text_h, id="recto")
        # Verso (even / left-hand): gutter on the RIGHT.
        verso = Frame(outside, bottom, text_w, text_h, id="verso")

        self.addPageTemplates([
            PageTemplate(id="recto", frames=[recto], onPage=self._furniture, autoNextPageTemplate="verso"),
            PageTemplate(id="verso", frames=[verso], onPage=self._furniture, autoNextPageTemplate="recto"),
        ])

    def _furniture(self, canvas, doc):
        recto = (doc.page % 2 == 1)
        # Title page (page 1) stays clean.
        if doc.page > 1:
            geom = self._geom_recto if recto else self._geom_verso
            decorations.draw_margin(
                canvas, geom, recto, self.decor.margin, self.decor.color,
                self.decor.corner_image,
            )
        canvas.saveState()
        canvas.setFont("Times-Roman", 9)
        canvas.drawCentredString(self._page_w / 2.0, 0.35 * inch, str(doc.page))
        canvas.restoreState()


def _styles(fonts: tuple[str, str, str], first: str):
    font, italic, bold = fonts
    src_color = HexColor("#1a1a1a")
    tgt_color = HexColor("#555555")
    src = ParagraphStyle(
        "src", fontName=font, fontSize=10.5, leading=14, textColor=src_color,
        spaceBefore=0, spaceAfter=2,
    )
    tgt = ParagraphStyle(
        "tgt", fontName=italic, fontSize=10, leading=13.5,
        textColor=tgt_color, leftIndent=14, spaceBefore=0, spaceAfter=8,
    )
    head = ParagraphStyle(
        "head", fontName=bold, fontSize=15, leading=20,
        alignment=TA_CENTER, spaceBefore=18, spaceAfter=14,
    )
    title = ParagraphStyle(
        "title", fontName=bold, fontSize=26, leading=32,
        alignment=TA_CENTER, spaceBefore=120, spaceAfter=12,
    )
    sub = ParagraphStyle(
        "sub", fontName=font, fontSize=14, leading=20, alignment=TA_CENTER,
    )
    return {"src": src, "tgt": tgt, "head": head, "title": title, "sub": sub}


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render(
    chapters: list[Chapter],
    *,
    out_path: str,
    title: str,
    author: str,
    src_lang: str,
    tgt_lang: str,
    trim: tuple[float, float],
    first: str = "src",
    estimated_pages: int = 200,
    font_spec: FontSpec | None = None,
    decor: DecorSpec | None = None,
) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    decor = decor or DecorSpec()
    font = _register_font(font_spec)
    gutter = _gutter_for_page_count(estimated_pages)
    st = _styles(font, first)

    doc = _BookDoc(out_path, trim, gutter, title, decor, author=author)

    story = []
    # --- Title page ---
    story.append(Paragraph(_esc(title), st["title"]))
    story.append(Paragraph(_esc(author), st["sub"]))
    story.append(Spacer(1, 40))
    story.append(Paragraph(
        f"{src_lang.upper()} &ndash; {tgt_lang.upper()} parallel edition", st["sub"]
    ))
    story.append(NextPageTemplate("verso"))
    story.append(PageBreak())

    # --- Body ---
    for ch in chapters:
        if ch.title:
            story.append(Paragraph(_esc(ch.title), st["head"]))
        orn = decorations.chapter_ornament(
            decor.chapter, decor.color, image=decor.chapter_image,
        )
        if orn is not None and (ch.title or decor.chapter_image):
            story.append(orn)
            story.append(Spacer(1, 8))
        for i, bead in enumerate(ch.beads):
            if i > 0 and decor.bead_separator == "fleuron":
                sep = decorations.chapter_ornament("fleuron", decor.color)
                if sep is not None:
                    story.append(sep)
            _render_bead(story, bead, st, first)

    doc.build(story)
    return out_path


def _render_bead(story, bead: Bead, st, first: str):
    src_txt = _esc(bead.src_text)
    tgt_txt = _esc(bead.tgt_text)
    blocks = []
    if first == "tgt":
        if tgt_txt:
            blocks.append(Paragraph(tgt_txt, st["src"]))
        if src_txt:
            blocks.append(Paragraph(src_txt, st["tgt"]))
    else:
        if src_txt:
            blocks.append(Paragraph(src_txt, st["src"]))
        if tgt_txt:
            blocks.append(Paragraph(tgt_txt, st["tgt"]))
    story.extend(blocks)
