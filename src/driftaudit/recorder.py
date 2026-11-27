"""Record a self-improvement loop you already have, so that it can be audited.

    rec = Recorder(task="my-task", n_items=200, model="my-model")
    rec.add_labels(incumbent, env, labels)                 # one 0/1 label per evaluation item
    rec.add_labels(candidate, env, candidate_labels)
    rec.add_round(candidate=candidate, incumbent=incumbent, env=env, accepted=True,
                  reference=(incumbent, env))
    run = rec.save("run.json")

The recorder only writes down what your loop measured. What an audit can say afterwards
depends on what is in the label bank: to tell a stale reference from a fresh one it needs the
incumbent's labels under the environment of each round, stored and rerun (rerun=True).
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

from . import schema
from .envs import Environment
from .errors import DriftAuditError
from .loop import default_run_id

Labels = Union[str, Sequence[Any]]


class Recorder:
    def __init__(self, task: Union[str, Mapping[str, Any]] = "task", n_items: Optional[int] = None,
                 model: Union[str, Mapping[str, Any]] = "model", seed: Optional[int] = 0, n_dev: int = 0,
                 source: str = "measured", id: Optional[str] = None) -> None:
        """task and model are names, or the dicts to store in the run log.

        n_items is the number of evaluation items, the length of every label vector. n_dev is
        how many extra model calls your loop spends per round to produce a candidate; it only
        enters the call counts of an audit. source is "measured", or "synthetic" for anything
        that did not come from a real model.
        """
        if not isinstance(n_items, int) or isinstance(n_items, bool) or n_items < 1:
            raise DriftAuditError("Recorder needs n_items, the number of evaluation items "
                                  "(the length of each label vector), as a positive integer.")
        if source not in schema.SOURCES:
            raise DriftAuditError('source must be "measured" or "synthetic".')
        self.n_items = n_items
        self.task = dict(task) if isinstance(task, Mapping) else {"name": task}
        self.task.update(n_items=n_items, n_dev=n_dev)
        self.model = dict(model) if isinstance(model, Mapping) else {"id": model}
        self.seed = seed
        self.n_dev = n_dev
        self.source = source
        self.id = id
        self._prompts: Dict[str, str] = {}
        self._envs: Dict[str, Environment] = {}
        self._env_ids: Dict[str, str] = {}      # fingerprint -> id in this run
        self._labels: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._snapshots: List[Dict[str, Any]] = []
        self._candidates: List[Dict[str, Any]] = []

    def add_labels(self, prompt: str, env: Environment, labels: Labels, rerun: bool = False) -> None:
        """Store one evaluation of a prompt under an environment.

        labels is a sequence of 0/1 (or booleans, or a "0110..." string), one per evaluation
        item, always in the same item order. The first evaluation of a prompt under an
        environment is its stored pass. An independent later evaluation of the same pair goes
        in with rerun=True; a newer rerun replaces the previous one.
        """
        encoded = self._encode(labels)
        pid = self._prompt_id(prompt, register=True)
        env_id = self._env_id(env)
        passes = self._labels.setdefault(pid, {}).setdefault(env_id, {})
        if not rerun and passes.get("current") not in (None, encoded):
            raise DriftAuditError(
                f"This prompt already has stored labels under {env_id}, and these differ. A second "
                "evaluation of the same prompt under the same environment is a rerun: pass rerun=True.")
        passes["rerun" if rerun else "current"] = encoded

    def add_round(self, *, candidate: str, incumbent: str, env: Environment, accepted: bool,
                  reference: Optional[Tuple[Any, ...]] = None, note: str = "") -> Dict[str, Any]:
        """Record one round: the candidate, the incumbent it tried to replace and the decision.

        env is the environment in force in this round. reference says what your gate compared
        the candidate with, as (prompt, env) for labels stored earlier or (prompt, env,
        "rerun") for a reference evaluated again; with it an audit can replay your own
        decisions next to the other policies. Rounds are numbered in the order they are added.
        """
        if not isinstance(accepted, bool):
            raise DriftAuditError("accepted must be True or False.")
        candidate_id = self._prompt_id(candidate, what="candidate")
        incumbent_id = self._prompt_id(incumbent, what="incumbent")
        env_id = self._env_id(env)
        candidate_labels = schema.labels(self._bank(), candidate_id, env_id)
        if candidate_labels is None:
            raise DriftAuditError(f"The candidate has no labels under {env_id}, the environment of this "
                                  "round. Call add_labels(candidate, env, labels) before add_round.")
        record: Dict[str, Any] = {"id": f"C{len(self._candidates) + 1}", "round": len(self._candidates),
                                  "prompt": candidate_id, "parent": incumbent_id, "env": env_id,
                                  "note": note, "accepted": accepted}
        compared = schema.labels(self._bank(), incumbent_id, env_id)
        if reference is not None:
            if not isinstance(reference, (tuple, list)) or len(reference) not in (2, 3):
                raise DriftAuditError('reference must be (prompt, env) or (prompt, env, "rerun").')
            tag = reference[2] if len(reference) == 3 else "current"
            if tag not in schema.PASSES:
                raise DriftAuditError('The third part of reference must be "current" or "rerun".')
            ref_prompt = self._prompt_id(reference[0], what="reference")
            ref_env = self._env_id(reference[1])
            compared = schema.labels(self._bank(), ref_prompt, ref_env, tag)
            if compared is None:
                raise DriftAuditError(
                    f"The reference has no {'rerun' if tag == 'rerun' else 'stored'} labels under {ref_env}. "
                    "Add them with add_labels" + ("(..., rerun=True)" if tag == "rerun" else "") + " before add_round.")
            record["reference"] = {"prompt": ref_prompt, "env": ref_env, "pass": tag}
        if compared is not None:
            record["wins"] = sum(1 for c, r in zip(candidate_labels, compared) if c == "1" and r == "0")
            record["losses"] = sum(1 for c, r in zip(candidate_labels, compared) if c == "0" and r == "1")
        self._snapshots.append({"round": record["round"], "prompt": incumbent_id, "env": env_id})
        self._candidates.append(record)
        return dict(record)

    def to_run(self) -> Dict[str, Any]:
        """Everything recorded so far as a valid v1 run log."""
        if not self._candidates:
            raise DriftAuditError("Nothing to save yet: record at least one round with add_round.")
        # The schedule is what the rounds say: an entry wherever the environment changes.
        schedule: Dict[int, str] = {}
        for snapshot in self._snapshots:
            if not schedule or snapshot["env"] != schedule[max(schedule)]:
                schedule[snapshot["round"]] = snapshot["env"]
        model_name = str(self.model.get("id", ""))
        run = schema.new_run(
            id=self.id or default_run_id(str(self.task.get("name", "")), model_name, self.seed or 0),
            seed=self.seed, task=self.task, model=self.model, environments=self._envs,
            schedule=schedule, source=self.source, cost={"n_dev": self.n_dev, "proposal_calls": 1})
        run.update(prompts=dict(self._prompts), snapshots=[dict(s) for s in self._snapshots],
                   candidates=[dict(c) for c in self._candidates],
                   labels={p: {e: dict(passes) for e, passes in per_env.items()}
                           for p, per_env in self._labels.items()})
        return schema.load(run)

    def save(self, path: Union[str, "os.PathLike[str]"]) -> Dict[str, Any]:
        """Write the run log and return it."""
        run = self.to_run()
        schema.save(run, path)
        return run

    def _bank(self) -> Dict[str, Any]:
        return {"labels": self._labels}

    def _encode(self, labels: Labels) -> str:
        encoded = schema.encode_labels(labels)
        if len(encoded) != self.n_items:
            raise DriftAuditError(f"Got {len(encoded)} labels, but the task has {self.n_items} evaluation "
                                  "items. Every label vector needs one entry per item, in the same order.")
        return encoded

    def _prompt_id(self, prompt: Any, register: bool = False, what: str = "prompt") -> str:
        if not isinstance(prompt, str) or not prompt:
            raise DriftAuditError(f"The {what} must be the prompt text, a non-empty string.")
        pid = schema.prompt_id(prompt)
        if register:
            self._prompts.setdefault(pid, prompt)
        elif pid not in self._prompts:
            raise DriftAuditError(f"Unknown {what}: no labels were added for this prompt. Call "
                                  "add_labels(prompt, env, labels) first.")
        return pid

    def _env_id(self, env: Any) -> str:
        if not isinstance(env, Environment):
            raise DriftAuditError("env must be a driftaudit.Environment; build one with "
                                  "Environment.make(model=..., temperature=..., scorer=...).")
        known = self._env_ids.get(env.fingerprint)
        if known is not None:
            return known
        derived = "env-" + hashlib.sha1(env.fingerprint.encode()).hexdigest()[:8]
        if not env.id or env.id == derived:
            # No id was chosen for it, so it is numbered in order of first use.
            number = len(self._envs) + 1
            while f"E{number}" in self._envs:
                number += 1
            env_id = f"E{number}"
        elif env.id in self._envs:
            raise DriftAuditError(
                f"Two different environments are both called {env.id!r}: {self._envs[env.id].fingerprint} "
                f"and {env.fingerprint}. Give each its own id.")
        else:
            env_id = env.id
        self._envs[env_id] = dataclasses.replace(env, id=env_id)
        self._env_ids[env.fingerprint] = env_id
        return env_id


class Reference(NamedTuple):
    prompt: str
    env: Environment
    labels: str


class ReferenceStore:
    """The reference a live loop compares candidates with, and the environment it was measured in.

        store = ReferenceStore()                    # environment-triggered refresh
        if store.stale(env):
            store.set(incumbent, env, evaluate(incumbent, env))
        wins, losses = compare(candidate_labels, store.reference.labels)

    stale(env) is True when the fingerprint of today's environment differs from the one stored
    with the reference, which is the check the environment-triggered policy runs.
    """

    POLICIES = ("env_triggered", "per_batch", "frozen")

    def __init__(self, policy: str = "env_triggered") -> None:
        if policy not in self.POLICIES:
            raise DriftAuditError(f"Unknown refresh policy {policy!r}. Choose one of: {', '.join(self.POLICIES)}.")
        self.policy = policy
        self._reference: Optional[Reference] = None

    @property
    def reference(self) -> Optional[Reference]:
        """(prompt, env, labels) of the stored reference, or None before the first set()."""
        return self._reference

    def set(self, prompt: str, env: Environment, labels: Labels) -> Reference:
        if not isinstance(env, Environment):
            raise DriftAuditError("env must be a driftaudit.Environment.")
        self._reference = Reference(prompt, env, schema.encode_labels(labels))
        return self._reference

    def stale(self, env: Environment) -> bool:
        """Whether the reference should be evaluated again before it is used under env."""
        if self._reference is None or self.policy == "per_batch":
            return True
        if self.policy == "frozen":
            return False
        return env.fingerprint != self._reference.env.fingerprint
