#!/usr/bin/env python
"""Launch the book_creator web UI.

    pip install -r requirements-web.txt
    python run_web.py            # then open http://127.0.0.1:5000
    python run_web.py --open     # ... and open a browser when it is ready

`--open` is what the desktop shortcut uses (see launch.cmd): double-clicking
an icon should end with the app on screen, not with a terminal telling you a
URL to type.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

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


def _in_use(host: str, port: int) -> bool:
    """Whether something is already listening there."""
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host,
                             port)) == 0


def _open_when_ready(url: str, host: str, port: int, timeout: float = 40.0) -> None:
    """Open a browser once the server answers, not before.

    Opening immediately races the server and shows a connection error on a
    cold start, which for someone who double-clicked an icon looks exactly
    like the app being broken.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _in_use(host, port):
            webbrowser.open(url)
            return
        time.sleep(0.25)
    print(f"  !  Server did not come up within {timeout:.0f}s; open {url} "
          f"yourself once it does.")


def _utf8_console() -> None:
    """Make stdout printable before anything prints to it.

    webapp.server.main does this too, but several messages here come first --
    the audio hint, the already-running notice -- and they contain em dashes.
    On a stock Windows console (cp1252) that is a UnicodeEncodeError, so the
    shortcut would open a window, throw, and close: the app would look broken
    at exactly the moment it was telling you something useful.
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_console()
    p = argparse.ArgumentParser(description="Run the book_creator web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--open", action="store_true",
                   help="Open a browser once the server is answering.")
    args = p.parse_args()

    url = f"http://{args.host}:{args.port}"
    # Double-clicking the icon a second time should show you the app, not a
    # crash about the address being in use.
    if _in_use(args.host, args.port):
        print(f"book_creator is already running at {url} — opening it.")
        if args.open:
            webbrowser.open(url)
        raise SystemExit(0)

    _audio_hint()
    if args.open:
        threading.Thread(target=_open_when_ready,
                         args=(url, args.host, args.port), daemon=True).start()
    main(host=args.host, port=args.port)
