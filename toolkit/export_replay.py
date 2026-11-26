"""Write the replay files the demo site reads: demo/replay/seed{N}.json and all_seeds.json.

Everything is computed from the saved GSM8K run files in runs/. No model is called, and no
number is typed in by hand.

    python export_replay.py            # seeds 1-5
    python export_replay.py 1 2 3
"""
import ast
import json
import math
import operator
import os
import random
import re
import statistics
import subprocess
import sys

from drift import config
from drift.analysis import _T95, POLICIES, RunView, age_pairs, candidate_truth, outcome, simulate, summarise
from drift.envs import ENVS
from drift.extract import extract_v1, extract_v2, gold_answer
from drift.model import Cache, generation_key
from drift.pipeline import run_path

OUT = os.path.join(config.ROOT, "demo", "replay")
# Same items, same order as openai/gsm8k (main, test) on Hugging Face, which the runs loaded.
GSM8K_URL = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
ENV_TEXT = {
    "E1": "greedy decoding, strict extractor",
    "E2": "sampling (T=0.2), strict extractor",
    "E3": "greedy decoding, lenient extractor",
    "E4": "sampling (T=0.2), lenient extractor",
}
CHANGE_TEXT = {"E2": "Decoding changes from greedy to sampling.",
               "E4": "Decoding and the answer extractor both change."}


def r4(x):
    return round(x, 4)


def mean_sd(xs):
    return [r4(statistics.mean(xs)), r4(statistics.stdev(xs)) if len(xs) > 1 else 0.0]


def interval(xs):
    """Mean with a 95% t interval across seeds, and how many seeds share the sign of the mean."""
    m = statistics.mean(xs)
    half = _T95.get(len(xs) - 1, 1.96) * statistics.stdev(xs) / math.sqrt(len(xs))
    same = sum(1 for x in xs if x != 0 and (x > 0) == (m > 0))
    return {"mean": r4(m), "lo": r4(m - half), "hi": r4(m + half), "seeds_same_sign": same, "per_seed": [r4(x) for x in xs]}


def cause(rec):
    """Why a frozen-reference false promotion happened, using the same rule against a fresh reference."""
    if not rec["false_accept"]:
        return None
    if rec["env"] == "E1":
        return "before_change"
    return "anyway" if rec["fresh_wins"] > rec["fresh_losses"] else "stale"


def export_seed(run):
    view = RunView(run)
    labels = {h: f"p{i}" for i, h in enumerate(run["prompts"])}
    sims = {p: simulate(view, p, with_records=True) for p in POLICIES}
    p0 = run["snapshots"][0]["prompt"]
    n = view.n

    rounds = []
    for rec, cand in zip(sims["P1"]["records"], run["candidates"]):
        after = rec["cand_prompt"] if rec["accepted"] else rec["inc_prompt"]
        rounds.append({
            "round": rec["round"], "env": rec["env"], "incumbent": labels[rec["inc_prompt"]],
            "candidate": labels[rec["cand_prompt"]], "note": cand["note"], "wins": rec["wins"], "losses": rec["losses"],
            "fresh_wins": rec["fresh_wins"], "fresh_losses": rec["fresh_losses"],
            "stale_net_pp": r4(100 * (rec["wins"] - rec["losses"]) / n),
            "fresh_net_pp": r4(100 * (rec["fresh_wins"] - rec["fresh_losses"]) / n),
            "inflation_pp": r4(100 * rec["inflation"]), "accepted": rec["accepted"],
            "false_accept": rec["false_accept"], "false_reject": rec["false_reject"],
            "incumbent_acc": r4(rec["inc_acc"]), "candidate_acc": r4(rec["cand_acc"]),
            "delta_pp": r4(rec["delta_pp"]), "acc_after": r4(view.gt_acc(after, rec["env"])),
            "cause": cause(rec),
        })

    policies = {}
    for p, s in sims.items():
        policies[p] = {
            "name": POLICIES[p][0],
            "decisions": [{"round": r["round"], "env": r["env"], "candidate": labels[r["cand_prompt"]],
                           "accepted": r["accepted"], "false_accept": r["false_accept"],
                           "false_reject": r["false_reject"], "wins": r["wins"], "losses": r["losses"],
                           "delta_pp": r4(r["delta_pp"]), "reference_refreshed": r["ref_fresh"]}
                          for r in s["records"]],
            "accepted": s["accepted"], "false_accepts": s["false_accepts"], "false_rejects": s["false_rejects"],
            "refreshes": s["refreshes"], "logical_calls": s["total_calls"], "final_acc": r4(s["final_gt_acc"]),
        }

    strict, lenient = view.labels(p0, "E1"), view.labels(p0, "E3")
    changes = [{"round": r, "env": e, "text": CHANGE_TEXT.get(e, "")} for r, e in sorted(view.schedule.items()) if r > 0]
    return {
        "meta": {
            "seed": run["seed"], "model": config.MODEL_ID.split("/")[-1], "dataset": "GSM8K",
            "n_items": n, "rounds": run["config"]["rounds"], "changes": changes,
            "precomputed": run["config"]["backend"] != "mock",
            "baseline_strict_acc": r4(sum(strict) / n), "baseline_lenient_acc": r4(sum(lenient) / n),
            "extractor_flips": {"n": n, "wrong_to_right": sum(b and not a for a, b in zip(strict, lenient)),
                                "right_to_wrong": sum(a and not b for a, b in zip(strict, lenient))},
            "false_promotion_rounds": [r["round"] for r in rounds if r["false_accept"] and r["env"] != "E1"],
            "reference": {"prompt": "p0", "prompt_hash": p0, "env": "E1", "fingerprint": ENVS["E1"].fingerprint,
                          "scorer": "extractor v1 (strict)", "n_outputs": n},
        },
        "envs": ENV_TEXT, "fingerprints": {e: ENVS[e].fingerprint for e in ENVS},
        "prompts": {labels[h]: t for h, t in run["prompts"].items()},
        "rounds": rounds, "policies": policies,
    }


def export_all(runs, files):
    views = [RunView(r) for r in runs]
    out = {"seeds": [r["seed"] for r in runs], "model": files[0]["meta"]["model"], "n_items": files[0]["meta"]["n_items"],
           "rounds": files[0]["meta"]["rounds"], "age": config.FIXED_AGE, "policies": {}, "per_seed": {}, "inflation": {}}
    for p in POLICIES:
        ps = [f["policies"][p] for f in files]
        out["policies"][p] = {
            "name": POLICIES[p][0], "accepted": sum(x["accepted"] for x in ps),
            "false_accepts": sum(x["false_accepts"] for x in ps), "false_rejects": sum(x["false_rejects"] for x in ps),
            "final_acc": mean_sd([x["final_acc"] for x in ps]), "logical_calls": mean_sd([x["logical_calls"] for x in ps]),
            "refreshes": mean_sd([x["refreshes"] for x in ps]),
        }
    # Reference stored under E1, candidate and rerun reference scored under each environment.
    for env_id in ENVS:
        sums = [summarise(age_pairs(v, config.FIXED_AGE, force_stored_env="E1", current_env=env_id)) for v in views]
        out["inflation"][env_id] = interval([100 * s["inflation"] for s in sums])
    for f in files:
        out["per_seed"][str(f["meta"]["seed"])] = {
            "false_promotion_rounds": f["meta"]["false_promotion_rounds"],
            **{p: {k: f["policies"][p][k] for k in ("accepted", "false_accepts", "false_rejects", "logical_calls", "final_acc")}
               for p in POLICIES},
        }
    out["verdict_flips"] = extractor_flips(views)
    causes = [r for f in files for r in f["rounds"] if r["cause"]]
    out["false_promotion_causes"] = {k: sum(r["cause"] == k for r in causes) for k in ("before_change", "stale", "anyway")}
    out["false_promotion_causes"]["same_text"] = sum(r["incumbent"] == r["candidate"] for r in causes)
    out["answer_flips"] = answer_flips(runs)
    out["questions"] = showcase(runs[0])
    return out


def answer_flips(runs):
    """Every prompt's saved greedy answers, graded by the strict and then the lenient extractor."""
    pairs = [(e["E1"]["current"], e["E3"]["current"]) for r in runs for e in r["correct"].values()]
    graded = [(s, l) for strict, lenient in pairs for s, l in zip(strict, lenient)]
    return {"prompts": len(pairs), "items": len(graded),
            "wrong_to_right": sum(l and not s for s, l in graded),
            "right_to_wrong": sum(s and not l for s, l in graded)}


def gsm8k_test():
    path = os.path.join(config.ROOT, "data", "gsm8k_test.jsonl")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["curl", "-sSL", "--fail", "-o", path, GSM8K_URL], check=True)
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def showcase(run, k_right=3, k_wrong=2):
    """Questions for the opening screen: every item the extractor switch regrades, plus a few others.

    Grades are the starting prompt's measured labels. Raw model text is added only when the
    generation cache holds the real output for that item.
    """
    rows = gsm8k_test()
    p0 = run["snapshots"][0]["prompt"]
    strict, lenient = run["correct"][p0]["E1"]["current"], run["correct"][p0]["E3"]["current"]
    flips = [i for i, (a, b) in enumerate(zip(strict, lenient)) if b and not a]
    rng = random.Random(0)
    right = rng.sample([i for i, a in enumerate(strict) if a], k_right)
    wrong = rng.sample([i for i, b in enumerate(lenient) if not b], k_wrong)
    cache = Cache()
    out = []
    for i in sorted(flips + right + wrong):
        item = {"index": i, "question": rows[i]["question"], "gold": gold_answer(rows[i]["answer"]),
                "strict_correct": bool(strict[i]), "lenient_correct": bool(lenient[i])}
        text = cache.get(generation_key(run["prompts"][p0], f"test-{i}", ENVS["E1"], run["seed"], "current"))
        if text:
            item.update(raw=text, answer_v1=extract_v1(text), answer_v2=extract_v2(text), steps=check_trace(text))
        out.append(item)
    return out


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_NUM = r"\d[\d,]*(?:\.\d+)?"
_EQ = re.compile(rf"(?<![\d.,])({_NUM}(?:\s*[-+*/]\s*{_NUM})+)\s*=\s*(-?{_NUM})")


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    raise ValueError("unsupported expression")


def check_trace(text):
    """Recompute each 'a op b ... = c' in a response. Shown on screen, never used for grading."""
    flat = re.sub(r"\\(?:times|cdot)", "*", text)
    flat = re.sub(r"\\div|÷", "/", flat).replace("×", "*").replace("\\$", "").replace("$", "")
    steps = []
    for m in _EQ.finditer(flat):
        lhs, rhs = m.group(1).replace(",", ""), float(m.group(2).replace(",", ""))
        try:
            got = _eval(ast.parse(lhs, mode="eval").body)
        except (ValueError, SyntaxError, ZeroDivisionError):
            continue
        steps.append({"text": re.sub(r"\s+", " ", m.group(0)), "ok": abs(got - rhs) <= max(0.01 * abs(got), 0.006)})
    return steps


def extractor_flips(views):
    """Candidates whose improved/no change/worse verdict differs between E1 and E3, which share all text."""
    rows = [r for v in views for r in candidate_truth(v)]
    flipped = [r for r in rows if outcome(r["delta_E1"]) != outcome(r["delta_E3"])]
    w = max(flipped, key=lambda r: abs(r["delta_E3"] - r["delta_E1"]))
    return {"n": len(rows), "flipped": len(flipped),
            "widest": {"seed": w["seed"], "cid": w["cid"], "e1_pp": r4(w["delta_E1"]), "e3_pp": r4(w["delta_E3"])}}


def write(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def main():
    seeds = [int(a) for a in sys.argv[1:]] or [1, 2, 3, 4, 5]
    runs = []
    for s in seeds:
        with open(run_path(s)) as f:
            runs.append(json.load(f))
    os.makedirs(OUT, exist_ok=True)
    files = [export_seed(r) for r in runs]
    for f in files:
        write(f"seed{f['meta']['seed']}.json", f)
    write("all_seeds.json", export_all(runs, files))
    print(f"Wrote {len(files)} seed files to {OUT}")


if __name__ == "__main__":
    main()

