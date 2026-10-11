# Source catalogue

Every work considered for a dual-language edition, what it is, and where it
stands. The recurring lesson: the code was rarely the obstacle. Finding a text
that is *public domain*, *digitised*, and *not behind a bot check* was.

Texts that can be fetched automatically live in [`fetch_sources.py`](fetch_sources.py);
the files themselves are gitignored, since they are re-fetchable. The OCR output
that is *not* re-fetchable by script is tracked in [`ocr-texts/`](ocr-texts/).

**[WANTED.md](WANTED.md) is the companion to this file**: for everything still
blocked, what to look for by hand, where, and what to check before bothering.

**Legend** — ✅ built · 🟡 ready to build · 🔶 blocked on sourcing · ⛔ blocked on
copyright or language.

---

## Built

| Work | Edition | English |
|---|---|---|
| **Das Nibelungenlied** | dual 574 pp · English-only 306 pp | Needler 1904, **human**, PD |
| **Os Lusíadas** | dual 481 pp · English-only 249 pp | Burton, **human**, PD |
| **Gerusalemme Liberata** | dual 2 vols (415 + 426 pp) · English-only 430 pp | Fairfax 1600, **human**, PD |
| **The Battle of Maldon** | dual 23 pp | Garnett, **human**, PD |
| **Klopstock, *Der Messias*** | dual 773 pp, 20 cantos, 8.5 × 11 in. `tight` | Egestorff 1826, **human**, PD — blank verse, re-read from the page scans with Tesseract (part 2) and Google's OCR (part 1), aligned by meaning in 6-line blocks |
| **Kudrun** | dual 501 pp, 1,705 strophes in 32 Aventiuren | Nichols 1889, **human**, PD |
| **Mistral, *Mirèio*** | dual 324 pp, 12 cantos | Preston 1872, **human**, PD |
| **Cantar de Mio Cid** | dual 231 pp, 3 cantares | Rose 1919, **human**, PD |
| **Wolfram, *Parzival*** | dual 1,253 pp, 16 books, set block fashion (verse against prose) | Weston 1894, **human**, PD |
| **Marcus Musurus, *Ode to Plato*** | dual 15 pp | Roscoe 1805, **human**, PD |
| **Ocland, *Anglorum Praelia* and *Elizabetha*** | dual 235 pp | Sharrock 1585, **human**, PD — 7 blocks with no matching English filled by machine and marked † |
| **La Légende des siècles** | dual 411 pp · English-only 257 pp | machine |
| **La Henriade** | dual 312 pp | machine |
| **Africa** | dual 386 pp | machine, via the `latin` repo's `nllb-latin` |
| **Basinio, *Hesperis*** | dual 429 pp, 13 books | machine, `nllb-latin`, a sentence at a time |
| **Basinio, *Astronomicon*** | dual 79 pp, 2 books | machine, `nllb-latin` |
| **Basinio, *Meleagris*** | dual 146 pp, 3 books | machine, `nllb-latin` |
| **Basinio, *Argonauticon*** | dual 126 pp, books 1–3, all there is: Basinio died before finishing it | machine, `nllb-latin` |
| **Pontano, *Urania*** | dual 299 pp, 5 books | machine, `nllb-latin` |
| **Pontano, *Parthenopeus*** | dual 85 pp | machine, `nllb-latin` |
| **Pontano, *De hortis Hesperidum*** | dual 60 pp | machine, `nllb-latin` |
| **Ronsard, *La Franciade*** books 1–4 | dual 444 pp | machine, `qwen3:14b` |
| **Ercilla, *La Araucana*** | part 1 dual 409 pp (cantos 1–15) · parts 2–3 dual 580 pp (cantos 16–37) | machine, `qwen3:14b`, octava by octava |
| **Rhodoman, 9 Latin works** | one short book each, `config/rhodoman_latin.yaml` | machine, `nllb-latin` |
| **Rhodoman, 23 Greek works** | one book each, `config/rhodoman_greek.yaml` | machine, `qwen3:14b` |
| **Poliziano, Greek epigrams** | dual 43 pp from 411 surviving lines | machine, `qwen3:14b`, from damaged OCR — **largely nonsense** where the Greek is damaged |

The human-translation books carry no disclosure and are sellable, with caveats:
the Kudrun, Mirèio, Cid and Ocland original-language texts are **unproofread OCR**
(their copyright pages say so), and Ocland's English has the gaps described below.
The machine-translated ones say so on the copyright page. The Rhodoman books are
working builds only, until the licence of rhodomanologia.de is settled; the
Pontano books use text from poetiditalia.it, whose terms are worth checking
before sale.

Camões and Tasso both wrote in ottava rima and both found translators who kept
it, so those pair **stanza for stanza** — 9 of 10 Lusíadas cantos match exactly,
18 of 20 Tasso cantos. Maldon pairs **line for line**, because Garnett's is a
scholarly crib rather than a verse rendering.

**How the newer ones were assembled** (each has a `fetch_<name>.py` and a
`config/<name>.yaml`; `tests/test_fetchers.py` covers the pure parts):

- **Kudrun.** Bartsch 1865 read by Tesseract's stock `lat` model — it beat
  GT4HistOCR by a wide margin, because that model is trained on blackletter and
  reads this Antiqua *w* as *v*. Both texts number their 1,705 strophes the same
  way and Nichols divides the poem into 32 tales, so both files are cut at his
  boundaries and pair exactly. 1,525 strophes were recovered; the other 180 print
  as `[strophe lost to OCR]` beside their English. The numbering uses the longest
  increasing run of printed numbers as anchors, because the OCR reads 2 as 9.
- **Mirèio.** The Provençal is the left-hand pages of an 1861 bilingual edition.
  Running heads are too garbled to sort pages by, so each *line* is classified as
  Provençal or French by function words and shape. Mistral's stanza is seven lines
  to Preston's six, so stanza counts differ and the pairing is by meaning.
- **Cid.** Pidal's critical text, with variant notes and margin headings stripped
  by line shape. Laisses are not numbered in it, so they are cut by measuring
  **assonance** — 161 against Rose's 149. The pairing is by meaning.
- **Hesperis.** Drudi's 1794 print from the Google Books text layer (the EPUB is
  page images only). A second OCR (`lat`) agrees on all but eight words; six are
  fixed. **`ocr_correct` was deliberately not run:** it "corrects" Neo-Latin
  forms toward the classical vocabulary (*Cyllam* → *cellam*, *Sismundumque* →
  *inmundumque*).
- **Ocland.** Sharrock's TEI is aligned to the Latin with the MT-pivot aligner
  in **blocks of eight lines** (`align_block`): a hexameter epic and a fourteener
  paraphrase do not pair line to line, and one line is too few words to score.
  Block alignment scores well (mean cosine 0.46). A block whose English scores
  under 0.15 — the page that belonged there is gone and the aligner paired it with
  its neighbour — is replaced by a machine translation, marked † and disclosed
  (`fill_missing`, `fill_below`). That is 7 blocks. The Latin is OCR of a 1580
  print, so those passages translate poorly. Illegible words in Sharrock show
  as `[...]`.

- **Parzival.** Weston's English is prose in two Gutenberg volumes whose files file
  every heading and every note under a `BOOK n` line (60 divisions where the poem has
  16); `fetch_parzival.py` keeps only each book's text. Verse cannot pair line by line
  with prose, so each book is set block fashion.
- **Araucana.** Part 1 from the 1911 edition, parts 2–3 from the 1803 Sancha edition
  (cantos numbered by order, because the OCR reads *XXII* as *XXIt*); each octava is
  translated whole.
- **Rhodoman.** The site's pages are TEI rendered as HTML; only the `main-grc` /
  `main-la` text of each verse line is taken, never the editors' German translation.
  The Greek went through `qwen3:14b` because the Greek NLLB models, trained on
  prose, turn Doric epic into nonsense.
- **Looping translations.** About one machine translation in 200 collapses into
  repeating itself ("He can, he can, he can ..."). `mt_cache` now spots these by how
  few distinct four-word runs they contain and translates that unit again in
  ten-word pieces, marking any piece that still loops `[not translated]`.

**A finding about translators.** On 16th-century verse, Opus-MT renders *yvoire*
as "yogurt" and *sourci* as "the sour" — it reads modern French only. A chat
model run locally (`qwen3:14b`) reads the early-modern spelling and is the
`OllamaTranslator` adapter in `translators.py`. On the same Latin hexameter,
`nllb-latin` read common nouns as names (*saevior*, *fragmina*, *vulnera* became
"Saevior", "Fragmins", "the wounded Vulnera") where `qwen3:14b` did not. The
Hesperis edition was built with `nllb-latin` on request; the comparison is
recorded here so the choice can be revisited.

---

## The Perseus corpus — 744 works already paired

The single largest source, and the one easiest to overlook because
`cache/perseus.db` goes silently empty: **148 Latin and 596 Greek works, each an
original beside a public-domain human translation**, anchored on its own CTS
citation scheme. "Book 3, line 40" is "Book 3, line 40" — no statistical
alignment, no machine translation, nothing to disclose.

Rebuild with `python make_book.py --update-perseus`, then build any work with
`--perseus-id <id>`. The copyright check is automatic: the build prints
"Translation published 1922 — before 1929, so public domain in the US."

War poetry and epic in there, which is where this project started:

| Work | Author | Translation |
|---|---|---|
| **de Bello Gothico** ✅ *built, 47 pp* | Claudian | Platnauer 1922 |
| de bello Gildonico · In Rufinum · de consulatu Stilichonis | Claudian | Platnauer 1922 |
| **Aeneid** | Virgil | 1910 |
| **Civil War** (*Pharsalia*) | Lucan | 1905 |
| Bellum Iugurthinum · Catilinae Coniuratio | Sallust | 1899 |
| Gallic War · Civil War | Caesar | 1872 / 1856 |
| De Bello Africo · De Bello Alexandrino | Pseudo-Caesar | 1955 |

Beyond war: Lucretius, Catullus, Horace, Ovid (6), Tacitus, Livy, Plautus (20),
Terence (6), Suetonius (12), Cicero (43).

One fix was needed to reach them. Perseus pairs a namespaced TEI P5 edition with
translations digitised decades earlier as un-namespaced **P4** — `TEIform=`
attributes and numbered `<div1>` rather than `<div type="textpart">`. Looking
only for namespaced TEI found every original and missed the translation beside
it, so Claudian failed with "TEI has no `<body>`" while both files sat there
intact.

---

## 🟡 Ready to build

| Work | Source | Note |
|---|---|---|
| **Jacob Balde** | CAMENA, 55 XML files | **CC BY-SA** — share-alike conflicts with a conventional all-rights-reserved book. A decision, not an obstacle. |

---

## 🔶 Blocked on sourcing

| Work | What exists | What's missing |
|---|---|---|
| **Germain de Brie, *Chordigerae navis conflagratio*** | Gallica [bpt6k715617](https://gallica.bnf.fr/ark:/12148/bpt6k715617) (1513), 45 page images and OCR in [`ocr-texts/`](ocr-texts/). **73.2% of words in the Latin vocabulary** | a Latinist's proofread. The correction pass cannot help: it fixed **0 tokens**, refusing 440 ambiguous and 305 candidate-less ones. A better recogniser or a human, not more passes |
| **Chastellain, *Le miroir de mort*** | PG 44162, Middle French | an English translation. Machine translation of Middle French fails badly — *"Il fault laisser voz haulx actours"* → *"It fails to leave voz haulx actours"* |
| **Pontano, *De bello Neapolitano*** | Google Books scans | a text. Also **prose history, not verse** — often miscatalogued |
| **Voltaire's other epics**, **Girart de Roussillon**, **Raoul de Cambrai**, **the Dietrich cycle**, **Willehalm** | — | nothing digitised in either language |

---

## ⛔ Blocked on copyright or language

| Work | Why |
|---|---|
| **Petrarch's *Africa*** (English) | Bergin & Wilson's 1977 Yale translation is in copyright, so the built edition faces machine English instead. |
| **Slovo o polku Igoreve** | No source in either language, and no Old East Slavic model. A modern Russian model on a 12th-century text is the *"Guns for man who is lame"* problem. |
| **Gottfried, *Tristan*** | Gutenberg's two "Tristan" entries are Bédier's modern French retelling via Belloc, not Gottfried. No MHG original. |

---

## Humanist Greek

Original Greek verse written in the Renaissance — a tradition almost entirely
unread, and a harder sourcing problem than the Latin, because the modern
scholarship that makes these texts accessible is itself in copyright.

| Work | Status |
|---|---|
| **Marcus Musurus, *Ode to Plato*** (1513) | **Built** — `config/musurus.yaml`, 15 pp. The Greek is the poem as Dijkstra & Hermans print it (Legrand's text; their translation and notes are in copyright and not taken). The English is Roscoe's 1805 rhymed rendering of all 154 lines, which is free rather than line for line, so it pairs by block. Too short to sell alone. |
| **Angelo Poliziano, *Liber epigrammatum graecorum*** (1498) | **Built from damaged Greek** — dual 43 pp. The 1553 Basel *Opera* (Getty copy, `gri_33125008502938`) was re-read with Tesseract's `grc` model, far better than the scan's text layer but still damaged; 411 lines survive, and the English is largely nonsense where the Greek is. See [WANTED.md](WANTED.md). |
| **Laurentius Rhodoman** (1545–1606) | **Built** — 23 Greek and 9 Latin works from [rhodomanologia.de](http://www.rhodomanologia.de/), one short book each, original text only (the editors' German translation is not taken). **The licence is unresolved**: working builds, not for sale until the editors are asked. English by `qwen3:14b` (Greek) and `nllb-latin` (Latin). |

Note the shape of the problem: for the Latin, Perseus supplies 1,900s
translations that are long out of copyright. Humanist Greek was never translated
in that era at all, so the English either does not exist or was made recently
enough to still be owned.

Greek OCR, if it comes to that: Kraken models from
[AjaxMultiCommentary](https://github.com/AjaxMultiCommentary/OCR-kraken-models)
are in `cache/kraken/` (5.2% CER on polytonic, better than Tesseract's `grc`),
but Kraken is not installed and brings its own torch stack.

---

## Notes on sources

**Three sites gate automated access** and were not worked around: Google Books
(terms prohibit it), Gallica's document endpoints and Cervantes Virtual (both
Cloudflare). Gallica's **IIIF image API is not gated**, which is how the de Brie
page images were fetched — but it rate-limits, and returns the 429 page *as a
JPEG*, so fetchers must check the magic bytes rather than the status code.

**Encoding and markup traps**, each of which silently produced a wrong text
before it was caught:

- zeno.org declares **iso-8859-1**; decoding as UTF-8 turns every umlaut into a
  replacement character and logs nothing.
- Wikisource serves **Parsoid markup** whose `data-mw` attributes carry the
  page's raw wikitext. A naive `<[^>]+>` stops at the first `>` inside an
  attribute and leaks the rest as apparent verse.
- Blank lines are **structure** in verse. A tag-stripper that drops them turns a
  canto into one 1,200-line stanza with nothing to pair.
- Gutenberg language tags mislead: Hugo's PG 12137 is tagged `en; fr` and is
  entirely French — the English is the editorial apparatus.

**Two indexes go silently empty.** `cache/pg_catalog.db` and `cache/perseus.db`
both needed rebuilding (`--update-catalog`, `--update-perseus`) and neither
announces that it is empty; search just returns nothing.

## OCR of early printed Latin

Stock `lat.traineddata` is trained on modern typesetting and produces noise on a
1513 page. **GT4HistOCR** (trained on 313,000 ground-truth lines of incunabula
and early modern print) reads the same line correctly, and transcribes the
abbreviations *as printed* — `ſ`, `ꝓ`, the nasal bar — so they can be expanded
deterministically afterwards rather than guessed at.

Do **not** use a vision LLM as the primary reader. Asked for the same line, one
produced `defendite armis` for *defendite ab oris*: a real Latin word that is
not on the page, and one no reader would catch. See
[arXiv 2605.27750](https://arxiv.org/html/2605.27750v1), which names the
failure. It is defensible as a second opinion flagging disagreements, never as
the source of the text.

For Greek, Kraken models from
[AjaxMultiCommentary](https://github.com/AjaxMultiCommentary/OCR-kraken-models)
are downloaded to `cache/kraken/` but unused — Kraken itself is not installed,
and it brings its own torch stack.

## OCR of Fraktur: re-read, not repaired

The Internet Archive's text layer for Haltaus's 1836 *Theuerdank*
(`bub_gb_UDhTAAAAcAAJ`) reads the Fraktur as Latin type: every long s is an `f`
and every `st` ligature a `ß`, so *schwert* is `fchwert` and *ist* is `iß`. A
repair has to guess, because `f` is also a real letter and `fein` is both
*sein* and *fein*. Re-reading the page images with Tesseract's `Fraktur` model
(`ocr_theuerdank.py`, 184 pages at 600 dpi in about three minutes) gets the long
s right outright, and keeps the two columns of each page apart under `--psm 3`.

What still goes wrong, and is not worth chasing: the model draws the
superscript *e* of an umlaut as `æ`/`œ` (normalised to `ä`/`ö`); about 17 pages
fuse one row of the left column with the same row of the right, which
misplaces a single verse; one damaged page near chapter XLV is scrambled; and
two chapter headings are lost, so those chapters run on into the one before.
Chapters are found from their rubric (a run of 45–55-character lines among
verse that is 32 wide), checked against the verse numbers starting again at 5.
