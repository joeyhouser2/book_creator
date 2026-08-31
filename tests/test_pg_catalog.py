"""The offline Gutenberg catalog, and falling back to it when Gutendex is down."""

from __future__ import annotations

import time

import pytest
import requests

from book_creator import fetch, pg_catalog


@pytest.fixture
def catalog(tmp_path):
    """A small hand-built index — no network, no 5 MB download."""
    db = tmp_path / "pg.db"
    rows = [
        (1170, "Anabasis", "Xenophon, 432 BCE-351? BCE; Dakyns, H. G.", "en", "Text", ""),
        (22003, "The First Four Books of Xenophon's Anabasis",
         "Xenophon, 432 BCE-351? BCE; Watson, J. S.", "en", "Text", ""),
        (46976, "The Anabasis of Alexander", "Arrian, 90?-180?", "en", "Text", ""),
        (218, "De Bello Gallico", "Caesar, Julius", "la", "Text", ""),
        (10657, "Gallic War", "Caesar, Julius; McDevitte, W. A.", "en", "Text", ""),
        (999, "A Sound Recording", "Nobody", "en", "Sound", ""),
        # Greek-script title: the reason folded search exists.
        (39764, "Κύρου Ανάβασις Τόμος 1",
         "Xenophon, 432 BCE-351? BCE; Anastasopoulos, Demetrios [Translator]",
         "el", "Text", ""),
    ]
    rows = [(*r, pg_catalog.searchable(f"{r[1]} {r[2]}")) for r in rows]
    with pg_catalog._connect(db) as conn:
        conn.executemany(
            "INSERT INTO books (id, title, authors, language, kind, subjects, "
            "search) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("INSERT INTO meta (key, value) VALUES ('built_at', ?)",
                     (str(time.time()),))
        conn.commit()
    return db


# --------------------------------------------------------------------------- #
# Index lifecycle
# --------------------------------------------------------------------------- #
def test_absent_index_is_reported_not_raised(tmp_path):
    st = pg_catalog.status(tmp_path / "nothing.db")
    assert st["available"] is False
    assert st["books"] == 0


def test_status_counts_and_dates(catalog):
    st = pg_catalog.status(catalog)
    assert st["available"] and st["books"] == 7
    assert st["age_days"] == 0.0


def test_search_without_an_index_says_how_to_build_one(tmp_path):
    with pytest.raises(pg_catalog.CatalogError, match="update-catalog"):
        pg_catalog.search("anabasis", db_path=tmp_path / "nothing.db")


# --------------------------------------------------------------------------- #
# Searching
# --------------------------------------------------------------------------- #
def test_search_finds_by_title(catalog):
    res = pg_catalog.search("anabasis", db_path=catalog)
    assert res["source"] == "local-catalog"
    # The Greek-script title matches too, via folding.
    assert {r["id"] for r in res["results"]} == {1170, 22003, 46976, 39764}


def test_exact_title_ranks_first(catalog):
    # Without download counts there is no popularity signal, so title-match
    # quality is the only thing keeping the obvious answer off page two.
    res = pg_catalog.search("anabasis", db_path=catalog)
    assert res["results"][0]["id"] == 1170


def test_search_finds_by_author(catalog):
    res = pg_catalog.search("Caesar", db_path=catalog)
    assert {r["id"] for r in res["results"]} == {218, 10657}


def test_language_filter(catalog):
    res = pg_catalog.search("", language="la", db_path=catalog)
    assert [r["id"] for r in res["results"]] == [218]


def test_non_text_records_are_excluded(catalog):
    # Audio and image records cannot be built from; offering them would be a
    # dead end at fetch time.
    res = pg_catalog.search("recording", db_path=catalog)
    assert res["results"] == []


def test_translators_are_split_off_from_authors(catalog):
    (row,) = [r for r in pg_catalog.search("Anabasis", db_path=catalog)["results"]
              if r["id"] == 1170]
    assert row["authors"] == "Xenophon, 432 BCE-351? BCE"
    assert "Dakyns" in row["translators"]


def test_result_shape_matches_gutendex(catalog):
    (row, *_) = pg_catalog.search("anabasis", db_path=catalog)["results"]
    # The web UI renders both sources with the same code path.
    assert set(row) == {"id", "title", "authors", "translators", "languages",
                        "downloads", "has_text"}
    assert isinstance(row["languages"], list)


def test_miss_returns_a_hint(catalog):
    res = pg_catalog.search("zzzznotathing", db_path=catalog)
    assert res["results"] == []
    assert "hint" in res


def test_paging(catalog):
    first = pg_catalog.search("", limit=2, page=1, db_path=catalog)
    second = pg_catalog.search("", limit=2, page=2, db_path=catalog)
    assert len(first["results"]) == 2
    assert first["has_next"] is True
    assert {r["id"] for r in first["results"]}.isdisjoint(
        {r["id"] for r in second["results"]})


# --------------------------------------------------------------------------- #
# Script and diacritic folding
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,folded", [
    ("Κύρου Ανάβασις Τόμος 1", "kyroy anabasis tomos 1"),
    ("Ξενοφῶν", "xenophon"),
    ("Ανάβασις", "anabasis"),
    ("Anabasis", "anabasis"),
    ("DE BELLO GALLICO", "de bello gallico"),
    ("", ""),
])
def test_searchable_folds_script_and_accents(raw, folded):
    assert pg_catalog.searchable(raw) == folded


def test_latin_query_finds_a_greek_title(catalog):
    # The reported bug: "anabasis" with the Greek filter returned nothing,
    # because the catalogue title is "Κύρου Ανάβασις".
    res = pg_catalog.search("anabasis", language="el", db_path=catalog)
    assert [r["id"] for r in res["results"]] == [39764]


def test_greek_script_query_still_works(catalog):
    res = pg_catalog.search("Ανάβασις", db_path=catalog)
    assert 39764 in {r["id"] for r in res["results"]}


def test_accents_are_optional_in_the_query(catalog):
    with_accent = pg_catalog.search("Ανάβασις", db_path=catalog)["results"]
    without = pg_catalog.search("Αναβασις", db_path=catalog)["results"]
    assert {r["id"] for r in with_accent} == {r["id"] for r in without}


def test_folded_search_does_not_swamp_latin_results(catalog):
    # Folding must not make every query match everything.
    assert pg_catalog.search("gallico", db_path=catalog)["count"] == 1


def test_outdated_schema_is_treated_as_no_index(tmp_path):
    # A pre-folding index cannot answer transliterated queries; rebuilding is
    # a 5 MB download, so it is dropped rather than migrated.
    db = tmp_path / "old.db"
    import sqlite3
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            authors TEXT, language TEXT, kind TEXT, subjects TEXT);
        INSERT INTO books VALUES (1, 'Old', '', 'en', 'Text', '');
    """)
    conn.commit()
    conn.close()
    assert pg_catalog.available(db) is False


# --------------------------------------------------------------------------- #
# Fallback
# --------------------------------------------------------------------------- #
def test_gutendex_failure_falls_back_to_the_catalog(monkeypatch, catalog):
    def boom(*a, **kw):
        raise requests.ConnectionError("gutendex is down")

    monkeypatch.setattr(fetch.requests, "get", boom)
    monkeypatch.setattr(pg_catalog, "DB_PATH", catalog)
    monkeypatch.setattr(pg_catalog, "available", lambda *a, **k: True)
    monkeypatch.setattr(pg_catalog, "search",
                        lambda q, lang=None, page=1, **kw: {
                            "count": 1, "results": [], "has_next": False,
                            "source": "local-catalog"})

    msgs = []
    out = fetch.search_gutenberg("anabasis", log=msgs.append)
    assert out["source"] == "local-catalog"
    # The UI shows this, so the user knows why download counts vanished.
    assert "degraded" in out
    assert any("not responding" in m for m in msgs)


def test_fallback_can_be_disabled(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("gutendex is down")

    monkeypatch.setattr(fetch.requests, "get", boom)
    with pytest.raises(requests.ConnectionError):
        fetch.search_gutenberg("anabasis", fallback=False)


def test_both_sources_failing_names_the_working_tabs(monkeypatch, tmp_path):
    def boom(*a, **kw):
        raise requests.ConnectionError("gutendex is down")

    monkeypatch.setattr(fetch.requests, "get", boom)
    monkeypatch.setattr(pg_catalog, "available", lambda *a, **k: False)
    monkeypatch.setattr(pg_catalog, "build", lambda **kw: (_ for _ in ()).throw(
        pg_catalog.CatalogError("no network at all")))

    with pytest.raises(RuntimeError, match="Latin corpus"):
        fetch.search_gutenberg("anabasis")


def test_gutendex_success_is_not_degraded(monkeypatch):
    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"count": 1, "next": None, "results": [
                {"id": 1170, "title": "Anabasis", "authors": [{"name": "Xenophon"}],
                 "translators": [], "languages": ["en"], "download_count": 42,
                 "formats": {"text/plain": "http://x"}}]}

    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: FakeResp())
    out = fetch.search_gutenberg("anabasis")
    assert out["source"] == "gutendex"
    assert "degraded" not in out
    assert out["results"][0]["downloads"] == 42
