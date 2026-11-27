"""Merge hand labels into the audit CSVs and compute agreement / false-credit statistics.
Usage: .venv/bin/python -I score_audit.py"""
import csv
import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import labels_a  # noqa: E402
import labels_b  # noqa: E402


def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def pct(x):
    return f"{100 * x:.1f}%"


out = []
# ---------------- (a)
A = list(csv.DictReader(open(os.path.join(HERE, "audit_sample_a.csv"))))
for s in A:
    s["label"], s["rationale"] = labels_a.SPECIAL.get(s["audit_id"], labels_a.G)
    s["committed_gold"] = int(s["audit_id"] not in labels_a.NOT_COMMITTED)
cols = list(A[0].keys())
with open(os.path.join(HERE, "audit_labels_a.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(A)
n = len(A)
lab = Counter(s["label"] for s in A)
out.append(f"(a) last_number fallback, v2 marks right: n={n} labels={dict(lab)}")
k = lab["COINCIDENTAL"]
lo, hi = wilson(k, n)
out.append(f"  false-credit (COINCIDENTAL) = {k}/{n} = {pct(k / n)}  Wilson95 [{pct(lo)}, {pct(hi)}]")
k2 = lab["COINCIDENTAL"] + lab["AMBIGUOUS"]
lo, hi = wilson(k2, n)
out.append(f"  false-credit incl. AMBIGUOUS = {k2}/{n} = {pct(k2 / n)}  Wilson95 [{pct(lo)}, {pct(hi)}]")
nc = sum(1 - s["committed_gold"] for s in A)
lo, hi = wilson(nc, n)
out.append(f"  no committed gold answer (truncated/degenerate) = {nc}/{n} = {pct(nc / n)}  Wilson95 [{pct(lo)}, {pct(hi)}]")
# post-stratified estimate (proportional allocation with floors -> reweight)
pop = Counter()
smp = Counter()
bad = Counter()
for s in A:
    pop[s["stratum"]] = int(s["stratum_pop"])
    smp[s["stratum"]] += 1
    bad[s["stratum"]] += s["label"] == "COINCIDENTAL"
N = sum(pop.values())
est = sum(pop[h] / N * bad[h] / smp[h] for h in pop)
out.append(f"  stratum-weighted false-credit estimate = {pct(est)} (population {N} rows)")
out.append("  by decoding: " + ", ".join(
    f"{d}: {sum(s['label'] == 'COINCIDENTAL' for s in A if d in s['stratum'])}/{sum(d in s['stratum'] for s in A)}"
    for d in ("greedy", "sampled")))
# gt agreement on (a): gt should credit iff committed_gold
agree = sum(int(s["gt_correct"]) == s["committed_gold"] for s in A)
tp = sum(int(s["gt_correct"]) == 1 and s["committed_gold"] == 1 for s in A)
fp = sum(int(s["gt_correct"]) == 1 and s["committed_gold"] == 0 for s in A)
fn = sum(int(s["gt_correct"]) == 0 and s["committed_gold"] == 1 for s in A)
lo, hi = wilson(agree, n)
out.append(f"  gt vs label (credit iff committed to gold): agree {agree}/{n} = {pct(agree / n)} "
           f"Wilson95 [{pct(lo)}, {pct(hi)}]; gt credits {tp + fp}: {fp} false credits; misses {fn} genuine")
gen = [s for s in A if s["label"] == "GENUINE"]
miss = [s for s in gen if s["gt_correct"] == "0"]
out.append(f"  gt recall on GENUINE = {len(gen) - len(miss)}/{len(gen)}; misses: " + ", ".join(s["audit_id"] for s in miss))
out.append(f"  v2 vs label: v2 credits all {n}; agrees on {sum(s['committed_gold'] for s in A)}/{n}")

# ---------------- (b)
B = list(csv.DictReader(open(os.path.join(HERE, "audit_sample_b.csv"))))
for s in B:
    s["label"], s["rationale"] = labels_b.SPECIAL.get(s["audit_id"], labels_b.DEFAULT)
    truth = {"CREDIT": 1, "NO_CREDIT": 0}.get(s["label"])
    for sc in ("v1", "v2", "gt", "gt_strict"):
        key = sc + "_correct" if sc != "gt_strict" else None
        val = int(s[key]) if key else int(s["gt_strict"] != "" and abs(float(s["gt_strict"]) - float(s["gold"])) < 1e-6 * max(1, abs(float(s["gold"]))))
        s[f"{sc}_right"] = "" if truth is None else int(val == truth)
    s["right_scorers"] = "+".join(sc for sc in ("v1", "v2", "gt") if s[f"{sc}_right"] == 1) or "none"
cols = list(B[0].keys())
with open(os.path.join(HERE, "audit_labels_b.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(B)
nb = len(B)
out.append(f"\n(b) other-rule disagreements: n={nb} labels={dict(Counter(s['label'] for s in B))}")
for sc in ("v1", "v2", "gt", "gt_strict"):
    k = sum(s[f"{sc}_right"] == 1 for s in B)
    lo, hi = wilson(k, nb)
    out.append(f"  {sc:9s} right on {k}/{nb} = {pct(k / nb)} Wilson95 [{pct(lo)}, {pct(hi)}]")
out.append("  by stratum (v1/v2/gt right):")
for st in dict.fromkeys(s["stratum"] for s in B):
    ss = [s for s in B if s["stratum"] == st]
    out.append(f"    {st:18s} n={len(ss):2d} pop={ss[0]['stratum_pop']:>4s}  " + "  ".join(
        f"{sc}={sum(s[f'{sc}_right'] == 1 for s in ss)}" for sc in ("v1", "v2", "gt")))
out.append("  gt wrong: " + ", ".join(f"{s['audit_id']}({s['stratum']})" for s in B if s["gt_right"] == 0))
# ---------------- combined gt agreement
allk = agree + sum(s["gt_right"] == 1 for s in B)
alln = n + nb
lo, hi = wilson(allk, alln)
out.append(f"\nCombined gt agreement with hand labels: {allk}/{alln} = {pct(allk / alln)} Wilson95 [{pct(lo)}, {pct(hi)}]")
gt_fp = fp + sum(s["gt_correct"] == "1" and s["label"] == "NO_CREDIT" for s in B)
gt_cred = sum(s["gt_correct"] == "1" for s in A) + sum(s["gt_correct"] == "1" for s in B)
out.append(f"gt false credits (credits a non-committed/wrong answer): {gt_fp}/{gt_cred} gt credits")
txt = "\n".join(out)
print(txt)
open(os.path.join(HERE, "audit_results.txt"), "w").write(txt + "\n")
