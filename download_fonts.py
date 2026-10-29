#!/usr/bin/env python
"""Download a curated set of SIL Open Font License fonts into fonts/.

Source: the official Google Fonts repository (github.com/google/fonts), OFL
directory. The OFL permits embedding these fonts in documents you sell, which is
what KDP print-on-demand requires. A copy of each license ships in the repo;
keep one with your publishing records.

    python download_fonts.py            # fetch all
    python download_fonts.py greek      # only one category (serif|medieval|greek|period)

The one exception is the "period" category: Dieter Steffmann's Theuerdank
Fraktur, a digitisation of the type cut for the 1517 Theuerdank itself. It is not
OFL but 1001fonts' Free For Commercial Use licence, which names "books ... that
will be sold for money" as permitted use and forbids modifying or republishing
the font file. A PDF's embedded subset is neither, so the print interior may use
it; an EPUB would ship the whole .ttf, so the Theuerdank-type edition is
PDF-only. It is fetched from 1001fonts rather than vendored for the same reason.
"""

from __future__ import annotations

import io
import sys
import zipfile
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
                 "grenzegotisch", "pirataone", "uncialantiqua"],
    "greek": ["gfsdidot", "gfsneohellenic"],
    "period": ["theuerdankfraktur"],
}

# Not on Google Fonts: zip URL and the one file to keep from it. See the
# module docstring for the licence.
ZIPS = {
    "theuerdankfraktur": ("https://www.1001fonts.com/download/theuerdank-fraktur.zip",
                          "TheuerdankFraktur.ttf"),
}


def fetch_zip(slug: str) -> tuple[list[str], str | None]:
    url, name = ZIPS[slug]
    dest = FONTS_DIR / name
    if dest.exists():
        return [name + " (cached)"], None
    resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=60)
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code}"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        dest.write_bytes(z.read(name))
    return [f"{name} ({dest.stat().st_size // 1024} KB)"], None


def fetch_family(slug: str) -> tuple[list[str], str | None]:
    if slug in ZIPS:
        return fetch_zip(slug)
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
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
