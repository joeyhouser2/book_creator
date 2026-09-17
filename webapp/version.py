"""Which copy of the code a running server was started from.

The desktop shortcut starts the server, and a second double-click finds it
already running and just opens the browser. That is right until the code
changes: then the icon keeps showing yesterday's app, with nothing on screen to
say so, and a fix you just pulled looks as if it never landed. Fingerprinting
the source lets the launcher tell a current server from a stale one.

Standard library only -- the launcher imports this before anything heavy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# What the server actually runs. Tests, docs and output do not change it.
WATCHED = ("book_creator", "webapp")
SUFFIXES = (".py", ".js", ".css", ".html")


def code_version(root: Path = ROOT) -> str:
    """A short hash of every served source file's path, size and mtime.

    mtime rather than content: this runs on every double-click, and a change
    worth restarting for always touches the file.
    """
    h = hashlib.sha1()
    files = [root / "run_web.py"]
    for name in WATCHED:
        files += [p for p in (root / name).rglob("*")
                  if p.suffix in SUFFIXES and "__pycache__" not in p.parts]
    for p in sorted(files):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n"
                 .encode())
    return h.hexdigest()[:12]
