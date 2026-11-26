"""Metrics from the proposal (Datasets and Evaluation section) computed on a saved run.

    measured win rate   = share of paired items where candidate is right and reference wrong
    drift inflation     = win rate vs stored reference - win rate vs same reference rerun now
    false-accept rate   = promoted candidates whose ground-truth accuracy is not higher than
                          the incumbent's (both under the current environment) / promoted

Rates over seeds are reported two ways and the two are not interchangeable: 'pooled' sums the
numerators and denominators across seeds, 'seed-mean' averages each seed's own rate and so
weights a seed with 2 accepts the same as a seed with 9.
"""
import math
import statistics

from . import config
from .envs import ENVS, env_at


class RunView:
    def __init__(self, run, stored_scoring=None):
        self.run = run
        self.n = run["config"]["n_eval"]
        self.n_dev = run["config"]["n_dev"]
        self.schedule = {int(r): e for r, e in run["config"]["schedule"].items()}
        self.stored_scoring = stored_scoring or config.STORED_SCORING

    def labels(self, h, env_id, tag="current"):
        return self.run["correct"][h][env_id][tag]

    def gt_acc(self, h, env_id):
        """Ground-truth accuracy of a prompt under an environment (the record)."""
        return sum(self.labels(h, env_id)) / self.n

    def stored(self, h, stored_env, current_env):
        """Labels of a reference whose outputs were stored under stored_env."""
        if self.stored_scoring == "rescore":
            s, c = ENVS[stored_env], ENVS[current_env]
            same_text_env = next(e for e in ENVS.values()
                                 if e.decoding_key == s.decoding_key and e.extractor == c.extractor)
            return self.labels(h, same_text_env.env_id)
        return self.labels(h, stored_env)

    def rerun(self, h, env_id):
        return self.labels(h, env_id, "rerun")

    def env_at(self, k, schedule=None):
        return env_at(k, schedule or self.schedule)


def pair(cand, ref):
    wins = sum(1 for c, r in zip(cand, ref) if c and not r)
    losses = sum(1 for c, r in zip(cand, ref) if r and not c)
    both_right = sum(1 for c, r in zip(cand, ref) if c and r)
    both_wrong = len(cand) - wins - losses - both_right
    return wins, losses, both_right, both_wrong


def win_rate(cand, ref):
    return pair(cand, ref)[0] / len(cand)


def pair_measure(view, cand_h, ref_h, stored_env, current_env, incumbent_h):
    """Stored vs rerun comparison of one candidate against one stored reference."""
    c = view.labels(cand_h, current_env)
    stored = view.stored(ref_h, stored_env, current_env)
    rerun = view.rerun(ref_h, current_env)
    n = len(c)
    sw, sl, _, _ = pair(c, stored)
    rw, rl, _, _ = pair(c, rerun)
    promote = sw > sl
    promote_rerun = rw > rl        # what the same rule decides after a refresh
    gt_better = view.gt_acc(cand_h, current_env) > view.gt_acc(incumbent_h, current_env)
    return {
        "stored_win": sw / n,
        "rerun_win": rw / n,
        "inflation": (sw - rw) / n,
        "promote": promote,
        "false_accept": promote and not gt_better,
        "promote_rerun": promote_rerun,
        "false_accept_rerun": promote_rerun and not gt_better,
        "env_changed": stored_env != current_env,
    }


def age_pairs(view, age, schedule=None, force_stored_env=None, current_env=None):
    """Candidate at round k against the snapshot from round k - age."""
    snaps = view.run["snapshots"]
    out = []
    for c in view.run["candidates"]:
        k = c["round"]
        if k - age < 0:
            continue
        ref = snaps[k - age]
        stored_env = force_stored_env or view.env_at(k - age, schedule)
        cur = current_env or view.env_at(k, schedule)
        m = pair_measure(view, c["prompt"], ref["prompt"], stored_env, cur, snaps[k]["prompt"])
        m["round"] = k
        out.append(m)
    return out


def summarise(measures):
    """One seed's cell: every rate is the mean of paired per-candidate differences."""
    if not measures:
        return {"n": 0}
    n_prom = sum(m["promote"] for m in measures)
    return {
        "n": len(measures),
        "stored_win": mean(m["stored_win"] for m in measures),
        "rerun_win": mean(m["rerun_win"] for m in measures),
        "inflation": mean(m["inflation"] for m in measures),
        "promoted": n_prom,
        "false_accepts": sum(m["false_accept"] for m in measures),
        "false_accept_rate": (sum(m["false_accept"] for m in measures) / n_prom) if n_prom else None,
        "env_changed": sum(m["env_changed"] for m in measures),
    }


def age_row(views, age, current_env, stored_env="E1", min_round=0):
    """One cell of Table 7: every seed's candidate/reference pairs `age` rounds apart.

    References are stored under stored_env and everything else is scored under current_env.
    Win rates stay per seed; promotions are pooled, because at the largest ages a seed has too
    few pairs to give a rate of its own. Age a can only use candidates from round a onward, so
    min_round keeps the candidate set the same across ages. The rerun_* counts apply the same
    promotion rule against the rerun reference, which is the baseline a refresh would give.
    """
    kept = [(v, [m for m in age_pairs(v, age, force_stored_env=stored_env, current_env=current_env)
                 if m["round"] >= min_round]) for v in views]
    kept = [(v, ms) for v, ms in kept if ms]
    sums = [summarise(ms) for _, ms in kept]
    pooled = [m for _, ms in kept for m in ms]
    return {
        "pairs": len(pooled),
        "seeds": [v.run["seed"] for v, _ in kept],
        "pairs_per_seed": [len(ms) for _, ms in kept],
        "stored_win": [s["stored_win"] for s in sums],
        "rerun_win": [s["rerun_win"] for s in sums],
        "inflation": [s["inflation"] for s in sums],
        "promoted": sum(m["promote"] for m in pooled),
        "false_accepts": sum(m["false_accept"] for m in pooled),
        "rerun_promoted": sum(m["promote_rerun"] for m in pooled),
        "rerun_false_accepts": sum(m["false_accept_rerun"] for m in pooled),
    }


def outcome(delta_pp):
    """Table 6 counts a false accept when the gain is 'no greater than', so this is strict."""
    if delta_pp > 0:
        return "improved"
    return "no change" if delta_pp == 0 else "worse"


def candidate_truth(view):
    """Every candidate scored against the incumbent it was actually proposed from (Table 5).

    The reference is the trajectory incumbent in c['parent'], not whatever incumbent a given
    refresh policy would have been holding; Table 6 covers the policy case. delta_<env> scores
    the same pair under each environment, which is the part the gate never sees.
    """
    rows = []
    for c in view.run["candidates"]:
        env = c["env"]
        deltas = {e: 100 * (view.gt_acc(c["prompt"], e) - view.gt_acc(c["parent"], e)) for e in ENVS}
        rows.append({
            "seed": view.run["seed"], "cid": c["id"], "round": c["round"], "env": env,
            "inc_acc": view.gt_acc(c["parent"], env), "cand_acc": view.gt_acc(c["prompt"], env),
            "delta_pp": deltas[env], "outcome": outcome(deltas[env]),
            "wins": c["wins"], "losses": c["losses"], "accepted": c["accepted"], "note": c["note"],
            **{f"delta_{e}": deltas[e] for e in ENVS},
        })
    return rows


POLICIES = {
    "P1": ("Frozen reference", "Never refresh"),
    "P2": ("Per-batch refresh", "Refresh every batch"),
    "P3": ("Environment-triggered refresh", "Refresh after detected environment changes"),
}


def simulate(view, policy, schedule=None, frozen_mode=None, fixed_age=None, with_records=False):
    """Replay the candidate pool through a reference policy (dry run: nothing is regenerated).

    with_records adds the per-decision trace and the false-reject count used by Table 6; it is
    off by default so the dict Table 3 logs stays unchanged.

    All three policies choose among the same candidates produced by the trajectory in
    pipeline.py, so final accuracy can never exceed the best candidate in that pool. The
    policies differ in which candidates they accept and in how many model calls they need.

    P1: compare against stored outputs, never rerun ("initial" = round-0 reference,
        "last_accepted" = outputs recorded when the current incumbent was accepted).
    P2: rerun the incumbent under the current environment every batch.
    P3: rerun when the current environment fingerprint differs from the one recorded with the
        reference; after an accept, the candidate's own fresh outputs become the reference
        (no extra cost). The fingerprint is the model/decoding/extractor config string a
        deployment can read from its own settings, so P3 never consults the hidden schedule.
    fixed_age: (ablation) always use the snapshot from round k - fixed_age, stored at its time.
    """
    frozen_mode = frozen_mode or config.FROZEN_MODE
    snaps = view.run["snapshots"]
    inc = snaps[0]["prompt"]
    ref = {"prompt": inc, "env": view.env_at(0, schedule), "fresh": False}
    calls = {"proposer": 0, "candidate_eval": 0, "reference_refresh": 0}
    refreshes = accepted = false_acc = false_rej = 0
    inflations = []
    records = []

    for c in view.run["candidates"]:
        k = c["round"]
        X = view.env_at(k, schedule)
        calls["proposer"] += 1 + view.n_dev       # one proposal + dev pass to find errors
        calls["candidate_eval"] += view.n

        if fixed_age is not None:
            r = snaps[max(0, k - fixed_age)]
            ref = {"prompt": r["prompt"], "env": view.env_at(r["round"], schedule), "fresh": False}
        elif policy == "P2" or (policy == "P3" and ENVS[ref["env"]].fingerprint != ENVS[X].fingerprint):
            ref = {"prompt": inc, "env": X, "fresh": True}
            refreshes += 1
            calls["reference_refresh"] += view.n

        c_lab = view.labels(c["prompt"], X)
        rerun = view.rerun(ref["prompt"], X)
        ref_lab = rerun if ref["fresh"] else view.stored(ref["prompt"], ref["env"], X)
        w, l, _, _ = pair(c_lab, ref_lab)
        inflations.append(win_rate(c_lab, ref_lab) - win_rate(c_lab, rerun))

        accept = w > l
        inc_acc, cand_acc = view.gt_acc(inc, X), view.gt_acc(c["prompt"], X)
        gt_better = cand_acc > inc_acc
        if with_records:
            fw, fl, _, _ = pair(c_lab, rerun)
            records.append({
                "seed": view.run["seed"], "policy": policy, "cid": c["id"], "round": k, "env": X,
                "inc_prompt": inc, "cand_prompt": c["prompt"], "inflation": inflations[-1],
                "fresh_wins": fw, "fresh_losses": fl,
                "ref_env": ref["env"], "ref_fresh": ref["fresh"], "wins": w, "losses": l,
                "accepted": accept, "inc_acc": inc_acc, "cand_acc": cand_acc,
                "delta_pp": 100 * (cand_acc - inc_acc), "outcome": outcome(100 * (cand_acc - inc_acc)),
                "false_accept": accept and not gt_better,
                "false_reject": gt_better and not accept,
            })

        if accept:
            accepted += 1
            if not gt_better:
                false_acc += 1
            inc = c["prompt"]
            if fixed_age is None and (policy == "P3" or (policy == "P1" and frozen_mode == "last_accepted")):
                ref = {"prompt": inc, "env": X, "fresh": False}
            elif policy == "P2":
                pass  # refreshed again next batch anyway
        elif gt_better:
            false_rej += 1

    final_env = view.env_at(view.run["candidates"][-1]["round"], schedule)
    out = {
        "policy": policy,
        "evaluated": len(view.run["candidates"]),
        "accepted": accepted,
        "false_accepts": false_acc,
        "false_accept_rate": false_acc / accepted if accepted else None,
        "final_gt_acc": view.gt_acc(inc, final_env),
        "inflation": mean(inflations),
        "refreshes": refreshes,
        "calls": calls,
        "total_calls": sum(calls.values()),
    }
    if with_records:
        out["false_rejects"] = false_rej
        out["records"] = records
    return out


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def mean_sd(xs, digits=2):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "n/a"
    if len(xs) == 1:
        return f"{xs[0]:.{digits}f}"
    return f"{statistics.mean(xs):.{digits}f} ± {statistics.stdev(xs):.{digits}f}"


# Two-sided t critical values at 95%, indexed by degrees of freedom.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131}


def ci95(xs, digits=2):
    """95% t interval across seeds. Read it against zero, not against the other rows."""
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return "n/a"
    m, half = statistics.mean(xs), _T95.get(len(xs) - 1, 1.96) * statistics.stdev(xs) / math.sqrt(len(xs))
    return f"[{m - half:+.{digits}f}, {m + half:+.{digits}f}]"


def sign_count(xs):
    """How many seeds share the sign of the mean. One line of evidence that an effect is systematic."""
    xs = [x for x in xs if x is not None]
    if not xs:
        return "n/a"
    same = sum(1 for x in xs if (x > 0) == (statistics.mean(xs) > 0) and x != 0)
    return f"{same}/{len(xs)}"


def pooled_rate(num, den, digits=1):
    return f"{100 * num / den:.{digits}f}" if den else "n/a"

