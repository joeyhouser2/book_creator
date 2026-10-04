"""Narrate both volumes of Taylor's The Wars of Marlborough (1921).

Read from the Internet Archive scans in input/, which book_creator.scanned
turns back into chapters -- running heads, page numbers and footnotes taken
out, so none of that is read aloud. Simon Evers, from the LibriVox recording
in voices/, narrates; the text is English and monolingual.

    .venv-tts/Scripts/python build_marlborough_audio.py        # both volumes
    .venv-tts/Scripts/python build_marlborough_audio.py 2      # just Volume II

The TTS engine lives in its own virtualenv (see run_web.py), so it has to be
that interpreter. About 43 hours of audio between the two.
"""

from __future__ import annotations

import sys
from pathlib import Path

from book_creator.model import AudioSpec, BookSpec, CoverSpec
from book_creator.pipeline import build_book

VOICE = "voices/en-gb-evers.wav"          # Simon Evers, LibriVox, public domain

VOLUMES = {
    "1": ("The Wars of Marlborough, 1702–1709 — Volume I",
          "input/warsofmarlboroug01tayl.pdf"),
    "2": ("The Wars of Marlborough, 1702–1709 — Volume II",
          "input/warsofmarlboroug02tayl.pdf"),
}


def spec(title: str, path: str) -> BookSpec:
    return BookSpec(
        title=title,
        author="Frank Taylor",
        # English, read by an English narrator: left at the app's old default
        # of Latin, the narrator read it with an Italian voice.
        src_lang="en",
        tgt_lang="en",
        src_path=path,
        # One text read aloud: there is no translation and no second side.
        sides="src",
        first="src",
        audio_only=True,
        cover=CoverSpec(enabled=False),
        audio=AudioSpec(enabled=True, engine="chatterbox", device="cuda:0",
                        src_voice=VOICE, tgt_voice=VOICE, format="m4b"),
    )


def main(argv: list[str]) -> int:
    for v in argv or list(VOLUMES):
        title, path = VOLUMES[v]
        if not Path(path).exists():
            print(f"missing {path}")
            return 1
        print(f"\n=== Volume {v}: {title}\n", flush=True)
        artifacts: dict = {}
        build_book(spec(title, path), out_dir="output", verbose=True,
                   artifacts=artifacts)
        print(f"=== Volume {v} done: {artifacts.get('audio')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
