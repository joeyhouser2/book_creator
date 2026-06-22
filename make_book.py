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

from book_creator.config import load_specs
from book_creator.model import BookSpec, DecorSpec, FontSpec
from book_creator.pipeline import build_book


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
    args = p.parse_args(argv)

    if args.config:
        specs = load_specs(args.config)
    elif args.src_id or args.src_path:
        specs = [BookSpec(
            title=args.title, author=args.author, src_lang=args.src_lang,
            src_gutenberg_id=args.src_id, tgt_gutenberg_id=args.tgt_id,
            src_path=args.src_path, tgt_path=args.tgt_path,
            mode=args.mode, aligner=args.aligner, first=args.first,
            translation_pd_confirmed=args.confirm_pd,
            font=FontSpec(family=args.font),
            decor=DecorSpec(
                margin=args.margin,
                chapter=args.chapter_ornament,
                color=args.decor_color,
                corner_image=args.corner_image,
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
