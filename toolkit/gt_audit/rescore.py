"""Re-score every decoded output with v1, v2 and gt.

Usage: .venv/bin/python -I rescore.py <audit_dir>
Writes gt_scores.csv (one row per output, no text) and gt_labels.json:
  gt_labels[seed][prompt_hash][decoding][tag] = 200 0/1 labels (test split), decoding in greedy/sample.
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # toolkit/
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
from drift.extract import extract_v1, extract_v2, is_correct  # noqa: E402
from gt_scorer import extract_gt_strict, gt_rule, numeric_equal  # noqa: E402

csv.field_size_limit(10**9)


def load_rows(audit_dir):
    return list(csv.DictReader(open(os.path.join(audit_dir, "all_outputs.csv"), newline="")))


def main(audit_dir):
    rows = load_rows(audit_dir)
    out = []
    labels = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    chk = Counter()
    for r in rows:
        t, gold = r["output"], float(r["gold"])
        v1, v2 = extract_v1(t), extract_v2(t)
        g, rule = gt_rule(t)
        gs = extract_gt_strict(t)
        c1, c2 = int(is_correct(v1, gold)), int(is_correct(v2, gold))
        cg, cgs = int(numeric_equal(g, gold)), int(numeric_equal(gs, gold))
        chk[(c1 == int(r["v1_correct"]), c2 == int(r["v2_correct"]))] += 1
        out.append({k: r[k] for k in ("seeds", "prompt_hash", "decoding", "tag", "split", "item_id", "gold",
                                      "v2_rule")} | {
            "v1": v1, "v2": v2, "gt": g, "gt_rule": rule, "gt_strict": gs,
            "v1_correct": c1, "v2_correct": c2, "gt_correct": cg, "gt_strict_correct": cgs,
            "has_box": int("\\boxed" in t), "chars": len(t)})
        if r["split"] == "test":
            dec = "greedy" if r["decoding"].startswith("greedy") else "sample"
            idx = int(r["item_id"].split("-")[1])
            for s in r["seeds"].split(","):
                d = labels[s][r["prompt_hash"]][dec].setdefault(r["tag"], {"gt": [None] * 200, "gt_strict": [None] * 200})
                d["gt"][idx] = cg
                d["gt_strict"][idx] = cgs
    print("csv label self-check (v1 ok, v2 ok):", dict(chk))
    with open(os.path.join(HERE, "gt_scores.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    missing = sum(x is None for s in labels.values() for h in s.values() for d in h.values()
                  for t in d.values() for k in t.values() for x in k)
    print("missing gt labels:", missing)
    json.dump(labels, open(os.path.join(HERE, "gt_labels.json"), "w"))
    print("rule counts:", Counter(o["gt_rule"] for o in out))


if __name__ == "__main__":
    main(sys.argv[1])
