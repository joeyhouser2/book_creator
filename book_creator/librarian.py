"""Natural-language book discovery agent.

Given a request like "Dante's Inferno, Italian original with an English
translation", this asks a locally-run LLM (via Ollama's tool-calling API) to
search the Project Gutenberg catalog (through Gutendex — see fetch.py), read
enough of each candidate edition to judge language/scope/fit, and propose a
BookSpec-ready pairing: source + translation Gutenberg ids, optional ranges
to scope mismatched editions, and a translator/edition note.

Deliberately scoped to Gutenberg only (no open web crawling): it matches the
project's existing copyright approach (fetch.py + BookSpec.translation_pd_
confirmed) and keeps every source auditable back to a Gutenberg id. The
agent NEVER sets translation_pd_confirmed=True itself — that stays a human
decision (see model.CopyrightSpec: translators hold their own copyright
separate from the PD original). It surfaces what it found in
translation_source_note so you have something concrete to verify.

Usage
-----
    ollama pull llama3.1        # any tool-calling-capable model
    ollama serve

    from book_creator.librarian import find_book
    spec = find_book("Dante's Inferno, Italian with an English translation")
    # inspect spec, verify the translation's PD status yourself, then:
    spec.translation_pd_confirmed = True
    from book_creator.pipeline import build_book
    build_book(spec)

Or from the command line: `python ask_librarian.py "..."`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from . import fetch, segment
from .model import BookSpec
from .ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaError, chat as _ollama_chat_raw

LibrarianError = OllamaError

_SYSTEM_PROMPT = """\
You are a research librarian helping assemble a dual-language parallel-text \
book from Project Gutenberg. Given a request naming a work (and usually an \
original language), find:

  1. SOURCE: an edition of the work in its original language.
  2. TRANSLATION: an edition of the SAME work translated into the target \
language (English unless the user says otherwise).

Use search_gutenberg to find candidates (search title/author, filter by \
language code: la, grc/el, fr, de, it, es, etc. — English is "en"). Use \
inspect_edition on promising ids to confirm it's really the right work, in \
the right language, and to see its division outline (chapters/books/cantos) \
before deciding.

Gutendex's search is close to a literal substring match on title/author, NOT \
semantic, and the ENGLISH edition of a foreign work is very often catalogued \
under its ORIGINAL-language title (e.g. Caesar's Gallic War appears in the \
English catalog as '"De Bello Gallico" and Other Commentaries', not \
"Gallic War"). If a specific-phrase query returns zero results, don't \
refine it further — immediately broaden to just the author's surname \
(e.g. "Caesar") and inspect the candidates by hand. Zero results does NOT \
mean no translation exists on Gutenberg; it usually means the query was too \
narrow or guessed the wrong title wording.

Rules:
- Only use Gutenberg ids that came back from search_gutenberg. Never invent one.
- Source and translation must be the SAME underlying work. Don't pair, e.g., \
one poet's "Sonnets" with another author's.
- If the two editions' outlines cover different scope (e.g. the source is \
just "Book I" of a work but the translation covers the whole thing), set \
src_range/tgt_range ([first, last], 1-based, from the outline indices) so \
both sides cover the same content. Leave ranges unset if scope already matches.
- For the translator field, use inspect_edition's `catalog_translators` value \
VERBATIM — it's real Gutendex catalog metadata, not a guess. Never invent a \
translator name. If `catalog_translators` is empty, leave the translator \
field empty rather than making one up.
- You cannot verify a translation's copyright status yourself (Gutendex has \
no reliable translation-publication date, and you don't reliably know when a \
named translator died). Do NOT claim or imply the translation is public \
domain, and do NOT invent a publication date or death date to argue it is. \
Put only what inspect_edition actually gave you (the real translator name, \
if any) into translation_source_note, phrased as unverified, e.g. "Translator: \
<name>, per Gutendex catalog — public-domain status not verified."
- mode is "verse" for poetry (line-by-line), "prose" otherwise.
- When you have a final answer, call propose_book_spec exactly once with your \
best pairing. Do not call it speculatively before you've inspected candidates.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_gutenberg",
            "description": "Search the Project Gutenberg catalog by title/author keywords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Title/author keywords."},
                    "language": {
                        "type": "string",
                        "description": "ISO language code to filter by, e.g. 'la', 'it', 'en'. Omit to search all languages.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_edition",
            "description": (
                "Fetch a Gutenberg edition by id and return its length, a text "
                "preview (to confirm language/content), and its structural "
                "division outline (for scoping src_range/tgt_range)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gutenberg_id": {"type": "integer", "description": "Gutenberg ebook id."},
                },
                "required": ["gutenberg_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_book_spec",
            "description": "Return the final source+translation pairing. Call exactly once, when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "src_lang": {"type": "string", "description": "Original language code, e.g. 'la', 'it', 'grc'."},
                    "tgt_lang": {"type": "string", "description": "Translation language code, default 'en'."},
                    "src_gutenberg_id": {"type": "integer"},
                    "tgt_gutenberg_id": {"type": "integer"},
                    "mode": {"type": "string", "enum": ["prose", "verse"]},
                    "src_range": {
                        "type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
                        "description": "[first, last] 1-based division indices, or omit for the whole text.",
                    },
                    "tgt_range": {
                        "type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
                    },
                    "translator": {"type": "string", "description": "Translator name, if identifiable."},
                    "translation_source_note": {
                        "type": "string",
                        "description": "Evidence toward the translation's PD status, for human verification.",
                    },
                    "confidence_notes": {
                        "type": "string",
                        "description": "Any caveats/uncertainty about this pairing.",
                    },
                },
                "required": ["title", "author", "src_lang", "src_gutenberg_id", "tgt_gutenberg_id"],
            },
        },
    },
]


@dataclass
class LibrarianResult:
    """What the agent found, before you turn it into a BookSpec."""

    spec: BookSpec
    translator: str = ""
    confidence_notes: str = ""
    transcript: list[dict] = field(default_factory=list)


def _ollama_chat(host: str, model: str, messages: list[dict]) -> dict:
    return _ollama_chat_raw(host, model, messages, tools=_TOOLS)


def _run_tool(name: str, args: dict) -> dict:
    if name == "search_gutenberg":
        return fetch.search_gutenberg(args["query"], language=args.get("language"))
    if name == "inspect_edition":
        gid = int(args["gutenberg_id"])
        text = fetch.fetch_gutenberg(gid)
        divisions = segment.outline(text)
        try:
            meta = fetch.gutenberg_metadata(gid)
        except Exception:
            meta = {}
        return {
            "gutenberg_id": gid,
            "catalog_title": meta.get("title", ""),
            "catalog_authors": meta.get("authors", ""),
            # Real translator name from Gutendex's catalog metadata, if any —
            # use this verbatim for translator/translation_source_note. Don't
            # guess a translator name; if this is empty, say so rather than
            # inventing one.
            "catalog_translators": meta.get("translators", ""),
            "char_count": len(text),
            "preview": text[:800],
            "division_count": len(divisions),
            # Cap so a huge multi-volume outline doesn't blow the context window.
            "divisions": divisions[:40],
        }
    raise LibrarianError(f"Unknown tool call: {name}")


def _distinctive_token(author: str) -> str | None:
    """The surname from an author name, lowercased — a cheap grounding check.

    E.g. "Julius Caesar" -> "caesar", "Victor Hugo" -> "hugo". Used to sanity-
    check that a proposed Gutenberg id's actual text plausibly is the claimed
    author's work, not just an id the model liked the look of. Prefers the
    LAST word over the longest: surnames tend to survive transliteration
    across languages/inflection better than given names (a Latin edition
    spells the author "C. Iulii Caesaris" — no exact "Julius" substring, but
    "Caesaris" still contains "caesar"). Returns None if there's no usable
    word (so the check is skipped rather than false-rejecting).
    """
    words = re.findall(r"[A-Za-z]{4,}", author or "")
    if not words:
        return None
    return words[-1].lower()


def _parse_range(raw) -> tuple[int, int] | None:
    if not raw:
        return None
    if len(raw) != 2:
        return None
    return (int(raw[0]), int(raw[1]))


def find_book(
    request: str,
    *,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    max_turns: int = 16,
    log: Callable[[str], None] = print,
) -> LibrarianResult:
    """Ask the local LLM to find and pair a source+translation edition.

    Returns a LibrarianResult wrapping a BookSpec with translation_pd_confirmed
    left False — you must verify the translation's PD status and flip it
    yourself before build_book stops warning (or publish it).
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]
    transcript: list[dict] = list(messages)
    # Ids the model has actually looked up this run (via search_gutenberg
    # results or inspect_edition calls) — propose_book_spec is rejected if it
    # names an id outside this set, since small models occasionally invent a
    # plausible-looking pairing instead of grounding it in a real lookup.
    seen_ids: set[int] = set()

    for turn in range(max_turns):
        data = _ollama_chat(host, model, messages)
        message = data.get("message", {})
        tool_calls = message.get("tool_calls") or []
        messages.append(message)
        transcript.append(message)

        if not tool_calls:
            content = (message.get("content") or "").strip()
            log(f"  (librarian, no tool call) {content[:300]}")
            messages.append({
                "role": "user",
                "content": (
                    "Continue by calling a tool (search_gutenberg / inspect_edition), "
                    "or call propose_book_spec if you have your final answer."
                ),
            })
            continue

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args)

            if name == "propose_book_spec":
                def _reject(reason: str) -> dict:
                    log(f"  ✗ propose_book_spec rejected: {reason}")
                    return {"role": "tool", "content": json.dumps({"error": f"Rejected: {reason}"})}

                missing = [f for f in ("title", "author", "src_lang", "src_gutenberg_id",
                                       "tgt_gutenberg_id") if not args.get(f)]
                if missing:
                    tool_msg = _reject(f"missing required field(s): {', '.join(missing)}.")
                    messages.append(tool_msg)
                    transcript.append(tool_msg)
                    continue

                try:
                    src_id = int(args["src_gutenberg_id"])
                    tgt_id = int(args["tgt_gutenberg_id"])
                except (TypeError, ValueError):
                    tool_msg = _reject("src_gutenberg_id/tgt_gutenberg_id must be integers.")
                    messages.append(tool_msg)
                    transcript.append(tool_msg)
                    continue

                unverified = [i for i in (src_id, tgt_id) if i not in seen_ids]
                if unverified:
                    tool_msg = _reject(
                        f"gutenberg id(s) {unverified} were never returned by search_gutenberg "
                        "or passed to inspect_edition in this conversation. Only propose ids "
                        "you have actually looked up — search and/or inspect them first."
                    )
                    messages.append(tool_msg)
                    transcript.append(tool_msg)
                    continue

                # Id-provenance alone isn't enough — a model can call inspect_edition on the
                # right id, get back content that plainly isn't the requested work, and still
                # propose it anyway (observed in testing). Cross-check the fetched text itself:
                # the author's name should actually appear near the start of both editions.
                token = _distinctive_token(args.get("author", ""))
                if token:
                    try:
                        src_text = fetch.fetch_gutenberg(src_id)
                        tgt_text = fetch.fetch_gutenberg(tgt_id)
                    except Exception:
                        src_text = tgt_text = ""
                    missing_side = [
                        side for side, text in (("source", src_text), ("translation", tgt_text))
                        if token not in text[:4000].lower()
                    ]
                    if missing_side:
                        tool_msg = _reject(
                            f"author name '{token}' doesn't appear near the start of the "
                            f"{' and '.join(missing_side)} text for ids {src_id}/{tgt_id} — "
                            "these ids likely aren't actually this work. Re-check with "
                            "inspect_edition and reconsider, or search again."
                        )
                        messages.append(tool_msg)
                        transcript.append(tool_msg)
                        continue

                log(f"• Librarian proposes: {args.get('title')} — "
                    f"src #{args.get('src_gutenberg_id')} / tgt #{args.get('tgt_gutenberg_id')}")
                spec = BookSpec(
                    title=args["title"],
                    author=args.get("author", "Unknown"),
                    src_lang=args["src_lang"],
                    tgt_lang=args.get("tgt_lang") or "en",
                    src_gutenberg_id=int(args["src_gutenberg_id"]),
                    tgt_gutenberg_id=int(args["tgt_gutenberg_id"]),
                    mode=args.get("mode") or "prose",
                    src_range=_parse_range(args.get("src_range")),
                    tgt_range=_parse_range(args.get("tgt_range")),
                    translation_pd_confirmed=False,
                    translation_source_note=args.get("translation_source_note", ""),
                )
                if args.get("translator"):
                    spec.copyright.translator = args["translator"]
                return LibrarianResult(
                    spec=spec,
                    translator=args.get("translator", ""),
                    confidence_notes=args.get("confidence_notes", ""),
                    transcript=transcript,
                )

            log(f"  → {name}({args})")
            try:
                result = _run_tool(name, args)
            except Exception as exc:  # noqa: BLE001 - surface to the model, keep going
                result = {"error": str(exc)}
                log(f"    ✗ {exc}")
            else:
                if name == "search_gutenberg":
                    seen_ids.update(r["id"] for r in result.get("results", []) if "id" in r)
                elif name == "inspect_edition" and "error" not in result:
                    seen_ids.add(result["gutenberg_id"])
            tool_msg = {"role": "tool", "content": json.dumps(result)}
            messages.append(tool_msg)
            transcript.append(tool_msg)

    raise LibrarianError(
        f"Librarian didn't reach a final answer in {max_turns} turns. "
        "Try a more specific request, or raise max_turns."
    )
