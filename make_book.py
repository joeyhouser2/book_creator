#!/usr/bin/env python
"""CLI entry point for book_creator.

Examples
--------
Build every book defined in a config file:
    python make_book.py config/books.yaml

Build a single book straight from two Gutenberg ids:
    python make_book.py --src-id 228 --tgt-id 22456 --src-lang la \\
        --title "Aeneid" --author "Virgil" --mode verse
"""

from __future__ import annotations

import argparse
import sys

# Windows consoles default to cp1252; our progress output uses Unicode symbols.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from book_creator import audio, corpus, fetch, segment
from book_creator.config import load_specs
from book_creator.model import (AudioSpec, BookSpec, CopyrightSpec, CorpusSpec,
                                CoverSpec, DecorSpec, FontSpec, MusicSpec)
from book_creator.pipeline import build_book


def _parse_range(text: str | None) -> tuple[int, int] | None:
    """Parse '2-5' or '2:5' or single '3' into a (first, last) tuple."""
    if not text:
        return None
    parts = text.replace(":", "-").split("-")
    nums = [int(p) for p in parts if p.strip()]
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (nums[0], nums[1])


def _print_corpus(args) -> int:
    """Browse the latin repo's corpus from the command line."""
    if args.corpus_id:
        doc = corpus.document(args.corpus_id, db_path=args.corpus_db)
        print(f"\n=== #{doc.id} {doc.title} ===")
        print(f"  author    {doc.author}")
        print(f"  language  {doc.language} ({doc.language_stage})")
        print(f"  segments  {doc.segments:,} ({doc.translated:,} translated, "
              f"{doc.styled:,} stylized)")
        print(f"  source    {doc.source}")
        print(f"  licence   {doc.license}  [{corpus.licence_risk(doc.license)}]")
        print("\n  sections:")
        for sec in corpus.outline(args.corpus_id, db_path=args.corpus_db):
            print(f"   {sec['index']:>3}. {sec['title'][:50]:<52} "
                  f"{sec['segments']:>6,} seg  {sec['translated']:>6,} translated")
        print("\n  Scope with --corpus-range (e.g. 2-5), then build with --corpus-id.")
        return 0

    res = corpus.search_documents(args.corpus_search or "", language=args.corpus_lang,
                                  stage=args.corpus_stage, limit=args.corpus_limit,
                                  db_path=args.corpus_db)
    print(f"\n=== corpus: {res['count']:,} document(s) match ===")
    for d in res["results"]:
        print(f"  #{d['id']:<6} {d['title'][:52]:<54} {d['language']:<4} "
              f"{d['translated']:>7,}/{d['segments']:<7,} [{d['license_risk']}]")
    if res.get("hint"):
        print(f"\n  {res['hint']}")
    print("\n  Inspect one with: --corpus --corpus-id <id>")
    return 0


def _print_outlines(args) -> int:
    for label, gid, path in [("ORIGINAL", args.src_id, args.src_path),
                             ("TRANSLATION", args.tgt_id, args.tgt_path)]:
        if not (gid or path):
            continue
        text = fetch.load_text(path=path, gid=gid)
        print(f"\n=== {label} outline ===")
        for d in segment.outline(text, mode=args.mode, poem_titles=args.poem_titles):
            print(f"  {d['index']:>3}. [{d['chars']:>8,} ch] {d['title'][:60]}")
    print("\nUse --src-range / --tgt-range (e.g. 2-5) to scope both sides to "
          "matching content.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build dual-language KDP PDFs.")
    p.add_argument("config", nargs="?", help="Path to a YAML config file.")
    p.add_argument("--src-id", type=int, help="Gutenberg id of the original text.")
    p.add_argument("--tgt-id", type=int, help="Gutenberg id of the translation.")
    p.add_argument("--src-path", help="Local file for the original (overrides --src-id).")
    p.add_argument("--tgt-path", help="Local file for the translation.")
    p.add_argument("--src-lang", default="la", help="Original language code (la, fr, grc, de).")
    p.add_argument("--title", default="Untitled")
    p.add_argument("--author", default="Unknown")
    p.add_argument("--mode", choices=["prose", "verse"], default="prose")
    p.add_argument("--poem-titles", action="store_true",
                   help="Verse mode: also split on an isolated untitled poem's "
                        "title line, not just numbered 'I'/'II' cycle markers. "
                        "Helps collections that name every poem instead of "
                        "numbering them continuously (e.g. Les Fleurs du Mal); "
                        "leave off for ones already numbered straight through "
                        "(e.g. Buch der Lieder).")
    p.add_argument("--aligner", choices=["auto", "embed", "mt", "gale-church"],
                   default="auto",
                   help="Alignment backend. 'embed' = LaBSE; 'mt' = translate "
                        "source then align in English (needs a registered "
                        "translator); 'auto' picks the best available.")
    p.add_argument("--first", choices=["src", "tgt"], default="src",
                   help="Which language prints first in each pair.")
    p.add_argument("--sides", choices=["both", "src", "tgt"], default="both",
                   help="Which languages to include. 'both' (default) is the "
                        "parallel text; 'src' prints a monolingual edition of "
                        "the original; 'tgt' prints the translation alone. A "
                        "monolingual audiobook follows the same setting.")
    p.add_argument("--src-range", help="Division range to include from the original, "
                   "e.g. 2-5 (1-based, inclusive). See --outline.")
    p.add_argument("--tgt-range", help="Division range to include from the translation.")
    p.add_argument("--outline", action="store_true",
                   help="Print each text's division outline and exit (use to pick ranges).")
    p.add_argument("--out", default="output", help="Output directory.")
    p.add_argument("--confirm-pd", action="store_true",
                   help="Affirm the translation is public domain (suppresses the warning).")
    p.add_argument("--font", default="Cardo",
                   help="Font family name (Cardo, GentiumPlus, NotoSerif) or stem.")
    p.add_argument("--margin", choices=["none", "rule", "corners", "frame"],
                   default="none", help="Per-page margin decoration.")
    p.add_argument("--chapter-ornament",
                   choices=["none", "fleuron", "rule", "medieval", "victorian",
                            "classical", "baroque", "nouveau", "rococo", "artdeco",
                            "random"],
                   default="fleuron",
                   help="Ornament under each chapter title. 'random' picks a "
                        "different style per chapter (deterministic by chapter "
                        "index, so PDF/EPUB and repeat builds agree).")
    p.add_argument("--decor-color", default="#8a7a5c", help="Ornament ink color (hex).")
    p.add_argument("--corner-image", help="PNG/JPG placed (mirrored) at text-block corners.")
    p.add_argument("--opener-font", default="",
                   help="Decorative display font for each chapter's opening line "
                        "(both languages), e.g. UncialAntiqua. Omit to disable.")
    # Copyright page.
    p.add_argument("--publisher", default="", help="Imprint name for the copyright page.")
    p.add_argument("--copyright-holder", default="",
                   help="Who holds the compilation copyright.")
    p.add_argument("--edition-year", type=int, help="Edition year for the copyright page.")
    p.add_argument("--isbn", default="", help="ISBN for the copyright page.")
    p.add_argument("--translator", default="", help="Translator name (public-domain credit).")
    p.add_argument("--cover", action="store_true",
                   help="Also generate a wraparound cover PDF (<slug>-cover.pdf).")
    p.add_argument("--paper", choices=["white", "cream", "color"], default="white",
                   help="Paper stock (sets spine width).")
    p.add_argument("--blurb", default="", help="Back-cover description text.")
    p.add_argument("--no-copyright", action="store_true", help="Omit the copyright page.")
    p.add_argument("--no-toc", action="store_true",
                   help="Omit the table of contents.")
    p.add_argument("--no-clean", action="store_true",
                   help="Don't strip inline section markers (I.--, XLIX.--) etc.")
    p.add_argument("--no-restyle", action="store_true",
                   help="Don't run a registered restyler (e.g. victorianizer) over "
                        "the printed translation, even if one is registered.")
    p.add_argument("--epub", action="store_true",
                   help="Also generate a reflowable EPUB (<slug>.epub), needs "
                        "requirements-epub.txt.")
    p.add_argument("--review", action="store_true",
                   help="After alignment, ask a local LLM (Ollama) to flag likely "
                        "misalignment/formatting errors into <slug>-review.md. "
                        "Advisory only; needs `ollama serve` running.")
    p.add_argument("--review-model", default="llama3.1",
                   help="Ollama model for --review (default: %(default)s).")
    p.add_argument("--review-host", default="http://localhost:11434",
                   help="Ollama host for --review (default: %(default)s).")
    p.add_argument("--review-sample", type=int,
                   help="Cap on beads reviewed (from the start), for a quick spot-check.")
    p.add_argument("--music", action="store_true",
                   help="Musical literature (verse mode): typeset the piano grand "
                        "staff (treble + bass) under poems matched to a known "
                        "art-song setting. Needs LilyPond on PATH; see book_creator/music.py.")
    p.add_argument("--music-catalog", default="dichterliebe",
                   help="Which registered catalog to match poems against for --music "
                        "(default: %(default)s).")
    # Latin corpus source (the sibling `latin` repo's pre-aligned corpus.db).
    g = p.add_argument_group("latin corpus")
    g.add_argument("--corpus", action="store_true",
                   help="Browse the latin corpus and exit. Combine with "
                        "--corpus-search / --corpus-id.")
    g.add_argument("--corpus-id", type=int,
                   help="Build from this corpus document id. Skips fetch/segment/"
                        "align entirely: the corpus is already sentence-aligned.")
    g.add_argument("--corpus-db",
                   help="Path to the latin repo checkout or its data/corpus.db. "
                        "Defaults to $LATIN_REPO, then ../latin.")
    g.add_argument("--corpus-range",
                   help="Section range within the corpus document, e.g. 2-5.")
    g.add_argument("--corpus-search", default="",
                   help="Title/author substring to search for.")
    g.add_argument("--corpus-lang", choices=["la", "grc"], help="Filter by language.")
    g.add_argument("--corpus-stage",
                   help="Filter by language stage (classical, late_antique, medieval…).")
    g.add_argument("--corpus-limit", type=int, default=40, help="Max search results.")
    g.add_argument("--no-styled", action="store_true",
                   help="Use the plain machine translation even where a stylized "
                        "(Victorian) English rendering exists.")
    g.add_argument("--keep-sigla", action="store_true",
                   help="Keep the editorial apparatus critical editions carry "
                        "(<A>ltus, Imp(erator), [Aug]ustus) instead of printing "
                        "just the letters. Off by default: a reader wants the "
                        "text, and a narrator cannot say a bracket.")
    # Audiobook.
    a = p.add_argument_group("audiobook")
    a.add_argument("--audio", action="store_true",
                   help="Also narrate an interleaved bilingual audiobook on the GPU "
                        "(needs requirements-audio.txt).")
    a.add_argument("--audio-engines", action="store_true",
                   help="List registered TTS engines and CUDA devices, then exit.")
    a.add_argument("--audio-engine", default="chatterbox",
                   help="TTS engine id (default: %(default)s).")
    a.add_argument("--audio-device",
                   help="Torch device for synthesis. Defaults to the CUDA device "
                        "with the most memory — not necessarily cuda:0, which CUDA "
                        "orders fastest-first rather than largest-first.")
    a.add_argument("--audio-voice",
                   help="Reference voice for both languages: a WAV path for cloning "
                        "engines, or a voice name for fixed-voice ones.")
    a.add_argument("--audio-src-voice", help="Override the voice for the original.")
    a.add_argument("--audio-tgt-voice", help="Override the voice for the translation.")
    a.add_argument("--audio-format", choices=["m4b", "mp3"], default="m4b",
                   help="Assembled audiobook container (default: %(default)s).")
    a.add_argument("--audio-max-beads", type=int,
                   help="Narrate only the first N beads — a quick voice test before "
                        "committing hours of GPU time.")
    a.add_argument("--no-announce-chapters", action="store_true",
                   help="Don't read each chapter title aloud.")
    args = p.parse_args(argv)

    if args.audio_engines:
        print("\n=== TTS engines ===")
        for e in audio.catalog():
            mark = "✓" if e["installed"] else "·"
            print(f"  {mark} {e['id']:<12} {e['label']:<38} {e['licence']}")
            if not e["installed"]:
                print(f"      not installed — {e['reason']}")
        info = audio.devices()
        print("\n=== devices ===")
        for d in info["devices"]:
            mark = "*" if d["id"] == info["recommended"] else " "
            print(f" {mark}{d['id']:<8} {d['label']}")
        if info["note"]:
            print(f"\n  ⚠  {info['note']}")
        print(f"\n  Default without --audio-device: {info['recommended']} (most memory).")
        return 0

    if args.corpus:
        return _print_corpus(args)

    if args.outline:
        return _print_outlines(args)

    audio_spec = AudioSpec(
        enabled=args.audio, engine=args.audio_engine,
        device=args.audio_device or (audio.best_device() if args.audio else "cpu"),
        src_voice=args.audio_src_voice or args.audio_voice,
        tgt_voice=args.audio_tgt_voice or args.audio_voice,
        announce_chapters=not args.no_announce_chapters,
        format=args.audio_format, max_beads=args.audio_max_beads,
    )

    if args.config:
        specs = load_specs(args.config)
        if args.audio:              # the CLI flag turns audio on for the whole batch
            for spec in specs:
                spec.audio = audio_spec
    elif args.corpus_id or args.src_id or args.src_path:
        specs = [BookSpec(
            # A corpus document supplies its own title/language, so leave those
            # blank unless the user overrode them (see _chapters_from_corpus).
            title="" if (args.corpus_id and args.title == "Untitled") else args.title,
            author=args.author,
            src_lang="" if args.corpus_id else args.src_lang,
            corpus=CorpusSpec(
                doc_id=args.corpus_id, db_path=args.corpus_db,
                section_range=_parse_range(args.corpus_range),
                prefer_styled=not args.no_styled,
                strip_markup=not args.keep_sigla,
            ),
            src_gutenberg_id=args.src_id, tgt_gutenberg_id=args.tgt_id,
            src_path=args.src_path, tgt_path=args.tgt_path,
            mode=args.mode, poem_titles=args.poem_titles, aligner=args.aligner,
            first=args.first, sides=args.sides,
            toc=not args.no_toc, clean=not args.no_clean, restyle=not args.no_restyle,
            src_range=_parse_range(args.src_range),
            tgt_range=_parse_range(args.tgt_range),
            translation_pd_confirmed=args.confirm_pd,
            font=FontSpec(family=args.font),
            decor=DecorSpec(
                margin=args.margin,
                chapter=args.chapter_ornament,
                color=args.decor_color,
                corner_image=args.corner_image,
                opener_font=args.opener_font or None,
            ),
            copyright=CopyrightSpec(
                enabled=not args.no_copyright,
                publisher=args.publisher,
                holder=args.copyright_holder,
                year=args.edition_year,
                isbn=args.isbn,
                translator=args.translator,
            ),
            cover=CoverSpec(enabled=args.cover, paper=args.paper, blurb=args.blurb),
            epub=args.epub,
            review=args.review,
            review_model=args.review_model,
            review_host=args.review_host,
            review_sample=args.review_sample,
            music=MusicSpec(enabled=args.music, catalog=args.music_catalog),
            audio=audio_spec,
        )]
    else:
        p.error("Provide a config file, --src-id/--src-path, or --corpus-id.")
        return 2

    failures = 0
    for spec in specs:
        label = spec.title or f"corpus #{spec.corpus.doc_id}"
        print(f"\n=== {label} ({spec.src_lang or '?'}→{spec.tgt_lang}) ===")
        try:
            build_book(spec, out_dir=args.out)
        except Exception as exc:  # noqa: BLE001 - surface per-book errors, keep going
            failures += 1
            print(f"✗ Failed: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
