"""Pluggable English-to-Victorian-English restylers, registered per target language.

This is the *interface* your victorianizer model plugs into. Unlike translators
(book_creator/translators.py), which feed the aligner, a restyler runs *after*
alignment on the real translation text that ends up printed in the book — it
never affects sentence matching, only the final prose.

A restyler is any callable:  restyle(texts: list[str]) -> list[str]
returning one restyled string per input, in the same order. Register one per
target language (almost always "en"):

    from book_creator import restylers
    restylers.register("en", my_victorianizer)

Two adapters are provided: HTTPRestyler (your model served on a URL) and
CallableRestyler (a plain Python function). Until a restyler is registered for
a language, restyling is skipped and the translation prints as fetched.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class Restyler(Protocol):
    def __call__(self, texts: list[str]) -> list[str]: ...


_REGISTRY: dict[str, Restyler] = {}


def _norm(lang: str | None) -> str:
    return (lang or "").lower()


def register(lang: str, restyler: Restyler) -> None:
    _REGISTRY[_norm(lang)] = restyler


def get(lang: str | None) -> Restyler | None:
    return _REGISTRY.get(_norm(lang))


def available(lang: str | None) -> bool:
    return get(lang) is not None


def clear() -> None:
    _REGISTRY.clear()


class CallableRestyler:
    """Wrap any function `fn(texts) -> restyled_texts`."""

    def __init__(self, fn: Callable[[list[str]], list[str]]):
        self._fn = fn

    def __call__(self, texts: list[str]) -> list[str]:
        return list(self._fn(texts))


class HTTPRestyler:
    """Call a restyling service over HTTP.

    Contract — your model's repo serves an endpoint that accepts:
        POST <url>   {"lang": "en", "texts": ["...", "..."]}
    and returns:
        200          {"texts": ["...", "..."]}   (same length & order)

    Requests are batched; restyled text is concatenated back in order.
    """

    def __init__(self, url: str, lang: str = "en", *, batch: int = 32,
                 timeout: int = 120, headers: dict | None = None):
        self.url = url
        self.lang = lang
        self.batch = batch
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def __call__(self, texts: list[str]) -> list[str]:
        import requests

        out: list[str] = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i:i + self.batch]
            resp = requests.post(
                self.url, json={"lang": self.lang, "texts": chunk},
                headers=self.headers, timeout=self.timeout,
            )
            resp.raise_for_status()
            restyled = resp.json()["texts"]
            if len(restyled) != len(chunk):
                raise ValueError(
                    f"restyler returned {len(restyled)} items for "
                    f"{len(chunk)} inputs"
                )
            out.extend(restyled)
        return out


def configure_from(mapping: dict) -> None:
    """Register HTTP restylers from a config mapping, e.g.

        {"en": {"url": "http://localhost:8003/restyle"}}
    """
    for lang, cfg in (mapping or {}).items():
        if isinstance(cfg, str):
            cfg = {"url": cfg}
        url = cfg.get("url")
        if url:
            register(lang, HTTPRestyler(
                url, lang=_norm(lang),
                batch=int(cfg.get("batch", 32)),
                timeout=int(cfg.get("timeout", 120)),
                headers=cfg.get("headers"),
            ))
