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
    # Paths to rendered grand-staff (treble + bass) page images for this
    # chapter, when it matched a known musical setting — see music.py.
    # Populated by pipeline.build_book, empty otherwise.
    music_images: list[str] = field(default_factory=list)
    music_caption: str = ""


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
    # Under each chapter title: none | fleuron | rule | medieval | victorian |
    # classical | baroque | nouveau | rococo | artdeco | random (a different
    # style per chapter, deterministic by chapter index — see
    # decorations.pick_random_style)
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
    # Decorative display font for each chapter's opening bead (both languages),
    # e.g. "UncialAntiqua". None disables the treatment and opens normally.
    opener_font: str | None = None


@dataclass
class CopyrightSpec:
    """Copyright-page content.

    Important: the original and a pre-1929 translation are public domain, so the
    text itself can't be copyrighted (that would be copyfraud). What you may
    claim is the *compilation* — the parallel arrangement, typography, and any
    new material. The default wording says exactly that.
    """

    enabled: bool = True
    publisher: str = ""        # imprint name, e.g. "Houser Classics"
    holder: str = ""           # who holds the compilation copyright
    year: int | None = None    # edition year
    isbn: str = ""
    translator: str = ""       # translator name, for the public-domain credit
    rights: str | None = None  # full override of the generated rights text


@dataclass
class CoverSpec:
    """Wraparound KDP cover (back + spine + front) with a per-language motif."""

    enabled: bool = False
    # Paper stock sets the spine thickness per page: white | cream | color.
    paper: str = "white"
    background: str = "#f4ead5"      # parchment
    accent: str | None = None        # override the per-language accent color
    blurb: str = ""                  # back-cover description


@dataclass
class MusicSpec:
    """Musical-literature companion: for poems that were set to music by a
    composer, typeset the piano grand staff (treble + bass clef) alongside
    the original text and its translation.

    Source: the OpenScore Lieder Corpus (github.com/OpenScore/Lieder),
    CC0-licensed MusicXML encodings of public-domain lieder — the same
    public-domain bar this tool already holds text sources to. Matching is
    by the poem's normalized first line (its "incipit"), since verse
    divisions here are numbered, not individually titled.

    Rendering needs LilyPond (both `lilypond` and `musicxml2ly`) on PATH —
    it is NOT bundled or auto-installed. If it's missing, matched poems are
    logged and skipped; the build still succeeds without music.
    """

    enabled: bool = False
    # Which registered catalog to match poems against. Currently only
    # "dichterliebe" (Schumann, Op. 48, 16 songs) is built in — see
    # music.py's _REGISTRIES.
    catalog: str = "dichterliebe"


@dataclass
class CorpusSpec:
    """Pull the parallel text out of the `latin` repo's corpus instead of
    fetching and aligning two Gutenberg editions.

    That corpus stores one Latin (or Greek) sentence per row with its English
    alongside, so segment *i* already corresponds to segment *i* -- the book
    skips fetch/clean/segment/align entirely and there is no alignment drift
    to proofread for. See book_creator/corpus.py.
    """

    doc_id: int | None = None
    # Path to the latin repo checkout or directly to corpus.db. None searches
    # $LATIN_REPO, then ../latin, then ~/Documents/GitHub/latin.
    db_path: str | None = None
    # Optional (first, last) section indices, 1-based inclusive, like src_range.
    section_range: tuple[int, int] | None = None
    # Use `english_styled` (the latin repo's Victorian stylizer output) where a
    # segment has it, falling back to the plain machine translation.
    prefer_styled: bool = True
    # Drop segments that have no English at all. Off prints them source-only.
    skip_untranslated: bool = True
    # Print the letters without the editorial apparatus that critical and
    # epigraphic editions carry ("<A>ltus", "Imp(erator)", "[Aug]ustus"). On by
    # default: a POD parallel text is for reading, and a narrator cannot say a
    # bracket. Turn off for a scholarly edition that should show its sigla.
    strip_markup: bool = True


@dataclass
class PerseusSpec:
    """Build from the Perseus Digital Library: the classical canon, paired.

    Perseus publishes the Greek/Latin original *and* a human English
    translation as TEI, both carrying the same CTS citation scheme -- so the
    two sides anchor on their own book/chapter numbers rather than being
    matched statistically, and the English needs no machine-translation
    disclosure. See book_creator/perseus.py.
    """

    work_id: str | None = None          # e.g. "greekLit:tlg0032.tlg006"
    # Optional (first, last) division indices, 1-based inclusive, applied
    # after the two editions are matched on their citation refs.
    division_range: tuple[int, int] | None = None


@dataclass
class AudioSpec:
    """Interleaved bilingual audiobook narrated by a local GPU TTS model.

    Each bead is read original-then-translation (or the reverse, following
    `BookSpec.first`), mirroring the printed parallel text in time rather than
    in space. See book_creator/audio.py.
    """

    enabled: bool = False
    # Registered engine id: chatterbox (default, MIT) | kokoro | xtts.
    engine: str = "chatterbox"
    # Torch device to synthesize on: "cuda:0", "cuda:1", "cpu".
    device: str = "cuda:0"
    # Reference voice per side. For cloning engines this is a path to a short
    # WAV of the narrator; for fixed-voice engines it is a voice name. Using
    # the same value for both sides gives one narrator reading both languages.
    src_voice: str | None = None
    tgt_voice: str | None = None
    # Gaps, in seconds: between the two sides of one bead, between beads, and
    # after a spoken chapter heading.
    pause_within: float = 0.45
    pause_bead: float = 0.9
    pause_chapter: float = 1.5
    # Read each chapter's title aloud before its text.
    announce_chapters: bool = True
    # Container for the assembled book: m4b (chapter markers) | mp3.
    format: str = "m4b"
    # Cap beads for a quick listen-test of the voice before committing hours
    # of GPU time. None narrates the whole book.
    max_beads: int | None = None
    # Which side is read first; set from BookSpec.first at build time.
    first: str = "src"


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
    # Or pull a pre-aligned work from the latin repo's corpus, which overrides
    # both of the above and skips fetch/segment/align (see CorpusSpec).
    corpus: "CorpusSpec" = field(default_factory=lambda: CorpusSpec())
    # Or a Perseus work, which supplies both sides at once (see PerseusSpec).
    perseus: "PerseusSpec" = field(default_factory=lambda: PerseusSpec())

    # "prose" -> sentence segmentation; "verse" -> line segmentation.
    mode: str = "prose"

    # Verse mode only: also split on an isolated, untitled poem's title line
    # (blank-flanked by a real paragraph-sized gap, not just numbered "I"/"II"
    # cycle markers) — see segment._is_isolated_title. Needed for collections
    # that name standalone poems instead of numbering every one continuously
    # (e.g. Les Fleurs du Mal); leave off for collections that already number
    # every poem in one run (e.g. Buch der Lieder's I..CCXXVII), since it can
    # pick up extra unintended divisions there instead of helping.
    poem_titles: bool = False

    # Alignment backend: "auto" | "embed" | "gale-church".
    aligner: str = "auto"

    # Strip inline section markers ("I.--", "XLIX.--") and stray boilerplate from
    # segments before alignment.
    clean: bool = True

    # Run a registered restyler (book_creator/restylers.py) over the printed
    # translation text after alignment, e.g. a "victorianizer" model. No-op
    # unless one is registered for tgt_lang. Runs after alignment so it never
    # affects sentence matching, only the final prose.
    restyle: bool = True

    # Optional (first, last) division indices to include, 1-based inclusive, per
    # side — so you can scope both editions to the same content (e.g. just Book
    # I). None = whole text. See segment.outline() for the division list.
    src_range: tuple[int, int] | None = None
    tgt_range: tuple[int, int] | None = None

    # KDP trim size in inches (width, height). 6x9 is the most common.
    trim: tuple[float, float] = (6.0, 9.0)

    # Which side prints first in each bead: "src" (original first) or "tgt".
    first: str = "src"

    # Which sides to include at all:
    #   "both" — the parallel text (default)
    #   "src"  — a monolingual edition of the ORIGINAL, translation dropped
    #   "tgt"  — a monolingual edition of the TRANSLATION, original dropped
    # Alignment still runs for "src"/"tgt" on the Gutenberg path, because the
    # bead structure is what carries chapter anchoring — only the printing (and
    # narration) of the unwanted side is dropped. `first` stops mattering once
    # a bead has one side. See pipeline._apply_sides.
    sides: str = "both"

    # Include a table of contents (only rendered when there are 2+ titled
    # divisions to list).
    toc: bool = True

    # Public-domain status of the TRANSLATION. The tool will warn unless this
    # is explicitly affirmed, because translators hold their own copyright.
    translation_pd_confirmed: bool = False
    translation_source_note: str = ""

    # Output filename stem (defaults to a slug of the title).
    slug: str | None = None

    # Typography / ornamentation.
    font: FontSpec = field(default_factory=FontSpec)
    decor: DecorSpec = field(default_factory=DecorSpec)
    copyright: CopyrightSpec = field(default_factory=CopyrightSpec)
    cover: CoverSpec = field(default_factory=CoverSpec)
    music: MusicSpec = field(default_factory=MusicSpec)
    audio: AudioSpec = field(default_factory=AudioSpec)

    # Also emit a reflowable EPUB alongside the PDF (needs requirements-epub.txt).
    epub: bool = False

    # Optional post-alignment QA pass: ask a local LLM (via Ollama) to flag
    # beads that look misaligned, have leftover markup, or are otherwise
    # malformed (book_creator/reviewer.py). Advisory only — never edits
    # content or blocks the build, just writes <slug>-review.md alongside the
    # PDF listing what to proofread. Needs `ollama serve` running locally
    # with review_model pulled.
    review: bool = False
    review_model: str = "llama3.1"
    review_host: str = "http://localhost:11434"
    # Cap how many beads get sent to the model (from the start), for a quick
    # spot-check on a long book. None = review every bead.
    review_sample: int | None = None
