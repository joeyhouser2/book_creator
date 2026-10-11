# What to look for by hand

Most of what this file once asked for has been found and built; see
[SOURCES.md](SOURCES.md). What is left is blocked on something a person with a
browser or a reading knowledge can do and a script cannot: pass a bot check,
proofread a scan, read a Greek page, decide between two editions.

Sorted by what it buys.

---

## 1. Proofreading, in order of how much each would improve a built book

The built editions of **Kudrun, Mirèio, the Cid, Hesperis and Ocland** set
original-language text that nobody has proofread; their copyright pages say so.
A reader with the language would raise their quality more than any further
script.

- **Kudrun** — 180 of 1,705 strophes print as `[strophe lost to OCR]`. The numbers
  are known, so each is a one-strophe job against Bartsch's printed page
  (archive.org `kudrun00bartgoog`, or Martin's 1883 edition `kudrun01martgoog`).
  The strophe near #800 also reads as a fragment.
- **Cid** — the Spanish is Pidal's critical text, 3,899 verses against the poem's
  3,730, so about 170 lines of marginal note or apparatus survive the line-shape
  filter. Its laisses are cut by measuring assonance (161) rather than numbered
  (Rose has 149), so the pairing is by meaning. A numbered Old Spanish edition
  would make it exact: Cervantes Virtual has one behind a Cloudflare check you can
  pass in a browser.
- **Mirèio** — a handful of French notes leak into the Provençal, and a dropped
  line shifts every stanza after it.
- **Hesperis** — the Google text layer and an independent Tesseract read agree on
  all but eight words, so this is sound; what remains is a Latinist's pass.
  Note that `ocr_correct` must **not** be run on it (see the last section).

---

## 2. Basinio — the lyric poems

All four poems in Drudi's volume are built (*Hesperis*, *Astronomicon*,
*Meleagris*, *Argonauticon*). The *Argonauticon* is complete as it stands: the
1794 commentary says it "was not finished, owing to the author's death", and the
text breaks off at Medea falling in love. The other 1794 volumes on archive.org
(`bub_gb_41MxnrlFrlAC`, `bub_gb_ALAHuNBQHwoC` and their twins) are *Tomus II*,
biography and documents, with no verse. What remains is Ferri's 1925 edition of
the *Isottaeus*, *Cyris* and minor poems (HathiTrust `mdp.39015013279883`, full view
in the US; the same text is on poetiditalia.it). No English exists for any.

---

## 3. Ocland, *Anglorum Praelia* — a cleaner scan of Sharrock

The English is now built from the EEBO-TCP transcription, with Latin that has no
English beside it machine translated and marked †. A cleaner scan of STC 18777
than the EEBO microfilm — the Bodleian, Huntington or Folger may hold one — would
close the gaps, and the dagger passages would become a human translation.

---

## 4. Poliziano's Greek epigrams — read the Greek

The epigrams are built, but the Greek is badly damaged and **the English is largely
nonsense where it is**. The Getty copy of the 1553 Basel *Opera*
(`gri_33125008502938`, saved as `cache/poliziano/gri_1553.pdf`) was re-read with
Tesseract's `grc` model, far better than the scan's own text layer, but accents,
breathings and the printer's ligatures are still misread, and only 411 lines with
at least two common Greek words survive the filter, from a longer section. Someone
who reads Greek could correct them in `input/poliziano_epigrammata_grc.txt`, and the
book would then translate properly. The epigrams are printed with Latin versions of
their own beside them (Poliziano wrote both); the Latin is not yet used.

---

## 5. Rhodoman — the licence

All 23 Greek works and 9 Latin works from rhodomanologia.de are built (one short
book each), from the site's HTML (`cache/rhodoman/html/`; the site's EPUB leaves
out several works, among them the *Arion*). Only the original text was taken: the
editors' German translation and apparatus were left out. **Neither the site nor the
EPUB metadata states a licence**, so the books are for working from, not selling.
Email the editors (Thomas Gärtner, Stefan Weise, via
[rhodomanologia.de](http://www.rhodomanologia.de/)) first. *Palaestina* is **not**
on the site, despite being the work Rhodoman is usually named for.

---

## 6. A public-domain English for the machine-translated epics

Both are built with a machine English, which is disclosed. A public-domain verse
translation, if one surfaces, would replace it.

- **Franciade** — a 19th-century English verse translation. None found; Usher's
  (2010) is in copyright.
- **La Araucana** — the same. Lancaster & Manchester's (1945) is in copyright.
  Hayley's 1782 *Essay on Epic Poetry* carries excerpts, which is not enough for
  a facing text. Walter Owen's *Araucaniad* (Vanderbilt, 1945) is the first complete
  English verse and is listed by HathiTrust as in copyright (search-only), so it
  cannot be used either. Sir George Carew's partial Elizabethan version survives
  only in manuscript at Lambeth Palace.

The Araucana is built in full: part 1 from the 1911 edition (cantos 1–15) and parts
2–3 from the 1803 Sancha edition's second volume (cantos 16–37), whose old spelling
a translation model reads less well.

---

## 7. Musurus, *Ode to Plato* — a companion text, if wanted

Built, with Roscoe's 1805 English, at 15 pages. Page count is not a concern for now;
if it ever is, it wants company: the other Aldine prefaces, or Dijkstra & Hermans'
commentary if their licence allows (open access to read, but in copyright).

---

## A warning about the correction pass

Do not assume post-processing will rescue a bad scan, and do not assume it is safe
on a good one.

| | before | after |
|---|---|---|
| Ocland, Philological Museum transcription | 82.1% | **88.6%** (1,217 tokens fixed) |
| de Brie, Gallica 1513 via GT4HistOCR | 73.2% | **73.2%** (0 tokens fixed) |

On de Brie the pass fixed **nothing**: 440 tokens had two or more equally near
candidates and 305 had none at all, so `correct()` refused every one. That
refusal is correct behaviour, but it means edit-distance correction only works
when the recogniser is already nearly right.

On **Hesperis** it did something worse. The text was already 92.4% in-vocabulary
and the pass raised that to 96.3% — by turning real Neo-Latin forms into
classical ones: *Cyllam* → *cellam*, *Sismundumque* → *inmundumque*,
*Pandulphius* → *pandulphus*, *hetruscos* → *hetruscis*, *jugosum* → *rugosum*.
A higher in-vocabulary score there means a *less* faithful text. The vocabulary is
classical Latin; Neo-Latin proper names and coinages are not in it. For such texts
the safer check is a **second, independent OCR**, accepting a change only where the
two disagree and the vocabulary decides.

---

## Not worth looking for

**Chastellain, *Le miroir de mort*** — no English translation exists in any era,
and Middle French defeats machine translation badly enough to be unpublishable:
*"Il fault laisser voz haulx actours"* came back as *"It fails to leave voz haulx
actours"*. This needs a translator, not a search.

**Pontano, *De bello Neapolitano*** — the 1769 Naples edition is on Google Books,
but it is **prose history, not verse** (it is routinely miscatalogued as the
poem) and no English translation exists. The three Pontano *poems* already in
hand are a better use of the same effort.

**Slovo o polku Igoreve** — no source in either language and no Old East Slavic
model. A modern Russian model on a 12th-century text reproduces the *"Guns for
man who is lame"* failure that made us abandon multi-source Opus-MT for Latin.

**Gottfried's *Tristan*** — Gutenberg's two "Tristan" entries are Bédier's modern
French retelling via Belloc, not Gottfried. No Middle High German original
anywhere I looked.

**Girart de Roussillon, Raoul de Cambrai, the Dietrich cycle, Willehalm** —
checked against the 79,288-book Gutenberg catalogue and the usual
German and French archives. Nothing in either language. These are genuinely
undigitised rather than merely hard to reach.
