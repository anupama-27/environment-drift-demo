"""Cross-check gt's box reading against HF math-verify on every distinct (last box, gold) pair.

Usage: .venv/bin/python -I mathverify_crosscheck.py <audit_dir>
math-verify is given only the last \\boxed{...} (so its unanchored fallbacks cannot fire) and the
gold as a plain number; we compare its verdict with gt's is-correct verdict.
"""
import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gt_scorer import _boxes, numeric_equal, parse_value  # noqa: E402
from math_verify import parse, verify  # noqa: E402
from math_verify.parser import LatexExtractionConfig  # noqa: E402

csv.field_size_limit(10**9)
rows = list(csv.DictReader(open(os.path.join(sys.argv[1], "all_outputs.csv"), newline="")))
pairs = Counter()
for r in rows:
    b = _boxes(r["output"])
    if b:
        pairs[(b[-1][1], float(r["gold"]))] += 1
agree = Counter()
dis = []
for (box, gold), n in pairs.items():
    g = numeric_equal(parse_value(box), gold)
    try:
        pred = parse("$\\boxed{" + box + "}$", extraction_config=[LatexExtractionConfig()],
                     parsing_timeout=None)
        mv = bool(pred) and verify(parse(f"${gold:g}$", parsing_timeout=None), pred, timeout_seconds=None)
    except Exception as e:  # report, never hide
        mv = f"error:{type(e).__name__}"
    agree[(g, mv)] += n
    if g != mv:
        dis.append((n, box, gold, g, mv))
print("distinct (box,gold) pairs:", len(pairs), "rows:", sum(pairs.values()))
print("(gt_correct, mathverify_correct) -> rows:", dict(agree))
with open(os.path.join(HERE, "mathverify_disagreements.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rows", "box", "gold", "gt_correct", "mathverify_correct"])
    for d in sorted(dis, key=lambda d: -d[0]):
        w.writerow(d)
for d in sorted(dis, key=lambda d: -d[0])[:40]:
    print(d)
