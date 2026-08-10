"""Post-alignment QA pass: ask a local LLM (via Ollama) to flag beads that
likely have alignment or formatting problems, so you know where to proofread
instead of reading the whole book.

Advisory only. It never edits Bead/Chapter content and never blocks a
build — it just writes a findings report. Runs after alignment (and after
restyle, if any) so what it sees is exactly what gets printed.

Usage (normally driven by BookSpec.review via pipeline.build_book, but
callable directly):

    from book_creator.reviewer import review_chapters, format_report
    findings = review_chapters(chapters, src_lang="fr", tgt_lang="en")
    Path("review.md").write_text(format_report(findings), encoding="utf-8")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .model import Chapter
from .ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaError, chat as _ollama_chat

ReviewerError = OllamaError

_SYSTEM_PROMPT = """\
You are proofreading a dual-language parallel-text book. Each numbered item \
below is one "bead": a source-language segment paired with its translation, \
meant to sit side by side on the printed page. Flag beads with a real problem:

- misalignment: the two sides clearly don't correspond in content/scope — \
not just normal translation looseness, but a whole clause/sentence present \
on one side and absent from the other, or the two sides plainly describing \
different sentences.
- leftover_markup: uncleaned editorial junk that shouldn't be in printed \
body text — a chapter/section number pasted into the sentence (e.g. \
"XLIX.--"), a "[Illustration]" caption, a footnote marker, a running header \
or page number, stray HTML entities.
- encoding_artifact: mojibake, replacement characters (�), or obviously \
broken Unicode.
- segmentation_error: the segment is truncated mid-sentence, or two unrelated \
sentences have been fused into one, in a way that breaks reading.
- other: something else clearly wrong.

Do NOT flag: normal translation looseness, one side being longer because of \
language differences, differing word order, or a bead where one side is \
legitimately empty (that's a marked insertion/deletion, not an error).

Call report_issues once for this batch with only the problem beads — an \
empty list if none are wrong.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "report_issues",
            "description": (
                "Report beads in this batch with alignment or formatting "
                "problems. Call exactly once per batch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref": {
                                    "type": "integer",
                                    "description": "The bead's number as shown in this batch (1-based).",
                                },
                                "issue_type": {
                                    "type": "string",
                                    "enum": ["misalignment", "leftover_markup",
                                             "encoding_artifact", "segmentation_error", "other"],
                                },
                                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                                "note": {"type": "string", "description": "One-sentence explanation."},
                            },
                            "required": ["ref", "issue_type", "severity", "note"],
                        },
                    },
                },
                "required": ["issues"],
            },
        },
    },
]

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Finding:
    chapter_index: int
    chapter_title: str
    bead_index: int
    issue_type: str
    severity: str
    note: str
    src_excerpt: str
    tgt_excerpt: str


def _truncate(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def review_chapters(
    chapters: list[Chapter],
    *,
    src_lang: str,
    tgt_lang: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    batch_size: int = 12,
    max_beads: int | None = None,
    log: Callable[[str], None] = print,
) -> list[Finding]:
    """Scan every bead across `chapters` and return flagged ones.

    max_beads caps how many beads are sent to the model (from the start),
    for a quick spot-check on a long book instead of a full pass.
    """
    flat: list[tuple[int, Chapter, int, object]] = []
    for ci, ch in enumerate(chapters):
        for bi, bead in enumerate(ch.beads):
            flat.append((ci, ch, bi, bead))
    if max_beads is not None:
        flat = flat[:max_beads]
    if not flat:
        return []

    findings: list[Finding] = []
    total_batches = (len(flat) + batch_size - 1) // batch_size
    for batch_no in range(total_batches):
        batch = flat[batch_no * batch_size: (batch_no + 1) * batch_size]
        start = batch_no * batch_size + 1
        log(f"  reviewing beads {start}-{start + len(batch) - 1} of {len(flat)}…")

        lines = []
        for i, (_, _, _, bead) in enumerate(batch, start=1):
            src = _truncate(bead.src_text) or "(empty)"
            tgt = _truncate(bead.tgt_text) or "(empty)"
            lines.append(f"{i}. SRC({src_lang}): {src}\n   TGT({tgt_lang}): {tgt}")
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

        data = _ollama_chat(host, model, messages, tools=_TOOLS)
        message = data.get("message", {})
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            if fn.get("name") != "report_issues":
                continue
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args)
            for issue in args.get("issues", []):
                ref = issue.get("ref")
                if not isinstance(ref, int) or not (1 <= ref <= len(batch)):
                    continue
                ci, ch, bi, bead = batch[ref - 1]
                findings.append(Finding(
                    chapter_index=ci,
                    chapter_title=ch.title or f"Chapter {ci + 1}",
                    bead_index=bi,
                    issue_type=issue.get("issue_type", "other"),
                    severity=issue.get("severity", "medium"),
                    note=issue.get("note", ""),
                    src_excerpt=_truncate(bead.src_text, 160),
                    tgt_excerpt=_truncate(bead.tgt_text, 160),
                ))
    return findings


def format_report(findings: list[Finding]) -> str:
    if not findings:
        return "# Segment review\n\nNo issues flagged.\n"
    lines = [f"# Segment review — {len(findings)} flagged bead(s)\n"]
    for f in sorted(findings, key=lambda f: (
        _SEVERITY_ORDER.get(f.severity, 9), f.chapter_index, f.bead_index)):
        lines.append(f"## [{f.severity.upper()}] {f.chapter_title} — bead {f.bead_index + 1} "
                     f"({f.issue_type})")
        lines.append(f"- {f.note}")
        lines.append(f"- SRC: {f.src_excerpt}")
        lines.append(f"- TGT: {f.tgt_excerpt}")
        lines.append("")
    return "\n".join(lines)
