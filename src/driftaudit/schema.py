"""Run log v1: load, validate, save, and upgrade the files the paper's toolkit wrote.

A run log holds what an audit needs and nothing a model has to be called for: the prompts a
loop tried, the environment in force at each round, and for every prompt, environment and
pass one correct/incorrect label per evaluation item. "current" is the pass that was stored
when the prompt was evaluated, "rerun" an independent later pass. Labels are strings of 0
and 1, one character per item. The bank may be sparse.

The format is a superset of the toolkit's run files, so those load unchanged and the
analysis that produced the paper's numbers carries over.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from . import __version__
from ._paths import write_atomic
from .envs import Environment, paper_environments
from .errors import RunLogError

SCHEMA = "driftaudit.run/v1"
PASSES = ("current", "rerun")
SOURCES = ("measured", "synthetic")

_LEGACY_KEYS = ("correct", "config", "snapshots", "candidates")
_SHOWN_PROBLEMS = 5


def encode_labels(seq: Union[str, Iterable[Any]]) -> str:
    """Labels as a string of 0 and 1. Takes a sequence of 0/1 or booleans, or such a string."""
    if isinstance(seq, str):
        if seq.strip("01"):
            raise RunLogError("labels must contain only 0 and 1")
        return seq
    chars = []
    for value in seq:
        if isinstance(value, str) or value not in (0, 1):
            raise RunLogError(f"labels must contain only 0 and 1, found {value!r}")
        chars.append("1" if value else "0")
    return "".join(chars)


def decode_labels(s: str) -> List[int]:
    return [1 if ch == "1" else 0 for ch in s]


def prompt_id(text: str) -> str:
    """Key of a prompt in a run log: the first 12 hex characters of its sha1."""
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def labels(run: Mapping[str, Any], prompt: str, env: str, tag: str = "current") -> Optional[str]:
    """Labels of a prompt under an environment for one pass, or None when the bank lacks them."""
    return run.get("labels", {}).get(prompt, {}).get(env, {}).get(tag)


def is_legacy(obj: Any) -> bool:
    """A run file written by toolkit/ before the v1 format existed."""
    return isinstance(obj, dict) and "schema" not in obj and all(k in obj for k in _LEGACY_KEYS)


def _slug(text):
    return re.sub(r"[^a-z0-9.]+", "-", str(text).lower()).strip("-")


def _legacy_id(config, seed):
    model = str(config.get("model", "")).split("/")[-1]
    gsm8k = "gsm8k" in str(config.get("dataset", "")).lower()
    mock = config.get("backend") == "mock"
    if model == "Qwen2.5-1.5B-Instruct" and gsm8k and not mock:
        return f"gsm8k-qwen2.5-1.5b-seed{seed}"
    # A mock run reuses the real model's name; its id must not pass for a measured run's.
    parts = ["gsm8k" if gsm8k else _slug(config.get("dataset", "")), _slug(model), "mock" if mock else "",
             f"seed{seed}"]
    return "-".join(p for p in parts if p)


def upgrade_legacy(legacy: Mapping[str, Any]) -> Dict[str, Any]:
    """A toolkit run file as a v1 run log. The argument is left as it is.

    The toolkit ran GSM8K under the paper's four environments and its gate compared each
    candidate with the incumbent in the same pass, so those facts are filled in. The whole
    legacy config is kept under meta.config.
    """
    if not is_legacy(legacy):
        raise RunLogError("not a toolkit run file: expected the keys correct, config, snapshots and candidates")
    config = legacy["config"]
    for key in ("n_eval", "schedule"):
        if key not in config:
            raise RunLogError(f"toolkit run file has no config.{key}")
    if "prompts" not in legacy:
        raise RunLogError("toolkit run file has no prompts")
    seed = legacy.get("seed")
    model_id = config.get("model", "")

    candidates = []
    for c in legacy["candidates"]:
        c = dict(c)
        if "parent" in c and "env" in c:
            c["reference"] = {"prompt": c["parent"], "env": c["env"], "pass": "current"}
        candidates.append(c)

    return {
        "schema": SCHEMA,
        "id": _legacy_id(config, seed),
        "tool": {"name": "driftaudit", "version": __version__},
        "source": "synthetic" if config.get("backend") == "mock" else "measured",
        "seed": seed,
        "task": {"name": "GSM8K", "split": "test", "n_items": config["n_eval"], "n_dev": config.get("n_dev"),
                 "dataset": config.get("dataset"), "revision": config.get("dataset_revision"),
                 "items": "gsm8k/eval200"},
        "model": {"id": model_id, "revision": config.get("model_revision"), "backend": config.get("backend")},
        "environments": {env_id: env.to_dict() for env_id, env in paper_environments(model_id).items()},
        "schedule": {str(start): env for start, env in config["schedule"].items()},
        "prompts": dict(legacy["prompts"]),
        "snapshots": [dict(s) for s in legacy["snapshots"]],
        "candidates": candidates,
        "labels": {h: {env: {tag: encode_labels(values) for tag, values in passes.items()}
                       for env, passes in per_env.items()}
                   for h, per_env in legacy["correct"].items()},
        "cost": {"n_dev": config.get("n_dev") or 0, "proposal_calls": 1},
        "meta": {"config": config, "physical_calls": legacy.get("physical_calls")},
    }


def _is_count(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _label_problem(value, n_items):
    if isinstance(value, str):
        if value.strip("01"):
            return "must contain only 0 and 1"
    elif isinstance(value, (list, tuple)):
        if any(isinstance(v, str) or v not in (0, 1) for v in value):
            return "must contain only 0 and 1"
    else:
        return "must be a string of 0 and 1 (or an array of 0/1)"
    if _is_count(n_items) and len(value) != n_items:
        return f"has {len(value)} labels, expected {n_items} (task.n_items)"
    return None


def validate(run: Any) -> List[str]:
    """Everything that stops an object from being a v1 run log; empty when it is one.

    A toolkit run file is checked in the form it would load as.
    """
    if is_legacy(run):
        try:
            run = upgrade_legacy(run)
        except (RunLogError, KeyError, TypeError, AttributeError) as err:
            return [f"toolkit run file cannot be upgraded: {err}"]
    if not isinstance(run, dict):
        return ["a run log is a JSON object"]

    problems: List[str] = []
    found = run.get("schema")
    if found is None:
        problems.append(f'missing "schema": expected "{SCHEMA}" (or a toolkit run file with correct, config, '
                        "snapshots and candidates)")
    elif found != SCHEMA:
        problems.append(f'schema is "{found}", but this version of driftaudit reads "{SCHEMA}"; '
                        "a newer file needs a newer driftaudit")
    if not isinstance(run.get("id"), str) or not run.get("id"):
        problems.append("id must be a non-empty string")
    if run.get("source") not in SOURCES:
        problems.append('source must be "measured" or "synthetic" (synthetic for anything a mock backend produced)')

    task = run.get("task")
    n_items = task.get("n_items") if isinstance(task, dict) else None
    if not _is_count(n_items, 1):
        problems.append("task.n_items must be a positive integer: the number of evaluation items per label string")
    if "model" in run and not isinstance(run["model"], dict):
        problems.append('model must be an object such as {"id": "my-model"}')

    envs = run.get("environments")
    if not isinstance(envs, dict) or not envs:
        problems.append("environments must define at least one environment")
        envs = {}
    for env_id, env in envs.items():
        for key in ("decoding", "scorer", "fingerprint"):
            if not isinstance(env, dict) or not isinstance(env.get(key), str):
                problems.append(f"environments.{env_id}.{key} must be a string")

    schedule = run.get("schedule")
    if not isinstance(schedule, dict) or not schedule:
        problems.append('schedule must map a start round to an environment, for example {"0": "E1"}')
        schedule = {}
    for start, env_id in schedule.items():
        if not (_is_count(start) or (isinstance(start, str) and start.isdigit())):
            problems.append(f"schedule round {start!r} must be a non-negative integer")
        if env_id not in envs:
            problems.append(f"schedule sends round {start} to environment {env_id!r}, which environments does not define")

    prompts = run.get("prompts")
    if not isinstance(prompts, dict) or not all(isinstance(t, str) for t in prompts.values()):
        problems.append("prompts must map each prompt id to its text")
        prompts = prompts if isinstance(prompts, dict) else {}

    snapshots = run.get("snapshots")
    if not isinstance(snapshots, list):
        problems.append("snapshots must be a list with the incumbent at the start of each round")
        snapshots = []
    for i, snap in enumerate(snapshots):
        if not isinstance(snap, dict) or snap.get("round") != i:
            problems.append(f"snapshots[{i}] must be the snapshot of round {i}; snapshots are listed one per round, "
                            "in order")
        elif snap.get("prompt") not in prompts:
            problems.append(f"snapshots[{i}] names prompt {snap.get('prompt')!r}, which is not in prompts")
        elif "env" in snap and snap["env"] not in envs:
            problems.append(f"snapshots[{i}] names environment {snap['env']!r}, which environments does not define")

    candidates = run.get("candidates")
    if not isinstance(candidates, list):
        problems.append("candidates must be a list")
        candidates = []
    seen, last_round = set(), 0
    for i, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            problems.append(f"candidates[{i}] must be an object")
            continue
        label = f"candidate {cand.get('id', i)!r}"
        if not isinstance(cand.get("id"), str) or not cand.get("id"):
            problems.append(f"candidates[{i}].id must be a non-empty string")
        elif cand["id"] in seen:
            problems.append(f"candidate id {cand['id']!r} is used more than once")
        seen.add(cand.get("id"))
        round_idx = cand.get("round")
        if not _is_count(round_idx) or round_idx >= len(snapshots):
            problems.append(f"{label} is in round {round_idx}, but snapshots cover rounds 0 to {len(snapshots) - 1}")
        elif round_idx < last_round:
            problems.append(f"{label} is out of order: candidates are listed by round")
        else:
            last_round = round_idx
        for key in ("prompt", "parent"):
            if (key == "prompt" or key in cand) and cand.get(key) not in prompts:
                problems.append(f"{label} names {key} {cand.get(key)!r}, which is not in prompts")
        if "env" in cand and cand["env"] not in envs:
            problems.append(f"{label} names environment {cand['env']!r}, which environments does not define")
        if "accepted" in cand and not isinstance(cand["accepted"], bool):
            problems.append(f"{label}: accepted must be true or false")
        for key in ("wins", "losses"):
            if key in cand and not _is_count(cand[key]):
                problems.append(f"{label}: {key} must be a non-negative integer")
        if "reference" in cand:
            ref = cand["reference"]
            if not isinstance(ref, dict) or ref.get("prompt") not in prompts or ref.get("env") not in envs:
                problems.append(f"{label}: reference must name a prompt in prompts and an environment in environments")
            elif ref.get("pass") not in PASSES:
                problems.append(f'{label}: reference pass must be "current" or "rerun"')

    bank = run.get("labels")
    if not isinstance(bank, dict):
        problems.append("labels must map prompt id, environment and pass to a label string")
        bank = {}
    for h, per_env in bank.items():
        if h not in prompts:
            problems.append(f"labels has prompt {h!r}, which is not in prompts")
        if not isinstance(per_env, dict):
            problems.append(f"labels.{h} must map environments to passes")
            continue
        for env_id, passes in per_env.items():
            if env_id not in envs:
                problems.append(f"labels.{h} has environment {env_id!r}, which environments does not define")
            if not isinstance(passes, dict):
                problems.append(f"labels.{h}.{env_id} must map a pass to a label string")
                continue
            for tag, value in passes.items():
                if tag not in PASSES:
                    problems.append(f'labels.{h}.{env_id} has pass {tag!r}; passes are "current" and "rerun"')
                    continue
                problem = _label_problem(value, n_items)
                if problem:
                    problems.append(f"labels.{h}.{env_id}.{tag} {problem}")

    cost = run.get("cost", {})
    if not isinstance(cost, dict):
        problems.append("cost must be an object")
    else:
        for key in ("n_dev", "proposal_calls"):
            if key in cost and not _is_count(cost[key]):
                problems.append(f"cost.{key} must be a non-negative integer")
    return problems


def _normalized(run):
    """Shallow copy with labels as strings and schedule rounds as strings."""
    out = dict(run)
    out["schedule"] = {str(int(start)): env for start, env in run["schedule"].items()}
    out["labels"] = {h: {env: {tag: encode_labels(value) for tag, value in passes.items()}
                         for env, passes in per_env.items()}
                     for h, per_env in run["labels"].items()}
    return out


# Far more than any run log needs. Deeper input is refused before anything recurses into it.
MAX_DEPTH = 64


def _plain_json_problem(obj: Any) -> Optional[str]:
    """Why obj cannot be written back as standard JSON, or None.

    Non-finite numbers are not JSON, and a browser reading the run log would fail on them
    later. The walk is iterative, so a very deep object cannot exhaust the stack here.
    """
    stack = [(obj, 1, "the run log")]
    while stack:
        value, depth, where = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            return f"{where} is {value}, which JSON does not allow; store a number or null"
        if isinstance(value, (dict, list, tuple)):
            if depth > MAX_DEPTH:
                return f"the run log is nested more than {MAX_DEPTH} levels deep"
            items = value.items() if isinstance(value, dict) else enumerate(value)
            stack.extend((child, depth + 1, f"{where} > {key}") for key, child in items)
    return None


def _checked(run, what):
    problem = _plain_json_problem(run)
    if problem:
        raise RunLogError(f"{what} is not a valid run log: {problem}", [problem])
    problems = validate(run)
    if problems:
        shown = "".join(f"\n  - {p}" for p in problems[:_SHOWN_PROBLEMS])
        more = f"\n  (and {len(problems) - _SHOWN_PROBLEMS} more)" if len(problems) > _SHOWN_PROBLEMS else ""
        raise RunLogError(f"{what} is not a valid run log:{shown}{more}", problems)
    return _normalized(upgrade_legacy(run) if is_legacy(run) else run)


def load(path_or_dict: Union[str, "os.PathLike[str]", Mapping[str, Any]]) -> Dict[str, Any]:
    """Read a run log from a file or an already parsed object and return it as a valid v1 run.

    Toolkit run files are upgraded in memory. Labels come back as 0/1 strings whatever form
    they were stored in. The argument is not modified.
    """
    if isinstance(path_or_dict, (str, os.PathLike)):
        path = os.fspath(path_or_dict)
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except FileNotFoundError:
            raise RunLogError(f"{path}: no such file") from None
        except (OSError, UnicodeDecodeError) as err:
            raise RunLogError(f"{path}: cannot be read ({err})") from None
        except json.JSONDecodeError as err:
            raise RunLogError(f"{path}: not valid JSON ({err.msg} at line {err.lineno}); a run log is one JSON "
                              "object") from None
        except RecursionError:
            raise RunLogError(f"{path}: nested too deeply to be a run log (more than {MAX_DEPTH} levels)") from None
        return _checked(obj, path)
    return _checked(path_or_dict, "this object")


def save(run: Mapping[str, Any], path: Union[str, "os.PathLike[str]"]) -> None:
    """Validate a run and write it as compact JSON.

    The file is written next to its destination and moved into place, so an interrupted
    save leaves the previous file intact rather than half a run log.
    """
    text = json.dumps(_checked(run, "this run"), separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    write_atomic(path, (text + "\n").encode("utf-8"))


def new_run(*, id: str, seed: Optional[int], task: Mapping[str, Any], model: Mapping[str, Any],
            environments: Union[Mapping[str, Any], Iterable[Environment]], schedule: Mapping[Any, str],
            source: str = "measured", cost: Optional[Mapping[str, Any]] = None,
            meta: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """A valid run log with no rounds yet: prompts, snapshots, candidates and labels are empty.

    environments is a mapping of id to Environment (or to its dict), or a list of
    Environment objects. task needs at least n_items.
    """
    if not isinstance(environments, Mapping):
        environments = {env.id: env for env in environments}
    environments = {env_id: env.to_dict() if isinstance(env, Environment) else dict(env)
                    for env_id, env in environments.items()}
    run = {
        "schema": SCHEMA,
        "id": id,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": "driftaudit", "version": __version__},
        "source": source,
        "seed": seed,
        "task": dict(task),
        "model": dict(model),
        "environments": environments,
        "schedule": dict(schedule),
        "prompts": {},
        "snapshots": [],
        "candidates": [],
        "labels": {},
        "cost": dict(cost or {}),
        "meta": dict(meta or {}),
    }
    return _checked(run, "the new run")
