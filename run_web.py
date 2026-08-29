#!/usr/bin/env python
"""Launch the book_creator web UI.

    pip install -r requirements-web.txt
    python run_web.py            # then open http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse

from webapp.server import main


def _audio_hint() -> None:
    """Say so when this interpreter cannot narrate, but another one could.

    The TTS engine lives in its own virtualenv (its torch pin would displace
    the CUDA build the aligner needs), and nothing about `python run_web.py`
    switches interpreters. Without this the audiobook panel just quietly
    reports the engine as missing, which looks like a broken install.
    """
    from pathlib import Path

    from book_creator import audio

    if any(e["installed"] for e in audio.catalog()):
        return
    venv = Path(".venv-tts/Scripts/python.exe")
    if not venv.exists():
        venv = Path(".venv-tts/bin/python")
    if venv.exists():
        print("  !  No TTS engine in this interpreter, but .venv-tts has one.")
        print(f"     For audiobooks, run:  {venv} run_web.py")
    else:
        print("  !  No TTS engine installed — the audiobook panel will be "
              "disabled.\n     See requirements-audio.txt to set one up.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run the book_creator web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args()
    _audio_hint()
    main(host=args.host, port=args.port)
