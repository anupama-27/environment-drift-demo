"""Replay refresh policies on a recorded run and measure what a stale reference cost.

    measured win rate   = share of paired items where the candidate is right and the reference wrong
    drift inflation     = win rate vs the stored reference - win rate vs the same reference rerun now
    false accept        = an accepted candidate whose accuracy under the current environment is
                          not higher than the incumbent's

Semantics are those of toolkit/drift/analysis.py, the code behind every number in the paper,
generalized from its fixed E1-E4 to whatever environments the run log declares. Nothing here
calls a model. Every policy chooses among the same recorded candidates and reads the same
label bank, so final accuracy can never exceed the best candidate in that pool; policies
differ only in which reference they compare against and how often they pay to rerun it.

Fractions stay fractions (an inflation of 0.015 is 1.5 pp); only delta_pp is in percentage
points, as in the toolkit. Results are unrounded plain JSON: formatting belongs to the
renderers, and an undefined value is None, never NaN.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from . import __version__, schema
from .envs import env_at
from .errors import DriftAuditError
from .stats import fisher_p, mean, sd, t_interval

AUDIT_SCHEMA = "driftaudit.audit/v1"
STUDY_SCHEMA = "driftaudit.study/v1"

# Ids are stable API; names are what the paper and the workbench show.
POLICIES: Dict[str, Dict[str, str]] = {
    "frozen": {"name": "Frozen",
               "rule": "Never refresh; compare with the reference stored at round 0"},
    "stored_incumbent": {"name": "Stored incumbent",
                         "rule": "Never refresh; compare with the outputs stored when the incumbent was accepted"},
    "per_batch": {"name": "Per-batch", "rule": "Refresh every batch"},
    "env_triggered": {"name": "Environment-triggered", "rule": "Refresh after detected environment changes"},
    "periodic": {"name": "Every k rounds", "rule": "Refresh once the reference is k rounds old"},
    "as_run": {"name": "As run", "rule": "The decisions the loop recorded, against the reference it recorded"},
}
CAUSES = ("stale", "anyway", "no_drift")
DEFAULT_AGES = (0, 1, 3, 5, 10)
MISSING_SHOWN = 20

_TOOL = {"name": "driftaudit", "version": __version__}
_TOTALS = ("accepted", "false_accepts", "false_rejects", "false_accept_rate", "refreshes", "calls", "total_calls",
           "final_acc", "final_prompt", "inflation", "causes")


def pair(cand: str, ref: str) -> Tuple[int, int, int, int]:
    """(wins, losses, both right, both wrong) of a candidate against a reference, item by item."""
    wins = losses = both_right = 0
    for c, r in zip(cand, ref):
        if c == "1":
            if r == "1":
                both_right += 1
            else:
                wins += 1
        elif r == "1":
            losses += 1
    return wins, losses, both_right, len(cand) - wins - losses - both_right


def outcome(delta_pp: float) -> str:
    """A false accept is a gain 'no greater than' zero, so the comparison is strict."""
    if delta_pp > 0:
        return "improved"
    return "no change" if delta_pp == 0 else "worse"


class _Ref(NamedTuple):
    """The reference a policy holds: whose outputs, stored under which environment, in which pass, and when."""
    prompt: str
    env: str
    tag: str
    round: int


class _Bank:
    """One run's label bank, read under the options of an audit."""

    def __init__(self, run, schedule, stored_scoring, margin):
        self.run = run
        self.n = run["task"]["n_items"]
        self.envs = run["environments"]
        self.schedule = schedule
        self.rescore = stored_scoring == "rescore"
        self.margin = margin
        self.notes: List[str] = []

    def labels(self, prompt, env, tag="current"):
        return schema.labels(self.run, prompt, env, tag)

    def acc(self, prompt, env):
        """Accuracy of a prompt under an environment from its stored pass (the record)."""
        lab = self.labels(prompt, env)
        return None if lab is None else lab.count("1") / self.n

    def env_at(self, k):
        return env_at(k, self.schedule)

    def same_fingerprint(self, a, b):
        return self.envs[a]["fingerprint"] == self.envs[b]["fingerprint"]

    def scored_env(self, stored_env, current_env):
        """Environment whose labels are read for a reference stored under stored_env.

        As recorded, that is stored_env itself: the labels are an anchor from when the
        outputs were stored. Under rescore the stored text is kept and read with today's
        scorer, which is the environment with the stored decoding and the current scorer.
        """
        if not self.rescore:
            return stored_env
        stored, current = self.envs[stored_env], self.envs[current_env]
        if stored["scorer"] == current["scorer"]:
            return stored_env
        for env_id in sorted(self.envs):
            env = self.envs[env_id]
            if env["decoding"] == stored["decoding"] and env["scorer"] == current["scorer"]:
                return env_id
        note = (f"rescore: no environment has decoding {stored['decoding']} with scorer {current['scorer']}; "
                f"labels stored under {stored_env} are used as recorded")
        if note not in self.notes:
            self.notes.append(note)
        return stored_env


def _decision(bank, k, env, cand, inc, ref, fresh, scored_env, c_lab, inc_lab, wins, losses, accepted=None):
    """One decision record. accepted is passed in only when the loop recorded the verdict."""
    n, margin = bank.n, bank.margin
    if accepted is None:
        accepted = wins - losses > margin
    # What the same rule would have seen had the reference been rerun under the current environment.
    rerun = bank.labels(ref.prompt, env, "rerun")
    rerun_wins = rerun_losses = rerun_accepts = inflation = None
    if rerun is not None:
        rerun_wins, rerun_losses, _, _ = pair(c_lab, rerun)
        rerun_accepts = rerun_wins - rerun_losses > margin
        if wins is not None:
            inflation = (wins - rerun_wins) / n
    inc_acc, cand_acc = inc_lab.count("1") / n, c_lab.count("1") / n
    better = cand_acc > inc_acc
    delta_pp = 100 * (cand_acc - inc_acc)
    mismatch = not fresh and not bank.same_fingerprint(ref.env, env)
    false_accept = accepted and not better
    cause = None
    if false_accept:
        if not mismatch:
            cause = "no_drift"
        elif rerun_accepts is not None:
            cause = "anyway" if rerun_accepts else "stale"
    return {
        "round": k, "env": env, "candidate": cand, "incumbent": inc,
        "ref_prompt": ref.prompt, "ref_env": ref.env, "ref_pass": ref.tag, "ref_scored_env": scored_env,
        "ref_fresh": fresh, "ref_round": ref.round, "ref_age": k - ref.round, "env_mismatch": mismatch,
        "wins": wins, "losses": losses, "rerun_wins": rerun_wins, "rerun_losses": rerun_losses,
        "inflation": inflation, "accepted": accepted, "rerun_accepts": rerun_accepts,
        "inc_acc": inc_acc, "cand_acc": cand_acc, "delta_pp": delta_pp, "outcome": outcome(delta_pp),
        "false_accept": false_accept, "false_reject": better and not accepted, "cause": cause,
    }


def _block(policy, missing, decisions=(), refreshes=0, calls=None, final_prompt=None, final_acc=None):
    """A policy's result. With labels missing it carries what to record and no numbers."""
    block = {"id": policy, "name": POLICIES[policy]["name"], "rule": POLICIES[policy]["rule"],
             "available": missing is not None and not missing,
             "missing": [{"prompt": p, "env": e, "pass": t} for p, e, t in list(missing or ())[:MISSING_SHOWN]],
             "missing_count": len(missing or ())}
    if not block["available"]:
        block.update({key: None for key in _TOTALS}, decisions=[])
        return block
    decisions = list(decisions)
    accepted = sum(d["accepted"] for d in decisions)
    false_accepts = sum(d["false_accept"] for d in decisions)
    block.update({
        "accepted": accepted,
        "false_accepts": false_accepts,
        "false_rejects": sum(d["false_reject"] for d in decisions),
        "false_accept_rate": false_accepts / accepted if accepted else None,
        "refreshes": refreshes,
        "calls": calls,
        "total_calls": sum(calls.values()),
        "final_acc": final_acc,
        "final_prompt": final_prompt,
        "inflation": mean(d["inflation"] for d in decisions if d["inflation"] is not None),
        "causes": {cause: sum(d["cause"] == cause for d in decisions) for cause in CAUSES},
        "decisions": decisions,
    })
    return block


def as_run_is_trivial(block: Optional[Mapping[str, Any]]) -> bool:
    """Whether an as_run block checks nothing a replayed policy does not.

    When every candidate was compared with its own incumbent, under the environment in
    force and in the same pass, the acceptance rule and the ground-truth check read the
    same labels, so the block shows no errors by construction. The built-in loop and the
    paper's runs record decisions of that kind.
    """
    if not block or not block.get("available"):
        return False
    return all(d["ref_prompt"] == d["incumbent"] and d["ref_env"] == d["env"] and d["ref_pass"] == "current"
               for d in block.get("decisions") or [])


def _call_costs(run):
    """Model calls a round costs before any refresh: the proposer's share and the candidate's evaluation."""
    cost = run.get("cost") or {}
    n_dev = cost.get("n_dev")
    if n_dev is None:
        n_dev = run["task"].get("n_dev") or 0
    return cost.get("proposal_calls", 1) + n_dev, run["task"]["n_items"]


def _replay(bank, policy, fixed_age, periodic_k):
    """Replay the candidate pool through a reference policy (dry run: nothing is regenerated).

    frozen            compare against the outputs stored at round 0, never rerun.
    stored_incumbent  compare against the outputs recorded when the incumbent was accepted, never rerun.
    per_batch         rerun the incumbent under the current environment every round.
    env_triggered     rerun when the current fingerprint differs from the one recorded with the
                      reference; after an accept the candidate's own outputs become the reference
                      at no extra cost. The policy never consults the schedule.
    periodic          as stored_incumbent, with a rerun whenever the reference is periodic_k rounds old.
    fixed_age         (ablation) always use the snapshot from round k - fixed_age, stored at its time.

    A rerun stays the reference in later rounds until something replaces it. When a round
    needs labels the bank lacks, the round is passed over and the replay goes on, so that
    the result lists everything that is missing rather than only the first gap.
    """
    run = bank.run
    snaps, cands, n = run["snapshots"], run["candidates"], bank.n
    per_proposal, per_eval = _call_costs(run)
    calls = {"proposer": 0, "candidate_eval": 0, "reference_refresh": 0}
    missing: Dict[Tuple[str, str, str], None] = {}
    decisions = []
    refreshes = 0
    inc = snaps[0]["prompt"] if snaps else None
    ref = _Ref(inc, bank.env_at(0), "current", 0)
    final_env = None

    def need(prompt, env, tag):
        lab = bank.labels(prompt, env, tag)
        if lab is None:
            missing.setdefault((prompt, env, tag))
        return lab

    for c in cands:
        k = c["round"]
        env = final_env = bank.env_at(k)
        calls["proposer"] += per_proposal
        calls["candidate_eval"] += per_eval

        fresh = False
        if fixed_age is not None:
            old = snaps[max(0, k - fixed_age)]
            ref = _Ref(old["prompt"], bank.env_at(old["round"]), "current", old["round"])
        elif (policy == "per_batch"
              or (policy == "env_triggered" and not bank.same_fingerprint(ref.env, env))
              or (policy == "periodic" and k - ref.round >= periodic_k)):
            ref = _Ref(inc, env, "rerun", k)
            fresh = True
            refreshes += 1
            calls["reference_refresh"] += n

        scored_env = bank.scored_env(ref.env, env)
        c_lab = need(c["prompt"], env, "current")
        ref_lab = need(ref.prompt, scored_env, ref.tag)
        inc_lab = need(inc, env, "current")
        if c_lab is None or ref_lab is None or inc_lab is None:
            continue

        wins, losses, _, _ = pair(c_lab, ref_lab)
        decision = _decision(bank, k, env, c["prompt"], inc, ref, fresh, scored_env, c_lab, inc_lab, wins, losses)
        decisions.append(decision)
        if decision["accepted"]:
            inc = c["prompt"]
            if fixed_age is None and policy in ("stored_incumbent", "env_triggered", "periodic"):
                ref = _Ref(inc, env, "current", k)

    if missing:
        return _block(policy, missing)
    final_acc = bank.acc(inc, final_env) if cands else None
    return _block(policy, missing, decisions, refreshes, calls, inc if cands else None, final_acc)


def _first_scored(run):
    """{(prompt, environment): round in which the trajectory first held or proposed that prompt under it}.

    That is when a loop that stores what it evaluates would have produced the stored outputs.
    """
    first: Dict[Tuple[str, str], int] = {}
    for entry in list(run["snapshots"]) + list(run["candidates"]):
        k = entry["round"]
        key = (entry["prompt"], entry.get("env", env_at(k, run["schedule"])))
        first[key] = min(k, first.get(key, k))
    return first


def _replay_recorded(bank):
    """The loop's own decisions, judged against the same ground truth as the replayed policies.

    Needs the reference each candidate was compared with. The verdict is the recorded one;
    wins and losses are recomputed when the bank holds both sides and are otherwise the
    recorded counts. Environments are the recorded ones, so the schedule, fixed_age and
    stored_scoring options do not apply.
    """
    run = bank.run
    snaps, cands, n = run["snapshots"], run["candidates"], bank.n
    if any("reference" not in c or "accepted" not in c for c in cands):
        return _block("as_run", None)
    per_proposal, per_eval = _call_costs(run)
    calls = {"proposer": 0, "candidate_eval": 0, "reference_refresh": 0}
    missing: Dict[Tuple[str, str, str], None] = {}
    decisions = []
    refreshes = 0
    final_prompt = final_env = None
    first_scored = _first_scored(run)

    for c in cands:
        k = c["round"]
        env = final_env = c.get("env", env_at(k, run["schedule"]))
        inc = c.get("parent", snaps[k]["prompt"])
        recorded = c["reference"]
        calls["proposer"] += per_proposal
        calls["candidate_eval"] += per_eval
        if recorded["pass"] == "rerun":
            refreshes += 1
            calls["reference_refresh"] += n
        fresh = recorded["pass"] == "rerun" and recorded["env"] == env
        ref_round = k
        if not fresh:
            # A reference the trajectory never scored before this round predates the run.
            ref_round = first_scored.get((recorded["prompt"], recorded["env"]), 0)
            if ref_round > k:
                ref_round = 0
        ref = _Ref(recorded["prompt"], recorded["env"], recorded["pass"], ref_round)

        final_prompt = c["prompt"] if c["accepted"] else inc
        c_lab, inc_lab = bank.labels(c["prompt"], env), bank.labels(inc, env)
        for prompt, lab in ((c["prompt"], c_lab), (inc, inc_lab)):
            if lab is None:
                missing.setdefault((prompt, env, "current"))
        if c_lab is None or inc_lab is None:
            continue
        ref_lab = bank.labels(ref.prompt, ref.env, ref.tag)
        if ref_lab is None:
            wins, losses = c.get("wins"), c.get("losses")
        else:
            wins, losses, _, _ = pair(c_lab, ref_lab)
        decisions.append(_decision(bank, k, env, c["prompt"], inc, ref, fresh, ref.env, c_lab, inc_lab, wins, losses,
                                   accepted=c["accepted"]))

    if missing:
        return _block("as_run", missing)
    final_acc = bank.acc(final_prompt, final_env) if cands else None
    return _block("as_run", missing, decisions, refreshes, calls, final_prompt, final_acc)


def _loaded(run):
    """Any form of a run (path, toolkit file, v1 object) as a validated v1 run with label strings."""
    return schema.load(run)


class _Options(NamedTuple):
    policies: List[str]
    schedule: Dict[str, str]
    overridden: bool
    stored_scoring: str
    margin: float
    fixed_age: Optional[int]
    periodic_k: int

    def as_dict(self):
        return {"stored_scoring": self.stored_scoring, "margin": self.margin, "schedule": self.schedule,
                "schedule_overridden": self.overridden, "fixed_age": self.fixed_age, "periodic_k": self.periodic_k}

    def bank(self, run):
        return _Bank(run, self.schedule, self.stored_scoring, self.margin)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _options(run, policies=None, schedule=None, stored_scoring="as_recorded", margin=0, fixed_age=None,
             periodic_k=3):
    if policies is None:
        policies = list(POLICIES)
    else:
        policies = [policies] if isinstance(policies, str) else list(policies)
        for policy in policies:
            if policy not in POLICIES:
                raise DriftAuditError(f"unknown policy {policy!r}; choose from {', '.join(POLICIES)}")
        policies = [p for p in POLICIES if p in policies]
    in_force = run["schedule"]
    if schedule is not None:
        try:
            in_force = {str(int(start)): env for start, env in schedule.items()}
        except (TypeError, ValueError, AttributeError):
            raise DriftAuditError("schedule must map start rounds to environment ids, "
                                  "for example {0: 'E1', 4: 'E2'}") from None
        if not in_force:
            raise DriftAuditError("schedule needs at least one entry, for example {0: 'E1'}")
        for env in in_force.values():
            if env not in run["environments"]:
                raise DriftAuditError(f"schedule names environment {env!r}, which the run does not define "
                                      f"(it defines {', '.join(run['environments'])})")
    if stored_scoring not in ("as_recorded", "rescore"):
        raise DriftAuditError(f"stored_scoring must be 'as_recorded' or 'rescore', not {stored_scoring!r}")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)):
        raise DriftAuditError(f"margin must be a number, not {margin!r}")
    if fixed_age is not None and (not _is_int(fixed_age) or fixed_age < 0):
        raise DriftAuditError(f"fixed_age must be a whole number of rounds, 0 or more, not {fixed_age!r}")
    if not _is_int(periodic_k) or periodic_k < 1:
        raise DriftAuditError(f"periodic_k must be a whole number of rounds, 1 or more, not {periodic_k!r}")
    return _Options(policies, in_force, in_force != run["schedule"], stored_scoring, margin, fixed_age, periodic_k)


def _simulate(bank, policy, options):
    if policy == "as_run":
        return _replay_recorded(bank)
    return _replay(bank, policy, options.fixed_age, options.periodic_k)


def simulate(run: Any, policy: str, *, schedule: Optional[Mapping[Any, str]] = None,
             stored_scoring: str = "as_recorded", margin: float = 0, fixed_age: Optional[int] = None,
             periodic_k: int = 3) -> Dict[str, Any]:
    """Replay one policy on a run and return its block of the audit result."""
    run = _loaded(run)
    options = _options(run, [policy], schedule, stored_scoring, margin, fixed_age, periodic_k)
    return _simulate(options.bank(run), policy, options)


def _environments(bank):
    """Environments in order of first use under the schedule in force, then the unused ones by id."""
    used: Dict[str, List[int]] = {}
    for k in range(len(bank.run["snapshots"])):
        used.setdefault(bank.env_at(k), []).append(k)
    order = sorted(used, key=lambda env_id: used[env_id][0]) + sorted(e for e in bank.envs if e not in used)
    return [{"id": env_id, "name": bank.envs[env_id].get("name", ""), "decoding": bank.envs[env_id]["decoding"],
             "scorer": bank.envs[env_id]["scorer"], "fingerprint": bank.envs[env_id]["fingerprint"],
             "detail": dict(bank.envs[env_id].get("detail") or {}),
             "first_round": used[env_id][0] if env_id in used else None, "rounds": used.get(env_id, [])}
            for env_id in order]


def _rounds(bank):
    """The recorded trajectory, one row per candidate: what was proposed against which incumbent."""
    rows = []
    for c in bank.run["candidates"]:
        k = c["round"]
        env = bank.env_at(k)
        inc = bank.run["snapshots"][k]["prompt"]
        rows.append({"round": k, "env": env, "env_changed": k > 0 and bank.env_at(k - 1) != env,
                     "incumbent": inc, "candidate": c["prompt"], "candidate_id": c["id"], "note": c.get("note"),
                     "candidate_acc": bank.acc(c["prompt"], env), "incumbent_acc": bank.acc(inc, env)})
    return rows


def _scorer_flips(bank, order):
    """Labels a scorer change flips on unchanged text, for each pair of environments that share their text."""
    flips = []
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if bank.envs[a]["decoding"] != bank.envs[b]["decoding"] or bank.envs[a]["scorer"] == bank.envs[b]["scorer"]:
                continue
            prompts = items = wrong_to_right = right_to_wrong = 0
            for h in bank.run["prompts"]:
                before, after = bank.labels(h, a), bank.labels(h, b)
                if before is None or after is None:
                    continue
                gained, lost, _, _ = pair(after, before)
                prompts += 1
                items += len(before)
                wrong_to_right += gained
                right_to_wrong += lost
            if prompts:
                flips.append({"from_env": a, "to_env": b, "prompts": prompts, "items": items,
                              "wrong_to_right": wrong_to_right, "right_to_wrong": right_to_wrong})
    return flips


def _full_bank(run):
    return all(schema.labels(run, h, env, tag) is not None
               for h in run["prompts"] for env in run["environments"] for tag in schema.PASSES)


def _audit(run, options):
    bank = options.bank(run)
    environments = _environments(bank)
    policies = {policy: _simulate(bank, policy, options) for policy in options.policies}
    return {
        "schema": AUDIT_SCHEMA,
        "tool": dict(_TOOL),
        "run": {"id": run["id"], "seed": run.get("seed"), "source": run["source"], "task": dict(run["task"]),
                "model": dict(run.get("model") or {}), "n_items": bank.n, "n_rounds": len(run["snapshots"]),
                "n_candidates": len(run["candidates"])},
        "options": options.as_dict(),
        "environments": environments,
        "rounds": _rounds(bank),
        "policies": policies,
        "scorer_flips": _scorer_flips(bank, [env["id"] for env in environments]),
        "completeness": {"full_bank": _full_bank(run), "notes": bank.notes},
    }


def audit(run: Any, *, policies: Optional[Sequence[str]] = None, schedule: Optional[Mapping[Any, str]] = None,
          stored_scoring: str = "as_recorded", margin: float = 0, fixed_age: Optional[int] = None,
          periodic_k: int = 3) -> Dict[str, Any]:
    """Audit one run: every policy replayed on its candidates, with each decision explained.

    run is a v1 run, a toolkit run file or a path to either.
    schedule        replaces the run's environment schedule (a what-if).
    stored_scoring  "as_recorded" keeps a stored reference's labels as they were recorded;
                    "rescore" reads its stored text with the current scorer.
    margin          accept iff wins - losses > margin.
    fixed_age       ablation: every policy uses the snapshot from that many rounds back.
    periodic_k      reference age at which the periodic policy reruns.

    A policy that needs labels the bank lacks comes back with available false and the list
    of what to record; a sparse bank never raises.
    """
    run = _loaded(run)
    return _audit(run, _options(run, policies, schedule, stored_scoring, margin, fixed_age, periodic_k))


def _age_pairs(bank, age, force_stored_env=None, current_env=None):
    snaps = bank.run["snapshots"]
    n, margin = bank.n, bank.margin
    out = []
    for c in bank.run["candidates"]:
        k = c["round"]
        if k - age < 0:
            continue
        ref = snaps[k - age]["prompt"]
        stored_env = force_stored_env or bank.env_at(k - age)
        env = current_env or bank.env_at(k)
        if stored_env not in bank.envs or env not in bank.envs:
            continue
        c_lab = bank.labels(c["prompt"], env)
        stored = bank.labels(ref, bank.scored_env(stored_env, env))
        rerun = bank.labels(ref, env, "rerun")
        inc_lab = bank.labels(snaps[k]["prompt"], env)
        if c_lab is None or stored is None or rerun is None or inc_lab is None:
            continue
        stored_wins, stored_losses, _, _ = pair(c_lab, stored)
        rerun_wins, rerun_losses, _, _ = pair(c_lab, rerun)
        promote = stored_wins - stored_losses > margin
        promote_rerun = rerun_wins - rerun_losses > margin      # what the same rule decides after a refresh
        better = c_lab.count("1") / n > inc_lab.count("1") / n
        out.append({
            "round": k,
            "stored_win": stored_wins / n,
            "rerun_win": rerun_wins / n,
            "inflation": (stored_wins - rerun_wins) / n,
            "promote": promote,
            "false_accept": promote and not better,
            "promote_rerun": promote_rerun,
            "false_accept_rerun": promote_rerun and not better,
            "env_changed": stored_env != env,
        })
    return out


def age_pairs(run: Any, age: int, *, schedule: Optional[Mapping[Any, str]] = None,
              force_stored_env: Optional[str] = None, current_env: Optional[str] = None,
              stored_scoring: str = "as_recorded", margin: float = 0) -> List[Dict[str, Any]]:
    """Each candidate against the trajectory's incumbent from `age` rounds earlier, stored and rerun.

    The reference is stored under the environment of its own round and the candidate scored
    under the environment of its round, unless force_stored_env and current_env fix them.
    A false accept is judged against the incumbent of the candidate's round. Pairs the bank
    cannot score are left out.
    """
    run = _loaded(run)
    options = _options(run, None, schedule, stored_scoring, margin)
    return _age_pairs(options.bank(run), age, force_stored_env, current_env)


def _across_runs(values):
    """A per-run quantity summarised over the runs that have it."""
    xs = [v for v in values if v is not None]
    m, lo, hi = t_interval(xs)
    return {"mean": m, "sd": sd(xs), "lo": lo, "hi": hi, "per_run": list(values),
            "n_positive": sum(x > 0 for x in xs),
            # How many runs share the sign of the mean: one line of evidence that an effect is systematic.
            "same_sign": sum(1 for x in xs if x != 0 and (x > 0) == (m > 0))}


def _run_inflation(pairs):
    """One run's drift inflation in percentage points: the mean over its candidate/reference pairs."""
    return 100 * mean(m["inflation"] for m in pairs) if pairs else None


def _pool_policy(policy, audits):
    blocks = [a["policies"][policy] for a in audits]
    accepted = sum(b["accepted"] for b in blocks)
    false_accepts = sum(b["false_accepts"] for b in blocks)
    finals = [b["final_acc"] for b in blocks]
    return {
        "name": POLICIES[policy]["name"],
        "accepted": accepted,
        "false_accepts": false_accepts,
        "false_rejects": sum(b["false_rejects"] for b in blocks),
        # Pooled sums numerators and denominators over runs. It is not the mean of the runs'
        # own rates, which weights a run with 2 accepts the same as a run with 9.
        "false_accept_rate_pooled": false_accepts / accepted if accepted else None,
        "final_acc": {"mean": mean(x for x in finals if x is not None), "sd": sd(x for x in finals if x is not None),
                      "per_run": finals},
        "total_calls": {"mean": mean(b["total_calls"] for b in blocks), "sd": sd(b["total_calls"] for b in blocks)},
        "refreshes": {"mean": mean(b["refreshes"] for b in blocks), "sd": sd(b["refreshes"] for b in blocks)},
        "causes": {cause: sum(b["causes"][cause] for b in blocks) for cause in CAUSES},
        "per_run": [{"id": a["run"]["id"], "seed": a["run"]["seed"], "accepted": b["accepted"],
                     "false_accepts": b["false_accepts"], "false_rejects": b["false_rejects"],
                     "final_acc": b["final_acc"], "total_calls": b["total_calls"], "refreshes": b["refreshes"]}
                    for a, b in zip(audits, blocks)],
    }


def _pool_scorer_flips(audits):
    pooled: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for a in audits:
        for flip in a["scorer_flips"]:
            row = pooled.setdefault((flip["from_env"], flip["to_env"]),
                                    {"from_env": flip["from_env"], "to_env": flip["to_env"], "prompts": 0,
                                     "items": 0, "wrong_to_right": 0, "right_to_wrong": 0})
            for key in ("prompts", "items", "wrong_to_right", "right_to_wrong"):
                row[key] += flip[key]
    return list(pooled.values())


def _verdict_flips(banks, a, b):
    """Candidates whose improved/no change/worse verdict against their parent differs between two environments."""
    n = flipped = 0
    for bank in banks:
        for c in bank.run["candidates"]:
            parent = c.get("parent", bank.run["snapshots"][c["round"]]["prompt"])
            accs = [bank.acc(h, env) for env in (a, b) for h in (c["prompt"], parent)]
            if None in accs:
                continue
            n += 1
            flipped += outcome(100 * (accs[0] - accs[1])) != outcome(100 * (accs[2] - accs[3]))
    return {"n": n, "flipped": flipped}


def study(runs: Iterable[Any], *, probe_age: Optional[int] = None, ages: Optional[Sequence[int]] = None,
          **audit_options: Any) -> Dict[str, Any]:
    """Pool the audits of several runs of one experiment (usually seeds) and probe for drift.

    policies      every policy all runs can replay: counts summed, per-run values with mean and sd.
    policy_tests  Fisher exact test of environment-triggered against each other policy on decision
                  errors. It treats every decision as independent, which overstates the evidence.
    probe         drift inflation (pp) at one reference age: references stored under the first
                  scheduled environment, everything else scored under each environment in turn.
    age           the same quantity by reference age, under the first and the last scheduled environment.

    probe_age defaults to 3 rounds, or less when the shortest run is shorter. ages defaults to
    0, 1, 3, 5 and 10 rounds, as far as the longest run reaches. audit_options are those of
    audit() and apply to every run.
    """
    runs = [_loaded(run) for run in runs]
    if not runs:
        raise DriftAuditError("study needs at least one run")
    options = [_options(run, **audit_options) for run in runs]
    audits = [_audit(run, opts) for run, opts in zip(runs, options)]
    banks = [opts.bank(run) for run, opts in zip(runs, options)]
    n_decisions = sum(len(run["candidates"]) for run in runs)

    policies = {p: _pool_policy(p, audits) for p in options[0].policies
                if all(a["policies"][p]["available"] for a in audits)}

    def errors(p):
        return policies[p]["false_accepts"] + policies[p]["false_rejects"]

    tests = []
    if "env_triggered" in policies:
        tests = [{"a": "env_triggered", "b": p, "errors_a": errors("env_triggered"), "errors_b": errors(p),
                  "n": n_decisions, "fisher_p": fisher_p(errors("env_triggered"), n_decisions, errors(p), n_decisions)}
                 for p in policies if p != "env_triggered"]

    lengths = [len(run["snapshots"]) for run in runs]
    stored_env = banks[0].env_at(0)
    if probe_age is None:
        probe_age = max(0, min(3, min(lengths) - 1))
    shared = [env for env in runs[0]["environments"] if all(env in run["environments"] for run in runs)]
    probe = {env: _across_runs([_run_inflation(_age_pairs(bank, probe_age, stored_env, env)) for bank in banks])
             for env in shared}

    if ages is None:
        ages = [a for a in DEFAULT_AGES if a < max(lengths)]
    last_env = banks[0].env_at(max(0, lengths[0] - 1))
    by_age: Dict[str, List[Dict[str, Any]]] = {}
    for env in dict.fromkeys((stored_env, last_env)):
        by_age[env] = []
        for age in ages:
            per_run_pairs = [_age_pairs(bank, age, stored_env, env) for bank in banks]
            pooled = [m for pairs in per_run_pairs for m in pairs]
            per_run = [_run_inflation(pairs) for pairs in per_run_pairs]
            m, lo, hi = t_interval([x for x in per_run if x is not None])
            # Inflation stays per run; promotions are pooled, because at the largest ages a
            # run has too few pairs to give a rate of its own.
            by_age[env].append({"age": age, "pairs": len(pooled), "mean": m, "lo": lo, "hi": hi, "per_run": per_run,
                                "promoted": sum(x["promote"] for x in pooled),
                                "false_accepts": sum(x["false_accept"] for x in pooled)})

    scorer_flips = _pool_scorer_flips(audits)
    verdict_flips = None
    if scorer_flips:
        verdict_flips = _verdict_flips(banks, scorer_flips[0]["from_env"], scorer_flips[0]["to_env"])

    return {
        "schema": STUDY_SCHEMA,
        "tool": dict(_TOOL),
        "options": options[0].as_dict(),
        "runs": [{"id": run["id"], "seed": run.get("seed"), "source": run["source"]} for run in runs],
        "source": study_source([run["source"] for run in runs]),
        "n_runs": len(runs),
        "n_decisions": n_decisions,
        "policies": policies,
        "policy_tests": tests,
        "probe": {"age": probe_age, "stored_env": stored_env, "by_env": probe},
        "age": {"stored_env": stored_env, "ages": list(ages), "by_env": by_age},
        "scorer_flips": scorer_flips,
        "verdict_flips": verdict_flips,
    }


def compatibility(runs: Sequence[Any], names: Optional[Sequence[str]] = None) -> List[str]:
    """Why these runs should not be pooled in one study; empty when they can be.

    Every run is compared with the first on task name, number of items, number of rounds,
    schedule and the fingerprint of each environment, and only the first difference is
    reported for each run. Run ids must also be unique, or the per-run table cannot tell
    the runs apart. names label the runs in the messages (default: their ids).
    """
    runs = [_loaded(run) for run in runs]
    labels = list(names) if names is not None else [run["id"] for run in runs]
    problems: List[str] = []
    if not runs:
        return problems

    def traits(run):
        envs = run["environments"]
        return [
            ("task", run["task"].get("name")),
            ("number of items", run["task"]["n_items"]),
            ("number of rounds", len(run["snapshots"])),
            ("schedule", ",".join(f"{k}:{v}" for k, v in sorted(run["schedule"].items(), key=lambda kv: int(kv[0])))),
            ("environments", ", ".join(sorted(envs))),
        ] + [(f"fingerprint of {env_id}", envs[env_id]["fingerprint"]) for env_id in sorted(envs)]

    first = traits(runs[0])
    for label, run in zip(labels[1:], runs[1:]):
        for (what, expected), (_, value) in zip(first, traits(run)):
            if value != expected:
                problems.append(f"{label}: {what} is {value}, where {labels[0]} has {expected}")
                break
    seen: Dict[str, str] = {}
    for label, run in zip(labels, runs):
        if run["id"] in seen:
            problems.append(f"{label}: run id {run['id']} is also the id of {seen[run['id']]}")
        else:
            seen[run["id"]] = label
    return problems


def study_source(sources: Sequence[str]) -> str:
    """"measured" or "synthetic" when every run is, "mixed" otherwise."""
    kinds = set(sources)
    return kinds.pop() if len(kinds) == 1 else "mixed"


def _cells(cand, ref):
    if cand is None or ref is None:
        return None
    return "".join(("b" if r == "1" else "w") if c == "1" else ("l" if r == "1" else "n") for c, r in zip(cand, ref))


def item_cells(run: Any, decision: Mapping[str, Any]) -> Dict[str, Any]:
    """Item-by-item view of one decision: the candidate against both readings of its reference.

    stored and rerun hold one character per item: w the candidate alone is right (a win),
    l the reference alone (a loss), b both, n neither. An item whose character differs
    between the two is one the refresh would have changed. rerun and reference_rerun are
    None when the bank has no rerun of the reference under the decision's environment.
    """
    run = _loaded(run)
    cand = schema.labels(run, decision["candidate"], decision["env"])
    stored = schema.labels(run, decision["ref_prompt"], decision.get("ref_scored_env", decision["ref_env"]),
                           decision.get("ref_pass", "current"))
    rerun = schema.labels(run, decision["ref_prompt"], decision["env"], "rerun")
    return {"n": run["task"]["n_items"], "stored": _cells(cand, stored), "rerun": _cells(cand, rerun),
            "candidate": cand, "reference_stored": stored, "reference_rerun": rerun}
