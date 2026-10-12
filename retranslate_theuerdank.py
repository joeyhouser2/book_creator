#!/usr/bin/env python
"""A second translation pass over Theuerdank's weakest sentences.

The first pass translates twelve sentences to a request and leaves some of the
German in: the pronouns of the 1517 spelling (Er, Sy, Ir) and a few function
words come through untouched, and a handful of units were given up on. This
finds those in the translation cache, translates each again on its own, with
the sentences either side for context and a prompt that names the failure, and
writes the better English back under the same cache key, so the next
`make_book.py config/theuerdank.yaml` picks it up without translating anything.

    python retranslate_theuerdank.py --scan            # count and show flagged
    python retranslate_theuerdank.py --run [--limit N] [--model M] [--host URL]
"""
import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from book_creator import clean, fetch, mt_cache, segment  # noqa: E402

CONFIG = "config/theuerdank.yaml"
CACHE_MODEL = "model_name:qwen3:14b"      # the key the build reads
DB = "cache/mt.db"

# Words of the 1517 text that an English rendering should not still contain.
GERMAN = re.compile(
    r"\b(Er|Sy|Ir|Ich|Eüch|Ewer|Ewr|vnd|vnnd|nit|nicht|aber|doch|noch|sich|dem|"
    r"mit|von|zu|zü|und|ein|einen|der|das|dann|wann|dieweil|darumb|wil|will|"
    r"Herr|Held|gar|sey|iß|ißt|hat|hab|habt|wer|wirdt|wirt)\b")
# Spellings no English word has; names of the poem's persons are excused.
ODD = re.compile(r"\b\w*(?:[äöüßæœ]|hait\b|heit\b|keit\b|vnn|vnd|ey[bcdfghjklmnpqrstvwxz]|"
                 r"\wff\w*ff|ge[ys]\b)\w*\b")
NAMES = re.compile(r"Tew?r?d\w*|Vn?f\w*|Ney\w*|F[uü]rw\w*|Ern\w*|Rom\w*|Ehren\w*|Schönsp\w*|Unf\w*|"
                   r"Fortuna|Maximilian|Burgund\w*|Ofterr\w*|Austria|Fürwittig|Theuerdank|School\w*|"
                   r"schol\w*|Sche\w*|Church|Christ\w*|Schw\w*|English|F[uü]\w*vitt\w*|Fü\w*itt\w*")
# English words that are also on that list; they alone do not flag a unit.
ENGLISH_OK = {"will", "hat", "gar", "wer", "Held", "Herr", "ein", "mit", "sich"}


def units() -> list[str]:
    """The strings the build translated, in order."""
    raw = yaml.safe_load(open(CONFIG, encoding="utf-8"))["books"][0]
    divisions = fetch.load_divisions(path=raw["src_path"], gid=None, mode="verse",
                                     poem_titles=False, log=lambda m: None)
    divisions = segment.subdivide(divisions, None, log=lambda m: None)
    out = []
    for _title, body in divisions:
        segs = segment.segment(body, "verse", "de")
        segs = clean.clean_segments(segs)
        out += [" ".join(g) for g in segment.sentence_groups(segs)]
    return out


def flagged(src: str, eng: str) -> list[str]:
    why = []
    if "[not translated]" in eng:
        why.append("not translated")
    if mt_cache.degenerate(eng):
        why.append("loops")
    left = [w for w in GERMAN.findall(eng) if w not in ENGLISH_OK]
    if left:
        why.append("German left: " + " ".join(sorted(set(left))))
    odd = [w for w in ODD.findall(eng) if not NAMES.fullmatch(w) and w.lower() not in
           {"school", "scheme", "ask", "back", "black", "check", "neck", "luck", "rock", "sick",
            "thick", "quick", "pick", "kick", "stick", "trick", "lock", "knock", "clock", "shock",
            "deck", "dock", "flock", "block", "brick", "track", "attack", "pack", "crack", "snack",
            "thank", "think", "drink", "wick", "chick", "heck", "buck", "duck", "tuck", "muck",
            "key", "they", "obey", "prey", "grey", "survey", "convey", "hey", "money", "honey",
            "valley", "monkey", "turkey", "jockey", "journey", "donkey", "alley", "chimney",
            "eye", "dye", "bye", "rye", "aye", "lye", "sweetheart"}]
    if odd:
        why.append("odd words: " + " ".join(sorted(set(odd))))
    if "[" in eng and "]" in eng:
        why.append("brackets")
    # a rendering far shorter than its source dropped something
    if len(src) > 60 and len(eng) < 0.45 * len(src):
        why.append("too short")
    return why


PROMPT = (
    "You are translating Theuerdank (1517), Emperor Maximilian I's allegorical "
    "chivalric poem in rhymed couplets, from Early New High German into plain, "
    "literal English. The spelling is unmodernised: vnd/vnnd = und (and), nit = "
    "nicht (not), Er = he (never the English word 'Er'), Sy = she or they, Ir = "
    "you (plural) or their, Ich = I, Eüch/Ewr = you/your, aber = but, doch = "
    "yet, dieweil = while, darumb = therefore. The hero is Tewrdannck (Theuerdank); "
    "his enemies are the three captains Fürwittig (Rashness), Vnfalo (Misfortune) "
    "and Neydelhart (Envy); the Ernhold is his herald and Ernreich the queen. The "
    "text has OCR noise; read through it for the sense. Terms: gemahel = wife or "
    "husband (consort); werber = suitors; geferlicheit/geuerlicheit = peril or danger; "
    "Gembs/Gembsen = chamois; Clausen/Klause = a fortified mountain pass; pass = "
    "pass or checkpoint; Fürwitz = rashness; Held = hero; leyd = grief; trew = "
    "faithful; pot/potten = messenger(s); herr/herre = lord; Künigin = queen; "
    "tochter = daughter; rat/Rät = council/counsellors; Ritter = knight. Translate "
    "what the text says; do not embellish and do not invent.\n\n"
    "{context}"
    "Translate ONLY the passage below, into complete natural English sentences, "
    "with no German words left in it (names excepted), no brackets and no notes. "
    "Output the English alone.\n\nPASSAGE:\n{text}")


def ask(model: str, host: str, prompt: str, timeout: int = 300) -> str:
    r = requests.post(f"{host}/api/chat", json={
        "model": model, "stream": False, "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.2, "num_predict": 700}}, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


PASS2 = Path("cache/theuerdank_pass2.jsonl")


def context_for(us: list[str], i: int) -> str:
    ctx = ""
    if i > 0:
        ctx += f"The sentence before it (for context only): {us[i - 1]}\n"
    if i + 1 < len(us):
        ctx += f"The sentence after it (for context only): {us[i + 1]}\n"
    return ctx + "\n" if ctx else ""


def run_all(a) -> int:
    """Every unit again, one at a time. Appends to PASS2 and resumes from it,
    so an interrupted run (or a GPU someone else wants) loses nothing."""
    import json

    us = units()
    done = set()
    if PASS2.exists():
        for line in PASS2.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["i"])
    todo = [i for i in range(len(us)) if i not in done][:a.limit]
    print(f"{len(us)} units, {len(done)} done, {len(todo)} to go", file=sys.stderr)
    t0 = time.time()
    with open(PASS2, "a", encoding="utf-8") as out:
        for n, i in enumerate(todo, 1):
            try:
                new = ask(a.model, a.host,
                          PROMPT.format(context=context_for(us, i), text=us[i]))
            except requests.RequestException as e:
                print(f"  ! {i}: {e}", file=sys.stderr)
                continue
            new = re.sub(r"^(PASSAGE|English|Translation)\s*:\s*", "", new).strip()
            out.write(json.dumps({"i": i, "sha": mt_cache._sha(us[i]), "new": new},
                                 ensure_ascii=False) + "\n")
            out.flush()
            if n % 50 == 0:
                rate = (time.time() - t0) / n
                print(f"  … {n}/{len(todo)}  {rate:.1f}s each, "
                      f"~{rate * (len(todo) - n) / 60:.0f} min left", file=sys.stderr, flush=True)
    return 0


def apply_all() -> int:
    """Put the second pass into the cache wherever it is acceptable.

    Accepted when it is not empty, has not looped, carries no German or odd
    spelling, and is within a sensible length of the first pass; anything else
    keeps the first pass. The first pass is kept in PASS2 beside the choice."""
    import json

    us = units()
    conn = sqlite3.connect(DB)
    took = kept = 0
    for line in PASS2.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        u, new = us[r["i"]], r["new"]
        row = conn.execute("SELECT english FROM translations WHERE model=? AND src_sha=?",
                           (CACHE_MODEL, r["sha"])).fetchone()
        old = row[0] if row else ""
        ok = (new and not mt_cache.degenerate(new) and not flagged(u, new)
              and 0.6 * len(old) <= len(new) <= 1.8 * max(len(old), 20)
              and new.strip() != old.strip())
        if ok:
            conn.execute("INSERT OR REPLACE INTO translations (model, src_sha, english) "
                         "VALUES (?, ?, ?)", (CACHE_MODEL, r["sha"], new))
            took += 1
        else:
            kept += 1
    conn.commit()
    print(f"second pass taken for {took} units, first pass kept for {kept}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="qwen3:14b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--all", action="store_true",
                    help="translate every unit again, into cache/theuerdank_pass2.jsonl")
    ap.add_argument("--apply", action="store_true",
                    help="write the accepted results of --all into the cache")
    a = ap.parse_args()
    if a.all:
        return run_all(a)
    if a.apply:
        return apply_all()

    us = units()
    conn = sqlite3.connect(DB)
    todo = []
    for i, u in enumerate(us):
        sha = mt_cache._sha(u)
        row = conn.execute("SELECT english FROM translations WHERE model=? AND src_sha=?",
                           (CACHE_MODEL, sha)).fetchone()
        if not row:
            continue
        why = flagged(u, row[0])
        if why:
            todo.append((i, u, row[0], why))
    print(f"{len(us)} units, {len(todo)} flagged", file=sys.stderr)
    from collections import Counter
    c = Counter(w.split(":")[0] for _, _, _, ws in todo for w in ws)
    print(dict(c), file=sys.stderr)
    for i, u, e, ws in todo[:a.show]:
        print(f"[{i}] {ws}\n  DE: {u[:160]}\n  EN: {e[:160]}\n", file=sys.stderr)
    if not a.run:
        return 0

    t0 = time.time()
    done = 0
    for i, u, old, why in todo[:a.limit]:
        ctx = ""
        if i > 0:
            ctx += f"The sentence before it (for context only): {us[i - 1]}\n"
        if i + 1 < len(us):
            ctx += f"The sentence after it (for context only): {us[i + 1]}\n"
        if ctx:
            ctx += "\n"
        try:
            new = ask(a.model, a.host, PROMPT.format(context=ctx, text=u))
        except requests.RequestException as e:
            print(f"  ! {i}: {e}", file=sys.stderr)
            continue
        new = re.sub(r"^(PASSAGE|English|Translation)\s*:\s*", "", new).strip()
        # keep it only if it is better: fewer flags and not a loop
        if new and not mt_cache.degenerate(new) and len(flagged(u, new)) < len(why):
            conn.execute("INSERT OR REPLACE INTO translations (model, src_sha, english) "
                         "VALUES (?, ?, ?)", (CACHE_MODEL, mt_cache._sha(u), new))
            conn.commit()
            done += 1
        if (done and done % 25 == 0):
            print(f"  … {done} improved ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    print(f"{done} of {len(todo[:a.limit])} replaced", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
