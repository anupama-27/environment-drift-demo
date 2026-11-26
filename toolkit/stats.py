"""Statistics quoted in the paper that no table script prints.

Covers Figure 4 (drift inflation at reference age 3 with 95% CIs), Figure 6 (pooled false
accepts by reference prompt and stored environment), the Appendix C ablation tests, the
Fisher tests in the Refresh Policies paragraph, and the numbers in the Setup and Evaluation
text. Everything is computed from the saved runs in runs/; no model is called.

    DRIFT_SEEDS=1,2,3,4,5 python3 stats.py

Writes results/stats.md and logs/stats.log.
"""
import logging
import math
import os
import statistics as st
import sys

from drift import config
from drift.analysis import RunView, _T95, age_pairs, pair, simulate, win_rate
from drift.pipeline import get_runs

os.makedirs(config.LOGS_DIR, exist_ok=True)
os.makedirs(config.RESULTS_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(os.path.join(config.LOGS_DIR, "stats.log"), mode="w"),
                              logging.StreamHandler(sys.stdout)])
log = logging.getLogger("stats")

views = [RunView(r) for r in get_runs()]
SCHEDULE = config.ENV_SCHEDULE
log.info("seeds=%s schedule=%s", config.SEEDS, SCHEDULE)


# ---------------------------------------------------------------- helpers

def ci(xs):
    m = st.mean(xs)
    h = _T95[len(xs) - 1] * st.stdev(xs) / math.sqrt(len(xs))
    return m, m - h, m + h


def fmt_ci(xs):
    m, lo, hi = ci(xs)
    return f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]"


def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 / (1 - qab * x / qap)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d, c = 1 / (1 + aa * d), 1 + aa / c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d, c = 1 / (1 + aa * d), 1 + aa / c
        h *= d * c
        if abs(d * c - 1) < 1e-13:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0 or x >= 1:
        return float(x >= 1)
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return bt * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * _betacf(b, a, 1 - x) / b


def t_test_p(xs):
    """Two-sided one-sample t-test against zero."""
    n = len(xs)
    t = st.mean(xs) / (st.stdev(xs) / math.sqrt(n))
    df = n - 1
    return _ibeta(df / 2, 0.5, df / (df + t * t))


def fisher_p(a, n1, b, n2):
    """Two-sided Fisher exact test for a/n1 vs b/n2."""
    N, K = n1 + n2, a + b
    h = lambda x: math.comb(n1, x) * math.comb(n2, K - x) / math.comb(N, K)
    p0 = h(a)
    return sum(h(x) for x in range(max(0, K - n2), min(K, n1) + 1) if h(x) <= p0 * (1 + 1e-9))


lines = ["# Statistics quoted in the paper", ""]


def section(title, headers, rows, notes=()):
    lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |",
                  "| " + " | ".join(":-" for _ in headers) + " |"])
    lines.extend("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    lines.extend([""] + [f"- {n}" for n in notes] + ([""] if notes else []))


# ---------------------------------------------------------------- Figure 4

rows = []
for env, label in [("E1", "Unchanged"), ("E2", "Decoding"), ("E3", "Extraction"), ("E4", "Combined")]:
    xs = [100 * st.mean(m["inflation"] for m in age_pairs(v, config.FIXED_AGE, force_stored_env="E1", current_env=env))
          for v in views]
    rows.append((label, fmt_ci(xs), f"{sum(x > 0 for x in xs)}/{len(xs)}"))
section("Figure 4: drift inflation at reference age 3",
        ["Environment", "Mean [95% CI] (pp)", "Seeds above zero"], rows,
        ["References are stored under E1, as in Table 4 (results/table4.md); the interval is a t-interval over seeds."])


# ---------------------------------------------------------------- Figure 6

def decomposition(ref_prompt, stored_env):
    """Frozen-policy acceptance rule with a chosen reference prompt and stored environment."""
    false_acc = accepted = 0
    per_seed = []
    for v in views:
        snaps = v.run["snapshots"]
        inc = snaps[0]["prompt"]
        infs = []
        for c in v.run["candidates"]:
            k = c["round"]
            cur = v.env_at(k, SCHEDULE)
            prev = max(0, k - 1)
            ref = snaps[0]["prompt"] if ref_prompt == "initial" else snaps[prev]["prompt"]
            env = {"initial": v.env_at(0, SCHEDULE), "previous": v.env_at(prev, SCHEDULE), "current": cur}[stored_env]
            c_lab, ref_lab, rerun = v.labels(c["prompt"], cur), v.stored(ref, env, cur), v.rerun(ref, cur)
            infs.append(100 * (win_rate(c_lab, ref_lab) - win_rate(c_lab, rerun)))
            w, l, _, _ = pair(c_lab, ref_lab)
            if w > l:
                accepted += 1
                false_acc += not (v.gt_acc(c["prompt"], cur) > v.gt_acc(inc, cur))
                inc = c["prompt"]
        per_seed.append(st.mean(infs))
    return false_acc, accepted, st.mean(per_seed)


rows = []
for ref_prompt, ref_label in [("initial", "Initial prompt"), ("previous", "Previous incumbent")]:
    for stored_env, env_label in [("initial", "Initial"), ("previous", "Previous round"), ("current", "Current")]:
        fa, acc, infl = decomposition(ref_prompt, stored_env)
        rows.append((ref_label, env_label, f"{fa}/{acc}", f"{100 * fa / acc:.1f}", f"{infl:+.2f}"))
section("Figure 6: pooled false accepts by reference prompt and stored environment",
        ["Reference prompt", "Environment of stored outputs", "False accepts / accepts", "Rate (%)", "Drift inflation (pp)"],
        rows, ["Initial prompt with initial environment is the full frozen policy (Table 8, A1); previous incumbent "
               "with previous-round environment is Table 8, A4."])


# ---------------------------------------------------------------- Appendix C

def frozen_inflation(schedule):
    return [100 * simulate(v, "P1", schedule=schedule)["inflation"] for v in views]


full = frozen_inflation(SCHEDULE)
no_decoding = frozen_inflation({0: "E1", 4: "E1", 8: "E3"})
no_extraction = frozen_inflation({0: "E1", 4: "E2", 8: "E2"})
rows = []
for label, other in [("Removing extraction drift", no_extraction), ("Removing decoding drift", no_decoding)]:
    d = [a - b for a, b in zip(full, other)]
    rows.append((label, f"{st.mean(d):.2f} ± {st.stdev(d):.2f}", f"{t_test_p(d):.3f}", f"{sum(x > 0 for x in d)}/{len(d)}"))
section("Appendix C: single-factor schedule ablations",
        ["Ablation", "Drop in drift inflation (pp, mean ± sd)", "p (paired t-test)", "Seeds with a drop"], rows)

by_env = {e: [] for e in ("E1", "E2", "E3", "E4")}
for v in views:
    h0 = v.run["snapshots"][0]["prompt"]
    for e in by_env:
        by_env[e].append(st.mean(
            100 * (win_rate(v.labels(c["prompt"], e), v.stored(h0, "E1", e)) - win_rate(v.labels(c["prompt"], e), v.rerun(h0, e)))
            for c in v.run["candidates"] if c["round"] >= 8))
rows = [(label, fmt_ci([x - y for x, y in zip(by_env[e], by_env["E1"])]))
        for e, label in [("E2", "Decoding"), ("E3", "Extraction"), ("E4", "Both")]]
inter = [(by_env["E4"][i] - by_env["E2"][i]) - (by_env["E3"][i] - by_env["E1"][i]) for i in range(len(views))]
section("Appendix C: 2×2 factorial over rounds 8–10",
        ["Drift", "Effect on drift inflation vs Unchanged (pp) [95% CI]"], rows,
        [f"Interaction: {st.mean(inter):+.2f} ± {st.stdev(inter):.2f} pp, p = {t_test_p(inter):.2f} (paired t-test)."])


# ---------------------------------------------------------------- Refresh policies

policies = [("Frozen", "P1", "initial"), ("Stored incumbent", "P1", "last_accepted"),
            ("Per-batch", "P2", None), ("Environment-triggered", "P3", None)]
errors, rows = {}, []
for label, pol, mode in policies:
    fa = fr = 0
    for v in views:
        s = simulate(v, pol, frozen_mode=mode, with_records=True)
        fa += s["false_accepts"]
        fr += s["false_rejects"]
    n = sum(len(v.run["candidates"]) for v in views)
    errors[label] = (fa + fr, n)
    rows.append((label, fa, fr, f"{fa + fr}/{n}"))
trig = errors["Environment-triggered"]
notes = [f"Fisher exact test, environment-triggered vs {k.lower()}: p = {fisher_p(*trig, *errors[k]):.3f}"
         for k in ("Frozen", "Per-batch", "Stored incumbent")]
notes.append("The test treats every decision as independent, which overstates the evidence.")
section("Refresh policies: errors and Fisher tests",
        ["Policy", "False accepts", "False rejects", "Errors / decisions"], rows, notes)

gaps = []
for v in views:
    final = 100 * simulate(v, "P3")["final_gt_acc"]
    env = v.env_at(v.run["candidates"][-1]["round"], SCHEDULE)
    pool = [v.run["snapshots"][0]["prompt"]] + [c["prompt"] for c in v.run["candidates"]]
    best = 100 * max(v.gt_acc(h, env) for h in pool)
    gaps.append((v.run["seed"], final, best, best - final))
section("Environment-triggered policy vs the best prompt in each pool",
        ["Seed", "Final accuracy (%)", "Best prompt in pool (%)", "Gap (pp)"],
        [(s, f"{f:.1f}", f"{b:.1f}", f"{g:.1f}") for s, f, b, g in gaps],
        [f"Mean gap {st.mean(g for *_, g in gaps):.1f} pp; mean final {st.mean(f for _, f, _, _ in gaps):.1f}% "
         f"vs mean best {st.mean(b for _, _, b, _ in gaps):.1f}%."])


# ---------------------------------------------------------------- Setup and evaluation text

long_prompts = sum(len(v.run["prompts"][c["prompt"]].split()) > 120 for v in views for c in v.run["candidates"])
n_cand = sum(len(v.run["candidates"]) for v in views)
greedy = st.mean(v.gt_acc(h, "E1") for v in views for h in v.run["correct"])
sampled = st.mean(v.gt_acc(h, "E2") for v in views for h in v.run["correct"])
diffs = [100 * abs(st.mean(d[e]["current"]) - st.mean(d[e]["rerun"]))
         for v in views for c in v.run["candidates"] for e in ("E2", "E4")
         for d in [v.run["correct"][c["prompt"]]]]
flips = reverse = total = 0
for v in views:
    for d in v.run["correct"].values():
        for x, y in zip(d["E1"]["current"], d["E3"]["current"]):
            total += 1
            flips += (not x) and y
            reverse += x and not y
section("Numbers in the Setup and Evaluation text", ["Quantity", "Value"], [
    ("Candidate prompts over 120 words", f"{long_prompts}/{n_cand}"),
    ("Accuracy, greedy vs sampled at T = 0.2 (strict extractor, all prompts)", f"{100 * greedy:.1f}% vs {100 * sampled:.1f}%"),
    ("Two sampled passes at T = 0.2, mean / max accuracy difference (candidates, E2 and E4)",
     f"{st.mean(diffs):.2f} / {max(diffs):.1f} pp"),
    ("Stored greedy labels flipped by the lenient extractor", f"{flips}/{total} incorrect→correct, {reverse} correct→incorrect"),
])

text = "\n".join(lines).rstrip() + "\n"
with open(os.path.join(config.RESULTS_DIR, "stats.md"), "w") as f:
    f.write(text)
log.info("Statistics written to %s\n%s", os.path.relpath(os.path.join(config.RESULTS_DIR, "stats.md"), config.ROOT), text)
