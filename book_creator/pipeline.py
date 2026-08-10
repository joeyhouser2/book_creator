"""Orchestrate the full build: fetch -> clean -> segment -> align -> render."""

from __future__ import annotations

import re
from pathlib import Path

from . import aligners, clean, cover, fetch, render_epub, render_pdf, restylers, reviewer, segment
from .model import Bead, BookSpec, Chapter


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


def _fuzzy_match_divisions(
    src_chaps: list[tuple[str, str]], tgt_chaps: list[tuple[str, str]], log,
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Match divisions by meaning when the two editions have different division
    counts — e.g. a *selection* translation that only covers some of the
    original's poems/chapters, in the original order. Concatenating everything
    into one giant block (the old fallback) works but risks drift; this instead
    reuses the embedding aligner's DP at DIVISION granularity (each division's
    full text stands in for one "sentence"), so unmatched divisions on the
    larger side become clean insertions — printed with only the side that has
    them — instead of dragging on the alignment of everything downstream.
    Requires sentence-transformers; caller should catch ImportError and fall
    back to single-block concatenation when it's not installed.
    """
    from .align_embed import embed_align

    src_texts = [body for _, body in src_chaps]
    tgt_texts = [body for _, body in tgt_chaps]
    # Unlike sentence-level alignment, divisions (chapters/poems) are whole
    # self-contained units — a translator splitting one sentence into two is
    # normal, but two DIFFERENT poems being spliced together is not. Restrict
    # to real 1-1 matches or clean insertions; no (2,1)/(1,2) merge steps, or
    # the DP will "explain away" a division with no counterpart by fusing it
    # onto its neighbor instead of honestly leaving it unmatched.
    div_beads = embed_align(src_texts, tgt_texts, steps=[(1, 1), (1, 0), (0, 1)])

    paired = []
    si = ti = 0
    matched = 0
    for bead in div_beads:
        ns, nt = len(bead.src), len(bead.tgt)
        s_slice = src_chaps[si:si + ns]
        t_slice = tgt_chaps[ti:ti + nt]
        si += ns
        ti += nt
        if ns and nt:
            matched += 1
        s_title = s_slice[0][0] if s_slice else ""
        t_title = t_slice[0][0] if t_slice else ""
        s_body = "\n\n".join(b for _, b in s_slice)
        t_body = "\n\n".join(b for _, b in t_slice)
        paired.append(((s_title, s_body), (t_title, t_body)))

    unmatched = len(paired) - matched
    log(f"• Division counts differ (source: {len(src_chaps)}, translation: "
        f"{len(tgt_chaps)}) — matched {matched} division(s) by meaning" +
        (f"; {unmatched} have no counterpart and print with only the "
         "available side." if unmatched else "."))
    return paired


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
    elif len(src_chaps) > 1 and len(tgt_chaps) > 1:
        # Division counts differ (e.g. a partial "selected poems" translation)
        # but both sides still have real structure to match against — prefer
        # meaning-based division matching over dumping everything into one
        # block, when the embedding aligner is available.
        try:
            from .align_embed import ensure_available
            ensure_available()
            paired = _fuzzy_match_divisions(src_chaps, tgt_chaps, log)
        except ImportError:
            src_body = "\n\n".join(b for _, b in src_chaps)
            tgt_body = "\n\n".join(b for _, b in tgt_chaps)
            paired = [(("", src_body), ("", tgt_body))]
            log("• Division counts differ; embedding aligner unavailable, "
                "aligning selected text as a single block.")
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
        if spec.clean:
            src_segs = clean.clean_segments(src_segs)
            tgt_segs = clean.clean_segments(tgt_segs)
        beads = aligners.align(src_segs, tgt_segs, method=spec.aligner,
                               src_lang=spec.src_lang, log=log)
        chapters.append(Chapter(title=t_title or s_title, src_segments=src_segs,
                                tgt_segments=tgt_segs, beads=beads))

    total_beads = sum(len(c.beads) for c in chapters)
    log(f"• Aligned into {total_beads} bead(s) across {len(chapters)} chapter(s).")

    slug = spec.slug or _slugify(spec.title)

    if spec.restyle and restylers.available(spec.tgt_lang):
        log(f"• Restyling translation ({spec.tgt_lang}) with registered restyler…")
        restyler = restylers.get(spec.tgt_lang)
        for ch in chapters:
            # Flatten every segment across this chapter's beads so the restyler
            # sees full context/order, then scatter results back in place —
            # bead boundaries (and therefore alignment) are untouched.
            spans: list[tuple[int, int]] = []
            flat: list[str] = []
            for bead in ch.beads:
                start = len(flat)
                flat.extend(bead.tgt)
                spans.append((start, len(flat)))
            if not flat:
                continue
            restyled = restyler(flat)
            if len(restyled) != len(flat):
                raise ValueError(
                    f"restyler returned {len(restyled)} items for {len(flat)} inputs"
                )
            for bead, (start, end) in zip(ch.beads, spans):
                bead.tgt = restyled[start:end]

    if spec.review:
        log(f"• Reviewing segments with local LLM ({spec.review_model})…")
        try:
            findings = reviewer.review_chapters(
                chapters, src_lang=spec.src_lang, tgt_lang=spec.tgt_lang,
                model=spec.review_model, host=spec.review_host,
                max_beads=spec.review_sample, log=log,
            )
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            review_path = str(Path(out_dir) / f"{slug}-review.md")
            Path(review_path).write_text(reviewer.format_report(findings), encoding="utf-8")
            high = sum(1 for f in findings if f.severity == "high")
            log(f"• Review flagged {len(findings)} bead(s) ({high} high-severity) → {review_path}")
        except reviewer.ReviewerError as exc:
            log(f"  ⚠  Review skipped: {exc}")

    pages = _estimate_pages(chapters)
    out_path = str(Path(out_dir) / f"{slug}.pdf")

    log(f"• Rendering PDF (≈{pages} pages) → {out_path}")
    _, actual_pages = render_pdf.render(
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
    log(f"✓ Done: {out_path} ({actual_pages} pages)")

    if spec.cover.enabled:
        cover_path = str(Path(out_dir) / f"{slug}-cover.pdf")
        _, dims = cover.render_cover(
            cover_path,
            title=spec.title, author=spec.author,
            src_lang=spec.src_lang, tgt_lang=spec.tgt_lang,
            trim=spec.trim, pages=actual_pages, paper=spec.cover.paper,
            font_spec=spec.font, background=spec.cover.background,
            accent=spec.cover.accent, blurb=spec.cover.blurb,
            publisher=spec.copyright.publisher,
        )
        w, h, spine = dims
        log(f"✓ Cover: {cover_path} ({w:.3f} × {h:.3f} in, spine {spine:.3f} in)")

    if spec.epub:
        epub_path = str(Path(out_dir) / f"{slug}.epub")
        ebook_cover_path = None
        try:
            ebook_cover_path = str(Path(out_dir) / f"{slug}-epub-cover.png")
            cover.render_ebook_cover(
                ebook_cover_path, title=spec.title, author=spec.author,
                src_lang=spec.src_lang, tgt_lang=spec.tgt_lang, trim=spec.trim,
                font_spec=spec.font, accent=spec.cover.accent,
                background=spec.cover.background,
            )
        except RuntimeError as exc:
            log(f"  ⚠  Skipping EPUB cover image: {exc}")
            ebook_cover_path = None
        render_epub.render(
            chapters,
            out_path=epub_path,
            title=spec.title,
            author=spec.author,
            src_lang=spec.src_lang,
            tgt_lang=spec.tgt_lang,
            first=spec.first,
            font_spec=spec.font,
            decor=spec.decor,
            copyright=spec.copyright,
            translation_note=spec.translation_source_note,
            cover_image_path=ebook_cover_path,
        )
        log(f"✓ EPUB: {epub_path}")

    return out_path
