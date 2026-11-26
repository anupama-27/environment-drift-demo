"""Table 8. Ablation study (frozen-reference gate, dry-run replay of the same candidates)."""
import statistics

from drift import config
from drift.analysis import RunView, mean, mean_sd, simulate, win_rate
from drift.envs import map_schedule
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(8)
views = [RunView(r) for r in get_runs()]
full = config.ENV_SCHEDULE

ablations = [
    ("A1: Full system", "E1 -> E2 -> E4", "yes (T=0.2 in r4–10)", "yes (v2 in r8–10)", "yes (ref=r0, age k)",
     dict(schedule=full)),
    ("A2: No decoding changes", "E1 -> E1 -> E3", "no (T=0.0 fixed)", "yes (v2 in r8–10)", "yes (ref=r0, age k)",
     dict(schedule=map_schedule(full, {"E2": "E1", "E4": "E3"}))),
    ("A3: No extraction changes", "E1 -> E2 -> E2", "yes (T=0.2 in r4–10)", "no (v1 fixed)", "yes (ref=r0, age k)",
     dict(schedule=map_schedule(full, {"E3": "E1", "E4": "E2"}))),
    ("A4: Fixed reference age", "E1 -> E2 -> E4", "yes (T=0.2 in r4–10)", "yes (v2 in r8–10)", "no (ref=r(k-1), age 1)",
     dict(schedule=full, fixed_age=1)),
]

rows = []
by_name = {}
for name, sched_str, dec, ext, age, kw in ablations:
    res = [simulate(v, "P1", with_records=True, **kw) for v in views]
    by_name[name] = res
    ac = sum(r["accepted"] for r in res)
    fa = sum(r["false_accepts"] for r in res)
    pooled_str = f"{fa}/{ac} ({100 * fa / ac:.1f}%)" if ac else "0/0 (n/a)"
    log.info("%s (%s) %s -> infl=%s, fa_per_seed=%s, pooled=%s",
             name, sched_str, kw,
             [round(100 * r["inflation"], 2) for r in res],
             [f"{r['false_accepts']}/{r['accepted']}" for r in res],
             pooled_str)
    rows.append((
        name, sched_str, dec, ext, age,
        mean_sd([100 * r["inflation"] for r in res]),
        mean_sd([None if r["false_accept_rate"] is None else 100 * r["false_accept_rate"] for r in res]),
        pooled_str,
    ))

# Paired seed-level differences & 2x2 factorial interaction on rounds 8-10 for notes
a1_inf = [100 * r["inflation"] for r in by_name["A1: Full system"]]
a2_inf = [100 * r["inflation"] for r in by_name["A2: No decoding changes"]]
a3_inf = [100 * r["inflation"] for r in by_name["A3: No extraction changes"]]
diff_12 = mean_sd([x - y for x, y in zip(a1_inf, a2_inf)])
diff_13 = mean_sd([x - y for x, y in zip(a1_inf, a3_inf)])

r8_by_env = {e: [] for e in ("E1", "E2", "E3", "E4")}
all_by_env = {e: [] for e in ("E1", "E2", "E3", "E4")}
for v in views:
    h0 = v.run["snapshots"][0]["prompt"]
    for e in r8_by_env:
        r8_by_env[e].append(mean(
            100 * (win_rate(v.labels(c["prompt"], e), v.stored(h0, "E1", e))
                   - win_rate(v.labels(c["prompt"], e), v.rerun(h0, e)))
            for c in v.run["candidates"] if c["round"] >= 8
        ))
        all_by_env[e].append(mean(
            100 * (win_rate(v.labels(c["prompt"], e), v.stored(h0, "E1", e))
                   - win_rate(v.labels(c["prompt"], e), v.rerun(h0, e)))
            for c in v.run["candidates"]
        ))
inter_r8 = mean_sd([
    (r8_by_env["E4"][i] - r8_by_env["E2"][i]) - (r8_by_env["E3"][i] - r8_by_env["E1"][i])
    for i in range(len(views))
])
inter_all = mean_sd([
    (all_by_env["E4"][i] - all_by_env["E2"][i]) - (all_by_env["E3"][i] - all_by_env["E1"][i])
    for i in range(len(views))
])

# Pure environment-age=1 control holding reference prompt fixed at h0
h0_age1_infs, h0_age1_acc, h0_age1_fa = [], 0, 0
for v in views:
    h0 = v.run["snapshots"][0]["prompt"]
    inc = h0
    infs = []
    for c in v.run["candidates"]:
        k = c["round"]
        X = v.env_at(k, full)
        ref_e = v.env_at(max(0, k - 1), full)
        c_lab = v.labels(c["prompt"], X)
        ref_lab = v.stored(h0, ref_e, X)
        rer_lab = v.rerun(h0, X)
        infs.append(100 * (win_rate(c_lab, ref_lab) - win_rate(c_lab, rer_lab)))
        w = sum(1 for x, y in zip(c_lab, ref_lab) if x and not y)
        l = sum(1 for x, y in zip(c_lab, ref_lab) if y and not x)
        if w > l:
            h0_age1_acc += 1
            if not (v.gt_acc(c["prompt"], X) > v.gt_acc(inc, X)):
                h0_age1_fa += 1
            inc = c["prompt"]
    h0_age1_infs.append(mean(infs))
h0_age1_inf_str = mean_sd(h0_age1_infs)
h0_age1_fa_str = f"{h0_age1_fa}/{h0_age1_acc} = {100 * h0_age1_fa / h0_age1_acc:.1f}%"

write_table(
    8, "Ablation study",
    ["Ablation", "Round schedule (0–3 / 4–7 / 8–10)", "Decoding changes enabled",
     "Extraction changes enabled", "Reference-age variation enabled",
     "Drift inflation (pp)", "False-accept rate, mean ± sd (%)",
     "Pooled false accepts / accepted (%)"],
    rows,
    notes=[
        f"Controlled single-factor design over {len(views)} seeds ({len(views) * config.ROUNDS} candidate evaluations): "
        "all rows replay the exact same candidate prompts, seeds, 200 GSM8K evaluation items, and frozen-reference "
        "promotion rule (P1: accept iff wins > losses).",
        "Explicit schedule mapping: E1 = (temp=0.0, v1_strict), E2 = (temp=0.2, v1_strict), E3 = (temp=0.0, v2_lenient), "
        "E4 = (temp=0.2, v2_lenient). A2 differs from A1 only by disabling the temp=0.0->0.2 shift in rounds 4–10 "
        "(E2->E1, E4->E3); A3 differs from A1 only by disabling the v1->v2 extractor shift in rounds 8–10 (E3->E1, E4->E2).",
        f"Descriptive schedule pattern vs. factorial contrast: across the 11-round schedule, A2 activates E3 in only 3/11 "
        f"rounds (r8–10) while A3 activates E2 in 7/11 rounds (r4–10). Paired seed-level inflation differences are "
        f"A1 - A2 = {diff_12} pp and A1 - A3 = {diff_13} pp; on a balanced 2x2 factorial evaluation across all 4 environments, "
        f"the interaction contrast (E4 - E2) - (E3 - E1) is {inter_r8} pp on rounds 8–10 and {inter_all} pp across all 11 rounds (approximately additive).",
        "Both unweighted per-seed mean ± sd (%) and pooled counts (false accepts / accepted candidates across all seeds) "
        "are reported because per-seed accepted denominators are small (2 to 9 accepted candidates per seed).",
        f"A4 (fixed_age=1) compares round k against snapshots[max(0, k-1)] stored under env_at(k-1). Because environment "
        f"shifts occur only at rounds 4 and 8, A4 compares matched environments (ref_env == cur_env) on 9/11 rounds and "
        f"cross-environment outputs on only 2/11 boundary rounds (k=4, 8), while also updating the reference prompt to "
        f"the round-(k-1) snapshot (holding the prompt fixed at h0 with env_at(k-1) yields {h0_age1_inf_str} pp inflation and {h0_age1_fa_str} pooled false accepts).",
    ],
)

