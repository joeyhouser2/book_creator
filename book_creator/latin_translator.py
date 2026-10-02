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

import json
import subprocess
import sys
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
_BRIDGE = r'''
import json, sys
sys.path.insert(0, ".")
from core.translator import NLLBTranslator

req = json.loads(sys.stdin.read())
tr = NLLBTranslator(model_name=req["model"], src_lang=req["src_lang"])
out = tr.translate_batch(req["texts"], batch_size=req.get("batch", 8))
# The model's own loading chatter goes to stdout, so the result is framed.
sys.stdout.write("\n===TRANSLATIONS===\n")
sys.stdout.write(json.dumps({"translations": out}))
'''


class LatinRepoTranslator:
    """A translator backed by a model in the sibling `latin` repo."""

    def __init__(self, lang: str = "la", *, repo: str | None = None,
                 batch: int = 8, timeout: int | None = None):
        lang = lang.lower()
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

    def __call__(self, texts: list[str]) -> list[str]:
        texts = list(texts)
        todo = [i for i, t in enumerate(texts) if t and t.strip()]
        if not todo:
            return ["" for _ in texts]

        repo = self.repo
        python = corpus_jobs.find_python(repo)
        payload = json.dumps({"model": self.model, "src_lang": self.src_lang,
                              "texts": [texts[i] for i in todo],
                              "batch": self.batch})
        proc = subprocess.run(
            [str(python), "-c", _BRIDGE], input=payload, cwd=str(repo),
            capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
            raise RuntimeError(
                f"The latin repo's translator failed (exit {proc.returncode}) "
                f"running {self.model} in {repo}:\n  " + "\n  ".join(tail))

        marker = "\n===TRANSLATIONS===\n"
        if marker not in proc.stdout:
            raise RuntimeError(
                "The latin repo's translator produced no result block. It "
                f"printed:\n  " + "\n  ".join(proc.stdout.strip().splitlines()[-6:]))
        got = json.loads(proc.stdout.rsplit(marker, 1)[1])["translations"]
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
