#!/usr/bin/env python
"""Redraw the covers of books already built, without rebuilding them: the
print wraparound (<slug>-cover.pdf), the EPUB's front (<slug>-epub-cover.png)
and the copy of that front inside <slug>.epub.

For when the cover code or a book's picture (assets/emblems/books.yaml)
changes. Many books were built from the command line and recorded nothing of
how, so every setting is read back from what the build left in output/: the
page count and trim from the interior PDF; title and author from the
.build.json; the blurb, publisher and font from the old cover; and the layout
by drawing the front in every style and keeping the one closest to the old
image. A book with a config takes its blurb, colours and font from there. The
new wraparound must come out the width the old one was, or nothing is
written.

    python redraw_covers.py [slug ...]      (default: every book in books.yaml)
"""
import glob
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import fitz
import numpy as np
import yaml
from PIL import Image

from book_creator import config, cover, fonts
from book_creator.model import FontSpec
from book_creator.pipeline import _slugify

HERE = Path(__file__).parent
OUT = HERE / "output"
LANG_NAMES = {m["name"].upper(): code for code, m in cover._MOTIFS.items()}


def config_specs() -> dict:
    specs = {}
    for path in glob.glob(str(HERE / "config" / "*.yaml")):
        try:
            for spec in config.load_specs(path):
                specs[spec.slug or _slugify(spec.title)] = spec
        except Exception:
            continue
    return specs


def font_family(cover_pdf: fitz.Document) -> str | None:
    """The family the old cover was set in, by its embedded fonts' names."""
    known = fonts.discover()
    for f in cover_pdf[0].get_fonts():
        name = f[3].split("+")[-1].split("-")[0]
        for candidate in (name, name.removesuffix("TT")):
            if fonts.normalize(candidate) in known:
                return candidate
    return None


def front_label_lang(text: str) -> str | None:
    """The source language from the old front's "X–ENGLISH PARALLEL EDITION"."""
    for line in text.splitlines():
        if "PARALLEL EDITION" in line:
            name = line.split("–")[0].strip()
            return LANG_NAMES.get(name, name.lower())
    return None


def closest_style(old_png: Path, **kw) -> str:
    old = Image.open(old_png).convert("L").resize((120, 180))
    best, best_d = None, None
    for style in cover.ALL_COVER_STYLES:
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "f.png"
            cover.render_ebook_cover(str(png), style=style, dpi=30, **kw)
            new = Image.open(png).convert("L").resize((120, 180))
        d = np.abs(np.asarray(old, float) - np.asarray(new, float)).mean()
        if best_d is None or d < best_d:
            best, best_d = style, d
    return best


def epub_meta(epub: Path) -> dict:
    """Title, author and source language from the EPUB's package document,
    for a book built before builds wrote a .build.json or with no print cover
    to read them from."""
    import re
    with zipfile.ZipFile(epub) as z:
        opf = next(n for n in z.namelist() if n.endswith(".opf"))
        text = z.read(opf).decode("utf-8")
    fields = lambda tag: [m.strip() for m in re.findall(rf"<dc:{tag}[^>]*>(.*?)</dc:{tag}>", text, re.S)]
    langs = [lang for lang in fields("language") if lang != "en"]
    return {"title": fields("title")[0], "author": fields("creator")[0],
            "lang": langs[0] if langs else None}


def replace_in_epub(epub: Path, png: Path) -> None:
    tmp = epub.with_suffix(".epub.new")
    with zipfile.ZipFile(epub) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = png.read_bytes() if info.filename == "EPUB/cover.png" else zin.read(info.filename)
            zout.writestr(info, data, compress_type=info.compress_type)
    os.replace(tmp, epub)


def redraw(slug: str, spec, emblem: str | None) -> str:
    interior = fitz.open(OUT / f"{slug}.pdf")
    pages = len(interior)
    trim = (round(interior[0].rect.width / 72, 3), round(interior[0].rect.height / 72, 3))
    interior.close()
    build = OUT / f"{slug}.build.json"
    if build.exists():
        meta = json.loads(build.read_text(encoding="utf-8"))
    elif spec:
        meta = {"title": spec.title, "author": spec.author}
    else:
        meta = epub_meta(OUT / f"{slug}.epub")
    pdf_path, png_path, epub_path = (OUT / f"{slug}-cover.pdf", OUT / f"{slug}-epub-cover.png",
                                     OUT / f"{slug}.epub")

    old = fitz.open(pdf_path) if pdf_path.exists() else None
    blurb, publisher, family, lang, old_w = "", "", None, None, None
    if old:
        page = old[0]
        old_w = page.rect.width / 72
        back = page.get_text(clip=fitz.Rect(0, 0, (trim[0] + cover.BLEED) * 72, page.rect.height))
        lines = [ln.strip() for ln in back.splitlines() if ln.strip()]
        if lines and lines[-1] == "Houser Classics":
            publisher = lines.pop()
        blurb = " ".join(" ".join(lines).split())
        family = font_family(old)
        front = page.get_text(clip=fitz.Rect(page.rect.width - (trim[0] + cover.BLEED) * 72, 0,
                                             page.rect.width, page.rect.height))
        lang = front_label_lang(front)
        old.close()

    kw = dict(title=meta["title"], author=meta["author"], trim=trim, tgt_lang="en")
    if spec:
        kw.update(src_lang=spec.src_lang, tgt_lang=spec.tgt_lang, font_spec=spec.font,
                  accent=spec.cover.accent, background=spec.cover.background)
        blurb = spec.cover.blurb or blurb
        publisher = spec.copyright.publisher or publisher
    else:
        if not lang and epub_path.exists():
            lang = epub_meta(epub_path)["lang"]
        kw.update(src_lang=lang or "en", font_spec=FontSpec(family=family or "Cardo"))
    style = closest_style(png_path, **kw) if png_path.exists() else (spec.cover.style if spec else "ornament")

    report = f"{slug}: {style}, {pages} pp"
    if old_w:
        tmp = pdf_path.with_suffix(".new.pdf")
        _, (w, h, spine) = cover.render_cover(
            str(tmp), style=style, pages=pages, paper=spec.cover.paper if spec else "white",
            blurb=blurb, publisher=publisher, emblem=emblem,
            spine_logo=spec.cover.spine_logo if spec else "auto", **kw)
        # A few thousandths is an old cover drawn for an interior a page or
        # two longer or shorter than the one there now, and the new one is
        # the right one. More is a different paper stock: keep the old.
        if abs(w - old_w) > 0.01:
            tmp.unlink()
            return f"{slug}: SKIPPED, new width {w:.3f} in against {old_w:.3f} in"
        os.replace(tmp, pdf_path)
        report += f", {w:.3f} x {h:.3f} in"
        if abs(w - old_w) > 0.0015:
            report += f" (was {old_w:.3f}: drawn for an older interior)"
    if png_path.exists():
        cover.render_ebook_cover(str(png_path), style=style, emblem=emblem, **kw)
        if epub_path.exists():
            replace_in_epub(epub_path, png_path)
            report += ", epub"
    return report


def main(slugs) -> None:
    books = yaml.safe_load((cover.EMBLEM_ART_DIR / "books.yaml").read_text(encoding="utf-8")) or {}
    specs = config_specs()
    for slug in slugs or books:
        if not (OUT / f"{slug}.pdf").exists():
            print(f"{slug}: no build in output/")
            continue
        print(redraw(slug, specs.get(slug), books.get(slug)))


if __name__ == "__main__":
    main(sys.argv[1:])
