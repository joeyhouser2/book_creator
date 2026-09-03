"""HTTP surface: local files, corpus facets, path safety, job history."""

from __future__ import annotations

import json
import time
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
# Perseus
# --------------------------------------------------------------------------- #
def test_perseus_status(client):
    status, data = _get(client, "/api/perseus/status")
    assert status == 200
    assert "available" in data


def test_perseus_search_endpoint_exists(client):
    # Regression guard for a stale server: a missing route returns Flask's
    # HTML error page, which the browser then fails to parse as JSON. The
    # symptom ("Unexpected token '<'") points nowhere near the cause.
    res = client.get("/api/perseus/search?q=anabasis")
    assert res.status_code != 404
    assert res.mimetype == "application/json"


def test_every_api_route_answers_json_not_html(client):
    """No /api/ route may return an HTML body on a normal request.

    The front end parses every response as JSON, so an HTML page anywhere
    surfaces as an unreadable parse error rather than the real problem.
    """
    checks = [
        "/api/fonts", "/api/local/files", "/api/jobs",
        "/api/audio/engines", "/api/catalog/status", "/api/perseus/status",
    ]
    for url in checks:
        res = client.get(url)
        assert res.mimetype == "application/json", f"{url} returned {res.mimetype}"


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
    """With nothing chosen at all the message no longer says "original": a
    monolingual edition can be built from a text in either slot, so what is
    missing is a text, not specifically an original."""
    res = client.post("/api/build", json={})
    assert res.status_code == 400
    assert "choose a text" in res.get_json()["error"].lower()


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


def test_audio_estimate_note_names_the_sources_that_do_work(client):
    body = client.post("/api/audio/estimate", json={"src_id": 218}).get_json()
    # The old message said "corpus sources" only, which read as a refusal on
    # the Perseus tab even though Perseus can be priced.
    assert "Perseus" in body["note"]
    assert "corpus" in body["note"]


def test_audio_estimate_handles_a_perseus_work(client, monkeypatch):
    """Perseus is anchored on citation refs, so it can be priced without a build."""
    from book_creator.model import Bead, Chapter

    def fake_chapters(spec, log):
        spec.src_lang = "grc"
        return [Chapter(title="Book 1", beads=[
            Bead(src=["ἓν"], tgt=["one"]), Bead(src=["δύο"], tgt=["two"])])]

    monkeypatch.setattr(server.pipeline, "_chapters_from_perseus", fake_chapters)
    res = client.post("/api/audio/estimate",
                      json={"perseus_id": "greekLit:tlg0032.tlg006",
                            "audio": {"announce_chapters": False}})
    assert res.status_code == 200
    est = res.get_json()["estimate"]
    assert est["utterances"] == 4          # 2 beads x 2 sides
    assert est["seconds"] > 0


def test_perseus_estimate_halves_for_a_monolingual_edition(client, monkeypatch):
    from book_creator.model import Bead, Chapter

    def fake_chapters(spec, log):
        spec.src_lang = "grc"
        return [Chapter(title="Book 1", beads=[
            Bead(src=["ἓν"], tgt=["one"]), Bead(src=["δύο"], tgt=["two"])])]

    monkeypatch.setattr(server.pipeline, "_chapters_from_perseus", fake_chapters)

    def utterances(sides):
        return client.post("/api/audio/estimate", json={
            "perseus_id": "x", "sides": sides,
            "audio": {"announce_chapters": False}}).get_json()["estimate"]["utterances"]

    assert utterances("both") == utterances("src") + utterances("tgt")


def test_perseus_estimate_reports_a_fetch_failure(client, monkeypatch):
    def boom(spec, log):
        raise RuntimeError("Perseus is unreachable")

    monkeypatch.setattr(server.pipeline, "_chapters_from_perseus", boom)
    res = client.post("/api/audio/estimate", json={"perseus_id": "x"})
    assert res.status_code == 502
    assert "unreachable" in res.get_json()["error"]


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


# --------------------------------------------------------------------------- #
# Corpus passes (translate / victorianize)
#
# The passes need a GPU and a multi-gigabyte model, so these cover the HTTP
# surface around them -- validation, naming, and refusing pointless work --
# and never let a real one start.
# --------------------------------------------------------------------------- #
def _stub_corpus(monkeypatch, title, *, translation, styling):
    """Stand in for the corpus so these never touch the real database."""
    class Doc:
        pass

    doc = Doc()
    doc.title = title
    monkeypatch.setattr(server.corpus, "document", lambda *a, **k: doc)
    monkeypatch.setattr(server.corpus, "pending", lambda *a, **k: {
        "segments": translation + styling,
        "translation": translation, "styling": styling})


def test_pass_status_reports_when_the_repo_is_missing(client, monkeypatch):
    monkeypatch.setattr(server.corpus_jobs, "status",
                        lambda *a, **k: {"available": False, "error": "no repo"})
    status, data = _get(client, "/api/corpus/pass/status")
    assert status == 200
    assert data["available"] is False


def test_pass_rejects_an_unknown_kind(client):
    res = client.post("/api/corpus/pass",
                      json={"kind": "delete", "doc_id": 1})
    assert res.status_code == 400
    assert "translate" in res.get_json()["error"]


def test_pass_requires_a_document(client):
    res = client.post("/api/corpus/pass", json={"kind": "translate"})
    assert res.status_code == 400
    assert "doc_id" in res.get_json()["error"]


def test_pass_refuses_work_with_nothing_to_do(client, monkeypatch, corpus_db):
    """Loading a model to discover there is nothing to do wastes minutes."""
    _stub_corpus(monkeypatch, "Iam Perfectum", translation=0, styling=0)
    res = client.post("/api/corpus/pass", json={"kind": "translate", "doc_id": 1})
    assert res.status_code == 400
    assert "Nothing to do" in res.get_json()["error"]


def test_pass_starts_a_named_job_and_reports_progress(client, monkeypatch, corpus_db):
    """The job is named after the work, so history is readable -- and it is
    pre-seeded with the pending count so the bar is scaled before the model
    has even loaded."""
    _stub_corpus(monkeypatch, "De Bello Gallico", translation=250, styling=0)
    started = {}

    def fake_run(kind, doc_id, *, opts=None, on_log=None, on_progress=None,
                 should_stop=None, repo_path=None):
        started.update(kind=kind, doc_id=doc_id, opts=opts)
        on_log("working")
        on_progress(250, 250, {"rate": 2.0})
        return {"segments": 250, "cancelled": False}

    monkeypatch.setattr(server.corpus_jobs, "run", fake_run)

    res = client.post("/api/corpus/pass",
                      json={"kind": "translate", "doc_id": 7,
                            "opts": {"batch_size": 4}})
    assert res.status_code == 200
    body = res.get_json()
    assert body["pending"] == 250
    assert started["kind"] == "translate" and started["doc_id"] == 7
    assert started["opts"]["batch_size"] == 4

    # The worker runs on a thread; wait for it rather than sleeping blindly.
    job_id = body["job_id"]
    for _ in range(200):
        status, data = _get(client, f"/api/status/{job_id}")
        if data["status"] != "running":
            break
        time.sleep(0.05)

    assert data["status"] == "done"
    assert data["kind"] == "corpus-translate"
    assert data["segments"] == 250
    assert server._store.recent(5)[0]["title"] == "Translate: De Bello Gallico"


def test_a_failing_pass_surfaces_its_error(client, monkeypatch, corpus_db):
    _stub_corpus(monkeypatch, "Fragmenta", translation=5, styling=0)

    def boom(*a, **k):
        raise server.corpus_jobs.JobError("exited with status 3")

    monkeypatch.setattr(server.corpus_jobs, "run", boom)

    job_id = client.post("/api/corpus/pass",
                         json={"kind": "translate", "doc_id": 1}).get_json()["job_id"]
    for _ in range(200):
        status, data = _get(client, f"/api/status/{job_id}")
        if data["status"] != "running":
            break
        time.sleep(0.05)

    assert data["status"] == "error"
    assert "status 3" in data["error"]


def test_only_one_pass_runs_at_a_time(client, monkeypatch, corpus_db):
    """Passes share one GPU, and the stylizer alone can fill a 16 GB card, so
    a second one would not queue behind the first -- it would OOM them both."""
    import threading

    _stub_corpus(monkeypatch, "Occupatus", translation=100, styling=100)
    release = threading.Event()

    def blocking_run(*a, **k):
        release.wait(timeout=10)
        return {"segments": 1, "cancelled": False}

    monkeypatch.setattr(server.corpus_jobs, "run", blocking_run)

    first = client.post("/api/corpus/pass", json={"kind": "translate", "doc_id": 1})
    assert first.status_code == 200
    try:
        second = client.post("/api/corpus/pass", json={"kind": "stylize", "doc_id": 2})
        assert second.status_code == 409
        assert "already running" in second.get_json()["error"]
    finally:
        release.set()


def test_pass_is_refused_while_reading_a_snapshot(client, monkeypatch, corpus_db):
    """A pass writes to the live corpus.db whatever the reader is pointed at,
    so it must be refused up front, not fail later on the worker thread."""
    _stub_corpus(monkeypatch, "Vetus", translation=10, styling=10)
    monkeypatch.setattr(server.corpus_jobs, "reading_snapshot",
                        lambda: "/repo/data/corpus.db.bak-preOcrFix-20260720201447")
    res = client.post("/api/corpus/pass", json={"kind": "translate", "doc_id": 1})
    assert res.status_code == 409
    assert "live corpus.db" in res.get_json()["error"]


def test_settings_refuse_a_location_with_no_corpus(client, tmp_path, monkeypatch):
    """Validated before storing: a bad setting would otherwise break the
    corpus tab on every later page load, far from where it was typed."""
    from book_creator import settings as bc_settings

    monkeypatch.setattr(bc_settings, "SETTINGS_PATH", tmp_path / "settings.json")
    res = client.post("/api/corpus/settings", json={"repo": str(tmp_path / "nope")})
    assert res.status_code == 400
    assert bc_settings.load() == {}, "a rejected setting must not be stored"


# --------------------------------------------------------------------------- #
# Monolingual builds: one text, no translation
# --------------------------------------------------------------------------- #
def _no_build(monkeypatch):
    """Accept the payload but never actually run a build."""
    monkeypatch.setattr(server, "_run_build", lambda *a, **k: None)


@pytest.mark.parametrize("payload", [
    {"src_path": "input/x.epub", "sides": "src"},
    {"tgt_path": "input/x.epub", "sides": "tgt"},
    {"src_id": 1234, "sides": "src"},
])
def test_a_single_text_is_enough_for_a_monolingual_edition(client, monkeypatch,
                                                           payload):
    """Narrating an English EPUB you already have is not a request for a
    translation, and the build endpoint used to demand one anyway."""
    _no_build(monkeypatch)
    res = client.post("/api/build", json=payload)
    assert res.status_code == 200, res.get_json()


def test_a_dual_language_edition_still_needs_both_sides(client, monkeypatch):
    _no_build(monkeypatch)
    res = client.post("/api/build", json={"src_path": "input/x.txt",
                                          "sides": "both"})
    assert res.status_code == 400
    assert "both sides" in res.get_json()["error"]


def test_no_text_at_all_is_refused(client, monkeypatch):
    _no_build(monkeypatch)
    res = client.post("/api/build", json={"sides": "src"})
    assert res.status_code == 400
    assert "Choose a text" in res.get_json()["error"]


# --------------------------------------------------------------------------- #
# OCR and source preview
# --------------------------------------------------------------------------- #
def test_pdfs_are_offered_as_local_sources(client):
    """They were not listed at all, so a scan could not even be chosen."""
    (client.input_dir / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    (client.input_dir / "notes.md").write_text("ignore", encoding="utf-8")
    data = _get(client, "/api/local/files")[1]
    kinds = {f["kind"] for f in data["files"]}
    assert "pdf" in kinds and "md" not in kinds


def test_ocr_status_reports_availability(client):
    status = _get(client, "/api/ocr/status")[1]
    assert "available" in status and "languages" in status


def test_ocr_refuses_a_language_it_does_not_have(client, monkeypatch):
    (client.input_dir / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(server.ocr, "available", lambda: (True, ""))
    monkeypatch.setattr(server.ocr, "languages", lambda: ["eng"])
    res = client.post("/api/ocr/run", json={"path": "scan.pdf", "lang": "klingon"})
    assert res.status_code == 400
    assert "klingon" in res.get_json()["error"]


def test_ocr_says_so_when_tesseract_is_missing(client, monkeypatch):
    (client.input_dir / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(server.ocr, "available",
                        lambda: (False, "Tesseract is not installed."))
    res = client.post("/api/ocr/run", json={"path": "scan.pdf"})
    assert res.status_code == 503
    assert "Tesseract" in res.get_json()["error"]


def test_ocr_paths_are_confined_to_the_input_directory(client):
    res = client.post("/api/ocr/run", json={"path": "../../etc/passwd"})
    assert res.status_code == 400


def test_source_preview_counts_pages_of_a_text_file(client):
    (client.input_dir / "book.txt").write_text("x" * 10_000, encoding="utf-8")
    data = _get(client, "/api/local/pages?path=book.txt")[1]
    assert data["kind"] == "text" and data["pages"] > 1


def test_source_preview_returns_a_screenful(client):
    (client.input_dir / "book.txt").write_text(
        "alpha " * 2000, encoding="utf-8")
    data = _get(client, "/api/local/page/0.txt?path=book.txt")[1]
    assert data["text"].startswith("alpha")
    assert 0 < len(data["text"]) <= server._TEXT_PAGE_CHARS
