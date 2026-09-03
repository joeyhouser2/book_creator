"""Read text off page images with Tesseract, for scans that have no text layer.

Two different files arrive needing this. A PDF of a scanned book is a stack of
pictures: `get_text()` returns nothing and every later stage sees an empty
book. An EPUB from a scanning project usually *has* a text layer, but one
produced by someone else's OCR at whatever quality they managed -- Internet
Archive scans routinely declare their own accuracy at around 24%, and
`epub_reader.inspect` already surfaces that.

So this module does two jobs: it says whether a file needs OCR, and it runs
it. Re-OCRing a file that already has a bad text layer is a legitimate use,
not an error, which is why `force` exists.

Tesseract is an external binary, like LilyPond in music.py: it is not bundled
and not installed by this project. When it is missing, everything here reports
that clearly and nothing else in the pipeline changes behaviour.

Output is cached under `cache/ocr/`, keyed by file content and settings, since
a 920-page book is about twenty minutes of work and nobody should pay that
twice.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path("cache") / "ocr"
# Traineddata assembled here so languages from different installs can be used
# together: Tesseract takes a single --tessdata-dir, and this machine keeps
# `eng` with the binary and `lat`/`grc` in the sibling latin repo.
TESSDATA_CACHE = Path("cache") / "tessdata"

# Where to look for extra .traineddata beyond Tesseract's own directory.
_EXTRA_TESSDATA = (
    "../latin/models/tessdata",
    "~/Documents/GitHub/latin/models/tessdata",
)

# Below this many characters per page, a PDF page is treated as having no
# usable text layer. Real pages of prose run to thousands; a scan yields the
# odd stray character from a header or a watermark.
_TEXT_LAYER_FLOOR = 120

_SUPPORTED = (".pdf", ".epub")


class OcrError(RuntimeError):
    """OCR could not run (no Tesseract, unreadable file, no such language)."""


# --------------------------------------------------------------------------- #
# Finding Tesseract and its languages
# --------------------------------------------------------------------------- #
def tesseract_exe() -> str | None:
    """The Tesseract binary, or None. TESSERACT_EXE overrides the search."""
    override = os.environ.get("TESSERACT_EXE")
    if override and Path(override).is_file():
        return override
    found = shutil.which("tesseract")
    if found:
        return found
    for guess in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  "/usr/bin/tesseract", "/usr/local/bin/tesseract",
                  "/opt/homebrew/bin/tesseract"):
        if Path(guess).is_file():
            return guess
    return None


def _own_tessdata(exe: str) -> Path | None:
    """Tesseract's own traineddata directory, asked of Tesseract itself."""
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    # First line is: List of available languages in "<dir>" (N):
    first = (out.stdout or out.stderr or "").splitlines()[:1]
    if first and '"' in first[0]:
        cand = Path(first[0].split('"')[1])
        if cand.is_dir():
            return cand
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        p = Path(prefix)
        return p if p.is_dir() else None
    return None


def _tessdata_sources(exe: str) -> list[Path]:
    dirs: list[Path] = []
    own = _own_tessdata(exe)
    if own:
        dirs.append(own)
    for raw in _EXTRA_TESSDATA:
        p = Path(raw).expanduser()
        if p.is_dir():
            dirs.append(p)
    return dirs


def tessdata_dir() -> Path | None:
    """A directory holding every traineddata this machine can offer.

    Built by copying, not symlinking: a symlink needs privilege on Windows,
    and these files change about never. Copies are refreshed only when the
    source is newer, so this costs nothing after the first call.
    """
    exe = tesseract_exe()
    if not exe:
        return None
    sources = _tessdata_sources(exe)
    if not sources:
        return None
    if len(sources) == 1:
        return sources[0]

    TESSDATA_CACHE.mkdir(parents=True, exist_ok=True)
    for src in sources:
        for f in src.glob("*.traineddata"):
            dst = TESSDATA_CACHE / f.name
            if not dst.exists() or f.stat().st_mtime > dst.stat().st_mtime:
                try:
                    shutil.copy2(f, dst)
                except OSError:
                    continue
    return TESSDATA_CACHE


def languages() -> list[str]:
    """Language codes available, across every traineddata directory found."""
    exe = tesseract_exe()
    if not exe:
        return []
    seen = set()
    for src in _tessdata_sources(exe):
        for f in src.glob("*.traineddata"):
            if f.stem != "osd":       # orientation detection, not a language
                seen.add(f.stem)
    return sorted(seen)


def available() -> tuple[bool, str]:
    """(usable?, reason if not) — for the UI to explain itself."""
    exe = tesseract_exe()
    if not exe:
        return False, ("Tesseract is not installed. It is a separate program: "
                       "see https://tesseract-ocr.github.io/ (or set "
                       "TESSERACT_EXE to it).")
    if not languages():
        return False, f"{exe} has no .traineddata languages installed."
    return True, ""


def status() -> dict:
    ok, reason = available()
    return {"available": ok, "error": reason, "exe": tesseract_exe(),
            "languages": languages(), "suffixes": list(_SUPPORTED)}


# --------------------------------------------------------------------------- #
# Does this file need OCR?
# --------------------------------------------------------------------------- #
@dataclass
class TextLayer:
    """What a file already offers before OCR is considered."""

    pages: int
    characters: int
    pages_with_text: int
    images: int

    @property
    def chars_per_page(self) -> int:
        return round(self.characters / self.pages) if self.pages else 0

    @property
    def needs_ocr(self) -> bool:
        """No usable text layer at all — the file is a stack of pictures."""
        return self.chars_per_page < _TEXT_LAYER_FLOOR

    def as_dict(self) -> dict:
        return {"pages": self.pages, "characters": self.characters,
                "pages_with_text": self.pages_with_text, "images": self.images,
                "chars_per_page": self.chars_per_page,
                "needs_ocr": self.needs_ocr}


def inspect_pdf(path: str | Path) -> TextLayer:
    """How much text a PDF already carries, per page."""
    import fitz

    p = Path(path)
    try:
        doc = fitz.open(str(p))
    except Exception as exc:  # noqa: BLE001 - fitz raises assorted types
        raise OcrError(f"Could not open {p.name}: {exc}") from exc
    try:
        chars = with_text = images = 0
        for page in doc:
            t = page.get_text().strip()
            chars += len(t)
            with_text += bool(t)
            images += len(page.get_images())
        return TextLayer(doc.page_count, chars, with_text, images)
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Running it
# --------------------------------------------------------------------------- #
def _run_tesseract(png: bytes, lang: str, exe: str, psm: int) -> str:
    """OCR one page image. Tesseract reads stdin and writes stdout, so no
    temporary files are needed for what can be thousands of pages."""
    cmd = [exe, "stdin", "stdout", "-l", lang, "--psm", str(psm)]
    data = tessdata_dir()
    if data:
        cmd += ["--tessdata-dir", str(data)]
    try:
        out = subprocess.run(cmd, input=png, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return ""
    except OSError as exc:
        raise OcrError(f"Could not run {exe}: {exc}") from exc
    if out.returncode != 0:
        detail = (out.stderr or b"").decode("utf-8", "replace").strip()
        raise OcrError(f"Tesseract failed: {detail[:300]}")
    return out.stdout.decode("utf-8", "replace")


def cache_path(path: str | Path, lang: str, dpi: int) -> Path:
    """Where this file's OCR lands, keyed by content and settings.

    Keyed by a hash of the bytes rather than the name: re-OCRing after
    replacing a file with a corrected scan of the same name has to miss the
    cache, or the old text is silently reused.
    """
    p = Path(path)
    h = hashlib.sha1()
    h.update(p.read_bytes() if p.stat().st_size < 64_000_000
             else f"{p.stat().st_size}{p.stat().st_mtime}".encode())
    key = f"{h.hexdigest()[:16]}-{lang}-{dpi}"
    return CACHE_DIR / f"{p.stem}-{key}.txt"


def ocr_pdf(path: str | Path, *, lang: str = "eng", dpi: int = 300,
            psm: int = 3, force: bool = False, on_log=None, on_progress=None,
            should_stop=None) -> str:
    """OCR a PDF, page by page, and return the text.

    Pages that already carry a usable text layer are kept as they are unless
    `force`, so a part-scanned book (plates OCRed, text pages digital) costs
    only the pages that need the work.
    """
    import fitz

    exe = tesseract_exe()
    if not exe:
        raise OcrError(available()[1])

    log = on_log or (lambda _m: None)
    p = Path(path)
    doc = fitz.open(str(p))
    try:
        total = doc.page_count
        log(f"• OCR {p.name}: {total} page(s) at {dpi} dpi, language '{lang}'.")
        out: list[str] = []
        ocred = kept = 0
        for i, page in enumerate(doc, start=1):
            if should_stop and should_stop():
                log("… stopped; pages done so far are kept.")
                break
            existing = page.get_text().strip()
            if existing and len(existing) >= _TEXT_LAYER_FLOOR and not force:
                out.append(existing)
                kept += 1
            else:
                png = page.get_pixmap(dpi=dpi).tobytes("png")
                out.append(_run_tesseract(png, lang, exe, psm).strip())
                ocred += 1
            if on_progress:
                on_progress(i, total)
        log(f"• OCR done: {ocred} page(s) read from the image"
            + (f", {kept} kept from the existing text layer" if kept else "")
            + ".")
        return "\n\n".join(t for t in out if t)
    finally:
        doc.close()


def ocr_epub(path: str | Path, *, lang: str = "eng", dpi: int = 300,
             psm: int = 3, on_log=None, on_progress=None,
             should_stop=None) -> str:
    """OCR the page images inside an EPUB.

    A scanned EPUB is a wrapper around a folder of page pictures, in the same
    reading order as its documents. The images are taken in manifest order,
    which for these files is the page order.
    """
    from ebooklib import epub

    exe = tesseract_exe()
    if not exe:
        raise OcrError(available()[1])

    log = on_log or (lambda _m: None)
    p = Path(path)
    try:
        book = epub.read_epub(str(p))
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"Could not read {p.name}: {exc}") from exc

    images = [it for it in book.get_items()
              if (getattr(it, "media_type", "") or "").startswith("image/")]
    images.sort(key=lambda it: it.get_name() or "")
    if not images:
        raise OcrError(
            f"{p.name} has no page images to read — if its text is already "
            "there but poor, it needs re-typesetting rather than OCR.")

    log(f"• OCR {p.name}: {len(images)} image(s) at {dpi} dpi, language '{lang}'.")
    out: list[str] = []
    for i, item in enumerate(images, start=1):
        if should_stop and should_stop():
            log("… stopped; images done so far are kept.")
            break
        try:
            text = _run_tesseract(item.get_content(), lang, exe, psm).strip()
        except OcrError:
            continue          # one unreadable image should not lose the book
        if text:
            out.append(text)
        if on_progress:
            on_progress(i, len(images))
    log(f"• OCR done: {len(out)} image(s) produced text.")
    return "\n\n".join(out)


def run(path: str | Path, *, lang: str = "eng", dpi: int = 300, psm: int = 3,
        force: bool = False, on_log=None, on_progress=None,
        should_stop=None) -> Path:
    """OCR a PDF or EPUB and write the text beside it in the cache.

    Returns the path of the text file, which `fetch` then reads in place of
    the original.
    """
    p = Path(path)
    if p.suffix.lower() not in _SUPPORTED:
        raise OcrError(f"OCR handles {', '.join(_SUPPORTED)}; {p.name} is "
                       f"neither.")
    dest = cache_path(p, lang, dpi)
    if dest.exists() and not force:
        if on_log:
            on_log(f"• Using the OCR already cached at {dest}.")
        return dest

    if p.suffix.lower() == ".pdf":
        text = ocr_pdf(p, lang=lang, dpi=dpi, psm=psm, force=force,
                       on_log=on_log, on_progress=on_progress,
                       should_stop=should_stop)
    else:
        text = ocr_epub(p, lang=lang, dpi=dpi, psm=psm, on_log=on_log,
                        on_progress=on_progress, should_stop=should_stop)

    if not text.strip():
        raise OcrError(
            f"OCR of {p.name} produced no text. If the pages are blank or the "
            f"language is wrong ('{lang}'), that is the first thing to check.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    if on_log:
        on_log(f"• OCR text written to {dest} ({len(text):,} characters).")
    return dest


def cached_for(path: str | Path) -> list[dict]:
    """Every OCR already done for this file, newest first.

    Listed rather than resolved to one, because the language and resolution
    are part of the answer: a book OCRed as Latin and again as English gives
    two different texts and the user chooses between them.
    """
    p = Path(path)
    if not CACHE_DIR.is_dir():
        return []
    out = []
    for f in CACHE_DIR.glob(f"{p.stem}-*.txt"):
        parts = f.stem.rsplit("-", 2)
        out.append({"path": str(f), "name": f.name,
                    "lang": parts[1] if len(parts) == 3 else "?",
                    "dpi": parts[2] if len(parts) == 3 else "?",
                    "characters": f.stat().st_size,
                    "modified": f.stat().st_mtime})
    return sorted(out, key=lambda d: -d["modified"])
