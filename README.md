# book_creator

Build **dual-language parallel-text books** from public-domain sources and output
**KDP print-ready PDFs** for Amazon print-on-demand.

Each aligned unit prints the original (Latin / Greek / French / German) and its
English translation together — sentence-by-sentence for prose, line-by-line for
verse — so the reader can follow both at once.

```
Gutenberg original ─┐
                    ├─ fetch ─ clean ─ segment ─ align (Gale-Church) ─┐
Gutenberg translation ┘                                              ├─ render → output/<book>.pdf
                                                                     │                    .epub
latin repo corpus ──── load (already aligned) ───────────────────────┘                    .m4b
```

Two ways in: a **pair of Gutenberg editions**, which have to be fetched and
statistically aligned, or a **work from the [`latin`](https://github.com/joeyhouser2/latin)
repo's corpus**, which is already sentence-aligned and skips all of that. Either
can then be narrated as a bilingual audiobook on your GPU.

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

## Web UI (search · build · preview · narrate)

A local browser app: pick a source, queue a build, flip through the rendered
pages, and play the audiobook.

```bash
pip install -r requirements-web.txt
python run_web.py            # then open http://127.0.0.1:5000
```

The **Source** panel has three tabs.

**Gutenberg pair** — two separate editions, aligned:
1. **Search** Gutenberg (title/author, optional language filter) — powered by
   the [Gutendex](https://gutendex.com) catalog API.
2. Drop one result into **Original** and one into **Translation**.
3. Pick a matching division range on each side.
4. Tick the public-domain confirmation and **Build**.

Tip: the original and translation are usually *separate* Gutenberg entries —
search once in the source language (e.g. `bello gallico`, lang `la`) and again in
English. The catalog uses the work's real title, so search `de bello gallico`,
not `gallic war`, for the Latin edition.

**Latin corpus** — one already-aligned work (see [Latin corpus
source](#latin-corpus-source-the-latin-repo)): search or filter by author /
genre / period, scope to sections, and preview the actual Latin/English pairs
before building. The aligner picker and the translator-copyright confirmation
both disappear on this tab, because neither applies.

**Local files** — your own `.txt` or `.epub` from `input/` (see [Local
files](#local-files-txt-and-epub)). Each file is inspected before it can be
selected, so a scan with no usable text layer is caught before the build
rather than after it.

Then set options and **Build**. The right column shows rendered pages, the
cover, and an audio player.

Two things are opt-in and off by default, so a plain dual-language PDF needs
neither: the **Edition** picker at the top of Options (dual-language, or one
language alone — see [Monolingual editions](#monolingual-editions)), and the
collapsed **Audiobook** panel, which loads no model and synthesizes nothing
unless you tick it.

Builds are recorded in `cache/jobs.db`, so **Recent builds** (under the
preview) survives restarting the server: reopen a finished book to page
through it or download it again. A job still marked running when the process
dies is listed as `interrupted` rather than spinning forever — the files it
had already written are on disk, and the TTS cache makes restarting it cheap.

## Local files (`.txt` and `.epub`)

Drop files into `input/` and pick them on the **Local files** tab, or point
`src_path` / `tgt_path` at them from the CLI or a config entry. A `.txt` is
read as-is; an `.epub` is unpacked into plain text, following the **spine**
(reading order) rather than the manifest, with headings kept on their own
lines so chapter detection still works.

### It tells you when a file is not worth building

A large share of EPUBs in the wild are page scans wrapped around OCR, and bad
OCR is worse than useless here: it survives alignment (which only compares
lengths or embeddings), reaches the page looking like text, and gets read
aloud literally. So every file is inspected first — document and image counts,
extractable characters, and any accuracy figure the file reports about itself:

```
input/pale_fire.epub
  221 documents, 219 images, 445,972 characters
  ⚠ Unusable: the file reports its own OCR as 24% accurate across 175 pages.
```

That one extracts as `a voung gentleman`, `Hodge shan't be sh< t`,
`JMES BOSWELL`. No amount of alignment or narration fixes a source like that —
the answer is a real ebook rather than a scan. The warning is advisory, not a
block: the UI asks for confirmation and builds it anyway if you insist.

## Monolingual editions

The parallel text is the point of this tool, but not every book wants both
languages. `sides` drops one:

| `sides` | result |
|---|---|
| `both` (default) | the dual-language parallel text |
| `src` | a monolingual edition of the **original** — no translation printed |
| `tgt` | a monolingual edition of the **translation** — a standalone readable English book |

```bash
python make_book.py --corpus-id 79 --sides src --mode verse --font cardo
```

In the web UI it's the **Edition** picker at the top of Options. Choosing a
monolingual edition hides the controls that stop meaning anything — "which line
comes first" is moot once a bead has one side.

It applies to the audiobook too: an original-only book narrates only the
original, which is also roughly half the GPU time.

Three things worth knowing:

- **Alignment still runs** on the Gutenberg path for `src`/`tgt`. That is
  deliberate — the bead structure is what carries chapter anchoring and sentence
  order, so the correct way to print one language is to align as usual and then
  stop printing the other side. Both renderers already skip an empty side, so
  nothing downstream needed changing.
- **`sides: src` needs no public-domain confirmation.** Nothing of the
  translation is published, so the translator's copyright stops applying, and
  the UI drops the checkbox. `sides: tgt` still asks, because that edition *is*
  the translation.
- **`sides: src` unlocks untranslated corpus works.** Roughly 13k of the corpus
  has no English at all; those are unbuildable as a parallel text but perfectly
  printable on their own, so an original-only build keeps segments that the
  dual-language path would drop.

## Latin corpus source (the `latin` repo)

The sibling project [`latin`](https://github.com/joeyhouser2/latin) maintains a
SQLite corpus of Latin and Greek works — Perseus, the Latin Library, Corpus
Corporum, DigilibLT, Musa Medievalis, Wikisource, EDCS inscriptions and more —
where each row is **one source sentence with its English already beside it**:

```
documents ─→ sections ─→ segments(latin_text, english_text, english_styled)
```

Because that pipeline translates per segment, segment *i* already corresponds to
segment *i*. So a book built from it **skips fetch, clean, segment, and align
entirely** — there is no statistical alignment and therefore no drift to
proofread around chapter starts, which is the main thing that goes wrong on the
Gutenberg path.

Browse it from the CLI:

```bash
python make_book.py --corpus --corpus-search alcuinus --corpus-lang la
python make_book.py --corpus --corpus-id 79      # sections, counts, licence
```

In the web UI there are **author / genre / period / century** filters as well
as free text, because substring search over 13k works only helps if you
already know the Latin form of the name you want (`Augustinus`, not
`Augustine`). Two coverage filters sit alongside them: works that already have
English, and works the Victorian stylizer has been over.

Then build. `title`, `author`, and `src_lang` come from the document record, so
an id is enough:

```bash
python make_book.py --corpus-id 79 --corpus-range 2-3 --mode verse --font cardo --epub
```

The database is found via `$LATIN_REPO`, then `../latin`, then
`~/Documents/GitHub/latin` — or pass `--corpus-db`. It is opened **read-only**;
this project never writes to your corpus.

| flag / config | meaning |
|---|---|
| `--corpus-id` / `corpus.doc_id` | which work to build |
| `--corpus-range` / `corpus.section_range` | section range, 1-based inclusive |
| `--no-styled` / `corpus.prefer_styled: false` | use the plain machine translation instead of the Victorian-stylized English |
| `--keep-sigla` / `corpus.strip_markup: false` | keep the editorial apparatus (see below) |
| `--corpus-db` / `corpus.db_path` | explicit path to the repo or the `.db` |

### Editorial sigla

Critical and epigraphic editions wrap letters in editorial marks —
`<A>ltus`, `Imp(erator)`, `[Aug]ustus`. The corpus keeps those for scholarly
display and stores a stripped copy alongside. A POD parallel text is for
*reading*, and a narrator cannot say a bracket, so **the stripped form is
printed by default** (`Altus`, `Imperator`, `Augustus`); the build logs how many
segments it touched. Pass `--keep-sigla` for a scholarly edition that should
show its apparatus.

### Copyright, the other way round

The Gutenberg path's hazard is that a *translator* owns their translation. Here
the English is machine translation this project produced, so no third party
holds copyright on it — but that has to be **disclosed** rather than passed off
as a human translation, and the copyright page says so automatically.

What needs checking instead is the **source licence**, which the corpus records
honestly and which is frequently *not* free — `CC BY-NC-ND (DigilibLT)`,
`no explicit license published`, `ALIM (SISMEL) via Corpus Corporum`. Every
licence string is shown in the UI with an `ok` / `check licence` /
`licence unknown` badge, and the build logs a warning for anything that is not
clearly permissive. That check is yours to make; the tool will not make it
for you.

## Audiobooks (bilingual narration on your GPU)

The printed book puts each bead's original next to its translation. The
audiobook does the same thing in time instead of space:

```
<original sentence>  (pause)  <English sentence>  (longer pause)  ...
```

Chapters become real chapter markers in the M4B, so a player shows a chapter
list and resumes where you left off.

```bash
pip install -r requirements-audio.txt      # read the warning at the top first
python make_book.py --audio-engines        # what's installed, and on which GPU
python make_book.py --corpus-id 79 --mode verse --audio \
    --audio-voice input/narrator.wav --audio-max-beads 20
```

> **Install this in its own virtualenv.** `chatterbox-tts` pins
> torch/transformers/numpy and will replace a working CUDA build of torch with a
> generic wheel — which breaks the LaBSE aligner here *and* the NLLB models in
> the `latin` repo. `requirements-audio.txt` has the isolated-venv recipe.

### Engines

Pluggable, registered exactly the way `translators.py` registers translation
backends, and all loaded lazily — importing the module never pulls in torch.

| engine | licence | languages | VRAM | notes |
|---|---|---|---|---|
| **`chatterbox`** (default) | MIT | 23, incl. `it`, `el`, `de`, `fr` | ~7 GB | clones a narrator from a 6–30s clip; **safe to sell** |
| `kokoro` | Apache-2.0 | 8, no Greek or German | ~1 GB | tiny and many times realtime; fixed voices |
| `xtts` | **CPML — non-commercial** | 17, incl. German | ~4 GB | best cloning quality; personal listening only, and the build says so |

Add your own with `audio.register("name", MyEngine())`.

### Narrator voices

**You don't need one to start.** Chatterbox ships a built-in voice, so leaving
the voice unset just works. A reference clip is only for cloning a *particular*
narrator.

When you do want one, fetch public-domain samples from
[LibriVox](https://librivox.org), whose recordings are dedicated to the public
domain — the same bar the text sources are held to. Cloning a voice you have no
rights to is the obvious hazard with any cloning TTS; a LibriVox reader has
explicitly released theirs, so the narration is as publishable as the text
beside it.

```bash
python download_voices.py            # the curated set
python download_voices.py la grc     # just these languages
python download_voices.py --list     # what's available
```

Each becomes a ~20 second mono 24 kHz WAV in `voices/`. Only that slice
crosses the network — ffmpeg range-requests into the MP3 rather than pulling a
whole chapter. Pick one from the Audiobook panel's dropdown, or:

```bash
python make_book.py --corpus-id 79 --audio --audio-voice voices/la-caesar.wav
```

| voice | what it is |
|---|---|
| `la-caesar`, `la-aesop` | **Latin**, read by a human |
| `grc-thucydides` | **Ancient Greek**, read by a human |
| `it-pirandello`, `fr-hugo`, `es-dickens` | Italian, French, Spanish |
| `en-austen` (female), `en-melville` (male) | English, for the translation side |

The Latin and Greek ones matter most, for the reason in the next section.

### Latin and Greek have no TTS voice

No model anywhere has one. They are read with the nearest living-language voice:

| source | voice | why |
|---|---|---|
| Latin (`la`) | Italian (`it`) | ecclesiastical Latin is pronounced Italianate — the standard choral convention |
| Ancient Greek (`grc`) | Modern Greek (`el`) | the usual modern reading of ancient text |

That is a real convention, not a fudge — but it *is* a convention: classical
restored pronunciation will not come out of any of these models. The build logs
the substitution every time.

**Cloning sidesteps this.** A voice cloned from `la-caesar` (a human reading
*De Bello Gallico*) or `grc-thucydides` carries that reader's actual Latin or
Greek pronunciation, rather than an Italian voice approximating it. That is the
best pronunciation available here, and it is the main reason to bother with a
reference clip at all.

### Options

| flag | config | meaning |
|---|---|---|
| `--audio` | `audio.enabled` | narrate after rendering |
| `--audio-engine` | `audio.engine` | which backend |
| `--audio-device` | `audio.device` | CUDA device. **Defaults to the card with the most memory**, not `cuda:0` — CUDA orders devices fastest-first, so `cuda:0` is often the *smaller* card |
| `--audio-voice` | `audio.voice` | reference WAV to clone; omit for the engine's built-in voice. See [Narrator voices](#narrator-voices) |
| `--audio-format` | `audio.format` | `m4b` (chapter markers) or `mp3` |
| `--audio-max-beads` | `audio.max_beads` | narrate only the first N beads — a voice test before committing hours of GPU time |
| `--no-announce-chapters` | `audio.announce_chapters` | don't read chapter titles aloud |

Every utterance is cached under `cache/tts/` keyed by engine + language + voice
+ text, so a re-run — or a run resumed after a crash — re-synthesizes only what
actually changed. Output lands at `output/<slug>.m4b`, with the per-chapter WAVs
in `output/<slug>-audio/`. If ffmpeg is missing the WAVs are kept and the build
says so; a TTS failure never loses the finished PDF.

If `CUDA_VISIBLE_DEVICES` is masking cards, the CLI and the UI both say so
outright — otherwise the biggest model you can run is decided by a stale
environment variable rather than by your hardware.

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

Division detection normally needs a numbered or keyword+number heading
("CHAPTER IV", a bare "I"/"II"...). That's enough for a poetry collection
numbered straight through in one run (Heine's *Buch der Lieder*, I..CCXXVII),
but some collections instead title each standalone poem by name and only
number *multi-part* poem cycles, restarting at I each time (Baudelaire's *Les
Fleurs du Mal*). Pass `--poem-titles` (or `poem_titles: true` in the config)
to also treat an isolated, blank-flanked title line as a division boundary —
check `--outline --mode verse --poem-titles` first, since it's off by default
and only worth turning on when the plain numbered-heading outline looks too
coarse (a few divisions running tens of thousands of characters instead of
one per poem).

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
| `corpus` | pull a pre-aligned work from the `latin` repo instead (overrides both; `corpus: 79` is valid shorthand) |
| `audio` | narrate a bilingual audiobook — see [Audiobooks](#audiobooks-bilingual-narration-on-your-gpu) |
| `mode` | `prose` (sentence alignment) or `verse` (line alignment) |
| `sides` | `both` (parallel text, default), `src` (original only), `tgt` (translation only) — see [Monolingual editions](#monolingual-editions) |
| `poem_titles` | verse only: also split on an isolated poem title with no numeral (see below) |
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
| `corpus.py` | read a pre-aligned work out of the `latin` repo's corpus.db (read-only) |
| `epub_reader.py` | unpack a local EPUB into plain text, and report scan/OCR quality first |
| `download_voices.py` | fetch public-domain narrator samples from LibriVox into voices/ |
| `audio.py` | pluggable GPU TTS engines + interleaved bilingual audiobook assembly |
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
| `webapp/` | Flask UI: Gutendex + corpus search, local files, background build jobs, PyMuPDF page preview, audio player |
| `webapp/jobs.py` | SQLite job record, so builds survive a server restart |
| `ollama_client.py` | thin client for a local Ollama server's tool-calling chat API |
| `librarian.py` | natural-language book search agent (finds + pairs Gutenberg editions) |
| `reviewer.py` | post-alignment QA pass (LLM flags likely misalignment/formatting errors) |
| `music.py` | musical literature: match poems to art-song settings, typeset the grand staff |

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

## Musical literature (`music:`)

For verse-mode books, poems that were set to music by a composer can print
their piano grand staff (treble + bass clef) right under the poem — Heine's
*Buch der Lieder* is the motivating case: Schumann's *Dichterliebe*, Op. 48
sets 16 of its poems ("Lyrisches Intermezzo").

```yaml
music:
  enabled: true
  catalog: dichterliebe   # only registry built in so far
```

or `--music --music-catalog dichterliebe` on the CLI.

How it works:
- **Matching** is by the poem's first line (its "incipit"), since verse
  divisions are numbered, not individually titled. A few of Heine's opening
  lines repeat verbatim across different poems, so ambiguous entries also
  check the second line (see `music.SongSetting.second_line`).
- **Source**: the [OpenScore Lieder Corpus](https://github.com/OpenScore/Lieder),
  CC0-licensed MusicXML — same public-domain bar the text sides are already
  held to. Scores are fetched once and cached under `cache/music/`.
- **Rendering** needs [LilyPond](https://lilypond.org/download.html) — both
  `lilypond` and `musicxml2ly` on PATH. It is **not bundled**; if it's
  missing, matched poems are logged and skipped, and the build still
  succeeds without music.
- Only the piano part (2 staves: treble + bass) is typeset, not the vocal
  line — the poem text is already printed alongside it.

Currently only `dichterliebe` is registered. Adding another composer/work
means adding entries to `music._REGISTRIES` the same way (see the module's
docstring) — the OpenScore corpus also has Schumann's *Liederkreis*, Op. 24
and Schubert's *Schwanengesang* (6 of its songs set Heine), both Heine
sources, as natural next additions.

## KDP notes

- Default output is **6×9″** with mirrored inside (gutter) margins that scale
  with page count, per KDP minimums.
- Fonts are embedded (KDP requires this).
- You still set the cover, metadata, and pricing in the KDP dashboard. This tool
  produces the **interior PDF** only.
- Print one proof copy before going live — automated alignment needs a human
  proofread.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Around 120 tests, a few seconds to run. They cover the parts where a silent
wrong answer is possible rather than a crash: alignment-free corpus loading,
editorial-sigla stripping (no letter may be lost with the brackets),
monolingual filtering, audiobook planning and chapter-marker ordering, EPUB
extraction, job persistence, and the HTTP surface — including that
`/api/local/*` refuses paths outside `input/`.

Tests needing the `latin` corpus or downloaded fonts **skip** rather than
fail, so the suite is still useful on a fresh clone. Audio tests run against a
stub engine that synthesizes a tone, so no model weights or GPU are required.

## Roadmap ideas

- Forced alignment between the narration and the EPUB, for read-along (Media Overlays)
- Per-speaker voices for dialogue in the audiobook
- Run a real TTS model end to end (the audio path is verified against a stub engine only)
- Drop caps at chapter openings
- Footnote/glossary support
- More musical-literature catalogs (Schumann's Liederkreis Op. 24, Schubert's
  Schwanengesang) and a web-UI toggle for `music:` (currently config/CLI only)
