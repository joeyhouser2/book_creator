"""HTTP surface: local files, corpus facets, path safety, job history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webapp import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client with input/ and the job store pointed at a temp dir."""
    from webapp.jobs import JobStore

    indir = tmp_path / "input"
    indir.mkdir()
    monkeypatch.setattr(server, "INPUT_DIR", indir)
    monkeypatch.setattr(server, "_store", JobStore(str(tmp_path / "jobs.db"),
                                                   min_write_gap=0.0))
    monkeypatch.setattr(server, "_jobs", {})
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        c.input_dir = indir
        yield c


def _get(client, url):
    res = client.get(url)
    return res.status_code, res.get_json()


# --------------------------------------------------------------------------- #
# Local files
# --------------------------------------------------------------------------- #
def test_local_files_lists_only_source_types(client):
    (client.input_dir / "book.txt").write_text("Gallia est omnis.", encoding="utf-8")
    (client.input_dir / "notes.md").write_text("ignore me", encoding="utf-8")
    (client.input_dir / "art.png").write_bytes(b"\x89PNG")

    status, data = _get(client, "/api/local/files")
    assert status == 200
    assert [f["name"] for f in data["files"]] == ["book.txt"]
    assert data["files"][0]["kind"] == "txt"


def test_local_files_handles_an_empty_directory(client):
    status, data = _get(client, "/api/local/files")
    assert status == 200
    assert data["files"] == []


def test_local_inspect_reports_a_text_file(client):
    (client.input_dir / "book.txt").write_text("x" * 400, encoding="utf-8")
    status, data = _get(client, "/api/local/inspect?path=book.txt")
    assert status == 200
    assert data["characters"] == 400
    assert data["usable"]


def test_local_outline_works_for_plain_text(client):
    (client.input_dir / "book.txt").write_text(
        "CHAPTER I\n\nGallia est omnis divisa.\n\nCHAPTER II\n\nHorum omnium.\n",
        encoding="utf-8")
    status, data = _get(client, "/api/local/outline?path=book.txt")
    assert status == 200
    assert len(data["divisions"]) >= 2


# --------------------------------------------------------------------------- #
# Path safety -- the browser sends a path back, so it is untrusted input
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("attack", [
    "../../../../Windows/System32/drivers/etc/hosts",
    "../../setup.py",
    "/etc/passwd",
    "..\\..\\secret.txt",
])
def test_inspect_refuses_paths_outside_input(client, attack):
    status, data = _get(client, f"/api/local/inspect?path={attack}")
    assert status == 400
    assert "error" in data


def test_outline_refuses_paths_outside_input(client, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    status, data = _get(client, f"/api/local/outline?path={outside}")
    assert status == 400
    assert "outside" in data["error"].lower() or "no such file" in data["error"].lower()


def test_inspect_reports_a_missing_file_without_leaking_the_path(client):
    status, data = _get(client, "/api/local/inspect?path=absent.txt")
    assert status == 400
    assert "absent.txt" in data["error"]


# --------------------------------------------------------------------------- #
# Decoration previews
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("style", [
    "fleuron", "medieval", "victorian", "classical", "baroque", "nouveau",
    "rococo", "artdeco",
])
def test_ornament_preview_renders_every_drawn_style(client, style):
    res = client.get(f"/api/preview/ornament.png?style={style}")
    assert res.status_code == 200
    assert res.mimetype == "image/png"
    assert res.data.startswith(b"\x89PNG")
    assert len(res.data) > 1000


@pytest.mark.parametrize("style", ["none", "rule"])
def test_ornament_preview_is_204_when_there_is_no_art(client, style):
    # "no art" is a real answer, not a missing resource — the UI shows a
    # caption for it rather than a broken image.
    res = client.get(f"/api/preview/ornament.png?style={style}")
    assert res.status_code == 204


@pytest.mark.parametrize("style", ["rule", "corners", "frame"])
def test_margin_preview_renders(client, style):
    res = client.get(f"/api/preview/margin.png?style={style}")
    assert res.status_code == 200
    assert res.data.startswith(b"\x89PNG")


def test_margin_preview_none_is_204(client):
    assert client.get("/api/preview/margin.png?style=none").status_code == 204


def test_margin_preview_differs_between_recto_and_verso(client):
    # Margin art is gutter-aware, so a preview that ignored the side would be
    # showing something the book never prints.
    recto = client.get("/api/preview/margin.png?style=frame&recto=1").data
    verso = client.get("/api/preview/margin.png?style=frame&recto=0").data
    assert recto != verso


def test_ornament_preview_honours_colour(client):
    a = client.get("/api/preview/ornament.png?style=victorian&color=%238a7a5c").data
    b = client.get("/api/preview/ornament.png?style=victorian&color=%237c2128").data
    assert a != b


def test_preview_rejects_a_bad_colour(client):
    res = client.get("/api/preview/ornament.png?style=victorian&color=notacolour")
    assert res.status_code == 400


def test_unknown_ornament_style_is_204_not_an_error(client):
    assert client.get(
        "/api/preview/ornament.png?style=nonesuch").status_code == 204


# --------------------------------------------------------------------------- #
# Decoration settings reach the spec
# --------------------------------------------------------------------------- #
def test_every_decor_field_reaches_the_spec():
    # Regression: the web payload only carried margin/chapter/color, so four
    # DecorSpec fields were unreachable from the UI entirely.
    spec = server._spec_from_payload({
        "corpus_id": 1,
        "decorations": {
            "margin": "frame", "chapter": "rococo", "bead_separator": "fleuron",
            "color": "#7c2128", "corner_image": "art/c.png",
            "chapter_image": "art/d.png", "opener_font": "uncialantiqua",
        },
    })
    d = spec.decor
    assert (d.margin, d.chapter, d.bead_separator) == ("frame", "rococo", "fleuron")
    assert d.color == "#7c2128"
    assert d.corner_image == "art/c.png"
    assert d.chapter_image == "art/d.png"
    assert d.opener_font == "uncialantiqua"


def test_blank_decor_paths_become_none_not_empty_strings():
    # An empty string would be treated as a path and fail at render time.
    spec = server._spec_from_payload({
        "corpus_id": 1,
        "decorations": {"corner_image": "", "chapter_image": "",
                        "opener_font": ""},
    })
    assert spec.decor.corner_image is None
    assert spec.decor.chapter_image is None
    assert spec.decor.opener_font is None


# --------------------------------------------------------------------------- #
# Corpus facets
# --------------------------------------------------------------------------- #
def test_corpus_facets(client, corpus_db):
    status, data = _get(client, "/api/corpus/facets")
    assert status == 200
    for key in ("languages", "stages", "genres", "authors", "centuries"):
        assert key in data
    assert data["languages"], "expected at least one language"
    for entry in data["languages"]:
        assert entry["count"] > 0


def test_corpus_search_filters_by_author(client, corpus_db):
    _, facets = _get(client, "/api/corpus/facets")
    author = facets["authors"][0]["value"]
    status, data = _get(
        client, f"/api/corpus/search?author={author}&translated=0")
    assert status == 200
    assert data["results"]
    assert all(d["author"] == author for d in data["results"])


def test_corpus_search_styled_only(client, corpus_db):
    status, data = _get(client, "/api/corpus/search?styled=1")
    assert status == 200
    assert all(d["styled"] > 0 for d in data["results"])


def test_corpus_search_century_range(client, corpus_db):
    status, data = _get(
        client, "/api/corpus/search?century_from=5&century_to=9&translated=0")
    assert status == 200
    for d in data["results"]:
        assert d["century"] is None or 5 <= d["century"] <= 9


def test_corpus_search_miss_gives_a_hint(client, corpus_db):
    status, data = _get(client, "/api/corpus/search?q=zzzznotathing")
    assert status == 200
    assert data["results"] == []
    assert "hint" in data


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
def test_jobs_starts_empty(client):
    status, data = _get(client, "/api/jobs")
    assert status == 200
    assert data["jobs"] == []


def test_status_falls_back_to_the_persisted_record(client):
    # Simulates a restart: the process has no in-memory job, but the record and
    # the files on disk are still there.
    server._store.create("abc", "Carmina")
    server._store.save("abc", {
        "title": "Carmina", "status": "done", "pages": 11, "error": None,
        "log": ["✓ Done"], "progress": None,
        "artifacts": {"pdf": "output/carmina.pdf", "epub": "output/carmina.epub"},
    }, force=True)

    status, data = _get(client, "/api/status/abc")
    assert status == 200
    assert data["status"] == "done"
    assert data["pages"] == 11
    assert data["epub"] is True
    assert data["log"] == ["✓ Done"]


def test_status_of_an_unknown_job_is_404(client):
    status, _ = _get(client, "/api/status/nosuchjob")
    assert status == 404


def test_jobs_listing_summarizes_a_finished_build(client):
    server._store.create("abc", "Carmina")
    server._store.save("abc", {
        "title": "Carmina", "status": "done", "pages": 11, "error": None,
        "log": [], "progress": None,
        "artifacts": {"pdf": "x.pdf", "audio": {"format": "m4b"}},
    }, force=True)
    status, data = _get(client, "/api/jobs")
    assert status == 200
    row = data["jobs"][0]
    assert row["title"] == "Carmina"
    assert row["has_pdf"] and row["audio"] == "m4b"


# --------------------------------------------------------------------------- #
# Build validation
# --------------------------------------------------------------------------- #
def test_build_requires_a_source(client):
    res = client.post("/api/build", json={})
    assert res.status_code == 400
    assert "original" in res.get_json()["error"].lower()


def test_build_requires_a_translation_for_a_gutenberg_pair(client):
    res = client.post("/api/build", json={"src_id": 218})
    assert res.status_code == 400
    assert "translation" in res.get_json()["error"].lower()


def test_corpus_build_needs_no_translation_id(client, corpus_db, small_doc,
                                              monkeypatch):
    # A corpus document is a complete parallel text on its own; requiring a
    # second id would make the whole tab unusable.
    started = {}

    def fake_thread(target, args, daemon):
        started["job"] = args[0]

        class _T:
            def start(self_inner):
                pass
        return _T()

    monkeypatch.setattr(server.threading, "Thread",
                        lambda target, args, daemon: fake_thread(target, args, daemon))
    res = client.post("/api/build", json={"corpus_id": small_doc})
    assert res.status_code == 200
    assert res.get_json()["job_id"] == started["job"]


# --------------------------------------------------------------------------- #
# Audio metadata
# --------------------------------------------------------------------------- #
def test_audio_engines_lists_devices_and_a_recommendation(client):
    status, data = _get(client, "/api/audio/engines")
    assert status == 200
    assert data["engines"] and data["recommended"]
    assert any(d["id"] == "cpu" for d in data["devices"])


def test_audio_estimate_declines_a_gutenberg_pair(client):
    res = client.post("/api/audio/estimate", json={"src_id": 218, "tgt_id": 10657})
    assert res.status_code == 200
    body = res.get_json()
    # It cannot be priced without aligning first, and saying so beats guessing.
    assert body["estimate"] is None
    assert "aligned" in body["note"]


def test_audio_estimate_prices_a_corpus_work(client, corpus_db, small_doc):
    res = client.post("/api/audio/estimate", json={"corpus_id": small_doc})
    assert res.status_code == 200
    est = res.get_json()["estimate"]
    assert est["utterances"] > 0 and est["seconds"] > 0


def test_audio_estimate_halves_for_a_monolingual_edition(client, corpus_db,
                                                         small_doc):
    def utterances(sides):
        res = client.post("/api/audio/estimate", json={
            "corpus_id": small_doc, "sides": sides,
            # Chapter headings are read once per edition, so they would be
            # double-counted by the sum below; this test is about the beads.
            "audio": {"announce_chapters": False},
        })
        return res.get_json()["estimate"]["utterances"]

    both, src, tgt = utterances("both"), utterances("src"), utterances("tgt")
    assert both == src + tgt
    assert src > 0 and tgt > 0


def test_audio_estimate_counts_chapter_headings(client, corpus_db, small_doc):
    def utterances(announce):
        res = client.post("/api/audio/estimate", json={
            "corpus_id": small_doc,
            "audio": {"announce_chapters": announce}})
        return res.get_json()["estimate"]["utterances"]

    # One extra utterance per chapter when titles are read aloud.
    assert utterances(True) > utterances(False)
