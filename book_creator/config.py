"""Load book specifications from a YAML file."""

from __future__ import annotations

from pathlib import Path

import yaml

from .model import BookSpec, DecorSpec, FontSpec


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
    )


def load_specs(path: str) -> list[BookSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "books" in data:
        data = data["books"]
    if not isinstance(data, list):
        raise ValueError("Config must be a list of books, or a mapping with a 'books' list.")

    specs = []
    for raw in data:
        trim = raw.get("trim", [6.0, 9.0])
        specs.append(BookSpec(
            title=raw["title"],
            author=raw.get("author", "Unknown"),
            src_lang=raw["src_lang"],
            tgt_lang=raw.get("tgt_lang", "en"),
            src_gutenberg_id=raw.get("src_gutenberg_id"),
            tgt_gutenberg_id=raw.get("tgt_gutenberg_id"),
            src_path=raw.get("src_path"),
            tgt_path=raw.get("tgt_path"),
            mode=raw.get("mode", "prose"),
            aligner=raw.get("aligner", "auto"),
            src_range=_parse_range(raw.get("src_range")),
            tgt_range=_parse_range(raw.get("tgt_range")),
            trim=(float(trim[0]), float(trim[1])),
            first=raw.get("first", "src"),
            translation_pd_confirmed=bool(raw.get("translation_pd_confirmed", False)),
            translation_source_note=raw.get("translation_source_note", ""),
            slug=raw.get("slug"),
            font=_parse_font(raw.get("font")),
            decor=_parse_decor(raw.get("decorations")),
        ))
    return specs
