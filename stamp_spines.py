#!/usr/bin/env python
"""Put the signum on the spine of every finished cover in output/.

    python stamp_spines.py --dry-run          # what would change
    python stamp_spines.py                    # do it (originals backed up)
    python stamp_spines.py --only murten --logo gold

A cover is edited, not rebuilt: its spine width, front, back and fonts stay as
they are, and the interior PDF is never touched. Each cover's spine is found
from its own size and its interior's trim, the existing spine text is cleared,
and the signum is stamped as a vector overlay (book_creator.cover.stamp_signum).
A cover that already carries one is left alone, so it is safe to re-run.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from book_creator import cover


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default="output")
    ap.add_argument("--only", action="append", default=[], help="substring of the slug")
    ap.add_argument("--logo", default="auto", choices=cover.SPINE_LOGO_CHOICES)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="stamp even if one is present")
    ap.add_argument("--backup-dir", default="output/_covers_before_signum")
    args = ap.parse_args()

    covers = sorted(glob.glob(os.path.join(args.dir, "*-cover.pdf")))
    if args.only:
        covers = [c for c in covers if any(o in os.path.basename(c) for o in args.only)]
    tally = {"stamped": 0, "skipped": 0}
    for path in covers:
        slug = os.path.basename(path)[:-len("-cover.pdf")]
        interior = os.path.join(args.dir, f"{slug}.pdf")
        if not os.path.exists(interior):
            interior = os.path.join(args.dir, f"{slug}-facsimile.pdf")   # facsimile books
        if not os.path.exists(interior):
            print(f"  skip  {slug:46s} no interior PDF beside it")
            tally["skipped"] += 1
            continue
        if args.dry_run:
            import tempfile
            with tempfile.TemporaryDirectory() as t:
                r = cover.stamp_signum(path, interior, logo=args.logo, force=args.force,
                                       out_path=os.path.join(t, "x.pdf"))
        else:
            os.makedirs(args.backup_dir, exist_ok=True)
            bak = os.path.join(args.backup_dir, os.path.basename(path))
            if not os.path.exists(bak):
                shutil.copyfile(path, bak)
            r = cover.stamp_signum(path, interior, logo=args.logo, force=args.force)
        tally[r["action"]] += 1
        if r["action"] == "stamped":
            print(f"  {'would ' if args.dry_run else ''}stamp {slug:46s} spine {r['spine_in']:.2f} in, "
                  f"{r['variant']}, {r['width_in']:.2f} in wide")
        else:
            print(f"  skip  {slug:46s} {r['reason']}")
    print(f"\n{tally['stamped']} {'would be ' if args.dry_run else ''}stamped, "
          f"{tally['skipped']} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
