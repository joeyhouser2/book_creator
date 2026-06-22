"""Shared data structures for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Bead:
    """One aligned unit: a run of source segments paired with a run of target segments.

    Either side may be empty (an insertion / deletion in the alignment).
    """

    src: list[str] = field(default_factory=list)
    tgt: list[str] = field(default_factory=list)

    @property
    def src_text(self) -> str:
        return " ".join(self.src).strip()

    @property
    def tgt_text(self) -> str:
        return " ".join(self.tgt).strip()


@dataclass
class Chapter:
    """A structural division used as an alignment anchor."""

    title: str
    src_segments: list[str] = field(default_factory=list)
    tgt_segments: list[str] = field(default_factory=list)
    beads: list[Bead] = field(default_factory=list)


@dataclass
class FontSpec:
    """Which font family to embed, and optionally explicit file overrides.

    File names are resolved against the fonts/ directory first, then as given
    (so absolute paths also work).
    """

    family: str = "Cardo"
    regular: str | None = None
    italic: str | None = None
    bold: str | None = None


@dataclass
class DecorSpec:
    """Page and chapter decoration settings."""

    # Per-page margin art: none | rule | corners | frame
    margin: str = "none"
    # Under each chapter title: none | fleuron | rule
    chapter: str = "fleuron"
    # Between aligned beads (section breaks within a chapter): none | fleuron
    bead_separator: str = "none"
    # Ink color for vector ornaments.
    color: str = "#8a7a5c"
    # Optional PNG/JPG placed (mirrored) at the four text-block corners.
    # Overrides the vector "corners" motif when set.
    corner_image: str | None = None
    # Optional PNG/JPG centered under chapter titles (overrides vector chapter art).
    chapter_image: str | None = None


@dataclass
class BookSpec:
    """Definition of one book to build, loaded from YAML."""

    title: str
    author: str
    # Language of the ORIGINAL text (the non-English side): la, fr, grc, de, ...
    src_lang: str
    # Language of the translation. Almost always "en".
    tgt_lang: str = "en"

    # Project Gutenberg ebook IDs (integers from the URL).
    src_gutenberg_id: int | None = None
    tgt_gutenberg_id: int | None = None
    # Or local file paths (override Gutenberg IDs if given).
    src_path: str | None = None
    tgt_path: str | None = None

    # "prose" -> sentence segmentation; "verse" -> line segmentation.
    mode: str = "prose"

    # Alignment backend: "auto" | "embed" | "gale-church".
    aligner: str = "auto"

    # KDP trim size in inches (width, height). 6x9 is the most common.
    trim: tuple[float, float] = (6.0, 9.0)

    # Which side prints first in each bead: "src" (original first) or "tgt".
    first: str = "src"

    # Public-domain status of the TRANSLATION. The tool will warn unless this
    # is explicitly affirmed, because translators hold their own copyright.
    translation_pd_confirmed: bool = False
    translation_source_note: str = ""

    # Output filename stem (defaults to a slug of the title).
    slug: str | None = None

    # Typography / ornamentation.
    font: FontSpec = field(default_factory=FontSpec)
    decor: DecorSpec = field(default_factory=DecorSpec)
