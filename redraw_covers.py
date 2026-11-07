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
    python redraw_covers.py --paper color slug ...   (an extra wraparound
        for a KDP listing set to colour ink: <slug>-cover-color-paper.pdf)
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
# Books whose old cover cannot say what face it should be in: the Salmasius
# was drawn before Old Standard was installed, so it fell back to Times --
# unembedded, which KDP refuses. build_victorian_doc.py asks for Old Standard.
FONT_FALLBACK = {"de-modo-usurarum-liber": "OldStandard"}


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


def lang_by_colour(page: fitz.Page, front_x0: float) -> str | None:
    """The language whose accent colour the old front's rules are drawn in,
    if any is: the commonest stroke colour on the panel, matched exactly."""
    from collections import Counter
    strokes = Counter(tuple(round(v * 255) for v in d["color"])
                      for d in page.get_drawings()
                      if d.get("color") and d["rect"].x0 >= front_x0)
    if not strokes:
        return None
    rgb = "#%02x%02x%02x" % strokes.most_common(1)[0][0]
    return next((code for code, m in cover._MOTIFS.items() if m["color"] == rgb), None)


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


def front_difference(old_front: fitz.Pixmap, new_pdf: Path, trim) -> float:
    """Mean grey-level difference between the old front panel and the new
    one: a handful for the same design, tens for a changed one."""
    doc = fitz.open(new_pdf)
    page = doc[0]
    new = page.get_pixmap(dpi=30, clip=fitz.Rect(page.rect.width - (trim[0] + cover.BLEED) * 72,
                                                  0, page.rect.width, page.rect.height))
    doc.close()
    grey = lambda pm: np.asarray(Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
                                 .convert("L").resize((120, 180)), float)
    return float(np.abs(grey(old_front) - grey(new)).mean())


def replace_in_epub(epub: Path, png: Path) -> None:
    tmp = epub.with_suffix(".epub.new")
    with zipfile.ZipFile(epub) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = png.read_bytes() if info.filename == "EPUB/cover.png" else zin.read(info.filename)
            zout.writestr(info, data, compress_type=info.compress_type)
    os.replace(tmp, epub)


def redraw(slug: str, spec, emblem: str | None, paper: str | None = None) -> str:
    """Redraw one book's covers in place -- or, given a paper, write only a
    second wraparound for that stock beside the first, <slug>-cover-<paper>-
    paper.pdf, for a KDP listing set to a paper the build was not."""
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
    edition_line, old_front, frame_lang = None, None, None
    if old:
        page = old[0]
        old_w = page.rect.width / 72
        back = page.get_text(clip=fitz.Rect(0, 0, (trim[0] + cover.BLEED) * 72, page.rect.height))
        lines = [ln.strip() for ln in back.splitlines() if ln.strip()]
        if lines and lines[-1] == "Houser Classics":
            publisher = lines.pop()
        blurb = " ".join(" ".join(lines).split())
        family = font_family(old)
        front_x0 = page.rect.width - (trim[0] + cover.BLEED) * 72
        front = page.get_text(clip=fitz.Rect(front_x0, 0, page.rect.width, page.rect.height))
        lang = front_label_lang(front)
        # The line at the foot of the front. Kept only when a build gave its
        # own (the Black Prince's, Salmasius's); the default is redrawn from
        # the language, which may have been named since.
        foot = " ".join(page.get_text(clip=fitz.Rect(
            front_x0, page.rect.height - (cover.BLEED + 1.3) * 72,
            page.rect.width, page.rect.height)).split())
        if foot and "PARALLEL EDITION" not in foot:
            edition_line = foot
        old_front = page.get_pixmap(dpi=30, clip=fitz.Rect(front_x0, 0, page.rect.width,
                                                           page.rect.height))
        frame_lang = lang_by_colour(page, front_x0)
        old.close()

    kw = dict(title=meta["title"], author=meta["author"], trim=trim, tgt_lang="en",
              edition_line=edition_line)
    if spec:
        kw.update(src_lang=spec.src_lang, tgt_lang=spec.tgt_lang, font_spec=spec.font,
                  accent=spec.cover.accent, background=spec.cover.background)
        blurb = spec.cover.blurb or blurb
        publisher = spec.copyright.publisher or publisher
    else:
        if not lang and epub_path.exists():
            lang = epub_meta(epub_path)["lang"]
        # An English-only book drawn with another language's motif -- the
        # Salmasius is English prose under the Latin laurel -- says so only
        # in its colour.
        lang = lang or frame_lang
        family = family or FONT_FALLBACK.get(slug, "Cardo")
        kw.update(src_lang=lang or "en", font_spec=FontSpec(family=family))
    style = closest_style(png_path, **kw) if png_path.exists() else (spec.cover.style if spec else "ornament")

    report = f"{slug}: {style}, {pages} pp"
    built_paper = spec.cover.paper if spec else "white"
    if old_w:
        tmp = pdf_path.with_suffix(".new.pdf")
        # A few thousandths is an old cover drawn for an interior a page or
        # two longer or shorter than the one there now, and the new one is
        # the right one. More is a different paper stock: keep the old.
        built_w = cover.cover_dimensions(trim, pages, built_paper)[0]
        if abs(built_w - old_w) > 0.01:
            return f"{slug}: SKIPPED, {built_paper} paper gives {built_w:.3f} in against {old_w:.3f} in"
        _, (w, h, spine) = cover.render_cover(
            str(tmp), style=style, pages=pages, paper=paper or built_paper,
            blurb=blurb, publisher=publisher, emblem=emblem,
            spine_logo=spec.cover.spine_logo if spec else "auto", **kw)
        if paper:
            out = OUT / f"{slug}-cover-{paper}-paper.pdf"
            os.replace(tmp, out)
            return report + f", {out.name}: {w:.3f} x {h:.3f} in, front differs by " \
                f"{front_difference(old_front, out, trim):.1f}"
        os.replace(tmp, pdf_path)
        report += f", {w:.3f} x {h:.3f} in"
        if abs(w - old_w) > 0.0015:
            report += f" (was {old_w:.3f}: drawn for an older interior)"
    elif paper:
        return f"{slug}: no print cover to read back"
    if png_path.exists():
        cover.render_ebook_cover(str(png_path), style=style, emblem=emblem, **kw)
        if epub_path.exists():
            replace_in_epub(epub_path, png_path)
            report += ", epub"
    return report


def main(argv) -> None:
    paper = None
    if "--paper" in argv:
        i = argv.index("--paper")
        paper = argv[i + 1]
        if paper not in cover._PAPER_THICKNESS:
            sys.exit(f"--paper takes one of {sorted(cover._PAPER_THICKNESS)}")
        argv = argv[:i] + argv[i + 2:]
    books = yaml.safe_load((cover.EMBLEM_ART_DIR / "books.yaml").read_text(encoding="utf-8")) or {}
    specs = config_specs()
    for slug in argv or books:
        if not (OUT / f"{slug}.pdf").exists():
            print(f"{slug}: no build in output/")
            continue
        print(redraw(slug, specs.get(slug), books.get(slug), paper))


if __name__ == "__main__":
    main(sys.argv[1:])
