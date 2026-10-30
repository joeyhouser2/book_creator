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
    # Print the source segments one per line instead of running them together.
    # Off by default: a prose bead's segments are sentences and belong in one
    # paragraph. A bead that holds several lines of verse -- a stanza, or five
    # numbered lines of a poem with no stanzas -- needs its line breaks kept.
    lines: bool = False
    # A heading that belongs inside the text rather than above a chapter: a
    # medieval rubric, set between two lines of verse. Printed centred and in
    # italic so it reads as a heading, not as two more lines of the poem.
    heading: bool = False
    # How well the two sides match, 0-1, when the aligner can say (the MT-pivot
    # aligner can). None for a bead from a backend that does not score, and for
    # one-sided beads.
    score: float | None = None
    # A plate printed under this bead (a heading, or nothing at all for a
    # tailpiece): path to the image, a caption, and its width as a fraction of
    # the text block. Unlike Chapter.image it can sit anywhere in a chapter.
    image: str | None = None
    image_caption: str = ""
    image_width: float = 0.62

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
    # This chapter's illustration, if the book has per-chapter images
    # (DecorSpec.chapter_images). Set by pipeline._render_print.
    image: str | None = None


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
    # A second family for the original-language text alone (its verse and its
    # rubrics), e.g. "TheuerdankFraktur" to set the 1517 German in the type it
    # was first printed in. The translation, headings and front matter stay in
    # `family`, as does any character the original's face has no glyph for.
    # PDF only: the EPUB keeps `family`.
    original: str | None = None


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
    # A different picture for each chapter: a path template with {n}, filled
    # with the number in the chapter's title ("Kapitel 12" -> 12), e.g.
    # "cache/theuerdank/woodcuts/wc_{n:03d}.jpg". Set under the first line of
    # the chapter (its rubric), at this fraction of the text width, in greyscale
    # unless chapter_images_color. A chapter with no such file gets none.
    chapter_images: str | None = None
    chapter_images_width: float = 0.5
    chapter_images_color: bool = False
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
    source: str = ""           # where the original text came from; default is Project Gutenberg


@dataclass
class CoverSpec:
    """Wraparound KDP cover (back + spine + front) with a per-language motif."""

    enabled: bool = False
    # Front-cover layout: ornament | plate | typographic | band. The emblem and
    # accent stay per-language; this is how they are arranged (cover.py).
    style: str = "ornament"
    # Paper stock sets the spine thickness per page: white | cream | color.
    paper: str = "white"
    background: str = "#f4ead5"      # parchment
    accent: str | None = None        # override the per-language accent color
    blurb: str = ""                  # back-cover description
    # The publisher's signum at the foot of the spine (assets/signum): auto
    # (black on a light spine, gold on a dark one) | black | gold | white | none.
    spine_logo: str = "auto"
    # A named emblem (cover.NAMED_EMBLEMS) in place of the language's own, for
    # a book its language's emblem says nothing about (Tasso's crusade).
    emblem: str | None = None


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
    # Check the finished narration rather than trusting it: nobody listens to
    # six hours of audio, and a TTS model fails by going quiet or by babbling
    # rather than by raising. "signal" costs seconds per hour of audio and
    # finds the blanks; "listen" transcribes the narration back and compares it
    # to the text, which also finds gibberish, and needs faster-whisper
    # installed. See book_creator/narration_check.py.
    check: str = "signal"       # off | signal | listen
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
    # Break divisions longer than this many characters into parts, at
    # paragraph breaks. 0 = leave them whole. See segment.subdivide: a
    # continuous text with no internal headings is otherwise one chapter
    # marker hours wide in an audiobook.
    split_long_divisions: int = 0

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
    # Line spacing of the body text: "normal", "compact" or "tight". A long
    # parallel poem is two books' worth of lines; this is how it fits one volume.
    density: str = "normal"
    # Whole-word replacements applied to the *translation* once it is made,
    # {"Henri": "Henry"}. A machine translation is consistent line by line but
    # not across a book -- La Henriade came back with the king as Henry 21 times
    # and Henri 20 -- and fixing that in the cache would mean re-translating.
    # Applied to the target side only; the original is never touched.
    tgt_replace: dict[str, str] = field(default_factory=dict)

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

    # Machine-translate the missing side, for an original with no published
    # English at all. Requires a translator registered for src_lang (see
    # book_creator/translators.py) and only applies when ONE edition was given:
    # with two, the real translation is used. The generated English is printed,
    # so it is disclosed on the copyright page rather than passed off as a human
    # translation -- and translation_pd_confirmed stops mattering, because no
    # third party holds copyright on it. See pipeline._chapters_from_machine_translation.
    translate: bool = False
    # What `translate` is handed in verse mode: "line" (one verse line at a
    # time, paired line for line), "sentence" (the lines between full stops
    # as one unit) or "stanza" (each blank-line-separated block as one unit);
    # a grouped unit is printed as its lines followed by one English passage.
    # A model that reads sentences does far better on enjambed verse that way.
    translate_by: str = "line"

    # Where a published translation covers only part of the original, machine-
    # translate the rest. Run after alignment: any bead that holds original and
    # no translation (a lost page, a passage the translator skipped) is filled
    # from the registered translator and marked with a dagger, and the copyright
    # page says so. A reader can then tell a translator's words from a machine's,
    # which a quietly filled gap would not let them do.
    fill_missing: bool = False
    # Holes in the translation whose place is known exactly: pages the scan
    # skipped. Each is {after_src, resume_src}: the last line of the original
    # the translation covers before the hole and the first it picks up again.
    # The original between them is paired with nothing (and, with
    # `fill_missing`, machine translated and dagger-marked). The English side is
    # cut at its `[about N lines lost ...]` marker. See pipeline._split_at_gaps.
    translation_gaps: list = field(default_factory=list)
    # Explicit stanza pairing for a short poem whose two sides do not follow one
    # another stanza for stanza and whose language an embedding cannot read
    # (a medieval German ballad against a 19th-century English one). A list of
    # [original, translation] pairs, each side a 1-based stanza number, an
    # "a-b" range, or null for none. Every stanza on each side must appear
    # exactly once, in order. An original stanza paired with null is a hole
    # (filled and dagger-marked under `fill_missing`). See
    # pipeline._explicit_stanza_pairs. For a poem in several divisions, a dict
    # of such lists keyed by division number ("1", "2", ...), or in the config
    # the path of a JSON file holding one.
    stanza_pairs: list | dict = field(default_factory=list)

    # Verse with `verse_align: line` only: align blocks of this many lines rather
    # than single lines (0 = single lines). A hexameter epic and its fourteener
    # paraphrase do not correspond line to line, and one line is too few words
    # for the MT-pivot aligner to match; a block of eight is enough. A missing
    # page of the translation then leaves whole blocks of the original with no
    # partner, which is exactly what `fill_missing` looks for.
    align_block: int = 0

    # With `fill_missing`: also treat a bead whose match score is below this as
    # a hole -- the translation beside it is about something else, because the
    # page that should be there is gone and the aligner paired the original with
    # its neighbour. 0 turns it off. Only the MT-pivot aligner scores beads.
    fill_below: float = 0.0

    # Verse mode only -- how the two sides are paired:
    #   "block"  — the whole original poem, then the whole translation (default)
    #   "stanza" — stanza against stanza, aligned on stanza sequence
    #   "line"   — line against line, for a translation made line for line
    #              (a scholarly crib, not a verse rendering)
    # Block is right for a short lyric, where a verse translation reorders
    # clauses freely enough that any line pairing would be invented. Stanza is
    # right for a long stanzaic narrative -- 2,500 strophes of the
    # Nibelungenlied printed as one block, then its translation as another, is
    # not a parallel text. Stanzas are found by segment.stanzas().
    verse_align: str = "block"

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

    # Produce ONLY the audiobook: no PDF, no cover, no EPUB. Useful for adding
    # narration to a book you have already printed, since skipping the render
    # means the existing PDF cannot be overwritten. Implies audio.enabled.
    audio_only: bool = False

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

    # Measured pair proofreading on the local GPU (book_creator/proofread_pairs.py):
    # LaBSE similarity, drift against neighbouring beads, length ratio, and a
    # translation model's source/target likelihood ratio in both directions,
    # each judged against this book's own distribution. Writes
    # <slug>-proofread.md. Advisory only. The default model is Tower-Instruct,
    # ~14 GB in half precision, so it wants the 16 GB card.
    proofread: bool = False
    proofread_model: str = "Unbabel/TowerInstruct-7B-v0.2"
    # Cap how many beads are scored (from the start). None = every bead.
    proofread_sample: int | None = None

    # Line-level re-cut of a block alignment (book_creator/align_lines.py): a
    # translation model scores each English line against the German block it
    # sits beside and its neighbours, and lines are moved back across a
    # boundary where the evidence says they belong. Fixes English displaced
    # by several lines, which name-based refinement cannot. GPU, ~30 min for
    # a long poem the first time, then cached on the text.
    recut: bool = False
    recut_model: str = "Unbabel/TowerInstruct-7B-v0.2"
    # Nats of evidence a line needs to be moved off the block it is in.
    recut_lambda: float = 1.0
    recut_device: str = "auto"
