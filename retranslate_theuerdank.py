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


JUDGE = Path("cache/theuerdank_judge.jsonl")
BEFORE = "cache/mt.db.before_pass2"      # the first pass, as it stood


JUDGE_PROMPT = (
    "Below is a passage of Early New High German verse (Theuerdank, 1517, spelling "
    "unmodernised: vnd = and, nit = not, Er = he, Sy = she or they) and two English "
    "translations of it, A and B. Decide which is the more FAITHFUL translation: "
    "first, which says what the German says, with nothing dropped, added or "
    "invented and no German word left standing; second, which reads as natural "
    "English. Answer with exactly one letter: A, B, or T if they are equally good.\n\n"
    "GERMAN:\n{de}\n\nA:\n{a}\n\nB:\n{b}\n\nAnswer (A, B or T):")


def judge_all(a) -> int:
    """For every unit, a second model chooses between the first-pass English and
    the second-pass English. Each is judged twice, in both orders, because a
    judge model leans toward whichever it is shown first; a verdict that flips
    with the order is a tie. Appends to JUDGE and resumes from it."""
    import json
    import random

    us = units()
    old_conn = sqlite3.connect(BEFORE)
    new = {}
    for line in PASS2.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        new[r["i"]] = r
    done = set()
    if JUDGE.exists():
        for line in JUDGE.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["i"])
    todo = [i for i in sorted(new, reverse=a.reverse) if i not in done]
    todo = todo[int(len(todo) * a.start_frac):][:a.limit]
    print(f"{len(new)} pairs, {len(done)} judged, {len(todo)} to go (judge {a.judge})",
          file=sys.stderr)
    t0 = time.time()

    def pick(de: str, a_txt: str, b_txt: str) -> str:
        try:
            out = ask(a.judge, a.host, JUDGE_PROMPT.format(de=de, a=a_txt, b=b_txt))
        except requests.RequestException:
            return "?"
        m = re.search(r"\b([ABT])\b", out.strip().upper()[:12])
        return m.group(1) if m else "?"

    with open(JUDGE, "a", encoding="utf-8") as out:
        for n, i in enumerate(todo, 1):
            r = new[i]
            row = old_conn.execute("SELECT english FROM translations WHERE model=? "
                                   "AND src_sha=?", (CACHE_MODEL, r["sha"])).fetchone()
            old = row[0] if row else ""
            nw = r["new"]
            if not old or not nw or old.strip() == nw.strip():
                verdict = "same" if old.strip() == nw.strip() else ("new" if nw else "old")
            else:
                v1 = pick(us[i], old, nw)            # A = old, B = new
                v2 = pick(us[i], nw, old)            # A = new, B = old
                new_votes = (v1 == "B") + (v2 == "A")
                old_votes = (v1 == "A") + (v2 == "B")
                verdict = ("new" if new_votes > old_votes else
                           "old" if old_votes > new_votes else "tie")
            out.write(json.dumps({"i": i, "verdict": verdict}) + "\n")
            out.flush()
            if n % 100 == 0:
                rate = (time.time() - t0) / n
                print(f"  … {n}/{len(todo)}  {rate:.1f}s each, "
                      f"~{rate * (len(todo) - n) / 60:.0f} min left", file=sys.stderr, flush=True)
    from collections import Counter
    c = Counter(json.loads(l)["verdict"] for l in JUDGE.read_text(encoding="utf-8").splitlines())
    print(dict(c), file=sys.stderr)
    return 0


RECHECK = Path("cache/theuerdank_recheck.jsonl")


def recheck_vetoes(a) -> int:
    """A reasoning model re-decides the pairs the judge vetoed.

    The judge answers in one token and leans toward the first answer it is
    shown; this one is allowed to think before it answers. Each pair goes in
    both orders and the verdict is only 'old' or 'new' when both agree."""
    import json

    us = units()
    old_conn = sqlite3.connect(BEFORE)
    new = {}
    for line in PASS2.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        new[r["i"]] = r
    verdict = {}
    for line in JUDGE.read_text(encoding="utf-8").splitlines():
        v = json.loads(line)
        verdict[v["i"]] = v["verdict"]
    vetoed = sorted(i for i, v in verdict.items() if v == "old")
    done = set()
    if RECHECK.exists():
        done = {json.loads(l)["i"] for l in RECHECK.read_text(encoding="utf-8").splitlines()}
    if a.ids_file:
        keep = set(json.loads(Path(a.ids_file).read_text()))
        vetoed = [i for i in vetoed if i in keep]
    todo = [i for i in vetoed if i not in done][:a.limit]
    print(f"{len(vetoed)} vetoed, {len(done)} rechecked, {len(todo)} to go "
          f"(arbiter {a.arbiter})", file=sys.stderr)

    def think(de: str, a_txt: str, b_txt: str) -> str:
        prompt = JUDGE_PROMPT.format(de=de, a=a_txt, b=b_txt).replace(
            "Answer (A, B or T):", "Think it through, then end with 'Answer: A', "
            "'Answer: B' or 'Answer: T'.")
        try:
            r = requests.post(f"{a.host}/api/chat", json={
                "model": a.arbiter, "stream": False, "think": True,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.2, "num_predict": 2500}}, timeout=600)
            r.raise_for_status()
            out = r.json()["message"]["content"]
        except requests.RequestException:
            return "?"
        m = re.findall(r"Answer:\s*\**\s*([ABT])\b", out)
        return m[-1] if m else "?"

    with open(RECHECK, "a", encoding="utf-8") as out:
        for i in todo:
            old = old_conn.execute("SELECT english FROM translations WHERE model=? AND "
                                   "src_sha=?", (CACHE_MODEL, new[i]["sha"])).fetchone()[0]
            nw = new[i]["new"]
            v1 = think(us[i], old, nw)           # A = old
            v2 = think(us[i], nw, old)           # A = new
            o = (v1 == "A") + (v2 == "B")
            n = (v1 == "B") + (v2 == "A")
            res = "old" if o > n else "new" if n > o else "tie"
            out.write(json.dumps({"i": i, "recheck": res, "v": [v1, v2]}) + "\n")
            out.flush()
    from collections import Counter
    c = Counter(json.loads(l)["recheck"] for l in RECHECK.read_text(encoding="utf-8").splitlines())
    print(dict(c), file=sys.stderr)
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
    verdicts = {}
    if JUDGE.exists():
        for line in JUDGE.read_text(encoding="utf-8").splitlines():
            v = json.loads(line)
            verdicts[v["i"]] = v["verdict"]
        print(f"using {len(verdicts)} judge verdicts: the judge's 'old' vetoes a "
              f"replacement; 'new' and 'tie' (it cannot tell) go to the rules",
              file=sys.stderr)
    for line in PASS2.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        u, new = us[r["i"]], r["new"]
        if verdicts.get(r["i"]) == "old":
            kept += 1
            continue
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
    ap.add_argument("--judge-all", action="store_true",
                    help="a second model chooses, per unit, between the two passes")
    ap.add_argument("--judge", default="gemma4:12b", help="the judge model")
    ap.add_argument("--recheck-vetoes", action="store_true",
                    help="a reasoning model re-decides the pairs the judge vetoed")
    ap.add_argument("--arbiter", default="qwen3:14b", help="the --recheck-vetoes model")
    ap.add_argument("--ids-file", help="with --recheck-vetoes, a JSON list of unit numbers")
    ap.add_argument("--start-frac", type=float, default=0.0,
                    help="with --judge-all, skip this fraction of the remaining units, "
                         "so a third process can take the middle")
    ap.add_argument("--reverse", action="store_true",
                    help="with --judge-all, work from the last unit backwards, so a second "
                         "process can share the job with a first")
    a = ap.parse_args()
    if a.recheck_vetoes:
        return recheck_vetoes(a)
    if a.judge_all:
        return judge_all(a)
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
