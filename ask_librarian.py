#!/usr/bin/env python
"""Find and (optionally) build a book from a natural-language request, using
a locally-run LLM to search Project Gutenberg for a matching source text and
translation.

Requires Ollama running locally with a tool-calling-capable model:
    ollama pull llama3.1
    ollama serve

Examples
--------
Just find a pairing and print it (writes nothing, builds nothing):
    python ask_librarian.py "Dante's Inferno, Italian with an English translation"

Find it, review, then build with default styling:
    python ask_librarian.py "Heinrich Heine's Buch der Lieder, German with English" --build

Use a different local model / Ollama host:
    python ask_librarian.py "..." --model qwen2.5:32b --host http://localhost:11434
"""

from __future__ import annotations

import argparse
import sys

# Windows consoles default to cp1252; progress output uses Unicode symbols.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from book_creator.librarian import DEFAULT_HOST, DEFAULT_MODEL, LibrarianError, find_book
from book_creator.pipeline import build_book


def _print_result(result) -> None:
    spec = result.spec
    print(f"\n=== {spec.title} — {spec.author} ===")
    print(f"  source:      {spec.src_lang}  Gutenberg #{spec.src_gutenberg_id}"
          + (f"  range {spec.src_range[0]}-{spec.src_range[1]}" if spec.src_range else ""))
    print(f"  translation: {spec.tgt_lang}  Gutenberg #{spec.tgt_gutenberg_id}"
          + (f"  range {spec.tgt_range[0]}-{spec.tgt_range[1]}" if spec.tgt_range else ""))
    if result.translator:
        print(f"  translator:  {result.translator}")
    if spec.translation_source_note:
        print(f"  PD evidence: {spec.translation_source_note}")
    if result.confidence_notes:
        print(f"  caveats:     {result.confidence_notes}")
    print(
        "\n  ⚠  translation_pd_confirmed is FALSE. Verify the translation's public-"
        "domain status yourself (US: published before 1929) before publishing.\n"
    )
    print("  YAML for config/books.yaml:")
    print(f"    - title: \"{spec.title}\"")
    print(f"      author: \"{spec.author}\"")
    print(f"      src_lang: {spec.src_lang}")
    print(f"      tgt_lang: {spec.tgt_lang}")
    print(f"      src_gutenberg_id: {spec.src_gutenberg_id}")
    print(f"      tgt_gutenberg_id: {spec.tgt_gutenberg_id}")
    print(f"      mode: {spec.mode}")
    if spec.src_range:
        print(f"      src_range: {spec.src_range[0]}-{spec.src_range[1]}")
    if spec.tgt_range:
        print(f"      tgt_range: {spec.tgt_range[0]}-{spec.tgt_range[1]}")
    print("      translation_pd_confirmed: true  # only after you've verified this")
    if spec.translation_source_note:
        print(f"      translation_source_note: \"{spec.translation_source_note}\"")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("request", help="Natural-language description of the book you want.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model (default: %(default)s).")
    p.add_argument("--host", default=DEFAULT_HOST, help="Ollama host (default: %(default)s).")
    p.add_argument("--max-turns", type=int, default=12, help="Cap on agent tool-call turns.")
    p.add_argument("--build", action="store_true",
                   help="Build the PDF immediately with default styling after finding a pairing.")
    p.add_argument("--out", default="output", help="Output directory for --build.")
    p.add_argument("--confirm-pd", action="store_true",
                   help="Affirm the found translation is public domain (only pass this after "
                        "verifying it yourself — required to suppress the PD warning on build).")
    p.add_argument("--review", action="store_true",
                   help="With --build, also ask a local LLM to flag likely alignment/"
                        "formatting errors into <slug>-review.md. Reuses --model/--host "
                        "unless --review-model/--review-host are given.")
    p.add_argument("--review-model", help="Ollama model for --review (default: same as --model).")
    p.add_argument("--review-host", help="Ollama host for --review (default: same as --host).")
    p.add_argument("--review-sample", type=int,
                   help="Cap on beads reviewed (from the start), for a quick spot-check.")
    args = p.parse_args(argv)

    try:
        result = find_book(args.request, model=args.model, host=args.host,
                           max_turns=args.max_turns)
    except LibrarianError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    _print_result(result)

    if args.build:
        result.spec.translation_pd_confirmed = args.confirm_pd
        if args.review:
            result.spec.review = True
            result.spec.review_model = args.review_model or args.model
            result.spec.review_host = args.review_host or args.host
            result.spec.review_sample = args.review_sample
        try:
            build_book(result.spec, out_dir=args.out)
        except Exception as exc:  # noqa: BLE001 - surface build errors
            print(f"✗ Build failed: {exc}", file=sys.stderr)
            return 1
    else:
        print("  (pass --build to render this immediately with default styling, or "
              "paste the YAML above into config/books.yaml and run make_book.py to "
              "style it further.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
