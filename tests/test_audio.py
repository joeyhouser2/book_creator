"""Audiobook pipeline: text preparation, planning, synthesis, assembly."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from book_creator import audio
from book_creator.model import AudioSpec, Bead, Chapter


# --------------------------------------------------------------------------- #
# Text preparation
# --------------------------------------------------------------------------- #
def test_chunk_text_splits_on_punctuation_within_limit():
    long = ("Gallia est omnis divisa in partes tres, quarum unam incolunt "
            "Belgae, aliam Aquitani, tertiam qui ipsorum lingua Celtae, nostra "
            "Galli appellantur.")
    chunks = audio.chunk_text(long, 60)
    assert len(chunks) > 1
    assert all(len(c) <= 60 for c in chunks)
    # Nothing may be lost: a dropped clause would be silently missing audio.
    assert " ".join(chunks).split() == long.split()


def test_chunk_text_passes_short_text_through():
    assert audio.chunk_text("Brevis.", 300) == ["Brevis."]
    assert audio.chunk_text("", 300) == []


def test_chunk_text_hard_splits_an_overlong_clause():
    # No punctuation to break on, so it must fall back to a word split rather
    # than hand the model something past its trained length.
    words = " ".join(["verbum"] * 60)
    chunks = audio.chunk_text(words, 50)
    assert all(len(c) <= 50 for c in chunks)
    assert " ".join(chunks).split() == words.split()


@pytest.mark.parametrize("raw,expected", [
    # Whole-note brackets are *about* the text, so they go entirely.
    ("Altus [p. 42] auctor omnium", "Altus auctor omnium"),
    ("verbum [Illustration] aliud", "verbum aliud"),
    # In-word editorial sigla keep their letters: dropping the group would
    # turn "Altus" into "ltus".
    ("<A>ltus Imp(erator) es", "Altus Imperator es"),
    ("[Aug]ustus", "ustus"),
    # Line/page break markers are not spoken.
    ("verbum / aliud", "verbum aliud"),
    ("  spaced   out  ", "spaced out"),
])
def test_speakable(raw, expected):
    assert audio.speakable(raw) == expected


def test_voice_lang_maps_dead_languages_to_living_voices():
    # No TTS model has Latin or Ancient Greek; these substitutions are the
    # documented convention, and callers rely on them.
    assert audio.voice_lang("la") == "it"
    assert audio.voice_lang("grc") == "el"
    assert audio.voice_lang("fr") == "fr"
    assert audio.voice_lang("en") == "en"


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def _spec(**kw):
    base = dict(enabled=True, engine="tone", device="cpu")
    base.update(kw)
    return AudioSpec(**base)


def test_plan_orders_heading_then_source_then_translation(chapters):
    spec = _spec(announce_chapters=True)
    plans = audio.plan(chapters, spec=spec, src_lang="la", tgt_lang="en")

    title, items = plans[0]
    assert title == "Liber I"
    assert items[0].lang == "en", "the chapter heading is read in the target language"
    assert (items[1].lang, items[2].lang) == ("la", "en")
    assert items[2].pause_after == spec.pause_bead, "bead boundary gets the longer gap"
    assert items[1].pause_after == spec.pause_within


def test_plan_first_tgt_flips_each_pair(chapters):
    spec = _spec(announce_chapters=False, first="tgt")
    _, items = audio.plan(chapters, spec=spec, src_lang="la", tgt_lang="en")[0]
    assert (items[0].lang, items[1].lang) == ("en", "la")


def test_plan_titles_travel_with_their_utterances(chapters):
    # Regression: titles used to be looked up by index afterwards, so a skipped
    # chapter shifted every M4B marker onto the wrong chapter.
    plans = audio.plan(chapters, spec=_spec(), src_lang="la", tgt_lang="en")
    assert [t for t, _ in plans] == ["Liber I", "Liber II"]


def test_max_beads_counts_beads_not_utterances(chapters):
    spec = _spec(max_beads=2, announce_chapters=True)
    plans = audio.plan(chapters, spec=spec, src_lang="la", tgt_lang="en")
    spoken = sum(1 for _, items in plans for u in items if u.lang == "la")
    assert spoken == 2


def test_max_beads_drops_a_chapter_left_with_only_its_heading(chapters):
    # 2 beads exhausts chapter one, so chapter two would contain nothing but
    # its own announcement -- not worth a track or a chapter marker.
    plans = audio.plan(chapters, spec=_spec(max_beads=2), src_lang="la", tgt_lang="en")
    assert len(plans) == 1


def test_estimate_is_proportional_to_text(chapters):
    est = audio.estimate(chapters, spec=_spec(announce_chapters=False),
                         src_lang="la", tgt_lang="en")
    assert est["chapters"] == 2
    assert est["utterances"] == 6          # 3 beads x 2 sides
    assert est["seconds"] > 0
    assert "h " in est["duration"]


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #
def test_catalog_reports_install_status_and_licence():
    entries = {e["id"]: e for e in audio.catalog()}
    assert {"chatterbox", "kokoro", "xtts"} <= set(entries)
    assert entries["chatterbox"]["licence"] == "MIT"
    # XTTS is non-commercial; the UI depends on that being visible.
    assert "non-commercial" in entries["xtts"]["licence"].lower()
    for e in entries.values():
        assert e["installed"] or e["reason"], "an uninstalled engine must say how to get it"


def test_unknown_engine_names_the_alternatives():
    with pytest.raises(audio.AudioError, match="chatterbox"):
        audio.get("nonesuch")


def test_engine_language_support_accounts_for_the_voice_fallback():
    chatterbox = audio.get("chatterbox")
    assert chatterbox.supports("la"), "Latin is read with the Italian voice"
    assert chatterbox.supports("grc"), "Ancient Greek is read with the Greek voice"
    kokoro = audio.get("kokoro")
    assert kokoro.supports("la")
    assert not kokoro.supports("grc"), "Kokoro has no Greek voice"


def test_best_device_prefers_memory_over_order():
    # CUDA orders devices fastest-first, so cuda:0 is often the smaller card;
    # what decides whether a model fits is memory.
    gpus = [{"id": "cuda:0", "memory_gb": 12.0}, {"id": "cuda:1", "memory_gb": 16.0}]
    assert audio.best_device(gpus) == "cuda:1"
    assert audio.best_device([]) == "cpu"


def test_devices_reports_a_recommendation():
    info = audio.devices()
    assert info["recommended"]
    assert any(d["id"] == "cpu" for d in info["devices"])


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #
def _build(chapters, tmp_path, tone_engine, **spec_kw):
    return audio.build_audiobook(
        chapters, spec=_spec(**spec_kw), out_dir=str(tmp_path), slug="bk",
        title="Test Book", author="Nemo", src_lang="la", tgt_lang="en",
        cache_dir=str(tmp_path / "cache"), log=lambda _m: None)


def test_build_produces_a_track_per_chapter(chapters, tmp_path, tone_engine):
    res = _build(chapters, tmp_path, tone_engine)
    assert res["chapters"] == 2
    assert len(res["chapter_wavs"]) == 2
    assert all(Path(p).exists() for p in res["chapter_wavs"])
    assert res["seconds"] > 0
    assert tone_engine.loaded_on == "cpu"
    assert tone_engine.calls > 0


def test_build_reuses_the_utterance_cache(chapters, tmp_path, tone_engine):
    first = _build(chapters, tmp_path, tone_engine)
    calls = tone_engine.calls
    second = _build(chapters, tmp_path, tone_engine)
    assert tone_engine.calls == calls, "a re-run must not re-synthesize"
    assert second["seconds"] == first["seconds"]


def test_build_refuses_a_language_the_engine_cannot_read(chapters, tmp_path,
                                                         tone_engine):
    # An installed engine that simply lacks the voice must fail loudly rather
    # than silently narrate one side. (An engine that isn't installed at all is
    # reported first -- see test_build_reports_a_missing_engine.)
    tone_engine.languages = ("en",)
    with pytest.raises(audio.AudioError, match="el"):
        audio.build_audiobook(
            chapters, spec=_spec(), out_dir=str(tmp_path), slug="bk",
            title="T", author="A", src_lang="grc", tgt_lang="en",
            cache_dir=str(tmp_path / "c"), log=lambda _m: None)


def test_only_spoken_languages_are_checked(chapters, tmp_path, tone_engine):
    """A translation-only audiobook reads no Greek, so a missing Greek voice
    is irrelevant to it.

    Checking both languages regardless refused perfectly buildable English
    audiobooks, and announced a substitute Greek voice that was never used.
    """
    from book_creator.pipeline import apply_sides

    tone_engine.languages = ("en",)          # no Greek voice at all
    english_only = apply_sides(chapters, "tgt", lambda _m: None)

    msgs = []
    res = audio.build_audiobook(
        english_only, spec=_spec(announce_chapters=False), out_dir=str(tmp_path),
        slug="bk", title="T", author="A", src_lang="grc", tgt_lang="en",
        cache_dir=str(tmp_path / "c"), log=msgs.append)
    assert res["chapters"] >= 1
    assert not any("grc" in m for m in msgs), msgs


def test_build_reports_a_missing_engine(chapters, tmp_path):
    # The install check comes first: without the package there is nothing to
    # check languages against, and the message has to say how to fix it.
    with pytest.raises(audio.AudioError, match="pip install"):
        audio.build_audiobook(
            chapters, spec=_spec(engine="kokoro"), out_dir=str(tmp_path),
            slug="bk", title="T", author="A", src_lang="la", tgt_lang="en",
            cache_dir=str(tmp_path / "c"), log=lambda _m: None)


def test_build_rejects_empty_input(tmp_path, tone_engine):
    with pytest.raises(audio.AudioError, match="[Nn]othing to narrate"):
        audio.build_audiobook(
            [], spec=_spec(), out_dir=str(tmp_path), slug="bk",
            title="T", author="A", src_lang="la", tgt_lang="en",
            cache_dir=str(tmp_path / "c"), log=lambda _m: None)


@pytest.mark.skipif(audio.ffmpeg_exe() is None, reason="ffmpeg not available")
def test_m4b_carries_chapter_markers_and_metadata(chapters, tmp_path, tone_engine):
    res = _build(chapters, tmp_path, tone_engine, format="m4b")
    assert res["book"] and Path(res["book"]).exists()

    probe = subprocess.run(
        [audio.ffmpeg_exe(), "-i", res["book"], "-f", "ffmetadata", "-"],
        capture_output=True, text=True, encoding="utf-8")
    meta = probe.stdout
    assert meta.count("[CHAPTER]") == res["chapters"]
    assert "title=Test Book" in meta
    # The chapter names must be the real ones, in order.
    assert meta.index("title=Liber I") < meta.index("title=Liber II")


def test_stop_signal_halts_synthesis(chapters, tmp_path, tone_engine):
    res = audio.build_audiobook(
        chapters, spec=_spec(), out_dir=str(tmp_path), slug="bk",
        title="T", author="A", src_lang="la", tgt_lang="en",
        cache_dir=str(tmp_path / "c"), log=lambda _m: None,
        should_stop=lambda: tone_engine.calls >= 2)
    # It stops early but still assembles what it managed to narrate, rather
    # than throwing away the GPU time already spent.
    assert res["chapters"] >= 1
    assert tone_engine.calls < 6


# --------------------------------------------------------------------------- #
# Nothing unpronounceable reaches the model
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["...", "…", "— — —", "***", "  .  ", "()"])
def test_punctuation_only_text_is_not_speakable(text):
    """An ellipsis on its own line is ordinary in a novel, and it used to
    survive every tidying rule and still be truthy. It then reached the model,
    which tokenized it to nothing and reduced over an empty tensor:
    "max(): Expected reduction dim 1 to have non-zero size" — nine hours into
    a run, with no indication which text caused it."""
    assert audio.speakable(text) == ""


@pytest.mark.parametrize("text", ["Gallia est omnis.", "42", "Ἱστορίαι",
                                  "L'an 40", "a"])
def test_real_text_is_still_speakable(text):
    assert audio.speakable(text)


def test_a_bead_with_nothing_sayable_is_dropped_from_the_plan():
    beads = [Bead(src=["..."], tgt=["..."]),
             Bead(src=["Gallia est omnis."], tgt=["All Gaul is divided."])]
    chapters = [Chapter(title="I", beads=beads)]
    plans = audio.plan(chapters, spec=AudioSpec(), src_lang="la", tgt_lang="en")
    said = [u.text for _, items in plans for u in items]
    assert "..." not in said
    assert any("Gallia" in t for t in said)


def test_chunk_text_never_emits_an_empty_chunk():
    """A first word longer than the limit used to flush an empty line."""
    long_word = "x" * 90
    for text in (long_word, f"{long_word} {long_word}", f"a {long_word}"):
        chunks = audio.chunk_text(text, 40)
        assert all(c.strip() for c in chunks), chunks


def test_estimate_names_a_substituted_voice():
    """Latin is read with an Italian voice by design — but so is a book whose
    language was left at the default, and that is worth seeing before the
    GPU spends hours on it."""
    chapters = [Chapter(title="I", beads=[
        Bead(src=["Gallia est omnis divisa."], tgt=["All Gaul is divided."])])]
    est = audio.estimate(chapters, spec=AudioSpec(), src_lang="la", tgt_lang="en")
    by_lang = {L["lang"]: L for L in est["languages"]}
    assert by_lang["la"]["substituted"] and by_lang["la"]["voice_lang"] == "it"
    assert not by_lang["en"]["substituted"]


# --------------------------------------------------------------------------- #
# The narration manifest, and not caching a failure
# --------------------------------------------------------------------------- #
def test_build_writes_a_manifest_of_what_was_said_when(chapters, tmp_path,
                                                       tone_engine):
    import json

    _build(chapters, tmp_path, tone_engine)
    data = json.loads((tmp_path / "bk-audio" / "manifest.json")
                      .read_text(encoding="utf-8"))
    assert data["engine"] == "tone"
    assert [ch["file"] for ch in data["chapters"]] == ["ch001.wav", "ch002.wav"]

    first = data["chapters"][0]["utterances"]
    assert [u["lang"] for u in first[:3]] == ["en", "la", "en"]
    # Spans have to be monotonic and inside the chapter, or a finding would
    # point at the wrong ten seconds of a six-hour book.
    assert all(u["start"] <= u["end"] for u in first)
    assert all(a["end"] <= b["start"] for a, b in zip(first, first[1:]))
    assert first[-1]["end"] <= data["chapters"][0]["seconds"]
    assert all(u["key"] for u in first)


def test_a_failed_utterance_is_not_cached_as_silence(chapters, tmp_path,
                                                     tone_engine):
    """An empty result must not become permanent.

    Caching it meant every later run of the book found the entry, reused the
    silence, and the missing sentence could never come back -- the build was
    then unable to fix itself even once the engine's bad day was over.
    """
    def _refuse(text, *, lang, voice=None):
        raise IndexError("engine cannot read this")

    tone_engine.synthesize = _refuse
    res = _build(chapters, tmp_path, tone_engine, max_beads=1,
                 announce_chapters=False)
    assert res["chapters"] >= 1
    assert list((tmp_path / "cache" / "tone").glob("*.wav")) == []


def test_a_silent_utterance_is_marked_in_the_manifest(chapters, tmp_path,
                                                      tone_engine):
    import json

    calls = {"n": 0}
    real = tone_engine.synthesize

    def _fail_first(text, *, lang, voice=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IndexError("engine cannot read this")
        return real(text, lang=lang, voice=voice)

    tone_engine.synthesize = _fail_first
    _build(chapters, tmp_path, tone_engine)
    data = json.loads((tmp_path / "bk-audio" / "manifest.json")
                      .read_text(encoding="utf-8"))
    silent = [u for ch in data["chapters"] for u in ch["utterances"]
              if u["silent"]]
    assert len(silent) == 1, "the dropped fragment is recorded, not hidden"
    assert silent[0]["start"] == silent[0]["end"]


# --------------------------------------------------------------------------- #
# Only language reaches the narrator
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("junk", [
    "15", "1916.", "22,2", "E.", "i",           # a scan's page numbers
    "PAGE 113 129 186",                         # an index line
    "¢ i = ; B Monchyg t¢ g 1 © 2 : be 9 2 2 eZ22",
    # A fold-out map label, from the same memoir: real place names, but
    # buried in the symbols a map OCRs into.
    "A Poelcanelle % % % %, ghemarcg oN I, % B nche S ° ¢ g Lake",
    "| | 1 | |",
])
def test_a_scans_non_text_is_not_narrated(junk):
    """OCR does not only misspell; it produces things that are not language.

    A memoir scanned from plates handed the narrator its contents page and the
    labels off a fold-out map, and the narrator read them: minutes of a chapter
    spent enumerating page numbers. Nothing was wrong with the narration — the
    text should never have reached it.
    """
    assert audio.narratable(junk) == ""


@pytest.mark.parametrize("real", [
    # Dialogue as the memoir's OCR actually delivers it: quote marks welded on
    # or floating free. An earlier version of the gate scored every one of
    # these as junk and dropped it -- silently, which is the worst way a
    # sentence can go missing from an audiobook.
    "“No?", "“Aw!", "Ha, Ha, Ha!",
    "”’ “No,” said I, a little disgusted.",
    "‘““ Come on!’ I shouted.",
    "”’ “ Relieved !", "”’ asked I.",
    "September 1916.", "3 officers, 45 other ranks.",
    "Yes.", "No, sir.", "It was cold.", "Arma virumque cano.",
    "I sing of arms and the man.", "L'an 40 arriva.", "Où est-il ?",
    "Ἱστορίαι δὲ αἱ Ἡροδότου.",                 # the gate must be script-blind
    "«Пойдём», сказал он.",
])
def test_real_language_still_reaches_the_narrator(real):
    assert audio.narratable(real)


def test_the_gate_clears_every_sentence_of_a_real_book():
    """A false drop is silent: the sentence simply never gets read. Checked
    against the repo's own fixtures rather than invented examples."""
    import re

    for name in ("caesar_b1_la.txt", "pere_goriot_en.txt",
                 "eugenie_grandet_fr.txt"):
        p = Path("input") / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)
                     if len(s.strip()) > 20][:300]
        dropped = [s for s in sentences if not audio.narratable(s)]
        assert not dropped, f"{name}: {dropped[:3]}"


def test_the_plan_reports_what_it_refused(chapters):
    chapters[0].beads.insert(0, Bead(src=["15"], tgt=["15"]))
    refused = []
    audio.plan(chapters, spec=_spec(), src_lang="la", tgt_lang="en",
               on_skip=refused.append)
    assert refused == ["15", "15"]


def test_estimate_prices_the_refusal_before_the_gpu_starts(chapters):
    chapters[0].beads.insert(0, Bead(src=["1916."], tgt=["22,2"]))
    est = audio.estimate(chapters, spec=AudioSpec(), src_lang="la", tgt_lang="en")
    assert est["not_prose"] == 2
    assert est["not_prose_sample"]
