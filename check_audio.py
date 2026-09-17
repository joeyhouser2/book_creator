#!/usr/bin/env python
"""Check a finished narration for blanks and gibberish.

Examples
--------
Fast pass, no model, seconds per hour of audio -- finds silent stretches where
a sentence should be:
    python check_audio.py output/anabasis-en-audio

Full pass -- transcribes the audio and compares it to the text that was meant
to be read, catching a model that looped or mumbled:
    python check_audio.py output/subalterns-audio --asr

Then re-narrate only what was flagged (needs a narration manifest, which
builds write from now on):
    python check_audio.py output/subalterns-audio --asr --quarantine
    python make_book.py config/subalterns.yaml   # everything else comes from cache

See book_creator/narration_check.py for what each pass actually measures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows consoles default to cp1252; the report uses curly quotes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from book_creator import narration_check as nc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio_dir",
                    help="the '<slug>-audio' directory a narration wrote")
    ap.add_argument("--asr", action="store_true",
                    help="also transcribe the audio and compare it to the text "
                         "(needs faster-whisper; much slower, much stricter)")
    ap.add_argument("--model", default="small",
                    help="whisper model for the listening pass: tiny, base, "
                         "small (default), medium, large-v3")
    ap.add_argument("--device", default="auto",
                    help="cuda | cpu | auto (default)")
    ap.add_argument("--lang", default=None,
                    help="force the recognizer's language (it/el/en/...). "
                         "Leave unset for a bilingual book: whisper then picks "
                         "per segment, which is what an interleaved narration "
                         "needs.")
    ap.add_argument("--min-gap", type=float, default=nc.DEFAULT_GAP,
                    help=f"silence this long counts as a blank "
                         f"(default {nc.DEFAULT_GAP}s)")
    ap.add_argument("--min-similarity", type=float, default=0.45,
                    help="below this much overlap with the text, a reading is "
                         "flagged as a mismatch (default 0.45)")
    ap.add_argument("--quarantine", action="store_true",
                    help="move the flagged utterances out of the TTS cache so "
                         "the next build re-narrates exactly those")
    ap.add_argument("--engine", default="chatterbox",
                    help="TTS engine whose cache --quarantine should prune")
    ap.add_argument("-o", "--out", default=None,
                    help="where to write the report "
                         "(default: <audio_dir>/narration-check.md)")
    args = ap.parse_args(argv)

    try:
        report = nc.check(args.audio_dir, asr=args.asr, model=args.model,
                          device=args.device, min_gap=args.min_gap,
                          min_similarity=args.min_similarity, lang=args.lang)
    except nc.NarrationCheckError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out \
        else Path(args.audio_dir) / "narration-check.md"
    out.write_text(nc.format_report(report), encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=1),
        encoding="utf-8")

    print()
    print(nc.format_report(report))
    print(f"Report: {out}")

    if args.quarantine:
        nc.quarantine(report, engine=args.engine)

    # Exit 1 when something was flagged, so this can gate a script.
    return 1 if report.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
