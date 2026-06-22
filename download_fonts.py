#!/usr/bin/env python
"""Download a curated set of SIL Open Font License fonts into fonts/.

Source: the official Google Fonts repository (github.com/google/fonts), OFL
directory. The OFL permits embedding these fonts in documents you sell, which is
what KDP print-on-demand requires. A copy of each license ships in the repo;
keep one with your publishing records.

    python download_fonts.py            # fetch all
    python download_fonts.py greek      # only one category (serif|medieval|greek)
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

FONTS_DIR = Path("fonts")
API = "https://api.github.com/repos/google/fonts/contents/ofl/{}"
HEADERS = {"User-Agent": "book_creator-fontfetch", "Accept": "application/vnd.github+json"}

# Some upstream files have cryptic PostScript-era names; give them clean,
# parser-friendly ones (Family-Style.ttf) so the discovery step groups them.
RENAME = {
    "IMFeENrm28P.ttf": "IMFellEnglish-Regular.ttf",
    "IMFeENit28P.ttf": "IMFellEnglish-Italic.ttf",
    "IMFePIrm28P.ttf": "IMFellDWPica-Regular.ttf",
    "IMFePIit28P.ttf": "IMFellDWPica-Italic.ttf",
}

# Google Fonts "ofl/<slug>" directories. All SIL Open Font License.
FAMILIES: dict[str, list[str]] = {
    "serif": ["cardo", "ebgaramond", "gentiumbookplus", "oldstandardtt",
              "librebaskerville", "imfellenglish", "imfelldwpica"],
    "medieval": ["unifrakturmaguntia", "unifrakturcook", "medievalsharp",
                 "grenzegotisch", "pirataone"],
    "greek": ["gfsdidot", "gfsneohellenic"],
}


def fetch_family(slug: str) -> tuple[list[str], str | None]:
    resp = requests.get(API.format(slug), headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        return [], f"listing HTTP {resp.status_code}"
    got = []
    for item in resp.json():
        if item.get("type") != "file" or not item["name"].lower().endswith(".ttf"):
            continue
        out_name = RENAME.get(item["name"], item["name"])
        dest = FONTS_DIR / out_name
        if dest.exists():
            got.append(out_name + " (cached)")
            continue
        data = requests.get(item["download_url"],
                            headers={"User-Agent": HEADERS["User-Agent"]}, timeout=60)
        if data.status_code == 200:
            dest.write_bytes(data.content)
            got.append(f"{item['name']} ({len(data.content) // 1024} KB)")
    return got, None


def main(argv: list[str]) -> int:
    FONTS_DIR.mkdir(exist_ok=True)
    categories = argv or list(FAMILIES)
    total = 0
    for cat in categories:
        slugs = FAMILIES.get(cat)
        if not slugs:
            print(f"unknown category {cat!r}; choose from {list(FAMILIES)}")
            continue
        print(f"\n=== {cat} ===")
        for slug in slugs:
            files, err = fetch_family(slug)
            if err:
                print(f"  ✗ {slug}: {err}")
            else:
                total += len([f for f in files if "cached" not in f])
                print(f"  ✓ {slug}: {', '.join(files) or 'no .ttf found'}")
    print(f"\nDone. {total} new file(s) in {FONTS_DIR}/.")
    return 0


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
