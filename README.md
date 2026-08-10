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

## Librarian agent (natural-language search)

Instead of searching Gutendex yourself, describe the book and let a
locally-run LLM find and pair the editions:

```bash
ollama pull llama3.1        # any tool-calling-capable model
ollama serve

python ask_librarian.py "Dante's Inferno, Italian with an English translation"
python ask_librarian.py "Heine's Buch der Lieder, German with English" --build
```

It calls Ollama's tool-calling API to search Gutendex, inspect candidate
editions (language, length, division outline), and pick a source + translation
pair — scoping `src_range`/`tgt_range` itself if the two editions cover
different amounts of the work. It's scoped to Gutenberg only (no open web
crawling), so every source stays an auditable Gutenberg id, same as searching
by hand.

It never marks `translation_pd_confirmed: true` itself — Gutendex has no
reliable translation-publication date, so that stays your call. It prints
whatever evidence it found (translator name, any date) as
`translation_source_note` and ready-to-paste YAML for `config/books.yaml`; add
`--build` to render immediately with default styling, or `--confirm-pd` once
you've verified the translation is actually public domain.

Small local models are stochastic — if it loops without proposing a pairing,
try a larger tool-calling model (`--model qwen3:14b`) or raise `--max-turns`.

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

### MT-pivot alignment (`mt`) — plug in your own translator

A third backend aligns by **translation pivot**: it translates the source
(Latin/Greek) into rough English with a model you provide, then aligns those
machine translations against the real English edition. Matching English-to-English
is far more reliable than cross-lingual matching — especially for Latin and
Ancient Greek, where general models like LaBSE are weak. The machine translation
only needs to be good enough to *match* sentences; the printed book still shows
the real source and translation.

Register a translator per language (any callable `texts -> english`):

```python
from book_creator import translators
translators.register("la",  translators.HTTPTranslator("http://localhost:8001/translate", src_lang="la"))
translators.register("grc", translators.HTTPTranslator("http://localhost:8002/translate", src_lang="grc"))
```

or in a config file:

```yaml
translators:
  la:  { url: "http://localhost:8001/translate" }
  grc: { url: "http://localhost:8002/translate" }
books:
  - ...
```

Once a translator is registered for a language, `aligner: auto` uses it
automatically (falling back to embeddings / Gale-Church otherwise). The HTTP
contract and a runnable reference server are in
[`examples/translator_server.py`](examples/translator_server.py).

## Segment review (local LLM QA pass)

After alignment (and restyle, if any), optionally ask a local LLM to flag
beads that look wrong, so you know where to proofread instead of reading the
whole book:

```bash
python make_book.py --src-id 218 --tgt-id 10657 --src-lang la --src-range 2-5 \
    --tgt-range 2-5 --title "The Gallic War" --author "Julius Caesar" \
    --confirm-pd --review --review-model llama3.1
```

or `review: true` in a config entry (plus `review_model`, `review_host`,
`review_sample` to cap how many beads get sent for a quick spot-check on a
long book). It writes `output/<slug>-review.md` listing each flagged bead —
grouped by severity — with the reason: misalignment (the two sides don't
correspond), leftover markup (uncleaned section numbers, `[Illustration]`
captions, footnote markers), encoding artifacts, or a bad sentence split. It
never edits content or blocks the build, and needs `ollama serve` running
locally; if it can't reach Ollama, the build logs a warning and continues
without a report.

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
| Medieval / display | UnifrakturMaguntia, UnifrakturCook (blackletter), Grenze Gotisch, Pirata One, MedievalSharp, Uncial Antiqua | — |
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

## Table of contents

A contents page is generated automatically when the book has **two or more
titled divisions** (e.g. Books I–IV). Page numbers are resolved against the real
layout (a two-pass `multiBuild`), with dotted leaders and right-aligned numbers.
Front matter (title, copyright, contents) is unnumbered; body pagination starts
after it. Disable with `toc: false` in config or `--no-toc`.

## Cover

Generates a **KDP wraparound cover** (back + spine + front in one PDF), sized
from the trim, the real interior page count (which sets the spine width), the
paper stock, and 0.125″ bleed. The bottom-right of the back cover is left clear
for KDP's barcode.

Each source language gets an **ornamental motif** — a vector emblem plus an
accent colour:

| Language | Emblem | Accent |
|----------|--------|--------|
| Latin (`la`) | laurel wreath | imperial oxblood |
| Greek (`grc`/`el`) | Greek key (meander) | Aegean blue |
| French (`fr`) | fleur-de-lis | royal azure |
| German (`de`) | oak leaf + acorns | forest green |

Enable with `--cover` (CLI) or a `cover:` block (config). The cover lands at
`output/<slug>-cover.pdf`:

```bash
python make_book.py --src-id 218 --tgt-id 10657 --src-lang la --src-range 2-5 \
    --tgt-range 2-5 --title "The Gallic War" --author "Julius Caesar" \
    --cover --paper white --blurb "Caesar's account of the conquest of Gaul." --confirm-pd
```

```yaml
cover:
  paper: white            # white | cream | color (sets spine width)
  blurb: "Back-cover description."
  background: "#f4ead5"   # parchment
  accent: "#7c2128"       # optional: override the per-language accent colour
```

## Decorations

Make the page look like a real published book:

| setting | values | effect |
|---------|--------|--------|
| `margin` | `none` / `rule` / `corners` / `frame` | per-page art, gutter-aware (outer edge is correct on recto vs verso) |
| `chapter` | `none` / `fleuron` / `rule` / `medieval` / `victorian` / `classical` / `baroque` / `nouveau` / `rococo` / `artdeco` / `random` | ornament under each chapter title |
| `color` | hex, e.g. `#8a7a5c` | ornament ink color |
| `corner_image` | PNG/JPG path | your own art, mirrored into the four corners (overrides vector `corners`) |
| `chapter_image` | PNG/JPG path | your own art centered under chapter titles |
| `opener_font` | font family id, e.g. `uncialantiqua` | decorative display font for each chapter's opening bead (both languages) |

Vector ornaments need no assets. For custom art, drop a PNG in (e.g.) `art/` and
point `corner_image` at it — it's auto-mirrored so each corner faces inward.

All styles are pure vector, no assets needed, and (except per-page `margin`)
also render in the EPUB — rasterized to a transparent PNG from the same
drawing code, so a font glyph is never required (some e-readers show a
missing-glyph box for Unicode dingbats; a picture always renders correctly).

| style | look | fits |
|-------|------|------|
| `fleuron` | line — diamond — line, with small end-curls | general-purpose, any era |
| `medieval` | wavy vine, alternating ivy leaves, berry cluster | illuminated-manuscript / medieval texts |
| `victorian` | central rosette flanked by acanthus scrollwork | 19th-century novels |
| `classical` | laurel sprig flanking a sunburst medallion | Latin/Greek antiquity (Caesar, Marcus Aurelius) |
| `baroque` | scallop-shell cartouche flanked by rocaille scrolls | 17th-18th century French (Molière, Racine, Voltaire) |
| `nouveau` | flowing whiplash tendrils around a five-petal flower | fin-de-siècle French (Baudelaire, Huysmans) |
| `rococo` | small asymmetric flower spray flanked by uneven, delicate C-scrolls | Louis XV-era French, lighter/more playful than baroque |
| `artdeco` | stepped sunburst fan flanked by nested chevron wedges | 1920s-30s, bold and geometric rather than organic |

`random` picks a different style (from every ornamented style above, i.e. all
except `none`) for each chapter. The pick is deterministic — seeded by the
chapter's index — so it isn't re-rolled between the PDF and EPUB editions of
the same book, or between repeat builds.

`opener_font` applies a decorative face (Uncial Antiqua ships as `uncialantiqua`)
to just the first bead of each chapter — typically an epigraph or section
subtitle — at a larger size, giving an illuminated chapter-opening feel without
touching the rest of the running text. CLI: `--opener-font uncialantiqua`.

## Pipeline modules

| module | role |
|--------|------|
| `fetch.py` | download Gutenberg text, strip the license banner, cache locally |
| `segment.py` | detect chapters; split into sentences (prose) or lines (verse) |
| `fonts.py` | auto-discover font families in fonts/, register, expose catalog |
| `align.py` | shared alignment DP + Gale-Church backend |
| `align_embed.py` | LaBSE embedding (meaning-based) backend |
| `align_mt.py` | MT-pivot backend (translate source, align in English) |
| `translators.py` | per-language translator registry + HTTP/callable adapters |
| `clean.py` | strip inline section markers / boilerplate before alignment |
| `aligners.py` | backend selection (`auto` / `embed` / `mt` / `gale-church`) |
| `decorations.py` | vector ornaments + chapter dividers |
| `render_pdf.py` | KDP interior PDF: mirrored gutter margins, embedded fonts, page numbers |
| `render_epub.py` | reflowable EPUB3: embedded fonts, cover, nav TOC |
| `cover.py` | KDP wraparound cover with per-language ornamental motifs |
| `pipeline.py` | orchestrates fetch → segment → align → render → cover → epub |
| `webapp/` | Flask UI: Gutendex search, background build jobs, PyMuPDF page preview |
| `ollama_client.py` | thin client for a local Ollama server's tool-calling chat API |
| `librarian.py` | natural-language book search agent (finds + pairs Gutenberg editions) |
| `reviewer.py` | post-alignment QA pass (LLM flags likely misalignment/formatting errors) |

## EPUB

Generates a reflowable EPUB3 alongside the PDF — same chapters, same
dual-language beads, same copyright wording and per-language cover art, so the
two editions stay in sync automatically:

```bash
pip install -r requirements-epub.txt   # ebooklib + pymupdf (rasterizes the cover)
python make_book.py --src-id 798 --tgt-id 44747 --src-lang fr \
    --title "Le Rouge et le Noir" --author "Stendhal" --epub --confirm-pd
```

or `epub: true` in a config entry. Output lands at `output/<slug>.epub`.

What carries over from `decor`: `chapter_image` (shown under each chapter
title, same as print), `bead_separator`, `opener_font`, the body font, and the
cover motif are all identical to the PDF. `chapter` (fleuron/medieval/
victorian/rule) has no vector drawing in reflowable text, so it falls back to
a centered Unicode dingbat (❦ / ❧ / ❋, or a plain rule) — still readable,
just not the full hand-drawn vector art.

What doesn't carry over: `margin` and `corner_image` are inherently per-page
(corner/frame art tied to a physical sheet), and EPUB has no fixed page to
draw them on.

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
