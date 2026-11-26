"""Table 3. Main comparison of reference-refresh policies (mean ± sd over seeds)."""
from drift.analysis import POLICIES, RunView, mean_sd, simulate
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(3)
views = [RunView(r) for r in get_runs()]

rows = []
for p, (name, rule) in POLICIES.items():
    res = [simulate(v, p) for v in views]
    for s, r in zip([v.run["seed"] for v in views], res):
        log.info("seed %d %s: %s", s, p, r)
    rows.append((f"{p}: {name}", rule,
                 mean_sd([100 * r["final_gt_acc"] for r in res]),
                 mean_sd([None if r["false_accept_rate"] is None else 100 * r["false_accept_rate"] for r in res]),
                 mean_sd([r["total_calls"] for r in res], 0),
                 mean_sd([r["refreshes"] for r in res], 0)))

write_table(3, "Main comparison of reference-refresh policies",
            ["Policy", "Reference refresh rule", "Ground-truth accuracy (%) ↑", "False-accept rate (%) ↓",
             "Model calls (logical, estimated) ↓", "Reference refreshes ↓"], rows,
            notes=["Ground-truth accuracy = final incumbent under the final environment.",
                   "Model calls are logical (estimated) counts: simulate() is a dry run, so it adds up the proposals, dev passes, candidate evaluations and refreshes each policy would need.",
                   "The policies are reference-management rules compared on the same candidate pool, not different ways of improving accuracy; accuracy is capped by the best candidate in the pool.",
                   "Policies replay the same candidate pool in dry-run mode."])

