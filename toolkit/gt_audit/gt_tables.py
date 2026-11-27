"""Re-derive the GT-dependent numbers with the frozen gt scorer (and two comparison GTs).

Usage: .venv/bin/python -I gt_tables.py
Needs gt_scores.csv / gt_labels.json from rescore.py. The repo is imported read-only; the only
change is GTView.gt_acc, which swaps the ground-truth grading. The gate (labels/stored/rerun)
keeps the environment's own parser labels, exactly as in drift/analysis.py.
"""
import csv
import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # toolkit/
sys.path.insert(0, REPO)
from drift import config  # noqa: E402
from drift.analysis import POLICIES, RunView, age_pairs, simulate, summarise  # noqa: E402
from drift.envs import ENVS  # noqa: E402

GT = json.load(open(os.path.join(HERE, "gt_labels.json")))
RUNS = []
for p in sorted(glob.glob(os.path.join(REPO, "runs", "run_seed*_r11.json"))):
    RUNS.append(json.load(open(p)))
RUNS.sort(key=lambda r: r["seed"])
OUT = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def dec(env_id):
    return "greedy" if ENVS[env_id].decoding == "greedy" else "sample"


class GTView(RunView):
    """RunView whose ground truth is a fixed scorer instead of the current environment's parser.

    gt='env'       -> original behaviour (sanity check)
    gt='gt'        -> frozen gt_scorer on the outputs of env X's decoding (stored pass)
    gt='gt_strict' -> gt without the conclusion-line rule
    gt='v2fixed'   -> v2 always (E3 labels for greedy text, E4 for sampled), never v1
    """

    def __init__(self, run, gt="gt"):
        super().__init__(run)
        self.gt = gt
        self.seed = str(run["seed"])

    def gt_labels(self, h, env_id):
        if self.gt == "env":
            return self.labels(h, env_id)
        if self.gt == "v2fixed":
            return self.labels(h, "E3" if dec(env_id) == "greedy" else "E4")
        return GT[self.seed][h][dec(env_id)]["current"][self.gt]

    def gt_acc(self, h, env_id):
        return sum(self.gt_labels(h, env_id)) / self.n


def msd(xs, d=1):
    xs = [x for x in xs if x is not None]
    return f"{statistics.mean(xs):.{d}f} ± {statistics.stdev(xs):.{d}f}" if len(xs) > 1 else "n/a"


# ------------------------------------------------------------ coverage check
for r in RUNS:
    for h in r["correct"]:
        for d in ("greedy", "sample"):
            assert len(GT[str(r["seed"])][h][d]["current"]["gt"]) == 200, (r["seed"], h, d)
say("seeds:", [r["seed"] for r in RUNS], "prompts per seed:", [len(r["correct"]) for r in RUNS])

# ------------------------------------------------------------ (i) accuracy per seed/prompt
rows = []
for r in RUNS:
    v = GTView(r, "gt")
    rounds = {s["prompt"]: s["round"] for s in r["snapshots"]}
    rounds.update({c["prompt"]: c["round"] for c in r["candidates"]})
    for h in r["correct"]:
        row = {"seed": r["seed"], "prompt_hash": h, "round": rounds.get(h, "")}
        for d, e1, e2 in (("greedy", "E1", "E3"), ("sampled", "E2", "E4")):
            dd = "greedy" if d == "greedy" else "sample"
            row[f"{d}_v1"] = 100 * sum(v.labels(h, e1)) / 200
            row[f"{d}_v2"] = 100 * sum(v.labels(h, e2)) / 200
            row[f"{d}_gt"] = 100 * sum(GT[str(r["seed"])][h][dd]["current"]["gt"]) / 200
            row[f"{d}_gt_strict"] = 100 * sum(GT[str(r["seed"])][h][dd]["current"]["gt_strict"]) / 200
        rows.append(row)
with open(os.path.join(HERE, "acc_per_prompt.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
say("\n(i) Accuracy (%) over all prompt x seed rows, stored outputs (mean over", len(rows), "rows):")
for d in ("greedy", "sampled"):
    m = {k: statistics.mean(x[f"{d}_{k}"] for x in rows) for k in ("v1", "v2", "gt", "gt_strict")}
    gap = [x[f"{d}_v2"] - x[f"{d}_gt"] for x in rows]
    gap1 = [x[f"{d}_gt"] - x[f"{d}_v1"] for x in rows]
    say(f"  {d:7s} v1 {m['v1']:.2f}  v2 {m['v2']:.2f}  gt {m['gt']:.2f}  gt_strict {m['gt_strict']:.2f} | "
        f"v2-gt per prompt: mean {statistics.mean(gap):.2f} max {max(gap):.1f}; gt-v1 mean {statistics.mean(gap1):.2f} max {max(gap1):.1f}")
say("  per seed (greedy v1/v2/gt | sampled v1/v2/gt), mean over that seed's prompts:")
for s in sorted({x["seed"] for x in rows}):
    xs = [x for x in rows if x["seed"] == s]
    say(f"    seed {s}: " + " | ".join(
        "/".join(f"{statistics.mean(x[f'{d}_{k}'] for x in xs):.1f}" for k in ("v1", "v2", "gt"))
        for d in ("greedy", "sampled")))
# rank agreement: does gt change which prompt is best within a seed?
chg = 0
for s in sorted({x["seed"] for x in rows}):
    xs = [x for x in rows if x["seed"] == s]
    for d in ("greedy", "sampled"):
        b2 = max(xs, key=lambda x: x[f"{d}_v2"])["prompt_hash"]
        bg = max(xs, key=lambda x: x[f"{d}_gt"])["prompt_hash"]
        chg += b2 != bg
say(f"  best prompt (argmax) differs between v2 and gt in {chg}/10 seed x decoding cells")
big = sorted(rows, key=lambda x: -(x["greedy_v2"] - x["greedy_gt"]))[:5]
say("  largest greedy v2-gt gaps:", [(x["seed"], x["round"], x["prompt_hash"][:8], x["greedy_v2"], x["greedy_gt"]) for x in big])

# ------------------------------------------------------------ (ii) the 638 greedy v1->v2 flips
sc = list(csv.DictReader(open(os.path.join(HERE, "gt_scores.csv"))))
flip = Counter()
for x in sc:
    if x["split"] != "test" or not x["decoding"].startswith("greedy") or x["tag"] != "current":
        continue
    if x["v1_correct"] == "0" and x["v2_correct"] == "1":
        n = len(x["seeds"].split(","))
        flip[("all", x["gt_correct"])] += n
        flip[(x["v2_rule"], x["gt_correct"])] += n
tot = flip[("all", "0")] + flip[("all", "1")]
say(f"\n(ii) greedy stored v1->v2 flips (seed-expanded): {tot}; gt agrees (credits) {flip[('all', '1')]} "
    f"= {100 * flip[('all', '1')] / tot:.1f}%, gt rejects {flip[('all', '0')]}")
for rule in ("last_number", "bold", "boxed_loose", "answer_is"):
    a, b = flip[(rule, "1")], flip[(rule, "0")]
    if a + b:
        say(f"    {rule:12s} {a + b:4d} flips: gt credits {a}, rejects {b}")


# ------------------------------------------------------------ (iii) Table 3
def table3(gt, schedule=None, label=""):
    res = {p: [] for p in POLICIES}
    for r in RUNS:
        v = GTView(r, gt)
        for p in POLICIES:
            res[p].append(simulate(v, p, schedule=schedule))
    say(f"  [{label}] GT={gt}")
    for p in POLICIES:
        rr = res[p]
        fa, ac = sum(x["false_accepts"] for x in rr), sum(x["accepted"] for x in rr)
        say(f"    {p}: final GT acc {msd([100 * x['final_gt_acc'] for x in rr])} | false accepts {fa}/{ac} pooled "
            f"| per-seed FA/acc {[(x['false_accepts'], x['accepted']) for x in rr]} "
            f"| per-seed acc {[round(100 * x['final_gt_acc'], 1) for x in rr]}")
    return res


say("\n(iii) Table 3 replay (gate = environment parser labels, unchanged; only GT grading switches)")
san = table3("env", label="drift schedule, sanity: GT = env parser")
exp = {"P1": (13, 34), "P2": (3, 13), "P3": (2, 16)}
expacc = {"P1": 70.8, "P2": 69.7, "P3": 72.5}
ok = all((sum(x["false_accepts"] for x in san[p]), sum(x["accepted"] for x in san[p])) == exp[p]
         and round(statistics.mean(100 * x["final_gt_acc"] for x in san[p]), 1) == expacc[p] for p in POLICIES)
say(f"  SANITY reproduces current Table 3 (P1 13/34, P2 3/13, P3 2/16; 70.8/69.7/72.5): {ok}")
assert ok
for gt in ("gt", "gt_strict", "v2fixed"):
    table3(gt, label="drift schedule")
say("  No-drift replay, schedule {0: 'E1'}:")
for gt in ("env", "gt", "gt_strict", "v2fixed"):
    table3(gt, schedule={0: "E1"}, label="no drift")

# decision-level view: which accepts flip false<->true when GT switches
say("  Accept-level changes, drift schedule (env-parser GT -> gt):")
for p in POLICIES:
    ch = []
    for r in RUNS:
        a = simulate(GTView(r, "env"), p, with_records=True)["records"]
        b = simulate(GTView(r, "gt"), p, with_records=True)["records"]
        for x, y in zip(a, b):
            assert x["accepted"] == y["accepted"]
            if x["accepted"] and x["false_accept"] != y["false_accept"]:
                ch.append((r["seed"], x["round"], x["env"], round(x["delta_pp"], 1), round(y["delta_pp"], 1),
                           "FA->ok" if x["false_accept"] else "ok->FA"))
    say(f"    {p}: {ch if ch else 'none'}")

# ------------------------------------------------------------ (iv) Table 4
say("\n(iv) Table 4 drift inflation (pp), reference age 3, stored under E1, mean ± sd over seeds")
age = config.FIXED_AGE


class FixedScorerView(GTView):
    """Every label (candidate, stored reference, rerun) from one fixed scorer on the right text."""

    def __init__(self, run, scorer, stored_mode):
        super().__init__(run, scorer)
        self.scorer, self.stored_mode = scorer, stored_mode

    def _fixed(self, h, env_id, tag):
        if self.scorer == "v2fixed":
            return self.run["correct"][h]["E3" if dec(env_id) == "greedy" else "E4"][tag]
        return GT[self.seed][h][dec(env_id)][tag][self.scorer]

    def labels(self, h, env_id, tag="current"):
        return self._fixed(h, env_id, tag)

    def stored(self, h, stored_env, current_env):
        if self.stored_mode == "as_recorded_v1":  # keep the anchor exactly as recorded (v1 under E1)
            return self.run["correct"][h][stored_env]["current"]
        return self._fixed(h, stored_env, "current")


def t4(make, label):
    say(f"  [{label}]")
    for e in ("E1", "E2", "E3", "E4"):
        s = [summarise(age_pairs(make(r), age, force_stored_env="E1", current_env=e)) for r in RUNS]
        say(f"    {e}: stored win {msd([100 * x['stored_win'] for x in s], 2)} | rerun win "
            f"{msd([100 * x['rerun_win'] for x in s], 2)} | inflation {msd([100 * x['inflation'] for x in s], 2)}")


t4(lambda r: RunView(r), "as published: env parsers (v1 for E1/E2, v2 for E3/E4)")
t4(lambda r: FixedScorerView(r, "gt", "fixed"), "all labels from gt (no extraction change exists)")
t4(lambda r: FixedScorerView(r, "gt", "as_recorded_v1"),
   "extraction change v1 -> gt: stored anchor as recorded (v1), candidate + rerun graded by gt")

open(os.path.join(HERE, "gt_tables_output.txt"), "w").write("\n".join(OUT) + "\n")
