"""Backend selection for sentence alignment.

methods:
  "gale-church" — length-based, zero extra dependencies (always available)
  "embed"       — LaBSE embeddings; errors if sentence-transformers is missing
  "auto"        — use embeddings when available, else fall back to Gale-Church
"""

from __future__ import annotations

from .align import gale_church
from .model import Bead

# Set once per run so we only emit the "using embeddings" / fallback note once.
_announced = False


def align(src: list[str], tgt: list[str], *, method: str = "auto", log=None) -> list[Bead]:
    global _announced

    def note(msg: str) -> None:
        global _announced
        if log and not _announced:
            log(msg)
        _announced = True

    if method in ("embed", "auto"):
        try:
            from .align_embed import embed_align, ensure_available
            ensure_available()
            note("• Aligner: LaBSE embeddings (meaning-based)")
            return embed_align(src, tgt)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on auto
            if method == "embed":
                raise
            note(f"• Aligner: Gale-Church (embeddings unavailable: {exc.__class__.__name__})")

    note("• Aligner: Gale-Church (length-based)")
    return gale_church(src, tgt)


def reset_announcement() -> None:
    """Call at the start of each book so the backend note prints once per book."""
    global _announced
    _announced = False
