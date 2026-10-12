#!/usr/bin/env python
"""Proofread a configured book's aligned pairs on the GPU, without rendering it.

    python proofread_book.py config/messias.yaml
    python proofread_book.py config/books.yaml --title "Der Messias" --sample 400

Builds the chapters exactly as make_book.py would, scores every pair
(book_creator/proofread_pairs.py) and writes output/<slug>-proofread.md.
Nothing is rendered and no existing PDF is touched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from book_creator import proofread_pairs
from book_creator.config import load_specs
from book_creator.pipeline import _slugify, chapters_for_spec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", nargs="?", default="")
    ap.add_argument("--title", help="Pick one book from a multi-book config.")
    ap.add_argument("--model", default=proofread_pairs.TOWER_MODEL)
    ap.add_argument("--sample", type=int, help="Score only the first N beads.")
    ap.add_argument("--directions", choices=["fwd", "both"],
                    help="Default: both when the source is a Tower language.")
    ap.add_argument("--suggest", type=int, default=40,
                    help="Beads to give the model's own reading of (default 40).")
    ap.add_argument("--quant", choices=["auto", "none", "4bit", "8bit"], default="auto",
                    help="Weight precision. auto = 4-bit when the card is short of room.")
    ap.add_argument("--device", default="auto",
                    help="cuda:N to force a card (CUDA numbers fastest first). "
                         "Default: the one with the most memory.")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--metrics", help="Also write the raw scores to this JSON file.")
    ap.add_argument("--from-metrics", help="Re-run the analysis on a saved metrics "
                    "file: no GPU, no alignment.")
    args = ap.parse_args()

    if args.from_metrics:
        saved = json.loads(Path(args.from_metrics).read_text(encoding="utf-8"))
        findings = proofread_pairs.analyse(saved["items"], saved["metrics"])
        path = Path(args.out_dir) / (Path(args.from_metrics).stem + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proofread_pairs.format_report(
            findings, scanned=len(saved["items"]), model=saved.get("model", "")),
            encoding="utf-8")
        high = sum(1 for f in findings if f.severity == "high")
        print(f"{len(findings)} of {len(saved['items'])} pairs flagged ({high} high) → {path}")
        return 0

    specs = load_specs(args.config)
    if args.title:
        specs = [s for s in specs if s.title == args.title]
    if len(specs) != 1:
        print(f"{len(specs)} books match; pick one with --title:")
        for s in specs:
            print("  ", s.title)
        return 2
    spec = specs[0]

    chapters = chapters_for_spec(spec)
    findings, scanned = proofread_pairs.check_chapters(
        chapters, src_lang=spec.src_lang, tgt_lang=spec.tgt_lang, model=args.model,
        max_beads=args.sample, directions=args.directions, suggest=args.suggest,
        quant=args.quant, device=args.device, batch_size=args.batch_size,
        metrics_out=args.metrics)
    slug = spec.slug or _slugify(spec.title)
    path = Path(args.out_dir) / f"{slug}-proofread.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proofread_pairs.format_report(
        findings, scanned=scanned, model=args.model), encoding="utf-8")
    high = sum(1 for f in findings if f.severity == "high")
    print(f"{len(findings)} of {scanned} pairs flagged ({high} high) → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
