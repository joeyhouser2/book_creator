"""Orchestrate the full build: fetch -> clean -> segment -> align -> render."""

from __future__ import annotations

import re
from pathlib import Path

from . import (aligners, audio, clean, corpus, cover, fetch, music, render_epub,
               render_pdf, restylers, reviewer, segment)
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


def apply_sides(chapters: list[Chapter], sides: str, log) -> list[Chapter]:
    """Drop one side of every bead for a monolingual edition.

    Runs *after* alignment rather than instead of it: on the Gutenberg path the
    bead structure is what carries chapter anchoring and sentence order, so the
    cheapest correct way to print one language is to align as usual and then
    stop printing the other side. Both renderers already skip an empty side
    (an unmatched division produces exactly this shape), so nothing downstream
    needs to know.

    Beads left with nothing at all are dropped, which is the case that matters
    for `sides="tgt"`: a source sentence the translator omitted has no English
    to show, and printing a blank for it would be worse than leaving it out.
    """
    if sides not in ("src", "tgt"):
        return chapters

    keep_src = sides == "src"
    dropped = 0
    emptied = 0
    for ch in chapters:
        beads = []
        for bead in ch.beads:
            if keep_src:
                bead.tgt = []
            else:
                bead.src = []
            if bead.src or bead.tgt:
                beads.append(bead)
            else:
                emptied += 1
        dropped += len(ch.beads) - len(beads)
        ch.beads = beads
        if keep_src:
            ch.tgt_segments = []
        else:
            ch.src_segments = []

    chapters = [ch for ch in chapters if ch.beads]
    side_name = "original" if keep_src else "translation"
    log(f"• Monolingual edition: printing the {side_name} only"
        + (f"; {emptied} bead(s) had nothing on that side and were dropped"
           if emptied else "") + ".")
    return chapters


def _chapters_from_corpus(spec: BookSpec, log) -> list[Chapter]:
    """Load a pre-aligned work from the latin repo's corpus.

    Nothing here fetches, segments, cleans, or aligns: that corpus already
    stores one source sentence per row with its English beside it, so each row
    becomes a Bead directly and there is no alignment drift to proofread for.
    Missing metadata (title, author, source language) is filled in from the
    document record, so a config entry can be as short as `corpus: 376`.
    """
    c = spec.corpus
    log(f"• Loading corpus document #{c.doc_id}…")
    # An original-only edition has no use for the English, so segments that
    # were never translated are perfectly printable — which is what makes the
    # corpus's ~13k untranslated works reachable at all.
    skip_untranslated = c.skip_untranslated and spec.sides != "src"
    load = corpus.load_chapters(
        c.doc_id, section_range=c.section_range, prefer_styled=c.prefer_styled,
        skip_untranslated=skip_untranslated, strip_markup=c.strip_markup,
        db_path=c.db_path)
    doc = load.doc

    if not spec.title:
        spec.title = doc.title
    if spec.author in ("", "Unknown"):
        spec.author = doc.author
    if not spec.src_lang:
        spec.src_lang = doc.language
    if not spec.translation_source_note:
        # An original-only edition prints no English, so the machine-translation
        # disclosure would be describing something that isn't in the book.
        spec.translation_source_note = corpus.source_note(
            doc, translated=spec.sides != "src")

    log(f"• {doc.title} — {doc.author} ({doc.language}, {doc.language_stage})")
    log(f"• {load.beads} bead(s) across {len(load.chapters)} section(s)"
        + (f"; {load.styled_used} used the stylized English" if load.styled_used else "")
        + (f"; {load.demarked} had editorial sigla stripped" if load.demarked else "")
        + (f"; {load.untranslated} untranslated segment(s) "
           f"{'dropped' if skip_untranslated else 'kept source-only'}"
           if load.untranslated else "") + ".")

    # The English side is this project's own machine translation, so no third
    # party holds copyright on it — but the *source* text's licence still
    # governs, and the corpus records plenty of non-free ones.
    risk = corpus.licence_risk(doc.license)
    if risk == "check":
        log(f"  ⚠  Source licence needs checking before you publish: {doc.license}")
    elif risk == "unknown":
        log(f"  ⚠  Source licence not classified: {doc.license or '(none recorded)'}")
    return load.chapters


def _chapters_from_perseus(spec: BookSpec, log) -> list[Chapter]:
    """Build from a Perseus work: both editions, anchored on their citation refs.

    The structural pairing is exact -- "Book 3" is "Book 3" by the work's own
    canonical numbering -- so alignment only ever runs *inside* a division,
    where sentence-level matching is what it is good at. That is a materially
    better starting point than the Gutenberg path, where the division match is
    itself a guess.
    """
    from . import perseus

    p = spec.perseus
    src_divs, tgt_divs, meta = perseus.fetch_pair(p.work_id, log=log)
    pairs = perseus.pair_divisions(src_divs, tgt_divs, log=log)

    if p.division_range:
        # The range is over the OUTERMOST references (books), which is what a
        # reader means by "Book 1". Pairs are sections, so slicing them
        # directly would silently keep one section instead of one book.
        first, last = p.division_range
        tops = list(dict.fromkeys(s.top for s, _ in pairs))
        keep = set(tops[max(1, first) - 1:min(len(tops), last)])
        pairs = [(s, t) for s, t in pairs if s.top in keep]
        log(f"• Scoped to division(s) {first}–{last} "
            f"({', '.join(sorted(keep)) or 'none'}): {len(pairs)} section(s).")

    if not spec.title:
        spec.title = meta["title"]
    if spec.author in ("", "Unknown"):
        spec.author = meta["author"]
    if not spec.src_lang:
        spec.src_lang = meta["language"]
    if not spec.translation_source_note:
        spec.translation_source_note = meta["translation_edition"]

    log(f"• {meta['title']} — {meta['author']} ({meta['language']})")
    log(f"• Translation: {meta['translation_edition'][:110]}")

    # Perseus translations are mostly Loeb-era and usually public domain, but
    # "usually" is not a licence: report the year and let the user affirm it.
    if meta["pd_status"] == "ok":
        log(f"• Translation published {meta['translation_year']} — before 1929, "
            "so public domain in the US.")
    elif meta["pd_status"] == "check":
        log(f"  ⚠  Translation published {meta['translation_year']}, which is "
            "1929 or later — verify its copyright status before publishing.")
    else:
        log("  ⚠  No publication year recorded for this translation — check its "
            "copyright status before publishing.")

    # Sections are the alignment unit but not the printing unit: group them
    # back under their outermost reference so the book still has chapters.
    grouped: dict[str, list] = {}
    for s, t in pairs:
        grouped.setdefault(s.top, []).append((s, t))

    aligners.reset_announcement()
    chapters: list[Chapter] = []
    for top, members in grouped.items():
        beads: list[Bead] = []
        src_segments: list[str] = []
        tgt_segments: list[str] = []
        for s, t in members:
            s_segs = segment.segment(s.text, spec.mode, spec.src_lang)
            t_segs = segment.segment(t.text, spec.mode, spec.tgt_lang)
            if spec.clean:
                s_segs = clean.clean_segments(s_segs)
                t_segs = clean.clean_segments(t_segs)
            if not s_segs and not t_segs:
                continue
            src_segments.extend(s_segs)
            tgt_segments.extend(t_segs)
            # One sentence each side is the common case at this granularity,
            # and needs no alignment at all.
            if len(s_segs) == 1 and len(t_segs) == 1:
                beads.append(Bead(src=s_segs, tgt=t_segs))
            else:
                beads.extend(aligners.align(
                    s_segs, t_segs, method=spec.aligner,
                    src_lang=spec.src_lang, log=lambda _m: None))
        if beads:
            title = members[0][0].title or members[0][1].title or f"Book {top}"
            chapters.append(Chapter(title=title, src_segments=src_segments,
                                    tgt_segments=tgt_segments, beads=beads))

    total = sum(len(c.beads) for c in chapters)
    log(f"• Aligned into {total} bead(s) across {len(chapters)} chapter(s).")
    return chapters


def _chapters_from_editions(spec: BookSpec, log) -> list[Chapter]:
    """Fetch, segment, and align two separate editions (the Gutenberg path)."""
    log(f"• Fetching source ({spec.src_lang})…")
    src_text = fetch.load_text(path=spec.src_path, gid=spec.src_gutenberg_id,
                               log=log)
    log(f"• Fetching translation ({spec.tgt_lang})…")
    tgt_text = fetch.load_text(path=spec.tgt_path, gid=spec.tgt_gutenberg_id,
                               log=log)

    # Structural anchoring: split both sides into divisions, optionally scoping
    # each to a selected range so the two editions cover the same content.
    src_chaps = _apply_range(
        segment.detect_chapters(src_text, mode=spec.mode, poem_titles=spec.poem_titles), spec.src_range)
    tgt_chaps = _apply_range(
        segment.detect_chapters(tgt_text, mode=spec.mode, poem_titles=spec.poem_titles), spec.tgt_range)
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

    return _align_paired(paired, spec, log)


def _align_paired(paired, spec: BookSpec, log) -> list[Chapter]:
    """Segment and align each already-paired division into beads.

    Shared by every source that arrives as matched divisions: the Gutenberg
    path (paired by heading count or by meaning) and the Perseus path
    (paired exactly on the CTS citation scheme). Only the *pairing* differs
    between them; what happens inside a division is the same work.
    """
    aligners.reset_announcement()
    verse_note_logged = False
    chapters: list[Chapter] = []
    for (s_title, s_body), (t_title, t_body) in paired:
        src_segs = segment.segment(s_body, spec.mode, spec.src_lang)
        tgt_segs = segment.segment(t_body, spec.mode, spec.tgt_lang)
        if spec.clean:
            src_segs = clean.clean_segments(src_segs)
            tgt_segs = clean.clean_segments(tgt_segs)
        if spec.mode == "verse":
            # Poetic translations routinely reorder clauses across lines for
            # rhyme/meter, so line-by-line embedding/length alignment is
            # unreliable (a German line's "translation" can land several
            # lines away in English) — matches published dual-language poetry
            # practice instead: the whole original poem block, then the whole
            # translation block, each with its own line breaks intact, rather
            # than forcing a false line-by-line correspondence.
            if not verse_note_logged:
                log("• Verse mode: pairing whole poem blocks, not aligning "
                    "individual lines (see pipeline._fuzzy_match_divisions docstring).")
                verse_note_logged = True
            src_block = [Bead(src=[s], tgt=[]) for s in src_segs]
            tgt_block = [Bead(src=[], tgt=[t]) for t in tgt_segs]
            beads = (tgt_block + src_block) if spec.first == "tgt" else (src_block + tgt_block)
        else:
            beads = aligners.align(src_segs, tgt_segs, method=spec.aligner,
                                   src_lang=spec.src_lang, log=log)
        chapters.append(Chapter(title=t_title or s_title, src_segments=src_segs,
                                tgt_segments=tgt_segs, beads=beads))

    total_beads = sum(len(c.beads) for c in chapters)
    log(f"• Aligned into {total_beads} bead(s) across {len(chapters)} chapter(s).")
    return chapters


def build_book(spec: BookSpec, *, out_dir: str = "output", verbose: bool = True,
               on_log=None, artifacts: dict | None = None,
               on_progress=None, should_stop=None) -> str:
    """Build one book. Returns the interior PDF path.

    `artifacts`, if given, is filled in with every file produced (pdf, cover,
    epub, review, audio) so a caller like the web UI can offer them all without
    re-deriving the names.
    """
    def log(msg: str) -> None:
        if verbose:
            print(msg)
        if on_log is not None:
            on_log(msg)

    out = artifacts if artifacts is not None else {}

    if spec.corpus.doc_id:
        chapters = _chapters_from_corpus(spec, log)
    elif spec.perseus.work_id:
        chapters = _chapters_from_perseus(spec, log)
    else:
        if not spec.translation_pd_confirmed:
            log(
                "  ⚠  translation_pd_confirmed is False. A translator holds copyright "
                "on their translation separately from the public-domain original. "
                "Verify the translation is public domain (US: published before 1929) "
                "before publishing."
            )
        chapters = _chapters_from_editions(spec, log)

    chapters = apply_sides(chapters, spec.sides, log)
    if not chapters:
        raise ValueError(
            f"Nothing left to print: sides='{spec.sides}' removed every bead.")

    slug = spec.slug or _slugify(spec.title)
    # A monolingual edition is a different book from the parallel text, so it
    # gets its own filenames. Without this, narrating the English of a book you
    # already built would quietly overwrite the dual-language one beside it.
    if not spec.slug and spec.sides != "both":
        lang = spec.tgt_lang if spec.sides == "tgt" else spec.src_lang
        slug = f"{slug}-{lang or spec.sides}"
        log(f"• Monolingual output, so files are named {slug}.* — the "
            "dual-language build is left alone.")

    if spec.music.enabled and not spec.audio_only:
        log(f"• Matching poems against musical-literature catalog ({spec.music.catalog})…")
        music_dir = Path(out_dir) / f"{slug}-music"
        matched = 0
        for ch in chapters:
            first_line = ch.src_segments[0] if ch.src_segments else ""
            second_line = ch.src_segments[1] if len(ch.src_segments) > 1 else ""
            result = music.render_poem_music(
                first_line, second_line, catalog=spec.music.catalog,
                cache_dir=Path("cache/music"), work_dir=music_dir, log=log,
            )
            if result:
                ch.music_images, ch.music_caption = result
                matched += 1
        log(f"• Music: {matched} poem(s) matched to a setting in '{spec.music.catalog}'.")

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
            out["review"] = review_path
        except reviewer.ReviewerError as exc:
            log(f"  ⚠  Review skipped: {exc}")

    out_path = ""
    if spec.audio_only:
        # Rendering nothing is the point: an existing PDF for this book stays
        # exactly as it was.
        log("• Audio only — skipping the PDF, cover and EPUB.")
    else:
        out_path = _render_print(chapters, spec, slug, out_dir, out, log)

    if spec.audio.enabled or spec.audio_only:
        spec.audio.first = spec.first
        try:
            out["audio"] = audio.build_audiobook(
                chapters, spec=spec.audio, out_dir=out_dir, slug=slug,
                title=spec.title, author=spec.author, src_lang=spec.src_lang,
                tgt_lang=spec.tgt_lang, log=log, on_progress=on_progress,
                should_stop=should_stop,
            )
            out_path = out_path or (out["audio"].get("book") or "")
        except audio.AudioError as exc:
            # Never lose a finished book to a TTS problem — the PDF (when there
            # is one) is already written, so report and carry on.
            log(f"  ⚠  Audiobook skipped: {exc}")
            if spec.audio_only:
                raise

    return out_path


def _render_print(chapters, spec: BookSpec, slug: str, out_dir: str, out: dict,
                  log) -> str:
    """Render the print edition: interior PDF, then cover and EPUB if asked."""
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
    out["pdf"] = out_path
    out["pages"] = actual_pages

    if spec.cover.enabled:
        cover_path = str(Path(out_dir) / f"{slug}-cover.pdf")
        _, dims = cover.render_cover(
            cover_path,
            style=spec.cover.style,
            title=spec.title, author=spec.author,
            src_lang=spec.src_lang, tgt_lang=spec.tgt_lang,
            trim=spec.trim, pages=actual_pages, paper=spec.cover.paper,
            font_spec=spec.font, background=spec.cover.background,
            accent=spec.cover.accent, blurb=spec.cover.blurb,
            publisher=spec.copyright.publisher,
        )
        w, h, spine = dims
        log(f"✓ Cover: {cover_path} ({w:.3f} × {h:.3f} in, spine {spine:.3f} in)")
        out["cover"] = cover_path

    if spec.epub:
        epub_path = str(Path(out_dir) / f"{slug}.epub")
        ebook_cover_path = None
        try:
            ebook_cover_path = str(Path(out_dir) / f"{slug}-epub-cover.png")
            cover.render_ebook_cover(
                ebook_cover_path, style=spec.cover.style,
                title=spec.title, author=spec.author,
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
        out["epub"] = epub_path

    return out_path
