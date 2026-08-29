"""Narrator sample discovery, and the curated LibriVox set."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

import download_voices
from book_creator import audio


def _write_wav(path: Path, seconds: float = 1.0, rate: int = 24000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def test_no_voices_directory_is_not_an_error(tmp_path):
    # The default engine ships a built-in voice, so having no clips is the
    # normal starting state rather than a misconfiguration.
    assert audio.voice_catalog(tmp_path / "absent") == []


def test_empty_voices_directory(tmp_path):
    (tmp_path / "voices").mkdir()
    assert audio.voice_catalog(tmp_path / "voices") == []


def test_catalog_parses_lang_from_the_filename(tmp_path):
    d = tmp_path / "voices"
    _write_wav(d / "la-caesar.wav")
    _write_wav(d / "grc-thucydides.wav")

    got = {v["id"]: v for v in audio.voice_catalog(d)}
    assert set(got) == {"la-caesar", "grc-thucydides"}
    assert got["la-caesar"]["lang"] == "la"
    assert got["grc-thucydides"]["lang"] == "grc"
    assert "caesar" in got["la-caesar"]["label"]
    assert got["la-caesar"]["size_kb"] > 0


def test_catalog_tolerates_an_unconventional_name(tmp_path):
    d = tmp_path / "voices"
    _write_wav(d / "mynarrator.wav")
    (entry,) = audio.voice_catalog(d)
    # Still offered, just without a language to match against.
    assert entry["id"] == "mynarrator"
    assert entry["lang"] == ""


def test_catalog_ignores_non_wav_files(tmp_path):
    d = tmp_path / "voices"
    d.mkdir()
    (d / "notes.txt").write_text("ignore me", encoding="utf-8")
    (d / "sample.mp3").write_bytes(b"\x00")
    assert audio.voice_catalog(d) == []


def test_catalog_is_sorted(tmp_path):
    d = tmp_path / "voices"
    for name in ("it-b.wav", "en-a.wav", "la-c.wav"):
        _write_wav(d / name)
    assert [v["id"] for v in audio.voice_catalog(d)] == ["en-a", "it-b", "la-c"]


# --------------------------------------------------------------------------- #
# The curated set
# --------------------------------------------------------------------------- #
def test_curated_voices_are_well_formed():
    assert download_voices.VOICES
    ids = [v.id for v in download_voices.VOICES]
    assert len(ids) == len(set(ids)), "duplicate voice ids"
    for v in download_voices.VOICES:
        # The id must parse back into a language the catalog can match on.
        assert v.id.startswith(f"{v.lang}-"), v.id
        assert v.identifier and v.file.endswith(".mp3")
        assert v.note


def test_curated_set_covers_the_languages_with_no_tts_voice():
    # Latin and Ancient Greek have no TTS voice anywhere, so a cloned human
    # reader is the only way to get real pronunciation rather than the
    # Italian/Modern-Greek approximation.
    langs = {v.lang for v in download_voices.VOICES}
    assert {"la", "grc"} <= langs
    assert "en" in langs, "the translation side needs a voice too"


def test_curated_ids_match_the_catalog_convention(tmp_path):
    d = tmp_path / "voices"
    for v in download_voices.VOICES:
        _write_wav(d / f"{v.id}.wav")
    catalog = {c["id"]: c for c in audio.voice_catalog(d)}
    for v in download_voices.VOICES:
        assert catalog[v.id]["lang"] == v.lang


def test_language_filter_selects_a_subset():
    wanted = [v for v in download_voices.VOICES if v.lang in ("la", "grc")]
    assert wanted
    assert all(v.lang in ("la", "grc") for v in wanted)


def test_list_mode_needs_no_network(capsys):
    assert download_voices.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "la-caesar" in out
    assert "public domain" in out.lower()


def test_unknown_language_is_reported(capsys):
    assert download_voices.main(["klingon"]) == 1
    out = capsys.readouterr().out
    assert "Available:" in out


def test_ffmpeg_is_discoverable():
    # The clips are trimmed with ffmpeg; imageio-ffmpeg ships one, so this
    # should hold without a system install.
    assert download_voices.ffmpeg_exe()


# --------------------------------------------------------------------------- #
# Integration with the audio spec
# --------------------------------------------------------------------------- #
def test_a_downloaded_voice_reaches_the_engine(tmp_path, tone_engine, chapters):
    from book_creator.model import AudioSpec

    voice = str(_write_wav(tmp_path / "voices" / "la-caesar.wav"))
    seen = []
    real = tone_engine.synthesize

    def spy(text, *, lang, voice=None):
        seen.append(voice)
        return real(text, lang=lang, voice=voice)

    tone_engine.synthesize = spy
    audio.build_audiobook(
        chapters,
        spec=AudioSpec(enabled=True, engine="tone", device="cpu",
                       src_voice=voice, tgt_voice=voice, max_beads=1),
        out_dir=str(tmp_path), slug="bk", title="T", author="A",
        src_lang="la", tgt_lang="en", cache_dir=str(tmp_path / "c"),
        log=lambda _m: None)
    assert seen and all(v == voice for v in seen)


def test_voice_is_part_of_the_cache_key(tmp_path):
    from book_creator.audio import Utterance, _cache_key

    a = Utterance("verbum", "la", "voices/la-caesar.wav", 0.5)
    b = Utterance("verbum", "la", "voices/la-aesop.wav", 0.5)
    # Changing narrator must invalidate the cache, or a re-run would splice
    # two different voices into one book.
    assert _cache_key("tone", a) != _cache_key("tone", b)
