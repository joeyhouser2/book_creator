# OCR'd texts

These four files are tracked, unlike everything in `cache/`, because they are
not reproducible by running a script. Each took a page-image download, a
Tesseract model that is not installed by `requirements.txt`, and a per-page
pass that was tuned by hand. Losing `cache/` should not lose them.

Measured against the 392,757-form Latin vocabulary in
`cache/latin_vocab.tsv` (exported from the `latin` repo), folding u/v and i/j
the way `ocr_correct.fold` does:

| File | Source | In-vocabulary |
|---|---|---|
| `chordigerae_1513_tesseract_lat.txt` | Gallica [bpt6k715617](https://gallica.bnf.fr/ark:/12148/bpt6k715617), stock `lat` | 56.6% |
| `chordigerae_1513_gt4histocr.txt` | same images, `GT4HistOCR_2000000` | **73.2%** |
| `ocland_anglorum_praelia_1580_raw.txt` | Philological Museum transcription | 82.1% |
| `ocland_anglorum_praelia_1580_corrected.txt` | the above, through `ocr_correct.repair` | **88.6%** |

Two things those numbers say.

**GT4HistOCR is worth the trouble on a 1513 page**: 56.6% → 73.2% on identical
images, for a `--tessdata-dir` and a model name.

**The correction pass helps Ocland and does nothing for de Brie.** On Ocland it
fixed 1,217 tokens, +6.5 points. On de Brie it fixed **zero** — 440 tokens were
ambiguous and 305 had no candidate at all, so `correct()` refused every one of
them, which is the behaviour it should have. Edit-distance correction needs the
recogniser to be nearly right; on the de Brie page it is not close enough for
one or two edits to reach a real word. That text needs a better recogniser or a
Latinist, not more post-processing.

The page images themselves stay in `cache/gallica/` (21 MB, 45 JPEGs of
bpt6k715617 — 23 at default scale, 22 at full). Re-downloadable from Gallica's
IIIF endpoint, which is not bot-checked but does rate-limit: it returns the
`429 Trop de requêtes` page **with an image content-type**, so a fetcher must
check for the `\xff\xd8\xff` JPEG magic bytes rather than trusting the status.
