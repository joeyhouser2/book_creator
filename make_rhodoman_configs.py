#!/usr/bin/env python
"""Write config/rhodoman_greek.yaml and config/rhodoman_latin.yaml from input/rhodoman/.

One book per work. The Greek is translated by a local chat model, because the
latin repo's Greek NLLB models, trained on prose, turned the opening of the Arion
into nonsense ("Archayous said to Archayous ...") where qwen3:14b read it
correctly; the Latin goes through the latin repo's NLLB model, as everywhere
else. Both are disclosed on the copyright page.

The licence of rhodomanologia.de is unresolved: these books are for working
from, not for sale, until the editors have been asked (see WANTED.md).
"""
from pathlib import Path

HERE = Path(__file__).parent
IN = HERE / "input" / "rhodoman"

# slug -> (title, a line saying what the work is)
WORKS = {
    "rhod-arion": ("Arion", "a Doric epyllion on the poet Arion's rescue by a dolphin"),
    "rhod-luth-1-2": ("Lutherus", "a hexametric didactic poem on Luther in two books"),
    "rhod-theol-christ": ("Theologia Christiana", "a theological didactic poem, from a manuscript"),
    "rhod-il-parv-hom-1-24": ("Ilias Parva, Part I", "Greek and Latin summaries of Homer's Iliad, 1604"),
    "rhod-il-parv-quint-1-14": ("Ilias Parva, Part II", "Greek and Latin summaries of Quintus of Smyrna, 1604"),
    "rhod-hym-schol": ("Hymnus Scholasticus", "a Greek-Latin school hymn"),
    "rhod-hist-eccl": ("Historia Ecclesiae", "a verse history of the Church"),
    "rhod-ilf-herc": ("Ilfelda Hercynica", "a prize poem in praise of Ilfeld"),
    "rhod-luth-dor": ("Dorian Lament for Luther", "a Doric funeral lament"),
    "rhod-biop": ("Bioporikon", "a poetic autobiography addressed to Martin Crusius"),
    "rhod-quint-praef": ("Dedicatory Preface to Quintus of Smyrna", "a poetic preface to the edition of the last three books"),
    "rhod-quint-per-1-3": ("Periochae to the Last Three Books of Quintus", "Greek and Latin summaries"),
    "rhod-par-chytr": ("Consolation for David Chytraeus", "a poem of consolation"),
    "rhod-ep-crus-2": ("Letter-Poem to Martin Crusius, 1581", "a verse letter"),
    "rhod-ep-crus-3": ("Letter-Poem to Martin Crusius, 1582", "a verse letter"),
    "rhod-dion-praef": ("Dedicatory Poem to Dio's Trojan Oration", "a dedicatory poem"),
    "rhod-carst-1-2": ("Two Epicedia for Hermann Carstens", "two funeral poems"),
    "rhod-phil-rein": ("Poem for Reiner Reineccius", "a contribution and consolation poem"),
    "rhod-westph": ("Congratulatory Poem for Joachim Westphal", "a congratulatory poem"),
    "rhod-crus-turc": ("Poem for Crusius' Turcograecia", "a prefatory poem"),
    "rhod-frei": ("Letter-Poem to Christoph Frey", "a verse letter"),
    "frei-eleg": ("Elegy to Rhodoman and Michael Neander", "an elegy dedicated to Rhodoman by Frey"),
    "goth-rhod": ("Letter-Poem from Matthaeus Gothus to Rhodoman", "a verse letter to Rhodoman"),
    "rhod-asp": ("Aspastikon", "an autobiographical poem on a change of post"),
    "rhod-it-lips": ("Iter Lipsicum", "a literary description of a journey to Leipzig"),
    "rhod-luth-epist": ("Dedicatory Poem to the Lutherus", "a Latin dedicatory poem"),
    "rhod-coc-ion-1-2": ("Two Poems for Koch's Jonah Paraphrase", "two accompanying poems"),
    "rhod-carm-1-3": ("Two Occasional Poems", "a wedding poem and another"),
    "rhod-mau": ("Friendship Poem to Thomas Mauer", "a request for friendship"),
    "mau-rhod": ("Thomas Mauer's Reply to Rhodoman", "a reply poem"),
    "rhod-moll": ("Poem for Moller's Sermons on Isaiah", "a prefatory poem"),
    "rhod-inscr-burgg": ("Epitaph for a Schwerin Court Preacher", "an inscriptional epitaph"),
}

HEADER = {
    "grc": '''# Rhodoman's Greek verse, one book per work, with a machine English.
#
# The Greek is from rhodomanologia.de (Gärtner and Weise's edition), original text
# only: their German translation and apparatus are not taken. The English is made
# by a local chat model (qwen3:14b), because the latin repo's Greek NLLB models,
# trained on prose, turn Doric epic into nonsense. The licence of the site is
# unresolved, so these are working builds, not for sale until the editors are asked.
#
# python fetch_rhodoman.py writes the inputs; python make_rhodoman_configs.py this file.
# Run with:  python make_book.py config/rhodoman_greek.yaml

translators:
  grc:
    ollama: "qwen3:14b"
    batch: 6
    context: >-
      This is Greek verse by Laurentius Rhodoman (1546-1606), a German humanist,
      written in imitation of Homer and the Homeric Hymns, often in Doric or Epic
      dialect; Latin names are people and places.

books:
''',
    "la": '''# Rhodoman's Latin verse, one book per work, with a machine English.
#
# From rhodomanologia.de (Gärtner and Weise's edition), original text only. The
# English is the latin repo's NLLB model, translated a sentence at a time. The
# licence of the site is unresolved: working builds, not for sale until the editors
# are asked.
#
# Run with:  python make_book.py config/rhodoman_latin.yaml

books:
''',
}

BOOK = '''  - title: "{title}"
    author: "Laurentius Rhodoman"
    src_lang: {lang}
    tgt_lang: en
    src_path: "input/rhodoman/{slug}_{lang}.txt"
    mode: verse
    translate: true
    translate_by: sentence
    first: src
    trim: [6.0, 9.0]
    font: {font}
    decorations:
      margin: corners
      chapter: classical
      color: "#4a3a1f"
    copyright:
      publisher: "Houser Classics"
      holder: "Joey Houser"
      year: 2026
      isbn: ""
      rights: >-
        This edition's typography, arrangement, and design are copyright
        &copy; 2026 Joey Houser. The {langname} text of Laurentius Rhodoman
        (1546&ndash;1606) is in the public domain; it is taken from the digital
        edition at rhodomanologia.de, original text only. The English is a machine
        translation made for this edition, not a published human translation, and
        will contain errors.
    cover:
      paper: white
      blurb: "Laurentius Rhodoman, {what}, in the original {langname} with a machine English translation."
    epub: true
'''


def main() -> int:
    index = [l.split("\t") for l in (IN / "index.tsv").read_text(encoding="utf-8").splitlines() if l]
    for lang, name, font in (("grc", "Greek", "GFSDidot"), ("la", "Latin", "Cardo")):
        out = HEADER[lang]
        n = 0
        for slug, l, count, _ in index:
            if l != lang or slug not in WORKS:
                continue
            title, what = WORKS[slug]
            out += BOOK.format(title=title, slug=slug, lang=lang, font=font, langname=name, what=what)
            n += 1
        (HERE / "config" / f"rhodoman_{'greek' if lang == 'grc' else 'latin'}.yaml").write_text(out, encoding="utf-8")
        print(f"{lang}: {n} books")
    missing = [s for s, l, *_ in index if s not in WORKS]
    if missing:
        print("works with no title entry:", missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
