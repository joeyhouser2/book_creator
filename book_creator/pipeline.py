"""Orchestrate the full build: fetch -> clean -> segment -> align -> render."""

from __future__ import annotations

import re
from pathlib import Path

from . import aligners, fetch, render_pdf, segment
from .model import BookSpec, Chapter


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "book"


def _apply_range(divisions: list[tuple[str, str]],
                 rng: tuple[int, int] | None) -> list[tuple[str, str]]:
    """Keep divisions [first, last] (1-based, inclusive). None keeps everything."""
    if not rng:
        return divisions
    first, last = rng
    first = max(1, first)
    last = min(len(divisions), last)
    return divisions[first - 1:last]


def _estimate_pages(chapters: list[Chapter]) -> int:
    """Rough page estimate so we can pick the right KDP gutter margin."""
    chars = sum(len(b.src_text) + len(b.tgt_text) for ch in chapters for b in ch.beads)
    # ~1,400 rendered characters per 6x9 page is a conservative average.
    return max(24, round(chars / 1400))


def build_book(spec: BookSpec, *, out_dir: str = "output", verbose: bool = True,
               on_log=None) -> str:
    def log(msg: str) -> None:
        if verbose:
            print(msg)
        if on_log is not None:
            on_log(msg)

    if not spec.translation_pd_confirmed:
        log(
            "  ⚠  translation_pd_confirmed is False. A translator holds copyright on "
            "their translation separately from the public-domain original. Verify the "
            "translation is public domain (US: published before 1929) before publishing."
        )

    log(f"• Fetching source ({spec.src_lang})…")
    src_text = fetch.load_text(path=spec.src_path, gid=spec.src_gutenberg_id)
    log(f"• Fetching translation ({spec.tgt_lang})…")
    tgt_text = fetch.load_text(path=spec.tgt_path, gid=spec.tgt_gutenberg_id)

    # Structural anchoring: split both sides into divisions, optionally scoping
    # each to a selected range so the two editions cover the same content.
    src_chaps = _apply_range(segment.detect_chapters(src_text), spec.src_range)
    tgt_chaps = _apply_range(segment.detect_chapters(tgt_text), spec.tgt_range)
    rng = ""
    if spec.src_range or spec.tgt_range:
        rng = f" (range src={spec.src_range or 'all'}, tgt={spec.tgt_range or 'all'})"
    log(f"• Divisions used — source: {len(src_chaps)}, translation: {len(tgt_chaps)}{rng}")

    if len(src_chaps) == len(tgt_chaps) and len(src_chaps) > 1:
        paired = list(zip(src_chaps, tgt_chaps))
        log("• Anchoring on matched division boundaries.")
    else:
        # Concatenate each side and align as one block.
        src_body = "\n\n".join(b for _, b in src_chaps)
        tgt_body = "\n\n".join(b for _, b in tgt_chaps)
        paired = [(("", src_body), ("", tgt_body))]
        if len(src_chaps) != len(tgt_chaps):
            log("• Division counts differ; aligning selected text as a single block.")

    aligners.reset_announcement()
    chapters: list[Chapter] = []
    for (s_title, s_body), (t_title, t_body) in paired:
        src_segs = segment.segment(s_body, spec.mode, spec.src_lang)
        tgt_segs = segment.segment(t_body, spec.mode, spec.tgt_lang)
        beads = aligners.align(src_segs, tgt_segs, method=spec.aligner, log=log)
        chapters.append(Chapter(title=t_title or s_title, src_segments=src_segs,
                                tgt_segments=tgt_segs, beads=beads))

    total_beads = sum(len(c.beads) for c in chapters)
    log(f"• Aligned into {total_beads} bead(s) across {len(chapters)} chapter(s).")

    pages = _estimate_pages(chapters)
    slug = spec.slug or _slugify(spec.title)
    out_path = str(Path(out_dir) / f"{slug}.pdf")

    log(f"• Rendering PDF (≈{pages} pages) → {out_path}")
    render_pdf.render(
        chapters,
        out_path=out_path,
        title=spec.title,
        author=spec.author,
        src_lang=spec.src_lang,
        tgt_lang=spec.tgt_lang,
        trim=spec.trim,
        first=spec.first,
        estimated_pages=pages,
        font_spec=spec.font,
        decor=spec.decor,
        copyright=spec.copyright,
        translation_note=spec.translation_source_note,
        include_toc=spec.toc,
    )
    log(f"✓ Done: {out_path}")
    return out_path
