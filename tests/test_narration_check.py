"""Checking a finished narration: blanks, loops, mismatches, and the manifest."""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np
import pytest

from book_creator import narration_check as nc


# --------------------------------------------------------------------------- #
# Fixtures: a synthetic narration
# --------------------------------------------------------------------------- #
SR = 24000


def _tone(seconds: float, level: float = 0.3) -> np.ndarray:
    """Something that is plainly speech-loud, without needing a TTS model."""
    t = np.arange(int(seconds * SR)) / SR
    return (level * np.sin(2 * math.pi * 180.0 * t)).astype("float32")


def _quiet(seconds: float, level: float = 0.002) -> np.ndarray:
    """A model breathing rather than speaking: audible, but not a reading.

    Deliberately NOT digital zero -- that is the shape a real blank has, and
    a checker that only looks for true silence walks straight past it.
    """
    rng = np.random.default_rng(0)
    return (level * rng.standard_normal(int(seconds * SR))).astype("float32")


def _write(path: Path, *parts: np.ndarray) -> Path:
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


@pytest.fixture()
def narration(tmp_path: Path) -> Path:
    """A one-chapter narration with a 6-second blank in the middle of it."""
    d = tmp_path / "book-audio"
    _write(d / "ch001.wav",
           _tone(4.0), _quiet(1.0),      # a sentence, then a normal pause
           _tone(4.0), _quiet(6.0),      # a sentence, then the blank
           _tone(4.0), _quiet(1.5))      # a sentence, then the tail
    return d


# --------------------------------------------------------------------------- #
# Pass 1: the signal
# --------------------------------------------------------------------------- #
def test_finds_a_blank_that_is_not_digital_silence(narration):
    gaps = nc.silent_gaps(narration / "ch001.wav")
    assert len(gaps) == 1
    start, end = gaps[0]
    assert start == pytest.approx(9.0, abs=0.2)
    assert end - start == pytest.approx(6.0, abs=0.2)


def test_ordinary_pauses_are_not_blanks(narration):
    # The 1.0s and 1.5s pauses are what the planner inserts between beads; a
    # checker that flagged those would flag every book ever built.
    assert all(end - start > 3.0 for start, end in
               nc.silent_gaps(narration / "ch001.wav"))


def test_trailing_silence_is_not_reported(tmp_path):
    d = tmp_path / "audio"
    _write(d / "ch001.wav", _tone(4.0), _quiet(8.0))
    assert nc.scan_signal(d, log=lambda *_: None) == []


def test_silence_floor_follows_the_book_it_is_given():
    # A quietly mastered chapter must not read as one long blank: the floor is
    # measured against the speech in the same chapter.
    loud = 20 * np.log10(np.full(1000, 0.3))
    soft = 20 * np.log10(np.full(1000, 0.02))
    assert nc.silence_floor(loud) > nc.silence_floor(soft) - 0.01
    assert nc.silence_floor(loud) <= nc.SILENCE_CEILING


def test_a_report_with_no_findings_says_so(narration, tmp_path):
    empty = tmp_path / "clean-audio"
    _write(empty / "ch001.wav", _tone(4.0), _quiet(1.0), _tone(4.0))
    report = nc.check(empty, log=lambda *_: None)
    assert report.findings == []
    assert "Nothing flagged" in nc.format_report(report)


def test_missing_audio_is_an_error_not_a_pass(tmp_path):
    with pytest.raises(nc.NarrationCheckError):
        nc.check(tmp_path / "nowhere", log=lambda *_: None)
    (tmp_path / "empty").mkdir()
    with pytest.raises(nc.NarrationCheckError):
        nc.check(tmp_path / "empty", log=lambda *_: None)


# --------------------------------------------------------------------------- #
# The manifest
# --------------------------------------------------------------------------- #
def _manifest(d: Path) -> dict:
    data = {
        "slug": "book", "engine": "chatterbox", "src_lang": "la",
        "tgt_lang": "en",
        "chapters": [{
            "index": 1, "title": "I", "file": "ch001.wav", "seconds": 20.5,
            "utterances": [
                {"key": "aaa", "text": "Arma virumque cano.", "lang": "la",
                 "start": 0.0, "end": 4.0, "silent": False},
                {"key": "bbb", "text": "I sing of arms and the man.",
                 "lang": "en", "start": 5.0, "end": 9.0, "silent": False},
                {"key": "ccc", "text": "Troiae qui primus ab oris.",
                 "lang": "la", "start": 9.0, "end": 15.0, "silent": True},
            ],
        }],
    }
    (d / nc.MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")
    return data


def test_a_blank_is_named_when_a_manifest_says_what_was_missed(narration):
    _manifest(narration)
    findings = nc.scan_signal(narration, manifest=nc.load_manifest(narration),
                              log=lambda *_: None)
    assert len(findings) == 1
    assert findings[0].text == "Troiae qui primus ab oris."
    assert findings[0].key == "ccc"


def test_without_a_manifest_the_report_says_what_it_cannot_do(narration):
    report = nc.check(narration, log=lambda *_: None)
    assert report.findings and not report.findings[0].key
    assert any("manifest" in note for note in report.notes)


def test_chapters_are_matched_by_file_not_by_position(tmp_path):
    # A chapter that came out empty is dropped from the book but still spends
    # its number, so ch002.wav can be the first file on disk.
    d = tmp_path / "audio"
    _write(d / "ch002.wav", _tone(2.0))
    manifest = {"chapters": [
        {"index": 1, "file": "ch001.wav", "utterances": [{"key": "wrong"}]},
        {"index": 2, "file": "ch002.wav", "utterances": [{"key": "right"}]},
    ]}
    record = nc._chapter_record(manifest, 1, "ch002.wav")
    assert record["utterances"][0]["key"] == "right"


def test_quarantine_moves_only_the_flagged_clips(tmp_path):
    cache = tmp_path / "tts" / "chatterbox"
    cache.mkdir(parents=True)
    for key in ("bad", "good"):
        (cache / f"{key}.wav").write_bytes(b"RIFF")
    report = nc.Report(audio_dir="x", findings=[
        nc.Finding(kind="blank", chapter=1, start=0, end=1, detail="",
                   key="bad"),
        nc.Finding(kind="blank", chapter=1, start=2, end=3, detail=""),
    ])
    assert nc.quarantine(report, cache_dir=str(tmp_path / "tts"),
                         log=lambda *_: None) == 1
    assert not (cache / "bad.wav").exists()
    assert (cache / "quarantine" / "bad.wav").exists()
    assert (cache / "good.wav").exists()


# --------------------------------------------------------------------------- #
# Pass 2: comparing the transcript to the text
# --------------------------------------------------------------------------- #
def test_similarity_recognizes_a_faithful_reading():
    said = "The subaltern had been ordered to hold the ridge."
    heard = "the subaltern had been ordered to hold the ridge"
    assert nc.similarity(said, heard) > 0.95


def test_similarity_rejects_gibberish():
    said = "The subaltern had been ordered to hold the ridge."
    heard = "ta ta ta ta ta ta ta"
    assert nc.similarity(said, heard) < 0.45


def test_latin_read_by_an_italian_voice_still_matches():
    # Chatterbox reads Latin with an Italian voice, so an Italian recognizer
    # spells it as it sounds. Without the sound fold every Latin line in the
    # book would be reported as a misreading.
    said = "Quis custodiet ipsos custodes?"
    heard = "Cuis custodiet ipsos custodes"
    assert nc.similarity(said, heard, fold_sound=True) > 0.9


def test_a_written_sound_is_not_a_loop():
    """Books make sounds, and every one of these is read correctly.

    Counting repeats alone cannot tell them from a stuck model; counting how
    FAR the repetition goes can, because written onomatopoeia stops at three or
    four and a model that has come off the rails does not stop.
    """
    for sound in ["Whirra, Whirra, Whirra, Phut, Phut, Phut!",
                  "Whoo-Whoo-Whoo-WHOO-CRASH!",
                  "Huh, huh, huh, huh, giggled Heywood",
                  "Crack, crack, crack went the rifles",
                  "something going on on the right"]:
        assert nc.longest_repeat(sound) < nc.LOOP_REPEATS, sound


def test_a_runaway_repeat_is_a_loop():
    assert nc.longest_repeat("and and and and and and and and") >= nc.LOOP_REPEATS
    assert nc.longest_repeat("the man had had enough of it") == 2
    assert nc.longest_repeat("") == 0


def test_statistics_flag_a_looping_segment():
    segments = [{"start": 0.0, "end": 5.0, "text": "ho ho ho ho ho ho ho",
                 "avg_logprob": -0.3, "compression_ratio": 3.1,
                 "no_speech_prob": 0.01}]
    found = nc._statistic_findings(segments, 1)
    assert [f.kind for f in found] == ["loop"]


def test_statistics_flag_an_unintelligible_segment():
    segments = [{"start": 0.0, "end": 5.0, "text": "mnh grr",
                 "avg_logprob": -1.8, "compression_ratio": 1.1,
                 "no_speech_prob": 0.2}]
    found = nc._statistic_findings(segments, 1)
    assert [f.kind for f in found] == ["mumble"]


def test_a_clean_segment_is_not_flagged():
    segments = [{"start": 0.0, "end": 5.0,
                 "text": "It was the best of times, it was the worst of times.",
                 "avg_logprob": -0.25, "compression_ratio": 1.6,
                 "no_speech_prob": 0.01}]
    assert nc._statistic_findings(segments, 1) == []


def test_mismatch_is_reported_against_the_text_that_was_given(narration):
    manifest = _manifest(narration)
    record = manifest["chapters"][0]
    segments = [{"start": 0.0, "end": 4.0, "text": "blah blah blah blah blah",
                 "avg_logprob": -0.2, "compression_ratio": 1.2,
                 "no_speech_prob": 0.0},
                {"start": 5.0, "end": 9.0,
                 "text": "I sing of arms and the man",
                 "avg_logprob": -0.2, "compression_ratio": 1.2,
                 "no_speech_prob": 0.0}]
    found = nc._mismatch_findings(segments, 1, record, {"la"}, 0.45)
    assert [f.text for f in found] == ["Arma virumque cano."]
    assert found[0].key == "aaa"


def test_short_utterances_are_not_scored(narration):
    record = {"utterances": [{"key": "k", "text": "Yes.", "lang": "en",
                              "start": 0.0, "end": 1.0}]}
    assert nc._mismatch_findings([], 1, record, set(), 0.45) == []


def test_report_names_a_timestamp_you_can_go_and_listen_to():
    report = nc.Report(audio_dir="output/book-audio", chapters=2, seconds=600,
                       findings=[nc.Finding(kind="blank", chapter=2,
                                            start=671.0, end=679.0,
                                            detail="8.0s with nothing said",
                                            text="Troiae qui primus")])
    text = nc.format_report(report)
    assert "0:11:11" in text
    assert "Chapter 2" in text
    assert "Troiae qui primus" in text


# --------------------------------------------------------------------------- #
# Wiring into a build
# --------------------------------------------------------------------------- #
def test_the_build_checks_its_own_narration(tmp_path):
    from book_creator import pipeline
    from book_creator.model import BookSpec

    _write(tmp_path / "bk-audio" / "ch001.wav",
           _tone(4.0), _quiet(6.0), _tone(4.0))
    spec = BookSpec(title="T", author="A", src_lang="la")
    spec.audio.check = "signal"
    out: dict = {}
    logged: list[str] = []
    pipeline._check_narration(out, spec, "bk", str(tmp_path), logged.append)

    report = Path(out["narration_check"])
    assert report.exists()
    assert "0:00:04" in report.read_text(encoding="utf-8")
    assert any("flagged" in line for line in logged)


def test_the_check_can_be_turned_off(tmp_path):
    from book_creator import pipeline
    from book_creator.model import BookSpec

    _write(tmp_path / "bk-audio" / "ch001.wav", _tone(4.0), _quiet(6.0))
    spec = BookSpec(title="T", author="A", src_lang="la")
    spec.audio.check = "off"
    out: dict = {}
    pipeline._check_narration(out, spec, "bk", str(tmp_path), lambda *_: None)
    assert out == {}


def test_a_book_with_no_audio_directory_does_not_break_the_build(tmp_path):
    # The check is advisory: a narration that stopped early still produced a
    # book, and a missing directory must not turn that into a failure.
    from book_creator import pipeline
    from book_creator.model import BookSpec

    spec = BookSpec(title="T", author="A", src_lang="la")
    out: dict = {}
    logged: list[str] = []
    pipeline._check_narration(out, spec, "bk", str(tmp_path), logged.append)
    assert out == {}
    assert any("skipped" in line for line in logged)


def test_a_neighbouring_sentence_in_the_transcript_is_not_a_misreading():
    """Whisper segments straddle utterances, so the transcript lined up against
    one sentence usually carries the next one with it. Scoring that as a
    misreading would flag most of a correctly narrated bilingual book."""
    said = "The subaltern had been ordered to hold the ridge."
    heard = ("quo usque tandem abutere patientia nostra "
             "the subaltern had been ordered to hold the ridge "
             "and then the next sentence began")
    assert nc.similarity(said, heard) > 0.95


def test_a_reading_that_stops_halfway_scores_about_half():
    said = "The subaltern had been ordered to hold the ridge."
    assert 0.35 < nc.similarity(said, "the subaltern had been") < 0.6


def test_a_book_that_repeats_itself_is_not_a_looping_model():
    """Real false positives from A Subaltern's War, all read correctly.

    Shell-fire onomatopoeia and a doubled preposition set off both of
    whisper's loop statistics. The text is the arbiter: if the audio says what
    the book says, the reading is right however odd the numbers look.
    """
    record = {"utterances": [
        {"key": "a", "lang": "en", "start": 0.0, "end": 8.0,
         "text": "Whirra, Whirra, Whirra, Phut, Phut, Phut! came the "
                 "tear-shells thick and fast."},
        {"key": "b", "lang": "en", "start": 9.0, "end": 16.0,
         "text": "“They're too tired.” Whoo—Whoo—Whoo"
                 "—WHOO—CRASH!"},
    ]}
    segments = [
        {"start": 0.0, "end": 8.0, "avg_logprob": -0.6, "no_speech_prob": 0.0,
         "compression_ratio": 3.0,
         "text": "Whirra, whirra, whirra, phut, phut, phut, came the "
                 "tear-shells thick and fast."},
        {"start": 9.0, "end": 16.0, "avg_logprob": -0.7, "no_speech_prob": 0.0,
         "compression_ratio": 2.9,
         "text": "They're too tired. Whoo, whoo, whoo, whoo, crash!"},
    ]
    assert _statistics(segments, None) != [], "with no text, both look like loops"
    assert _statistics(segments, record) == [], "the text explains both"


def test_a_real_loop_survives_the_text_check():
    record = {"utterances": [
        {"key": "a", "lang": "en", "start": 0.0, "end": 8.0,
         "text": "The battalion moved up the road towards the ridge at dusk."},
    ]}
    segments = [{"start": 0.0, "end": 8.0, "avg_logprob": -0.4,
                 "no_speech_prob": 0.0, "compression_ratio": 3.4,
                 "text": "the the the the the the the the the the"}]
    assert [f.kind for f in _statistics(segments, record)] == ["loop"]


def _statistics(segments, record):
    return nc._statistic_findings(segments, 1, record, set())


def test_the_report_gives_both_chapter_and_book_timestamps():
    """The chapter WAV is where the audio is; the M4B is what people play.

    A finding 12 seconds into chapter 10 is an hour and ten minutes into the
    book, so a report that names only one of the two sends you to the wrong
    place in whichever file you opened.
    """
    report = nc.Report(audio_dir="output/bk-audio", chapters=10, seconds=9000,
                       findings=[nc.Finding(kind="blank", chapter=10,
                                            start=12.0, end=20.0,
                                            detail="8.0s", book_start=4212.0)])
    text = nc.format_report(report)
    assert "0:00:12" in text and "book 1:10:12" in text


def test_book_offsets_accumulate_across_chapters():
    findings = [nc.Finding(kind="blank", chapter=1, start=5.0, end=9.0, detail=""),
                nc.Finding(kind="blank", chapter=3, start=5.0, end=9.0, detail="")]
    nc._locate_in_book(findings, [100.0, 200.0, 300.0])
    assert [f.book_start for f in findings] == [5.0, 305.0]


def test_a_broken_check_never_loses_a_finished_audiobook(tmp_path,
                                                         monkeypatch):
    """The check is advisory. Whatever goes wrong in it -- a corrupt WAV, a
    recognizer that dies mid-run -- the narration is already on disk and the
    build has to finish."""
    from book_creator import narration_check, pipeline
    from book_creator.model import BookSpec

    _write(tmp_path / "bk-audio" / "ch001.wav", _tone(2.0))
    monkeypatch.setattr(narration_check, "check",
                        lambda *a, **k: (_ for _ in ()).throw(
                            MemoryError("recognizer fell over")))
    spec = BookSpec(title="T", author="A", src_lang="la")
    out: dict = {}
    logged: list[str] = []
    pipeline._check_narration(out, spec, "bk", str(tmp_path), logged.append)
    assert out == {}
    assert any("recognizer fell over" in line for line in logged)


def test_a_loop_names_the_clip_to_re_narrate():
    """A loop is one clip's failure, and the clip holding most of the segment
    is the one to redo. Before this, loops carried no cache key at all, so the
    finding most worth fixing was the one `quarantine` could not touch."""
    record = {"utterances": [
        {"key": "before", "text": "We dug in.", "lang": "en",
         "start": 0.0, "end": 2.0},
        {"key": "looped", "lang": "en", "start": 2.5, "end": 9.0,
         "text": "We should want it again in a day or two."},
    ]}
    segments = [{"start": 1.0, "end": 9.0, "avg_logprob": -0.3,
                 "no_speech_prob": 0.0, "compression_ratio": 1.4,
                 "text": "and should want it again in a day or two. "
                         "And, and, and, and, and day or two."}]
    found = nc._statistic_findings(segments, 14, record, set())
    assert [f.kind for f in found] == ["loop"]
    assert found[0].key == "looped"


# --------------------------------------------------------------------------- #
# Borrowing the recognizer from the venv beside this one
# --------------------------------------------------------------------------- #
def test_the_recognizer_is_found_in_a_sibling_venv(tmp_path):
    """The UI runs in the TTS venv, which cannot hold faster-whisper; the
    build that just narrated a book has to borrow a recognizer to listen."""
    (tmp_path / ".venv-tts" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv-tts" / "Scripts" / "python.exe").write_text("")
    exe = tmp_path / ".venv-asr" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert nc.recognizer_interpreter(tmp_path) is None
    (tmp_path / ".venv-asr" / "Lib" / "site-packages" / "faster_whisper").mkdir(
        parents=True)
    assert nc.recognizer_interpreter(tmp_path) == exe


def test_a_report_survives_the_trip_between_interpreters():
    report = nc.Report(audio_dir="d", chapters=2, seconds=90.0, asr=True,
                       notes=["n"], findings=[nc.Finding(
                           kind="loop", chapter=2, start=1.0, end=2.0,
                           detail="x", key="k", book_start=61.0)])
    back = nc.Report.from_dict(json.loads(json.dumps(report.to_dict())))
    assert back == report


def test_listen_mode_without_any_recognizer_still_checks_for_blanks(
        tmp_path, monkeypatch):
    from book_creator import pipeline
    from book_creator.model import BookSpec

    _write(tmp_path / "bk-audio" / "ch001.wav", _tone(4.0), _quiet(6.0),
           _tone(4.0))
    monkeypatch.setattr(nc.Recognizer, "available",
                        staticmethod(lambda: (False, "not here")))
    monkeypatch.setattr(nc, "recognizer_interpreter", lambda *a: None)
    spec = BookSpec(title="T", author="A", src_lang="la")
    spec.audio.check = "listen"
    out: dict = {}
    logged: list[str] = []
    pipeline._check_narration(out, spec, "bk", str(tmp_path), logged.append)
    assert out["narration_check"]
    assert any("blanks only" in line for line in logged)
