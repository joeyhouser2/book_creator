# What to look for by hand

Everything here is blocked on something a person with a browser can do and a
script cannot: pass a Cloudflare or ALTCHA check, click Google Books' download
button, or exercise judgement about which of six editions of a poem has the
division numbering that matches a translation we already hold.

Sorted by what it buys. Each entry says **what to fetch**, **where**, and **what
to check before bothering** — because for most of these the original is the easy
half and the *public-domain English* is the scarce one. That is the real shape of
this problem, and I had it wrong in two places until today.

---

## 1. Basinio, *Hesperis* — a printed edition exists, so no HTR is needed

This is the big one, and it overturns the plan in
`docs/roadmap-basinio-hesperis-htr.md` in the latin repo. I built that around BnF
Arsenal Ms-630, a 15th-century parchment manuscript needing handwritten-text
recognition. I had not looked for a **print** edition.

There is one, and it is the edition modern scholarship actually cites:

> **Basinii Parmensis poetae opera praestantiora**, vol. 1, ed. Lorenzo Drudi
> (with Francesco Gaetano Battaglini), Rimini, *ex typographia Albertiniana*,
> 1794 — *Hesperis* at pp. 1–288, followed by the *Astronomicon*, *Meleagris*
> and *Argonauticon*.

1794, so unambiguously public domain, and print — which `GT4HistOCR` reads well.
Christian Peters' German translation works from this same Drudi text, so it is
not a second-rate witness.

**Fetch:** Google Books [`id=AuzlAAAAMAAJ`](https://books.google.com/books/about/Basini_Parmensis_poetae_opera_praestanti.html?id=AuzlAAAAMAAJ),
which is **full view with PDF and EPUB download**. Use the download button; the
terms-of-service objection is to scripted access, not to you clicking it.

**Check before bothering:** that the download is the real scan rather than a
metadata-only record, and that pp. 1–288 are present and legible.

**Then:** this needs no new recogniser and no Transkribus credits — it enters the
ordinary OCR path. Workstreams A, B and D of that roadmap can be dropped. Keep
workstream C; it is the same correction pass, and see the warning about it below.

**Also look for** a copy on [MDZ](https://www.digitale-sammlungen.de/) or
archive.org. Either would let a script do it, and neither is bot-checked.

---

## 2. Ocland, *Anglorum Praelia* — Sharrock's 1585 English is public domain after all

Also a correction, and already fetched, so no action needed from you. I had this
filed under "blocked on copyright" because the Philological Museum's English is
Dana Sutton's own, and Sutton's introduction says he could not use Sharrock's
1585 translation because the Early English Books microfilm was too damaged.

Sutton was describing the *microfilm*. The **Text Creation Partnership keyed a
transcription from it** and released it to the public domain on 1 January 2015:

> `A08452` — *The valiant actes and victorious battailes of the English nation*,
> trans. John Sharrock, London: Robert Walde-grave, 1585. STC 18777.
> [raw TEI, 592 KB](https://raw.githubusercontent.com/textcreationpartnership/A08452/master/A08452.xml)

But the damage Sutton complained about is visible in the transcription, and that
is a decision to take before building anything:

| | |
|---|---|
| Verse lines, the two books of *Anglorum Praelia* | 1,695 + 1,298 = **2,993** |
| A third division, 823 lines | *Elizabetha* — Ocland's **other** poem |
| Lines containing an illegible gap | **516 (13.0%)** |
| `1+ letters` illegible | 748 |
| `1 word` illegible | 232 |
| **`2+ pages` missing outright** | **5 within the two books** (9 in the file) |

So 87% of lines are clean and five holes of at least two pages each are not.
Against the Latin's 4,332 lines the counts do not pair off either — Sharrock
translated into English meeter, not line for line — so this needs real alignment
rather than line-matching.

**A genuine trade, and your call:** a *human* translation with five visible
lacunae and 516 partly-gapped lines, or the *machine* translation that is
complete and carries a disclosure. I would not quietly fill the gaps with machine
output; a reader cannot tell which is which, and that is the one thing this
project has consistently refused to do.

**Worth looking for either way:** a cleaner scan of STC 18777 than the EEBO
microfilm — the Bodleian, Huntington or Folger may hold a better copy. That would
close the gaps and make this a clean human-translation edition.

**Bonus:** *Elizabetha* is in the same file, and for that poem Sutton *did* use
Sharrock, which is why it was already flagged as possibly buildable. 823 lines,
and it stands on its own.

---

## 3. Musurus, *Ode to Plato* — Roscoe 1805 would unblock the English

The Greek is public domain and in hand. Dijkstra & Hermans' 2015 *Akroterion*
translation is in copyright, but their own article says theirs is the first
complete English version **since Roscoe in 1805** — and Roscoe is long out of
copyright.

**Fetch:** William Roscoe, *The Life and Pontificate of Leo the Tenth*, London:
T. Cadell & W. Davies, 1805, 4 vols. The ode is the dedicatory poem to the 1513
Aldine Plato, so look in **the volume covering 1513** — likely vol. 2 or 3, and
worth checking the index under "Musurus" rather than guessing.

**Where:** archive.org and Google Books both have the 1805 edition and later
reprints. Prefer 1805: a Victorian reprint may drop the appendices, and a
translated poem in an appendix is exactly the sort of thing that gets cut.

**Check before bothering:** that Roscoe gives the **whole** ode rather than a
paraphrase or a few quoted lines. Dijkstra & Hermans calling theirs the first
full translation since Roscoe implies Roscoe's was full — but verify, because
forty lines of a long poem is no use as a facing text.

---

## 4. Cantar de Mio Cid — need the Old Spanish, with laisse numbers

Rose's English (PG 6088) is in hand, in **152 numbered laisses**. That numbering
is the alignment key, so the edition has to carry it.

**Fetch, best first:**

1. Ramón Menéndez Pidal, *Cantar de Mio Cid: texto, gramática y vocabulario*,
   Madrid, 1908–11, 3 vols — **vol. 3 is the text**. On archive.org; take the
   `djvu.txt`.
2. Tomás Antonio Sánchez, *Colección de poesías castellanas anteriores al siglo
   XV*, vol. 1 (1779), which contains the *Poema del Cid*. Google Books, full
   view.

**Where it failed automatically:** Biblioteca Virtual Miguel de Cervantes is
Cloudflare-gated and you can reach it in a browser. es.wikisource has Sánchez's
apparatus but not the verse. archive.org's search API returns 400 for this one.

**Check before bothering:** that laisses are numbered, and that it is the Old
Spanish rather than a modernised *castellano actual* rendering — those are
everywhere and look superficially right.

---

## 5. Kudrun — need the Middle High German, in 32 Âventiuren

Nichols' English (PG 46109) is in hand.

**Fetch:** Karl Bartsch, *Kudrun*, Leipzig, 1865 (*Deutsche Classiker des
Mittelalters*), or Ernst Martin, *Kudrun*, Halle, 1872/1883. Both public domain.

**Where:** [MDZ](https://www.digitale-sammlungen.de/) first — not bot-checked,
serves OCR full text, and the best German source this project has found. Then
archive.org. Not on Gutenberg, Bibliotheca Augustana or zeno.org, all checked.

**Check before bothering:** that the Âventiuren are numbered. The segmenter
already treats *âventiure*, *abenteuer* and *gesang* as division keywords, so
numbered divisions will be picked up with no new code.

---

## 6. Mistral, *Mirèio* — need the Provençal, in 12 cantos

Preston's English (PG 56008) is in hand, in 12 cantos, matching the poem's own
structure — so this should align cleanly once the Occitan exists.

**Fetch:** the 1859 Avignon first edition, or any of the bilingual editions —
Mistral printed his own facing French translation, which is a useful check even
though the Occitan is what we want.

**Where:** [Occitanica](https://occitanica.eu/) (CIRDOC's Occitan digital
library) first, as it is purpose-built and likely to have clean text. Then
Gallica, where a `bpt6k` ark is a printed book and **does** have an OCR layer
behind the bot check you can pass in a browser.

**Check before bothering:** that you have the Provençal and not only the French.
Bilingual editions are the norm for Mistral and it is easy to come away with the
wrong column.

---

## 7. Poliziano and Rhodoman — Greek obtainable, English probably not

The same shape as Musurus, and probably without Musurus' luck.

**Poliziano, *Liber epigrammatum graecorum*** (1498) — the Greek is in *Omnia
opera Angeli Politiani* (Aldus, Venice 1498) and in the Basel 1553 *Opera omnia*.
The only scan I found OCR'd with **zero Greek characters**, because the
recogniser was never given a Greek model. Pontani's modern edition is in
copyright. Look for any scan with a real Greek text layer, or a 19th-century
edition with a facing Latin version, which would at least be translatable.

**Rhodoman** — [rhodomanologia.de](https://rhodomanologia.de/) serves **64,321
Greek characters** on the *Arion* page alone, and I can fetch it today. What I
cannot determine is the **licence**. Look for an imprint or *Impressum*, or email
the project. Note that *Palaestina* is **not** in that edition, despite being the
work Rhodoman is usually named for.

---

## 8. Ronsard's *Franciade* and Ercilla's *La Araucana* — I was wrong about these

Both were filed as "nothing digitised in either language". That is false for the
originals:

- **Franciade** — *Oeuvres complètes de P. de Ronsard* (1858) has the four books
  with full text on archive.org (`oeuvrescompltes00ronsgoog`), and the 1572 first
  edition is there as `ronsard0016unse`.
- **La Araucana** — several full-text Spanish editions on archive.org, among them
  `laaraucana01erci` and `laaraucanapoema01erciuoft`.

What is actually missing for both is a **public-domain English translation**.
Usher's *Franciade* (2010) and Lancaster & Manchester's *Araucana* (1945) are
both in copyright. So the thing to look for is a **19th-century** English verse
translation of either; Hayley's 1782 *Essay on Epic Poetry* carries *Araucana*
excerpts, which is not enough for a facing text but shows the tradition existed.
If nothing surfaces, these become machine-translation builds — and for that the
originals are already fetchable without you doing anything.

---

## A warning about the correction pass

Do not assume post-processing will rescue a bad scan. Re-measured today against
the folded 392,757-form vocabulary:

| | before | after |
|---|---|---|
| Ocland, Philological Museum transcription | 82.1% | **88.6%** (1,217 tokens fixed) |
| de Brie, Gallica 1513 via GT4HistOCR | 73.2% | **73.2%** (0 tokens fixed) |

On de Brie the pass fixed **nothing**: 440 tokens had two or more equally near
candidates and 305 had none at all, so `correct()` refused every one. That
refusal is correct behaviour — but it means edit-distance correction only works
when the recogniser is already nearly right. When a page is badly read, the
answer is a better recogniser or a Latinist, not more passes.

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

**Theuerdank, Girart de Roussillon, Raoul de Cambrai, the Dietrich cycle,
Willehalm** — checked against the 79,288-book Gutenberg catalogue and the usual
German and French archives. Nothing in either language. These are genuinely
undigitised rather than merely hard to reach.
