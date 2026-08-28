"""Musical literature: match poems to public-domain art-song settings and
typeset the piano grand staff (treble + bass clef) alongside the original
text and its translation.

Source: the OpenScore Lieder Corpus (github.com/OpenScore/Lieder), CC0
("Creative Commons Zero") MusicXML/MuseScore encodings of public-domain
lieder — the same public-domain bar this project already holds text sources
to (see model.CopyrightSpec / BookSpec.translation_pd_confirmed). Each song
is fetched as a compressed MusicXML (.mxl) and cached under cache/music/,
mirroring how fetch.py caches Gutenberg texts under cache/.

Matching: poems in a verse-mode book are numbered divisions, not
individually titled (see segment._is_heading's bare-roman-numeral case), so
we can't match on Chapter.title. Instead each registered setting carries the
poem's verified first line ("incipit"); a chapter matches when its first
source segment is a prefix-or-equal match of a registry entry's (registry
incipits are sometimes truncated versions of the real line). A few Heine
incipits repeat verbatim across different poems, so some entries also carry
a `second_line` that must additionally match — see SongSetting's docstring.

Rendering: LilyPond. `musicxml2ly` (converts MusicXML -> LilyPond source) and
`lilypond` (engraves the source to PNG) both ship with a LilyPond install,
but neither is bundled or auto-installed here — see
ensure_lilypond_available(). Proof-of-concept scope: only Schumann's
*Dichterliebe*, Op. 48 (16 songs, all setting poems from Heine's "Lyrisches
Intermezzo") is registered so far; add further composers/works to
_REGISTRIES the same way.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageChops

_RAW_BASE = "https://raw.githubusercontent.com/OpenScore/Lieder/main/scores"


@dataclass
class SongSetting:
    """One composer's setting of one poem.

    `title` is the display/caption form (OpenScore's modern spelling).
    `incipit` is the actual matching key: verified against the specific
    Gutenberg edition (pg3498, Buch der Lieder) this catalog is meant to
    pair with, which uses period orthography (e.g. "wüßtens" not
    "wüssten's") and, in one case, a genuinely different textual variant
    ("schönen Strome" not "heiligen Strome") — OpenScore's title text can't
    be matched against it directly. `second_line`, when set, additionally
    requires the chapter's second line to match: Heine reuses some opening
    lines verbatim across different poems (confirmed: "Ich hab im Traum
    geweinet" opens three separate poems here), so the first line alone
    isn't always a unique key.
    """

    composer: str          # display form, e.g. "Robert Schumann"
    composer_dir: str        # OpenScore composer path segment, e.g. "Schumann,_Robert"
    work: str                 # e.g. "Dichterliebe, Op.48"
    number: int                # song number within the work
    title: str                  # display form, for captions/logging
    incipit: str                  # verified first line, for matching
    folder: str                    # OpenScore path segment for the song directory
    mxl_file: str                   # OpenScore filename, e.g. "lc4976777.mxl"
    second_line: str | None = None   # disambiguator when the incipit repeats

    @property
    def incipit_key(self) -> str:
        return _normalize(self.incipit)

    @property
    def second_line_key(self) -> str | None:
        return _normalize(self.second_line) if self.second_line else None

    @property
    def mxl_url(self) -> str:
        segs = [self.composer_dir, self.work.replace(" ", "_"), self.folder, self.mxl_file]
        return _RAW_BASE + "/" + "/".join(urllib.parse.quote(s, safe="") for s in segs)

    @property
    def cache_name(self) -> str:
        composer_slug = re.sub(r"[^a-z0-9]+", "-", self.composer.lower()).strip("-")
        work_slug = re.sub(r"[^a-z0-9]+", "-", self.work.lower()).strip("-")
        return f"{composer_slug}-{work_slug}-{self.number:02d}.mxl"


# --- Schumann, Dichterliebe, Op. 48 (16 songs, all Heine, "Lyrisches
# Intermezzo") ------------------------------------------------------------
# folder/mxl_file confirmed live against github.com/OpenScore/Lieder;
# incipit/second_line confirmed against cache/pg3498.txt (Buch der Lieder,
# Gutenberg #3498) — both 2026-08-11. See SongSetting's docstring for why
# `incipit` sometimes differs from `title`.
def _schumann(number: int, title: str, incipit: str, folder: str, mxl_file: str,
              second_line: str | None = None) -> SongSetting:
    return SongSetting("Robert Schumann", "Schumann,_Robert", "Dichterliebe, Op.48",
                       number, title, incipit, folder, mxl_file, second_line)


_DICHTERLIEBE = [
    _schumann(1, "Im wunderschönen Monat Mai",
              "Im wunderschönen Monat Mai",
              "1_Im_wunderschönen_Monat_Mai", "lc4976777.mxl"),
    _schumann(2, "Aus meinen Tränen sprießen",
              "Aus meinen Tränen sprießen",
              "2_Aus_meinen_Tränen_sprießen", "lc4976769.mxl"),
    _schumann(3, "Die Rose, die Lilie",
              "Die Rose, die Lilie, die Taube, die Sonne",
              "3_Die_Rose,_die_Lilie", "lc4976849.mxl"),
    _schumann(4, "Wenn ich in deine Augen seh’",
              "Wenn ich in deine Augen seh",
              "4_Wenn_ich_in_deine_Augen_seh’", "lc4978368.mxl"),
    _schumann(5, "Ich will meine Seele tauchen",
              "Ich will meine Seele tauchen",
              "5_Ich_will_meine_Seele_tauchen", "lc4978373.mxl"),
    _schumann(6, "Im Rhein, im heiligen Strome",
              "Im Rhein, im schönen Strome",  # this edition's textual variant
              "6_Im_Rhein,_im_heiligen_Strome", "lc4978379.mxl"),
    _schumann(7, "Ich grolle nicht",
              "Ich grolle nicht",
              "7_Ich_grolle_nicht", "lc4978382.mxl"),
    _schumann(8, "Und wüssten’s die Blumen",
              "Und wüßtens, die Blumen, die kleinen",  # pre-1901 orthography
              "8_Und_wüssten’s_die_Blumen", "lc4978387.mxl"),
    _schumann(9, "Das ist ein Flöten und Geigen",
              "Das ist ein Flöten und Geigen",
              "9_Das_ist_ein_Flöten_und_Geigen", "lc4978390.mxl"),
    _schumann(10, "Hör’ ich das Liedchen klingen",
              "Hör ich das Liedchen klingen",
              "10_Hör’_ich_das_Liedchen_klingen", "lc5003150.mxl"),
    _schumann(11, "Ein Jüngling liebt ein Mädchen",
              "Ein Jüngling liebt ein Mädchen",
              "11_Ein_Jüngling_liebt_ein_Mädchen", "lc4978393.mxl"),
    _schumann(12, "Am leuchtenden Sommermorgen",
              "Am leuchtenden Sommermorgen",
              "12_Am_leuchtenden_Sommermorgen", "lc4978395.mxl"),
    _schumann(13, "Ich hab’ im Traum geweinet",
              "Ich hab im Traum geweinet",
              "13_Ich_hab’_im_Traum_geweinet", "lc4978396.mxl",
              second_line="Mir träumte, du lägest im Grab"),  # disambiguates: this
              # exact incipit opens two OTHER poems too, with different 2nd lines.
    _schumann(14, "Allnächtlich im Traume",
              "Allnächtlich im Traume",
              "14_Allnächtlich_im_Traume", "lc4978397.mxl"),
    _schumann(15, "Aus alten Märchen winkt es",
              "Aus alten Märchen winkt es",
              "15_Aus_alten_Märchen_winkt_es", "lc4978398.mxl"),
    _schumann(16, "Die alten, bösen Lieder",
              "Die alten, bösen Lieder",
              "16_Die_alten,_bösen_Lieder", "lc4978400.mxl"),
]

_REGISTRIES: dict[str, list[SongSetting]] = {
    "dichterliebe": _DICHTERLIEBE,
}


def _normalize(text: str) -> str:
    """Fold a line down to a matching key: casefold, straighten curly
    punctuation, collapse whitespace, strip trailing punctuation."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = text.replace("„", '"').replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(",.;:!?")
    return text.casefold()


def find_setting(
    poem_first_line: str, catalog: list[SongSetting], poem_second_line: str = "",
) -> SongSetting | None:
    """A chapter's first source line matches a registry entry when one is a
    prefix of the other (registry incipits are sometimes truncated, e.g.
    song 3 stops after "die Lilie"). When the entry also carries a
    `second_line` (Heine repeats a few opening lines verbatim across
    different poems — see SongSetting's docstring), the chapter's second
    line must match it too, or the match is rejected."""
    if not poem_first_line:
        return None
    key = _normalize(poem_first_line)
    if not key:
        return None
    second_key = _normalize(poem_second_line) if poem_second_line else ""
    for setting in catalog:
        reg_key = setting.incipit_key
        if not (key == reg_key or key.startswith(reg_key) or reg_key.startswith(key)):
            continue
        if setting.second_line_key:
            sl_reg = setting.second_line_key
            if not (second_key and (second_key == sl_reg or second_key.startswith(sl_reg)
                                    or sl_reg.startswith(second_key))):
                continue
        return setting
    return None


class MusicError(RuntimeError):
    """Raised when a setting was matched but couldn't be fetched or rendered."""


def _resolve_lilypond() -> Path | None:
    found = shutil.which("lilypond")
    return Path(found) if found else None


def _musicxml2ly_command() -> list[str] | None:
    """Command (as an argv prefix) to invoke musicxml2ly, or None if it can't
    be located.

    On Linux/Mac a LilyPond install typically puts a directly-runnable
    `musicxml2ly` script on PATH. On Windows (confirmed against the
    LilyPond.LilyPond winget package, 2.24.4) it instead ships as
    `musicxml2ly.py` sitting next to `lilypond.exe`, meant to be run with
    LilyPond's own bundled `python.exe` in that same bin/ directory — a bare
    `musicxml2ly` is never on PATH there, and the system Python may not have
    LilyPond's `share/lilypond/<ver>/python/` conversion modules importable
    (the bundled interpreter has that already set up)."""
    found = shutil.which("musicxml2ly")
    if found:
        return [found]
    lily = _resolve_lilypond()
    if lily is None:
        return None
    bin_dir = lily.parent
    script = bin_dir / "musicxml2ly.py"
    if not script.exists():
        return None
    bundled_python = bin_dir / "python.exe"
    if bundled_python.exists():
        return [str(bundled_python), str(script)]
    return [sys.executable, str(script)]  # best-effort fallback


def ensure_lilypond_available() -> None:
    if _resolve_lilypond() is None:
        raise MusicError(
            "lilypond not found on PATH. Install LilyPond (lilypond.org/download) "
            "to render musical-literature pages; builds continue without music until then."
        )
    if _musicxml2ly_command() is None:
        raise MusicError(
            "musicxml2ly not found (checked PATH and next to the lilypond executable). "
            "Install LilyPond (lilypond.org/download) to render musical-literature pages; "
            "builds continue without music until then."
        )


def _fetch_mxl(setting: SongSetting, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / setting.cache_name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    resp = requests.get(setting.mxl_url, headers={"User-Agent": "book_creator"}, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _rootfile_name(z: zipfile.ZipFile) -> str:
    """MXL is a zip; META-INF/container.xml points at the actual MusicXML
    entry (OpenScore always uses "score.xml", but don't assume)."""
    try:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = container.find(".//rootfile")
        if rootfile is not None and rootfile.get("full-path"):
            return rootfile.get("full-path")
    except KeyError:
        pass
    candidates = [n for n in z.namelist() if n.endswith((".xml", ".musicxml"))
                  and not n.startswith("META-INF/")]
    if not candidates:
        raise MusicError("No MusicXML entry found inside .mxl archive.")
    return candidates[0]


def _grand_staff_part_ids(root: ET.Element) -> list[str]:
    """The piano part(s): exactly the ones with 2 staves and both a treble
    (G) and bass (F) clef in their first measure — robust across the corpus
    even when a vocal part's declared instrument name is wrong (observed:
    one Dichterliebe song's vocal part is mislabeled "Clarinet in C")."""
    ids = []
    for part in root.iter("part"):
        first_measure = part.find("measure")
        if first_measure is None:
            continue
        attrs = first_measure.find("attributes")
        if attrs is None:
            continue
        staves_el = attrs.find("staves")
        staves = int(staves_el.text) if staves_el is not None else 1
        clefs = {c.findtext("sign") for c in attrs.findall("clef")}
        if staves >= 2 and {"G", "F"} <= clefs:
            ids.append(part.attrib["id"])
    return ids


def extract_grand_staff_musicxml(mxl_path: Path) -> str:
    """Load a .mxl, drop every part except the piano grand staff (treble +
    bass), return the remaining document as a MusicXML string."""
    with zipfile.ZipFile(mxl_path) as z:
        root_name = _rootfile_name(z)
        data = z.read(root_name)
    root = ET.fromstring(data)

    keep_ids = _grand_staff_part_ids(root)
    if not keep_ids:
        raise MusicError(f"No 2-staff (treble+bass) piano part found in {mxl_path.name}.")

    part_list = root.find("part-list")
    if part_list is not None:
        for score_part in list(part_list.findall("score-part")):
            if score_part.attrib.get("id") not in keep_ids:
                part_list.remove(score_part)
    for part in list(root.findall("part")):
        if part.attrib.get("id") not in keep_ids:
            root.remove(part)

    return ET.tostring(root, encoding="unicode", xml_declaration=False)


_LY_APPEND = """
% --- book_creator: strip page furniture for an embedded snippet. Multiple
% top-level \\header/\\paper blocks merge (this one overrides the fields it
% names, musicxml2ly's earlier block keeps the rest — title/subtitle/
% composer/poet stay). `copyright` matters most: LilyPond anchors it to the
% bottom of the LAST page regardless of how little music is above it, which
% defeats whitespace-cropping the PNG afterward if left in place.
\\header {
  tagline = ##f
  copyright = ##f
  arranger = ##f
}
\\paper {
  print-page-number = ##f
  indent = 0
  ragged-bottom = ##t
  ragged-last-bottom = ##t
}
"""


def render_grand_staff(musicxml: str, out_prefix: Path, *, title: str = "") -> list[Path]:
    """Convert MusicXML -> LilyPond source -> PNG page(s). Returns the PNG
    paths in page order. Raises MusicError if LilyPond isn't available or
    either subprocess step fails."""
    ensure_lilypond_available()
    out_prefix = out_prefix.resolve()  # absolute: lilypond's -o is otherwise
    # re-resolved against `cwd` below, double-prefixing a relative path.
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    xml_path = out_prefix.with_suffix(".musicxml")
    xml_path.write_text(musicxml, encoding="utf-8")

    ly_path = out_prefix.with_suffix(".ly")
    m2ly = _musicxml2ly_command()
    if m2ly is None:  # ensure_lilypond_available() already checked this; belt and suspenders
        raise MusicError("musicxml2ly not found.")
    result = subprocess.run(
        [*m2ly, "--no-articulation-directions", "-o", str(ly_path), str(xml_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not ly_path.exists():
        raise MusicError(f"musicxml2ly failed for {title or xml_path.name}: {result.stderr.strip()}")

    with ly_path.open("a", encoding="utf-8") as f:
        f.write(_LY_APPEND)

    lily = _resolve_lilypond()
    result = subprocess.run(
        [str(lily), "-dresolution=300", "--png", "-o", str(out_prefix), str(ly_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise MusicError(f"lilypond failed for {title or ly_path.name}: {result.stderr.strip()}")

    pages = sorted(out_prefix.parent.glob(f"{out_prefix.name}*.png"))
    if not pages:
        raise MusicError(f"lilypond produced no PNG output for {title or ly_path.name}.")
    for page in pages:
        _crop_whitespace(page)
    return pages


def _crop_whitespace(png_path: Path, margin: int = 24) -> None:
    """LilyPond renders a full page (A4 by default) even when the music only
    fills a fraction of it — embedded at full size that's mostly wasted
    space in the finished book. Crop to the ink bounding box in place, with
    a small margin. No-op (leaves the page untouched) if the page is
    entirely blank, which shouldn't happen but isn't worth failing a build
    over."""
    with Image.open(png_path) as im:
        rgb = im.convert("RGB")
        bg = Image.new("RGB", rgb.size, (255, 255, 255))
        diff = ImageChops.difference(rgb, bg)
        bbox = diff.getbbox()
        if bbox is None:
            return
        left, top, right, bottom = bbox
        left = max(0, left - margin)
        top = max(0, top - margin)
        right = min(rgb.width, right + margin)
        bottom = min(rgb.height, bottom + margin)
        cropped = im.crop((left, top, right, bottom))
        cropped.save(png_path)


def render_poem_music(
    first_src_line: str,
    second_src_line: str = "",
    *,
    catalog: str,
    cache_dir: Path,
    work_dir: Path,
    log=lambda msg: None,
) -> tuple[list[str], str] | None:
    """End-to-end: match `first_src_line`/`second_src_line` against
    `catalog`, fetch + render the matched setting. Returns
    (png_page_paths, caption) or None if unmatched. Rendering failures
    (including a missing LilyPond install) are logged and treated as "no
    music for this poem" — never fail the build."""
    registry = _REGISTRIES.get(catalog)
    if not registry:
        log(f"  ⚠  Unknown music catalog '{catalog}'; skipping musical literature.")
        return None

    setting = find_setting(first_src_line, registry, second_src_line)
    if setting is None:
        return None

    caption = f"Set to music by {setting.composer} — {setting.work}, No. {setting.number}"
    try:
        mxl_path = _fetch_mxl(setting, cache_dir)
        musicxml = extract_grand_staff_musicxml(mxl_path)
        prefix = work_dir / f"{setting.number:02d}-{re.sub(r'[^a-z0-9]+', '-', setting.title.lower()).strip('-')}"
        pages = render_grand_staff(musicxml, prefix, title=setting.title)
        log(f"  ♪ {setting.title!r} — {caption} ({len(pages)} page(s))")
        return [str(p) for p in pages], caption
    except MusicError as exc:
        log(f"  ⚠  {caption}: {exc}")
        return None
    except requests.RequestException as exc:
        log(f"  ⚠  {caption}: couldn't fetch score ({exc}).")
        return None
