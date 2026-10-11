#!/usr/bin/env python
"""One volume: Grün's Der letzte Ritter with Veit Weber's Murtenlied after it.

The two books come from different kinds of English -- the Romanzen are a machine
translation, the Murtenlied is C. C. Felton's published 1845 version -- so they
cannot be one config entry (a book is either translated or paired). Each is
built into chapters exactly as its own config builds it, and the chapters are
set in one PDF. The machine translation comes from mt.db, so after the first
build of config/letzte_ritter.yaml this costs nothing.

The Murtenlied belongs here because Romanze 5 ends on the death of Charles the
Bold's line and Maximilian's marriage into Burgundy; Murten (1476) is the
battle that broke Charles the year before Nancy.

    python build_letzte_ritter_murten.py
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from book_creator import config, pipeline  # noqa: E402

SLUG = "der-letzte-ritter-and-the-murtenlied"


def main() -> None:
    log = print
    knight = config.load_specs(str(ROOT / "config" / "letzte_ritter.yaml"))[0]
    murten = config.load_specs(str(ROOT / "config" / "murten.yaml"))[0]

    log("== Der letzte Ritter (machine English, from cache) ==")
    chapters = pipeline._chapters_from_machine_translation(knight, log)
    log("== Murtenlied (Felton's English) ==")
    song = pipeline._chapters_from_editions(murten, log)
    for ch in song:
        ch.title = "Das Murtenlied (1476)"
    chapters = chapters + song

    spec = copy.deepcopy(knight)
    spec.title = "Der letzte Ritter, with the Murtenlied"
    spec.author = "Anastasius Grün; Veit Weber"
    spec.translation_source_note = (
        "Der letzte Ritter: machine translation made for this edition. "
        "The Murtenlied: C. C. Felton, 1845 — public domain.")
    spec.copyright.translator = "C. C. Felton (the Murtenlied only)"
    spec.copyright.rights = (
        "This edition's typography, arrangement, and design are copyright "
        "&copy; 2026 Joey Houser. <i>Der letzte Ritter</i> (1830) by Anastasius "
        "Gr&uuml;n (Anton Alexander, Count von Auersperg, 1806&ndash;1876) is in "
        "the public domain; the German is set from the transcription at Projekt "
        "Gutenberg-DE, and the author's prose notes are omitted. Its English is a "
        "machine translation made for this edition, not a published human "
        "translation, and will contain errors. Appended is Veit Weber's song of "
        "the battle of Murten (1476), also in the public domain, set from R. von "
        "Liliencron's edition (1866), read from the page images by machine and "
        "checked by eye; its English is C. C. Felton's ballad of 1845, from "
        "Longfellow's <i>The Poets and Poetry of Europe</i>, which renders a "
        "modernised text of the song and so does not follow it strophe for "
        "strophe.")
    spec.cover.blurb = (
        "Anastasius Gr&uuml;n's cycle of Romanzen on Emperor Maximilian I, the "
        "last knight, with Veit Weber's eyewitness song of the Swiss victory over "
        "Charles the Bold at Murten (1476) after it. German with English: a "
        "machine translation of the Romanzen, and Felton's 1845 ballad for the song.")

    out: dict = {}
    pipeline._claim_slug(SLUG, spec, "output", log)
    path = pipeline._render_print(chapters, spec, SLUG, "output", out, log)
    log(f"done: {path}")


if __name__ == "__main__":
    main()
