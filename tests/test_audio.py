"""Audiobook pipeline: text preparation, planning, synthesis, assembly."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from book_creator import audio
from book_creator.model import AudioSpec


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
