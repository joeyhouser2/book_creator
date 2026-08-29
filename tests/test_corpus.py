"""Reading pre-aligned works out of the latin repo's corpus."""

from __future__ import annotations

import pytest

from book_creator import corpus


# --------------------------------------------------------------------------- #
# Locating the database
# --------------------------------------------------------------------------- #
def test_find_db_error_names_what_it_tried(monkeypatch, tmp_path):
    # Neutralize the built-in fallbacks too, or this passes only on a machine
    # that happens not to have the repo in its default location.
    monkeypatch.setattr(corpus, "_REPO_CANDIDATES", ())
    monkeypatch.setenv("LATIN_REPO", str(tmp_path / "nope"))
    with pytest.raises(corpus.CorpusError) as exc:
        corpus.find_db()
    # A bare "not found" would leave the user guessing where to put it.
    assert "LATIN_REPO" in str(exc.value)
    assert "Tried" in str(exc.value)


def test_find_db_accepts_the_db_file_directly(corpus_db):
    assert corpus.find_db(corpus_db) == corpus.find_db()


def test_connection_is_read_only(corpus_db):
    # This project must never mutate the user's corpus.
    with corpus.connect(corpus_db) as conn:
        with pytest.raises(Exception, match="readonly|read-only"):
            conn.execute("UPDATE documents SET title = 'x' WHERE id = 1")


# --------------------------------------------------------------------------- #
# Licence classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("licence,expected", [
    ("Public domain (pre-1929 scan, raw OCR text)", "ok"),
    ("CC0/CC-BY (CroALa, per-work -- check teiHeader)", "ok"),
    ("CC BY-SA (CAMENA, GitHub republish)", "ok"),
    ("CC BY-NC-ND (DigilibLT)", "check"),
    ("no explicit license published -- personal research use", "check"),
    ("Corpus Thomisticum; research use", "check"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_licence_risk(licence, expected):
    # The badge drives a publishing decision, so a restrictive licence must
    # never be classified "ok".
    assert corpus.licence_risk(licence) == expected


# --------------------------------------------------------------------------- #
# Searching
# --------------------------------------------------------------------------- #
def test_search_returns_counted_documents(corpus_db):
    res = corpus.search_documents("", limit=5, db_path=corpus_db)
    assert res["count"] > 0
    assert len(res["results"]) <= 5
    for d in res["results"]:
        assert d["segments"] >= d["translated"]
        assert 0.0 <= d["coverage"] <= 1.0
        assert d["license_risk"] in ("ok", "check", "unknown")


def test_search_translated_only_excludes_untranslated(corpus_db):
    res = corpus.search_documents("", translated_only=True, limit=20,
                                  db_path=corpus_db)
    assert res["results"], "expected some translated works"
    assert all(d["translated"] > 0 for d in res["results"])


def test_search_language_filter(corpus_db):
    res = corpus.search_documents("", language="grc", limit=10, db_path=corpus_db)
    assert all(d["language"] == "grc" for d in res["results"])


def test_search_miss_returns_a_useful_hint(corpus_db):
    res = corpus.search_documents("zzzzzznotathing", db_path=corpus_db)
    assert res["results"] == []
    assert "hint" in res


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def test_outline_is_one_based_and_ordered(corpus_db, small_doc):
    sections = corpus.outline(small_doc, db_path=corpus_db)
    assert sections
    assert [s["index"] for s in sections] == list(range(1, len(sections) + 1))
    assert all(s["segments"] >= s["translated"] for s in sections)


def test_load_chapters_pairs_each_segment(corpus_db, small_doc):
    load = corpus.load_chapters(small_doc, db_path=corpus_db)
    assert load.chapters and load.beads > 0
    for ch in load.chapters:
        for bead in ch.beads:
            # The corpus is aligned per segment, so every bead is 1:1 -- this
            # is the property that lets the build skip alignment entirely.
            assert len(bead.src) == 1
            assert bead.src_text.strip()


def test_section_range_selects_a_subset(corpus_db, small_doc):
    full = corpus.load_chapters(small_doc, db_path=corpus_db)
    if len(full.chapters) < 2:
        pytest.skip("document has only one section")
    part = corpus.load_chapters(small_doc, section_range=(1, 1), db_path=corpus_db)
    assert len(part.chapters) == 1
    assert part.beads < full.beads


def test_strip_markup_removes_editorial_sigla(corpus_db):
    """Find a work carrying sigla and check both renderings of it."""
    with corpus.connect(corpus_db) as conn:
        row = conn.execute("""
            SELECT sec.doc_id FROM segments s
              JOIN sections sec ON s.section_id = sec.id
             WHERE s.embed_text IS NOT NULL AND TRIM(s.embed_text) <> ''
               AND s.latin_text LIKE '%<%'
             LIMIT 1
        """).fetchone()
    if row is None:
        pytest.skip("no marked-up segments in this corpus")

    doc_id = row["doc_id"]
    clean = corpus.sample(doc_id, limit=40, strip_markup=True, db_path=corpus_db)
    raw = corpus.sample(doc_id, limit=40, strip_markup=False, db_path=corpus_db)

    assert any(c["marked_up"] for c in clean), "expected some stripped segments"

    def letters(s: str) -> str:
        """Just the characters a reader would voice.

        Stripping only ever *deletes* editorial marks -- brackets, line-break
        slashes, lacuna dashes, illegibility markers -- so the alphanumeric
        sequence has to come through byte-identical.
        """
        return "".join(ch for ch in s if ch.isalnum())

    for c, r in zip(clean, raw):
        if not c["marked_up"]:
            continue
        # The apparatus is gone from the printed form...
        assert not any(ch in c["src"] for ch in "<>[]{}")
        # ...but not one letter of the text was lost with it. Epigraphic
        # editions nest marks mid-word ("Imp(erator) Caes]ar"), so the letters
        # only survive if the brackets are removed rather than the groups.
        assert letters(c["src"]) == letters(r["src"])


def test_untranslated_doc_is_rejected_with_a_pointer(corpus_db, untranslated_doc):
    # Building it as a parallel text is impossible; the message must say what
    # to do instead rather than just failing.
    with pytest.raises(corpus.CorpusError, match="sides"):
        corpus.load_chapters(untranslated_doc, skip_untranslated=True,
                             db_path=corpus_db)


def test_untranslated_doc_loads_when_untranslated_segments_are_kept(
        corpus_db, untranslated_doc):
    load = corpus.load_chapters(untranslated_doc, skip_untranslated=False,
                                db_path=corpus_db)
    assert load.beads > 0
    assert load.untranslated > 0
    assert all(not b.tgt for ch in load.chapters for b in ch.beads)


def test_missing_document_raises(corpus_db):
    with pytest.raises(corpus.CorpusError):
        corpus.document(99_999_999, db_path=corpus_db)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def test_source_note_discloses_machine_translation(corpus_db, small_doc):
    doc = corpus.document(small_doc, db_path=corpus_db)
    note = corpus.source_note(doc)
    # Passing MT off as a human translation would be the dishonest failure.
    assert "machine translation" in note

    # An original-only edition prints no English, so there is nothing to
    # disclose about it.
    assert "machine translation" not in corpus.source_note(doc, translated=False)
