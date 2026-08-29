#!/usr/bin/env python
"""Download public-domain narrator samples into voices/, for voice cloning.

Source: LibriVox (librivox.org), whose recordings are dedicated to the public
domain -- the same bar this project holds its text sources to. Cloning a voice
you have no rights to is the obvious hazard with any cloning TTS; a LibriVox
reader has explicitly released theirs, so a book narrated with one of these is
as publishable as the text beside it.

    python download_voices.py             # fetch the curated set
    python download_voices.py la grc      # only these languages
    python download_voices.py --list      # show what is available

Each entry becomes a ~20 second mono 24 kHz WAV, which is what the cloning
engines want. Only that slice is transferred: ffmpeg range-requests into the
MP3 rather than downloading a whole chapter.

You do NOT need any of this to get started -- Chatterbox ships a built-in
voice and works with no reference audio at all. These are for when you want a
particular narrator, and especially for Latin and Ancient Greek, where a real
human reading the language beats approximating it with an Italian or Modern
Greek voice (see book_creator/audio.py's VOICE_LANG_FALLBACK).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

VOICES_DIR = Path("voices")
DOWNLOAD = "https://archive.org/download/{identifier}/{file}"
METADATA = "https://archive.org/metadata/{identifier}"
HEADERS = {"User-Agent": "book_creator-voicefetch"}

# Seconds to skip before sampling. Every LibriVox file opens with a spoken
# boilerplate credit ("This is a LibriVox recording..."), which is the reader's
# voice but not the reader reading the work; starting later gets natural prose.
SKIP_SECONDS = 75
CLIP_SECONDS = 20
SAMPLE_RATE = 24000


@dataclass(frozen=True)
class Voice:
    """One curated LibriVox recording to sample a narrator from."""

    id: str                 # output stem, e.g. "la-caesar"
    lang: str               # source language this voice suits
    identifier: str         # archive.org item
    file: str               # MP3 within that item
    note: str               # what it is, shown by --list
    skip: int = SKIP_SECONDS


# Curated because a live search returns a different (and sometimes unusable)
# recording every run; these identifiers are pinned and verified.
VOICES: list[Voice] = [
    # --- Latin: a human actually reading Latin, rather than an Italian voice
    #     approximating it. This is the recording of the very text the README
    #     uses as its worked example.
    Voice("la-caesar", "la", "bellum_gallicum_1210_librivox",
          "bellumgallicum_01_caesar_64kb.mp3",
          "Latin — Caesar, De Bello Gallico (male)"),
    Voice("la-aesop", "la", "selectaefabulaeaesopior_2401_librivox",
          "selectaefabulaeaesopi_01_various_64kb.mp3",
          "Latin — Selectae Fabulae Aesopi"),
    # --- Ancient Greek
    Voice("grc-thucydides", "grc", "histories5_thucydides_1208_librivox",
          "histories5_01_thucydides_64kb.mp3",
          "Ancient Greek — Thucydides, Histories V"),
    # --- Modern languages, for the source side of a non-Latin book
    Voice("it-pirandello", "it", "novelle_per_un_anno_vol_13_candelora_1503_librivox",
          "novelle13_01_pirandello_64kb.mp3",
          "Italian — Pirandello, Novelle per un Anno"),
    Voice("fr-hugo", "fr", "notredameparis_1312_librivox",
          "notredameparis_01_hugo_64kb.mp3",
          "French — Hugo, Notre-Dame de Paris"),
    Voice("es-dickens", "es", "tiemposdificiles_2411_librivox",
          "tiemposdificiles_01_dickens_64kb.mp3",
          "Spanish — Dickens, Tiempos difíciles (trans.)"),
    # --- English, for the translation side
    Voice("en-austen", "en", "prideandprejudice_1005_librivox",
          "prideandprejudice_01_austen_64kb.mp3",
          "English — Austen, Pride and Prejudice (female)"),
    Voice("en-melville", "en", "moby_dick_librivox",
          "mobydick_001_melville_64kb.mp3",
          "English — Melville, Moby Dick (male)"),
]


def ffmpeg_exe() -> str | None:
    """A usable ffmpeg: the system one first, else imageio-ffmpeg's."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def resolve_file(voice: Voice) -> str | None:
    """Confirm the pinned MP3 still exists, else pick another from the item.

    Archive.org items do get re-derived, so a pinned filename can go stale;
    falling back to any 64 kbps MP3 in the same item keeps the script working
    instead of failing on a name change.
    """
    try:
        meta = requests.get(METADATA.format(identifier=voice.identifier),
                            headers=HEADERS, timeout=30).json()
    except Exception as exc:  # noqa: BLE001 - offline, rate-limited, moved
        print(f"    ! could not read item metadata: {exc}")
        return None

    names = [f["name"] for f in meta.get("files", [])]
    if voice.file in names:
        return voice.file
    alts = [n for n in sorted(names) if n.lower().endswith("_64kb.mp3")]
    if not alts:
        alts = [n for n in sorted(names) if n.lower().endswith(".mp3")]
    if alts:
        print(f"    · pinned file missing, using {alts[0]}")
        return alts[0]
    return None


def fetch(voice: Voice, ffmpeg: str, *, refresh: bool = False) -> bool:
    out = VOICES_DIR / f"{voice.id}.wav"
    if out.exists() and not refresh:
        print(f"  = {voice.id:16} already present")
        return True

    print(f"  → {voice.id:16} {voice.note}")
    name = resolve_file(voice)
    if not name:
        print("    ! no usable audio in that item; skipped")
        return False

    url = DOWNLOAD.format(identifier=voice.identifier, file=name)
    # -ss before -i seeks in the input, so ffmpeg range-requests into the file
    # and only the sampled span crosses the network.
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", str(voice.skip), "-i", url, "-t", str(CLIP_SECONDS),
           "-ac", "1", "-ar", str(SAMPLE_RATE), str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        print(f"    ! ffmpeg failed: {detail[:160]}")
        return False
    except subprocess.TimeoutExpired:
        print("    ! timed out")
        return False

    if not out.exists() or out.stat().st_size < 20_000:
        print("    ! produced no usable audio; skipped")
        out.unlink(missing_ok=True)
        return False
    print(f"    ✓ {out}  ({out.stat().st_size / 1024:.0f} KB, "
          f"{CLIP_SECONDS}s mono {SAMPLE_RATE} Hz)")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download public-domain narrator samples from LibriVox.")
    p.add_argument("languages", nargs="*",
                   help="Only these language codes (la, grc, it, fr, es, en). "
                        "Default: all.")
    p.add_argument("--list", action="store_true",
                   help="Show the curated voices and exit.")
    p.add_argument("--refresh", action="store_true",
                   help="Re-download voices already in voices/.")
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    if args.list:
        print("\nCurated LibriVox narrators (all public domain):\n")
        for v in VOICES:
            print(f"  {v.id:16} [{v.lang:3}] {v.note}")
        print("\n  python download_voices.py la grc     # just these languages")
        return 0

    wanted = [v for v in VOICES if not args.languages or v.lang in args.languages]
    if not wanted:
        print(f"No curated voices for: {', '.join(args.languages)}")
        print("Available: " + ", ".join(sorted({v.lang for v in VOICES})))
        return 1

    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        print("ffmpeg is required to trim the clips.\n"
              "  pip install imageio-ffmpeg")
        return 1

    VOICES_DIR.mkdir(exist_ok=True)
    print(f"Fetching {len(wanted)} narrator sample(s) into {VOICES_DIR}/\n")
    ok = sum(fetch(v, ffmpeg, refresh=args.refresh) for v in wanted)
    print(f"\n{ok}/{len(wanted)} ready.")
    if ok:
        print("\nUse one as the narrator:")
        print("  python make_book.py --corpus-id 79 --audio \\")
        print(f"      --audio-voice {VOICES_DIR}/la-caesar.wav")
        print("\nor pick it in the web UI's Audiobook panel. Leave the voice "
              "blank to use\nthe engine's own built-in voice instead.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
