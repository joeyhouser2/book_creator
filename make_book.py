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
from book_creator.model import BookSpec, CopyrightSpec, DecorSpec, FontSpec
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
    p.add_argument("--aligner", choices=["auto", "embed", "gale-church"],
                   default="auto",
                   help="Alignment backend. 'embed' = LaBSE (meaning-based); "
                        "'auto' uses it when installed, else Gale-Church.")
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
    p.add_argument("--chapter-ornament", choices=["none", "fleuron", "rule"],
                   default="fleuron", help="Ornament under each chapter title.")
    p.add_argument("--decor-color", default="#8a7a5c", help="Ornament ink color (hex).")
    p.add_argument("--corner-image", help="PNG/JPG placed (mirrored) at text-block corners.")
    # Copyright page.
    p.add_argument("--publisher", default="", help="Imprint name for the copyright page.")
    p.add_argument("--copyright-holder", default="",
                   help="Who holds the compilation copyright.")
    p.add_argument("--edition-year", type=int, help="Edition year for the copyright page.")
    p.add_argument("--isbn", default="", help="ISBN for the copyright page.")
    p.add_argument("--translator", default="", help="Translator name (public-domain credit).")
    p.add_argument("--no-copyright", action="store_true", help="Omit the copyright page.")
    p.add_argument("--no-toc", action="store_true",
                   help="Omit the table of contents.")
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
            mode=args.mode, aligner=args.aligner, first=args.first, toc=not args.no_toc,
            src_range=_parse_range(args.src_range),
            tgt_range=_parse_range(args.tgt_range),
            translation_pd_confirmed=args.confirm_pd,
            font=FontSpec(family=args.font),
            decor=DecorSpec(
                margin=args.margin,
                chapter=args.chapter_ornament,
                color=args.decor_color,
                corner_image=args.corner_image,
            ),
            copyright=CopyrightSpec(
                enabled=not args.no_copyright,
                publisher=args.publisher,
                holder=args.copyright_holder,
                year=args.edition_year,
                isbn=args.isbn,
                translator=args.translator,
            ),
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
