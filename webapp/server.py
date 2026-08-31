"""Flask app: search Gutenberg, queue builds, stream progress, preview pages."""

from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import yaml

from book_creator import (audio, corpus, corpus_jobs, decorations, epub_reader,
                          fetch, fonts, perseus, pg_catalog, segment)
from book_creator.model import (AudioSpec, BookSpec, CopyrightSpec, CorpusSpec,
                                CoverSpec, DecorSpec, FontSpec, PerseusSpec)
from book_creator import pipeline
from book_creator.pipeline import apply_sides, build_book

from . import gutendex, jobs as jobstore, preview

app = Flask(__name__, static_folder="static", template_folder="templates")

OUTPUT_DIR = "output"
# Local source texts live here. Everything served by the /api/local endpoints
# is confined to this directory — see _safe_input_path.
INPUT_DIR = Path("input")
LOCAL_SUFFIXES = (".txt", ".epub")

# In-memory job registry for the live view, mirrored to SQLite so a restart
# does not lose finished builds (webapp/jobs.py).
_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_store = jobstore.JobStore()


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@app.route("/api/fonts")
def api_fonts():
    """Installed font families, grouped/sorted for the picker."""
    return jsonify({"fonts": fonts.catalog()})


# --------------------------------------------------------------------------- #
# Decoration previews
# --------------------------------------------------------------------------- #
def _png_response(render, **kwargs) -> Response:
    """Rasterize a decoration to PNG and return it, or 204 if it draws nothing.

    204 rather than 404: "this style has no art" (none, rule) is a valid
    answer, not a missing resource, and the UI shows a placeholder for it.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp) / "preview.png")
        try:
            if render(out_path=out, **kwargs) is None:
                return Response(status=204)
            data = Path(out).read_bytes()
        except Exception as exc:  # noqa: BLE001 - a bad colour, mostly
            return Response(f"could not render: {exc}", status=400)
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "no-store"})


@app.route("/api/preview/ornament.png")
def api_preview_ornament():
    """The chapter ornament for a style — eleven of them, unguessable by name."""
    return _png_response(
        decorations.render_ornament_png,
        style=request.args.get("style", "fleuron"),
        color=request.args.get("color", "#8a7a5c"))


@app.route("/api/preview/margin.png")
def api_preview_margin():
    """Page-margin art on a miniature page.

    Margin styles are gutter-aware, so which side the art sits on depends on
    recto vs verso; the preview offers both rather than implying a page has
    only one appearance.
    """
    return _png_response(
        decorations.render_margin_png,
        style=request.args.get("style", "none"),
        color=request.args.get("color", "#8a7a5c"),
        corner_image=request.args.get("corner_image") or None,
        recto=request.args.get("recto", "1") != "0")


@app.route("/api/outline")
def api_outline():
    """Division outline for a Gutenberg id, so the user can pick a range."""
    gid = request.args.get("id", type=int)
    if not gid:
        return jsonify({"error": "missing id"}), 400
    try:
        text = fetch.fetch_gutenberg(gid)
        return jsonify({"divisions": segment.outline(text)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------------------------------- #
# Local source files (input/)
# --------------------------------------------------------------------------- #
def _safe_input_path(raw: str) -> Path:
    """Resolve a client-supplied path, refusing anything outside input/.

    The browser sends back a path string, so it is untrusted: without this a
    crafted request could read any file the server user can.
    """
    base = INPUT_DIR.resolve()
    p = (base / Path(raw).name).resolve() if "/" not in raw and "\\" not in raw \
        else Path(raw).resolve()
    if base != p.parent and base not in p.parents:
        raise ValueError("Path is outside the input directory.")
    if not p.is_file():
        raise ValueError(f"No such file: {p.name}")
    return p


@app.route("/api/local/files")
def api_local_files():
    """Source texts sitting in input/, for the Local files tab."""
    INPUT_DIR.mkdir(exist_ok=True)
    files = []
    for p in sorted(INPUT_DIR.iterdir()):
        if not p.is_file() or p.suffix.lower() not in LOCAL_SUFFIXES:
            continue
        files.append({
            "name": p.name,
            "path": str(p),
            "kind": p.suffix.lower().lstrip("."),
            "size_mb": round(p.stat().st_size / 1024 ** 2, 1),
        })
    return jsonify({"dir": str(INPUT_DIR.resolve()), "files": files})


@app.route("/api/local/inspect")
def api_local_inspect():
    """What a local file actually contains, before a build is spent on it.

    For an EPUB this is the quality report — a scan with 24%-accurate OCR
    looks like a book to every other part of the pipeline, and the only place
    to catch it is before the build starts.
    """
    try:
        p = _safe_input_path(request.args.get("path", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if p.suffix.lower() == ".epub":
        try:
            report = epub_reader.inspect(p).as_dict()
        except epub_reader.EpubError as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        text = p.read_text(encoding="utf-8", errors="replace")
        report = {"path": str(p), "documents": 1, "images": 0,
                  "characters": len(text),
                  "size_mb": round(p.stat().st_size / 1024 ** 2, 1),
                  "chars_per_document": len(text), "ocr_accuracy": None,
                  "ocr_pages": 0, "warnings": [], "usable": len(text) > 100}
    return jsonify(report)


@app.route("/api/local/outline")
def api_local_outline():
    """Division outline for a local file, so the range picker works there too."""
    try:
        p = _safe_input_path(request.args.get("path", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        text = fetch.load_text(path=str(p))
        return jsonify({"divisions": segment.outline(
            text, mode=request.args.get("mode", "prose"))})
    except (epub_reader.EpubError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------- #
# Perseus (the classical canon, original + human translation)
# --------------------------------------------------------------------------- #
@app.route("/api/perseus/status")
def api_perseus_status():
    return jsonify(perseus.status())


@app.route("/api/perseus/build", methods=["POST"])
def api_perseus_build():
    try:
        return jsonify(perseus.build(
            refresh=bool((request.get_json(silent=True) or {}).get("refresh"))))
    except perseus.PerseusError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/perseus/search")
def api_perseus_search():
    try:
        return jsonify(perseus.search(
            request.args.get("q", ""),
            language=request.args.get("lang") or None,
            page=max(1, int(request.args.get("page", 1)))))
    except perseus.PerseusError as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/perseus/work/<path:work_id>")
def api_perseus_work(work_id: str):
    """Metadata plus a preview of the first few aligned sections."""
    try:
        meta = perseus.get(work_id)
        src, tgt, _ = perseus.fetch_pair(work_id)
        pairs = perseus.pair_divisions(src, tgt)
    except perseus.PerseusError as exc:
        return jsonify({"error": str(exc)}), 404

    tops = list(dict.fromkeys(s.top for s, _ in pairs))
    return jsonify({
        "work": meta,
        "sections": len(pairs),
        "divisions": [{"index": i, "title": f"Book {t}", "ref": t}
                      for i, t in enumerate(tops, start=1)],
        "sample": [{"ref": s.ref, "src": s.text[:400], "tgt": t.text[:400]}
                   for s, t in pairs[:8]],
    })


# --------------------------------------------------------------------------- #
# Latin corpus (the sibling `latin` repo's pre-aligned corpus.db)
# --------------------------------------------------------------------------- #
@app.route("/api/corpus/status")
def api_corpus_status():
    """Whether the corpus is reachable, and how big it is."""
    try:
        db = corpus.find_db()
    except corpus.CorpusError as exc:
        return jsonify({"available": False, "error": str(exc)})
    with corpus.connect(str(db)) as conn:
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return jsonify({"available": True, "path": str(db), "documents": docs})


@app.route("/api/corpus/facets")
def api_corpus_facets():
    """Author / genre / period / stage picklists — 13k works is too many to
    find anything in by substring alone."""
    try:
        return jsonify(corpus.facets())
    except corpus.CorpusError as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/corpus/search")
def api_corpus_search():
    def _int(name):
        raw = request.args.get(name)
        return int(raw) if raw not in (None, "") else None

    try:
        return jsonify(corpus.search_documents(
            request.args.get("q", ""),
            language=request.args.get("lang") or None,
            stage=request.args.get("stage") or None,
            author=request.args.get("author") or None,
            genre=request.args.get("genre") or None,
            century_from=_int("century_from"),
            century_to=_int("century_to"),
            translated_only=request.args.get("translated", "1") != "0",
            styled_only=request.args.get("styled", "0") == "1",
            needs=request.args.get("needs") or None,
            limit=40,
            offset=(max(1, int(request.args.get("page", 1))) - 1) * 40,
        ))
    except corpus.CorpusError as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/corpus/doc/<int:doc_id>")
def api_corpus_doc(doc_id: int):
    """Metadata, section outline, and a preview of the aligned pairs."""
    styled = request.args.get("styled", "1") != "0"
    strip = request.args.get("strip", "1") != "0"
    try:
        with corpus.connect() as conn:
            doc = corpus.document(doc_id, conn=conn)
            return jsonify({
                "doc": doc.as_dict(),
                "sections": corpus.outline(doc_id, conn=conn),
                "sample": corpus.sample(doc_id, limit=10, prefer_styled=styled,
                                        strip_markup=strip, conn=conn),
                "note": corpus.source_note(doc),
            })
    except corpus.CorpusError as exc:
        return jsonify({"error": str(exc)}), 404


# --------------------------------------------------------------------------- #
# Corpus passes: translate / victorianize a work that is not finished yet.
#
# These are the only operations here that *write* to the corpus, and they do it
# by driving the latin repo's own scripts in a subprocess — see
# book_creator/corpus_jobs.py for why it is done that way. They share the build
# job registry, so /api/status/<id> and /api/cancel/<id> work on them unchanged.
# --------------------------------------------------------------------------- #
@app.route("/api/corpus/pass/status")
def api_corpus_pass_status():
    """Whether passes can be run, and on which GPU."""
    return jsonify(corpus_jobs.status())


def _run_corpus_pass(job_id: str, kind: str, doc_id: int, opts: dict) -> None:
    job = _jobs[job_id]

    def on_log(msg: str) -> None:
        with _lock:
            job["log"].append(msg)
        _store.save(job_id, job)

    def on_progress(done: int, total: int, info: dict | None = None) -> None:
        with _lock:
            job["progress"] = {"done": done, "total": total,
                               "percent": round(100 * done / max(1, total)),
                               **(info or {})}
        _store.save(job_id, job)

    try:
        result = corpus_jobs.run(kind, doc_id, opts=opts, on_log=on_log,
                                 on_progress=on_progress,
                                 should_stop=lambda: job.get("cancel", False))
        verb = "Translated" if kind == "translate" else "Stylized"
        with _lock:
            job["artifacts"]["segments"] = result["segments"]
            job["status"] = "cancelled" if result["cancelled"] else "done"
            job["log"].append(f"✓ {verb} {result['segments']:,} segment(s).")
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job["status"] = "error"
            job["error"] = str(exc)
            job["log"].append(f"✗ {exc}")
        traceback.print_exc()
    finally:
        _store.save(job_id, job, force=True)


@app.route("/api/corpus/pass", methods=["POST"])
def api_corpus_pass():
    payload = request.get_json(force=True)
    kind = payload.get("kind")
    if kind not in ("translate", "stylize"):
        return jsonify({"error": "kind must be 'translate' or 'stylize'"}), 400
    try:
        doc_id = int(payload.get("doc_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "doc_id is required"}), 400

    # Name the job after the work, so the jobs list reads as history rather
    # than a row of anonymous document ids.
    try:
        with corpus.connect() as conn:
            doc = corpus.document(doc_id, conn=conn)
    except corpus.CorpusError as exc:
        return jsonify({"error": str(exc)}), 404
    verb = "Translate" if kind == "translate" else "Victorianize"
    title = f"{verb}: {doc.title[:60]}"

    # Refuse work that has nothing to do rather than spending a model load
    # discovering it — the scripts would exit cleanly having done nothing.
    pending = doc.pending_translation if kind == "translate" else doc.pending_styling
    if not pending:
        return jsonify({"error": f"Nothing to do — {doc.title[:60]} has no "
                                 f"segments awaiting this pass."}), 400

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "log": [], "pages": 0, "title": title,
                     "kind": f"corpus-{kind}", "doc_id": doc_id,
                     "pdf_path": None, "cover_path": None, "error": None,
                     "progress": {"done": 0, "total": pending, "percent": 0},
                     "artifacts": {}, "cancel": False}
    _store.create(job_id, title)
    threading.Thread(target=_run_corpus_pass,
                     args=(job_id, kind, doc_id, payload.get("opts") or {}),
                     daemon=True).start()
    return jsonify({"job_id": job_id, "pending": pending})


# --------------------------------------------------------------------------- #
# Audiobook
# --------------------------------------------------------------------------- #
@app.route("/api/audio/engines")
def api_audio_engines():
    """Registered TTS engines, CUDA devices, and any narrator clips on hand."""
    info = audio.devices()
    return jsonify({"engines": audio.catalog(),
                    "voices": audio.voice_catalog(), **info})


@app.route("/api/audio/estimate", methods=["POST"])
def api_audio_estimate():
    """How long a narration would run, before committing the GPU to it.

    A corpus work is already aligned, and a Perseus work is anchored on its
    citation refs, so both can be priced in seconds. A Gutenberg pair or a
    local file cannot: getting to beads means fetching and aligning two whole
    editions, which is the build itself.
    """
    p = request.get_json(force=True)
    sides = p.get("sides", "both")
    spec = _audio_from(p.get("audio"))
    spec.first = p.get("first", "src")

    if p.get("perseus_id"):
        # Reuse the build's own loader so the bead count is the real one,
        # forcing the cheap aligner — an estimate does not warrant loading
        # LaBSE, and the difference in bead count is immaterial.
        book = BookSpec(title="", author="Unknown", src_lang="", sides=sides,
                        aligner="gale-church",
                        perseus=PerseusSpec(
                            work_id=p["perseus_id"],
                            division_range=_range(p.get("perseus_range"))))
        try:
            chapters = pipeline._chapters_from_perseus(book, lambda _m: None)
        except Exception as exc:  # noqa: BLE001 - network or malformed TEI
            return jsonify({"error": str(exc)}), 502
        chapters = apply_sides(chapters, sides, lambda _m: None)
        return jsonify({"estimate": audio.estimate(
            chapters, spec=spec, src_lang=book.src_lang,
            tgt_lang=p.get("tgt_lang", "en"))})

    if not p.get("corpus_id"):
        return jsonify({"estimate": None,
                        "note": "Available for corpus and Perseus works. A "
                                "Gutenberg pair or local file has to be fetched "
                                "and aligned first, which is the build itself."})
    try:
        load = corpus.load_chapters(
            int(p["corpus_id"]),
            section_range=_range(p.get("corpus_range")),
            prefer_styled=bool(p.get("prefer_styled", True)),
            skip_untranslated=sides != "src",
            strip_markup=bool(p.get("strip_markup", True)))
    except corpus.CorpusError as exc:
        return jsonify({"error": str(exc)}), 404
    # A monolingual book is a monolingual audiobook — roughly half the runtime,
    # which is the main thing the estimate is for.
    chapters = apply_sides(load.chapters, sides, lambda _m: None)
    return jsonify({"estimate": audio.estimate(
        chapters, spec=spec, src_lang=load.doc.language,
        tgt_lang=p.get("tgt_lang", "en"))})


@app.route("/api/audio/<job_id>.<ext>")
def api_audio_file(job_id: str, ext: str):
    """Stream (or download) the assembled audiobook for a finished job."""
    job = _get_job(job_id)
    result = (job or {}).get("artifacts", {}).get("audio") or {}
    path = result.get("book")
    if not path or not Path(path).exists():
        return Response("no audio", status=404)
    p = Path(path).resolve()
    return send_from_directory(p.parent, p.name,
                               as_attachment=request.args.get("dl") == "1")


@app.route("/api/catalog/status")
def api_catalog_status():
    """Whether the offline Gutenberg catalog is indexed, and how stale."""
    return jsonify(pg_catalog.status())


@app.route("/api/catalog/build", methods=["POST"])
def api_catalog_build():
    """Fetch/refresh the offline catalog on demand."""
    try:
        return jsonify(pg_catalog.build(
            refresh=bool((request.get_json(silent=True) or {}).get("refresh"))))
    except pg_catalog.CatalogError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    language = request.args.get("lang") or None
    page = int(request.args.get("page", 1))
    if not query:
        return jsonify({"count": 0, "results": [], "has_next": False})
    try:
        # Falls back to the local catalog when Gutendex is down, so a
        # third-party outage does not take the Gutenberg tab with it.
        return jsonify(fetch.search_gutenberg(query, language, page))
    except Exception as exc:  # noqa: BLE001 - both sources failed
        return jsonify({"error": str(exc)}), 503


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _range(v) -> tuple[int, int] | None:
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(v):
        return (int(v[0]), int(v[1]))
    return None


def _audio_from(a) -> AudioSpec:
    a = a or {}
    voice = a.get("voice") or None
    return AudioSpec(
        enabled=bool(a.get("enabled", False)),
        engine=a.get("engine", "chatterbox"),
        device=a.get("device") or audio.best_device(),
        src_voice=a.get("src_voice") or voice,
        tgt_voice=a.get("tgt_voice") or voice,
        pause_within=float(a.get("pause_within", 0.45)),
        pause_bead=float(a.get("pause_bead", 0.9)),
        pause_chapter=float(a.get("pause_chapter", 1.5)),
        announce_chapters=bool(a.get("announce_chapters", True)),
        format=a.get("format", "m4b"),
        max_beads=int(a["max_beads"]) if a.get("max_beads") else None,
    )


def _corpus_from(p: dict) -> CorpusSpec:
    """A corpus source overrides the Gutenberg ids when a doc id is present."""
    if not p.get("corpus_id"):
        return CorpusSpec()
    return CorpusSpec(
        doc_id=int(p["corpus_id"]),
        section_range=_range(p.get("corpus_range")),
        prefer_styled=bool(p.get("prefer_styled", True)),
        skip_untranslated=bool(p.get("skip_untranslated", True)),
        strip_markup=bool(p.get("strip_markup", True)),
    )


def _spec_from_payload(p: dict) -> BookSpec:
    trim = p.get("trim", [6.0, 9.0])
    decor = p.get("decorations", {}) or {}
    # A corpus document and a Perseus work each supply both sides and their
    # own metadata, so title/author/language are filled in at build time.
    from_corpus = bool(p.get("corpus_id") or p.get("perseus_id"))
    return BookSpec(
        # A corpus document carries its own title/author/language; leave them
        # blank so the pipeline fills them in unless the user typed something.
        title=p.get("title") or ("" if from_corpus else "Untitled"),
        author=p.get("author") or "Unknown",
        src_lang=p.get("src_lang") or ("" if from_corpus else "la"),
        tgt_lang=p.get("tgt_lang", "en"),
        corpus=_corpus_from(p),
        perseus=PerseusSpec(
            work_id=p.get("perseus_id") or None,
            division_range=_range(p.get("perseus_range"))),
        audio=_audio_from(p.get("audio")),
        src_gutenberg_id=p.get("src_id"),
        tgt_gutenberg_id=p.get("tgt_id"),
        src_path=p.get("src_path"),
        tgt_path=p.get("tgt_path"),
        mode=p.get("mode", "prose"),
        aligner=p.get("aligner", "auto"),
        src_range=_range(p.get("src_range")),
        tgt_range=_range(p.get("tgt_range")),
        first=p.get("first", "src"),
        sides=p.get("sides", "both"),
        trim=(float(trim[0]), float(trim[1])),
        translation_pd_confirmed=bool(p.get("translation_pd_confirmed", False)),
        toc=bool(p.get("toc", True)),
        clean=bool(p.get("clean", True)),
        font=FontSpec(family=p.get("font", "Cardo")),
        decor=DecorSpec(
            margin=decor.get("margin", "none"),
            chapter=decor.get("chapter", "fleuron"),
            bead_separator=decor.get("bead_separator", "none"),
            color=decor.get("color", "#8a7a5c"),
            corner_image=decor.get("corner_image") or None,
            chapter_image=decor.get("chapter_image") or None,
            opener_font=decor.get("opener_font") or None,
        ),
        copyright=_copyright_from(p.get("copyright")),
        cover=_cover_from(p.get("cover")),
        epub=bool(p.get("epub", False)),
        audio_only=bool(p.get("audio_only", False)),
    )


def _copyright_from(cr) -> CopyrightSpec:
    cr = cr or {}
    return CopyrightSpec(
        enabled=bool(cr.get("enabled", True)),
        publisher=cr.get("publisher", ""),
        holder=cr.get("holder", ""),
        year=int(cr["year"]) if cr.get("year") else None,
        isbn=str(cr.get("isbn", "")),
        translator=cr.get("translator", ""),
    )


def _cover_from(cov) -> CoverSpec:
    cov = cov or {}
    return CoverSpec(
        enabled=bool(cov.get("enabled", False)),
        paper=cov.get("paper", "white"),
        blurb=cov.get("blurb", ""),
    )


def _run_build(job_id: str, spec: BookSpec) -> None:
    job = _jobs[job_id]

    def on_log(msg: str) -> None:
        with _lock:
            job["log"].append(msg)
        _store.save(job_id, job)

    def on_progress(done: int, total: int) -> None:
        with _lock:
            job["progress"] = {"done": done, "total": total,
                               "percent": round(100 * done / max(1, total))}
        _store.save(job_id, job)

    def should_stop() -> bool:
        return job.get("cancel", False)

    artifacts: dict = {}
    job["artifacts"] = artifacts
    try:
        build_book(spec, out_dir=OUTPUT_DIR, verbose=False,
                   on_log=on_log, artifacts=artifacts,
                   on_progress=on_progress, should_stop=should_stop)
        # An audio-only build renders no PDF, so there is nothing to paginate
        # or preview — the point of it is to leave an existing PDF untouched.
        pdf_path = artifacts.get("pdf")
        pages = preview.page_count(pdf_path) if pdf_path else 0
        cover_cand = (Path(pdf_path).with_name(Path(pdf_path).stem + "-cover.pdf")
                      if pdf_path else None)
        with _lock:
            job["pdf_path"] = pdf_path
            job["pages"] = pages
            job["title"] = spec.title or job["title"]
            job["cover_path"] = (str(cover_cand)
                                 if cover_cand and cover_cand.exists() else None)
            if cover_cand and cover_cand.exists():
                artifacts.setdefault("cover", str(cover_cand))
            job["status"] = "cancelled" if job.get("cancel") else "done"
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job["status"] = "error"
            job["error"] = str(exc)
            job["log"].append(f"✗ {exc}")
        traceback.print_exc()
    finally:
        # Always force this one: a finished build left showing as running
        # because its write was throttled is the one genuinely misleading state.
        _store.save(job_id, job, force=True)


@app.route("/api/build", methods=["POST"])
def api_build():
    payload = request.get_json(force=True)
    # A corpus document is a complete parallel text on its own; the Gutenberg
    # path needs an edition on each side.
    if payload.get("audio_only"):
        payload.setdefault("audio", {})["enabled"] = True
    if not (payload.get("corpus_id") or payload.get("perseus_id")):
        if not (payload.get("src_id") or payload.get("src_path")):
            return jsonify({"error": "Choose an original text."}), 400
        if not (payload.get("tgt_id") or payload.get("tgt_path")):
            return jsonify({"error": "Choose a translation."}), 400

    job_id = uuid.uuid4().hex[:12]
    spec = _spec_from_payload(payload)
    title = spec.title or payload.get("title") or f"corpus #{spec.corpus.doc_id}"
    _jobs[job_id] = {"status": "running", "log": [], "pages": 0, "title": title,
                     "kind": "build",
                     "pdf_path": None, "cover_path": None, "error": None,
                     "progress": None, "artifacts": {}, "cancel": False}
    _store.create(job_id, title)
    threading.Thread(target=_run_build, args=(job_id, spec), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/jobs")
def api_jobs():
    """Recent builds, so a finished book survives a server restart."""
    return jsonify({"jobs": _store.recent(25)})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id: str):
    """Ask a running job to stop at its next safe point.

    Only the audio stage of a build checks this — everything before it is fast
    enough that stopping mid-way would just lose work. A corpus translate or
    stylize pass checks it too, and stops after the current chunk: those commit
    as they go, so what has already been written to the corpus is kept and
    re-running continues from there.
    """
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    job["cancel"] = True
    return jsonify({"cancelling": True})


def _get_job(job_id: str) -> dict | None:
    """The live job if it is still in memory, else the persisted record.

    After a restart the process has no jobs but the files are still on disk,
    so a bookmarked preview or download link keeps working.
    """
    job = _jobs.get(job_id)
    if job:
        return job
    stored = _store.get(job_id)
    if not stored:
        return None
    art = stored.get("artifacts") or {}
    stored.setdefault("pdf_path", art.get("pdf"))
    stored.setdefault("cover_path", art.get("cover"))
    return stored


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    with _lock:
        art = job.get("artifacts") or {}
        return jsonify({
            "status": job["status"],
            "kind": job.get("kind", "build"),
            "segments": art.get("segments"),
            "log": job["log"],
            "pages": job["pages"],
            "has_cover": bool(job.get("cover_path") or art.get("cover")),
            "has_pdf": bool(art.get("pdf") or job.get("pdf_path")),
            "progress": job.get("progress"),
            "audio": art.get("audio"),
            "epub": bool(art.get("epub")),
            "error": job["error"],
        })


@app.route("/api/preview/<job_id>/<int:page>.png")
def api_preview(job_id: str, page: int):
    job = _get_job(job_id)
    if not job or not job.get("pdf_path"):
        return Response("not ready", status=404)
    png = preview.render_page(job["pdf_path"], page)
    return Response(png, mimetype="image/png")


@app.route("/api/download/<job_id>.pdf")
def api_download(job_id: str):
    job = _get_job(job_id)
    if not job or not job.get("pdf_path"):
        return Response("not ready", status=404)
    path = Path(job["pdf_path"]).resolve()
    return send_from_directory(path.parent, path.name, as_attachment=True)


@app.route("/api/cover/<job_id>.png")
def api_cover_preview(job_id: str):
    job = _get_job(job_id)
    if not job or not job.get("cover_path"):
        return Response("no cover", status=404)
    png = preview.render_page(job["cover_path"], 0, dpi=90)
    return Response(png, mimetype="image/png")


@app.route("/api/cover-download/<job_id>.pdf")
def api_cover_download(job_id: str):
    job = _get_job(job_id)
    if not job or not job.get("cover_path"):
        return Response("no cover", status=404)
    path = Path(job["cover_path"]).resolve()
    return send_from_directory(path.parent, path.name, as_attachment=True)


def _payload_to_yaml(p: dict) -> dict:
    """Translate a build payload into a config/books.yaml entry."""
    book: dict = {"title": p.get("title", "Untitled"),
                  "author": p.get("author", "Unknown"),
                  "src_lang": p.get("src_lang", "la"),
                  "tgt_lang": p.get("tgt_lang", "en")}
    if p.get("corpus_id"):
        book["corpus"] = {"doc_id": int(p["corpus_id"]),
                          "prefer_styled": bool(p.get("prefer_styled", True)),
                          "strip_markup": bool(p.get("strip_markup", True))}
        if p.get("corpus_range"):
            book["corpus"]["section_range"] = list(p["corpus_range"])
    if p.get("perseus_id"):
        book["perseus"] = {"work_id": p["perseus_id"]}
        if p.get("perseus_range"):
            book["perseus"]["division_range"] = list(p["perseus_range"])
    if p.get("src_id"):
        book["src_gutenberg_id"] = p["src_id"]
    if p.get("tgt_id"):
        book["tgt_gutenberg_id"] = p["tgt_id"]
    book["mode"] = p.get("mode", "prose")
    book["aligner"] = p.get("aligner", "auto")
    if p.get("src_range"):
        book["src_range"] = list(p["src_range"])
    if p.get("tgt_range"):
        book["tgt_range"] = list(p["tgt_range"])
    book["first"] = p.get("first", "src")
    if p.get("sides", "both") != "both":
        book["sides"] = p["sides"]
    book["trim"] = [float(x) for x in p.get("trim", [6.0, 9.0])]
    book["translation_pd_confirmed"] = bool(p.get("translation_pd_confirmed", False))
    book["font"] = p.get("font", "Cardo")
    if p.get("decorations"):
        # Drop unset/default fields so a saved entry stays readable.
        dec = {k: v for k, v in p["decorations"].items() if v not in (None, "")}
        if dec.get("bead_separator") == "none":
            dec.pop("bead_separator")
        if dec:
            book["decorations"] = dec
    cr = {k: v for k, v in (p.get("copyright") or {}).items() if v not in ("", None)}
    if cr:
        book["copyright"] = cr
    cov = p.get("cover") or {}
    if cov.get("enabled"):
        book["cover"] = {k: v for k, v in cov.items() if k != "enabled" and v != ""}
        book["cover"].setdefault("paper", "white")
    aud = p.get("audio") or {}
    if aud.get("enabled"):
        book["audio"] = {k: v for k, v in aud.items()
                         if k != "enabled" and v not in ("", None)}
        book["audio"]["enabled"] = True
    if p.get("epub"):
        book["epub"] = True
    return book


@app.route("/api/save-config", methods=["POST"])
def api_save_config():
    payload = request.get_json(force=True)
    target = Path(payload.get("_config_path") or "config/books.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if target.exists():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        data = {"books": loaded} if isinstance(loaded, list) else loaded
    data.setdefault("books", [])
    data["books"].append(_payload_to_yaml(payload))
    target.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return jsonify({"saved": str(target), "count": len(data["books"])})


def main(host: str = "127.0.0.1", port: int = 5000) -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    print(f"book_creator UI -> http://{host}:{port}")
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
