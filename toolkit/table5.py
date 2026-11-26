"""Table 5. Ground-truth evaluation of candidate prompts.

Every candidate the proposer offered is scored against the incumbent it was proposed from,
both under the environment in force at that round. This is the measurement the gate in
pipeline.py does not have access to: the gate only sees paired wins and losses against a
reference, while this table reports what the candidate was actually worth.

Table 6 then asks how often each refresh policy accepted a candidate this table calls
non-improving, so the two tables must be read together.

Writes results/table5.md (full record), results/table5_example.md (one seed, for the paper),
results/table5_summary.md, results/table5_crossenv.md and results/table5.csv.
"""
import csv
import os

from drift import config
from drift.analysis import RunView, candidate_truth, outcome
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(5)
views = [RunView(r) for r in get_runs()]

rows = [r for v in views for r in candidate_truth(v)]
log.info("%d candidates over %d seeds", len(rows), len(views))

ENV_LABEL = {"E1": "Unchanged", "E2": "Decoding change",
             "E3": "Extraction change", "E4": "Multiple changes"}

HEADERS = ["Candidate ID", "Seed", "Round", "Environment", "Incumbent accuracy (%)",
           "Candidate accuracy (%)", "Accuracy change (pp)", "Ground-truth outcome"]


def fmt(r):
    return (r["cid"], r["seed"], r["round"], f"{r['env']} {ENV_LABEL[r['env']]}",
            f"{100 * r['inc_acc']:.1f}", f"{100 * r['cand_acc']:.1f}",
            f"{r['delta_pp']:+.1f}", r["outcome"])


degenerate = [r for r in rows if r["note"] == "fallback_unparsed"]

# The incumbent can be re-measured at a different accuracy with no accept, when the environment moves.
env_moves = []
for v in views:
    seed_rows = [r for r in rows if r["seed"] == v.run["seed"]]
    for prev, cur in zip(seed_rows, seed_rows[1:]):
        if not prev["accepted"] and abs(cur["inc_acc"] - prev["inc_acc"]) > 1e-9:
            env_moves.append((cur["seed"], prev["cid"], cur["cid"],
                              100 * prev["inc_acc"], 100 * cur["inc_acc"]))

move_eg = ""
if env_moves:
    s, a, b, before, after = env_moves[0]
    move_eg = (f" Example: on seed {s} the incumbent reads {before:.1f}% at {a} and {after:.1f}% at "
               f"{b} with no accept in between.")

deg_note = []
if degenerate:
    ids = ", ".join(f"seed {r['seed']} {r['cid']}" for r in degenerate)
    deg_note = [f"{len(degenerate)} candidates ({ids}) are the incumbent copied verbatim, because the "
                "proposer's own output could not be parsed. They score 0.0 pp by construction."]

example_seed = views[0].run["seed"]
example = [r for r in rows if r["seed"] == example_seed]

NOTES = [f"All {len(rows)} candidates proposed across {len(views)} seeds, {config.ROUNDS} rounds each. "
         f"Accuracy is over all {config.N_EVAL} evaluation items under the environment in force at "
         "that round.",
         f"Where space allows only one seed, the paper prints seed {example_seed} in full "
         f"({len(example)} rows) and labels it an illustrative subset, not a sample. Every rate in "
         f"Table 6 is computed over all {len(rows)} candidates.",
         "Rows are sequential rounds within a seed. The incumbent changes only when a candidate is "
         "accepted, so consecutive rows often share one incumbent accuracy.",
         f"It also moves with no accept in {len(env_moves)} rows, where the environment changed and "
         f"the same prompt was re-measured.{move_eg}",
         "'Improved' means strictly higher accuracy, so one extra correct item "
         f"({100 / config.N_EVAL:.1f} pp) counts. Table 6 calls an accept false when this column is "
         "not 'improved'."] + deg_note + [
         f"Selection and reporting both use the same {config.N_EVAL} items.",
         "Per-environment scores and the gate's wins, losses and decisions are in "
         "results/table5_crossenv.md and results/table5.csv."]

write_table(5, "Ground-truth evaluation of candidate prompts", HEADERS, [fmt(r) for r in rows],
            notes=NOTES)

write_table(5, "Ground-truth evaluation of candidate prompts (illustrative subset)",
            HEADERS, [fmt(r) for r in example], suffix="_example",
            notes=[f"One seed of {len(views)}, shown in full as an example. The evidence behind "
                   f"Table 6 is all {len(rows)} candidates, in results/table5.md."] + NOTES[2:5])

by_outcome = {}
for r in rows:
    by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1

summary = []
for env_id, label in ENV_LABEL.items():
    sub = [r for r in rows if r["env"] == env_id]
    if not sub:
        continue
    imp = sum(r["outcome"] == "improved" for r in sub)
    summary.append((label, len(sub), imp, sum(r["outcome"] == "no change" for r in sub),
                    sum(r["outcome"] == "worse" for r in sub), f"{100 * imp / len(sub):.1f}",
                    f"{sum(r['delta_pp'] for r in sub) / len(sub):+.1f}"))
imp_all = by_outcome.get("improved", 0)
summary.append(("All", len(rows), imp_all, by_outcome.get("no change", 0), by_outcome.get("worse", 0),
                f"{100 * imp_all / len(rows):.1f}",
                f"{sum(r['delta_pp'] for r in rows) / len(rows):+.1f}"))

write_table(5, "Candidate quality by environment condition",
            ["Environment at proposal", "Candidates", "Improved", "No change", "Worse",
             "Improved (%)", "Mean accuracy change (pp)"], summary, suffix="_summary",
            notes=["Environment is the one in force when the candidate was proposed, not a "
                   "condition applied afterwards, so the rows are not balanced in size.",
                   "Most candidates are worse than the incumbent they came from. That is the base "
                   "rate a refresh policy has to work against in Table 6."])

cross = []
for env_id, label in ENV_LABEL.items():
    ds = [r[f"delta_{env_id}"] for r in rows]
    imp = sum(d > 0 for d in ds)
    cross.append((label, env_id, len(ds), imp, sum(d == 0 for d in ds), sum(d < 0 for d in ds),
                  f"{100 * imp / len(ds):.1f}", f"{sum(ds) / len(ds):+.1f}"))
flips = sum(outcome(r["delta_E1"]) != outcome(r["delta_E4"]) for r in rows)
parser_flips = [r for r in rows if outcome(r["delta_E1"]) != outcome(r["delta_E3"])]
flip_eg = ""
if parser_flips:
    r = max(parser_flips, key=lambda x: abs(x["delta_E3"] - x["delta_E1"]))
    flip_eg = (f" The widest is seed {r['seed']} {r['cid']}: {r['delta_E1']:+.1f} pp under E1 and "
               f"{r['delta_E3']:+.1f} pp under E3, same prompt and same responses.")

write_table(5, "The same candidates judged under every environment",
            ["Environment", "ID", "Candidates", "Improved", "No change", "Worse",
             "Improved (%)", "Mean accuracy change (pp)"], cross, suffix="_crossenv",
            notes=[f"Every row scores all {len(rows)} candidates against their own incumbent, so the "
                   "pool is identical across rows and the environment is the only thing that changes.",
                   f"{flips} of {len(rows)} candidates ({100 * flips / len(rows):.1f}%) get a different "
                   "verdict under E1 than under E4. That disagreement is what Table 6 turns into a "
                   "false-accept rate.",
                   f"E1 and E3 differ only in the answer extractor, and {len(parser_flips)} of "
                   f"{len(rows)} candidates ({100 * len(parser_flips) / len(rows):.1f}%) still change "
                   f"verdict between them.{flip_eg} Reading the answer out of an unchanged response "
                   "is enough to flip a promotion decision, which is why the parser audit in "
                   "Table 2 matters for every number downstream.",
                   "Unlike the main table, these columns are not a restatement of the gate's wins and "
                   "losses, because the gate only ever saw the environment in force at the round."])

os.makedirs(config.RESULTS_DIR, exist_ok=True)
csv_path = os.path.join(config.RESULTS_DIR, "table5.csv")
envs = tuple(ENV_LABEL)
cols = ["seed", "cid", "round", "env", "inc_acc_pct", "cand_acc_pct", "delta_pp", "outcome",
        "wins", "losses", "accepted", "note"] + [f"delta_{e}" for e in envs]
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({
            "seed": r["seed"], "cid": r["cid"], "round": r["round"], "env": r["env"],
            "inc_acc_pct": round(100 * r["inc_acc"], 1),
            "cand_acc_pct": round(100 * r["cand_acc"], 1),
            "delta_pp": round(r["delta_pp"], 1), "outcome": r["outcome"],
            "wins": r["wins"], "losses": r["losses"], "accepted": r["accepted"], "note": r["note"],
            **{f"delta_{e}": round(r[f"delta_{e}"], 1) for e in envs},
        })
log.info("Per-candidate detail written to %s", os.path.relpath(csv_path, config.ROOT))

