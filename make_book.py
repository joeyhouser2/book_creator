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

from book_creator import fetch, segment
from book_creator.config import load_specs
from book_creator.model import BookSpec, CopyrightSpec, CoverSpec, DecorSpec, FontSpec
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


def _print_outlines(args) -> int:
    for label, gid, path in [("ORIGINAL", args.src_id, args.src_path),
                             ("TRANSLATION", args.tgt_id, args.tgt_path)]:
        if not (gid or path):
            continue
        text = fetch.load_text(path=path, gid=gid)
        print(f"\n=== {label} outline ===")
        for d in segment.outline(text):
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
    p.add_argument("--aligner", choices=["auto", "embed", "mt", "gale-church"],
                   default="auto",
                   help="Alignment backend. 'embed' = LaBSE; 'mt' = translate "
                        "source then align in English (needs a registered "
                        "translator); 'auto' picks the best available.")
    p.add_argument("--first", choices=["src", "tgt"], default="src",
                   help="Which language prints first in each pair.")
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
    args = p.parse_args(argv)

    if args.outline:
        return _print_outlines(args)

    if args.config:
        specs = load_specs(args.config)
    elif args.src_id or args.src_path:
        specs = [BookSpec(
            title=args.title, author=args.author, src_lang=args.src_lang,
            src_gutenberg_id=args.src_id, tgt_gutenberg_id=args.tgt_id,
            src_path=args.src_path, tgt_path=args.tgt_path,
            mode=args.mode, aligner=args.aligner, first=args.first,
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
        )]
    else:
        p.error("Provide a config file, or --src-id/--src-path for a single book.")
        return 2

    failures = 0
    for spec in specs:
        print(f"\n=== {spec.title} ({spec.src_lang}→{spec.tgt_lang}) ===")
        try:
            build_book(spec, out_dir=args.out)
        except Exception as exc:  # noqa: BLE001 - surface per-book errors, keep going
            failures += 1
            print(f"✗ Failed: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
