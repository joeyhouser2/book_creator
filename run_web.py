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
import os
import shutil
import socket
import subprocess
import threading
import time
import webbrowser


def _physical_gpus() -> int:
    """GPUs the driver reports, ignoring CUDA_VISIBLE_DEVICES."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0
    try:
        out = subprocess.run([exe, "--list-gpus"], capture_output=True,
                             text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return 0
    return len([l for l in out.stdout.splitlines() if l.startswith("GPU ")])


def unmask_gpus(mode: str = "all") -> str:
    """Let this process see every card, before CUDA is initialised.

    CUDA reads CUDA_VISIBLE_DEVICES once, when a context is first created, so
    this has to happen before anything imports torch -- which is why it runs
    at the top of the launcher rather than inside the audio module.

    A shell that exports CUDA_VISIBLE_DEVICES=0 (easy to acquire and easy to
    forget) leaves the larger card invisible: the device picker offers one GPU,
    and the biggest model that will "fit" is decided by an environment variable
    instead of by the hardware. Narration runs in this process, so unlike the
    corpus passes -- which are subprocesses and can be given their own
    environment -- there is no later opportunity to fix it.

    Also pins PCI ordering, so cuda:N means the same card here, in nvidia-smi,
    and in the corpus-pass subprocesses. Without it CUDA orders by speed and
    the indices disagree between the two.

    `mode` is "all" to see everything, "inherit" to leave the environment
    exactly as found, or an explicit list like "0,1".
    """
    if mode == "inherit":
        return ""
    count = _physical_gpus()
    if not count:
        return ""

    wanted = ",".join(str(i) for i in range(count)) if mode == "all" else mode
    previous = os.environ.get("CUDA_VISIBLE_DEVICES")
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = wanted
    if previous is not None and previous != wanted:
        return (f"CUDA_VISIBLE_DEVICES was {previous!r}, which hid "
                f"{count - len(previous.split(','))} of {count} GPUs from this "
                f"process; using {wanted!r} so every card is selectable.")
    return ""


# Imported after unmask_gpus is defined but called before `main` runs — see
# __main__ below. The import itself pulls in no CUDA.
from webapp.server import main  # noqa: E402


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


def _replace_stale(url: str, host: str, port: int) -> bool:
    """Stop an out-of-date server so this launch can start a current one.

    Returns True if the port is now free. A server running a build is left
    alone -- a narration is hours of GPU -- and so is anything on the port
    that does not answer as book_creator.
    """
    import json
    import urllib.error
    import urllib.request

    from webapp.version import code_version

    def call(path: str, data: bytes | None = None) -> dict:
        req = urllib.request.Request(url + path, data=data, method="POST" if data
                                     is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:       # 409 carries a body
            return json.loads(exc.read().decode("utf-8") or "{}")

    try:
        running = call("/api/version")
    except (OSError, ValueError):
        # No version endpoint. Either not book_creator at all, or one started
        # before this check existed -- which cannot be asked to step aside, and
        # cannot be killed blind either, since it may be hours into a build.
        try:
            with urllib.request.urlopen(url + "/", timeout=5) as resp:
                ours = b"book_creator" in resp.read(4096)
        except OSError:
            ours = False
        if ours:
            print(f"book_creator at {url} was started before this launcher "
                  "could update it, so it is still running older code. Close "
                  "its server window (once any build in it has finished) and "
                  "start the app again; from then on this happens by itself.")
        else:
            print(f"Something else is already using {url} — opening it anyway.")
        return False
    if running.get("version") == code_version():
        print(f"book_creator is already running at {url} — opening it.")
        return False
    if running.get("busy"):
        print(f"book_creator at {url} is running older code, but it is busy "
              f"({', '.join(running['busy'])}), so it has been left alone. "
              "Close its window once that finishes and start the app again "
              "to pick up the changes.")
        return False

    print("book_creator is running older code — restarting it.")
    try:
        call("/api/shutdown", b"{}")
    except (OSError, ValueError):
        pass                            # it may drop the connection as it exits
    deadline = time.time() + 15
    while time.time() < deadline:
        if not _in_use(host, port):
            return True
        time.sleep(0.25)
    print("  !  The old server did not exit; opening it as it is.")
    return False


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
    p.add_argument("--gpus", default="all", metavar="all|inherit|0,1",
                   help="Which CUDA devices this process may see. Default "
                        "'all' overrides a CUDA_VISIBLE_DEVICES inherited "
                        "from the shell, which otherwise hides cards from "
                        "the narrator.")
    args = p.parse_args()

    note = unmask_gpus(args.gpus)
    if note:
        print(f"  i  {note}")

    url = f"http://{args.host}:{args.port}"
    # Double-clicking the icon a second time should show you the app, not a
    # crash about the address being in use -- but the app as it is now, not
    # as it was when that server started.
    if _in_use(args.host, args.port) and not _replace_stale(url, args.host,
                                                             args.port):
        if args.open:
            webbrowser.open(url)
        raise SystemExit(0)

    _audio_hint()
    if args.open:
        threading.Thread(target=_open_when_ready,
                         args=(url, args.host, args.port), daemon=True).start()
    main(host=args.host, port=args.port)
