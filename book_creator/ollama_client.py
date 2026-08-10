"""Minimal client for a local Ollama server's tool-calling chat API.

Shared by librarian.py (book discovery) and reviewer.py (post-alignment QA
pass) — both just need "send messages + a tool schema, get back a message
that may contain tool_calls". No new dependency: uses `requests`, already
required by fetch.py/translators.py.
"""

from __future__ import annotations

import requests

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


class OllamaError(RuntimeError):
    pass


def chat(host: str, model: str, messages: list[dict], tools: list[dict] | None = None,
        timeout: int = 180) -> dict:
    try:
        resp = requests.post(
            f"{host.rstrip('/')}/api/chat",
            json={"model": model, "messages": messages, "tools": tools or [], "stream": False},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OllamaError(
            f"Could not reach Ollama at {host}: {exc}. Is `ollama serve` running?"
        ) from exc
    if resp.status_code == 404:
        raise OllamaError(f"Ollama has no model '{model}' pulled. Run: ollama pull {model}")
    resp.raise_for_status()
    return resp.json()
