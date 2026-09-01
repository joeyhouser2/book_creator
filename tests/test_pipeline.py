"""Pipeline orchestration: monolingual editions, corpus builds, artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from book_creator import audio, corpus, pipeline
from book_creator.model import AudioSpec, BookSpec, CorpusSpec, FontSpec
from book_creator.pipeline import apply_sides, build_book


def _copy(chapters):
    """apply_sides mutates beads in place, so tests need their own copy."""
    import copy
    return copy.deepcopy(chapters)


# --------------------------------------------------------------------------- #
# apply_sides
# --------------------------------------------------------------------------- #
def test_sides_both_is_a_no_op(chapters):
    before = [(b.src, b.tgt) for ch in chapters for b in ch.beads]
    out = apply_sides(_copy(chapters), "both", lambda _m: None)
    assert [(b.src, b.tgt) for ch in out for b in ch.beads] == before


@pytest.mark.parametrize("sides,keep,drop", [("src", "src", "tgt"),
                                             ("tgt", "tgt", "src")])
def test_sides_keeps_exactly_one_side(chapters, sides, keep, drop):
    out = apply_sides(_copy(chapters), sides, lambda _m: None)
    beads = [b for ch in out for b in ch.beads]
    assert beads
    assert all(getattr(b, keep) for b in beads)
    assert not any(getattr(b, drop) for b in beads)


def test_sides_drops_beads_left_with_nothing():
    from book_creator.model import Bead, Chapter
    # A source sentence the translator omitted has no English to show; printing
    # a blank for it would be worse than leaving it out.
    chs = [Chapter(title="I", beads=[
        Bead(src=["habet"], tgt=["has"]),
        Bead(src=["omissum"], tgt=[]),
    ])]
    out = apply_sides(chs, "tgt", lambda _m: None)
    assert len(out[0].beads) == 1
    assert out[0].beads[0].tgt_text == "has"


def test_sides_drops_a_chapter_that_empties_completely():
    from book_creator.model import Bead, Chapter
    chs = [Chapter(title="I", beads=[Bead(src=["a"], tgt=["A"])]),
           Chapter(title="II", beads=[Bead(src=["b"], tgt=[])])]
    out = apply_sides(chs, "tgt", lambda _m: None)
    assert [ch.title for ch in out] == ["I"]


def test_sides_logs_what_it_did(chapters):
    msgs = []
    apply_sides(_copy(chapters), "src", msgs.append)
    assert any("original only" in m for m in msgs)


# --------------------------------------------------------------------------- #
# Corpus builds
# --------------------------------------------------------------------------- #
def _spec(doc_id, **kw):
    base = dict(title="", author="Unknown", src_lang="",
                corpus=CorpusSpec(doc_id=doc_id), mode="prose")
    base.update(kw)
    return BookSpec(**base)


def test_corpus_build_backfills_metadata(corpus_db, small_doc, a_font, tmp_path):
    spec = _spec(small_doc, font=FontSpec(family=a_font))
    art = {}
    build_book(spec, out_dir=str(tmp_path), verbose=False, artifacts=art,
               on_log=lambda _m: None)

    doc = corpus.document(small_doc, db_path=corpus_db)
    # A config entry can be just `corpus: <id>`; the rest comes from the record.
    assert spec.title == doc.title
    assert spec.author == doc.author
    assert spec.src_lang == doc.language
    assert spec.translation_source_note
    assert Path(art["pdf"]).exists()
    assert art["pages"] > 0


def test_corpus_build_records_every_artifact(corpus_db, small_doc, a_font, tmp_path):
    spec = _spec(small_doc, font=FontSpec(family=a_font), epub=True)
    art = {}
    pdf = build_book(spec, out_dir=str(tmp_path), verbose=False, artifacts=art,
                     on_log=lambda _m: None)
    assert art["pdf"] == pdf
    assert Path(art["epub"]).exists()


@pytest.mark.parametrize("sides", ["both", "src", "tgt"])
def test_corpus_build_honours_sides(corpus_db, small_doc, a_font, tmp_path, sides):
    spec = _spec(small_doc, font=FontSpec(family=a_font), sides=sides,
                 slug=f"ed-{sides}")
    art = {}
    build_book(spec, out_dir=str(tmp_path), verbose=False, artifacts=art,
               on_log=lambda _m: None)
    assert Path(art["pdf"]).exists()
    art["_sides"] = sides


def test_monolingual_is_shorter_than_parallel(corpus_db, small_doc, a_font, tmp_path):
    pages = {}
    for sides in ("both", "src", "tgt"):
        art = {}
        build_book(_spec(small_doc, font=FontSpec(family=a_font), sides=sides,
                         slug=f"p-{sides}"),
                   out_dir=str(tmp_path), verbose=False, artifacts=art,
                   on_log=lambda _m: None)
        pages[sides] = art["pages"]
    assert pages["both"] >= pages["src"]
    assert pages["both"] >= pages["tgt"]


def test_original_only_omits_the_translation_disclosure(corpus_db, small_doc,
                                                        a_font, tmp_path):
    src_only = _spec(small_doc, font=FontSpec(family=a_font), sides="src",
                     slug="n-src")
    both = _spec(small_doc, font=FontSpec(family=a_font), sides="both",
                 slug="n-both")
    for spec in (src_only, both):
        build_book(spec, out_dir=str(tmp_path), verbose=False,
                   on_log=lambda _m: None)
    # Disclosing a machine translation that is not in the book would be noise
    # at best and misleading at worst.
    assert "machine translation" not in src_only.translation_source_note
    assert "machine translation" in both.translation_source_note


def test_original_only_can_build_an_untranslated_work(corpus_db, untranslated_doc,
                                                      a_font, tmp_path):
    # These works are unbuildable as a parallel text but perfectly printable
    # alone -- that is most of the corpus.
    art = {}
    build_book(_spec(untranslated_doc, font=FontSpec(family=a_font), sides="src"),
               out_dir=str(tmp_path), verbose=False, artifacts=art,
               on_log=lambda _m: None)
    assert art["pages"] > 0


def test_untranslated_work_as_parallel_text_fails_with_a_pointer(
        corpus_db, untranslated_doc, a_font, tmp_path):
    with pytest.raises(corpus.CorpusError, match="sides"):
        build_book(_spec(untranslated_doc, font=FontSpec(family=a_font)),
                   out_dir=str(tmp_path), verbose=False, on_log=lambda _m: None)


# --------------------------------------------------------------------------- #
# Narration follows the edition
# --------------------------------------------------------------------------- #
def test_monolingual_narration_reads_one_language(chapters):
    spec = AudioSpec(enabled=True, engine="tone", device="cpu",
                     announce_chapters=False)
    counts = {}
    for sides in ("both", "src", "tgt"):
        chs = apply_sides(_copy(chapters), sides, lambda _m: None)
        langs = {u.lang for _, items in
                 audio.plan(chs, spec=spec, src_lang="la", tgt_lang="en")
                 for u in items}
        expected = {"la", "en"} if sides == "both" else {
            "la" if sides == "src" else "en"}
        assert langs == expected
        counts[sides] = audio.estimate(chs, spec=spec, src_lang="la",
                                       tgt_lang="en")["utterances"]
    # Halving the languages halves the GPU time, exactly.
    assert counts["both"] == counts["src"] + counts["tgt"]


def test_audio_failure_does_not_lose_the_book(corpus_db, small_doc, a_font,
                                              tmp_path):
    # The PDF is already written by the time narration starts; a missing TTS
    # package must not throw it away.
    spec = _spec(small_doc, font=FontSpec(family=a_font),
                 audio=AudioSpec(enabled=True, engine="kokoro", device="cpu"))
    art = {}
    msgs = []
    pdf = build_book(spec, out_dir=str(tmp_path), verbose=False, artifacts=art,
                     on_log=msgs.append)
    assert Path(pdf).exists()
    assert "audio" not in art
    assert any("Audiobook skipped" in m for m in msgs)


def test_epub_output_is_genuinely_optional(monkeypatch, tmp_path, chapters):
    """Regression: a missing ebooklib took down the whole CLI.

    pipeline imports render_epub unconditionally, so a module-level
    `from ebooklib import epub` made an optional dependency mandatory —
    `make_book.py --help` failed on an install that never asked for EPUB.
    """
    from book_creator import render_epub

    monkeypatch.setattr(render_epub, "epub", None)
    with pytest.raises(RuntimeError, match="requirements-epub"):
        render_epub.render(chapters, out_path=str(tmp_path / "x.epub"),
                           title="T", author="A", src_lang="la", tgt_lang="en")


def test_audio_only_renders_no_print_files(corpus_db, small_doc, a_font,
                                           tmp_path, tone_engine):
    spec = _spec(small_doc, font=FontSpec(family=a_font), epub=True,
                 audio_only=True,
                 audio=AudioSpec(enabled=True, engine="tone", device="cpu",
                                 format="mp3", max_beads=3))
    art = {}
    returned = build_book(spec, out_dir=str(tmp_path), verbose=False,
                          artifacts=art, on_log=lambda _m: None)
    assert "pdf" not in art and "epub" not in art and "cover" not in art
    assert not list(Path(tmp_path).glob("*.pdf"))
    assert art["audio"]["book"]
    # The audiobook is the deliverable, so it is what gets returned.
    assert returned == art["audio"]["book"]


def test_audio_only_leaves_an_existing_pdf_untouched(corpus_db, small_doc,
                                                     a_font, tmp_path,
                                                     tone_engine):
    """The point of audio-only: add narration without rebuilding the book."""
    printed = _spec(small_doc, font=FontSpec(family=a_font))
    art = {}
    build_book(printed, out_dir=str(tmp_path), verbose=False, artifacts=art,
               on_log=lambda _m: None)
    pdf = Path(art["pdf"])
    before = pdf.read_bytes()

    narrate = _spec(small_doc, font=FontSpec(family=a_font), sides="tgt",
                    audio_only=True,
                    audio=AudioSpec(enabled=True, engine="tone", device="cpu",
                                    format="mp3", max_beads=3))
    build_book(narrate, out_dir=str(tmp_path), verbose=False,
               on_log=lambda _m: None)
    assert pdf.read_bytes() == before, "the printed book was modified"


def test_monolingual_output_gets_its_own_filenames(corpus_db, small_doc,
                                                   a_font, tmp_path):
    # Otherwise an English-only edition silently overwrites the parallel text.
    both, tgt = {}, {}
    build_book(_spec(small_doc, font=FontSpec(family=a_font)),
               out_dir=str(tmp_path), verbose=False, artifacts=both,
               on_log=lambda _m: None)
    build_book(_spec(small_doc, font=FontSpec(family=a_font), sides="tgt"),
               out_dir=str(tmp_path), verbose=False, artifacts=tgt,
               on_log=lambda _m: None)
    assert both["pdf"] != tgt["pdf"]
    assert Path(tgt["pdf"]).stem.endswith("-en")
    assert Path(both["pdf"]).exists()


def test_an_explicit_slug_is_never_suffixed(corpus_db, small_doc, a_font,
                                            tmp_path):
    art = {}
    build_book(_spec(small_doc, font=FontSpec(family=a_font), sides="tgt",
                     slug="my-own-name"),
               out_dir=str(tmp_path), verbose=False, artifacts=art,
               on_log=lambda _m: None)
    assert Path(art["pdf"]).stem == "my-own-name"


def test_audio_only_propagates_a_tts_failure(corpus_db, small_doc, a_font,
                                             tmp_path):
    # With no print edition to fall back on, swallowing the error would leave
    # the build reporting success having produced nothing at all.
    spec = _spec(small_doc, font=FontSpec(family=a_font), audio_only=True,
                 audio=AudioSpec(enabled=True, engine="kokoro", device="cpu"))
    with pytest.raises(Exception, match="pip install|not installed"):
        build_book(spec, out_dir=str(tmp_path), verbose=False,
                   on_log=lambda _m: None)


def test_build_with_narration(corpus_db, small_doc, a_font, tmp_path, tone_engine):
    spec = _spec(small_doc, font=FontSpec(family=a_font),
                 audio=AudioSpec(enabled=True, engine="tone", device="cpu",
                                 format="mp3", max_beads=4))
    art = {}
    build_book(spec, out_dir=str(tmp_path), verbose=False, artifacts=art,
               on_log=lambda _m: None)
    assert art["audio"]["book"] and Path(art["audio"]["book"]).exists()
    assert art["audio"]["seconds"] > 0


# --------------------------------------------------------------------------- #
# One edition, printed on its own
# --------------------------------------------------------------------------- #
def test_a_single_edition_becomes_one_sided_beads(tmp_path):
    """No second edition means nothing to align against — the text is just
    segmented, with the other side of every bead left empty."""
    src = tmp_path / "en.txt"
    src.write_text("Gallia est omnis. Divisa in partes tres. Quarum unam.",
                   encoding="utf-8")
    spec = BookSpec(title="T", author="A", src_path=str(src), src_lang="en",
                    sides="src")
    chapters = pipeline._chapters_from_single_edition(spec, lambda _m: None)

    beads = [b for ch in chapters for b in ch.beads]
    assert beads, "expected beads from the single edition"
    assert all(b.src and not b.tgt for b in beads)


def test_a_single_edition_can_be_the_translation_side(tmp_path):
    tgt = tmp_path / "en.txt"
    tgt.write_text("All Gaul is divided. Into three parts. One of which.",
                   encoding="utf-8")
    spec = BookSpec(title="T", author="A", src_lang="la",
                    tgt_path=str(tgt), tgt_lang="en", sides="tgt")
    chapters = pipeline._chapters_from_single_edition(spec, lambda _m: None)

    beads = [b for ch in chapters for b in ch.beads]
    assert beads
    assert all(b.tgt and not b.src for b in beads)


def test_asking_to_print_the_side_that_is_missing_says_so(tmp_path):
    """Only an Original given, but the edition set to translation-only: the
    error has to name the contradiction, not fail opening a path of None."""
    src = tmp_path / "en.txt"
    src.write_text("Gallia est omnis.", encoding="utf-8")
    spec = BookSpec(title="T", author="A", src_path=str(src), src_lang="en",
                    sides="tgt")
    with pytest.raises(ValueError, match="missing"):
        pipeline._chapters_from_single_edition(spec, lambda _m: None)


def test_build_routes_a_lone_edition_to_the_single_path(tmp_path):
    """The whole point: build_book must not try to fetch a translation that
    was never chosen."""
    src = tmp_path / "en.txt"
    src.write_text(" ".join(f"Sentence number {i}." for i in range(40)),
                   encoding="utf-8")
    spec = BookSpec(title="Solo", author="A", src_path=str(src), src_lang="en",
                    sides="src", epub=False)
    out = pipeline.build_book(spec, out_dir=str(tmp_path), verbose=False)
    assert Path(out).exists()
