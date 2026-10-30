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
        spine_logo=raw.get("spine_logo", "auto"),
        emblem=raw.get("emblem"),
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
        source=raw.get("source", ""),
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
        original=raw.get("original"),
    )


def _parse_stanza_pairs(raw):
    """A list of pairs for every division, or a dict of lists by division
    number, or the path of a JSON file holding either (a long poem's pairing
    is generated, not typed -- see fetch_sources.nibelungen)."""
    if isinstance(raw, str):
        import json
        raw = json.loads(Path(raw).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return {str(k): list(v) for k, v in raw.items()}
    return list(raw or [])


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
        chapter_images=raw.get("chapter_images"),
        chapter_images_width=float(raw.get("chapter_images_width", 0.5)),
        chapter_images_color=bool(raw.get("chapter_images_color", False)),
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
        check=str(raw.get("check", "signal")).lower(),
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
            verse_align=raw.get("verse_align", "block"),
            translate=bool(raw.get("translate", False)),
            translate_by=raw.get("translate_by", "line"),
            fill_missing=bool(raw.get("fill_missing", False)),
            translation_gaps=list(raw.get("translation_gaps") or []),
            stanza_pairs=_parse_stanza_pairs(raw.get("stanza_pairs")),
            align_block=int(raw.get("align_block", 0)),
            fill_below=float(raw.get("fill_below", 0.0)),
            poem_titles=bool(raw.get("poem_titles", False)),
            aligner=raw.get("aligner", "auto"),
            clean=bool(raw.get("clean", True)),
            restyle=bool(raw.get("restyle", True)),
            toc=bool(raw.get("toc", True)),
            src_range=_parse_range(raw.get("src_range")),
            tgt_range=_parse_range(raw.get("tgt_range")),
            trim=(float(trim[0]), float(trim[1])),
            first=raw.get("first", "src"),
            density=raw.get("density", "normal"),
            tgt_replace={str(k): str(v) for k, v in
                         (raw.get("tgt_replace") or {}).items()},
            sides=raw.get("sides", "both"),
            translation_pd_confirmed=bool(raw.get("translation_pd_confirmed", False)),
            translation_source_note=raw.get("translation_source_note", ""),
            slug=raw.get("slug"),
            font=_parse_font(raw.get("font")),
            decor=_parse_decor(raw.get("decorations")),
            copyright=_parse_copyright(raw.get("copyright")),
            split_long_divisions=int(raw.get("split_long_divisions", 0) or 0),
            cover=_parse_cover(raw.get("cover")),
            epub=bool(raw.get("epub", False)),
            audio_only=bool(raw.get("audio_only", False)),
            review=bool(raw.get("review", False)),
            review_model=raw.get("review_model", "llama3.1"),
            review_host=raw.get("review_host", "http://localhost:11434"),
            review_sample=raw.get("review_sample"),
            proofread=bool(raw.get("proofread", False)),
            proofread_model=raw.get("proofread_model", "Unbabel/TowerInstruct-7B-v0.2"),
            proofread_sample=raw.get("proofread_sample"),
            recut=bool(raw.get("recut", False)),
            recut_model=raw.get("recut_model", "Unbabel/TowerInstruct-7B-v0.2"),
            recut_lambda=float(raw.get("recut_lambda", 1.0)),
            recut_device=raw.get("recut_device", "auto"),
            music=_parse_music(raw.get("music")),
            audio=_parse_audio(raw.get("audio")),
        ))
    return specs
