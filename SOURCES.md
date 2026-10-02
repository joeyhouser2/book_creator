# Source catalogue

Every work considered for a dual-language edition, what it is, and where it
stands. The recurring lesson: the code was rarely the obstacle. Finding a text
that is *public domain*, *digitised*, and *not behind a bot check* was.

Texts that can be fetched automatically live in [`fetch_sources.py`](fetch_sources.py);
the files themselves are gitignored, since they are re-fetchable.

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
| **La Légende des siècles** | dual 411 pp · English-only 257 pp | machine |
| **La Henriade** | dual 312 pp | machine |
| **Der Messias** | dual 2 vols (593 + 773 pp) | machine |
| **Africa** | dual 386 pp | machine, via the `latin` repo's `nllb-latin` |

The four with human translations carry no disclosure and are sellable. The four
machine-translated ones say so on the copyright page.

Camões and Tasso both wrote in ottava rima and both found translators who kept
it, so those pair **stanza for stanza** — 9 of 10 Lusíadas cantos match exactly,
18 of 20 Tasso cantos. Maldon pairs **line for line**, because Garnett's is a
scholarly crib rather than a verse rendering.

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
| **Pontano, *Urania*** | poetiditalia, `PONTANO\|uran` | 5 books, 4,842 lines, verified |
| **Pontano, *Parthenopeus*** | poetiditalia, `PONTANO\|part` | 838 lines in book 1 |
| **Pontano, *De hortis Hesperidum*** | poetiditalia, `PONTANO\|hesp` | 486 lines |
| **Wolfram, *Parzival*** | Bibliotheca Augustana (fetched) | 24,812 MHG lines in hand; Weston's English is PG 47297/47298 but its divisions need the same assembly Burton's Lusiads needed |
| **Jacob Balde** | CAMENA, 55 XML files | **CC BY-SA** — share-alike conflicts with a conventional all-rights-reserved book. A decision, not an obstacle. |

---

## 🔶 Blocked on sourcing

| Work | What exists | What's missing |
|---|---|---|
| **Germain de Brie, *Chordigerae navis conflagratio*** | Gallica [bpt6k715617](https://gallica.bnf.fr/ark:/12148/bpt6k715617) (1513) and [bpt6k9415155x](https://gallica.bnf.fr/ark:/12148/bpt6k9415155x) (1514). OCR'd: 602 lines, **71% of words in the Latin vocabulary** | a Latinist's proofread. GT4HistOCR + the correction pass produce a readable draft, not an edition |
| **Cantar de Mio Cid** | Rose's *The Lay of the Cid* (PG 6088), 152 numbered laisses — a ready human translation | the Spanish. Cervantes Virtual is Cloudflare-blocked; es.wikisource has Sánchez's apparatus but not the verse; archive.org's search API returns 400 |
| **Kudrun** | Nichols' English (PG 46109) | the Middle High German. Not on Gutenberg, Augustana or zeno |
| **Mistral, *Mirèio*** | Preston's English (PG 56008) | the Occitan |
| **Chastellain, *Le miroir de mort*** | PG 44162, Middle French | an English translation. Machine translation of Middle French fails badly — *"Il fault laisser voz haulx actours"* → *"It fails to leave voz haulx actours"* |
| **Pontano, *De bello Neapolitano*** | Google Books scans | a text. Also **prose history, not verse** — often miscatalogued |
| **La Araucana**, **Ronsard *La Franciade***, **Voltaire's other epics**, **Theuerdank**, **Girart de Roussillon**, **Raoul de Cambrai**, **the Dietrich cycle**, **Willehalm** | — | nothing digitised in either language |

---

## ⛔ Blocked on copyright or language

| Work | Why |
|---|---|
| **Ocland, *Anglorum Praelia*** | The English at the Philological Museum is **Sutton's own**, and so in copyright. His introduction says why: he meant to use Sharrock's 1585 translation "but the copy… in the Early English Books microfilm series… is of such poor quality (many pages are out of order or missing altogether) that this proved impossible". So Sharrock exists but is damaged in the only accessible scan. |
| **Ocland, *Eirenarchia* / *Elizabetha*** | Ocland's *other* poem, same site — and for this one Sutton **did** use Sharrock's 1585 translation, which is public domain. Worth checking: it may be buildable where *Anglorum Praelia* is not. |
| **Basinio da Parma, *Hesperis*** | Gallica has all 13 books — as **BnF Arsenal Ms-630**, parchment, *écriture italienne du XVe siècle*. A **manuscript**, so print OCR cannot read it; it needs HTR. This is also why the Ludwig Boltzmann digital edition stalled at 2 of 13 books and was never published. |
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
| **Marcus Musurus, *Ode to Plato*** (1513) | The Greek is public domain — it was printed as the dedicatory poem to the Aldine *editio princeps* of Plato. The only modern English is **Dijkstra & Hermans, *Akroterion* 60 (2015)**, open access to read but **in copyright**; their own article notes it is the first full translation since **Roscoe (1805)**, which would be PD if a copy can be found. So: original available, translation blocked unless Roscoe surfaces. |
| **Angelo Poliziano, *Liber epigrammatum graecorum*** (1498) | The first book of original ancient-style Greek verse printed in the West. Not yet checked for a digital text or a public-domain translation. |
| **Laurentius Rhodoman** (1545–1606) | Greek hexameter epics — *Palaestina*, the Arion poem. An active digital edition project at **rhodomanologia.de**; its licence and completeness are unchecked. Rhodoman is the one case here where a modern project might make the Greek readily fetchable. |

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
