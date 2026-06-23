"""Optional text cleanup applied to segments before alignment.

Some public-domain translations prepend an inline section/chapter marker to a
sentence — e.g. the McDevitte Caesar has "I.--All Gaul...", "XLIX.--Perceiving...".
These appear on only one side, so they add noise to the parallel text. We strip
them with a deliberately strict pattern (numeral + period + dash) so ordinary
prose — a sentence that merely starts with "I" or an em-dash — is left alone.
"""

from __future__ import annotations

import re

# A leading section marker: roman/arabic numeral, a period, then a dash run.
# The required period after the numeral keeps this from matching "I — ...".
_SECTION_MARKER = re.compile(r"^\s*(?:[IVXLCDM]{1,7}|\d{1,3})\.\s*(?:--|—|–)\s*")

# Obvious transcription/boilerplate lines that can leak past range selection.
_JUNK = re.compile(r"^\s*(produced by|transcribed|prepared by|end of\b|\*\*\*)", re.I)


def clean_segment(text: str) -> str:
    return _SECTION_MARKER.sub("", text, count=1).strip()


def clean_segments(segments: list[str]) -> list[str]:
    out = []
    for s in segments:
        if _JUNK.match(s):
            continue
        cleaned = clean_segment(s)
        if cleaned:
            out.append(cleaned)
    return out
