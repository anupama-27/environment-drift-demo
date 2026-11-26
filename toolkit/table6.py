"""Table 6. False-accept analysis.

Each refresh policy is replayed over the same candidate pool, and every accept is checked
against the ground truth from Table 5. An accept is false when the candidate's ground-truth
accuracy is no greater than the incumbent's under the environment in force at that round.

Counts are pooled over seeds, because a count is only meaningful over a fixed denominator.
Table 3 reports the same false-accept rate averaged over seeds instead, which gives a
different number; the note below carries both so the two tables reconcile.

Writes results/table6.md, results/table6_errors.md and results/table6_decisions.csv.
"""
import csv
import os

from drift import config
from drift.analysis import POLICIES, RunView, ci95, mean_sd, pooled_rate, simulate
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(6)
views = [RunView(r) for r in get_runs()]

results = {p: [simulate(v, p, with_records=True) for v in views] for p in POLICIES}
for p, res in results.items():
    for v, r in zip(views, res):
        log.info("seed %d %s: evaluated=%d accepted=%d false_accepts=%d false_rejects=%d",
                 v.run["seed"], p, r["evaluated"], r["accepted"], r["false_accepts"],
                 r["false_rejects"])

rows, error_rows = [], []
for p, (name, rule) in POLICIES.items():
    res = results[p]
    ev = sum(r["evaluated"] for r in res)
    ac = sum(r["accepted"] for r in res)
    fa = sum(r["false_accepts"] for r in res)
    fr = sum(r["false_rejects"] for r in res)
    seed_rates = [None if r["false_accept_rate"] is None else 100 * r["false_accept_rate"]
                  for r in res]
    rows.append((name, ev, ac, fa, pooled_rate(fa, ac),
                 mean_sd(seed_rates, 1), ci95(seed_rates, 1)))
    error_rows.append((
        f"{p}: {name}", ev, ac, fa, pooled_rate(fa, ac),
        fr, pooled_rate(fr, ev - ac), pooled_rate(fa + fr, ev), mean_sd(seed_rates, 1)))

seed_list = ", ".join(str(v.run["seed"]) for v in views)
perseed_frac = "; ".join(
    POLICIES[p][0].lower() + " "
    + ", ".join(f"{r['false_accepts']}/{r['accepted']}" for r in results[p])
    for p in POLICIES)

# Worked reconciliation for the policy the paper leads with, built from the same numbers as the table.
lead = "P3" if "P3" in POLICIES else next(iter(POLICIES))
lead_res = results[lead]
lead_fa = sum(r["false_accepts"] for r in lead_res)
lead_ac = sum(r["accepted"] for r in lead_res)
lead_mean = mean_sd([None if r["false_accept_rate"] is None else 100 * r["false_accept_rate"]
                     for r in lead_res], 1)

write_table(6, "False-accept analysis",
            ["Refresh policy", "Candidates evaluated", "Candidates accepted",
             "Accepted candidates with no ground-truth improvement",
             "False-accept rate, pooled (%)", "False-accept rate, per-seed mean ± sd (%)",
             "95% CI of the seed-mean (pp)"],
            rows,
            notes=["False-accept rate = accepted candidates whose ground-truth accuracy is no "
                   "greater than the incumbent's, divided by all accepted candidates. The candidate "
                   f"pool is identical across policies, so evaluated is {rows[0][1]} in every row.",
                   "Pooled sums the counts across seeds; the seed-mean averages the five per-seed "
                   f"rates and is the figure Table 3 reports. For {POLICIES[lead][0].lower()} these "
                   f"are {lead_fa}/{lead_ac} = {pooled_rate(lead_fa, lead_ac)}% and {lead_mean}, "
                   "because a seed with one accept weighs the same as a seed with five in the "
                   "average but not in the pool.",
                   f"False accepts / accepts per seed ({seed_list}): {perseed_frac}.",
                   f"Denominators are small: reclassifying one accept moves "
                   f"{POLICIES[lead][0].lower()} by {100 / lead_ac:.1f} pp, and the intervals "
                   "overlap, so the ordering is a direction rather than an established gap.",
                   "Table 7's stale-reference, changed-environment rate covers a subset of these "
                   "accepts, not the same quantity.",
                   "A policy lowers this rate by accepting less; results/table6_errors.md adds the "
                   "improvements each one rejected."])

write_table(6, "Decision errors in both directions",
            ["Policy", "Evaluated", "Accepted", "False accepts", "False-accept rate (%)",
             "False rejects", "False-reject rate (%)", "Total error rate (%)",
             "False-accept rate, per-seed mean ± sd (%)"], error_rows, suffix="_errors",
            notes=["False reject = a candidate with strictly higher ground-truth accuracy that "
                   "the gate turned down; the rate is over rejected candidates.",
                   "Total error rate is over all candidates evaluated, so the two directions are "
                   "comparable on one denominator.",
                   "A policy can lower its false-accept rate simply by accepting less, so the "
                   "false-reject column is needed to tell caution apart from accuracy."])

os.makedirs(config.RESULTS_DIR, exist_ok=True)
csv_path = os.path.join(config.RESULTS_DIR, "table6_decisions.csv")
cols = ["seed", "policy", "cid", "round", "env", "ref_env", "ref_fresh", "wins", "losses",
        "accepted", "inc_acc", "cand_acc", "delta_pp", "outcome", "false_accept", "false_reject"]
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for p in POLICIES:
        for r in results[p]:
            w.writerows({k: rec[k] for k in cols} for rec in r["records"])
log.info("Per-decision detail written to %s", os.path.relpath(csv_path, config.ROOT))

