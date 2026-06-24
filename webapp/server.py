"""Flask app: search Gutenberg, queue builds, stream progress, preview pages."""

from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import yaml

from book_creator import fetch, fonts, segment
from book_creator.model import BookSpec, CopyrightSpec, CoverSpec, DecorSpec, FontSpec
from book_creator.pipeline import build_book

from . import gutendex, preview

app = Flask(__name__, static_folder="static", template_folder="templates")

OUTPUT_DIR = "output"

# In-memory job registry. Single-user local app, so a dict + lock is plenty.
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


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


@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    language = request.args.get("lang") or None
    page = int(request.args.get("page", 1))
    if not query:
        return jsonify({"count": 0, "results": [], "has_next": False})
    try:
        return jsonify(gutendex.search(query, language, page))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _range(v) -> tuple[int, int] | None:
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(v):
        return (int(v[0]), int(v[1]))
    return None


def _spec_from_payload(p: dict) -> BookSpec:
    trim = p.get("trim", [6.0, 9.0])
    decor = p.get("decorations", {}) or {}
    return BookSpec(
        title=p.get("title", "Untitled"),
        author=p.get("author", "Unknown"),
        src_lang=p.get("src_lang", "la"),
        tgt_lang=p.get("tgt_lang", "en"),
        src_gutenberg_id=p.get("src_id"),
        tgt_gutenberg_id=p.get("tgt_id"),
        src_path=p.get("src_path"),
        tgt_path=p.get("tgt_path"),
        mode=p.get("mode", "prose"),
        aligner=p.get("aligner", "auto"),
        src_range=_range(p.get("src_range")),
        tgt_range=_range(p.get("tgt_range")),
        first=p.get("first", "src"),
        trim=(float(trim[0]), float(trim[1])),
        translation_pd_confirmed=bool(p.get("translation_pd_confirmed", False)),
        toc=bool(p.get("toc", True)),
        clean=bool(p.get("clean", True)),
        font=FontSpec(family=p.get("font", "Cardo")),
        decor=DecorSpec(
            margin=decor.get("margin", "none"),
            chapter=decor.get("chapter", "fleuron"),
            color=decor.get("color", "#8a7a5c"),
        ),
        copyright=_copyright_from(p.get("copyright")),
        cover=_cover_from(p.get("cover")),
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

    try:
        pdf_path = build_book(spec, out_dir=OUTPUT_DIR, verbose=False, on_log=on_log)
        pages = preview.page_count(pdf_path)
        cover_cand = Path(pdf_path).with_name(Path(pdf_path).stem + "-cover.pdf")
        with _lock:
            job["pdf_path"] = pdf_path
            job["pages"] = pages
            job["cover_path"] = str(cover_cand) if cover_cand.exists() else None
            job["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job["status"] = "error"
            job["error"] = str(exc)
            job["log"].append(f"✗ {exc}")
        traceback.print_exc()


@app.route("/api/build", methods=["POST"])
def api_build():
    payload = request.get_json(force=True)
    if not (payload.get("src_id") or payload.get("src_path")):
        return jsonify({"error": "Choose an original text."}), 400
    if not (payload.get("tgt_id") or payload.get("tgt_path")):
        return jsonify({"error": "Choose a translation."}), 400

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "log": [], "pages": 0,
                     "pdf_path": None, "cover_path": None, "error": None}
    spec = _spec_from_payload(payload)
    threading.Thread(target=_run_build, args=(job_id, spec), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    with _lock:
        return jsonify({
            "status": job["status"],
            "log": job["log"],
            "pages": job["pages"],
            "has_cover": bool(job.get("cover_path")),
            "error": job["error"],
        })


@app.route("/api/preview/<job_id>/<int:page>.png")
def api_preview(job_id: str, page: int):
    job = _jobs.get(job_id)
    if not job or not job.get("pdf_path"):
        return Response("not ready", status=404)
    png = preview.render_page(job["pdf_path"], page)
    return Response(png, mimetype="image/png")


@app.route("/api/download/<job_id>.pdf")
def api_download(job_id: str):
    job = _jobs.get(job_id)
    if not job or not job.get("pdf_path"):
        return Response("not ready", status=404)
    path = Path(job["pdf_path"]).resolve()
    return send_from_directory(path.parent, path.name, as_attachment=True)


@app.route("/api/cover/<job_id>.png")
def api_cover_preview(job_id: str):
    job = _jobs.get(job_id)
    if not job or not job.get("cover_path"):
        return Response("no cover", status=404)
    png = preview.render_page(job["cover_path"], 0, dpi=90)
    return Response(png, mimetype="image/png")


@app.route("/api/cover-download/<job_id>.pdf")
def api_cover_download(job_id: str):
    job = _jobs.get(job_id)
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
    book["trim"] = [float(x) for x in p.get("trim", [6.0, 9.0])]
    book["translation_pd_confirmed"] = bool(p.get("translation_pd_confirmed", False))
    book["font"] = p.get("font", "Cardo")
    if p.get("decorations"):
        book["decorations"] = p["decorations"]
    cr = {k: v for k, v in (p.get("copyright") or {}).items() if v not in ("", None)}
    if cr:
        book["copyright"] = cr
    cov = p.get("cover") or {}
    if cov.get("enabled"):
        book["cover"] = {k: v for k, v in cov.items() if k != "enabled" and v != ""}
        book["cover"].setdefault("paper", "white")
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
