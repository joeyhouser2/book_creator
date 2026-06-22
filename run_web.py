#!/usr/bin/env python
"""Launch the book_creator web UI.

    pip install -r requirements-web.txt
    python run_web.py            # then open http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse

from webapp.server import main

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run the book_creator web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args()
    main(host=args.host, port=args.port)
