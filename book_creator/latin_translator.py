"""Translate Latin and Greek with the `latin` repo's own fine-tuned models.

The Opus-MT defaults in translators.py have no Latin worth the name: there is no
opus-mt-la-en at all, and the multi-source Italic model renders "Arma virumque
cano" as "Guns for man who is lame". The sibling `latin` repo has fine-tuned
NLLB models for exactly this (models/nllb-latin, models/nllb-greek*), and they
are markedly better -- "Gallia est omnis divisa in partes tres" comes back as
"The whole of Gaul is divided into three parts".

Run as a subprocess under the latin repo's own virtualenv, for the reasons
corpus_jobs.py already gives: torch and a CUDA context stay out of this process,
a wedged generate() cannot take the web UI down with it, and that venv is the
one those models are known to load under. This module only adds the ability to
translate ARBITRARY text -- corpus_jobs drives the same repo's scripts over
corpus documents by id, which is no use for a text that is not in the corpus.

Register it like any other translator:

    from book_creator import latin_translator
    latin_translator.register("la")      # or "grc"

It names itself after the model it runs, so mt_cache remembers its output
between builds like any other.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import corpus_jobs, translators

# Which model in the latin repo serves which language. Greek has several; the
# plain one is the safe default, since the archaic/v2/v3 variants are trained for
# particular corpora.
MODELS = {
    "la": ("models/nllb-latin", "lat_Latn"),
    "grc": ("models/nllb-greek", "ell_Grek"),
}

# Runs inside the latin repo, under its venv, with the repo as cwd. Reads
# {"texts": [...]} on stdin and writes {"translations": [...]} on stdout, so
# nothing has to be quoted onto a command line and a 20,000-line epic is one
# model load rather than one per chunk.
# Runs inside the latin repo, under its venv, with the repo as cwd. It loads the
# model ONCE and then serves batches: one JSON request per line on stdin, one
# JSON response per line on stdout. The earlier version took a single batch and
# exited, which meant mt_cache's chunking reloaded a 2.5 GB NLLB model about
# twenty times for one book -- most of the wall time of a Pontano build was
# model loading, not translating.
_BRIDGE = r"""
import json, sys
sys.path.insert(0, ".")
from core.translator import NLLBTranslator

req = json.loads(sys.stdin.readline())
tr = NLLBTranslator(model_name=req["model"], src_lang=req["src_lang"])
batch = req.get("batch", 8)
# The model's own loading chatter goes to stdout, so the protocol starts only
# once it is quiet and the marker has been printed.
out = tr.translate_batch(req["texts"], batch_size=batch)
sys.stdout.write("\n===READY===\n")
sys.stdout.write(json.dumps({"translations": out}) + "\n")
sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    texts = json.loads(line)["texts"]
    out = tr.translate_batch(texts, batch_size=batch)
    sys.stdout.write(json.dumps({"translations": out}) + "\n")
    sys.stdout.flush()
"""


class LatinRepoTranslator:
    """A translator backed by a model in the sibling `latin` repo."""

    def __init__(self, lang: str = "la", *, repo: str | None = None,
                 batch: int = 8, timeout: int | None = None):
        lang = lang.lower()
        # Set before the validation below, because __del__ runs even on an
        # instance whose __init__ raised, and close() would then trip over the
        # attribute not existing yet.
        self._proc = None
        self._errlog = None
        if lang not in MODELS:
            raise ValueError(
                f"No latin-repo model for {lang!r}. Known: {', '.join(MODELS)}.")
        self.lang = lang
        self.model, self.src_lang = MODELS[lang]
        self._repo = repo
        self.batch = batch
        self.timeout = timeout
        # mt_cache keys on this, so a rebuild reuses what the model already said.
        self.model_name = f"latin-repo:{self.model}"

    @property
    def repo(self) -> Path:
        return corpus_jobs.find_repo(self._repo)

    def _start(self, first_batch: list[str]) -> list[str]:
        """Spawn the worker, load the model, and return the first batch."""
        repo = self.repo
        python = corpus_jobs.find_python(repo)
        # UTF-8 both ways: a Windows console defaults to cp1252 and the first
        # Latin long s or Greek breathing kills the pipe.
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        # stderr goes to a FILE, not a pipe. transformers writes a progress bar
        # per shard while loading, tens of thousands of lines; an undrained
        # stderr pipe fills its 64 KB buffer, the child blocks writing to it and
        # this process blocks reading stdout -- a deadlock that looks exactly
        # like the model being slow to start.
        self._errlog = tempfile.NamedTemporaryFile(
            mode="w+", suffix=".log", prefix="nllb-", delete=False,
            encoding="utf-8")
        self._proc = subprocess.Popen(
            [str(python), "-c", _BRIDGE], cwd=str(repo), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._errlog, text=True, encoding="utf-8", bufsize=1)
        # A worker holds a 2.5 GB model on the GPU. If the build dies -- a
        # timeout, a Ctrl-C -- nothing else would reap it, and the next run
        # would find the card already full.
        atexit.register(self.close)
        self._send({"model": self.model, "src_lang": self.src_lang,
                    "texts": first_batch, "batch": self.batch})
        # Skip the model's loading chatter up to the ready marker.
        for line in self._proc.stdout:
            if line.strip() == "===READY===":
                break
        else:
            raise RuntimeError(self._died("never became ready"))
        return self._read()

    def _send(self, payload: dict) -> None:
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _read(self) -> list[str]:
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError(self._died("closed its output"))
        return json.loads(line)["translations"]

    def _died(self, what: str) -> str:
        err = ""
        if self._errlog is not None:
            try:
                self._errlog.flush()
                tail = Path(self._errlog.name).read_text(encoding="utf-8",
                                                         errors="replace")
                # The loading bars are not the error; the last real lines are.
                lines = [l for l in tail.splitlines()
                         if l.strip() and "Loading weights" not in l]
                err = "\n  ".join(lines[-6:])
            except OSError:
                pass
        return (f"The latin repo's translator {what} running {self.model} "
                f"in {self.repo}:\n  {err}")

    def __del__(self):
        self.close()

    def close(self) -> None:
        """Let the model go. Safe to call more than once, and at interpreter
        shutdown, where anything may already be half torn down."""
        proc = getattr(self, "_proc", None)
        if proc is not None:
            self._proc = None
            try:
                proc.stdin.close()
                proc.wait(timeout=20)
            except Exception:  # noqa: BLE001 - shutting down regardless
                # kill() may itself be gone -- a stubbed process in a test, or
                # a module already collected at exit. Nothing left to do then.
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        errlog = getattr(self, "_errlog", None)
        if errlog is not None:
            self._errlog = None
            try:
                errlog.close()
                Path(errlog.name).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 - best effort
                pass

    def __call__(self, texts: list[str]) -> list[str]:
        texts = list(texts)
        todo = [i for i, t in enumerate(texts) if t and t.strip()]
        if not todo:
            return ["" for _ in texts]
        batch = [texts[i] for i in todo]

        if self._proc is None or self._proc.poll() is not None:
            got = self._start(batch)
        else:
            self._send({"texts": batch})
            got = self._read()
        if len(got) != len(todo):
            raise ValueError(
                f"translator returned {len(got)} items for {len(todo)} inputs")

        out = ["" for _ in texts]
        for i, english in zip(todo, got):
            out[i] = english
        return out


def available(repo: str | None = None) -> tuple[bool, str]:
    """Whether the repo, its venv and at least one model are actually there."""
    try:
        root = corpus_jobs.find_repo(repo)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return False, str(exc)
    try:
        corpus_jobs.find_python(root)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    missing = [m for m, _ in MODELS.values() if not (root / m).exists()]
    if len(missing) == len(MODELS):
        return False, f"no translation models in {root} (looked for {missing})"
    return True, str(root)


def register(lang: str = "la", **kwargs) -> LatinRepoTranslator:
    """Register the latin repo's model for `lang` with the translator registry."""
    tr = LatinRepoTranslator(lang, **kwargs)
    translators.register(lang, tr)
    return tr
