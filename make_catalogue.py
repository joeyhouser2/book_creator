"""Write CATALOGUE.md from what is actually in output/, plus config/.

Page counts are read out of the PDFs, so the catalogue cannot drift from the
builds the way a hand-kept list does -- and the KDP page check at the end runs
against the real count rather than a remembered one.

The per-book summaries and the original-work dates live in DATA and TITLES
below, because nothing in a build records them: a config knows its own blurb
and its translator, but not what century the poem is from. Add a book to DATA
when you build one; anything in output/ that is not accounted for here is
reported as uncovered rather than silently dropped.

    python make_catalogue.py
"""
import glob
import pathlib
import re

import yaml

try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader

REPO = pathlib.Path(__file__).resolve().parent
OUT = REPO / "output"

# slug -> (author, year, translator, summary). Year is the ORIGINAL work's.
# "machine" as translator means an NLLB/Opus-MT rendering made for the edition.
DATA = {
    # ---- human translation, paired with a published English ----
    "parzival": ("Wolfram von Eschenbach", "c. 1200–10", "Jessie L. Weston, 1894",
                 "The Grail romance: Parzival's long education from naive boy to Grail king, the fullest Arthurian poem in German."),
    "kudrun": ("Anonymous", "c. 1230–40", "Arthur Nichols, 1889",
               "A Hegelingen princess abducted and held for years, who endures rather than avenges — the Nibelungenlied's answer poem, and far gentler."),
    "das-nibelungenlied": ("Anonymous", "c. 1200", "George Henry Needler, 1904",
                           "Siegfried's murder and Kriemhild's annihilating revenge: the central German heroic epic."),
    "os-lusiadas": ("Luís de Camões", "1572", "Richard Francis Burton, 1880",
                    "Vasco da Gama's voyage to India told as national epic, with the gods of Olympus taking sides."),
    "gerusalemme-liberata-volume-1": ("Torquato Tasso", "1581", "Edward Fairfax, 1600",
                                      "The First Crusade's siege of Jerusalem, cantos 1–10, in Fairfax's Elizabethan ottava rima."),
    "gerusalemme-liberata-volume-2": ("Torquato Tasso", "1581", "Edward Fairfax, 1600",
                                      "Cantos 11–20: Armida's enchantments, Tancred and Clorinda, and the city's fall."),
    "mireio": ("Frédéric Mistral", "1859", "Harriet Waters Preston, 1872",
               "A farm girl loves a basket-weaver beneath her station and dies on pilgrimage — the poem that won Provençal a Nobel Prize."),
    "anglorum-praelia": ("Christopher Ocland", "1580", "John Sharrock, 1585",
                         "English victories in Latin hexameters from Edward III to Mary I, a Tudor schoolroom set text."),
    "cantar-de-mio-cid": ("Anonymous", "c. 1200", "Rose, 1919",
                          "The Cid exiled by his king, winning Valencia and his honour back: Spain's national epic."),
    "the-battle-of-maldon": ("Anonymous", "c. 1000", "James M. Garnett",
                             "The Old English fragment on Byrhtnoth's defeat by vikings in 991, and the most famous bad decision in the language."),
    "ode-to-plato": ("Marcus Musurus", "1513", "William Roscoe, 1805",
                     "A Homeric ode asking Plato to descend and present his own works to Leo X, prefixed to the Aldine first edition — the high point of Renaissance Greek verse."),
    "life-of-the-black-prince": ("Chandos Herald", "c. 1385", "Pope & Lodge, 1910",
                                 "A verse life of Edward of Woodstock by a herald who served in his household, in Anglo-Norman."),
    "anabasis": ("Xenophon", "c. 370 BC", "unnamed on the copyright page",
                 "Ten thousand Greek mercenaries stranded in Persia march home — the original account of a fighting retreat."),
    "de-bello-gothico": ("Claudian", "402", "Maurice Platnauer, 1922",
                         "Stilicho's defeat of Alaric at Pollentia, written within months of the battle."),
    "de-bello-gildonico": ("Claudian", "398", "Maurice Platnauer, 1922",
                           "The suppression of Gildo's African revolt, which had threatened Rome's grain supply."),
    "de-consulatu-stilichonis": ("Claudian", "400", "Maurice Platnauer, 1922",
                                 "Three books of panegyric on Stilicho's consulship, the fullest portrait of the general who held the West together."),
    "in-rufinum": ("Claudian", "396–97", "Maurice Platnauer, 1922",
                   "An invective against the eastern minister Rufinus, with a prologue comparing him to a monster."),
    "in-eutropium": ("Claudian", "399", "Maurice Platnauer, 1922",
                     "A savage attack on Eutropius, the eunuch who became consul — Roman political abuse at its most unrestrained."),
    "le-rouge-et-le-noir": ("Stendhal", "1830", "Horace B. Samuel, 1916",
                            "A carpenter's son climbs through seminary and salon by calculation and sincerity in turn, and is destroyed by both."),
    "notre-dame-de-paris": ("Victor Hugo", "1831", "Isabel F. Hapgood, 1888",
                            "Quasimodo, Esmeralda and Frollo around the cathedral Hugo wrote the book to save."),
    "le-p-re-goriot": ("Honoré de Balzac", "1835", "Ellen Marriage, 1896",
                       "A retired merchant ruins himself for two daughters who will not be seen with him."),
    "eug-nie-grandet": ("Honoré de Balzac", "1833", "Katharine Prescott Wormeley",
                        "A miser's daughter in provincial Saumur, whose one act of generosity costs her everything."),
    "buch-der-lieder": ("Heinrich Heine", "1827", "Emma Lazarus, 1887",
                        "The songbook that became the most-set body of lyric in European music. A selection: ~125 of 227 poems have a Lazarus version."),
    "les-fleurs-du-mal": ("Charles Baudelaire", "1857", "Cyril Scott, 1909",
                          "The founding book of Symbolism, prosecuted for obscenity the year it appeared. 55 of 123 poems."),
    "the-gallic-war": ("Julius Caesar", "c. 51 BC", "McDevitte & Bohn, 1869",
                       "Caesar's own account of the conquest of Gaul, Book I."),
    # ---- machine translation, disclosed on the copyright page ----
    "hesperis": ("Basinio da Parma", "c. 1455", "machine",
                 "Sigismondo Malatesta's wars in 13 Virgilian books: the first large-scale Neo-Latin epic ever finished, never before in English."),
    "meleagris": ("Basinio da Parma", "c. 1450s", "machine",
                  "The Calydonian boar hunt in three books."),
    "argonauticon": ("Basinio da Parma", "c. 1450s", "machine",
                     "An unfinished Latin epic of Jason and the Argonauts."),
    "astronomicon": ("Basinio da Parma", "c. 1450s", "machine",
                     "A didactic poem on the constellations and planets, after Manilius."),
    "africa": ("Francesco Petrarca", "1338–43", "machine",
               "Scipio against Hannibal, the Latin epic Petrarch was crowned laureate for and never finished."),
    "urania": ("Giovanni Pontano", "pub. 1505", "machine",
               "Five books on the stars and their influence, the most ambitious Latin astronomical poem of the Renaissance."),
    "parthenopeus": ("Giovanni Pontano", "c. 1457", "machine",
                     "Youthful love elegies to his Naples, in the manner of Ovid and Propertius."),
    "de-hortis-hesperidum": ("Giovanni Pontano", "1501", "machine",
                             "On growing citrus: a Virgilian georgic for the orange groves of Campania."),
    "greek-epigrams": ("Angelo Poliziano", "1470s", "machine",
                       "The first book of original ancient-style Greek verse composed in the West."),
    "la-araucana-part-one": ("Alonso de Ercilla", "1569", "machine",
                             "Cantos 1–15 of the Araucanian war, written by a soldier who fought in it and admired the enemy."),
    "la-araucana-parts-two-and-three": ("Alonso de Ercilla", "1578, 1589", "machine",
                                        "Cantos 16–37, including Caupolicán's death and Ercilla's own disillusion."),
    "la-franciade": ("Pierre de Ronsard", "1572", "machine",
                     "France descended from a surviving son of Hector: the national epic Ronsard abandoned after four books."),
    "la-henriade": ("Voltaire", "1723", "machine",
                    "Henri IV ending the wars of religion, Voltaire's bid to give France its Aeneid."),
    "der-messias-band-1": ("Friedrich Gottlieb Klopstock", "1748–73", "machine",
                           "Cantos 1–10 of the German Paradise Lost, in hexameters that remade German as a poetic language."),
    "der-messias-band-2": ("Friedrich Gottlieb Klopstock", "1748–73", "machine",
                           "Cantos 11–20, through the passion to the resurrection."),
    "la-legende-des-siecles": ("Victor Hugo", "1859–83", "machine",
                               "History as a succession of visions from Eve to the Day of Judgement."),
    "de-modo-usurarum-liber": ("Claudius Salmasius", "1588–1653", "machine",
                               "A vast humanist treatise arguing that lending at interest is lawful — Salmasius against a thousand years of canon law. English only."),
}

# English-only companion editions
EN_ONLY = {
    "das-nibelungenlied-en": "das-nibelungenlied",
    "os-lusiadas-en": "os-lusiadas",
    "gerusalemme-liberata-en": "gerusalemme-liberata-volume-1",
    "la-legende-des-siecles-en": "la-legende-des-siecles",
}

FACSIMILE = {
    "warsofmarlboroug01tayl-facsimile": ("Frank Taylor", "1921",
                                         "Volume I of the Oxford study of Marlborough's campaigns, reproduced as page images."),
    "warsofmarlboroug02tayl-facsimile": ("Frank Taylor", "1921",
                                         "Volume II, same edition."),
}

SCRAPS = {
    "caesar-b1-la": "Gallic War Book I, untitled run — superseded by `the-gallic-war`.",
    "the-gallic-war-book-i": "Same text, titled properly. One of four Gallic War iterations.",
    "gw-book-i-via-ui": "The same again, built through the web UI to check that path.",
    "the-gallic-wars": "**Broken**: pulled the wrong Gutenberg text — page 3 is Ernest Bramah's *Kai Lung's Golden Hours*.",
    "carmina-rhytmica": "Alcuin, 3 pages. A fragment, not a book.",
    "life-of-the-black-prince-v2": "Second layout pass of the Black Prince; same 197 pages.",
    "enc-test": "encoding probe", "feathers-test": "ornament probe",
    "gallic-war": "2-page stub", "gallic-war-embed": "font-embedding probe",
    "gallic-war-embed2": "font-embedding probe", "gc-check": "2-page stub",
    "greek-test": "Greek font probe", "split-gc": "division-splitting probe",
    "t": "scratch", "t2": "scratch", "toy": "scratch", "toy2": "scratch",
    "ui-test": "web UI probe", "the-gallic-war-test": "2-page stub",
    "im-fell-english-sample": "typeface sample",
    "marl-cover-band": "cover-style probe", "marl-cover-plate": "cover-style probe",
    "marl-cover-typographic": "cover-style probe",
    "v2-check": "570-page facsimile re-run, 146 MB",
}


def pages(slug):
    try:
        return len(PdfReader(str(OUT / f"{slug}.pdf")).pages)
    except Exception:
        return 0


def has_epub(slug):
    return (OUT / f"{slug}.epub").exists()


def load_configs():
    """slug -> (author, blurb, translator, note, machine) straight from config/."""
    got = {}
    for f in sorted(glob.glob(str(REPO / "config" / "*.yaml"))):
        if "example" in f:
            continue
        doc = yaml.safe_load(open(f, encoding="utf-8")) or {}
        for b in (doc.get("books") or []):
            if not isinstance(b, dict) or not b.get("title"):
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", b["title"].lower()).strip("-")
            got[slug] = {
                "title": b["title"], "author": b.get("author"),
                "blurb": (b.get("cover") or {}).get("blurb") or "",
                "translator": (b.get("copyright") or {}).get("translator"),
                "note": b.get("translation_source_note"),
                "machine": bool(b.get("translate")),
                "src": b.get("src_lang"),
            }
    return got


CFG = load_configs()
RHOD_LIFE = "1546–1606"

# Where slugifying the title is not reversible (accents, commas, articles), the
# real title. Everything else falls back to the config title or the slug.
TITLES = {
    "os-lusiadas": "Os Lusíadas",
    "os-lusiadas-en": "Os Lusíadas",
    "mireio": "Mirèio",
    "gerusalemme-liberata-volume-1": "Gerusalemme Liberata, Volume 1",
    "gerusalemme-liberata-volume-2": "Gerusalemme Liberata, Volume 2",
    "gerusalemme-liberata-en": "Gerusalemme Liberata",
    "life-of-the-black-prince": "The Life of the Black Prince",
    "the-battle-of-maldon": "The Battle of Maldon",
    "le-p-re-goriot": "Le Père Goriot",
    "eug-nie-grandet": "Eugénie Grandet",
    "la-legende-des-siecles": "La Légende des siècles",
    "la-legende-des-siecles-en": "La Légende des siècles",
    "das-nibelungenlied-en": "Das Nibelungenlied",
    "de-modo-usurarum-liber": "De modo usurarum liber",
    "der-messias-band-1": "Der Messias, Band 1",
    "der-messias-band-2": "Der Messias, Band 2",
    "warsofmarlboroug01tayl-facsimile": "The Wars of Marlborough, Volume I",
    "warsofmarlboroug02tayl-facsimile": "The Wars of Marlborough, Volume II",
}


def title_of(slug):
    if slug in TITLES:
        return TITLES[slug]
    c = CFG.get(slug, {}).get("title")
    return c or slug.replace("-", " ").title()


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("&copy;", "(c)").replace("&ndash;", "–").replace("&dagger;", "†")
    return re.sub(r"\s+", " ", s).strip()


def rhodoman_rows():
    rows = []
    for slug, c in sorted(CFG.items()):
        if c["author"] != "Laurentius Rhodoman":
            continue
        n = pages(slug)
        if not n:
            continue
        year = RHOD_LIFE
        m = re.search(r"\b(15\d\d|16\d\d)\b", c["title"])
        if m:
            year = m.group(1)
        summary = clean(c["blurb"])
        summary = re.sub(r"^Laurentius Rhodoman,\s*", "", summary)
        summary = re.sub(
            r",?\s*in the original (Greek|Latin)( with a machine English translation)?\.?$",
            "", summary).strip()
        summary = summary[:1].upper() + summary[1:] if summary else ""
        lang = "Greek" if c["src"] == "grc" else "Latin"
        rows.append((c["title"], year, n, lang, summary, has_epub(slug)))
    return rows


def md_escape(s):
    return s.replace("|", "\\|")


lines = []
A = lines.append

real = [s for s in DATA] + list(EN_ONLY) + list(FACSIMILE) + \
    [s for s, c in CFG.items() if c["author"] == "Laurentius Rhodoman" and pages(s)]
total_pages = sum(pages(s) for s in real)

A("# Catalogue of built books")
A("")
A(f"Every finished book in `output/`, with its author, the date of the original")
A(f"work, and what it is. Page counts are read from the PDFs themselves, so they")
A("are what KDP would see.")
A("")
A(f"**{len(real)} books, {total_pages:,} pages.** Development scraps are listed at the")
A("end and are not books.")
A("")
A("The division that matters commercially is **who made the English**. A book with")
A("a published public-domain translation can be sold as it stands. A book whose")
A("English was made by a machine says so on its copyright page, and is worth less")
A("as a result — see [SOURCES.md](SOURCES.md) for why some works have no other option.")
A("")
A("---")
A("")
A("## Paired with a published human translation")
A("")
A("No disclosure, sellable as they stand.")
A("")
A("| Work | Author | Written | Translator | Pages | Summary |")
A("|---|---|---|---:|---:|---|")

human = [(s, v) for s, v in DATA.items() if v[2] != "machine"]
order_h = sorted(human, key=lambda kv: -pages(kv[0]))
for slug, (author, year, trans, summary) in order_h:
    t = title_of(slug)
    A(f"| **{md_escape(t)}** | {md_escape(author)} | {year} | {md_escape(trans)} "
      f"| {pages(slug)} | {md_escape(summary)} |")

A("")
A("## Machine-translated")
A("")
A("Each carries a disclosure on the copyright page. For most of these no English")
A("translation exists at all, in or out of copyright.")
A("")
A("| Work | Author | Written | Pages | Summary |")
A("|---|---|---|---:|---|")
mach = [(s, v) for s, v in DATA.items() if v[2] == "machine"]
for slug, (author, year, _t, summary) in sorted(mach, key=lambda kv: -pages(kv[0])):
    t = title_of(slug)
    A(f"| **{md_escape(t)}** | {md_escape(author)} | {year} | {pages(slug)} "
      f"| {md_escape(summary)} |")

rr = rhodoman_rows()
A("")
A(f"## Laurentius Rhodoman — {len(rr)} books, {sum(r[2] for r in rr):,} pages")
A("")
ngrc = sum(1 for r in rr if r[3] == "Greek")
A("A Lutheran schoolmaster who wrote epic, didactic and occasional verse in Homeric")
A(f"Greek for sixty years, and is now almost unread. {ngrc} of these are Greek and")
A(f"{len(rr) - ngrc} Latin. The texts come from the digital")
A("edition at [rhodomanologia.de](https://rhodomanologia.de/); all the English is")
A("machine-made, since none of it has ever been translated. Dates are his lifespan")
A(f"({RHOD_LIFE}) except where the title itself carries a year.")
A("")
A("| Work | Year | Lang | Pages | Summary |")
A("|---|---|---|---:|---|")
for title, year, n, lang, summary, _e in sorted(rr, key=lambda r: -r[2]):
    A(f"| {md_escape(title)} | {year} | {lang} | {n} | {md_escape(summary)} |")

A("")
A("## English-only companions")
A("")
A("The same build with the original suppressed, for readers who want only the")
A("translation. Same text, roughly half the pages.")
A("")
A("| Edition | Pages | Dual-language counterpart |")
A("|---|---:|---|")
for slug, parent in EN_ONLY.items():
    t = title_of(slug)
    A(f"| {md_escape(t)} (English only) | {pages(slug)} | {parent}.pdf, {pages(parent)} pp |")

A("")
A("## Facsimiles")
A("")
A("Page images rather than reset text, so there is no parallel translation.")
A("")
A("| Work | Author | Year | Pages | Note |")
A("|---|---|---|---:|---|")
for slug, (author, year, summary) in FACSIMILE.items():
    A(f"| {md_escape(title_of(slug))} | {author} | {year} | {pages(slug)} | {md_escape(summary)} |")

A("")
A("---")
A("")
A("## Not books — development scraps")
A("")
nscrap = sum(1 for k in SCRAPS if pages(k))
scrapmb = sum((OUT / f"{k}.pdf").stat().st_size for k in SCRAPS
              if (OUT / f"{k}.pdf").exists()) / 1e6
A(f"{nscrap} files, {scrapmb:.0f} MB. Probes, stubs and superseded runs. All")
A("reproducible, and safe to delete.")
A("")
A("| File | Pages | What it was |")
A("|---|---:|---|")
for slug, why in sorted(SCRAPS.items(), key=lambda kv: -pages(kv[0])):
    n = pages(slug)
    if not n:
        continue
    A(f"| `{slug}` | {n} | {why} |")

A("")
A("## Known problems")
A("")
over = [(s, pages(s)) for s in real if pages(s) > 828]
A("**Over KDP's 828-page interior maximum**, so they cannot be printed as single")
A("volumes. The build warns and continues, but the generated cover has a spine")
A("thicker than KDP accepts, so the rejection arrives after upload:")
A("")
for s, n in sorted(over, key=lambda kv: -kv[1]):
    t = title_of(s)
    A(f"- **{t}** — {n} pp, {n - 828} over")
A("")
A("Each needs splitting with `--src-range`, the way Gerusalemme Liberata and Der")
A("Messias already are, which also gives every volume a printable spine.")
A("")
A("**Empty output directories**: `pale-fire-la-audio` and")
A("`warsofmarlboroug01tayl-la-audio` — abandoned audio runs.")
A("")
A("**`the-gallic-wars.pdf` contains the wrong book.** Page 3 begins Ernest Bramah's")
A("*Kai Lung's Golden Hours*; a Gutenberg id fetched the wrong text and nothing")
A("downstream noticed. The file is a scrap, but the silence is worth remembering.")

path = REPO / "CATALOGUE.md"
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {path.name} - {len(real)} books, {total_pages:,} pages")
if over:
    print("over KDP's 828 pages:",
          ", ".join(f"{s} ({n})" for s, n in sorted(over, key=lambda kv: -kv[1])))

# A book built after this script was last touched would otherwise just vanish
# from the catalogue, which is the one failure a catalogue must not have.
known = set(DATA) | set(EN_ONLY) | set(FACSIMILE) | set(SCRAPS) | {
    s for s, c in CFG.items() if c["author"] == "Laurentius Rhodoman"}
uncovered = sorted(p.stem for p in OUT.glob("*.pdf")
                   if not p.name.endswith("-cover.pdf") and p.stem not in known)
if uncovered:
    print(f"\n{len(uncovered)} PDF(s) in output/ are not described in this "
          "script, so they are missing from the catalogue.\n"
          "Add each to DATA (a book) or SCRAPS (not a book):")
    for s in uncovered:
        print(f"  {s}  ({pages(s)} pp)")
