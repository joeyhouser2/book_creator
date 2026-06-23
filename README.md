# book_creator

Build **dual-language parallel-text books** from public-domain sources and output
**KDP print-ready PDFs** for Amazon print-on-demand.

Each aligned unit prints the original (Latin / Greek / French / German) and its
English translation together — sentence-by-sentence for prose, line-by-line for
verse — so the reader can follow both at once.

```
Gutenberg original ─┐
                    ├─ fetch ─ clean ─ segment ─ align (Gale-Church) ─ render → output/<book>.pdf
Gutenberg translation ┘
```

## ⚠️ Read this first: translation copyright

The original works are public domain, but **a translation has its own copyright
held by the translator**. Pairing a 50-year-old original with a modern
translation does *not* make the translation free to publish.

For US/KDP, a translation is generally safe only if it was **first published
before 1929**, or the translator died **70+ years ago**. Always verify the
translation's status before publishing, and keep your source records. The tool
warns on every build unless you set `translation_pd_confirmed: true`.

## Setup

```bash
pip install -r requirements.txt
```

Then add a Unicode serif font (needed for Greek glyph embedding) — see
[`fonts/README.md`](fonts/README.md). Cardo is recommended.

## Web UI (search · build · preview)

A local browser app to search Project Gutenberg, queue a build, and flip through
the rendered pages.

```bash
pip install -r requirements-web.txt
python run_web.py            # then open http://127.0.0.1:5000
```

Flow:
1. **Search** Gutenberg (by title/author, optional language filter) — powered by
   the [Gutendex](https://gutendex.com) catalog API.
2. Drop one result into **Original** and one into **Translation**.
3. Set options (mode, aligner, font, decorations, trim), tick the
   public-domain confirmation, and **Build**.
4. Watch the live build log, then **page through the rendered PDF** and download it.

Tip: the original and translation are usually *separate* Gutenberg entries —
search once in the source language (e.g. `bello gallico`, lang `la`) and again in
English. The catalog uses the work's real title, so search `de bello gallico`,
not `gallic war`, for the Latin edition.

## Matching scope (range selection)

The biggest real-world gotcha: the two editions must cover the **same content**.
A Gutenberg "translation" often bundles extra works — e.g. the McDevitte Caesar
(#10657) contains the Gallic War *and* the Civil War, while the Latin #218 is only
Gallic War I–IV. Aligning them whole would be hopeless.

So scope each side to matching **divisions** (books/chapters). List them first:

```bash
python make_book.py --src-id 218 --tgt-id 10657 --outline
```

Then pass a range per side (1-based, inclusive). Division 1 is usually front
matter, so to take Gallic War Books I–IV from both:

```bash
python make_book.py --src-id 218 --tgt-id 10657 --src-lang la \
    --src-range 2-5 --tgt-range 2-5 --title "The Gallic War" \
    --author "Julius Caesar" --aligner embed --confirm-pd
```

When both ranges resolve to the same number of divisions, they're **anchored
book-by-book** (each aligned independently — no cross-book drift). In the web UI,
the range is a pair of dropdowns under each selected edition.

## Command-line usage

**Single book** straight from two Gutenberg ids:

```bash
python make_book.py --src-id 218 --tgt-id 10657 --src-lang la \
    --title "The Gallic War" --author "Julius Caesar" --mode prose --confirm-pd
```

**Batch** from a config file (copy and edit the example):

```bash
cp config/books.example.yaml config/books.yaml
python make_book.py config/books.yaml
```

Output PDFs land in `output/`.

## Config fields

| field | meaning |
|-------|---------|
| `title`, `author` | printed on the title page |
| `src_lang` | original language: `la`, `fr`, `grc` (Greek), `de` |
| `src_gutenberg_id` / `tgt_gutenberg_id` | Gutenberg ebook ids |
| `src_path` / `tgt_path` | local text files (override the ids) |
| `mode` | `prose` (sentence alignment) or `verse` (line alignment) |
| `aligner` | `auto` / `embed` / `gale-church` (see below) |
| `first` | `src` = original first, `tgt` = translation first |
| `trim` | KDP trim size in inches, e.g. `[6.0, 9.0]` |
| `translation_pd_confirmed` | set `true` once you've verified PD status |
| `font` | family name, or a block with `regular`/`italic`/`bold` files |
| `decorations` | `margin`, `chapter`, `color`, `corner_image`, `chapter_image` |

## How alignment works

Two backends, selected by the `aligner` field (or `--aligner`):

- **`embed` (recommended)** — **LaBSE cross-lingual embeddings**. Compares what
  sentences *mean*, so it stays aligned even when a translator splits, merges, or
  reorders sentences. Needs the optional deps:
  `pip install -r requirements-embed.txt` (pulls in PyTorch; the ~1.8 GB model
  downloads once and is cached).
- **`gale-church`** — length-based, **zero extra dependencies**. Fast and
  surprisingly good when the two editions track each other closely, but drifts
  where sentence counts diverge.
- **`auto`** (default) — uses `embed` when `sentence-transformers` is installed,
  otherwise falls back to `gale-church`.

Both anchor on chapter headings (when both editions agree on chapter count) to
prevent drift over long texts. Alignment is automatic and *approximate*: always
proofread the output, especially around chapter starts.

## Fonts

Fonts are **auto-discovered** from `fonts/`: drop a font's `.ttf` files in and the
tool groups them into a family, infers regular/italic/bold from the filenames, and
exposes it to the CLI (`--font <id>`), the `font:` config field, and the web UI's
picker (grouped by category, with a ✔ Greek badge). Set `font` to a family id
(e.g. `cardo`, `imfellenglish`, `gfsdidot`) or a full block with explicit
`regular`/`italic`/`bold` files.

Install a curated, **commercially-licensable** set (all SIL Open Font License,
which permits embedding in books you sell) with:

```bash
python download_fonts.py            # all, or: serif | medieval | greek
```

| Category | Families | Greek |
|----------|----------|-------|
| Classic serif | Cardo, EB Garamond, Gentium Book Plus, Old Standard, Libre Baskerville, IM Fell English, IM Fell DW Pica | most ✔ |
| Medieval / display | UnifrakturMaguntia, UnifrakturCook (blackletter), Grenze Gotisch, Pirata One, MedievalSharp | — |
| Greek display | GFS Didot, GFS Neohellenic | ✔ |

Greek (polytonic) needs a ✔ Greek font, or glyphs render blank. Cardo and Old
Standard are good all-rounders that cover both Latin and polytonic Greek. The
medieval/display faces are Latin-only — best for titles, not Greek body text.

## Copyright page

A copyright page is generated on the title page's verso (it's unnumbered, like
the title page; body pagination starts after it). Crucially, it claims **only the
compilation** — the parallel arrangement, typography, and design — and explicitly
states the original and translation are public domain. Claiming copyright on the
PD texts themselves would be copyfraud, so don't.

Config block (or CLI: `--publisher`, `--copyright-holder`, `--edition-year`,
`--isbn`, `--translator`, `--no-copyright`):

```yaml
copyright:
  publisher: "Houser Classics"
  holder: "Your Name"      # compilation copyright holder
  year: 2026
  isbn: ""                 # KDP issues a free ISBN if you don't have one
  translator: "W. A. McDevitte and W. S. Bohn"
  # rights: "..."          # optional: replace the generated wording entirely
```

Set `copyright: false` to omit the page. You still set metadata and pricing in
the KDP dashboard — this only produces the interior page.

## Decorations

Make the page look like a real published book:

| setting | values | effect |
|---------|--------|--------|
| `margin` | `none` / `rule` / `corners` / `frame` | per-page art, gutter-aware (outer edge is correct on recto vs verso) |
| `chapter` | `none` / `fleuron` / `rule` | ornament under each chapter title |
| `color` | hex, e.g. `#8a7a5c` | ornament ink color |
| `corner_image` | PNG/JPG path | your own art, mirrored into the four corners (overrides vector `corners`) |
| `chapter_image` | PNG/JPG path | your own art centered under chapter titles |

Vector ornaments need no assets. For custom art, drop a PNG in (e.g.) `art/` and
point `corner_image` at it — it's auto-mirrored so each corner faces inward.

## Pipeline modules

| module | role |
|--------|------|
| `fetch.py` | download Gutenberg text, strip the license banner, cache locally |
| `segment.py` | detect chapters; split into sentences (prose) or lines (verse) |
| `fonts.py` | auto-discover font families in fonts/, register, expose catalog |
| `align.py` | shared alignment DP + Gale-Church backend |
| `align_embed.py` | LaBSE embedding (meaning-based) backend |
| `aligners.py` | backend selection (`auto` / `embed` / `gale-church`) |
| `decorations.py` | vector ornaments + chapter dividers |
| `render_pdf.py` | KDP interior PDF: mirrored gutter margins, embedded fonts, page numbers |
| `pipeline.py` | orchestrates fetch → segment → align → render |
| `webapp/` | Flask UI: Gutendex search, background build jobs, PyMuPDF page preview |

## KDP notes

- Default output is **6×9″** with mirrored inside (gutter) margins that scale
  with page count, per KDP minimums.
- Fonts are embedded (KDP requires this).
- You still set the cover, metadata, and pricing in the KDP dashboard. This tool
  produces the **interior PDF** only.
- Print one proof copy before going live — automated alignment needs a human
  proofread.

## Roadmap ideas

- Cover generator
- EPUB output for Kindle
- Drop caps at chapter openings
- Footnote/glossary support
- Alignment confidence report (flag low-similarity beads for manual review)
