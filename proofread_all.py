#!/usr/bin/env python
"""Proofread many configured books in one model load.

    python proofread_all.py                       # every config except messias
    python proofread_all.py --only franciade --only meleagris
    python proofread_all.py --cap 300 --device cuda:0
    python proofread_all.py --from-metrics        # re-analyse the saved scores

For each book this builds the aligned beads exactly as make_book.py would (so a
machine-translated book is read from the translation cache), keeps up to `--cap`
beads as a few contiguous runs spread over the book, and scores all of them in a
single Tower load (proofread_pairs.run_batch). It writes one report per book and
output/proofread/SUMMARY.md. Advisory only: nothing is edited or rebuilt.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st
import sys
import time
import traceback
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from book_creator import proofread_pairs as pp
from book_creator.config import load_specs
from book_creator.pipeline import _slugify, chapters_for_spec

# Configs that are not one finished book each, or that are done separately.
SKIP = {"books.yaml", "books.example.yaml", "messias.yaml"}


def _specs(paths: list[str], only: list[str]):
    for path in paths:
        if os.path.basename(path) in SKIP:
            continue
        try:
            specs = load_specs(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ {path}: {exc}")
            continue
        for spec in specs:
            slug = spec.slug or _slugify(spec.title)
            key = f"{os.path.basename(path)} {spec.title} {slug}".lower()
            if only and not any(o.lower() in key for o in only):
                continue
            yield path, spec, slug


def build_items(args) -> list[dict]:
    books = []
    paths = args.configs or sorted(glob.glob("config/*.yaml"))
    for path, spec, slug in _specs(paths, args.only):
        t0 = time.time()
        rec = {"config": os.path.basename(path), "title": spec.title, "slug": slug,
               "src_lang": spec.src_lang, "tgt_lang": spec.tgt_lang, "items": [],
               "total": 0, "error": ""}
        try:
            quiet = lambda m: print(m) if "⚠" in m else None  # noqa: E731
            chapters = chapters_for_spec(spec, quiet)
            items = pp.collect_items(chapters)
            rec["total"] = len(items)
            rec["items"] = pp.sample_windows(items, args.cap)
        except BaseException as exc:  # noqa: BLE001 - one bad book must not stop the rest
            if isinstance(exc, KeyboardInterrupt):
                raise
            rec["error"] = f"{type(exc).__name__}: {exc}"[:240]
            traceback.print_exc(limit=2)
        print(f"• {spec.title[:48]:48s} {rec['total']:6d} beads, scoring "
              f"{len(rec['items']):4d}  ({time.time() - t0:.0f}s)"
              + (f"  ERROR {rec['error'][:70]}" if rec["error"] else ""), flush=True)
        books.append(rec)
    return books


def summarise(books: list[dict], out_dir: Path) -> None:
    rows = []
    for b in books:
        if b["error"] or not b["items"]:
            rows.append((b, None))
            continue
        findings = pp.analyse(b["items"], b["metrics"])
        n = len(b["items"])
        lab = [m["labse"] for m in b["metrics"]]
        nb = [max(x for x in (m.get("labse_prev"), m.get("labse_next")) if x is not None)
              for m in b["metrics"]]
        drift = sum(1 for o, x in zip(lab, nb) if x > o + 0.08 and o < 0.75)
        high = sum(1 for f in findings if f.severity == "high")
        rows.append((b, {"n": n, "flagged": len(findings), "high": high,
                         "labse": st.mean(lab), "low": sum(v < 0.5 for v in lab),
                         "drift": drift}))
        report = pp.format_report(findings, scanned=n, model=pp.TOWER_MODEL,
                                  note=f"Sampled {n} of {b['total']} beads "
                                       f"(contiguous runs across the book).")
        (out_dir / f"{b['slug']}-proofread.md").write_text(report, encoding="utf-8")

    lines = ["# Pair proofreading, all books", "",
             "Each book is scored on up to a few hundred contiguous beads. Flags are "
             "relative to that book's own distribution, so compare the *absolute* "
             "columns (mean LaBSE, beads under 0.5, drift) between books, not the "
             "flag counts.", "",
             "| Book | Lang | Beads | Scored | Mean LaBSE | LaBSE<0.5 | Drift | Flagged | High |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    ok = [(b, r) for b, r in rows if r]
    for b, r in sorted(ok, key=lambda x: x[1]["labse"]):
        lines.append(f"| {b['title'][:46]} | {b['src_lang']} | {b['total']} | {r['n']} | "
                     f"{r['labse']:.3f} | {r['low']} ({100 * r['low'] / r['n']:.0f}%) | "
                     f"{r['drift']} | {r['flagged']} | {r['high']} |")
    bad = [b for b, r in rows if not r]
    if bad:
        lines += ["", "## Not scored", ""]
        lines += [f"- **{b['title']}** ({b['config']}): "
                  f"{b['error'] or 'no two-sided beads'}" for b in bad]
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {out_dir / 'SUMMARY.md'} ({len(ok)} scored, {len(bad)} not)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("configs", nargs="*", help="config files (default: config/*.yaml)")
    ap.add_argument("--only", action="append", default=[],
                    help="substring of config/title/slug; repeatable")
    ap.add_argument("--cap", type=int, default=500, help="max beads scored per book")
    ap.add_argument("--model", default=pp.TOWER_MODEL)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--quant", choices=["auto", "none", "4bit", "8bit"], default="auto")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--out-dir", default="output/proofread")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and count the beads, score nothing")
    ap.add_argument("--from-metrics", action="store_true",
                    help="re-analyse <out-dir>/_scores.json without any GPU work")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "_scores.json"

    if args.from_metrics:
        books = json.loads(cache.read_text(encoding="utf-8"))
    else:
        books = build_items(args)
        if args.dry_run:
            tot = sum(len(b["items"]) for b in books)
            print(f"\n{len(books)} books, {tot} beads would be scored")
            return 0
        todo = [b for b in books if b["items"]]
        t0 = time.time()
        metrics = pp.run_batch(todo, model=args.model, batch_size=args.batch_size,
                               quant=args.quant, device=args.device,
                               log=lambda m: print(m, flush=True))
        for b, m in zip(todo, metrics):
            b["metrics"] = m
        print(f"scored {sum(len(b['items']) for b in todo)} beads in {time.time() - t0:.0f}s")
        cache.write_text(json.dumps(books), encoding="utf-8")
    summarise(books, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
