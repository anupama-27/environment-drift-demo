"""Draw the hand-audit samples (fixed seed) and dump them for reading.

Usage: .venv/bin/python -I draw_audit_sample.py <audit_dir>
Writes audit_sample_a.csv / audit_sample_b.csv (ids + extractions, labels filled in later) and
audit_dump_a.txt / audit_dump_b.txt (question + full response, for the annotator).
(a) last_number-fallback rows that v2 marks right, stratified by seed group x greedy/sampled,
    proportional allocation with a floor of 6 per stratum, ~120 total, distinct texts.
(b) rows from other rules where v1, v2 and gt disagree on correctness.
"""
import csv
import hashlib
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261024
csv.field_size_limit(10**9)

rows = list(csv.DictReader(open(os.path.join(sys.argv[1], "all_outputs.csv"), newline="")))
scores = list(csv.DictReader(open(os.path.join(HERE, "gt_scores.csv"))))
assert len(rows) == len(scores)
for i, (r, s) in enumerate(zip(rows, scores)):
    assert (r["item_id"], r["prompt_hash"], r["tag"]) == (s["item_id"], s["prompt_hash"], s["tag"])
    s["row"] = i
    s["sha"] = hashlib.sha1(r["output"].encode()).hexdigest()[:12]

rng = random.Random(SEED)


def dec(s):
    return "greedy" if s["decoding"].startswith("greedy") else "sampled"


def take(pool, k, used):
    pool = sorted(pool, key=lambda s: s["row"])
    rng.shuffle(pool)
    out = []
    for s in pool:
        if s["sha"] in used:
            continue
        used.add(s["sha"])
        out.append(s)
        if len(out) == k:
            break
    return out


used = set()
# ---- (a)
ln = [s for s in scores if s["v2_rule"] == "last_number" and s["v2_correct"] == "1"]
strata = defaultdict(list)
for s in ln:
    g = s["seeds"] if "," not in s["seeds"] else "shared"
    strata[(g, dec(s))].append(s)
TARGET = 120
alloc = {k: max(6, round(TARGET * len(v) / len(ln))) for k, v in strata.items() if k[0] != "shared"}
alloc.update({k: min(3, len(v)) for k, v in strata.items() if k[0] == "shared"})
A = []
for k in sorted(strata):
    for s in take(strata[k], alloc[k], used):
        s["stratum"] = f"{k[0]}|{k[1]}"
        s["stratum_pop"] = len(strata[k])
        A.append(s)
# ---- (b)
def cell(s):
    return (s["v2_rule"], s["v1_correct"], s["v2_correct"], s["gt_correct"])


B_PLAN = [  # (predicate, k, name)
    (lambda s: s["v1_correct"] == "0" and s["v2_correct"] == "0" and s["gt_correct"] == "1", 99, "gt_only_right"),
    (lambda s: cell(s) == ("bold", "0", "1", "0"), 18, "bold_v2_only"),
    (lambda s: cell(s) == ("bold", "0", "1", "1"), 15, "bold_v2_gt"),
    (lambda s: cell(s) == ("boxed_loose", "0", "1", "0"), 12, "boxloose_v2_only"),
    (lambda s: cell(s) == ("boxed_loose", "0", "1", "1"), 10, "boxloose_v2_gt"),
    (lambda s: cell(s) == ("answer_is", "0", "1", "1"), 12, "answeris_v2_gt"),
]
B = []
for pred, k, name in B_PLAN:
    pool = [s for s in scores if pred(s)]
    for s in take(pool, k, used):
        s["stratum"] = name
        s["stratum_pop"] = len(pool)
        B.append(s)

COLS = ["audit_id", "row", "seeds", "decoding", "tag", "split", "pass", "item_id", "prompt_hash", "stratum",
        "stratum_pop", "v2_rule", "gt_rule", "gold", "v1", "v2", "gt", "v1_correct", "v2_correct",
        "gt_correct", "gt_strict", "label", "rationale"]
for name, sample in (("a", A), ("b", B)):
    with open(os.path.join(HERE, f"audit_sample_{name}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for i, s in enumerate(sample):
            s["audit_id"] = f"{name.upper()}{i + 1:03d}"
            s["pass"] = f"{dec(s)}-{'stored' if s['tag'] == 'current' else 'rerun'}"
            s["label"] = s["rationale"] = ""
            w.writerow(s)
    with open(os.path.join(HERE, f"audit_dump_{name}.txt"), "w") as f:
        for s in sample:
            r = rows[s["row"]]
            f.write(f"\n\n######## {s['audit_id']} | gold={s['gold']} v1={s['v1']} v2={s['v2']} "
                    f"gt={s['gt']} ({s['gt_rule']}) rule={s['v2_rule']} | {s['stratum']}\n")
            f.write(f"Q: {r['question']}\n---\n{r['output']}\n")
    print(name, len(sample))
print("alloc a:", sorted(alloc.items()))
