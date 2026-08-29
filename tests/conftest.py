"""Shared fixtures.

Two things here are environment-dependent and must never fail the suite when
absent: the `latin` corpus (a separate checkout) and the installed fonts (a
download step). Tests that need them skip rather than error, so the suite is
still useful on a fresh clone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from book_creator import audio, corpus, fonts  # noqa: E402
from book_creator.model import Bead, Chapter    # noqa: E402


# --------------------------------------------------------------------------- #
# A deterministic stand-in narrator
# --------------------------------------------------------------------------- #
class ToneEngine(audio.TTSEngine):
    """Synthesizes a tone instead of speech.

    Lets the whole audio pipeline be exercised -- planning, chunking, the
    utterance cache, resampling, WAV assembly, the ffmpeg encode -- without
    downloading gigabytes of model weights or needing a GPU. Its sample rate
    deliberately differs from audio.TARGET_SR so the resample path is covered.
    """

    name = "tone"
    label = "Test tone generator"
    licence = "n/a"
    clones_voice = False
    sample_rate = 22050
    max_chars = 200
    languages = None

    def __init__(self) -> None:
        self.calls = 0
        self.loaded_on: str | None = None

    def available(self):
        return True, ""

    def load(self, device):
        self.loaded_on = device

    def synthesize(self, text, *, lang, voice=None):
        self.calls += 1
        secs = max(0.05, len(text) / 800.0)
        t = np.linspace(0, secs, int(secs * self.sample_rate), endpoint=False)
        freq = 220.0 if audio.voice_lang(lang) == "it" else 330.0
        return (0.2 * np.sin(2 * np.pi * freq * t)).astype("float32")


@pytest.fixture
def tone_engine():
    """Register the stub engine under 'tone' for the duration of one test."""
    engine = ToneEngine()
    audio.register("tone", engine)
    yield engine


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def corpus_db():
    """Path to the latin corpus, or skip the test."""
    try:
        return str(corpus.find_db())
    except corpus.CorpusError as exc:
        pytest.skip(f"latin corpus not available: {exc}")


@pytest.fixture(scope="session")
def small_doc(corpus_db):
    """A fully-translated document small enough to build in a test.

    Looked up by shape rather than hard-coded id, so the suite does not break
    when the corpus is re-ingested and ids move.
    """
    with corpus.connect(corpus_db) as conn:
        row = conn.execute("""
            SELECT d.id, COUNT(s.id) AS n,
                   SUM(CASE WHEN s.english_text IS NOT NULL
                             AND TRIM(s.english_text) <> '' THEN 1 ELSE 0 END) AS t
              FROM documents d
              JOIN sections sec ON sec.doc_id = d.id
              JOIN segments s ON s.section_id = sec.id
             WHERE d.language = 'la'
             GROUP BY d.id
            HAVING n = t AND n BETWEEN 10 AND 120
             ORDER BY d.id LIMIT 1
        """).fetchone()
    if row is None:
        pytest.skip("no suitably small fully-translated document in the corpus")
    return row["id"]


@pytest.fixture(scope="session")
def untranslated_doc(corpus_db):
    """A document with no English at all -- only buildable as sides='src'."""
    with corpus.connect(corpus_db) as conn:
        row = conn.execute("""
            SELECT d.id, COUNT(s.id) AS n,
                   SUM(CASE WHEN s.english_text IS NOT NULL
                             AND TRIM(s.english_text) <> '' THEN 1 ELSE 0 END) AS t
              FROM documents d
              JOIN sections sec ON sec.doc_id = d.id
              JOIN segments s ON s.section_id = sec.id
             WHERE d.language = 'la'
             GROUP BY d.id
            HAVING t = 0 AND n BETWEEN 10 AND 120
             ORDER BY d.id LIMIT 1
        """).fetchone()
    if row is None:
        pytest.skip("no untranslated document in the corpus")
    return row["id"]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def a_font():
    """An installed font family id, or skip -- fonts are a download step."""
    cat = fonts.catalog()
    if not cat:
        pytest.skip("no fonts installed (run download_fonts.py)")
    for f in cat:
        if f["id"] == "cardo":
            return "cardo"
    return cat[0]["id"]


@pytest.fixture
def chapters():
    """Two small hand-built chapters, independent of any external data."""
    return [
        Chapter(title="Liber I", beads=[
            Bead(src=["Gallia est omnis divisa in partes tres."],
                 tgt=["All Gaul is divided into three parts."]),
            Bead(src=["Horum omnium fortissimi sunt Belgae."],
                 tgt=["Of all these, the Belgae are the bravest."]),
        ]),
        Chapter(title="Liber II", beads=[
            Bead(src=["Apud Helvetios longe nobilissimus fuit Orgetorix."],
                 tgt=["Among the Helvetii, Orgetorix was by far the most distinguished."]),
        ]),
    ]
