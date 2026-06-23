"""Reference translation server — implement this contract in your model's repo.

book_creator's HTTPTranslator (book_creator/translators.py) calls an endpoint
that speaks this exact JSON contract. Run one server per language (Latin, Greek),
then point book_creator at them:

    # config.yaml
    translators:
      la:  { url: "http://localhost:8001/translate" }
      grc: { url: "http://localhost:8002/translate" }

or programmatically:

    from book_creator import translators
    translators.register("la", translators.HTTPTranslator(
        "http://localhost:8001/translate", src_lang="la"))

Contract
--------
POST /translate
  request  : {"src_lang": "la", "texts": ["Gallia est...", "..."]}
  response : {"translations": ["All Gaul is...", "..."]}   # same length & order

The translations only need to be good enough to MATCH sentences against the
existing English edition — rough is fine. Run with:

    pip install flask
    python examples/translator_server.py --port 8001
"""

from __future__ import annotations

import argparse

from flask import Flask, jsonify, request

app = Flask(__name__)


def translate_batch(texts: list[str], src_lang: str) -> list[str]:
    """Replace this body with a call to your trained model.

    Must return one English string per input, in the same order.
    """
    # --- placeholder: echoes the input so the plumbing can be tested ---
    # Example real implementation:
    #   return MODEL.generate(texts, src_lang=src_lang)
    return [f"[{src_lang}] {t}" for t in texts]


@app.route("/translate", methods=["POST"])
def translate():
    payload = request.get_json(force=True)
    texts = payload.get("texts", [])
    src_lang = payload.get("src_lang", "")
    return jsonify({"translations": translate_batch(texts, src_lang)})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    app.run(host=args.host, port=args.port)
