"""The desktop launcher: interpreter choice, icon, and the shortcut script.

None of this runs a server. What is worth testing is the part that decides
*how* to start one, plus the two files the shortcut depends on existing.
"""

from __future__ import annotations

import runpy
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_web():
    """run_web.py's helpers, without executing its __main__ block."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_run_web", ROOT / "run_web.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_free_port_is_not_reported_in_use():
    mod = _run_web()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    # The socket is closed, so nothing is listening there now.
    assert not mod._in_use("127.0.0.1", free)


def test_a_listening_port_is_reported_in_use():
    """This is what stops a second double-click crashing on "address in use"."""
    mod = _run_web()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        assert mod._in_use("127.0.0.1", srv.getsockname()[1])
    finally:
        srv.close()


def test_the_browser_is_not_opened_before_the_server_answers(monkeypatch):
    """Opening immediately races a cold start and shows a connection error,
    which looks exactly like the app being broken."""
    mod = _run_web()
    opened: list[str] = []
    monkeypatch.setattr(mod.webbrowser, "open", opened.append)
    monkeypatch.setattr(mod, "_in_use", lambda *a: False)
    mod._open_when_ready("http://x", "127.0.0.1", 1, timeout=0.5)
    assert opened == [], "it opened a browser at a server that never came up"


def test_the_browser_opens_once_the_server_answers(monkeypatch):
    mod = _run_web()
    opened: list[str] = []
    monkeypatch.setattr(mod.webbrowser, "open", opened.append)
    monkeypatch.setattr(mod, "_in_use", lambda *a: True)
    mod._open_when_ready("http://here", "127.0.0.1", 1, timeout=2)
    assert opened == ["http://here"]


def test_messages_printed_before_the_server_starts_are_encodable():
    """They contain em dashes and run before webapp.server.main reconfigures
    stdout; on a stock Windows console that would be a UnicodeEncodeError."""
    mod = _run_web()
    assert hasattr(mod, "_utf8_console")
    lines = (ROOT / "run_web.py").read_text(encoding="utf-8").splitlines()
    fixed = [i for i, l in enumerate(lines) if l.strip() == "_utf8_console()"]
    hinted = [i for i, l in enumerate(lines) if l.strip() == "_audio_hint()"]
    assert fixed and hinted, (fixed, hinted)
    assert fixed[0] < hinted[0], "the console is fixed only after the first print"


# --------------------------------------------------------------------------- #
# The files the shortcut points at
# --------------------------------------------------------------------------- #
def test_launcher_script_exists_and_prefers_the_tts_interpreter():
    cmd = (ROOT / "launch.cmd").read_text(encoding="utf-8")
    # The TTS virtualenv is checked first: narration lives only there.
    assert cmd.index(".venv-tts") < cmd.index('set "PY=python"')
    assert "run_web.py --open" in cmd
    # Relative paths (input/, output/, cache/) only work from the repo root.
    assert 'cd /d "%~dp0"' in cmd


def test_shortcut_installer_asks_windows_for_the_desktop():
    r"""A OneDrive-backed Desktop is not %USERPROFILE%\Desktop, and a shortcut
    written to the wrong one simply never appears."""
    ps = (ROOT / "install_shortcut.ps1").read_text(encoding="utf-8")
    assert 'GetFolderPath("Desktop")' in ps
    assert "WorkingDirectory" in ps


@pytest.mark.skipif(not (ROOT / "assets" / "book_creator.ico").exists(),
                    reason="icon not built (run python make_icon.py)")
def test_icon_carries_every_size_windows_asks_for():
    """Windows picks a different size for the desktop, the taskbar and
    Alt-Tab; one large bitmap scaled down turns the laurel to mush."""
    Image = pytest.importorskip("PIL.Image", reason="needs Pillow")
    import PIL.Image

    with PIL.Image.open(ROOT / "assets" / "book_creator.ico") as im:
        sizes = {s[0] for s in im.info.get("sizes", [])}
    assert {16, 32, 48, 256}.issubset(sizes), sizes


# --------------------------------------------------------------------------- #
# GPU visibility
# --------------------------------------------------------------------------- #
def test_inherit_leaves_the_environment_alone(monkeypatch):
    mod = _run_web()
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert mod.unmask_gpus("inherit") == ""
    assert __import__("os").environ["CUDA_VISIBLE_DEVICES"] == "0"


def test_a_masking_env_var_is_overridden_and_reported(monkeypatch):
    """A shell that exports CUDA_VISIBLE_DEVICES=0 leaves the larger card
    invisible, and the biggest model that "fits" is then decided by an
    environment variable rather than by the hardware."""
    import os

    mod = _run_web()
    monkeypatch.setattr(mod, "_physical_gpus", lambda: 2)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    note = mod.unmask_gpus("all")
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0,1"
    assert "hid 1 of 2" in note


def test_pci_ordering_is_pinned(monkeypatch):
    """So cuda:N means the same card here, in nvidia-smi, and in the
    corpus-pass subprocesses; CUDA's default order is by speed."""
    import os

    mod = _run_web()
    monkeypatch.setattr(mod, "_physical_gpus", lambda: 2)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    mod.unmask_gpus("all")
    assert os.environ["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"


def test_an_explicit_list_is_honoured(monkeypatch):
    import os

    mod = _run_web()
    monkeypatch.setattr(mod, "_physical_gpus", lambda: 2)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    mod.unmask_gpus("1")
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "1"


def test_no_gpus_means_no_change(monkeypatch):
    """A CPU-only machine should not have the variable invented for it."""
    import os

    mod = _run_web()
    monkeypatch.setattr(mod, "_physical_gpus", lambda: 0)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    assert mod.unmask_gpus("all") == ""
    assert "CUDA_VISIBLE_DEVICES" not in os.environ


def test_unmasking_happens_before_the_server_starts():
    """CUDA reads the variable once, when a context is first created, so it
    has to be set before anything touches torch."""
    lines = (ROOT / "run_web.py").read_text(encoding="utf-8").splitlines()
    called = [i for i, l in enumerate(lines) if l.strip().startswith("note = unmask_gpus(")]
    served = [i for i, l in enumerate(lines) if l.strip().startswith("main(host=")]
    assert called and served and called[0] < served[0]
