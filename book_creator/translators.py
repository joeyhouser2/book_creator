"""Pluggable source-to-English translators, registered per language.

This is the *interface* your Latin/Greek translator models plug into. The
MT-pivot aligner (align_mt) asks a translator to render source segments as rough
English, then aligns those against the real English translation — matching
English-to-English is far more reliable than cross-lingual matching, especially
for Latin and Ancient Greek where general models are weak.

A translator is any callable:  translate(texts: list[str]) -> list[str]
returning one English string per input, in order. Register one per language:

    from book_creator import translators
    translators.register("la", my_latin_translator)
    translators.register("grc", my_greek_translator)

Three adapters are provided: LocalTranslator (a Hugging Face model run on this
machine), HTTPTranslator (your model served on a URL) and CallableTranslator (a
plain Python function). Until a translator is registered for a language, the MT
aligner is unavailable for it and `auto` falls back to the embedding /
Gale-Church backends.

A registered translator has a second job besides alignment: `BookSpec.translate`
asks the pipeline to *generate* the missing English side with it, for an original
that has no published translation at all (see the pipeline's
_chapters_from_machine_translation). That English then gets printed, so it is disclosed on the
copyright page as machine translation rather than passed off as a human one.

Note what the models can and cannot read. The built-in Opus-MT defaults below
are trained on the MODERN form of each language: they handle Hugo, Voltaire or
Klopstock, and produce noise on Middle High German, Old French or Middle French.
A historical language stage needs a model fine-tuned for it, named explicitly.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

# Treat modern-Greek and Ancient-Greek codes as interchangeable for routing.
_LANG_ALIASES = {"el": "grc", "grc": "grc"}


@runtime_checkable
class Translator(Protocol):
    def __call__(self, texts: list[str]) -> list[str]: ...


_REGISTRY: dict[str, Translator] = {}


def _norm(lang: str | None) -> str:
    return _LANG_ALIASES.get((lang or "").lower(), (lang or "").lower())


def register(lang: str, translator: Translator) -> None:
    _REGISTRY[_norm(lang)] = translator


def get(lang: str | None) -> Translator | None:
    return _REGISTRY.get(_norm(lang))


def available(lang: str | None) -> bool:
    return get(lang) is not None


def clear() -> None:
    _REGISTRY.clear()


class CallableTranslator:
    """Wrap any function `fn(texts) -> translations`."""

    def __init__(self, fn: Callable[[list[str]], list[str]]):
        self._fn = fn

    def __call__(self, texts: list[str]) -> list[str]:
        return list(self._fn(texts))


class TranslatorUnavailable(RuntimeError):
    """A translator was registered but its model cannot be loaded here."""


def _torch_version() -> str:
    try:
        import torch
        return f"torch {torch.__version__}"
    except Exception:  # noqa: BLE001 - only used to phrase an error message
        return "torch (not installed)"


# Opus-MT covers the modern languages this app's language box can be set to.
# Each is a ~300 MB download on first use, cached by huggingface_hub, and each
# reads the MODERN language only -- see the module docstring. There is no
# opus-mt-pt-en, so Portuguese goes through the multi-source Romance model.
LOCAL_MODELS = {
    "de": "Helsinki-NLP/opus-mt-de-en",
    "fr": "Helsinki-NLP/opus-mt-fr-en",
    "it": "Helsinki-NLP/opus-mt-it-en",
    "es": "Helsinki-NLP/opus-mt-es-en",
    "nl": "Helsinki-NLP/opus-mt-nl-en",
    "pt": "Helsinki-NLP/opus-mt-ROMANCE-en",
}


class LocalTranslator:
    """A Hugging Face seq2seq translation model, run on this machine.

    No service to start, unlike HTTPTranslator: the weights are downloaded once
    and then run locally, on the GPU when there is one. The model is loaded on
    the FIRST CALL rather than in __init__, so registering a translator for a
    language you do not end up building costs nothing but a dictionary entry.

    Blank inputs are passed straight through. A translation model given an empty
    string will happily hallucinate a sentence into it, and on the alignment
    path that invents a match where the text says there is none.
    """

    def __init__(self, model: str, *, batch: int = 16, device: str | None = None,
                 max_new_tokens: int = 512):
        self.model_name = model
        self.batch = batch
        self.device = device
        self.max_new_tokens = max_new_tokens
        self._model = None
        self._tok = None

    def _load(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        if self.device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._tok = AutoTokenizer.from_pretrained(self.model_name)
        try:
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
        except ValueError as exc:
            # transformers refuses torch.load on torch < 2.6 (CVE-2025-32434),
            # and several Opus-MT repos -- opus-mt-de-en among them -- still
            # ship only pytorch_model.bin with no safetensors copy. Say which
            # of the two is missing rather than re-raising a CVE notice that
            # never mentions the model.
            if "safetensors" not in str(exc):
                raise
            raise TranslatorUnavailable(
                f"{self.model_name} publishes its weights only as "
                "pytorch_model.bin, and this environment's torch is too old "
                f"for transformers to load that ({_torch_version()} < 2.6). "
                "Either upgrade torch to 2.6+, or name a model that ships "
                "safetensors (opus-mt-fr-en does; opus-mt-de-en does not)."
            ) from exc
        self._model.to(self.device)
        self._model.eval()

    def __call__(self, texts: list[str]) -> list[str]:
        import torch

        texts = list(texts)
        todo = [i for i, t in enumerate(texts) if t and t.strip()]
        if not todo:
            return ["" for _ in texts]
        self._load()

        out = ["" for _ in texts]
        for k in range(0, len(todo), self.batch):
            idx = todo[k:k + self.batch]
            enc = self._tok([texts[i] for i in idx], return_tensors="pt",
                            padding=True, truncation=True, max_length=512)
            enc = {k2: v.to(self.device) for k2, v in enc.items()}
            with torch.inference_mode():
                gen = self._model.generate(**enc, max_new_tokens=self.max_new_tokens)
            for i, row in zip(idx, self._tok.batch_decode(gen, skip_special_tokens=True)):
                out[i] = row.strip()
        return out


def has_local(lang: str | None) -> bool:
    """Is there a built-in model for this language? (Routes through the same
    alias table as everything else, so "el" and "grc" answer alike.)"""
    return _norm(lang) in LOCAL_MODELS


def use_local(lang: str, model: str | None = None, **kwargs) -> LocalTranslator:
    """Register the built-in local model for `lang` (or `model` if given)."""
    lang = _norm(lang)
    name = model or LOCAL_MODELS.get(lang)
    if not name:
        raise ValueError(
            f"No built-in translation model for {lang!r}. Known: "
            f"{', '.join(sorted(LOCAL_MODELS))}. Pass `model=` to name one, "
            "but note a historical language stage needs a model trained on it.")
    tr = LocalTranslator(name, **kwargs)
    register(lang, tr)
    return tr


class HTTPTranslator:
    """Call a translation service over HTTP.

    Contract — your model's repo serves an endpoint that accepts:
        POST <url>   {"src_lang": "la", "texts": ["...", "..."]}
    and returns:
        200          {"translations": ["...", "..."]}   (same length & order)

    Requests are batched; translations are concatenated back in order.
    """

    def __init__(self, url: str, src_lang: str, *, batch: int = 32,
                 timeout: int = 120, headers: dict | None = None):
        self.url = url
        self.src_lang = src_lang
        self.batch = batch
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def __call__(self, texts: list[str]) -> list[str]:
        import requests

        out: list[str] = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i:i + self.batch]
            resp = requests.post(
                self.url, json={"src_lang": self.src_lang, "texts": chunk},
                headers=self.headers, timeout=self.timeout,
            )
            resp.raise_for_status()
            translations = resp.json()["translations"]
            if len(translations) != len(chunk):
                raise ValueError(
                    f"translator returned {len(translations)} items for "
                    f"{len(chunk)} inputs"
                )
            out.extend(translations)
        return out


class OllamaTranslator:
    """A chat model served by a local Ollama, prompted to translate verse.

    Opus-MT reads modern French; on Ronsard it renders *yvoire* as "yogurt" and
    *sourci* as "the sour". A general chat model reads the early-modern
    spelling and returns sense, so for historical stages this is the better
    adapter -- at roughly 2 s a line against Opus-MT's few milliseconds.

    Segments go to the model several at a time as a numbered list, which
    amortises the prompt and gives it the neighbouring lines as context. The
    numbers are how the answer is split back apart: a reply that does not carry
    every number is retried one segment at a time rather than trusted, because
    a shifted line would pair every later line with the wrong English.
    """

    def __init__(self, model: str, src_lang: str = "fr", *,
                 host: str = "http://localhost:11434", batch: int = 12,
                 context: str = "", timeout: int = 300):
        self.model_name = model
        self.src_lang = src_lang
        self.host = host.rstrip("/")
        self.batch = batch
        self.context = context
        self.timeout = timeout
        self.failures = 0           # units given up on; see _one

    def _ask(self, numbered: str) -> str:
        import requests

        prompt = (
            f"Translate these numbered lines of a historical {self.src_lang} poem into "
            "plain, literal English. The spelling is unmodernised and the text "
            "may contain OCR noise; read through it for the sense. "
            + (self.context + " " if self.context else "")
            + "Keep every number and give exactly one English line per "
            "numbered line, in the form '<number>. <English>'. Output only the "
            "translation.\n\n" + numbered)
        resp = requests.post(
            f"{self.host}/api/chat",
            json={"model": self.model_name, "stream": False, "think": False,
                  "messages": [{"role": "user", "content": prompt}],
                  # A cap on the reply: damaged Greek has sent the model into a loop
                  # that ran until the HTTP timeout and took the whole book with it.
                  "options": {"temperature": 0.2,
                              "num_predict": min(2500, 400 + len(numbered) // 2)}},
            timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    @staticmethod
    def _parse(reply: str, n: int) -> list[str] | None:
        import re

        got: dict[int, str] = {}
        for line in reply.splitlines():
            m = re.match(r"\s*(\d+)[.)]\s*(.*)$", line)
            if m:
                got[int(m.group(1))] = m.group(2).strip()
        if n == 1 and got:
            # One unit asked for: a model that renders a long unit as several
            # sentences numbers each of them. They are all the one answer.
            return [" ".join(got[k] for k in sorted(got) if got[k])]
        if set(got) != set(range(1, n + 1)):
            return None
        return [got[i] for i in range(1, n + 1)]

    def _numbered(self, lines: list[str]) -> list[str] | None:
        """Ask for `lines` as one numbered list; None if the answer is short."""
        import requests

        numbered = "\n".join(f"{i}. {ln}" for i, ln in enumerate(lines, 1))
        try:
            return self._parse(self._ask(numbered), len(lines))
        except requests.RequestException:
            return None             # a timeout is retried like a misnumbered reply

    def _one(self, text: str) -> str:
        """One segment on its own, for when a batch came back misnumbered."""
        parts = [ln for ln in text.splitlines() if ln.strip()]
        for _ in range(2):
            out = self._numbered(parts)
            if out is not None:
                return "\n".join(out)
        # Two tries and still no usable reply. One unit the model cannot read is
        # not worth a whole book (it ended a 400-line build once), so it is marked
        # as untranslated and counted, and the rest goes on.
        import sys

        self.failures += 1
        print(f"  ! {self.model_name} gave no usable translation for: {parts[0][:50]!r}",
              file=sys.stderr)
        return "\n".join(["[not translated]"] * len(parts))

    def __call__(self, texts: list[str]) -> list[str]:
        results: list[str] = [""] * len(texts)
        todo = [i for i, t in enumerate(texts) if t.strip()]
        for at in range(0, len(todo), self.batch):
            idx = todo[at:at + self.batch]
            # A multi-line segment cannot share a numbered list one-to-one, so
            # a batch containing one goes segment by segment.
            out = None
            if all("\n" not in texts[i].strip() for i in idx):
                out = self._numbered([texts[i].strip() for i in idx])
            if out is None:
                out = [self._one(texts[i]) for i in idx]
            for i, t in zip(idx, out):
                results[i] = t
        return results


def configure_from(mapping: dict) -> None:
    """Register translators from a config mapping. Each entry is either a
    served endpoint or a model run locally:

        {"la":  {"url": "http://localhost:8001/translate"},
         "de":  {"model": "Helsinki-NLP/opus-mt-de-en"},
         "fr":  "local",
         "fr":  {"ollama": "qwen3:14b"}}

    A bare string is a URL if it looks like one, "local" for this language's
    built-in model, and otherwise a model name.
    """
    for lang, cfg in (mapping or {}).items():
        if isinstance(cfg, str):
            if cfg.startswith(("http://", "https://")):
                cfg = {"url": cfg}
            elif cfg.lower() == "local":
                cfg = {"model": None}
            else:
                cfg = {"model": cfg}
        common = {"batch": int(cfg.get("batch", 16))}
        if cfg.get("url"):
            register(lang, HTTPTranslator(
                cfg["url"], src_lang=_norm(lang),
                batch=int(cfg.get("batch", 32)),
                timeout=int(cfg.get("timeout", 120)),
                headers=cfg.get("headers"),
            ))
        elif cfg.get("ollama"):
            register(lang, OllamaTranslator(
                cfg["ollama"], src_lang=_norm(lang),
                host=cfg.get("host", "http://localhost:11434"),
                batch=int(cfg.get("batch", 12)),
                context=cfg.get("context", "")))
        elif "model" in cfg:
            use_local(lang, cfg["model"], device=cfg.get("device"), **common)
        else:
            raise ValueError(
                f"Translator for {lang!r} names no 'url', 'ollama' model or 'model'.")
