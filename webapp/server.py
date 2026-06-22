"""Flask app: search Gutenberg, queue builds, stream progress, preview pages."""

from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from book_creator import fonts
from book_creator.model import BookSpec, DecorSpec, FontSpec
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
        first=p.get("first", "src"),
        trim=(float(trim[0]), float(trim[1])),
        translation_pd_confirmed=bool(p.get("translation_pd_confirmed", False)),
        font=FontSpec(family=p.get("font", "Cardo")),
        decor=DecorSpec(
            margin=decor.get("margin", "none"),
            chapter=decor.get("chapter", "fleuron"),
            color=decor.get("color", "#8a7a5c"),
        ),
    )


def _run_build(job_id: str, spec: BookSpec) -> None:
    job = _jobs[job_id]

    def on_log(msg: str) -> None:
        with _lock:
            job["log"].append(msg)

    try:
        pdf_path = build_book(spec, out_dir=OUTPUT_DIR, verbose=False, on_log=on_log)
        pages = preview.page_count(pdf_path)
        with _lock:
            job["pdf_path"] = pdf_path
            job["pages"] = pages
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
                     "pdf_path": None, "error": None}
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
