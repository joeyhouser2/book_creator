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


def configure_from(mapping: dict) -> None:
    """Register translators from a config mapping. Each entry is either a
    served endpoint or a model run locally:

        {"la":  {"url": "http://localhost:8001/translate"},
         "de":  {"model": "Helsinki-NLP/opus-mt-de-en"},
         "fr":  "local"}

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
        elif "model" in cfg:
            use_local(lang, cfg["model"], device=cfg.get("device"), **common)
        else:
            raise ValueError(
                f"Translator for {lang!r} names neither a 'url' nor a 'model'.")
