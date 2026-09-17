"""Listen back to a finished narration and flag the parts that aren't a reading.

A TTS run of a whole book is hours long, so nobody hears most of it before it
ships. Two failures show up in practice and neither one fails the build:

* **Blanks.** A fragment the engine refused (see the `skipped` path in
  `audio.build_audiobook`) leaves an empty stretch where a sentence should be.
  The book plays on, a paragraph short.
* **Gibberish.** Neural TTS models hallucinate: given an odd fragment they
  loop a syllable, mumble, or read something that is not the text at all.
  Chatterbox does this on short or punctuation-heavy input.

Both are obvious to a listener in one second and invisible to the pipeline, so
this module plays the part of the listener. Two passes, cheapest first:

1. **Signal.** Frame RMS over the chapter WAV. A gap longer than the longest
   pause the plan ever asks for is a blank, full stop -- no model needed, and
   it runs over a 46-minute chapter in a couple of seconds.
2. **Speech recognition.** Whisper transcribes the audio and we compare what it
   heard against what the book said to read. Wrong words, a looped syllable, or
   silence where a sentence belongs all fall out of that comparison. Whisper's
   own decoding statistics (`compression_ratio`, `avg_logprob`) catch loops even
   where there is no reference text to compare against.

Nothing here edits audio. It writes a report naming chapter and timestamp so
you can go and listen to the ten seconds in question, and -- when a narration
manifest is on hand -- it can quarantine the offending entries from the TTS
cache so that re-running the build re-synthesizes only those and leaves the
rest of the hours alone.

    python check_audio.py output/subalterns-audio
    python check_audio.py output/subalterns-audio --asr --quarantine

The ASR pass needs `faster-whisper`, which is deliberately not a dependency of
anything else here; see requirements-audio.txt for why it wants its own
virtualenv.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST_NAME = "manifest.json"

# Whisper reports these per decoded segment. The thresholds are the ones
# whisper itself uses internally to decide a decode went wrong, and they are
# good hallucination detectors in their own right: a compression ratio above
# 2.4 means the text is mostly repetition ("ta ta ta ta ta"), and a mean token
# logprob below -1.0 means the model never found anything it believed in.
LOOP_COMPRESSION = 2.4
LOW_CONFIDENCE = -1.0
# ...but a transcript that matches the text this well was read correctly,
# whatever those two statistics think of it. Books repeat themselves.
READS_AS_WRITTEN = 0.6
# ...in BOTH directions. A loop adds words, so the text is still all there in
# the transcript; what gives it away is how much of the transcript is not in
# the text. On a real Chatterbox loop ("And, and, and, and, and day or two")
# that share was 0.52; on correctly read onomatopoeia it was 1.00.
SAYS_ONLY_THE_TEXT = 0.8
# A word repeated this many times running is a model that has come off the
# rails. Four is not enough: see longest_repeat.
LOOP_REPEATS = 5

# A gap this long is not a pause. The longest pause the planner ever inserts is
# AudioSpec.pause_chapter (1.5s by default) and two utterances' pauses can meet
# back to back, so the floor sits comfortably above their sum.
DEFAULT_GAP = 3.5

# What counts as silence is measured against the chapter's own speech, not
# against full scale. A blank from a TTS model is rarely digital zero -- only
# the pauses this pipeline inserts are that -- it is the model breathing,
# mumbling under its breath, or emitting its noise floor, which lands around
# -50 dBFS in Chatterbox's output. An absolute -50 threshold therefore misses
# precisely the failure worth finding, while a level 20 dB under the speech in
# the same chapter finds it in books normalized to any level.
SILENCE_BELOW_SPEECH = 20.0
# ...but never call something this loud "silence", however quiet the book is.
SILENCE_CEILING = -40.0


class NarrationCheckError(RuntimeError):
    """The check could not run (no audio, or no recognizer installed)."""


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    """One stretch of audio that does not sound like a reading of the text."""

    kind: str          # blank | loop | mumble | mismatch | clipping
    chapter: int       # 1-based index into the chapter WAVs
    start: float       # seconds into that chapter
    end: float
    detail: str        # human-readable reason
    text: str = ""     # what the book said to read, when known
    heard: str = ""    # what the recognizer actually heard
    score: float | None = None    # similarity or whisper statistic
    key: str = ""      # TTS cache key, when known -- lets us re-synthesize it
    # Where this falls in the assembled M4B rather than in its chapter, so a
    # player can seek straight to it. The chapter WAVs are concatenated in
    # order, so it is the sum of everything before this chapter plus `start`.
    book_start: float = 0.0

    @property
    def seconds(self) -> float:
        return self.end - self.start


@dataclass
class Report:
    audio_dir: str
    chapters: int = 0
    seconds: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    asr: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"audio_dir": self.audio_dir, "chapters": self.chapters,
                "seconds": round(self.seconds, 1), "asr": self.asr,
                "notes": self.notes,
                "findings": [asdict(f) for f in self.findings]}

    @classmethod
    def from_dict(cls, data: dict) -> "Report":
        return cls(audio_dir=data.get("audio_dir", ""),
                   chapters=data.get("chapters", 0),
                   seconds=data.get("seconds", 0.0), asr=data.get("asr", False),
                   notes=list(data.get("notes", [])),
                   findings=[Finding(**f) for f in data.get("findings", [])])


# --------------------------------------------------------------------------- #
# Reading the audio
# --------------------------------------------------------------------------- #
def chapter_wavs(audio_dir: str | Path) -> list[Path]:
    """The per-chapter WAVs a narration wrote, in playing order."""
    d = Path(audio_dir)
    if not d.is_dir():
        raise NarrationCheckError(f"No such audio directory: {d}")
    wavs = sorted(d.glob("ch*.wav"))
    if not wavs:
        raise NarrationCheckError(
            f"{d} has no chapter WAVs. Point this at the '<slug>-audio' "
            "directory a narration wrote, not at the M4B.")
    return wavs


def frame_levels(path: Path, frame: float = 0.05):
    """Per-frame RMS in dBFS, streamed so a long chapter never loads whole.

    A 46-minute chapter is 67 million samples; holding it as float32 costs a
    quarter of a gigabyte for a statistic that fits in a thousandth of that.
    """
    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        step = max(1, int(sr * frame))
        levels: list = []
        while True:
            raw = w.readframes(step * 64)
            if not raw:
                break
            block = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
            if channels > 1:
                block = block.reshape(-1, channels).mean(axis=1)
            usable = (block.size // step) * step
            if usable:
                rms = np.sqrt((block[:usable].reshape(-1, step) ** 2).mean(axis=1))
                levels.append(rms)
            tail = block[usable:]
            if tail.size:
                levels.append(np.sqrt((tail ** 2).mean()).reshape(1))
    if not levels:
        return np.zeros(0, dtype="float32"), frame
    rms = np.concatenate(levels)
    # -120 dBFS stands in for true digital zero so the array stays finite.
    return 20.0 * np.log10(np.maximum(rms, 1e-6)), step / sr


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


# --------------------------------------------------------------------------- #
# Pass 1: signal
# --------------------------------------------------------------------------- #
def _runs(mask, hop: float, min_run: float) -> list[tuple[float, float]]:
    """(start, end) seconds of every True run in `mask` at least min_run long.

    Walks the run-length encoding rather than the frames: a 46-minute chapter
    is a million frames and the runs in it number in the hundreds.
    """
    import numpy as np

    if mask.size == 0:
        return []
    edges = np.flatnonzero(np.diff(mask.astype("int8")))
    bounds = [0, *(edges + 1).tolist(), mask.size]
    return [(a * hop, b * hop) for a, b in zip(bounds, bounds[1:])
            if mask[a] and (b - a) * hop >= min_run]


def silence_floor(levels) -> float:
    """The dBFS level below which this chapter is not speaking."""
    import numpy as np

    if levels.size == 0:
        return SILENCE_CEILING
    speech = float(np.percentile(levels, 95))
    return min(SILENCE_CEILING, speech - SILENCE_BELOW_SPEECH)


def silent_gaps(path: Path, *, min_gap: float = DEFAULT_GAP,
                floor: float | None = None) -> list[tuple[float, float]]:
    """(start, end) of every silence longer than `min_gap` seconds."""
    levels, hop = frame_levels(path)
    return _silent_gaps(levels, hop, min_gap=min_gap, floor=floor)


def _silent_gaps(levels, hop: float, *, min_gap: float = DEFAULT_GAP,
                 floor: float | None = None) -> list[tuple[float, float]]:
    return _runs(levels < (silence_floor(levels) if floor is None else floor),
                 hop, min_gap)


def clipped_runs(path: Path, *, min_run: float = 0.05) -> list[tuple[float, float]]:
    """Stretches pinned at full scale -- a model that blew up rather than spoke."""
    levels, hop = frame_levels(path)
    return _runs(levels > -0.5, hop, min_run)


def scan_signal(audio_dir: str | Path, *, min_gap: float = DEFAULT_GAP,
                manifest: dict | None = None, log=print) -> list[Finding]:
    """Blanks and blowouts, found without loading any model."""
    out: list[Finding] = []
    for ci, wav in enumerate(chapter_wavs(audio_dir), start=1):
        # One pass over the samples answers both questions; a chapter is
        # hundreds of megabytes and reading it twice doubles the only cost
        # this pass has.
        levels, hop = frame_levels(wav)
        length = levels.size * hop
        record = _chapter_record(manifest, ci, wav.name)
        for start, end in _silent_gaps(levels, hop, min_gap=min_gap):
            # Silence running to the very end of a chapter is the final pause,
            # not a missing sentence.
            if end >= length - 0.05:
                continue
            said = _utterance_at(record, start, end)
            out.append(Finding(
                kind="blank", chapter=ci, start=start, end=end,
                detail=f"{end - start:.1f}s with nothing being said",
                text=said.get("text", "")[:200], key=said.get("key", "")))
        for start, end in _runs(levels > -0.5, hop, 0.05):
            out.append(Finding(
                kind="clipping", chapter=ci, start=start, end=end,
                detail=f"{end - start:.2f}s pinned at full scale"))
        log(f"  - chapter {ci}: {length / 60:.1f} min scanned")
    return out


# --------------------------------------------------------------------------- #
# The narration manifest
# --------------------------------------------------------------------------- #
def load_manifest(audio_dir: str | Path) -> dict | None:
    """The per-utterance record `audio.build_audiobook` writes, if there is one.

    Older narrations were built before the manifest existed, so every caller
    here has to work without one -- with less precision, because there is then
    no record of what each stretch of audio was supposed to say.
    """
    p = Path(audio_dir) / MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _chapter_record(manifest: dict | None, chapter: int,
                    name: str = "") -> dict:
    """The manifest row for one chapter WAV.

    Matched on file name first: a chapter that came out empty is dropped from
    the M4B but its number is still spent, so ch007.wav can be the sixth file
    on disk and position alone would line the manifest up against the wrong
    chapter's text.
    """
    if not manifest:
        return {}
    for ch in manifest.get("chapters", []):
        if name and ch.get("file") == name:
            return ch
    for ch in manifest.get("chapters", []):
        if not ch.get("file") and ch.get("index") == chapter:
            return ch
    return {}


def _utterance_at(record: dict, start: float, end: float) -> dict:
    """The one utterance a stretch of audio belongs to, or {}."""
    hits = [u for u in record.get("utterances", [])
            if u.get("end", 0.0) > start and u.get("start", 0.0) < end]
    return hits[0] if len(hits) == 1 else {}


# --------------------------------------------------------------------------- #
# Comparing what was heard to what was written
# --------------------------------------------------------------------------- #
# Latin and Ancient Greek are read with Italian and Modern Greek voices
# (audio.VOICE_LANG_FALLBACK), so they come back through an Italian or Greek
# recognizer spelled the way they sound rather than the way they are written:
# "caelum" is heard as "chelum", "qui" as "cui". Folding both sides through
# these equivalences compares the sound, which is the thing under test --
# without it every Latin line would look like a mismatch.
_SOUND_FOLD = [
    (r"ae|oe", "e"), (r"ph", "f"), (r"th", "t"), (r"ch", "c"), (r"qu", "c"),
    (r"k", "c"), (r"y", "i"), (r"j", "i"), (r"v", "u"), (r"h", ""),
    (r"z", "s"), (r"x", "cs"),
]


def normalize(text: str, *, fold_sound: bool = False) -> str:
    """Lowercase, unaccented, punctuation-free text for comparison."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if fold_sound:
        for pattern, repl in _SOUND_FOLD:
            text = re.sub(pattern, repl, text)
        text = re.sub(r"(.)\1+", r"\1", text)      # doubled letters sound single
    return text


def similarity(said: str, heard: str, *, fold_sound: bool = False) -> float:
    """How much of `said` can be heard in `heard`, 0..1.

    Deliberately asymmetric. Whisper segments audio its own way, and a segment
    routinely straddles two utterances -- the Latin and the English of one bead
    are four seconds apart -- so the transcript lined up against a sentence
    usually carries its neighbours with it. A symmetric ratio scores that as a
    misreading, which it is not. Coverage asks the only question worth asking:
    is this sentence in there?
    """
    a = normalize(said, fold_sound=fold_sound)
    b = normalize(heard, fold_sound=fold_sound)
    if not a:
        return 1.0 if not b else 0.0
    if not b:
        return 0.0
    blocks = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return min(1.0, sum(block.size for block in blocks) / len(a))


def longest_repeat(text: str) -> int:
    """How many times in a row the most-repeated word repeats itself.

    Books make sounds. *A Subaltern's War* has "Whirra, Whirra, Whirra",
    "Phut, Phut, Phut", "Whoo--Whoo--Whoo--CRASH", "Huh, huh, huh", "Crack,
    crack, crack"; a stammer, a refrain or a drumbeat does the same thing. All
    of them are read perfectly and all of them look like a stuck model if you
    only count repeats. What separates them is how far it goes: written
    onomatopoeia runs to three or four, a model that has come off the rails
    does not stop. Hence a count rather than a ratio, and a high bar on it.
    """
    words = normalize(text).split()
    best = run = 1
    for a, b in zip(words, words[1:]):
        run = run + 1 if a == b else 1
        best = max(best, run)
    return best if words else 0


# --------------------------------------------------------------------------- #
# Pass 2: speech recognition
# --------------------------------------------------------------------------- #
class Recognizer:
    """faster-whisper, loaded lazily and only if the ASR pass is asked for."""

    def __init__(self, model: str = "small", device: str = "auto",
                 compute_type: str = "default") -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._cpu_only = False

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, "pip install faster-whisper"
        return True, ""

    def load(self, log=print):
        if self._model is not None:
            return self._model
        if not self._cpu_only:
            _add_cuda_dll_dirs()    # must precede the import below
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise NarrationCheckError(
                "faster-whisper is not installed (pip install faster-whisper). "
                "It does not depend on torch, so it can sit in its own venv "
                "without disturbing the TTS one.") from exc
        device, compute = self.device, self.compute_type
        if device == "auto":
            device, compute = ("cpu", "int8") if self._cpu_only \
                else _pick_device(compute)
        self._model = WhisperModel(self.model_name, device=device,
                                   compute_type=compute)
        log(f"  - listening with whisper-{self.model_name} on {device}.")
        return self._model

    def transcribe(self, path: Path, *, lang: str | None = None,
                   log=print) -> list[dict]:
        """Segments with their text, span, and whisper's own decode statistics."""
        try:
            return self._decode(self.load(log=log), path, lang)
        except RuntimeError as exc:
            # A visible CUDA device is not the same as a usable one. CTranslate2
            # wants its own cuBLAS and cuDNN 9, which a machine can perfectly
            # well lack while torch runs happily on the copies it bundles -- and
            # it only finds out when it tries to encode, not when it loads.
            # Checking audio on the CPU is slow, not wrong, so a check left
            # running unattended falls back instead of failing.
            if self._cpu_only or self.device != "auto":
                raise
            log(f"  !  CUDA is not usable here ({exc}); transcribing on the "
                "CPU instead - slower, same findings. See requirements-audio.txt.")
            self._cpu_only = True
            self._model = None
            return self._decode(self.load(log=log), path, lang)

    @staticmethod
    def _decode(model, path: Path, lang: str | None) -> list[dict]:
        segments, _info = model.transcribe(
            str(path), language=lang, beam_size=5,
            # Keeps one bad segment from poisoning every segment after it,
            # which would turn a single glitch into a chapter of findings.
            condition_on_previous_text=False,
            vad_filter=False)               # the blanks are the point
        return [{"start": s.start, "end": s.end, "text": s.text.strip(),
                 "avg_logprob": s.avg_logprob,
                 "compression_ratio": s.compression_ratio,
                 "no_speech_prob": s.no_speech_prob}
                for s in segments]


def _pick_device(compute: str) -> tuple[str, str]:
    """CUDA if ctranslate2 can see it, CPU otherwise. Never fails the run."""
    _add_cuda_dll_dirs()        # before the import: see that function's docstring
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", ("float16" if compute == "default" else compute)
    except Exception:  # noqa: BLE001 - no ctranslate2, or no driver
        pass
    return "cpu", ("int8" if compute == "default" else compute)


def _add_cuda_dll_dirs() -> list[str]:
    """Let CTranslate2 find cuBLAS and cuDNN on Windows. Returns what it added.

    Unlike torch, CTranslate2 does not ship the CUDA libraries it links
    against, and pip has no way to put them on PATH. They are usually already
    on the machine anyway -- in the `nvidia-*-cu12` wheels, or inside the torch
    the TTS venv installed -- so the directories are pointed out to the loader
    rather than asking for a second multi-gigabyte download. Set
    BOOK_CREATOR_CUDA_DLL_DIR to point somewhere else again.

    It has to happen before ctranslate2 is imported, and it has to go on PATH:
    CTranslate2 delay-loads these with a plain LoadLibrary, which searches PATH
    but not the directories `os.add_dll_directory` registers. Both are done,
    since the flags it uses are its business and have changed before.
    """
    import os
    import site
    import sys

    if os.name != "nt":                 # elsewhere the rpath already handles it
        return []
    roots = [Path(p) for p in
             (os.environ.get("BOOK_CREATOR_CUDA_DLL_DIR") or "").split(os.pathsep)
             if p]
    bases = list(site.getsitepackages())
    if site.ENABLE_USER_SITE:
        bases.append(site.getusersitepackages())
    # The narration venv installs torch and the checking venv does not, so the
    # libraries are frequently one directory sideways from this interpreter.
    bases += [str(p) for p in Path(sys.prefix).parent.glob(".venv*/Lib/site-packages")]
    for base in dict.fromkeys(bases):
        roots += sorted(Path(base).glob("nvidia/*/bin"))
        roots.append(Path(base) / "torch" / "lib")

    added: list[str] = []
    for d in roots:
        if not d.is_dir() or str(d) in added:
            continue
        if not any(d.glob("cublas64_*.dll")) and not any(d.glob("cudnn64_*.dll")):
            continue
        added.append(str(d))
        try:
            os.add_dll_directory(str(d))
        except (OSError, ValueError):           # already added, or vanished
            pass
    if added:
        os.environ["PATH"] = os.pathsep.join([*added, os.environ.get("PATH", "")])
    return added


def scan_asr(audio_dir: str | Path, *, manifest: dict | None = None,
             model: str = "small", device: str = "auto",
             min_similarity: float = 0.45, lang: str | None = None,
             log=print) -> list[Finding]:
    """Transcribe each chapter and flag what does not match the text.

    With a manifest the comparison is exact: every utterance has a known
    intended text, so a low similarity is a real mismatch. Without one we fall
    back to whisper's decode statistics, which still catch loops and mumbling
    but cannot tell a fluent misreading from a faithful one.
    """
    rec = Recognizer(model, device)
    out: list[Finding] = []
    voices = _voice_langs(manifest)
    for ci, wav in enumerate(chapter_wavs(audio_dir), start=1):
        log(f"  - chapter {ci}: transcribing {wav_seconds(wav) / 60:.1f} min...")
        segments = rec.transcribe(wav, lang=lang, log=log)
        record = _chapter_record(manifest, ci, wav.name)
        out.extend(_statistic_findings(segments, ci, record or None, voices))
        if record:
            out.extend(_mismatch_findings(segments, ci, record, voices,
                                          min_similarity))
    return out


def _voice_langs(manifest: dict | None) -> set[str]:
    """Languages read by a substitute voice, which need the sound fold."""
    from .audio import VOICE_LANG_FALLBACK

    if not manifest:
        return set()
    langs = {u.get("lang") for ch in manifest.get("chapters", [])
             for u in ch.get("utterances", [])}
    return {ln for ln in langs if ln in VOICE_LANG_FALLBACK}


def _main_utterance(record: dict | None, start: float, end: float) -> dict:
    """The utterance that most of a whisper segment falls inside, or {}.

    Whisper segments by its own logic and often straddles two clips, but a loop
    is one clip's failure: the one holding most of the segment is the one to
    re-narrate. Without this a loop -- the finding most worth fixing -- carried
    no cache key, and `quarantine` could do nothing about it.
    """
    best, most = {}, 0.0
    for u in (record or {}).get("utterances", []):
        overlap = min(end, u.get("end", 0.0)) - max(start, u.get("start", 0.0))
        if overlap > most:
            best, most = u, overlap
    return best


def _as_written(record: dict, start: float, end: float) -> str:
    """What the book asked for across a span of a chapter, or ''."""
    return " ".join(u.get("text", "") for u in record.get("utterances", [])
                    if u.get("end", 0.0) > start and u.get("start", 0.0) < end)


def _statistic_findings(segments: list[dict], chapter: int,
                        record: dict | None = None,
                        voices: set[str] | None = None) -> list[Finding]:
    """Loops and mumbling, from whisper's own view of its decode.

    These statistics describe the *transcript*, so on their own they cannot
    tell a looping model from a book that repeats itself -- and books do. A
    real narration of *A Subaltern's War* was flagged three times for
    "Whirra, Whirra, Whirra, Phut, Phut, Phut", "Whoo--Whoo--Whoo--CRASH" and
    "something going on on the right", every one of them read perfectly. So
    when the manifest says what the text was, the text gets the last word: if
    the audio says what the book says, nothing is wrong with it however odd
    the statistics look -- provided it says nothing *but* the text, because a
    loop is extra words on top of a reading that is otherwise all there.
    """
    out: list[Finding] = []
    for seg in segments:
        if record is not None:
            written = _as_written(record, seg["start"], seg["end"])
            fold = bool(voices) and any(
                u.get("lang") in voices for u in record.get("utterances", [])
                if u.get("end", 0.0) > seg["start"] and u.get("start", 0.0) < seg["end"])
            if (written
                    and similarity(written, seg["text"],
                                   fold_sound=fold) >= READS_AS_WRITTEN
                    and similarity(seg["text"], written,
                                   fold_sound=fold) >= SAYS_ONLY_THE_TEXT):
                continue
        if (seg["compression_ratio"] > LOOP_COMPRESSION
                or longest_repeat(seg["text"]) >= LOOP_REPEATS):
            said = _main_utterance(record, seg["start"], seg["end"])
            out.append(Finding(
                kind="loop", chapter=chapter, start=seg["start"], end=seg["end"],
                detail="the reading repeats itself - the model looped",
                text=said.get("text", "")[:200], heard=seg["text"][:200],
                score=round(seg["compression_ratio"], 2),
                key=said.get("key", "")))
        elif seg["avg_logprob"] < LOW_CONFIDENCE:
            said = _main_utterance(record, seg["start"], seg["end"])
            out.append(Finding(
                kind="mumble", chapter=chapter, start=seg["start"],
                end=seg["end"],
                detail="the recognizer could not make words of this",
                text=said.get("text", "")[:200], heard=seg["text"][:200],
                score=round(seg["avg_logprob"], 2), key=said.get("key", "")))
    return out


def _mismatch_findings(segments: list[dict], chapter: int, record: dict,
                       voices: set[str], min_similarity: float) -> list[Finding]:
    """Utterances whose audio does not say what the book asked for."""
    out: list[Finding] = []
    for u in record.get("utterances", []):
        said = u.get("text", "")
        if u.get("silent"):
            # The build already knew this one produced no audio, and the signal
            # pass reports the gap. Scoring it too would name the same eight
            # seconds twice under two different headings.
            continue
        if len(normalize(said)) < 12:
            # Too short to score: "Yes." against a one-word transcript is noise
            # either way, and the signal pass already catches it if it came out
            # empty.
            continue
        heard = " ".join(s["text"] for s in segments
                         if s["end"] > u["start"] and s["start"] < u["end"])
        score = similarity(said, heard, fold_sound=u.get("lang") in voices)
        if score < min_similarity:
            out.append(Finding(
                kind="mismatch", chapter=chapter, start=u["start"], end=u["end"],
                detail=f"heard {score:.0%} of the text it was given",
                text=said[:200], heard=heard[:200], score=round(score, 2),
                key=u.get("key", "")))
    return out


# --------------------------------------------------------------------------- #
# Borrowing a recognizer from another virtualenv
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parent.parent


def recognizer_interpreter(root: Path = REPO) -> Path | None:
    """A python beside this one that has faster-whisper, or None.

    The web UI runs in the TTS virtualenv, because that is the only place the
    narrator lives -- and faster-whisper is deliberately not installed there,
    since it pulls a numpy the TTS stack cannot take. So the build that has
    just narrated a book is exactly the process that cannot listen to it. The
    recognizer is usually one directory sideways, in `.venv-asr`.
    """
    for venv in sorted(root.glob(".venv*")):
        for exe, site in ((venv / "Scripts" / "python.exe",
                           venv / "Lib" / "site-packages"),
                          (venv / "bin" / "python", None)):
            if not exe.exists():
                continue
            sites = [site] if site else list(venv.glob("lib/python*/site-packages"))
            if any((s / "faster_whisper").is_dir() for s in sites if s):
                return exe
    return None


def check_in(python: Path, audio_dir: str | Path, report_path: str | Path, *,
             model: str = "small", log=print) -> Report:
    """Run the full check in another interpreter and read its report back.

    Progress lines are passed through as they arrive: the listening pass is
    most of an hour on a long book, and a build log that goes quiet for that
    long looks hung.
    """
    import os
    import subprocess

    report_path = Path(report_path)
    cmd = [str(python), str(REPO / "check_audio.py"), str(audio_dir), "--asr",
           "--model", model, "-o", str(report_path)]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, text=True,
                            encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        # The script prints the whole report once it is done; the build log
        # wants the progress, not a second copy of the file it links to.
        if line.startswith("# Narration check"):
            break
        if line.strip():
            tail = (tail + [line])[-5:]
            if line.lstrip().startswith(("-", "!")):
                log(f"  {line.strip()}")
    for _ in proc.stdout:                 # drain, so the child can exit
        pass
    # 0 = clean, 1 = findings; anything else is the check itself failing.
    if proc.wait() not in (0, 1):
        raise NarrationCheckError(
            f"the listening pass in {python.parent.parent.name} failed: "
            + " / ".join(tail))
    data = report_path.with_suffix(".json")
    try:
        return Report.from_dict(json.loads(data.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise NarrationCheckError(f"could not read {data}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Running both passes
# --------------------------------------------------------------------------- #
def check(audio_dir: str | Path, *, asr: bool = False, model: str = "small",
          device: str = "auto", min_gap: float = DEFAULT_GAP,
          min_similarity: float = 0.45, lang: str | None = None,
          log=print) -> Report:
    """Signal pass always, recognizer pass when asked for."""
    audio_dir = Path(audio_dir)
    manifest = load_manifest(audio_dir)
    wavs = chapter_wavs(audio_dir)
    lengths = [wav_seconds(p) for p in wavs]
    report = Report(audio_dir=str(audio_dir), chapters=len(wavs),
                    seconds=sum(lengths), asr=asr)
    if manifest is None:
        report.notes.append(
            "No manifest.json in this directory, so findings cannot name the "
            "text that should have been read, and nothing can be re-narrated "
            "from them. Narrations built from now on write one.")
        if asr:
            report.notes.append(
                "Without the text, 'looped' and 'not recognizable' are guesses "
                "from the transcript alone -- a book that repeats itself "
                "(shellfire, a refrain, a stammer) reads exactly like a model "
                "that looped. Check those by ear, or rebuild the narration to "
                "get a manifest: the cache makes that cheap, and the check can "
                "then tell the two apart.")

    log(f"- Checking {len(wavs)} chapter(s), {report.seconds / 60:.0f} minutes.")
    report.findings.extend(scan_signal(audio_dir, min_gap=min_gap,
                                       manifest=manifest, log=log))
    if asr:
        ok, reason = Recognizer.available()
        if not ok:
            raise NarrationCheckError(f"Cannot run the listening pass: {reason}")
        report.findings.extend(scan_asr(audio_dir, manifest=manifest,
                                        model=model, device=device,
                                        min_similarity=min_similarity,
                                        lang=lang, log=log))
    report.findings.sort(key=lambda f: (f.chapter, f.start))
    _locate_in_book(report.findings, lengths)
    return report


def _locate_in_book(findings: list[Finding], lengths: list[float]) -> None:
    """Fill in where each finding falls in the assembled book.

    The chapter WAVs are concatenated in order to make the M4B, so this is the
    offset a player has to seek to -- which is what turns a report into
    something you click rather than something you scroll a six-hour file
    looking for.
    """
    before = [0.0]
    for length in lengths:
        before.append(before[-1] + length)
    for f in findings:
        if 1 <= f.chapter <= len(lengths):
            f.book_start = round(before[f.chapter - 1] + f.start, 2)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
_KIND_LABEL = {
    "blank": "Silence where a sentence belongs",
    "loop": "The model looped",
    "mumble": "Not recognizable as speech",
    "mismatch": "Does not say what the text says",
    "clipping": "Distorted (pinned at full scale)",
}


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def format_report(report: Report) -> str:
    """Markdown naming chapter and timestamp, so you can go and listen."""
    lines = [f"# Narration check - {Path(report.audio_dir).name}", "",
             f"{report.chapters} chapter(s), {report.seconds / 60:.0f} minutes, "
             f"{'signal + listening' if report.asr else 'signal only'} pass.", ""]
    for note in report.notes:
        lines += [f"> {note}", ""]
    if not report.findings:
        lines.append("Nothing flagged. Every chapter reads through without a "
                     "blank, a loop, or a distorted stretch.")
        return "\n".join(lines) + "\n"

    counts: dict[str, int] = {}
    for f in report.findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    lines += ["| Problem | Found |", "| --- | --- |"]
    for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {_KIND_LABEL.get(kind, kind)} | {n} |")

    chapter = None
    for f in report.findings:
        if f.chapter != chapter:
            chapter = f.chapter
            lines += ["", f"## Chapter {chapter}", ""]
        # Chapter-relative first, because that is where the WAV is, then where
        # to drag to in the assembled book -- which is the file most people
        # actually listen to, and the two are hours apart.
        where = f"{hms(f.start)}-{hms(f.end)}"
        if f.book_start and abs(f.book_start - f.start) > 1:
            where += f" (book {hms(f.book_start)})"
        lines.append(f"- **{where}** "
                     f"*{_KIND_LABEL.get(f.kind, f.kind)}* - {f.detail}")
        if f.text:
            lines.append(f"  - text: “{f.text}”")
        if f.heard:
            lines.append(f"  - heard: “{f.heard}”")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Fixing what was found
# --------------------------------------------------------------------------- #
def quarantine(report: Report, *, engine: str = "chatterbox",
               cache_dir: str = "cache/tts", log=print) -> int:
    """Move every flagged utterance's cached WAV aside, and say how many.

    The TTS cache is keyed by engine + language + voice + text, so deleting an
    entry is the whole fix: re-run the same build and only the flagged
    utterances are synthesized again, while the hours that were fine are reused
    from cache. Moved rather than deleted so a bad clip can still be listened
    to afterwards.
    """
    cache = Path(cache_dir) / engine
    bin_dir = cache / "quarantine"
    moved = 0
    seen: set[str] = set()
    for f in report.findings:
        if not f.key or f.key in seen:
            continue
        seen.add(f.key)
        src = cache / f"{f.key}.wav"
        if not src.exists():
            continue
        bin_dir.mkdir(parents=True, exist_ok=True)
        src.replace(bin_dir / src.name)
        moved += 1
    if moved:
        log(f"- Quarantined {moved} cached utterance(s) to {bin_dir}. "
            "Re-run the same build to re-narrate exactly those.")
    else:
        log("- Nothing to quarantine: no finding named a cached utterance "
            "(a narration manifest is needed for that).")
    return moved
