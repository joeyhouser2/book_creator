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

Two adapters are provided: HTTPTranslator (your model served on a URL) and
CallableTranslator (a plain Python function). Until a translator is registered
for a language, the MT aligner is unavailable for it and `auto` falls back to
the embedding / Gale-Church backends.
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
    """Register HTTP translators from a config mapping, e.g.

        {"la": {"url": "http://localhost:8001/translate"},
         "grc": {"url": "http://localhost:8002/translate"}}
    """
    for lang, cfg in (mapping or {}).items():
        if isinstance(cfg, str):
            cfg = {"url": cfg}
        url = cfg.get("url")
        if url:
            register(lang, HTTPTranslator(
                url, src_lang=_norm(lang),
                batch=int(cfg.get("batch", 32)),
                timeout=int(cfg.get("timeout", 120)),
                headers=cfg.get("headers"),
            ))
