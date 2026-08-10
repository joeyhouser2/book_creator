"""Meaning-based sentence alignment using cross-lingual embeddings (LaBSE).

Unlike Gale-Church (which only compares sentence *lengths*), this compares what
sentences *mean* — so it stays aligned even when a translator splits, merges, or
reorders text. It needs `sentence-transformers` (which pulls in PyTorch); install
it with `pip install -r requirements-embed.txt`.

The model is loaded once per process and cached, so aligning many chapters in one
run pays the load cost only once.
"""

from __future__ import annotations

from .align import beads_from_path, run_dp
from .model import Bead

# Default model: LaBSE covers 100+ languages incl. Latin, Greek, French, German.
DEFAULT_MODEL = "sentence-transformers/LaBSE"

_MODEL_CACHE: dict = {}

# Soft penalties (added to 1 - cosine). Pooling embeddings for a merged bead
# inflates its cosine similarity, so without a real penalty the DP collapses
# clean 1-1 parallel text into 2-2 merges. 0.15/extra-segment keeps 1-1 the
# default unless a merge fits clearly better; null alignments stay expensive.
_MERGE_PENALTY = 0.15   # per extra segment beyond a 1-1 match
_NULL_COST = 0.85       # cost of an unaligned (inserted/deleted) segment

# Allowed moves. 2-2 is deliberately excluded: averaged LaBSE vectors keep a 2-2
# pool nearly as similar as true 1-1 pairs, so it collapses clean parallel text.
# The legitimate merges for literary translation are 1-2 (a split) and 2-1 (a join).
_STEPS = [(1, 1), (1, 0), (0, 1), (2, 1), (1, 2)]


def ensure_available() -> None:
    """Raise ImportError with a helpful message if the optional deps are missing."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError as exc:  # pragma: no cover - env dependent
        raise ImportError(
            "Embedding aligner needs sentence-transformers. "
            "Install with: pip install -r requirements-embed.txt"
        ) from exc


def _get_model(name: str):
    if name not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer
        _MODEL_CACHE[name] = SentenceTransformer(name)
    return _MODEL_CACHE[name]


def embed_align(src: list[str], tgt: list[str], *, model_name: str = DEFAULT_MODEL,
                steps: list[tuple[int, int]] | None = None) -> list[Bead]:
    if not src and not tgt:
        return []
    if not src:
        # One bead per segment, not one bead holding the whole list — bead.tgt
        # is space-joined for rendering, which would otherwise flatten verse
        # lines (or prose paragraphs) into a single run-on block.
        return [Bead(src=[], tgt=[t]) for t in tgt]
    if not tgt:
        return [Bead(src=[s], tgt=[]) for s in src]

    import numpy as np

    model = _get_model(model_name)
    se = model.encode(src, normalize_embeddings=True, convert_to_numpy=True)
    te = model.encode(tgt, normalize_embeddings=True, convert_to_numpy=True)

    def _pooled(mat, start, count):
        """Mean of a run of (unit) embeddings, renormalized so cosine is valid."""
        vec = mat[start:start + count].mean(axis=0)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def cost_fn(i, j, ds, dt):
        if ds == 0 or dt == 0:
            return _NULL_COST
        sim = float(np.dot(_pooled(se, i, ds), _pooled(te, j, dt)))
        penalty = _MERGE_PENALTY * (ds + dt - 2)
        return (1.0 - sim) + penalty

    path = run_dp(len(src), len(tgt), cost_fn, steps=steps or _STEPS)
    return beads_from_path(src, tgt, path)
