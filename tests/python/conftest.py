"""Shared fixtures: the five paper runs, the toolkit they are checked against, small runs."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLKIT = os.path.join(ROOT, "toolkit")
GOLDEN = os.path.join(ROOT, "tests", "golden")
SEEDS = (1, 2, 3, 4, 5)


def paper_run_path(seed):
    return os.path.join(TOOLKIT, "runs", f"run_seed{seed}_hf_Qwen2.5-1.5B-Instruct_n200_r11.json")


@pytest.fixture(scope="session")
def legacy_runs():
    """The saved run files exactly as the toolkit wrote them, keyed by seed."""
    runs = {}
    for seed in SEEDS:
        with open(paper_run_path(seed), encoding="utf-8") as f:
            runs[seed] = json.load(f)
    return runs


@pytest.fixture(scope="session")
def paper_runs(legacy_runs):
    """The same five runs upgraded to the v1 format, keyed by seed."""
    from driftaudit import schema
    return {seed: schema.load(run) for seed, run in legacy_runs.items()}


@pytest.fixture(scope="session")
def toolkit():
    """The toolkit modules every number in the paper came from. Read-only: they are the oracle.

    drift.config reads its settings from the environment at import time, so the variables
    are pinned first. Bytecode writing is switched off for the import so that nothing is
    created under toolkit/.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("DRIFT_SEEDS", "1,2,3,4,5")
    for name in ("DRIFT_MODEL", "DRIFT_STORED_SCORING", "DRIFT_FROZEN_MODE", "DRIFT_BACKEND"):
        patch.delenv(name, raising=False)
    patch.syspath_prepend(TOOLKIT)
    patch.setattr(sys, "dont_write_bytecode", True)
    try:
        from drift import analysis, config, envs, extract
    finally:
        patch.undo()
    return types.SimpleNamespace(analysis=analysis, config=config, envs=envs, extract=extract)


def bits(key, n, per_mille):
    """n reproducible 0/1 labels, each 1 with probability per_mille/1000, derived from sha1."""
    out = []
    for i in range(n):
        digest = hashlib.sha1(f"{key}/{i}".encode()).hexdigest()
        out.append(1 if int(digest[:8], 16) % 1000 < per_mille else 0)
    return out


def make_legacy_run(seed, n_items=30, rounds=6, schedule=None, accept_bias=0):
    """A run file in the toolkit's own format with sha1-derived labels.

    Small enough to build in a test and shaped like the real ones (one candidate a round,
    E1-E4 fully measured, greedy reruns nearly repeating the stored pass), so the toolkit's
    simulate and the new engine can be compared on many more shapes than the five saved runs.
    """
    schedule = schedule or {0: "E1", 2: "E2", 4: "E4"}
    prompts = {f"p{i}": f"prompt {i} of seed {seed}" for i in range(rounds + 1)}
    correct = {}
    for h in prompts:
        skill = 450 + int(hashlib.sha1(f"{seed}/{h}".encode()).hexdigest()[:4], 16) % 300
        greedy = bits(f"{seed}/{h}/greedy", n_items, skill)
        noise = bits(f"{seed}/{h}/greedy-noise", n_items, 60)
        greedy_rerun = [g ^ x for g, x in zip(greedy, noise)]
        sample = {tag: bits(f"{seed}/{h}/sample/{tag}", n_items, skill - 30) for tag in ("current", "rerun")}
        # The lenient extractor only ever turns a wrong answer into a right one.
        lift = bits(f"{seed}/{h}/lenient", n_items, 150)
        correct[h] = {
            "E1": {"current": greedy, "rerun": greedy_rerun},
            "E2": dict(sample),
            "E3": {"current": [g | x for g, x in zip(greedy, lift)],
                   "rerun": [g | x for g, x in zip(greedy_rerun, lift)]},
            "E4": {tag: [s | x for s, x in zip(sample[tag], lift)] for tag in sample},
        }

    def env_at(k):
        return schedule[max(r for r in schedule if r <= k)]

    snapshots, candidates = [], []
    incumbent = "p0"
    for k in range(rounds):
        env = env_at(k)
        snapshots.append({"round": k, "prompt": incumbent, "env": env})
        cand = f"p{k + 1}"
        c, i = correct[cand][env]["current"], correct[incumbent][env]["current"]
        wins = sum(1 for a, b in zip(c, i) if a and not b)
        losses = sum(1 for a, b in zip(c, i) if b and not a)
        accepted = wins + accept_bias > losses
        candidates.append({"id": f"C{k + 1}", "round": k, "prompt": cand, "parent": incumbent, "env": env,
                           "note": "ok", "wins": wins, "losses": losses, "accepted": accepted, "dev_acc": 0.5})
        if accepted:
            incumbent = cand
    return {
        "seed": seed,
        "config": {"model": "Qwen/Qwen2.5-1.5B-Instruct", "model_revision": "rev", "dataset": "openai/gsm8k (main)",
                   "dataset_revision": "rev", "n_dev": 7, "n_eval": n_items, "rounds": rounds,
                   "schedule": {str(r): e for r, e in schedule.items()}, "backend": "mock"},
        "prompts": prompts, "snapshots": snapshots, "candidates": candidates, "correct": correct,
        "physical_calls": 0,
    }


def small_run(labels, schedule, snapshots, candidates, n_items, reruns=None, environments=None, **extra):
    """A v1 run from plain label lists: labels[prompt][env] is the stored pass.

    reruns[(prompt, env)] overrides the rerun pass, which otherwise repeats the stored one;
    a value of None leaves that rerun out of the bank.
    """
    from driftaudit import envs as da_envs
    from driftaudit import schema
    reruns = reruns or {}
    environments = environments or da_envs.paper_environments("test-model")
    run = schema.new_run(id=extra.pop("id", "small"), seed=extra.pop("seed", 1),
                         task={"name": "toy", "n_items": n_items, "n_dev": extra.pop("n_dev", 0)},
                         model={"id": "test-model"}, environments=environments, schedule=schedule,
                         source="synthetic", **extra)
    for h, per_env in labels.items():
        run["prompts"][h] = f"text of {h}"
        for env, lab in per_env.items():
            entry = {"current": schema.encode_labels(lab)}
            rerun = reruns.get((h, env), lab)
            if rerun is not None:
                entry["rerun"] = schema.encode_labels(rerun)
            run["labels"].setdefault(h, {})[env] = entry
    run["snapshots"] = [{"round": i, "prompt": p} for i, p in enumerate(snapshots)]
    run["candidates"] = [dict(c) for c in candidates]
    # A prompt the loop held or proposed belongs in the log even when nothing was measured for it.
    for h in list(snapshots) + [c[k] for c in candidates for k in ("prompt", "parent") if k in c]:
        run["prompts"].setdefault(h, f"text of {h}")
    return schema.load(run)
