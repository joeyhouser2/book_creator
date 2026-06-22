"""Dynamic font discovery and registration.

Scans the fonts/ directory, groups files into families by filename, and infers
each style (regular / italic / bold). Drop a font's .ttf files into fonts/ and it
shows up automatically — in the CLI, in `register()`, and in the web UI's font
picker (via the discovered metadata).

Only embed fonts you're licensed to sell with. The curated set fetched by
download_fonts.py is all SIL Open Font License, which permits commercial embedding.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONTS_DIR = Path("fonts")

# Known families: normalized-key -> (display name, category, covers-Greek).
# Anything discovered but not listed here still works; it just lands in "other".
_META: dict[str, tuple[str, str, bool]] = {
    "cardo": ("Cardo", "serif", True),
    "ebgaramond": ("EB Garamond", "serif", True),
    "gentiumbookplus": ("Gentium Book Plus", "serif", True),
    "gentiumplus": ("Gentium Plus", "serif", True),
    "oldstandardtt": ("Old Standard", "serif", True),
    "oldstandard": ("Old Standard", "serif", True),
    "librebaskerville": ("Libre Baskerville", "serif", False),
    "imfellenglish": ("IM Fell English", "serif", False),
    "imfelldwpica": ("IM Fell DW Pica", "serif", False),
    "notoserif": ("Noto Serif", "serif", True),
    "junicode": ("Junicode", "medieval", True),
    "unifrakturmaguntia": ("UnifrakturMaguntia", "medieval", False),
    "unifrakturcook": ("UnifrakturCook", "medieval", False),
    "medievalsharp": ("MedievalSharp", "medieval", False),
    "grenzegotisch": ("Grenze Gotisch", "medieval", False),
    "pirataone": ("Pirata One", "medieval", False),
    "gfsdidot": ("GFS Didot", "greek", True),
    "gfsneohellenic": ("GFS Neohellenic", "greek", True),
    "gfsporson": ("GFS Porson", "greek", True),
}

_CATEGORY_ORDER = {"serif": 0, "medieval": 1, "greek": 2, "other": 3}

# Trailing style/weight words to peel off the end of a filename to get the
# family. Order matters: strip longest/compound suffixes first. Stripped as a
# SUFFIX (looped), not a substring, so e.g. "GentiumBookPlus" keeps its "Book".
_STYLE_SUFFIXES = [
    "bolditalic", "boldoblique", "semibolditalic", "extrabold",
    "semibold", "italic", "oblique", "bold", "medium", "light",
    "regular", "roman", "book", "display",
]


def normalize(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _strip_style_suffix(name: str) -> str:
    s = name.strip("-_ ")
    changed = True
    while changed:
        changed = False
        for suf in _STYLE_SUFFIXES:
            if s.lower().endswith(suf) and len(s) > len(suf):
                s = s[: len(s) - len(suf)].strip("-_ ")
                changed = True
                break
    return s


def _parse_filename(stem: str) -> tuple[str, str, str]:
    """(family_key, family_display, style) from a font filename stem."""
    cleaned = re.sub(r"\[.*?\]", "", stem)            # drop variable axis tags
    low = re.sub(r"[-_ ]", "", cleaned).lower()
    bold = "bold" in low
    italic = "italic" in low or "oblique" in low
    if bold and italic:
        style = "bolditalic"
    elif bold:
        style = "bold"
    elif italic:
        style = "italic"
    else:
        style = "regular"

    family = _strip_style_suffix(cleaned) or cleaned
    display = re.sub(r"[-_]+", " ", family).strip()
    return normalize(family), display, style


def _resolve(name: str | None) -> str | None:
    if not name:
        return None
    in_fonts = FONTS_DIR / name
    if in_fonts.exists():
        return str(in_fonts)
    direct = Path(name)
    return str(direct) if direct.exists() else None


def discover() -> dict[str, dict]:
    """Map family_key -> entry with files, regular/italic/bold paths, metadata."""
    reg: dict[str, dict] = {}
    if not FONTS_DIR.exists():
        return reg

    files = sorted(FONTS_DIR.glob("*.ttf")) + sorted(FONTS_DIR.glob("*.otf"))
    for path in files:
        key, disp, style = _parse_filename(path.stem)
        if not key:
            continue
        entry = reg.setdefault(key, {"key": key, "display": disp, "files": {}})
        entry["files"].setdefault(style, str(path))

    for key, entry in reg.items():
        meta = _META.get(key)
        if meta:
            entry["display"], entry["category"], entry["greek"] = meta
        else:
            entry.setdefault("category", "other")
            entry.setdefault("greek", None)
        f = entry["files"]
        entry["regular"] = (f.get("regular") or f.get("bold")
                            or f.get("italic") or next(iter(f.values()), None))
        entry["italic"] = f.get("italic") or f.get("bolditalic")
        entry["bold"] = f.get("bold") or f.get("bolditalic")
    return reg


def catalog() -> list[dict]:
    """Sorted, UI-friendly list of installed families."""
    entries = discover().values()
    out = [{
        "id": e["key"],
        "label": e["display"],
        "category": e["category"],
        "greek": e["greek"],
        "has_italic": bool(e["italic"]),
        "has_bold": bool(e["bold"]),
    } for e in entries]
    out.sort(key=lambda e: (_CATEGORY_ORDER.get(e["category"], 9), e["label"].lower()))
    return out


def _safe_register(name: str, path: str) -> None:
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, path))


def register(family: str | None, overrides: dict | None = None) -> tuple[str, str, str]:
    """Register the requested family and return (regular, italic, bold) names.

    Resolution: explicit file overrides -> discovered family -> any installed
    font -> built-in Times (which lacks Greek glyphs).
    """
    reg = discover()
    ov = overrides or {}
    entry = reg.get(normalize(family))

    reg_path = _resolve(ov.get("regular")) or (entry and entry["regular"])
    ital_path = _resolve(ov.get("italic")) or (entry and entry["italic"])
    bold_path = _resolve(ov.get("bold")) or (entry and entry["bold"])

    if not reg_path:  # fall back to any installed family
        entry = next(iter(reg.values()), None)
        if entry:
            reg_path, ital_path, bold_path = entry["regular"], entry["italic"], entry["bold"]

    if not reg_path:
        return "Times-Roman", "Times-Italic", "Times-Bold"

    base = re.sub(r"[^A-Za-z0-9]", "", entry["display"]) if entry else normalize(family)
    reg_name, ital_name, bold_name = base, f"{base}-Italic", f"{base}-Bold"
    _safe_register(reg_name, reg_path)
    _safe_register(ital_name, ital_path or reg_path)
    _safe_register(bold_name, bold_path or reg_path)
    pdfmetrics.registerFontFamily(
        base, normal=reg_name, bold=bold_name, italic=ital_name, boldItalic=bold_name,
    )
    return reg_name, ital_name, bold_name
