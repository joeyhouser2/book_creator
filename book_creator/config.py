"""Load book specifications from a YAML file."""

from __future__ import annotations

from pathlib import Path

import yaml

from . import restylers, translators
from .model import (AudioSpec, BookSpec, CopyrightSpec, CorpusSpec, CoverSpec,
                    DecorSpec, FontSpec, MusicSpec, PerseusSpec)


def _parse_cover(raw) -> CoverSpec:
    if raw is None or raw is False:
        return CoverSpec(enabled=False)
    if raw is True:
        return CoverSpec(enabled=True)
    return CoverSpec(
        enabled=bool(raw.get("enabled", True)),
        style=raw.get("style", "ornament"),
        paper=raw.get("paper", "white"),
        background=raw.get("background", "#f4ead5"),
        accent=raw.get("accent"),
        blurb=raw.get("blurb", ""),
    )


def _parse_copyright(raw) -> CopyrightSpec:
    if raw is None:
        return CopyrightSpec()
    if raw is False:
        return CopyrightSpec(enabled=False)
    return CopyrightSpec(
        enabled=bool(raw.get("enabled", True)),
        publisher=raw.get("publisher", ""),
        holder=raw.get("holder", ""),
        year=raw.get("year"),
        isbn=str(raw.get("isbn", "")),
        translator=raw.get("translator", ""),
        rights=raw.get("rights"),
    )


def _parse_range(raw) -> tuple[int, int] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = [int(p) for p in raw.replace(":", "-").split("-") if p.strip()]
        return (parts[0], parts[0]) if len(parts) == 1 else (parts[0], parts[1])
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (int(raw[0]), int(raw[1]))
    return None


def _parse_font(raw) -> FontSpec:
    if raw is None:
        return FontSpec()
    if isinstance(raw, str):  # shorthand: just a family name
        return FontSpec(family=raw)
    return FontSpec(
        family=raw.get("family", "Cardo"),
        regular=raw.get("regular"),
        italic=raw.get("italic"),
        bold=raw.get("bold"),
    )


def _parse_decor(raw) -> DecorSpec:
    if raw is None:
        return DecorSpec()
    return DecorSpec(
        margin=raw.get("margin", "none"),
        chapter=raw.get("chapter", "fleuron"),
        bead_separator=raw.get("bead_separator", "none"),
        color=raw.get("color", "#8a7a5c"),
        corner_image=raw.get("corner_image"),
        chapter_image=raw.get("chapter_image"),
        opener_font=raw.get("opener_font"),
    )


def _parse_music(raw) -> MusicSpec:
    if raw is None or raw is False:
        return MusicSpec(enabled=False)
    if raw is True:
        return MusicSpec(enabled=True)
    return MusicSpec(
        enabled=bool(raw.get("enabled", True)),
        catalog=raw.get("catalog", "dichterliebe"),
    )


def _parse_corpus(raw) -> CorpusSpec:
    """`corpus:` block, or the shorthand `corpus: 376` (just a document id)."""
    if raw is None or raw is False:
        return CorpusSpec()
    if isinstance(raw, int):
        return CorpusSpec(doc_id=raw)
    return CorpusSpec(
        doc_id=raw.get("doc_id") or raw.get("id"),
        db_path=raw.get("db_path") or raw.get("db"),
        section_range=_parse_range(raw.get("section_range") or raw.get("range")),
        prefer_styled=bool(raw.get("prefer_styled", True)),
        skip_untranslated=bool(raw.get("skip_untranslated", True)),
        strip_markup=bool(raw.get("strip_markup", True)),
    )


def _parse_perseus(raw) -> PerseusSpec:
    """`perseus:` block, or the shorthand `perseus: greekLit:tlg0032.tlg006`."""
    if raw is None or raw is False:
        return PerseusSpec()
    if isinstance(raw, str):
        return PerseusSpec(work_id=raw)
    return PerseusSpec(
        work_id=raw.get("work_id") or raw.get("id"),
        division_range=_parse_range(raw.get("division_range") or raw.get("range")),
    )


def _parse_audio(raw) -> AudioSpec:
    if raw is None or raw is False:
        return AudioSpec(enabled=False)
    if raw is True:
        return AudioSpec(enabled=True)
    return AudioSpec(
        enabled=bool(raw.get("enabled", True)),
        engine=raw.get("engine", "chatterbox"),
        device=raw.get("device", "cuda:0"),
        src_voice=raw.get("src_voice") or raw.get("voice"),
        tgt_voice=raw.get("tgt_voice") or raw.get("voice"),
        pause_within=float(raw.get("pause_within", 0.45)),
        pause_bead=float(raw.get("pause_bead", 0.9)),
        pause_chapter=float(raw.get("pause_chapter", 1.5)),
        announce_chapters=bool(raw.get("announce_chapters", True)),
        format=raw.get("format", "m4b"),
        max_beads=raw.get("max_beads"),
    )


def load_specs(path: str) -> list[BookSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # Optional top-level translators block registers MT-pivot endpoints.
        if data.get("translators"):
            translators.configure_from(data["translators"])
        # Optional top-level restylers block registers post-alignment prose
        # restylers (e.g. a "victorianizer"), keyed by tgt_lang.
        if data.get("restylers"):
            restylers.configure_from(data["restylers"])
        if "books" in data:
            data = data["books"]
    if not isinstance(data, list):
        raise ValueError("Config must be a list of books, or a mapping with a 'books' list.")

    specs = []
    for raw in data:
        trim = raw.get("trim", [6.0, 9.0])
        corpus = _parse_corpus(raw.get("corpus"))
        # A corpus entry carries its own title and language, so those fields
        # are optional there and get filled in from the document at build time.
        specs.append(BookSpec(
            title=(raw.get("title", "") if (corpus.doc_id or raw.get("perseus"))
                   else raw["title"]),
            author=raw.get("author", "Unknown"),
            src_lang=(raw.get("src_lang", "") if (corpus.doc_id or raw.get("perseus"))
                      else raw["src_lang"]),
            tgt_lang=raw.get("tgt_lang", "en"),
            corpus=corpus,
            perseus=_parse_perseus(raw.get("perseus")),
            src_gutenberg_id=raw.get("src_gutenberg_id"),
            tgt_gutenberg_id=raw.get("tgt_gutenberg_id"),
            src_path=raw.get("src_path"),
            tgt_path=raw.get("tgt_path"),
            mode=raw.get("mode", "prose"),
            poem_titles=bool(raw.get("poem_titles", False)),
            aligner=raw.get("aligner", "auto"),
            clean=bool(raw.get("clean", True)),
            restyle=bool(raw.get("restyle", True)),
            toc=bool(raw.get("toc", True)),
            src_range=_parse_range(raw.get("src_range")),
            tgt_range=_parse_range(raw.get("tgt_range")),
            trim=(float(trim[0]), float(trim[1])),
            first=raw.get("first", "src"),
            sides=raw.get("sides", "both"),
            translation_pd_confirmed=bool(raw.get("translation_pd_confirmed", False)),
            translation_source_note=raw.get("translation_source_note", ""),
            slug=raw.get("slug"),
            font=_parse_font(raw.get("font")),
            decor=_parse_decor(raw.get("decorations")),
            copyright=_parse_copyright(raw.get("copyright")),
            cover=_parse_cover(raw.get("cover")),
            epub=bool(raw.get("epub", False)),
            audio_only=bool(raw.get("audio_only", False)),
            review=bool(raw.get("review", False)),
            review_model=raw.get("review_model", "llama3.1"),
            review_host=raw.get("review_host", "http://localhost:11434"),
            review_sample=raw.get("review_sample"),
            music=_parse_music(raw.get("music")),
            audio=_parse_audio(raw.get("audio")),
        ))
    return specs
