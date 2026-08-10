#!/usr/bin/env python
"""One-off build for input/doc376_victorian.pdf: a single-language (English)
machine-translated, LLM-stylized "Victorian prose" rendering of Claudius
Salmasius's Latin treatise "De modo usurarum liber". Not a Gutenberg
dual-language source, so it doesn't go through pipeline.build_book() (which
expects two languages to align) — this extracts the PDF's own text, splits it
into paragraph-sized beads with only the src side populated, chunks it into
sized "Part N" pseudo-chapters (the source has no reliable chapter headings
after OCR/translation corruption), and renders PDF + cover + EPUB directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent))

from book_creator import cover, render_epub, render_pdf
from book_creator.model import Bead, Chapter, CopyrightSpec, CoverSpec, DecorSpec, FontSpec

SRC_PDF = "input/doc376_victorian.pdf"
TITLE = "De Modo Usurarum Liber"
AUTHOR = "Claudius Salmasius"
SLUG = "de-modo-usurarum-liber"
SRC_LANG = "en"   # the rendered text itself is English prose
TGT_LANG = "en"

PARAGRAPHS_PER_PART = 55  # ~ a chapter-sized chunk, purely for pagination/TOC


_MERGE_TARGET = 420  # roughly a short paragraph's worth of prose


def extract_paragraphs() -> list[str]:
    """The source PDF has no blank-line paragraph markers in its plain text
    stream (paragraph spacing came from flowable layout, not literal blank
    lines), so segment._paragraphs() can't find breaks — the whole thing
    collapses into one 1.7M-character blob. Block-level extraction recovers
    real boundaries, but the source was apparently rendered one sentence per
    flowable (avg block length ~110 chars): reading that as one paragraph per
    sentence would look like a choppy list, not prose, so consecutive blocks
    are merged up to ~_MERGE_TARGET chars, breaking only at a block that ends
    in sentence-final punctuation so a merged paragraph doesn't end mid-clause."""
    doc = fitz.open(SRC_PDF)
    blocks: list[str] = []
    # Page 0 is our own auto-generated description page, not part of the work.
    for i in range(1, doc.page_count):
        for block in doc[i].get_text("blocks"):
            text = " ".join(block[4].split())  # collapse internal wrapping
            if len(text) >= 2:
                blocks.append(text)
    doc.close()

    paras: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for b in blocks:
        buf.append(b)
        buf_len += len(b) + 1
        if buf_len >= _MERGE_TARGET and b.rstrip()[-1:] in ".!?”’":
            paras.append(" ".join(buf))
            buf, buf_len = [], 0
    if buf:
        paras.append(" ".join(buf))
    return paras


def build_chapters(paragraphs: list[str]) -> list[Chapter]:
    chapters = []
    for start in range(0, len(paragraphs), PARAGRAPHS_PER_PART):
        chunk = paragraphs[start:start + PARAGRAPHS_PER_PART]
        beads = [Bead(src=[p], tgt=[]) for p in chunk]
        idx = start // PARAGRAPHS_PER_PART + 1
        chapters.append(Chapter(title=f"Part {idx}", src_segments=chunk,
                                tgt_segments=[], beads=beads))
    return chapters


def main() -> None:
    print("Extracting text...")
    paragraphs = extract_paragraphs()
    print(f"  {len(paragraphs)} paragraphs")

    chapters = build_chapters(paragraphs)
    print(f"  chunked into {len(chapters)} parts")

    font = FontSpec(family="OldStandard")
    decor = DecorSpec(
        margin="corners",
        chapter="victorian",
        color="#5c3b1e",           # aged-parchment brown, fits a legal treatise
        opener_font="uncialantiqua",
    )
    copyright = CopyrightSpec(
        enabled=True,
        publisher="Houser Classics",
        holder="Joey Houser",
        year=2026,
        rights=(
            "This edition's typography, arrangement, and design are copyright "
            "&copy; 2026 Joey Houser. The underlying Latin work, <i>De modo "
            "usurarum liber</i> by Claudius Salmasius (1588&ndash;1653), is in "
            "the public domain. This English text is a machine-translated "
            "(NLLB) rendering, restyled into Victorian-era prose by a local "
            "LLM stylizer; it is not a historical human translation. A small "
            "number of passages (source OCR/translation artifacts, including "
            "garbled embedded Greek) were not successfully translated and are "
            "flagged as such in the text."
        ),
    )
    cover_spec = CoverSpec(
        enabled=True,
        paper="white",
        blurb=(
            "A machine-translated, Victorian-prose-stylized English rendering "
            "of Claudius Salmasius's 17th-century Latin treatise on usury and "
            "interest — produced via automated translation (NLLB) and "
            "LLM restyling from a public-domain Latin source."
        ),
    )

    # Plain Unicode em-dash (not the &mdash; entity): render_pdf/render_epub's
    # Paragraph markup would interpret an entity fine, but cover.py draws this
    # string with a raw canvas.drawCentredString call that does no entity
    # substitution, so it needs to already be a literal character.
    edition_line = "Victorian-Prose English Rendering — from the Latin of Salmasius"

    trim = (6.0, 9.0)
    out_pdf = f"output/{SLUG}.pdf"
    print(f"Rendering PDF -> {out_pdf}")
    _, actual_pages = render_pdf.render(
        chapters, out_path=out_pdf, title=TITLE, author=AUTHOR,
        src_lang=SRC_LANG, tgt_lang=TGT_LANG, trim=trim, first="src",
        estimated_pages=max(24, sum(len(p) for p in paragraphs) // 1400),
        font_spec=font, decor=decor, copyright=copyright,
        translation_note="", include_toc=True, edition_line=edition_line,
    )
    print(f"  {actual_pages} pages")

    cover_path = f"output/{SLUG}-cover.pdf"
    print(f"Rendering cover -> {cover_path}")
    _, dims = cover.render_cover(
        cover_path, title=TITLE, author=AUTHOR, src_lang="la", tgt_lang=TGT_LANG,
        trim=trim, pages=actual_pages, paper=cover_spec.paper, font_spec=font,
        background=cover_spec.background, accent=cover_spec.accent,
        blurb=cover_spec.blurb, publisher=copyright.publisher,
        edition_line=edition_line,
    )
    print(f"  {dims[0]:.3f} x {dims[1]:.3f} in, spine {dims[2]:.3f} in")

    ebook_cover_path = f"output/{SLUG}-epub-cover.png"
    print(f"Rendering EPUB cover -> {ebook_cover_path}")
    cover.render_ebook_cover(
        ebook_cover_path, title=TITLE, author=AUTHOR, src_lang="la",
        tgt_lang=TGT_LANG, trim=trim, font_spec=font,
        background=cover_spec.background, accent=cover_spec.accent,
        edition_line=edition_line,
    )

    out_epub = f"output/{SLUG}.epub"
    print(f"Rendering EPUB -> {out_epub}")
    render_epub.render(
        chapters, out_path=out_epub, title=TITLE, author=AUTHOR,
        src_lang=SRC_LANG, tgt_lang=TGT_LANG, first="src", font_spec=font,
        decor=decor, copyright=copyright, translation_note="",
        cover_image_path=ebook_cover_path, edition_line=edition_line,
    )
    print("Done.")


if __name__ == "__main__":
    main()
