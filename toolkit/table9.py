"""Table 9. Reproducibility across random seeds."""
import statistics

from drift import config
from drift.analysis import POLICIES, RunView, simulate
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(9)
views = [RunView(r) for r in get_runs()]

rows, by_policy = [], {p: [] for p in POLICIES}
for v in views:
    for p in POLICIES:
        r = simulate(v, p, with_records=True)
        by_policy[p].append(r)
        acc_cids = [rec["cid"] for rec in r["records"] if rec["accepted"]]
        final_inc = acc_cids[-1] if acc_cids else "h0"
        r["final_inc"] = final_inc
        fa_cnt = f"{r['false_accepts']}/{r['accepted']}"
        fa = "n/a" if r["false_accept_rate"] is None else f"{100 * r['false_accept_rate']:.1f}"
        rows.append((
            v.run["seed"], p, final_inc,
            f"{100 * r['final_gt_acc']:.1f}",
            f"{100 * r['inflation']:.2f}",
            fa_cnt, fa, r["total_calls"],
        ))
        log.info("seed=%s policy=%s final_inc=%s acc=%.1f infl=%.2f fa_cnt=%s fa=%s calls=%d",
                 v.run["seed"], p, final_inc, 100 * r["final_gt_acc"],
                 100 * r["inflation"], fa_cnt, fa, r["total_calls"])


def ms(xs, d=1):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return "n/a"
    return f"{statistics.mean(xs):.{d}f} ± {statistics.stdev(xs):.{d}f}"


for p, res in by_policy.items():
    tot_acc = sum(r["accepted"] for r in res)
    tot_fa = sum(r["false_accepts"] for r in res)
    rows.append((
        "Mean ± standard deviation", p, "—",
        ms([100 * r["final_gt_acc"] for r in res]),
        ms([100 * r["inflation"] for r in res], 2),
        f"{ms([r['false_accepts'] for r in res], 1)} / {ms([r['accepted'] for r in res], 1)}",
        ms([None if r["false_accept_rate"] is None else 100 * r["false_accept_rate"] for r in res]),
        ms([r["total_calls"] for r in res], 0),
    ))

for p, res in by_policy.items():
    tot_ev = sum(r["evaluated"] for r in res)
    tot_acc = sum(r["accepted"] for r in res)
    tot_fa = sum(r["false_accepts"] for r in res)
    pooled_fa = f"{100 * tot_fa / tot_acc:.1f}" if tot_acc else "n/a"
    rows.append((
        f"Pooled ({len(views)} seeds, {tot_ev} evals)", p, "—",
        "—", "—",
        f"{tot_fa}/{tot_acc}", pooled_fa,
        sum(r["total_calls"] for r in res),
    ))

write_table(
    9, "Reproducibility across random seeds",
    ["Seed", "Refresh policy", "Final incumbent", "Ground-truth accuracy (%)",
     "Drift inflation (pp)", "False accepts / accepted", "False-accept rate (%)", "Model calls"],
    rows,
    notes=[
        "Seed controls the proposer's dev-error sampling and the temperature-0.2 evaluation decoding.",
        "Auditable denominators: 'False accepts / accepted' reports x/y for every seed/policy (out of 11 evaluated "
        "candidates per seed), followed by both the unweighted per-seed Mean ± standard deviation (matching Table 3) "
        "and the Pooled rate across all seeds (matching Table 6).",
        "Why P2 has 0.00 pp drift inflation yet nonzero false accepts: P2 refreshes the stored reference under the "
        "current environment before every comparison (ref_lab == rerun), making stored-minus-rerun inflation 0 by "
        "policy design rather than independent evidence that drift is absent. A nonzero P2 false-accept rate remains "
        "possible because paired promotion compares the candidate's primary evaluation pass ('current') against the "
        "incumbent's fresh pass ('rerun'), whereas ground-truth accuracy is scored on the canonical 'current' record.",
        "Why final ground-truth accuracy varies across P1/P2/P3 on a shared candidate pool: all three policies replay "
        "the exact same 11 candidates per seed, but each policy updates its running incumbent only when its own gate "
        "accepts (wins > losses). The 'Final incumbent' column reports the last candidate accepted by that policy in "
        "rounds 0–10, scored under the final environment E4.",
        "The 5-seed run (Seeds 1–5) is the primary reproducibility table; the 3-seed subset (table9_seeds1-3.md) is "
        "retained as a legacy/sensitivity analysis at the same post-fix code revision.",
    ],
)

