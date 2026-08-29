"""Render aligned beads to a reflowable EPUB3 ebook, duplicating the PDF's
content (title, copyright, TOC, chapters, dual-language text, cover) in a
format e-readers can reflow.

What carries over from the PDF's `decor`:
- `chapter_image`: embedded and shown under each chapter title, same as print.
- `chapter` (fleuron/medieval/victorian): rasterized from the SAME vector
  drawing routines the PDF uses (decorations.render_ornament_png) and embedded
  as a PNG, rather than a Unicode dingbat character — a font glyph is never
  guaranteed to exist on a given e-reader (confirmed: some readers show a
  missing-glyph box for these), but a picture always renders. "rule" is a
  plain CSS <hr>, which needs no image and is font-independent already.
- `bead_separator`: same image treatment, between beads within a chapter.
- `opener_font`, body `font`, per-language cover art, copyright wording: all
  identical to the PDF (same font files embedded via @font-face, same text).

What doesn't carry over, because there's no fixed page to draw on:
- `margin` (per-page corner/frame/rule art) — inherently tied to a physical page.
- `corner_image` — same reason; only `chapter_image` (not page-corner-bound)
  has an EPUB equivalent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

try:
    from ebooklib import epub
except ImportError:  # pragma: no cover - exercised by test_epub_optional
    # EPUB output is optional (requirements-epub.txt), but pipeline imports
    # this module unconditionally — so a missing ebooklib must not take the
    # whole CLI down, only `--epub`. Annotations below are strings thanks to
    # `from __future__ import annotations`, so they never dereference this.
    epub = None

from . import decorations, fonts
from .model import Chapter, CopyrightSpec, DecorSpec, FontSpec
from .render_pdf import _esc, _lang_name, copyright_text


def _font_files(family: str | None) -> dict[str, str] | None:
    """Resolve a family name to its (regular, italic, bold) file paths, if installed."""
    if not family:
        return None
    entry = fonts.discover().get(fonts.normalize(family))
    if not entry or not entry.get("regular"):
        return None
    return {"regular": entry["regular"], "italic": entry.get("italic"),
            "bold": entry.get("bold")}


def _add_font_face(book: epub.EpubBook, css: list[str], css_name: str,
                   files: dict[str, str]) -> None:
    weights = [("regular", "normal", "normal"), ("italic", "normal", "italic"),
               ("bold", "bold", "normal")]
    seen: set[str] = set()
    for key, weight, style in weights:
        path = files.get(key)
        if not path or path in seen:
            continue
        seen.add(path)
        fname = f"{css_name}-{key}{Path(path).suffix}"
        item = epub.EpubItem(uid=f"font-{css_name}-{key}", file_name=fname,
                             media_type="application/x-font-ttf",
                             content=Path(path).read_bytes())
        book.add_item(item)
        css.append(
            f'@font-face {{ font-family: "{css_name}"; src: url("{fname}"); '
            f'font-weight: {weight}; font-style: {style}; }}'
        )


def _build_css(book: epub.EpubBook, *, body_font: str | None, opener_font: str | None,
               decor: DecorSpec) -> epub.EpubItem:
    css: list[str] = []
    body_family = "serif"
    if body_font:
        files = _font_files(body_font)
        if files:
            _add_font_face(book, css, "BodyFont", files)
            body_family = '"BodyFont", serif'

    opener_family = None
    if opener_font:
        files = _font_files(opener_font)
        if files:
            _add_font_face(book, css, "OpenerFont", files)
            opener_family = '"OpenerFont", serif'

    css.append(f"""
body {{ font-family: {body_family}; }}
h1.chapter-title {{ text-align: center; font-size: 1.4em; margin: 1.4em 0 0.2em; }}
hr.orn-rule {{ width: 35%; margin: 1.2em auto; border: none; border-top: 1px solid {decor.color}; }}
p.src {{ margin: 0 0 0.15em 0; text-align: justify; }}
p.tgt {{ margin: 0 0 0.9em 1.2em; font-style: italic; color: #555555; font-size: 0.95em; text-align: justify; }}
""")
    if opener_family:
        css.append(f"""
p.src.opener {{ font-family: {opener_family}; font-size: 1.55em; font-style: normal; }}
p.tgt.opener {{ font-family: {opener_family}; font-size: 1.3em; }}
""")
    css.append("""
.titlepage { text-align: center; margin-top: 30%; }
.titlepage h1 { font-size: 2em; }
.copyright p { font-size: 0.85em; margin: 0 0 0.8em; }
p.orn-img { text-align: center; margin: 0.4em 0 1em; }
p.orn-img img { height: 1.3em; width: auto; }
p.orn-img.sep { margin: 1.2em 0; }
p.orn-img.sep img { height: 0.9em; }
p.music-page { text-align: center; margin: 0.6em 0; }
p.music-page img { width: 100%; height: auto; }
p.music-caption { text-align: center; font-style: italic; font-size: 0.8em; color: #555555; margin: 0 0 1.4em; }
""")
    item = epub.EpubItem(uid="style-main", file_name="style.css",
                         media_type="text/css", content="\n".join(css).encode("utf-8"))
    book.add_item(item)
    return item


def _add_image_item(book: epub.EpubBook, path: str, uid: str) -> str:
    p = Path(path)
    fname = f"{uid}{p.suffix}"
    media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    book.add_item(epub.EpubItem(uid=uid, file_name=fname, media_type=media,
                                content=p.read_bytes()))
    return fname


def _rasterize_ornament(book: epub.EpubBook, style: str, color: str, uid: str,
                        tmp_dir: str) -> str | None:
    """Render a chapter-ornament style to a PNG and embed it. None for styles
    with no vector art (none/rule)."""
    tmp_path = str(Path(tmp_dir) / f"{uid}.png")
    if decorations.render_ornament_png(style, color, tmp_path) is None:
        return None
    return _add_image_item(book, tmp_path, uid)


def _chapter_ornament_html(chapter_image_fname: str | None,
                           chapter_orn_fname: str | None) -> str:
    fname = chapter_image_fname or chapter_orn_fname
    return f'<p class="orn-img"><img src="{fname}" alt=""/></p>' if fname else ""


def _bead_separator_html(sep_orn_fname: str | None) -> str:
    return f'<p class="orn-img sep"><img src="{sep_orn_fname}" alt=""/></p>' if sep_orn_fname else ""


def _music_html(book: epub.EpubBook, image_paths: list[str], caption: str, uid_prefix: str) -> str:
    """Embed a chapter's rendered grand-staff page images (see music.py)."""
    parts = []
    for i, path in enumerate(image_paths):
        fname = _add_image_item(book, path, f"{uid_prefix}-{i}")
        parts.append(f'<p class="music-page"><img src="{fname}" alt="Sheet music"/></p>')
    if caption:
        parts.append(f'<p class="music-caption">{_esc(caption)}</p>')
    return "\n".join(parts)


def _bead_html(bead, first: str, opener: bool) -> str:
    src_txt = _esc(bead.src_text)
    tgt_txt = _esc(bead.tgt_text)
    src_cls = "src opener" if opener else "src"
    tgt_cls = "tgt opener" if opener else "tgt"
    parts = []
    if first == "tgt":
        if tgt_txt:
            parts.append(f'<p class="{src_cls}">{tgt_txt}</p>')
        if src_txt:
            parts.append(f'<p class="{tgt_cls}">{src_txt}</p>')
    else:
        if src_txt:
            parts.append(f'<p class="{src_cls}">{src_txt}</p>')
        if tgt_txt:
            parts.append(f'<p class="{tgt_cls}">{tgt_txt}</p>')
    return "\n".join(parts)


def render(
    chapters: list[Chapter],
    *,
    out_path: str,
    title: str,
    author: str,
    src_lang: str,
    tgt_lang: str,
    first: str = "src",
    font_spec: FontSpec | None = None,
    decor: DecorSpec | None = None,
    copyright: CopyrightSpec | None = None,
    translation_note: str = "",
    cover_image_path: str | None = None,
    edition_line: str | None = None,
) -> str:
    if epub is None:
        raise RuntimeError(
            "EPUB output needs ebooklib: pip install -r requirements-epub.txt")

    decor = decor or DecorSpec()
    copyright = copyright or CopyrightSpec()
    font_spec = font_spec or FontSpec()

    book = epub.EpubBook()
    book.set_identifier(f"book-creator-{fonts.normalize(title)}-{fonts.normalize(author)}")
    book.set_title(title)
    book.set_language(tgt_lang)
    book.add_metadata("DC", "language", src_lang)
    book.add_author(author)

    has_cover = bool(cover_image_path and Path(cover_image_path).exists())
    if has_cover:
        book.set_cover(f"cover{Path(cover_image_path).suffix}",
                       Path(cover_image_path).read_bytes())
        # set_cover() only registers the image/page as manifest items — it does
        # NOT add the cover page to the spine or an EPUB2 <guide>, so without
        # this most readers (and Kindle conversion) never actually show it.
        book.guide.append({"type": "cover", "title": "Cover", "href": "cover.xhtml"})

    css_item = _build_css(book, body_font=font_spec.family,
                          opener_font=decor.opener_font, decor=decor)

    chapter_image_fname = None
    if decor.chapter_image and Path(decor.chapter_image).exists():
        chapter_image_fname = _add_image_item(book, decor.chapter_image, "chapter-orn")

    docs: list[epub.EpubHtml] = []

    # --- Title page ---
    edition_label = edition_line or f"{src_lang.upper()} &ndash; {tgt_lang.upper()} Parallel Edition"
    title_html = (
        f'<div class="titlepage"><h1>{_esc(title)}</h1>'
        f'<p>{_esc(author)}</p><p>{edition_label}</p></div>'
    )
    title_doc = epub.EpubHtml(title=title, file_name="title.xhtml", lang=tgt_lang)
    title_doc.content = title_html
    title_doc.add_item(css_item)
    book.add_item(title_doc)
    docs.append(title_doc)

    # --- Copyright page ---
    if copyright.enabled:
        paras, tail = copyright_text(copyright, title=title, author=author,
                                     src_lang=src_lang, translation_note=translation_note)
        body = "".join(f"<p>{p}</p>" for p in paras)
        body += "".join(f"<p>{t}</p>" for t in tail)
        cr_doc = epub.EpubHtml(title="Copyright", file_name="copyright.xhtml", lang=tgt_lang)
        cr_doc.content = f'<div class="copyright">{body}</div>'
        cr_doc.add_item(css_item)
        book.add_item(cr_doc)
        docs.append(cr_doc)

    # --- Chapters ---
    # Ornament PNGs are generated lazily, one per distinct style actually
    # used, and cached — matters for `chapter: random`, where different
    # chapters may pick different styles. Image bytes are read into the
    # EpubItem immediately inside _rasterize_ornament, so the temp dir
    # doesn't need to outlive this block.
    chapter_docs: list[epub.EpubHtml] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        orn_cache: dict[str, str | None] = {}

        def _orn_fname_for(style: str) -> str | None:
            if style not in orn_cache:
                orn_cache[style] = _rasterize_ornament(
                    book, style, decor.color, f"orn-{style}", tmp_dir)
            return orn_cache[style]

        sep_orn_fname = _orn_fname_for(decor.bead_separator)

        for idx, ch in enumerate(chapters, start=1):
            parts = []
            if ch.title:
                parts.append(f'<h1 class="chapter-title">{_esc(ch.title)}</h1>')
            chapter_style = (decorations.pick_random_style(idx - 1)
                            if decor.chapter == "random" else decor.chapter)
            chapter_orn_fname = None if chapter_image_fname else _orn_fname_for(chapter_style)
            orn = _chapter_ornament_html(chapter_image_fname, chapter_orn_fname)
            if orn and (ch.title or chapter_image_fname):
                parts.append(orn)
            sep = _bead_separator_html(sep_orn_fname)
            for i, bead in enumerate(ch.beads):
                if i > 0 and sep:
                    parts.append(sep)
                parts.append(_bead_html(bead, first, opener=(i == 0 and bool(decor.opener_font))))
            if ch.music_images:
                parts.append(_music_html(book, ch.music_images, ch.music_caption, f"music-{idx}"))

            fname = f"chap_{idx:04d}.xhtml"
            doc = epub.EpubHtml(title=ch.title or f"Chapter {idx}", file_name=fname, lang=tgt_lang)
            doc.content = "\n".join(parts)
            doc.add_item(css_item)
            book.add_item(doc)
            chapter_docs.append(doc)

    docs.extend(chapter_docs)

    # --- Navigation / TOC ---
    nav = epub.EpubNav()
    book.add_item(epub.EpubNcx())
    book.add_item(nav)
    book.toc = tuple(d for d in chapter_docs if d.title)

    book.spine = (["cover"] if has_cover else []) + ["nav"] + docs

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(out_path, book)
    return out_path
