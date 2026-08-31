"""Run the `latin` repo's translation and Victorian-stylizer passes as jobs.

book_creator reads the corpus **read-only** (see corpus.py) -- deliberately, so
this project can never corrupt the library it borrows from. But the corpus is
mostly *unfinished*: at the time of writing ~946k Latin and ~56k Greek segments
have no English at all, and only a tenth of what is translated has been through
the Victorian stylizer. Browsing to a work that is not ready and having no way
to start it from here is a dead end.

So the writing is done by the latin repo's own scripts, spawned as a
subprocess, and this module just drives them and relays their output:

    scripts/translate_pending.py --doc-id N     ->  segments.english_text
    scripts/stylize_library.py   --doc-id N     ->  segments.english_styled

Why a subprocess rather than importing `pipeline.Library` here:

* It keeps torch and a loaded CUDA context out of the Flask process. A wedged
  `generate()` would otherwise take the whole web UI down with it, and the
  model would hold VRAM for the life of the server rather than the life of
  the job.
* The latin repo has its own virtualenv (`latinvenv/`). Even though both
  environments currently agree on transformers 5.0.0, nothing keeps them in
  step, and its venv is the one its models are known to load under.
* Both scripts are already resumable and commit in chunks, so cancelling (or
  crashing) costs at most the current chunk. Re-running continues where it
  stopped -- which is the only sane behaviour for a pass that can run for hours.

Writes land in the same SQLite file this project reads. That is safe because
the corpus runs in WAL mode: one writer and many readers coexist, so a build
can go on reading while a translation pass writes.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .corpus import _DB_RELATIVE, _REPO_CANDIDATES

# Both scripts print one progress line per committed chunk, in the same shape:
#   [42] Corpus Corporum    1,200/9,000  | overall 1,200/9,000 3.1 seg/s ETA 0.7h
_PROGRESS = re.compile(
    r"overall\s+([\d,]+)\s*/\s*([\d,]+)"
    r"(?:\s+([\d.]+)\s*seg/s)?(?:\s+ETA\s+([\d.]+)\s*h)?")
# ... and finish with a total: "Done. Translated 9,000 segments across 1 docs".
_FINAL = re.compile(r"Done\.\s+(?:Translated|Stylized)\s+([\d,]+)\s+segments")
# The up-front plan, which is the total even before any chunk has landed.
_PLANNED = re.compile(r"===.*?([\d,]+)\s+segments")
# A tqdm frame: "Loading weights:  12%|#### | 61/512 [00:00<00:00, 995it/s]".
# Python's universal newlines turn tqdm's carriage returns into line breaks, so
# a single model load arrives here as hundreds of near-identical "lines". They
# are suppressed at the source below; this catches whatever still leaks out of
# a dependency that does not honour the environment variables.
_TQDM = re.compile(r"\d+%\|.*\||\d+/\d+\s*\[\d+:\d+<")

PRESETS = ("victorian_prose", "verse_blank", "verse_couplet")
BACKENDS = ("t5", "llm")


class JobError(RuntimeError):
    """The latin repo, its interpreter, or one of its scripts is unusable."""


# --------------------------------------------------------------------------- #
# Locating the repo and the interpreter to run it with
# --------------------------------------------------------------------------- #
def _looks_like_repo(p: Path) -> bool:
    """The repo shape: a scripts directory and a corpus to write into.

    Deliberately not a check for one named script -- `run` reports a missing
    script itself, and conflating "this is not the repo" with "this repo is
    missing that pass" sends the search off to a different checkout when the
    honest answer is that one file is absent.
    """
    return (p / "scripts").is_dir() and (p / _DB_RELATIVE).is_file()


def find_repo(path: str | None = None) -> Path:
    """Resolve the latin repo checkout (not the .db), or raise JobError.

    `corpus.find_db` accepts a bare database file so the corpus can be read
    from a copy. Writing needs the actual repo, because the scripts, the
    trained models, and the virtualenv all live beside it.

    An explicitly named location -- an argument or LATIN_REPO -- is used or
    rejected on its own merits; it never falls back to a checkout found
    somewhere else. These passes *write*, and quietly translating into a
    different corpus than the one the caller named is the worst thing this
    module could do.
    """
    for raw, source in ((path, "the path given"),
                        (os.environ.get("LATIN_REPO"), "LATIN_REPO")):
        if not raw:
            continue
        p = Path(raw).expanduser()
        if _looks_like_repo(p):
            return p.resolve()
        detail = ("it is a database file, not a repo checkout -- a copied-out "
                  "corpus.db is enough to read from, but writing needs the "
                  "repo, its scripts and its models"
                  if p.suffix == ".db" else
                  f"expected {p / 'scripts'} and {p / _DB_RELATIVE} to exist")
        raise JobError(f"{source} ({p}) is not a usable latin repo: {detail}")

    for raw in _REPO_CANDIDATES:
        p = Path(raw).expanduser()
        if _looks_like_repo(p):
            return p.resolve()

    tried = "\n  ".join(str(Path(c).expanduser()) for c in _REPO_CANDIDATES)
    raise JobError(
        "Could not find the latin repo checkout to run translation from. Set "
        "LATIN_REPO to it (a bare corpus.db is enough to read from, but not to "
        "translate into). Tried:\n  " + (tried or "(nothing to try)"))


def find_python(repo: Path) -> Path:
    """The interpreter to run the latin scripts with: its venv, else ours.

    Falling back to `sys.executable` is worth doing rather than failing -- this
    project's environment happens to carry torch and transformers too, so a
    checkout without a built venv still works.
    """
    for rel in ("latinvenv/Scripts/python.exe", "latinvenv/bin/python",
                ".venv/Scripts/python.exe", ".venv/bin/python"):
        cand = repo / rel
        if cand.is_file():
            return cand
    return Path(sys.executable)


# --------------------------------------------------------------------------- #
# GPU selection
# --------------------------------------------------------------------------- #
@dataclass
class Gpu:
    index: int
    name: str
    total_mb: int

    def as_dict(self) -> dict:
        return {"index": self.index, "name": self.name, "total_mb": self.total_mb}


def gpus() -> list[Gpu]:
    """Every CUDA card nvidia-smi can see, in PCI order.

    Asked of nvidia-smi rather than torch on purpose: the web process should
    not import torch just to list devices, and nvidia-smi reports the machine's
    real hardware regardless of whatever CUDA_VISIBLE_DEVICES the server was
    started with -- which is the whole point, since that variable is what hides
    a card from the job.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []

    found: list[Gpu] = []
    for line in out.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            found.append(Gpu(int(parts[0]), parts[1], int(parts[2])))
        except ValueError:
            continue
    return found


def best_gpu() -> Gpu | None:
    """The card with the most memory -- never simply device 0.

    This machine has a 16 GB 4060 Ti and a 12 GB 4070 SUPER, and the shell sets
    CUDA_VISIBLE_DEVICES=0 globally. CUDA's default enumeration is fastest-first
    rather than PCI order, so "device 0" is the *smaller* card. Picking by
    memory and pinning PCI order below is what actually gets the 16 GB.
    """
    return max(gpus(), key=lambda g: g.total_mb, default=None)


def _cuda_env(device: int | str | None) -> dict[str, str]:
    """CUDA_VISIBLE_DEVICES for the child, as PCI-ordered indices.

    CUDA_DEVICE_ORDER is pinned to PCI_BUS_ID so the index means the same thing
    here, in nvidia-smi, and in the child -- without it the mapping silently
    depends on relative card speed.
    """
    if device == "cpu":
        return {"CUDA_VISIBLE_DEVICES": "", "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    if device in (None, "", "auto"):
        chosen = best_gpu()
        if chosen is None:                  # no CUDA at all; let the child decide
            return {}
        index = chosen.index
    else:
        index = int(device)
    return {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": str(index)}


# --------------------------------------------------------------------------- #
# Building the command
# --------------------------------------------------------------------------- #
def _terminate_tree(proc: subprocess.Popen) -> None:
    """Kill the pass *and its children*, not just the process we launched.

    The script re-execs a worker to do the generating (on Windows that worker
    runs under the base interpreter, not the venv's), and it is the worker that
    holds the CUDA context. Terminating only our direct child would leave that
    worker alive with the whole card still allocated -- so a cancelled pass
    would quietly make the GPU unusable for the next one.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # No process groups to signal; taskkill /T walks the tree for us.
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
            return
        except (OSError, subprocess.SubprocessError):
            pass          # fall through to the plain terminate below
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            return
        except (OSError, AttributeError):
            pass
    proc.terminate()


def _translate_cmd(doc_id: int, opts: dict) -> list[str]:
    return ["scripts/translate_pending.py", "--doc-id", str(doc_id),
            "--batch-size", str(int(opts.get("batch_size") or 16)),
            "--chunk", str(int(opts.get("chunk") or 200)),
            "--max-length", str(int(opts.get("max_length") or 256))]


def _stylize_cmd(doc_id: int, opts: dict) -> list[str]:
    preset = opts.get("preset") or "victorian_prose"
    if preset not in PRESETS:
        raise JobError(f"unknown preset {preset!r}; choose from {list(PRESETS)}")
    backend = opts.get("backend") or "t5"
    if backend not in BACKENDS:
        raise JobError(f"unknown backend {backend!r}; choose from {list(BACKENDS)}")
    return ["scripts/stylize_library.py", "--doc-id", str(doc_id),
            "--preset", preset, "--backend", backend,
            "--batch-size", str(int(opts.get("batch_size") or 20))]


_BUILDERS = {"translate": _translate_cmd, "stylize": _stylize_cmd}


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #
def run(kind: str, doc_id: int, *, opts: dict | None = None,
        on_log=None, on_progress=None, should_stop=None,
        repo_path: str | None = None) -> dict:
    """Run one pass over one document, relaying output line by line.

    Returns {"segments": n, "cancelled": bool}. Raises JobError if the pass
    cannot be started or exits non-zero.
    """
    if kind not in _BUILDERS:
        raise JobError(f"unknown pass {kind!r}; choose from {list(_BUILDERS)}")
    opts = opts or {}
    repo = find_repo(repo_path)
    python = find_python(repo)
    script, *args = _BUILDERS[kind](doc_id, opts)
    if not (repo / script).is_file():
        raise JobError(f"{script} is missing from the latin repo at {repo}")

    env = {**os.environ, **_cuda_env(opts.get("device")),
           # The scripts print Latin and Greek titles; the default Windows
           # console codepage would raise UnicodeEncodeError inside the child
           # and kill the pass partway through for no good reason.
           "PYTHONIOENCODING": "utf-8",
           "PYTHONUNBUFFERED": "1",
           # Loading a model draws a tqdm bar per shard, and every redraw
           # reaches us as its own line -- hundreds of them, burying the
           # output that matters.
           "TQDM_DISABLE": "1",
           "HF_HUB_DISABLE_PROGRESS_BARS": "1"}

    log = on_log or (lambda _msg: None)
    log("$ " + " ".join([python.name, script, *args]))
    dev = env.get("CUDA_VISIBLE_DEVICES")
    if dev:
        card = next((g for g in gpus() if str(g.index) == dev), None)
        log(f"  GPU {dev}" + (f" - {card.name} ({card.total_mb} MB)" if card else ""))
    elif dev == "":
        log("  CPU only (this will be slow)")

    try:
        proc = subprocess.Popen(
            [str(python), script, *args], cwd=str(repo), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            # So the whole pass can be signalled as one group on POSIX;
            # Windows uses taskkill /T instead (see _terminate_tree).
            start_new_session=(os.name != "nt"))
    except OSError as exc:
        raise JobError(f"could not start {python}: {exc}") from exc

    # Cancellation is watched on its own thread rather than between output
    # lines. A batch of twenty segments can take minutes on a big model, and
    # the script prints nothing until it commits -- so a stop checked only in
    # the read loop would appear to do nothing for as long as the batch runs.
    stopping = threading.Event()   # the stop was seen and the child killed
    finished = threading.Event()   # the read loop is done; stand the watchdog down

    def watch_for_stop() -> None:
        while not finished.wait(1.0):
            if should_stop and should_stop():
                stopping.set()
                _terminate_tree(proc)
                return

    watchdog = None
    if should_stop:
        watchdog = threading.Thread(target=watch_for_stop, daemon=True)
        watchdog.start()

    total = 0
    segments = 0
    cancelled = False
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line or _TQDM.search(line):
                continue

            hit = _PROGRESS.search(line)
            if hit:
                # A progress line supersedes the one before it, so it becomes
                # the job's progress rather than another entry in the log. A
                # long pass emits thousands of these; logging them all would
                # bury the messages worth reading and ship half a megabyte of
                # superseded text to the browser on every poll.
                done = int(hit.group(1).replace(",", ""))
                total = int(hit.group(2).replace(",", "")) or total
                if on_progress:
                    on_progress(done, total, {
                        "rate": float(hit.group(3)) if hit.group(3) else None,
                        "eta_hours": float(hit.group(4)) if hit.group(4) else None,
                    })
            else:
                log(line)
                if not total:
                    planned = _PLANNED.search(line)
                    if planned:
                        total = int(planned.group(1).replace(",", ""))
                        if on_progress:
                            on_progress(0, total, None)

                final = _FINAL.search(line)
                if final:
                    segments = int(final.group(1).replace(",", ""))

            if stopping.is_set():
                break
    finally:
        finished.set()
        if watchdog:
            watchdog.join(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _terminate_tree(proc)
            code = proc.wait()

    if stopping.is_set():
        cancelled = True
        log("... stopped. Segments already written are kept; run it again to "
            "continue from there.")
    if cancelled:
        return {"segments": segments, "cancelled": True}
    if code != 0:
        raise JobError(f"{script} exited with status {code} - see the log above")
    return {"segments": segments, "cancelled": False}


def status(repo_path: str | None = None) -> dict:
    """Whether passes can be run at all, for the UI to grey out its buttons."""
    cards = [g.as_dict() for g in gpus()]
    try:
        repo = find_repo(repo_path)
    except JobError as exc:
        return {"available": False, "error": str(exc), "gpus": cards}
    python = find_python(repo)
    best = best_gpu()
    return {
        "available": True,
        "repo": str(repo),
        "python": str(python),
        "own_venv": python != Path(sys.executable),
        "gpus": cards,
        "default_gpu": best.index if best else None,
        "presets": list(PRESETS),
        "backends": list(BACKENDS),
    }
