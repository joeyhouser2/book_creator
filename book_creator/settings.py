"""Small persisted settings, for choices that should outlive one page load.

Only what the user sets in the UI and expects to still be set tomorrow lives
here -- currently just where the `latin` corpus is. Everything else is a
per-build option and belongs on a BookSpec.

Stored as JSON beside the book configs rather than in the job database: it is
hand-editable, and someone who has been driving this from the CLI should be
able to see and change the same setting the web UI writes.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

SETTINGS_PATH = Path("config") / "settings.json"

_lock = threading.Lock()


def load(path: Path | str | None = None) -> dict:
    """Every stored setting. A missing or corrupt file reads as empty.

    Unreadable settings must not take the app down -- the corpus tab has a
    perfectly good default (the sibling checkout), and a hand-edit with a
    trailing comma in it should degrade to "nothing set", not a 500.
    """
    p = Path(path or SETTINGS_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default=None, *, path: Path | str | None = None):
    return load(path).get(key, default)


def save(values: dict, *, path: Path | str | None = None) -> dict:
    """Merge `values` into the stored settings and write them back.

    A key set to None is removed, so the UI can clear a setting back to the
    default search rather than having to store an empty string that then has
    to be special-cased everywhere it is read.
    """
    p = Path(path or SETTINGS_PATH)
    with _lock:
        data = load(p)
        for k, v in values.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data
