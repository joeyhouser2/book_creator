"""Render aligned beads to a KDP print-ready interior PDF using ReportLab."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import ParagraphStyle

from . import decorations, fonts
from .model import Bead, Chapter, CopyrightSpec, DecorSpec, FontSpec

_LANG_NAMES = {
    "la": "Latin", "fr": "French", "grc": "Ancient Greek", "el": "Greek",
    "de": "German", "it": "Italian", "es": "Spanish", "en": "English",
}


def _lang_name(code: str) -> str:
    return _LANG_NAMES.get(code, code.upper())


class _BodyStart(Flowable):
    """Zero-size sentinel marking where the body begins, so the document can tell
    front matter (unnumbered, undecorated) from body pages."""

    def wrap(self, *_):
        return (0, 0)

    def draw(self):
        pass


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
        # First body page. Pages before it (title, copyright, contents) get no
        # margin art and no page number. Set by afterFlowable (or directly when
        # there's no TOC and a single build pass is used).
        self._body_start_page: int | None = None
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

    def afterFlowable(self, flowable):
        if isinstance(flowable, _BodyStart):
            self._body_start_page = self.page
        elif isinstance(flowable, Paragraph) and flowable.style.name == "head":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))

    def _furniture(self, canvas, doc):
        # Front matter (title, copyright, contents) stays clean and unnumbered.
        bsp = self._body_start_page
        if bsp is None or doc.page < bsp:
            return
        recto = (doc.page % 2 == 1)
        geom = self._geom_recto if recto else self._geom_verso
        decorations.draw_margin(
            canvas, geom, recto, self.decor.margin, self.decor.color,
            self.decor.corner_image,
        )
        canvas.saveState()
        canvas.setFont("Times-Roman", 9)
        canvas.drawCentredString(self._page_w / 2.0, 0.35 * inch, str(doc.page))
        canvas.restoreState()


def _styles(fonts: tuple[str, str, str], first: str, opener_font: str | None = None):
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
    if opener_font:
        src_open = ParagraphStyle(
            "src_open", parent=src, fontName=opener_font, fontSize=15.5,
            leading=20, spaceAfter=6,
        )
        tgt_open = ParagraphStyle(
            "tgt_open", parent=tgt, fontName=opener_font, fontSize=13,
            leading=17,
        )
    else:
        src_open, tgt_open = src, tgt
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
    cr = ParagraphStyle(
        "cr", fontName=font, fontSize=8.5, leading=12.5,
        textColor=HexColor("#333333"), spaceAfter=7,
    )
    toc_head = ParagraphStyle(
        "tochead", fontName=bold, fontSize=16, leading=22,
        alignment=TA_CENTER, spaceBefore=10, spaceAfter=22,
    )
    toc0 = ParagraphStyle(
        "toc0", fontName=font, fontSize=11.5, leading=20,
    )
    music_caption = ParagraphStyle(
        "music_caption", fontName=italic, fontSize=8.5, leading=11,
        textColor=HexColor("#555555"), alignment=TA_CENTER,
        spaceBefore=4, spaceAfter=14,
    )
    return {"src": src, "tgt": tgt, "src_open": src_open, "tgt_open": tgt_open,
            "head": head, "title": title, "sub": sub,
            "cr": cr, "tochead": toc_head, "toc0": toc0,
            "music_caption": music_caption}


def copyright_text(cr: CopyrightSpec, *, title: str, author: str,
                   src_lang: str, translation_note: str) -> tuple[list[str], list[str]]:
    """Copyright-page lines (ReportLab/XHTML markup, e.g. &mdash; / &copy; /
    <i>...</i>, is allowed and NOT escaped further), shared by PDF and EPUB.

    Claims compilation rights only, never the public-domain text itself.
    `cr.rights`, like the auto-generated wording it replaces, is trusted
    publisher-authored markup — not escaped, so it can use entities/<i> the
    same way the generated paragraphs below do. Only genuinely dynamic,
    untrusted fields (title/author/holder/translator names) get `_esc()`.
    Returns (body_paragraphs, tail_lines) — tail is the imprint/ISBN/printed-in block.
    """
    lang = _lang_name(src_lang)
    paras: list[str] = []

    if cr.rights:
        paras.append(cr.rights)
    else:
        holder = cr.holder or cr.publisher
        if holder:
            year = f" {cr.year}" if cr.year else ""
            paras.append(
                f"This parallel edition &mdash; its translation arrangement, "
                f"typography, and design &mdash; copyright &copy;{year} {_esc(holder)}."
            )
        trans = (f" The English translation by {_esc(cr.translator)} is in the "
                 "public domain." if cr.translator
                 else " The English translation is in the public domain.")
        paras.append(
            f"The original {lang} text by {_esc(author)} is in the public domain."
            + trans + " No copyright is claimed on these public-domain texts."
        )
        src_line = "Source texts: Project Gutenberg (www.gutenberg.org)."
        if translation_note:
            src_line += " Translation: " + _esc(translation_note)
        paras.append(src_line)

    tail: list[str] = []
    if cr.publisher:
        tail.append(_esc(cr.publisher))
    if cr.isbn:
        tail.append("ISBN " + _esc(cr.isbn))
    tail.append("Printed in the United States of America.")
    return paras, tail


def _copyright_flowables(cr: CopyrightSpec, *, title: str, author: str,
                         src_lang: str, translation_note: str,
                         trim: tuple[float, float], style) -> list:
    """Build the copyright page flowables — see copyright_text() for the wording."""
    paras, tail = copyright_text(cr, title=title, author=author, src_lang=src_lang,
                                 translation_note=translation_note)

    # Sit the block in the lower portion of the page, like a traditional colophon.
    top_pad = max(40, (trim[1] * 72 - 1.2 * 72) - 250)
    flows: list = [Spacer(1, top_pad)]
    for p in paras:
        flows.append(Paragraph(p, style))
    flows.append(Spacer(1, 6))
    for t in tail:
        flows.append(Paragraph(t, style))
    return flows


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _music_flowables(image_paths: list[str], caption: str, st, max_width: float) -> list:
    """Grand-staff page images (see music.py), scaled to fit the text column,
    each followed by a small attribution caption."""
    flows: list = []
    for idx, path in enumerate(image_paths):
        try:
            px_w, px_h = ImageReader(path).getSize()
        except Exception:
            continue
        # LilyPond rendered these at 300 dpi.
        pt_w, pt_h = px_w / 300.0 * 72.0, px_h / 300.0 * 72.0
        scale = min(1.0, max_width / pt_w) if pt_w else 1.0
        img = Image(path, width=pt_w * scale, height=pt_h * scale)
        img.hAlign = "CENTER"
        flows.append(img)
        if idx == len(image_paths) - 1 and caption:
            flows.append(Paragraph(_esc(caption), st["music_caption"]))
        else:
            flows.append(Spacer(1, 4))
    return flows


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
    copyright: CopyrightSpec | None = None,
    translation_note: str = "",
    include_toc: bool = True,
    edition_line: str | None = None,
) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    decor = decor or DecorSpec()
    copyright = copyright or CopyrightSpec()
    font = _register_font(font_spec)
    gutter = _gutter_for_page_count(estimated_pages)
    opener_font = fonts.register(decor.opener_font)[0] if decor.opener_font else None
    st = _styles(font, first, opener_font)
    text_width = trim[0] * inch - gutter - 0.5 * inch  # matches _BookDoc's text_w

    # A TOC is only meaningful when there are at least two titled divisions.
    titled = [ch for ch in chapters if ch.title]
    want_toc = include_toc and len(titled) >= 2

    doc = _BookDoc(out_path, trim, gutter, title, decor, author=author)

    story = []
    # --- Title page (recto) ---
    story.append(Paragraph(_esc(title), st["title"]))
    story.append(Paragraph(_esc(author), st["sub"]))
    story.append(Spacer(1, 40))
    story.append(Paragraph(
        edition_line or f"{src_lang.upper()} &ndash; {tgt_lang.upper()} parallel edition",
        st["sub"],
    ))

    # --- Copyright page (verso) — pages auto-alternate recto/verso ---
    if copyright.enabled:
        story.append(PageBreak())
        story.extend(_copyright_flowables(
            copyright, title=title, author=author, src_lang=src_lang,
            translation_note=translation_note, trim=trim, style=st["cr"],
        ))

    # --- Table of contents ---
    if want_toc:
        story.append(PageBreak())
        story.append(Paragraph("Contents", st["tochead"]))
        toc = TableOfContents()
        toc.dotsMinLevel = 0
        toc.levelStyles = [st["toc0"]]
        story.append(toc)

    # --- Body begins here ---
    story.append(PageBreak())
    story.append(_BodyStart())
    if not want_toc:
        # Single build pass: the sentinel's afterFlowable fires after this page's
        # furniture, so set the body-start page directly. Title (1) + copyright.
        doc._body_start_page = 2 + (1 if copyright.enabled else 0)

    for ch_idx, ch in enumerate(chapters):
        if ch_idx > 0:
            story.append(PageBreak())
        if ch.title:
            story.append(Paragraph(_esc(ch.title), st["head"]))
        chapter_style = (decorations.pick_random_style(ch_idx)
                        if decor.chapter == "random" else decor.chapter)
        orn = decorations.chapter_ornament(
            chapter_style, decor.color, image=decor.chapter_image,
        )
        if orn is not None and (ch.title or decor.chapter_image):
            story.append(orn)
            story.append(Spacer(1, 8))
        for i, bead in enumerate(ch.beads):
            if i > 0 and decor.bead_separator == "fleuron":
                sep = decorations.chapter_ornament("fleuron", decor.color)
                if sep is not None:
                    story.append(sep)
            _render_bead(story, bead, st, first, opener=(i == 0 and opener_font))
        if ch.music_images:
            story.append(Spacer(1, 6))
            story.extend(_music_flowables(ch.music_images, ch.music_caption, st, text_width))

    if want_toc:
        doc.multiBuild(story)   # extra passes resolve TOC page numbers
    else:
        doc.build(story)
    return out_path, doc.page   # doc.page is the final page count


def _render_bead(story, bead: Bead, st, first: str, opener: bool = False):
    src_txt = _esc(bead.src_text)
    tgt_txt = _esc(bead.tgt_text)
    src_style = st["src_open"] if opener else st["src"]
    tgt_style = st["tgt_open"] if opener else st["tgt"]
    blocks = []
    if first == "tgt":
        if tgt_txt:
            blocks.append(Paragraph(tgt_txt, src_style))
        if src_txt:
            blocks.append(Paragraph(src_txt, tgt_style))
    else:
        if src_txt:
            blocks.append(Paragraph(src_txt, src_style))
        if tgt_txt:
            blocks.append(Paragraph(tgt_txt, tgt_style))
    story.extend(blocks)
