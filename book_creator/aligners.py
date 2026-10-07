"""Backend selection for sentence alignment.

methods:
  "gale-church" — length-based, zero extra dependencies (always available)
  "embed"       — LaBSE cross-lingual embeddings; needs sentence-transformers
  "mt"          — MT-pivot: translate source->English, align in English; needs a
                  translator registered for the source language (see translators)
  "auto"        — best available: MT-pivot if a translator is registered for the
                  language, else embeddings, else Gale-Church

`band`, when given, restricts every backend's DP to that many positions either
side of the diagonal (see align.run_dp). Needed for sequences long enough that
O(n·m) stops being free -- stanza alignment across a whole epic -- and not for
sentences inside one chapter, where it is left off.
"""

from __future__ import annotations

from . import translators
from .align import gale_church
from .model import Bead

# Set once per run so we only emit the "using embeddings" / fallback note once.
_announced = False


def align(src: list[str], tgt: list[str], *, method: str = "auto",
          src_lang: str | None = None, log=None,
          band: int | None = None) -> list[Bead]:
    global _announced

    def note(msg: str) -> None:
        global _announced
        if log and not _announced:
            log(msg)
        _announced = True

    # MT-pivot: requires a translator registered for this source language.
    if method in ("mt", "auto"):
        translator = translators.get(src_lang)
        if translator is not None:
            note("• Aligner: MT-pivot (translate source → align in English)")
            from .align_mt import mt_align
            return mt_align(src, tgt, translator=translator, log=log, band=band)
        if method == "mt":
            # Latin and Greek have a fine-tuned model in the sibling latin repo;
            # asking for the MT aligner by name is enough to use it.
            from . import latin_translator
            if src_lang in latin_translator.MODELS and latin_translator.available()[0]:
                translator = latin_translator.register(src_lang)
                note(f"• Aligner: MT-pivot with the latin repo's {translator.model_name}")
                from .align_mt import mt_align
                return mt_align(src, tgt, translator=translator, log=log, band=band)
            raise RuntimeError(
                f"No translator registered for source language {src_lang!r}. "
                "Register one via translators.register() (see book_creator/translators.py)."
            )

    if method in ("embed", "auto"):
        try:
            from .align_embed import embed_align, ensure_available
            ensure_available()
            note("• Aligner: LaBSE embeddings (meaning-based)")
            return embed_align(src, tgt, band=band)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on auto
            if method == "embed":
                raise
            note(f"• Aligner: Gale-Church (embeddings unavailable: {exc.__class__.__name__})")

    note("• Aligner: Gale-Church (length-based)")
    return gale_church(src, tgt, band=band)


def reset_announcement() -> None:
    """Call at the start of each book so the backend note prints once per book."""
    global _announced
    _announced = False
