"""Proofread the aligned pairs of a dual-language book on the local GPU.

`reviewer.py` asks a chat model for its opinion of each bead. This module
measures instead, with three independent signals, and only reports where they
are unusual *for this book*:

  1. LaBSE similarity of the two sides, and whether either side matches a
     neighbouring bead better than its own (the signature of a drifted
     alignment).
  2. The length ratio of the two sides against the book's own norm (an
     omitted or an added clause).
  3. A translation model's pointwise mutual information between the sides:
     how much more probable each token of the target is *given the source*
     than without it. A fluent English sentence that the source does not
     support has near-zero PMI on exactly the tokens that were invented; a
     source clause missing from the target shows the same way in the reverse
     direction. Tower-Instruct is trained to translate, so it is a better
     likelihood model of "is this a translation of that" than a chat model is.

Everything is judged against the book's own distribution (median / MAD), so
a language the model reads poorly -- Latin, Middle High German -- just shifts
the baseline instead of flagging every line. Weak models give weak, not wrong,
rankings. Advisory only: it never edits a bead.

The scorer runs in a subprocess with CUDA_VISIBLE_DEVICES cleared. A 7B model
in half precision needs ~14 GB, and a shell that exports CUDA_VISIBLE_DEVICES=0
hides the 16 GB card; and by the time a build reaches this step the parent
process has already initialised CUDA with that mask for LaBSE.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .model import Chapter

TOWER_MODEL = "Unbabel/TowerInstruct-7B-v0.2"
LABSE_MODEL = "sentence-transformers/LaBSE"

# Names the translation prompt uses. Tower was trained on the first ten; the
# rest are best-effort and are only used as prompt text.
LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian",
    "zh": "Chinese", "ko": "Korean", "la": "Latin", "grc": "Ancient Greek",
    "el": "Greek", "gmh": "Middle High German", "enm": "Middle English",
    "ang": "Old English", "fro": "Old French", "sv": "Swedish", "da": "Danish",
    "pl": "Polish", "cs": "Czech", "hu": "Hungarian", "fi": "Finnish",
}
TOWER_LANGS = {"en", "de", "fr", "es", "it", "pt", "nl", "ru", "zh", "ko"}

_MAX_CHARS = 1500       # per side; a very long bead is judged on its start
_SPAN_TOKENS = 6        # window used to localise the worst-supported text
_MIN_TOKENS = 3         # below this a likelihood ratio is noise

# Thresholds, in robust z-scores against the book itself.
_Z_FLAG = -3.0
_Z_EXTREME = -5.0
# A single line is short and noisy and its left tail is short too, so the line
# bar is lower than the bead bar; a line this far out is still ~1 in 20 beads.
_Z_LINE = -2.0
_Z_LINE_EXTREME = -3.0
_LEN_Z = 3.5
_LABSE_FLOOR = 0.30
_DRIFT_MARGIN = 0.08
_DRIFT_CEILING = 0.75

_SEVERITY_ORDER = {"high": 0, "medium": 1}


class ProofreadError(RuntimeError):
    pass


def lang_name(code: str) -> str:
    return LANG_NAMES.get((code or "").lower(), code or "the source language")


# --------------------------------------------------------------------------- #
# Pure analysis: metrics in, findings out
# --------------------------------------------------------------------------- #
def robust_z(values: list[float | None]) -> list[float | None]:
    """z-scores from the median and MAD, so a few broken beads cannot hide
    themselves by dragging the mean. None stays None."""
    present = [v for v in values if v is not None and not math.isnan(v)]
    if len(present) < 8:
        return [None] * len(values)
    med = statistics.median(present)
    mad = statistics.median(abs(v - med) for v in present) * 1.4826
    if mad < 1e-9:
        mad = statistics.pstdev(present) or 1.0
    return [None if v is None or math.isnan(v) else (v - med) / mad for v in values]


@dataclass
class PairFinding:
    chapter_index: int
    chapter_title: str
    bead_index: int
    severity: str
    reasons: list[str]
    src_excerpt: str
    tgt_excerpt: str
    labse: float | None = None
    # Most negative z among this bead's signals: how far out it is. Reports
    # sort on it so the worst come first within a severity.
    worst_z: float = 0.0
    suggestion: str = ""
    metrics: dict = field(default_factory=dict)


def _excerpt(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _line_z(items: list[dict], metrics: list[dict], metric_key: str,
            lines_key: str) -> list[list[float | None]]:
    """Per-line robust z-scores, pooled over every bead that has >= 2 lines on
    that side. A one-line bead's line score is its bead score, which the bead
    level already covers."""
    pool: list[float | None] = []
    where: list[tuple[int, int]] = []
    for i, (it, m) in enumerate(zip(items, metrics)):
        vals = m.get(metric_key) or []
        if len(it[lines_key]) < 2:
            continue
        for k, v in enumerate(vals):
            pool.append(v)
            where.append((i, k))
    zs = robust_z(pool)
    out: list[list[float | None]] = [[None] * len(it[lines_key]) for it in items]
    for (i, k), z in zip(where, zs):
        if k < len(out[i]):
            out[i][k] = z
    return out


def _quote(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return "“" + (text if len(text) <= limit else text[:limit].rstrip() + "…") + "”"


def _line_reasons(zs: list[float | None], lines: list[str], template: str,
                  limit: int = 3) -> tuple[list[str], bool]:
    bad = [k for k, z in enumerate(zs) if z is not None and z <= _Z_LINE]
    out = [template.format(n=k + 1, text=_quote(lines[k])) for k in bad[:limit]]
    if len(bad) > limit:
        out.append(f"(and {len(bad) - limit} more such lines)")
    return out, any(zs[k] <= _Z_LINE_EXTREME for k in bad)


def analyse(items: list[dict], metrics: list[dict]) -> list[PairFinding]:
    """Turn per-bead metrics into findings.

    `items[i]` carries src, tgt, src_lines, tgt_lines, chapter_index,
    chapter_title, bead_index; `metrics[i]` is what the scorer returned for it
    (any key may be missing).

    Findings count *independent* signals: alignment (similarity and drift are
    one signal, because a drifted bead is by definition a poor match), length,
    translation-unsupported, and original-uncarried. Two or more, or one
    extreme one, is high; a single ordinary one is medium.
    """
    n = len(items)
    own = [m.get("labse") for m in metrics]
    prev = [m.get("labse_prev") for m in metrics]
    nxt = [m.get("labse_next") for m in metrics]
    fwd = [m.get("fwd_pmi") for m in metrics]
    rev = [m.get("rev_pmi") for m in metrics]
    ratio = [math.log(max(len(it["tgt"]), 1) / max(len(it["src"]), 1)) for it in items]

    z_labse, z_fwd, z_rev = robust_z(own), robust_z(fwd), robust_z(rev)
    z_len = robust_z(ratio)
    zl_fwd = _line_z(items, metrics, "fwd_lines", "tgt_lines")
    zl_rev = _line_z(items, metrics, "rev_lines", "src_lines")

    findings: list[PairFinding] = []
    for i in range(n):
        it, m = items[i], metrics[i]
        reasons: list[str] = []
        signals = 0
        extreme = False
        zs_seen: list[float] = []
        short = len(it["src"].split()) < 3 or len(it["tgt"].split()) < 3

        # -- alignment: one signal, however many ways it shows ---------------
        if own[i] is not None and not short:
            parts: list[str] = []
            neighbour = max((x for x in (prev[i], nxt[i]) if x is not None), default=None)
            if own[i] < _LABSE_FLOOR:
                parts.append(f"the two sides barely match (LaBSE {own[i]:.2f})")
                extreme = True
            elif z_labse[i] is not None and z_labse[i] <= _Z_FLAG:
                zs_seen.append(z_labse[i])
                parts.append(f"weak match for this book (LaBSE {own[i]:.2f}, "
                             f"z {z_labse[i]:.1f})")
                extreme |= z_labse[i] <= _Z_EXTREME
            if (neighbour is not None and neighbour > own[i] + _DRIFT_MARGIN
                    and own[i] < _DRIFT_CEILING):
                side = "previous" if (prev[i] or -9) >= (nxt[i] or -9) else "next"
                parts.append(f"the source fits the {side} bead's translation "
                             f"better ({neighbour:.2f} vs {own[i]:.2f}): alignment drift")
            if parts:
                reasons.append("; ".join(parts))
                signals += 1

        # -- length ----------------------------------------------------------
        if z_len[i] is not None and abs(z_len[i]) >= _LEN_Z and not short:
            zs_seen.append(-abs(z_len[i]))
            kind = "target much longer than usual (added text?)" if z_len[i] > 0 \
                else "target much shorter than usual (omitted text?)"
            reasons.append(f"length: {kind}")
            signals += 1

        # -- text the original does not support -----------------------------
        line_r, line_x = _line_reasons(
            zl_fwd[i], it["tgt_lines"],
            "translation line {n} is not supported by the original: {text}")
        if line_r:
            reasons += line_r
            signals += 1
            extreme |= line_x
            zs_seen.append(min(z for z in zl_fwd[i] if z is not None))
        elif z_fwd[i] is not None and z_fwd[i] <= _Z_FLAG:
            span = m.get("fwd_span")
            reasons.append("the translation says more than the source supports"
                           + (f": “{span}”" if span else ""))
            signals += 1
            extreme |= z_fwd[i] <= _Z_EXTREME
            zs_seen.append(z_fwd[i])

        # -- text the translation does not carry ----------------------------
        line_r, line_x = _line_reasons(
            zl_rev[i], it["src_lines"],
            "line {n} of the original has no counterpart in the translation: {text}")
        if line_r:
            reasons += line_r
            signals += 1
            extreme |= line_x
            zs_seen.append(min(z for z in zl_rev[i] if z is not None))
        elif z_rev[i] is not None and z_rev[i] <= _Z_FLAG:
            span = m.get("rev_span")
            reasons.append("the source says more than the translation carries"
                           + (f": “{span}”" if span else ""))
            signals += 1
            extreme |= z_rev[i] <= _Z_EXTREME
            zs_seen.append(z_rev[i])

        if not signals:
            continue
        severity = "high" if (signals >= 2 or extreme) else "medium"
        findings.append(PairFinding(
            chapter_index=it["chapter_index"], chapter_title=it["chapter_title"],
            bead_index=it["bead_index"], severity=severity, reasons=reasons,
            src_excerpt=_excerpt(it["src"]), tgt_excerpt=_excerpt(it["tgt"]),
            labse=own[i], worst_z=min(zs_seen, default=0.0),
            suggestion=m.get("suggestion", ""),
            metrics={k: (round(v, 3) if isinstance(v, float) else v)
                     for k, v in m.items()
                     if k not in ("suggestion", "fwd_lines", "rev_lines")},
        ))
    return findings


def format_report(findings: list[PairFinding], *, scanned: int = 0,
                  model: str = "", note: str = "") -> str:
    head = "# Pair proofreading"
    if not findings:
        return f"{head}\n\nNo pairs stood out ({scanned} scanned).\n"
    high = sum(1 for f in findings if f.severity == "high")
    lines = [f"{head} — {len(findings)} of {scanned} pairs flagged ({high} high)", ""]
    if model:
        lines += [f"Scored with `{model}`; thresholds are relative to this book.", ""]
    if note:
        lines += [note, ""]
    for f in sorted(findings, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9),
                                             f.worst_z, f.chapter_index, f.bead_index)):
        lines.append(f"## [{f.severity.upper()}] {f.chapter_title} — bead {f.bead_index + 1}")
        for r in f.reasons:
            lines.append(f"- {r}")
        lines.append(f"- SRC: {f.src_excerpt}")
        lines.append(f"- TGT: {f.tgt_excerpt}")
        if f.suggestion:
            lines.append(f"- MODEL READS: {f.suggestion}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
Scorer = Callable[[list[tuple[list[str], list[str]]], dict, Callable[[str], None]],
                  list[dict]]


def run_worker(pairs: list[tuple[list[str], list[str]]], opts: dict,
               log: Callable[[str], None] = print) -> list[dict]:
    """Score `pairs` in a child process that can see every GPU."""
    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    masked = env.pop("CUDA_VISIBLE_DEVICES", None)
    if masked:
        log(f"  (scoring in a subprocess without CUDA_VISIBLE_DEVICES={masked}, "
            f"so the largest card is usable)")
    with tempfile.TemporaryDirectory() as tmp:
        src_path, out_path = Path(tmp, "in.json"), Path(tmp, "out.json")
        src_path.write_text(json.dumps({"pairs": pairs, **opts}), encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "book_creator.proofread_pairs", "--worker",
             str(src_path), str(out_path)],
            cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        tail: list[str] = []
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line.startswith("PROGRESS "):
                log(f"  {line[9:]}")
            elif line:
                tail = (tail + [line])[-12:]
        code = proc.wait()
        if code != 0 or not out_path.exists():
            raise ProofreadError("pair scorer failed:\n" + "\n".join(tail))
        return json.loads(out_path.read_text(encoding="utf-8"))


def _cap_lines(segs: list[str]) -> list[str]:
    """The non-empty lines of one side, cut off at _MAX_CHARS in total."""
    out, used = [], 0
    for seg in segs:
        seg = (seg or "").strip()
        if not seg:
            continue
        if used and used + len(seg) > _MAX_CHARS:
            break
        out.append(seg[:_MAX_CHARS])
        used += len(seg) + 1
    return out


def check_chapters(chapters: list[Chapter], *, src_lang: str, tgt_lang: str,
                   model: str = TOWER_MODEL, max_beads: int | None = None,
                   directions: str | None = None, suggest: int = 40,
                   batch_size: int = 8, quant: str = "auto",
                   device: str = "auto", scorer: Scorer | None = None,
                   metrics_out: str | Path | None = None,
                   log: Callable[[str], None] = print) -> tuple[list[PairFinding], int]:
    """Score every two-sided bead and return (findings, beads scanned)."""
    items: list[dict] = []
    for ci, ch in enumerate(chapters):
        for bi, bead in enumerate(ch.beads):
            sl, tl = _cap_lines(bead.src), _cap_lines(bead.tgt)
            if not sl or not tl:
                continue            # a marked insertion or deletion
            items.append({"src": " ".join(sl), "tgt": " ".join(tl),
                          "src_lines": sl, "tgt_lines": tl,
                          "chapter_index": ci, "bead_index": bi,
                          "chapter_title": ch.title or f"Chapter {ci + 1}"})
    if max_beads is not None:
        items = items[:max_beads]
    if not items:
        return [], 0
    if directions is None:
        directions = "both" if src_lang.lower() in TOWER_LANGS else "fwd"
    opts = {"src_lang": src_lang, "tgt_lang": tgt_lang, "model": model,
            "directions": directions, "suggest": suggest, "batch_size": batch_size,
            "quant": quant, "device": device,
            "labse": LABSE_MODEL}
    run = scorer or run_worker
    metrics = run([(it["src_lines"], it["tgt_lines"]) for it in items], opts, log)
    if len(metrics) != len(items):
        raise ProofreadError(f"scorer returned {len(metrics)} results for {len(items)} pairs")
    if metrics_out:
        # The raw scores, so thresholds can be tuned (`analyse`) without
        # another GPU run.
        Path(metrics_out).write_text(
            json.dumps({"items": items, "metrics": metrics, "model": model}),
            encoding="utf-8")
    findings = analyse(items, metrics)
    return findings, len(items)


# --------------------------------------------------------------------------- #
# Worker: runs in the child process, owns torch / LaBSE / the translation model
# --------------------------------------------------------------------------- #
def _chat_prompt(tok, src_name: str, tgt_name: str, text: str) -> str:
    user = (f"Translate the following text from {src_name} into {tgt_name}.\n"
            f"{src_name}: {text}\n{tgt_name}:")
    if getattr(tok, "chat_template", None):
        return tok.apply_chat_template([{"role": "user", "content": user}],
                                       tokenize=False, add_generation_prompt=True)
    return f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"


def _pick_device(torch):
    """The CUDA device with the most memory, or cpu."""
    if not torch.cuda.is_available():
        return "cpu"
    best = max(range(torch.cuda.device_count()),
               key=lambda i: torch.cuda.get_device_properties(i).total_memory)
    return f"cuda:{best}"


def _weights_bytes(name: str) -> int:
    """On-disk size of a cached model's weights; 14 GB (a 7B) if not cached."""
    try:
        from huggingface_hub import snapshot_download
        root = Path(snapshot_download(name, local_files_only=True,
                                      allow_patterns=["*.safetensors"]))
        size = sum(f.stat().st_size for f in root.glob("*.safetensors"))
        cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
        # Stored in fp32 but loaded in half precision: half the size on the card.
        return size // 2 if str(cfg.get("torch_dtype", cfg.get("dtype", ""))) == "float32" else size
    except Exception:  # noqa: BLE001
        return 14 * 1024 ** 3


def _load_lm(name: str, log, quant: str = "auto", device: str = "auto"):
    """Load the scoring model on the roomiest card.

    `auto` quantises to 4-bit when the card cannot hold the half-precision
    weights with ~25% headroom. A 13.5 GB model "fitting" a 16 GB card that
    other programs already hold 2.5 GB of does not leave room for activations,
    and the failure is an opaque asynchronous launch error, not an OOM.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if device == "auto":
        device = _pick_device(torch)
    tok = AutoTokenizer.from_pretrained(name)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    if device == "cpu":
        log(f"PROGRESS loading {name} on cpu (slow)")
        return tok, AutoModelForCausalLM.from_pretrained(
            name, torch_dtype=torch.float32).eval(), device
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    free = torch.cuda.mem_get_info(torch.device(device))[0]
    need = _weights_bytes(name)
    if quant == "auto":
        quant = "none" if free >= need * 1.25 else "4bit"
    log(f"PROGRESS loading {name} on {device} ({quant}; "
        f"{free / 1024 ** 3:.1f} GB free, weights {need / 1024 ** 3:.1f} GB)")
    if quant in ("4bit", "8bit"):
        from transformers import BitsAndBytesConfig
        cfg = (BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                  bnb_4bit_compute_dtype=dtype)
               if quant == "4bit" else BitsAndBytesConfig(load_in_8bit=True))
        lm = AutoModelForCausalLM.from_pretrained(
            name, device_map={"": device}, quantization_config=cfg,
            torch_dtype=dtype, low_cpu_mem_usage=True)
    else:
        lm = AutoModelForCausalLM.from_pretrained(name, torch_dtype=dtype).to(device)
    return tok, lm.eval(), device


def _seg_ids(tok, segs: list[str], cap: int = 400) -> tuple[list[int], list[tuple[int, int]]]:
    """Token ids of `segs` joined by newlines, and each segment's (start, end).

    A segment that would push past `cap` tokens is dropped along with the
    rest; its span is (0, 0), which scores as None.
    """
    nl = tok.encode("\n", add_special_tokens=False)[-1:]
    ids: list[int] = []
    spans: list[tuple[int, int]] = []
    full = False
    for seg in segs:
        enc = tok(seg, add_special_tokens=False).input_ids if seg.strip() else []
        if full or not enc or len(ids) + len(enc) > cap:
            full = full or bool(enc)
            spans.append((0, 0))
            continue
        spans.append((len(ids), len(ids) + len(enc)))
        ids += enc + nl
    return ids, spans


def _token_logprobs(tok, lm, device, prompts: list[str], target_ids: list[list[int]],
                    batch_size: int) -> list[list[float]]:
    """Per-token log P(target | prompt) for each pair, batched by length."""
    import torch
    out: list[list[float] | None] = [None] * len(prompts)
    enc_p = [tok(p, add_special_tokens=False).input_ids for p in prompts]
    enc_t = target_ids
    order = sorted(range(len(prompts)), key=lambda i: len(enc_p[i]) + len(enc_t[i]))
    for start in range(0, len(order), batch_size):
        idx = order[start:start + batch_size]
        seqs = [enc_p[i] + enc_t[i] for i in idx]
        width = max(len(s) for s in seqs)
        ids = torch.full((len(idx), width), tok.pad_token_id, dtype=torch.long)
        mask = torch.zeros((len(idx), width), dtype=torch.long)
        for r, s in enumerate(seqs):
            ids[r, :len(s)] = torch.tensor(s)
            mask[r, :len(s)] = 1
        with torch.no_grad():
            logits = lm(input_ids=ids.to(device), attention_mask=mask.to(device)).logits
        for r, i in enumerate(idx):
            p, t = len(enc_p[i]), len(enc_t[i])
            if t == 0:
                out[i] = []
                continue
            rows = logits[r, p - 1:p - 1 + t].float().log_softmax(-1)
            tgt = torch.tensor(enc_t[i], device=rows.device)
            out[i] = rows.gather(1, tgt[:, None]).squeeze(1).cpu().tolist()
    return [o or [] for o in out]


def _pmi_from_logprobs(tok, ids: list[int], spans: list[tuple[int, int]],
                       cond: list[float], base: list[float]) -> dict:
    """Bead mean, worst window and per-line means of cond - base over `ids`."""
    n = min(len(cond), len(base))
    diff = [cond[k] - base[k] for k in range(n)]
    lines: list[float | None] = []
    for a, b in spans:
        b = min(b, n)
        lines.append(sum(diff[a:b]) / (b - a) if b - a >= _MIN_TOKENS else None)
    content = [k for a, b in spans for k in range(a, min(b, n))]
    if len(content) < _MIN_TOKENS:
        return {"mean": None, "span": None, "lines": lines}
    vals = [diff[k] for k in content]
    mean = sum(vals) / len(vals)
    w = min(_SPAN_TOKENS, len(vals))
    worst = min(range(len(vals) - w + 1), key=lambda k: sum(vals[k:k + w]))
    span = tok.decode([ids[k] for k in content[worst:worst + w]]).strip()
    return {"mean": mean, "span": span, "lines": lines}


def _pmi(tok, lm, device, src_lines, tgt_lines, src_name, tgt_name, batch_size):
    """PMI of each target (a list of lines) given its source lines.

    Lines are scored in the context of the whole block, in one pass: line k of
    the target is conditioned on every source line and on target lines 1..k-1,
    and the baseline sees the same earlier target lines but no source. So a
    line's PMI is what *the source* added to it.
    """
    enc = [_seg_ids(tok, segs) for segs in tgt_lines]
    ids = [e[0] for e in enc]
    cond = _token_logprobs(
        tok, lm, device,
        [_chat_prompt(tok, src_name, tgt_name, "\n".join(s)) for s in src_lines],
        ids, batch_size)
    base = _token_logprobs(
        tok, lm, device,
        [_chat_prompt(tok, src_name, tgt_name, "") for _ in src_lines],
        ids, batch_size)
    return [_pmi_from_logprobs(tok, e[0], e[1], c, b)
            for e, c, b in zip(enc, cond, base)]


def _labse_metrics(pairs, model_name):
    import numpy as np
    from sentence_transformers import SentenceTransformer
    st = SentenceTransformer(model_name)
    se = st.encode([p[0] for p in pairs], normalize_embeddings=True,
                   convert_to_numpy=True, batch_size=64)
    te = st.encode([p[1] for p in pairs], normalize_embeddings=True,
                   convert_to_numpy=True, batch_size=64)
    own = (se * te).sum(1)
    res = []
    for i in range(len(pairs)):
        res.append({
            "labse": float(own[i]),
            "labse_prev": float(se[i] @ te[i - 1]) if i > 0 else None,
            "labse_next": float(se[i] @ te[i + 1]) if i + 1 < len(pairs) else None,
        })
    del st
    return res


def _worker(src_json: str, out_json: str) -> int:
    cfg = json.loads(Path(src_json).read_text(encoding="utf-8"))
    pairs = [(list(p[0]), list(p[1])) for p in cfg["pairs"]]
    log = print
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    log(f"PROGRESS embedding {len(pairs)} pairs with LaBSE")
    metrics = _labse_metrics([(" ".join(p[0]), " ".join(p[1])) for p in pairs],
                             cfg.get("labse", LABSE_MODEL))

    import torch
    tok, lm, device = _load_lm(cfg["model"], log, cfg.get("quant", "auto"),
                                cfg.get("device", "auto"))
    s_name, t_name = lang_name(cfg["src_lang"]), lang_name(cfg["tgt_lang"])
    bs = int(cfg.get("batch_size", 8))
    src = [p[0] for p in pairs]          # lists of lines
    tgt = [p[1] for p in pairs]

    log(f"PROGRESS scoring {s_name} → {t_name} likelihood")
    for m, r in zip(metrics, _pmi(tok, lm, device, src, tgt, s_name, t_name, bs)):
        m["fwd_pmi"], m["fwd_span"], m["fwd_lines"] = r["mean"], r["span"], r["lines"]
    if cfg.get("directions", "fwd") == "both":
        log(f"PROGRESS scoring {t_name} → {s_name} likelihood")
        for m, r in zip(metrics, _pmi(tok, lm, device, tgt, src, t_name, s_name, bs)):
            m["rev_pmi"], m["rev_span"], m["rev_lines"] = r["mean"], r["span"], r["lines"]

    # A second opinion for the beads most likely to need one: the model's own
    # translation, by greedy decoding, set beside the book's.
    want = int(cfg.get("suggest", 0))
    if want > 0:
        z = robust_z([m.get("fwd_pmi") for m in metrics])
        z2 = robust_z([m.get("rev_pmi") for m in metrics])
        worst = sorted(range(len(pairs)), key=lambda i: min(
            [v for v in (z[i], z2[i], (metrics[i]["labse"] - 0.6) * 10) if v is not None]))[:want]
        log(f"PROGRESS drafting a second reading of {len(worst)} beads")
        for k, i in enumerate(worst):
            prompt = _chat_prompt(tok, s_name, t_name, "\n".join(src[i]))
            enc = tok(prompt, return_tensors="pt", add_special_tokens=False).to(device)
            with torch.no_grad():
                gen = lm.generate(**enc, max_new_tokens=min(400, 2 * len(tok(" ".join(tgt[i])).input_ids) + 20),
                                  do_sample=False)
            metrics[i]["suggestion"] = tok.decode(
                gen[0, enc.input_ids.shape[1]:], skip_special_tokens=True).strip()

    Path(out_json).write_text(json.dumps(metrics), encoding="utf-8")
    log("PROGRESS done")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--worker", nargs=2, metavar=("IN_JSON", "OUT_JSON"),
                    help="internal: score a JSON list of pairs")
    args = ap.parse_args(argv)
    if args.worker:
        return _worker(*args.worker)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
