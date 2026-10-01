"""Remember what a translation model already said, so a rebuild is not a re-run.

Machine translation is a deterministic function of (model, source text), and a
book gets rebuilt for reasons that have nothing to do with its text: a wrong
filename, a second edition in one language, a page count over KDP's limit. Each
of those re-ran the model over text it had already translated -- across one
working session, 59,500 segments were translated of which only 29,200 were
distinct, so half the GPU time produced output that already existed.

The same argument the TTS cache makes (audio._cache_key): cache on the way in,
and a re-run only pays for what actually changed.

Cached ONLY for a translator that names itself -- a local model's `model_name`,
an HTTP service's `url`. A bare callable is not cached at all, because two
different functions would otherwise share the anonymous key and be served each
other's translations. Slower is better than wrong.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

DB_PATH = "cache/mt.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    model   TEXT NOT NULL,
    src_sha TEXT NOT NULL,
    english TEXT NOT NULL,
    PRIMARY KEY (model, src_sha)
);
"""


def translator_id(translator) -> str | None:
    """A stable name for this translator, or None if it has no claim to one."""
    for attr in ("model_name", "url"):
        value = getattr(translator, attr, None)
        if isinstance(value, str) and value:
            return f"{attr}:{value}"
    return None


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def translate(translator, texts: list[str], *, db_path: str | Path = DB_PATH,
              log=None, chunk: int = 250) -> list[str]:
    """Translate `texts`, reusing anything this model has translated before.

    Returns one English string per input, in order, exactly as calling the
    translator directly would. Falls back to a plain call when the translator
    cannot be named, and refuses to guess when the model returns the wrong
    number of items.
    """
    texts = list(texts)
    model = translator_id(translator)
    if model is None:
        return list(translator(texts))

    conn = _connect(db_path)
    try:
        # Look up by distinct text: a book repeats lines (a refrain, a blank),
        # and the model should see each one once even on a cold cache.
        wanted = {t: _sha(t) for t in set(texts)}
        hits: dict[str, str] = {}
        shas = list(wanted.values())
        for i in range(0, len(shas), 500):
            batch = shas[i:i + 500]
            rows = conn.execute(
                f"SELECT src_sha, english FROM translations WHERE model = ? "
                f"AND src_sha IN ({','.join('?' * len(batch))})",
                [model, *batch]).fetchall()
            hits.update(dict(rows))

        missing = [t for t, sha in wanted.items() if sha not in hits]
        if log:
            reused = len(wanted) - len(missing)
            if reused:
                log(f"• Translation cache: reusing {reused:,} of "
                    f"{len(wanted):,} distinct segment(s); "
                    f"{len(missing):,} to translate.")

        for start in range(0, len(missing), chunk):
            part = missing[start:start + chunk]
            got = list(translator(part))
            if len(got) != len(part):
                raise ValueError(
                    f"translator returned {len(got)} items for {len(part)} inputs")
            conn.executemany(
                "INSERT OR REPLACE INTO translations (model, src_sha, english) "
                "VALUES (?, ?, ?)",
                [(model, wanted[s], e) for s, e in zip(part, got)])
            conn.commit()
            hits.update({wanted[s]: e for s, e in zip(part, got)})
            if log and len(missing) > chunk:
                done = min(start + chunk, len(missing))
                log(f"  … {done:,}/{len(missing):,} segment(s)")

        return [hits[wanted[t]] for t in texts]
    finally:
        conn.close()


def stats(*, db_path: str | Path = DB_PATH) -> dict:
    """How much is remembered, per model."""
    if not Path(db_path).exists():
        return {"total": 0, "models": {}}
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT model, COUNT(*) FROM translations GROUP BY model").fetchall()
        return {"total": sum(n for _, n in rows), "models": dict(rows)}
    finally:
        conn.close()
