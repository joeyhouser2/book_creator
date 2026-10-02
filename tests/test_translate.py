"""Generating the missing English side, and pairing a stanzaic poem.

Together these are what it takes to print a dual-language edition of something
that has no published translation, or whose translation is too long to pair as
one block. No model is downloaded here: a translator is any callable, so a
deterministic stand-in exercises the whole path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from book_creator import pipeline, segment, translators
from book_creator.align import gale_church
from book_creator.model import BookSpec


@pytest.fixture(autouse=True)
def _clean_registry():
    """No test may leak a translator into the next one -- registration is global."""
    translators.clear()
    yield
    translators.clear()


def upper(texts):
    """Stand-in translator: uppercase, one output per input, order preserved."""
    return [t.upper() for t in texts]


# --------------------------------------------------------------------------- #
# segment.stanzas
# --------------------------------------------------------------------------- #
SINGLE_SPACED = """Line one of one
Line two of one

Line one of two
Line two of two
"""

# Gutenberg's German Nibelungenlied is laid out like this: a blank line between
# every verse line, three between stanzas. The commonest gap is what tells them
# apart, so the same code has to read both spacings.
DOUBLE_SPACED = """Line one of one

Line two of one



Line one of two

Line two of two
"""


@pytest.mark.parametrize("text", [SINGLE_SPACED, DOUBLE_SPACED])
def test_stanzas_found_at_either_line_spacing(text):
    assert segment.stanzas(text) == [["Line one of one", "Line two of one"],
                                     ["Line one of two", "Line two of two"]]


def test_stanzas_strips_a_number_printed_after_the_verse():
    # Simrock prints the strophe number at the end of the stanza's first line.
    text = "Von ihrem Kleide leuchtete   mancher edle Stein;        288\nIhre rosenrothe Farbe\n"
    assert segment.stanzas(text) == [
        ["Von ihrem Kleide leuchtete   mancher edle Stein;", "Ihre rosenrothe Farbe"]]


def test_stanzas_does_not_count_a_number_line_as_a_stanza():
    # Needler sets the strophe number on its own line, at the same wide gap that
    # separates stanzas -- so it arrives here looking like a stanza of its own.
    # Counting it would double the stanza count and offset every pairing by one.
    # Laid out as he lays it out: four-line strophes, a blank line between the
    # lines and three between the strophes.
    text = "\n\n\n".join(
        f"{239 + n}\n\n\n" + "\n\n".join(f"line {n}.{k}" for k in range(4))
        for n in range(3))
    assert segment.stanzas(text) == [
        [f"line {n}.{k}" for k in range(4)] for n in range(3)]


def test_stanzas_drops_a_number_line_at_any_spacing():
    # Not every edition sets the number off by a wider gap; it is still a label.
    assert segment.stanzas("17\nfirst line\nsecond line\n") == [
        ["first line", "second line"]]


def test_stanzas_keeps_a_number_that_is_part_of_the_verse():
    # Only a WIDE gap marks a strophe number; "in 1415" mid-line is text.
    assert segment.stanzas("he came in 1415\nand left\n") == [["he came in 1415", "and left"]]


def test_stanzas_returns_one_group_when_there_is_no_break_to_find():
    # Callers treat this as "no stanza structure here", not as one giant stanza.
    assert segment.stanzas("a\nb\nc\n") == [["a", "b", "c"]]


def test_stanzas_of_empty_text_is_empty():
    assert segment.stanzas("\n\n  \n") == []


# --------------------------------------------------------------------------- #
# A banded DP
# --------------------------------------------------------------------------- #
def _pair(n: int, split: set[int]):
    src = [f"stanza {i} " + "x" * (40 + i % 60) for i in range(n)]
    tgt = []
    for i, s in enumerate(src):
        if i in split:
            tgt += [s[:len(s) // 2], s[len(s) // 2:]]
        else:
            tgt.append(s)
    return src, tgt


def test_band_does_not_change_the_alignment_it_finds():
    # The whole point: the band is a speed-up, not a different answer. An epic's
    # stanzas are 5.9M cells unbanded, which measures in minutes.
    src, tgt = _pair(120, {7, 33, 61, 99})
    wide = gale_church(src, tgt)
    narrow = gale_church(src, tgt, band=32)
    assert [(b.src, b.tgt) for b in narrow] == [(b.src, b.tgt) for b in wide]


def test_band_wide_enough_absorbs_a_length_difference():
    src, tgt = _pair(60, set(range(0, 60, 2)))   # half the stanzas split
    assert len(tgt) == 90
    beads = gale_church(src, tgt, band=40)
    assert sum(len(b.src) for b in beads) == 60
    assert sum(len(b.tgt) for b in beads) == 90


def test_band_too_narrow_says_so_instead_of_crashing():
    with pytest.raises(ValueError, match="No alignment path within band"):
        gale_church(["a bc"] * 50, ["d ef"] * 200, band=0)


def test_band_tolerates_an_empty_side():
    assert gale_church([], [], band=16) == []
    assert len(gale_church(["a", "b"], [], band=16)) == 2


# --------------------------------------------------------------------------- #
# Stanza pairing
# --------------------------------------------------------------------------- #
def _spec(**kw) -> BookSpec:
    base = dict(title="T", author="A", src_lang="de", mode="verse",
                aligner="gale-church", verse_align="stanza", clean=False)
    base.update(kw)
    return BookSpec(**base)


def test_align_stanzas_pairs_stanza_against_stanza():
    src = "eins zwei drei\nvier fuenf sechs\n\nsieben acht neun\nzehn elf zwoelf\n"
    tgt = "one two three\nfour five six\n\nseven eight nine\nten eleven twelve\n"
    beads = pipeline._align_stanzas(src, tgt, _spec(), lambda _m: None)
    assert beads is not None
    assert len(beads) == 2
    assert beads[0].src == ["eins zwei drei", "vier fuenf sechs"]
    assert beads[0].tgt == ["one two three", "four five six"]


def test_align_stanzas_keeps_the_line_breaks():
    # A stanza printed as one run-on paragraph is not verse. `lines` is what
    # tells the renderer to keep the breaks.
    src = "a b c\nd e f\n\ng h i\nj k l\n"
    beads = pipeline._align_stanzas(src, src, _spec(), lambda _m: None)
    assert beads and all(b.lines for b in beads)


def test_align_stanzas_declines_when_a_side_has_no_stanzas():
    # None means "fall back to block pairing", which the caller then logs.
    lines_only = "a\nb\nc\nd\n"
    stanzaic = "a b\nc d\n\ne f\ng h\n"
    assert pipeline._align_stanzas(lines_only, stanzaic, _spec(), lambda _m: None) is None
    assert pipeline._align_stanzas(stanzaic, lines_only, _spec(), lambda _m: None) is None


def test_verse_block_pairing_is_still_the_default():
    spec = _spec(verse_align="block")
    assert spec.verse_align == "block"
    beads = pipeline._verse_blocks(["a", "b"], ["x", "y"], spec)
    # Whole original first, then the whole translation -- never interleaved.
    assert [(b.src, b.tgt) for b in beads] == [(["a"], []), (["b"], []),
                                               ([], ["x"]), ([], ["y"])]


def test_verse_block_pairing_honours_first_tgt():
    beads = pipeline._verse_blocks(["a"], ["x"], _spec(verse_align="block", first="tgt"))
    assert [(b.src, b.tgt) for b in beads] == [([], ["x"]), (["a"], [])]


# --------------------------------------------------------------------------- #
# Machine-translating the missing side
# --------------------------------------------------------------------------- #
SOURCE = """Erstes Kapitel

Dies ist ein Satz. Und hier ein zweiter.

Zweites Kapitel

Noch ein Satz.
"""


@pytest.fixture
def source_file(tmp_path):
    p = tmp_path / "original.txt"
    p.write_text(SOURCE, encoding="utf-8")
    return str(p)


def test_translate_fills_the_missing_side(source_file):
    translators.register("de", upper)
    spec = _spec(mode="prose", src_path=source_file, translate=True)
    chapters = pipeline._chapters_from_machine_translation(spec, lambda _m: None)
    beads = [b for ch in chapters for b in ch.beads]
    assert beads
    assert all(b.src and b.tgt for b in beads)
    # Identity pairing: one English rendering per source segment, in order. The
    # correspondence is exact by construction, so no aligner runs.
    assert all(b.tgt_text == b.src_text.upper() for b in beads)


def test_translate_discloses_that_a_machine_wrote_it(source_file):
    translators.register("de", upper)
    spec = _spec(mode="prose", src_path=source_file, translate=True)
    pipeline._chapters_from_machine_translation(spec, lambda _m: None)
    assert "machine translation" in spec.translation_source_note


def test_translate_leaves_an_explicit_source_note_alone(source_file):
    translators.register("de", upper)
    spec = _spec(mode="prose", src_path=source_file, translate=True,
                 translation_source_note="Rendered by my own model.")
    pipeline._chapters_from_machine_translation(spec, lambda _m: None)
    assert spec.translation_source_note == "Rendered by my own model."


class _Named:
    """A translator carrying a model_name, standing in for LocalTranslator so no
    weights are downloaded."""

    def __init__(self, model_name):
        self.model_name = model_name

    def __call__(self, texts):
        return upper(texts)


@pytest.fixture
def no_download(monkeypatch):
    """use_local without the 300 MB download."""
    def fake(lang, model=None, **kw):
        tr = _Named(model or translators.LOCAL_MODELS[lang])
        translators.register(lang, tr)
        return tr
    monkeypatch.setattr(translators, "use_local", fake)


def test_translate_reaches_for_the_built_in_model_when_none_is_registered(
        source_file, no_download):
    """--translate alone is enough; the web UI cannot register one at all."""
    spec = _spec(mode="prose", src_path=source_file, translate=True)
    notes: list[str] = []
    chapters = pipeline._chapters_from_machine_translation(spec, notes.append)
    assert [b for ch in chapters for b in ch.beads]
    # And it says which model, and that it only reads the modern language.
    assert any("opus-mt-de-en" in n and "modern" in n for n in notes)


def test_translate_prefers_a_translator_that_was_registered(source_file, no_download):
    translators.register("de", upper)
    spec = _spec(mode="prose", src_path=source_file, translate=True)
    notes: list[str] = []
    pipeline._chapters_from_machine_translation(spec, notes.append)
    assert not any("built-in" in n for n in notes)


def test_translate_refuses_a_language_with_no_model_at_all(source_file):
    # Old English has no Opus-MT model and no latin-repo fine-tune, and guessing
    # one would be worse than saying so.
    spec = _spec(mode="prose", src_lang="ang", src_path=source_file, translate=True)
    with pytest.raises(ValueError, match="no built-in model"):
        pipeline._chapters_from_machine_translation(spec, lambda _m: None)


def test_translate_will_not_reconstruct_an_original_from_its_translation(source_file):
    # Rendering English back into Middle High German is not a thing to offer.
    translators.register("de", upper)
    spec = _spec(mode="prose", tgt_path=source_file, translate=True)
    with pytest.raises(ValueError, match="no original was given"):
        pipeline._chapters_from_machine_translation(spec, lambda _m: None)


def test_translate_rejects_a_translator_that_loses_segments(source_file):
    translators.register("de", lambda texts: [t.upper() for t in texts][:-1])
    spec = _spec(mode="prose", src_path=source_file, translate=True)
    with pytest.raises(ValueError, match="translator returned"):
        pipeline._chapters_from_machine_translation(spec, lambda _m: None)


def test_translated_verse_keeps_its_lines(tmp_path):
    p = tmp_path / "poem.txt"
    p.write_text("erste zeile\nzweite zeile\n\ndritte zeile\n", encoding="utf-8")
    translators.register("de", upper)
    spec = _spec(src_path=str(p), translate=True)
    chapters = pipeline._chapters_from_machine_translation(spec, lambda _m: None)
    beads = [b for ch in chapters for b in ch.beads]
    assert beads and all(b.lines for b in beads)


def test_translate_path_is_chosen_only_when_one_edition_is_given(source_file, tmp_path):
    """With both editions present, the real translation wins over the model."""
    other = tmp_path / "english.txt"
    other.write_text("A sentence. And another.\n", encoding="utf-8")
    translators.register("de", upper)
    spec = _spec(mode="prose", src_path=source_file, tgt_path=str(other),
                 translate=True, translation_pd_confirmed=True)
    chapters = pipeline._chapters_from_editions(spec, lambda _m: None)
    tgt = " ".join(t for ch in chapters for t in ch.tgt_segments)
    assert "A sentence." in tgt
    assert tgt != tgt.upper()


# --------------------------------------------------------------------------- #
# Registering the built-in models
# --------------------------------------------------------------------------- #
def test_use_local_registers_the_built_in_model_for_the_language():
    # Constructed but never called, so no weights are downloaded here.
    tr = translators.use_local("de")
    assert tr.model_name == translators.LOCAL_MODELS["de"]
    assert translators.get("de") is tr


def test_use_local_accepts_an_explicit_model_name():
    tr = translators.use_local("de", "some-org/middle-high-german-en")
    assert tr.model_name == "some-org/middle-high-german-en"


def test_use_local_refuses_a_language_it_has_no_model_for():
    with pytest.raises(ValueError, match="No built-in translation model"):
        translators.use_local("grc")


@pytest.mark.parametrize("cfg,attr,expected", [
    ("local", "model_name", "Helsinki-NLP/opus-mt-fr-en"),
    ({"model": None}, "model_name", "Helsinki-NLP/opus-mt-fr-en"),
    ("my-org/my-model", "model_name", "my-org/my-model"),
    ("http://localhost:8001/translate", "url", "http://localhost:8001/translate"),
])
def test_configure_from_reads_both_local_models_and_endpoints(cfg, attr, expected):
    translators.configure_from({"fr": cfg})
    assert getattr(translators.get("fr"), attr) == expected


def test_configure_from_rejects_an_entry_naming_neither():
    with pytest.raises(ValueError, match="neither a 'url' nor a 'model'"):
        translators.configure_from({"fr": {"batch": 8}})


def test_local_translator_passes_blank_text_through_untouched():
    # A translation model given an empty string invents a sentence for it, which
    # on the alignment path fabricates a match where the text says there is none.
    tr = translators.LocalTranslator("never-loaded")
    assert tr(["", "   "]) == ["", ""]


# --------------------------------------------------------------------------- #
# Output filenames
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("title,slug", [
    # Dropping the accent mangles the name instead of simplifying it: this one
    # used to come out "la-l-gende-des-si-cles".
    ("La Légende des siècles", "la-legende-des-siecles"),
    ("Mirèio", "mireio"),
    ("Œuvres complètes", "oeuvres-completes"),
    # ß has no NFD decomposition, so it is spelled out before folding.
    ("Neununddreißigstes Abenteuer", "neununddreissigstes-abenteuer"),
    ("Das Nibelungenlied", "das-nibelungenlied"),
    ("", "book"),
    # Greek survives the accent fold and was then stripped wholesale by the
    # [a-z0-9] filter, so EVERY Greek title slugged to "book" -- build the
    # Iliad and then the Odyssey and the second silently replaced the first.
    # Greek is a primary source language here (Perseus, the Latin corpus), so
    # these go through the same transliteration the catalog search uses.
    ("Κύρου Ἀνάβασις", "kyrou-anabasis"),
    ("Ἰλιάς", "ilias"),
    ("Ὀδύσσεια", "odysseia"),
    # Polytonic breathings and the iota subscript are combining marks after
    # NFD, so they come off with the accents.
    ("Ξενοφῶν", "xenophon"),
    ("Εὐριπίδης", "euripides"),
    # Mixed scripts in one title still produce one readable stem.
    ("Ἰλιάς: The Iliad of Homer", "ilias-the-iliad-of-homer"),
    # Only punctuation, in any script, still has no letters to name a file by.
    ("— ; —", "book"),
])
def test_slug_folds_accents_rather_than_dropping_them(title, slug):
    assert pipeline._slugify(title) == slug


def test_greek_titles_do_not_all_slug_alike():
    # The bug was not just an ugly name: distinct books shared one filename.
    titles = ["Ἰλιάς", "Ὀδύσσεια", "Κύρου Ἀνάβασις"]
    assert len({pipeline._slugify(t) for t in titles}) == len(titles)


# --------------------------------------------------------------------------- #
# Slug collisions
# --------------------------------------------------------------------------- #
def _claim(tmp_path, slug, title):
    spec = BookSpec(title=title, author="A.", src_lang="el", tgt_lang="en")
    pipeline._claim_slug(slug, spec, str(tmp_path), lambda m: None)


def test_a_second_book_may_not_take_over_the_first_s_slug(tmp_path):
    _claim(tmp_path, "iliad", "The Iliad")
    with pytest.raises(ValueError, match="already belongs to 'The Iliad'"):
        _claim(tmp_path, "iliad", "The Odyssey")


def test_rebuilding_the_same_book_keeps_its_slug(tmp_path):
    _claim(tmp_path, "iliad", "The Iliad")
    _claim(tmp_path, "iliad", "The Iliad")


def test_two_books_with_different_slugs_do_not_collide(tmp_path):
    _claim(tmp_path, "ilias", "Ἰλιάς")
    _claim(tmp_path, "odysseia", "Ὀδύσσεια")


def test_an_unreadable_claim_does_not_block_a_build(tmp_path):
    # Bookkeeping must never be the thing that stops a build; with no readable
    # evidence of an owner there is no collision to report.
    (tmp_path / "iliad.build.json").write_text("{not json", encoding="utf-8")
    _claim(tmp_path, "iliad", "The Iliad")


def test_the_claim_survives_a_title_in_a_non_latin_script(tmp_path):
    _claim(tmp_path, "ilias", "Ἰλιάς")
    with pytest.raises(ValueError, match="already belongs to"):
        _claim(tmp_path, "ilias", "Ὀδύσσεια")


# --------------------------------------------------------------------------- #
# Machine translation combined with a monolingual edition
# --------------------------------------------------------------------------- #
def _build(tmp_path, src_text, **kw):
    """Run a real build and return (spec, chapters) via the source-selection path."""
    p = tmp_path / "original.txt"
    p.write_text(src_text, encoding="utf-8")
    spec = _spec(mode="prose", src_path=str(p), translate=True, **kw)
    out = tmp_path / "out"
    out.mkdir()
    pipeline.build_book(spec, out_dir=str(out), verbose=False)
    return spec, out


def test_english_only_edition_of_an_untranslated_original(tmp_path):
    """`sides: tgt` used to be refused for wanting "the side that is missing" --
    which is the side the machine-translation path exists to supply."""
    translators.register("de", upper)
    spec, out = _build(tmp_path, "Dies ist ein Satz. Und hier ein zweiter.\n",
                       sides="tgt")
    # It built, and the English is named separately from the parallel text so
    # one does not overwrite the other.
    pdfs = [f.name for f in out.iterdir() if f.suffix == ".pdf"]
    assert pdfs and any(n.endswith("-en.pdf") for n in pdfs), pdfs


def test_original_only_edition_does_not_run_the_model(tmp_path):
    """Translating and then printing only the original would run the slowest
    step in the build to throw its output away."""
    called: list[int] = []

    def counting(texts):
        called.append(len(texts))
        return upper(texts)

    translators.register("de", counting)
    _build(tmp_path, "Dies ist ein Satz. Und hier ein zweiter.\n", sides="src")
    assert called == []


# --------------------------------------------------------------------------- #
# KDP's page ceiling
# --------------------------------------------------------------------------- #
def test_a_book_over_kdp_page_limit_says_so(tmp_path, monkeypatch, no_download):
    """A parallel text is two books' worth of pages and crosses 828 easily.
    Without this the only signal is a rejection from the KDP dashboard."""
    monkeypatch.setattr(pipeline.render_pdf, "render",
                        lambda *a, **k: (str(tmp_path / "x.pdf"), 1366))
    p = tmp_path / "o.txt"
    p.write_text("Dies ist ein Satz. Und hier ein zweiter.\n", encoding="utf-8")
    spec = _spec(mode="prose", src_path=str(p), translate=True)
    notes: list[str] = []
    pipeline.build_book(spec, out_dir=str(tmp_path), verbose=False, on_log=notes.append)
    assert any("exceeds KDP's 828-page maximum" in n for n in notes), notes


def test_a_book_within_the_limit_is_not_nagged(tmp_path, monkeypatch, no_download):
    monkeypatch.setattr(pipeline.render_pdf, "render",
                        lambda *a, **k: (str(tmp_path / "x.pdf"), 300))
    p = tmp_path / "o.txt"
    p.write_text("Dies ist ein Satz. Und hier ein zweiter.\n", encoding="utf-8")
    spec = _spec(mode="prose", src_path=str(p), translate=True)
    notes: list[str] = []
    pipeline.build_book(spec, out_dir=str(tmp_path), verbose=False, on_log=notes.append)
    assert not any("exceeds KDP" in n for n in notes)


# --------------------------------------------------------------------------- #
# Remembering what the model already said
# --------------------------------------------------------------------------- #
class _Counting:
    """A named translator that records every batch it is actually asked for."""

    def __init__(self, model_name="test/model"):
        self.model_name = model_name
        self.seen: list[list[str]] = []

    def __call__(self, texts):
        self.seen.append(list(texts))
        return [t.upper() for t in texts]

    @property
    def calls(self):
        return sum(len(b) for b in self.seen)


def test_cache_returns_the_same_answers_as_a_direct_call(tmp_path):
    from book_creator import mt_cache
    db = tmp_path / "mt.db"
    tr = _Counting()
    texts = ["eins", "zwei", "drei"]
    assert mt_cache.translate(tr, texts, db_path=db) == ["EINS", "ZWEI", "DREI"]


def test_a_rebuild_does_not_pay_for_the_model_twice(tmp_path):
    """The whole point: a book is rebuilt for reasons unrelated to its text."""
    from book_creator import mt_cache
    db = tmp_path / "mt.db"
    tr = _Counting()
    texts = ["eins", "zwei", "drei"]
    first = mt_cache.translate(tr, texts, db_path=db)
    assert tr.calls == 3
    second = mt_cache.translate(tr, texts, db_path=db)
    assert second == first
    assert tr.calls == 3, "second run re-translated text it already had"


def test_only_the_new_segments_reach_the_model(tmp_path):
    from book_creator import mt_cache
    db = tmp_path / "mt.db"
    tr = _Counting()
    mt_cache.translate(tr, ["eins", "zwei"], db_path=db)
    tr.seen.clear()
    out = mt_cache.translate(tr, ["eins", "zwei", "drei"], db_path=db)
    assert out == ["EINS", "ZWEI", "DREI"]
    assert [t for b in tr.seen for t in b] == ["drei"]


def test_a_repeated_line_is_translated_once(tmp_path):
    # A refrain, or the same blank formula, should not be paid for each time.
    from book_creator import mt_cache
    tr = _Counting()
    out = mt_cache.translate(tr, ["ja", "ja", "nein", "ja"], db_path=tmp_path / "mt.db")
    assert out == ["JA", "JA", "NEIN", "JA"]
    assert sorted(t for b in tr.seen for t in b) == ["ja", "nein"]


def test_different_models_do_not_share_answers(tmp_path):
    from book_creator import mt_cache
    db = tmp_path / "mt.db"
    a, b = _Counting("org/model-a"), _Counting("org/model-b")
    mt_cache.translate(a, ["eins"], db_path=db)
    b.seen.clear()
    mt_cache.translate(b, ["eins"], db_path=db)
    assert [t for x in b.seen for t in x] == ["eins"], "served another model's output"


def test_an_anonymous_translator_is_not_cached(tmp_path):
    """Two bare functions would otherwise share one key and be served each
    other's translations. Slower is better than wrong."""
    from book_creator import mt_cache
    db = tmp_path / "mt.db"
    calls = []

    def anon(texts):
        calls.append(list(texts))
        return [t.upper() for t in texts]

    assert mt_cache.translator_id(anon) is None
    mt_cache.translate(anon, ["eins"], db_path=db)
    mt_cache.translate(anon, ["eins"], db_path=db)
    assert len(calls) == 2, "an unnameable translator must not be cached"


def test_an_http_translator_is_named_by_its_url(tmp_path):
    from book_creator import mt_cache
    tr = translators.HTTPTranslator("http://localhost:8001/translate", src_lang="la")
    assert mt_cache.translator_id(tr) == "url:http://localhost:8001/translate"


def test_cache_reports_what_it_reused(tmp_path):
    from book_creator import mt_cache
    db = tmp_path / "mt.db"
    tr = _Counting()
    mt_cache.translate(tr, ["eins", "zwei"], db_path=db)
    notes: list[str] = []
    mt_cache.translate(tr, ["eins", "zwei", "drei"], db_path=db, log=notes.append)
    assert any("reusing 2" in n for n in notes), notes


def test_cache_refuses_a_translator_that_loses_segments(tmp_path):
    from book_creator import mt_cache

    class Lossy(_Counting):
        def __call__(self, texts):
            return [t.upper() for t in texts][:-1]

    with pytest.raises(ValueError, match="translator returned"):
        mt_cache.translate(Lossy(), ["a", "b"], db_path=tmp_path / "mt.db")


# --------------------------------------------------------------------------- #
# The latin repo's own fine-tuned models
# --------------------------------------------------------------------------- #
def test_latin_translator_is_named_after_the_model_it_runs(tmp_path):
    """mt_cache keys on the name, so the Latin model must not share a key with
    anything else — and must keep its own answers between builds."""
    from book_creator import latin_translator, mt_cache
    tr = latin_translator.LatinRepoTranslator("la")
    assert tr.model_name == "latin-repo:models/nllb-latin"
    assert mt_cache.translator_id(tr) == "model_name:latin-repo:models/nllb-latin"


def test_latin_translator_knows_greek_too():
    from book_creator import latin_translator
    tr = latin_translator.LatinRepoTranslator("grc")
    assert tr.src_lang == "ell_Grek"
    assert "greek" in tr.model


def test_latin_translator_refuses_a_language_it_has_no_model_for():
    from book_creator import latin_translator
    with pytest.raises(ValueError, match="No latin-repo model"):
        latin_translator.LatinRepoTranslator("fr")


def test_latin_translator_passes_blank_text_through_without_spawning(monkeypatch):
    """Blank-only input must not pay for a model load, and must not invent text."""
    from book_creator import latin_translator
    import subprocess

    def boom(*a, **k):
        raise AssertionError("spawned a subprocess for blank input")

    monkeypatch.setattr(subprocess, "run", boom)
    tr = latin_translator.LatinRepoTranslator("la")
    assert tr(["", "   "]) == ["", ""]


def test_latin_translator_reports_a_failed_subprocess(monkeypatch):
    from book_creator import latin_translator, corpus_jobs
    import subprocess
    monkeypatch.setattr(corpus_jobs, "find_repo", lambda p=None: Path("."))
    monkeypatch.setattr(corpus_jobs, "find_python", lambda r: Path("python"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0] if a else [], 1, stdout="", stderr="CUDA out of memory"))
    tr = latin_translator.LatinRepoTranslator("la")
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        tr(["Gallia est omnis divisa in partes tres."])


def test_latin_translator_rejects_a_short_result(monkeypatch):
    from book_creator import latin_translator, corpus_jobs
    import subprocess, json as _json
    monkeypatch.setattr(corpus_jobs, "find_repo", lambda p=None: Path("."))
    monkeypatch.setattr(corpus_jobs, "find_python", lambda r: Path("python"))
    body = "\n===TRANSLATIONS===\n" + _json.dumps({"translations": ["one"]})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0] if a else [], 0, stdout=body, stderr=""))
    tr = latin_translator.LatinRepoTranslator("la")
    with pytest.raises(ValueError, match="translator returned"):
        tr(["unum", "duo"])


def test_translate_uses_the_latin_repo_for_latin(source_file, monkeypatch):
    """Latin must not fall through to the Opus-MT branch: there is no
    opus-mt-la-en, and the Italic model renders "Arma virumque cano" as
    "Guns for man who is lame"."""
    from book_creator import latin_translator
    monkeypatch.setattr(latin_translator, "available", lambda repo=None: (True, "/repo"))
    stub = _Named(f"latin-repo:models/nllb-la")
    stub.model = "models/nllb-latin"
    monkeypatch.setattr(latin_translator, "register", lambda lang, **k: stub)
    spec = _spec(mode="prose", src_lang="la", src_path=source_file, translate=True)
    notes: list[str] = []
    chapters = pipeline._chapters_from_machine_translation(spec, notes.append)
    assert [b for ch in chapters for b in ch.beads]
    assert any("latin repo" in n for n in notes), notes


def test_translate_says_so_when_the_latin_repo_is_missing(source_file, monkeypatch):
    from book_creator import latin_translator
    monkeypatch.setattr(latin_translator, "available",
                        lambda repo=None: (False, "no corpus.db found"))
    spec = _spec(mode="prose", src_lang="la", src_path=source_file, translate=True)
    with pytest.raises(ValueError, match="no corpus.db found"):
        pipeline._chapters_from_machine_translation(spec, lambda _m: None)


def test_verse_line_pairing_pairs_each_line(tmp_path):
    """A line-for-line crib (Garnett's Maldon) loses everything to block
    pairing: 325 lines of Old English then 325 of English is not a facing text."""
    src = "brocen wurde;\nhet tha hyssa hwaene\nfeorr afysan\nhicgan to handum"
    tgt = "was broken.\nThen bade he each youth\nTo hasten afar\nBe mindful of might"
    spec = _spec(verse_align="line", aligner="gale-church")
    beads = pipeline._align_paired([(("", src), ("", tgt))], spec, lambda _m: None)[0].beads
    assert len(beads) == 4
    assert all(b.src and b.tgt and b.lines for b in beads)
    assert beads[0].src == ["brocen wurde;"] and beads[0].tgt == ["was broken."]
