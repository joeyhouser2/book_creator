"""Narrate an aligned book as an interleaved bilingual audiobook, on the GPU.

The printed book puts each bead's original next to its translation; the
audiobook does the same in time instead of space:

    <original sentence>  (pause)  <English sentence>  (longer pause)  ...

so you can follow the parallel text with your ears. Chapters become real
chapter markers in the M4B.

Engines are pluggable, registered the same way `translators.py` registers
translation backends, and every one of them is loaded lazily -- importing this
module never pulls in torch or downloads a model.

    from book_creator import audio
    audio.register("myengine", MyEngine())

Nothing here is bundled: `pip install -r requirements-audio.txt` installs the
default engine. If it is missing, the build says so and skips the audiobook
rather than failing the book.

Latin and Ancient Greek have no native TTS voice anywhere, so they are read
with the nearest living-language voice -- Italian for Latin (the ecclesiastical
pronunciation used in choral practice) and Modern Greek for Ancient Greek. That
is a real convention, not a fudge, but it is a *convention*: classical restored
pronunciation will not come out of any of these models.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

# Sample rate everything is resampled to before assembly, so engines with
# different native rates can be mixed within one book.
TARGET_SR = 24000

# Non-living source languages mapped to the nearest voice a TTS model actually
# has. See the module docstring for why this is a defensible convention.
VOICE_LANG_FALLBACK = {
    "la": "it",     # ecclesiastical Latin is pronounced Italianate
    "grc": "el",    # ancient Greek read with modern Greek phonology
}


class AudioError(RuntimeError):
    """Synthesis could not run (engine missing, model unavailable, ...)."""


def voice_lang(lang: str) -> str:
    """The language id to hand a TTS model for a given source language."""
    return VOICE_LANG_FALLBACK.get(lang, lang)


# --------------------------------------------------------------------------- #
# Engine registry
# --------------------------------------------------------------------------- #
_ENGINES: dict[str, "TTSEngine"] = {}


class TTSEngine:
    """Base class for a text-to-speech backend.

    Subclasses load their model lazily in `_load` (so listing engines in the UI
    costs nothing) and return float32 mono samples from `synthesize`.
    """

    name = "base"
    sample_rate = TARGET_SR
    # Longest text the model handles in one pass; longer input is split on
    # punctuation before being sent.
    max_chars = 300
    # Language ids the model accepts, or None for "anything".
    languages: tuple[str, ...] | None = None

    def available(self) -> tuple[bool, str]:
        """(installed?, human-readable reason if not)."""
        raise NotImplementedError

    def load(self, device: str) -> None:
        raise NotImplementedError

    def synthesize(self, text: str, *, lang: str, voice: str | None = None):
        """Return float32 mono samples at self.sample_rate."""
        raise NotImplementedError

    def unload(self) -> None:
        pass

    def supports(self, lang: str) -> bool:
        return self.languages is None or voice_lang(lang) in self.languages


def register(name: str, engine: TTSEngine) -> None:
    _ENGINES[name] = engine


def get(name: str) -> TTSEngine:
    if name not in _ENGINES:
        raise AudioError(
            f"Unknown TTS engine '{name}'. Available: {', '.join(sorted(_ENGINES))}")
    return _ENGINES[name]


def catalog() -> list[dict]:
    """Every registered engine with its install status, for the UI picker."""
    out = []
    for name, eng in sorted(_ENGINES.items()):
        ok, reason = eng.available()
        out.append({
            "id": name,
            "label": eng.label,
            "installed": ok,
            "reason": "" if ok else reason,
            "licence": eng.licence,
            "languages": list(eng.languages) if eng.languages else [],
            "clones_voice": eng.clones_voice,
        })
    return out


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #
class ChatterboxEngine(TTSEngine):
    """Resemble AI's Chatterbox Multilingual -- the default.

    MIT-licensed (so output is safe to sell), 23 languages including Italian
    and Greek, and it clones a voice from a few seconds of reference audio, so
    both languages can be read by the same narrator. About 7 GB of VRAM in
    fp16, which fits a 16 GB card with room to spare.
    """

    name = "chatterbox"
    label = "Chatterbox Multilingual (Resemble AI)"
    licence = "MIT"
    clones_voice = True
    sample_rate = 24000
    max_chars = 280
    languages = ("ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
                 "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
                 "sw", "tr", "zh")

    def __init__(self) -> None:
        self._model = None
        self._device = None

    def available(self) -> tuple[bool, str]:
        try:
            import chatterbox  # noqa: F401
        except ImportError:
            return False, "pip install chatterbox-tts"
        return True, ""

    def load(self, device: str) -> None:
        if self._model is not None and self._device == device:
            return
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as exc:
            raise AudioError(
                "chatterbox-tts is not installed "
                "(pip install -r requirements-audio.txt)") from exc
        self._model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        self._device = device

    def synthesize(self, text: str, *, lang: str, voice: str | None = None):
        if self._model is None:
            raise AudioError("Chatterbox engine used before load().")
        kwargs = {"language_id": voice_lang(lang)}
        if voice:
            kwargs["audio_prompt_path"] = voice
        wav = self._model.generate(text, **kwargs)
        return _to_mono_float(wav)

    def unload(self) -> None:
        self._model = None
        _empty_cuda_cache()


class KokoroEngine(TTSEngine):
    """Kokoro-82M -- tiny, Apache-2.0, many times realtime.

    Worth having as the fast option: it runs in about a gigabyte, so it can
    share a card with an embedding model, but it has fixed voices (no cloning)
    and no Greek.
    """

    name = "kokoro"
    label = "Kokoro-82M"
    licence = "Apache-2.0"
    clones_voice = False
    sample_rate = 24000
    max_chars = 400
    languages = ("en", "es", "fr", "hi", "it", "ja", "pt", "zh")

    # Kokoro keys pipelines by a single-letter language code.
    _LANG_CODE = {"en": "a", "es": "e", "fr": "f", "hi": "h", "it": "i",
                  "ja": "j", "pt": "p", "zh": "z"}

    def __init__(self) -> None:
        self._pipelines: dict[str, object] = {}
        self._device = "cpu"

    def available(self) -> tuple[bool, str]:
        try:
            import kokoro  # noqa: F401
        except ImportError:
            return False, "pip install kokoro"
        return True, ""

    def load(self, device: str) -> None:
        self._device = device
        self._pipelines.clear()

    def _pipeline(self, lang: str):
        code = self._LANG_CODE.get(voice_lang(lang), "a")
        if code not in self._pipelines:
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise AudioError("kokoro is not installed (pip install kokoro)") from exc
            self._pipelines[code] = KPipeline(lang_code=code, device=self._device)
        return self._pipelines[code]

    def synthesize(self, text: str, *, lang: str, voice: str | None = None):
        import numpy as np

        pipe = self._pipeline(lang)
        chunks = [_to_mono_float(audio)
                  for _, _, audio in pipe(text, voice=voice or "af_heart")]
        if not chunks:
            return np.zeros(0, dtype="float32")
        return np.concatenate(chunks)

    def unload(self) -> None:
        self._pipelines.clear()
        _empty_cuda_cache()


class XttsEngine(TTSEngine):
    """Coqui XTTS-v2 -- best cloning quality, but NOT licensed for commercial use.

    Registered because it is genuinely the nicest-sounding option for personal
    listening, and it covers German, which Kokoro does not. Its CPML licence
    forbids selling the output, so the UI flags it and the build logs a warning.
    """

    name = "xtts"
    label = "Coqui XTTS-v2"
    licence = "CPML (non-commercial only)"
    clones_voice = True
    sample_rate = 24000
    max_chars = 250
    languages = ("ar", "cs", "de", "en", "es", "fr", "hi", "hu", "it", "ja",
                 "ko", "nl", "pl", "pt", "ru", "tr", "zh")

    def __init__(self) -> None:
        self._tts = None

    def available(self) -> tuple[bool, str]:
        try:
            import TTS  # noqa: F401
        except ImportError:
            return False, "pip install coqui-tts"
        return True, ""

    def load(self, device: str) -> None:
        if self._tts is not None:
            return
        try:
            from TTS.api import TTS as CoquiTTS
        except ImportError as exc:
            raise AudioError("coqui-tts is not installed") from exc
        self._tts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    def synthesize(self, text: str, *, lang: str, voice: str | None = None):
        if self._tts is None:
            raise AudioError("XTTS engine used before load().")
        if not voice:
            raise AudioError(
                "XTTS needs a reference voice: point the voice setting at a "
                "6-30 second WAV of the narrator you want.")
        return _to_mono_float(self._tts.tts(
            text=text, speaker_wav=voice, language=voice_lang(lang)))

    def unload(self) -> None:
        self._tts = None
        _empty_cuda_cache()


register("chatterbox", ChatterboxEngine())
register("kokoro", KokoroEngine())
register("xtts", XttsEngine())


# --------------------------------------------------------------------------- #
# Audio helpers
# --------------------------------------------------------------------------- #
def _to_mono_float(wav):
    """Normalize whatever an engine returned into a 1-D float32 numpy array."""
    import numpy as np

    if hasattr(wav, "detach"):          # torch tensor
        wav = wav.detach().cpu().numpy()
    arr = np.asarray(wav, dtype="float32")
    if arr.ndim > 1:                    # (channels, n) or (n, channels)
        arr = arr.mean(axis=0) if arr.shape[0] < arr.shape[-1] else arr.mean(axis=-1)
    return arr.reshape(-1)


def _resample(samples, src_sr: int, dst_sr: int = TARGET_SR):
    """Linear resample. Good enough for speech joins; avoids a scipy dependency."""
    import numpy as np

    if src_sr == dst_sr or samples.size == 0:
        return samples
    n_out = int(round(samples.size * dst_sr / src_sr))
    x_old = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype("float32")


def _silence(seconds: float, sr: int = TARGET_SR):
    import numpy as np
    return np.zeros(max(0, int(seconds * sr)), dtype="float32")


def _write_wav(path: Path, samples, sr: int = TARGET_SR) -> None:
    """16-bit PCM WAV via the stdlib -- no soundfile/libsndfile needed."""
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1.0:                       # only touch it if it would clip
        samples = samples / peak
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _read_wav(path: Path):
    """Read a 16-bit mono WAV back as float32 at its stored rate."""
    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
        arr = np.frombuffer(frames, dtype="<i2").astype("float32") / 32767.0
        if w.getnchannels() > 1:
            arr = arr.reshape(-1, w.getnchannels()).mean(axis=1)
    return arr, sr


def ffmpeg_exe() -> str | None:
    """Path to an ffmpeg binary: system first, then the one imageio-ffmpeg ships."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - any failure just means "no ffmpeg"
        return None


# --------------------------------------------------------------------------- #
# Text preparation
# --------------------------------------------------------------------------- #
_ABBREV_SPLIT = re.compile(r"(?<=[.!?;:,])\s+")


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text a model cannot swallow whole, preferring punctuation breaks.

    TTS models degrade badly past their trained length (they clip, or loop the
    last phrase), so long sentences are broken at clause boundaries and only
    fall back to a hard word-count split when a single clause is still too long.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    out: list[str] = []
    buf = ""
    for piece in _ABBREV_SPLIT.split(text):
        if not piece:
            continue
        if len(buf) + len(piece) + 1 <= max_chars:
            buf = f"{buf} {piece}".strip()
            continue
        if buf:
            out.append(buf)
        if len(piece) <= max_chars:
            buf = piece
            continue
        # A single clause longer than the limit: split on whitespace.
        words, line = piece.split(), ""
        for word in words:
            if len(line) + len(word) + 1 > max_chars:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        buf = line
    if buf:
        out.append(buf)
    return out


def speakable(text: str) -> str:
    """Tidy printed text into something worth reading aloud.

    Two different things get treated differently, on purpose:

    * `[Illustration]`, `[p. 42]` and friends are *notes about* the text, so
      they are dropped whole -- a narrator saying "bracket p forty-two" is
      noise.
    * `<A>ltus`, `Imp(erator)` are editorial marks *inside* a word, so only the
      brackets go and the letters stay ("Altus", "Imperator"). This is the same
      convention the latin repo uses in `normalize_for_embedding`; dropping the
      group whole would silently turn "Altus" into "ltus".

    Corpus sources normally arrive already cleaned (see corpus._SRC_CLEAN);
    this is the backstop for Gutenberg text and for `strip_markup: false`.
    The printed book is untouched either way.
    """
    text = re.sub(r"\[[^\]]{0,40}\]", " ", text)   # whole-note brackets: drop
    text = re.sub(r"[<>(){}]+", "", text)           # in-word sigla: keep letters
    text = re.sub(r"[|~^*_`]+", " ", text)          # markup leftovers
    text = re.sub(r"/+", " ", text)                 # line/page break markers
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- #
# Building an audiobook
# --------------------------------------------------------------------------- #
@dataclass
class Utterance:
    """One thing to say: a bead side, or a spoken chapter heading."""

    text: str
    lang: str
    voice: str | None
    pause_after: float


def plan(chapters, *, spec, src_lang: str,
         tgt_lang: str) -> list[tuple[str, list[Utterance]]]:
    """Turn chapters into (title, utterances) pairs, in listening order.

    The title travels with its utterances rather than being looked up by index
    later: a chapter with nothing to say is dropped here, so indexes into the
    original chapter list stop matching and the M4B would end up with chapter
    markers naming the wrong chapters.

    Kept separate from synthesis so the UI can price a run (utterance count,
    characters, estimated duration) without loading a model.
    """
    out: list[tuple[str, list[Utterance]]] = []
    spoken = 0        # beads narrated so far, for the max_beads test-run cap
    for ch in chapters:
        if spec.max_beads and spoken >= spec.max_beads:
            break
        items: list[Utterance] = []
        if spec.announce_chapters and ch.title:
            items.append(Utterance(speakable(ch.title), tgt_lang,
                                   spec.tgt_voice, spec.pause_chapter))
        for bead in ch.beads:
            if spec.max_beads and spoken >= spec.max_beads:
                break
            src = speakable(bead.src_text)
            tgt = speakable(bead.tgt_text)
            pair: list[Utterance] = []
            if src:
                pair.append(Utterance(src, src_lang, spec.src_voice, spec.pause_within))
            if tgt:
                pair.append(Utterance(tgt, tgt_lang, spec.tgt_voice, spec.pause_within))
            if not pair:
                continue
            if spec.first == "tgt":
                pair.reverse()
            pair[-1].pause_after = spec.pause_bead      # longer gap between beads
            items.extend(pair)
            spoken += 1
        # Skip a chapter that would contain nothing but its own heading —
        # which happens once max_beads has been used up mid-book.
        heading = 1 if (spec.announce_chapters and ch.title) else 0
        if len(items) > heading:
            out.append((ch.title or f"Chapter {len(out) + 1}", items))
    return out


def estimate(chapters, *, spec, src_lang: str, tgt_lang: str) -> dict:
    """Rough size of a run, for the UI to show before committing the GPU.

    ~14 characters per second is a typical narration rate; it is a ballpark,
    not a promise.
    """
    plans = plan(chapters, spec=spec, src_lang=src_lang, tgt_lang=tgt_lang)
    utterances = [u for _, items in plans for u in items]
    chars = sum(len(u.text) for u in utterances)
    pauses = sum(u.pause_after for u in utterances)
    speech = chars / 14.0
    return {
        "chapters": len(plans),
        "utterances": len(utterances),
        "characters": chars,
        "seconds": round(speech + pauses),
        "duration": _hms(speech + pauses),
    }


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h {s % 3600 // 60:02d}m {s % 60:02d}s"


def _cache_key(engine: str, u: Utterance) -> str:
    raw = f"{engine}|{voice_lang(u.lang)}|{u.voice or ''}|{u.text}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_audiobook(chapters, *, spec, out_dir: str, slug: str, title: str,
                    author: str, src_lang: str, tgt_lang: str,
                    cache_dir: str = "cache/tts", log=print,
                    on_progress=None, should_stop=None) -> dict:
    """Synthesize the interleaved bilingual audiobook. Returns a result dict.

    Every utterance is cached as a WAV keyed by engine + language + voice +
    text, so a re-run (or a run resumed after a crash) re-synthesizes only
    what actually changed -- which matters when a full book is hours of GPU
    time.
    """
    engine = get(spec.engine)
    ok, reason = engine.available()
    if not ok:
        raise AudioError(f"TTS engine '{spec.engine}' is not installed: {reason}")
    if engine.licence.startswith("CPML"):
        log(f"  !  {engine.label} is licensed {engine.licence} -- personal "
            "listening only, do not sell this audio.")
    for lang, side in ((src_lang, "original"), (tgt_lang, "translation")):
        if not engine.supports(lang):
            raise AudioError(
                f"{engine.label} has no voice for the {side} language "
                f"'{lang}' (mapped to '{voice_lang(lang)}'). Pick another engine.")
    if src_lang in VOICE_LANG_FALLBACK:
        log(f"• {src_lang} has no TTS voice; reading it with the "
            f"'{voice_lang(src_lang)}' voice (see audio.VOICE_LANG_FALLBACK).")

    plans = plan(chapters, spec=spec, src_lang=src_lang, tgt_lang=tgt_lang)
    total = sum(len(items) for _, items in plans)
    if not total:
        raise AudioError("Nothing to narrate: no beads with text.")

    est = estimate(chapters, spec=spec, src_lang=src_lang, tgt_lang=tgt_lang)
    log(f"• Narrating {total} utterance(s) across {len(plans)} chapter(s) "
        f"— about {est['duration']} of audio.")
    log(f"• Loading {engine.label} on {spec.device}…")
    engine.load(spec.device)

    cache = Path(cache_dir) / spec.engine
    cache.mkdir(parents=True, exist_ok=True)
    audio_dir = Path(out_dir) / f"{slug}-audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np

    chapter_files: list[Path] = []
    chapter_lengths: list[float] = []
    chapter_titles: list[str] = []
    done = 0
    reused = 0
    try:
        for ci, (title_of, items) in enumerate(plans, start=1):
            if should_stop is not None and should_stop():
                log("• Stopped before chapter %d." % ci)
                break
            pieces: list = []
            for u in items:
                if should_stop is not None and should_stop():
                    break
                key = _cache_key(spec.engine, u)
                cached = cache / f"{key}.wav"
                if cached.exists():
                    samples, sr = _read_wav(cached)
                    reused += 1
                else:
                    parts = []
                    for chunk in chunk_text(u.text, engine.max_chars):
                        parts.append(engine.synthesize(
                            chunk, lang=u.lang, voice=u.voice))
                    samples = (np.concatenate(parts) if parts
                               else np.zeros(0, dtype="float32"))
                    sr = engine.sample_rate
                    _write_wav(cached, samples, sr)
                pieces.append(_resample(samples, sr))
                pieces.append(_silence(u.pause_after))
                done += 1
                if on_progress and done % 5 == 0:
                    on_progress(done, total)

            if not pieces:
                continue
            track = np.concatenate(pieces)
            chapter_lengths.append(track.size / TARGET_SR)
            path = audio_dir / f"ch{ci:03d}.wav"
            _write_wav(path, track)
            chapter_files.append(path)
            chapter_titles.append(title_of)
            log(f"  · chapter {ci}/{len(plans)}: {_hms(track.size / TARGET_SR)}")

        if on_progress:
            on_progress(done, total)
    finally:
        engine.unload()

    if not chapter_files:
        raise AudioError("No audio was produced.")

    log(f"• Synthesized {done - reused} utterance(s); reused {reused} from cache.")
    result = {
        "chapter_wavs": [str(p) for p in chapter_files],
        "chapters": len(chapter_files),
        "seconds": round(sum(chapter_lengths)),
        "duration": _hms(sum(chapter_lengths)),
        "engine": spec.engine,
        "book": None,
        "format": "wav",
    }

    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        log("  !  ffmpeg not found — leaving per-chapter WAVs; "
            "`pip install imageio-ffmpeg` to get an M4B with chapter markers.")
        return result

    book = _encode_book(ffmpeg, chapter_files, chapter_lengths, chapter_titles,
                        audio_dir.parent / f"{slug}.{spec.format}",
                        title=title, author=author, log=log)
    if book:
        result["book"] = str(book)
        result["format"] = spec.format
        log(f"✓ Audiobook: {book} ({result['duration']})")
    return result


def _encode_book(ffmpeg: str, wavs: list[Path], lengths: list[float],
                 titles: list[str], out_path: Path, *, title: str, author: str,
                 log=print) -> Path | None:
    """Concatenate the chapter WAVs into one M4B/MP3 with chapter markers."""
    work = out_path.parent / f"{out_path.stem}-audio"
    concat_list = work / "chapters.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in wavs),
        encoding="utf-8")

    # ffmetadata chapter markers: an audiobook player needs these to show a
    # chapter list and to resume where you left off.
    meta = [";FFMETADATA1", f"title={title}", f"artist={author}", f"album={title}"]
    start = 0.0
    for name, length in zip(titles, lengths):
        end = start + length
        meta += ["[CHAPTER]", "TIMEBASE=1/1000",
                 f"START={int(start * 1000)}", f"END={int(end * 1000)}",
                 f"title={name}"]
        start = end
    meta_file = work / "chapters.ffmeta"
    meta_file.write_text("\n".join(meta) + "\n", encoding="utf-8")

    codec = ["-c:a", "aac", "-b:a", "64k"] if out_path.suffix == ".m4b" \
        else ["-c:a", "libmp3lame", "-q:a", "4"]
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(concat_list),
           "-i", str(meta_file), "-map_metadata", "1",
           *codec, str(out_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        log(f"  !  ffmpeg failed, keeping WAVs: {detail[:300]}")
        return None
    return out_path


def devices() -> dict:
    """CUDA devices available for synthesis, for the UI to choose between.

    Also reports when CUDA_VISIBLE_DEVICES is masking cards: a machine with a
    big card and a fast one will happily hide the big one, and then the largest
    model you can actually run is decided by an environment variable rather
    than by your hardware.
    """
    gpus: list[dict] = []
    note = ""
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                gb = round(props.total_memory / 1024 ** 3, 1)
                gpus.append({"id": f"cuda:{i}", "name": props.name,
                             "label": f"cuda:{i} — {props.name} ({gb} GB)",
                             "memory_gb": gb})
    except Exception:  # noqa: BLE001 - no torch, or a driver problem
        pass

    masked = os.environ.get("CUDA_VISIBLE_DEVICES")
    installed = _physical_gpu_count()
    if masked and installed and len(gpus) < installed:
        note = (f"CUDA_VISIBLE_DEVICES={masked} hides {installed - len(gpus)} of "
                f"{installed} GPUs from this process. Unset it (or set it to "
                f"{','.join(str(i) for i in range(installed))}) to reach every "
                "card — otherwise a larger card on the machine is simply invisible.")

    return {
        "devices": gpus + [{"id": "cpu", "name": "CPU", "label": "CPU (very slow)",
                            "memory_gb": None}],
        "note": note,
        "recommended": best_device(gpus),
    }


# Narrator samples fetched by download_voices.py, named "<lang>-<who>.wav" or
# "<lang>-<region>-<who>.wav" where accent matters (en-gb-savage, en-us-klett).
VOICES_DIR = Path("voices")

_LANG_NAMES = {"la": "Latin", "grc": "Ancient Greek", "el": "Greek",
               "fr": "French", "de": "German", "it": "Italian",
               "es": "Spanish", "en": "English", "pt": "Portuguese"}
_REGION_NAMES = {"gb": "British", "us": "American", "au": "Australian",
                 "ie": "Irish", "ca": "Canadian"}


def voice_catalog(voices_dir: str | Path = VOICES_DIR) -> list[dict]:
    """Reference clips available for cloning.

    Empty is the normal starting state and not an error: the default engine
    ships a built-in voice, so a reference clip is only needed to clone a
    *particular* narrator.
    """
    d = Path(voices_dir)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.wav")):
        parts = p.stem.split("-")
        lang = parts[0] if len(parts) > 1 else ""
        region = ""
        who_parts = parts[1:] if len(parts) > 1 else parts
        # A two-letter second segment is an accent marker, not a name.
        if len(who_parts) > 1 and who_parts[0] in _REGION_NAMES:
            region = who_parts[0]
            who_parts = who_parts[1:]
        who = " ".join(who_parts)

        name = _LANG_NAMES.get(lang, lang or "?")
        accent = _REGION_NAMES.get(region, "")
        label = f"{name}{f' ({accent})' if accent else ''} · {who}"
        out.append({
            "id": p.stem,
            "path": str(p),
            "lang": lang,
            "accent": accent,
            "label": label,
            "size_kb": round(p.stat().st_size / 1024),
        })
    return out


def _physical_gpu_count() -> int:
    """How many GPUs the driver reports, ignoring CUDA_VISIBLE_DEVICES."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0
    try:
        out = subprocess.run([exe, "--list-gpus"], capture_output=True,
                             text=True, timeout=10)
        return len([ln for ln in out.stdout.splitlines() if ln.strip()])
    except Exception:  # noqa: BLE001 - driver missing or wedged
        return 0


def best_device(gpus: list[dict] | None = None) -> str:
    """The CUDA device with the most memory, or cpu.

    Defaulting to cuda:0 is wrong on a mixed pair: CUDA orders devices fastest
    first, so cuda:0 is often the *smaller* card, and the model that decides
    what fits is memory-bound rather than speed-bound.
    """
    if gpus is None:
        gpus = [d for d in devices()["devices"] if d["id"].startswith("cuda")]
    if not gpus:
        return "cpu"
    return max(gpus, key=lambda d: d["memory_gb"] or 0)["id"]


def _empty_cuda_cache() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
