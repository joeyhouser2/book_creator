"""Perseus: TEI parsing, citation-anchored pairing, and the index."""

from __future__ import annotations

import time

import pytest

from book_creator import perseus

TEI = """<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
  <div type="edition">
    <div type="textpart" subtype="book" n="1">
      <div type="textpart" subtype="chapter" n="1">
        <div type="textpart" subtype="section" n="1">
          <p>First section. <note>an editorial note</note>Still first.</p>
        </div>
        <div type="textpart" subtype="section" n="2">
          <p>Second section.</p>
        </div>
      </div>
    </div>
    <div type="textpart" subtype="book" n="2">
      <div type="textpart" subtype="chapter" n="1">
        <div type="textpart" subtype="section" n="1">
          <p>Book two.</p>
        </div>
      </div>
    </div>
  </div>
</body></text></TEI>"""

CTS = """<?xml version="1.0"?>
<ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
         urn="urn:cts:greekLit:tlg0032.tlg006" xml:lang="grc">
  <ti:title xml:lang="eng">Anabasis</ti:title>
  <ti:edition urn="urn:cts:greekLit:tlg0032.tlg006.perseus-grc2" xml:lang="grc">
    <ti:description>Xenophon. Opera omnia, Vol. 3. Oxford: Clarendon Press, 1904.</ti:description>
  </ti:edition>
  <ti:translation urn="urn:cts:greekLit:tlg0032.tlg006.perseus-eng2" xml:lang="eng">
    <ti:description>Brownson, Carleton L, translator. Harvard University Press, 1921-1922.</ti:description>
  </ti:translation>
</ti:work>"""


# --------------------------------------------------------------------------- #
# TEI parsing
# --------------------------------------------------------------------------- #
def test_divisions_go_to_the_finest_level():
    # Books are the printing unit but sections are the alignment unit: a
    # sentence aligner working over a whole book accumulates off-by-one drift.
    divs = perseus.divisions(TEI)
    assert [d.ref for d in divs] == ["1.1.1", "1.1.2", "2.1.1"]


def test_division_path_and_top():
    (first, *_) = perseus.divisions(TEI)
    assert first.path == ("1", "1", "1")
    assert first.top == "1"


def test_editorial_notes_are_dropped():
    (first, *_) = perseus.divisions(TEI)
    # A note belongs to the edition, not the work; printing it (or reading it
    # aloud) would be wrong.
    assert "editorial note" not in first.text
    assert "First section." in first.text
    assert "Still first." in first.text


def test_body_without_textparts_becomes_one_division():
    tei = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
           '<p>Just prose.</p></body></text></TEI>')
    (only,) = perseus.divisions(tei)
    assert only.ref == "1"
    assert "Just prose." in only.text


def test_malformed_tei_raises():
    with pytest.raises(perseus.PerseusError, match="Malformed"):
        perseus.divisions("<TEI><unclosed>")


def test_missing_body_raises():
    with pytest.raises(perseus.PerseusError, match="body"):
        perseus.divisions('<TEI xmlns="http://www.tei-c.org/ns/1.0"></TEI>')


def test_greek_elision_mark_is_normalised():
    # U+02BC is what Perseus uses; GFS Didot has no glyph for it and prints a
    # box, so it is folded to the identical-looking U+2019.
    tei = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
           '<p>δʼ ἐνόμιζε</p>'
           '</body></text></TEI>')
    (only,) = perseus.divisions(tei)
    assert "ʼ" not in only.text
    assert "’" in only.text


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #
def _div(ref, text="x"):
    return perseus.Division(path=tuple(ref.split(".")), title="", text=text)


def test_pairing_matches_on_citation_refs():
    src = [_div("1.1.1"), _div("1.1.2"), _div("2.1.1")]
    tgt = [_div("2.1.1"), _div("1.1.1"), _div("1.1.2")]   # different order
    paired = perseus.pair_divisions(src, tgt)
    # Order follows the source; matching is by reference, not position.
    assert [s.ref for s, _ in paired] == ["1.1.1", "1.1.2", "2.1.1"]
    assert all(s.ref == t.ref for s, t in paired)


def test_unmatched_source_divisions_are_skipped_and_reported():
    src = [_div("1.1.1"), _div("1.1.2")]
    tgt = [_div("1.1.1")]
    msgs = []
    paired = perseus.pair_divisions(src, tgt, log=msgs.append)
    assert [s.ref for s, _ in paired] == ["1.1.1"]
    assert any("no counterpart" in m for m in msgs)


def test_incompatible_schemes_fall_back_to_order():
    # Two editions numbered differently still produce a book, but the log has
    # to say the anchoring was lost.
    src = [_div("1.1.1"), _div("1.1.2")]
    tgt = [_div("a"), _div("b")]
    msgs = []
    paired = perseus.pair_divisions(src, tgt, log=msgs.append)
    assert len(paired) == 2
    assert any("different citation schemes" in m for m in msgs)


def test_pairing_reports_the_unit_it_anchored_on():
    msgs = []
    perseus.pair_divisions([_div("1.1.1")], [_div("1.1.1")], log=msgs.append)
    assert any("section" in m for m in msgs)


# --------------------------------------------------------------------------- #
# CTS metadata
# --------------------------------------------------------------------------- #
def test_cts_gives_title_and_edition_years():
    meta = perseus._parse_work_cts(CTS)
    assert meta["title"] == "Anabasis"
    assert "Clarendon" in meta["src_desc"]
    assert meta["src_year"] == 1904
    # A range takes the later year: that is when the edition was completed.
    assert meta["tgt_year"] == 1922


def test_paired_works_needs_both_sides():
    paths = [
        "data/tlg0032/tlg006/tlg0032.tlg006.perseus-grc2.xml",
        "data/tlg0032/tlg006/tlg0032.tlg006.perseus-eng2.xml",
        "data/tlg0099/tlg001/tlg0099.tlg001.perseus-grc1.xml",   # no English
        "data/tlg0098/tlg001/tlg0098.tlg001.perseus-eng1.xml",   # no source
    ]
    found = perseus._paired_works(paths)
    assert list(found) == [("tlg0032", "tlg006")]


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
@pytest.fixture
def index(tmp_path):
    db = tmp_path / "perseus.db"
    with perseus._connect(db) as conn:
        conn.execute(
            "INSERT INTO works (id, repo, textgroup, work, author, title, "
            "language, src_file, src_desc, tgt_file, tgt_desc, tgt_year, search)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("greekLit:tlg0032.tlg006", "greekLit", "tlg0032", "tlg006",
             "Xenophon", "Anabasis", "grc", "a.xml", "Oxford, 1904.",
             "b.xml", "Brownson, 1922.", 1922,
             perseus.searchable("Anabasis Xenophon")))
        conn.execute(
            "INSERT INTO works (id, repo, textgroup, work, author, title, "
            "language, src_file, src_desc, tgt_file, tgt_desc, tgt_year, search)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("latinLit:phi0448.phi001", "latinLit", "phi0448", "phi001",
             "Caesar", "Gallic War", "lat", "c.xml", "Teubner, 1908.",
             "d.xml", "Modern press, 1998.", 1998,
             perseus.searchable("Gallic War Caesar")))
        conn.execute("INSERT INTO meta (key, value) VALUES ('built_at', ?)",
                     (str(time.time()),))
        conn.commit()
    return db


def test_status_counts_by_language(index):
    st = perseus.status(index)
    assert st["works"] == 2
    assert st["by_language"] == {"grc": 1, "lat": 1}


def test_search_by_author(index):
    res = perseus.search("xenophon", db_path=index)
    assert [w["id"] for w in res["results"]] == ["greekLit:tlg0032.tlg006"]
    assert res["source"] == "perseus"


def test_search_language_filter(index):
    res = perseus.search("", language="lat", db_path=index)
    assert [w["author"] for w in res["results"]] == ["Caesar"]


def test_pd_status_from_the_translation_year(index):
    by_id = {w["id"]: w for w in perseus.search("", db_path=index)["results"]}
    # US public domain is publication before 1929.
    assert by_id["greekLit:tlg0032.tlg006"]["pd_status"] == "ok"
    assert by_id["latinLit:phi0448.phi001"]["pd_status"] == "check"


def test_missing_year_is_unknown_not_ok(tmp_path):
    db = tmp_path / "p.db"
    with perseus._connect(db) as conn:
        conn.execute(
            "INSERT INTO works (id, repo, textgroup, work, language, tgt_year) "
            "VALUES ('x','greekLit','a','b','grc', NULL)")
        conn.commit()
    (w,) = perseus.search("", db_path=db)["results"]
    # Absence of evidence must not read as permission to publish.
    assert w["pd_status"] == "unknown"


def test_get_unknown_work_raises(index):
    with pytest.raises(perseus.PerseusError, match="No Perseus work"):
        perseus.get("greekLit:nope.nope", db_path=index)


def test_search_without_an_index_says_how_to_build_one(tmp_path):
    with pytest.raises(perseus.PerseusError, match="update-perseus"):
        perseus.search("x", db_path=tmp_path / "absent.db")
