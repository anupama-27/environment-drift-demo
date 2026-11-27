"""Environment versions and the schedule that says which one is in force at each round.

An environment is everything that turns a prompt into a grade: the model, how it is decoded
and which scorer reads the answer. A reference measured under one environment is only
comparable with a candidate measured under the same one.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from .errors import DriftAuditError


def decoding_key(temperature: float) -> str:
    """'greedy-0.0' or 'sample-0.2'. Environments with the same key share generated text."""
    temperature = float(temperature)
    return f"{'greedy' if temperature == 0 else 'sample'}-{temperature}"


def make_fingerprint(model: str, decoding: str, scorer: str, scorer_version: Optional[str] = None,
                     extra: Optional[Mapping[str, Any]] = None) -> str:
    """Config string a deployment can read from its own settings, with no access to the schedule.

    This is the signal the environment-triggered policy refreshes on. The first three parts
    are written exactly as the paper's toolkit wrote them, so its runs keep their fingerprints.
    """
    extract = scorer if scorer_version is None else f"{scorer}@{scorer_version}"
    text = f"model={model};decode={decoding};extract={extract}"
    for key in sorted(extra or {}):
        text += f";{key}={extra[key]}"
    return text


@dataclass(frozen=True)
class Environment:
    id: str
    name: str
    decoding: str
    scorer: str
    fingerprint: str
    # Free-form settings for display. Two environments are the same when their fingerprints
    # are, so detail stays out of comparisons (and keeps the object hashable).
    detail: Dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def make(cls, *, id: Optional[str] = None, name: str = "", model: str = "", temperature: float = 0.0,
             scorer: Any = "strict", scorer_version: Optional[str] = None,
             extra: Optional[Mapping[str, Any]] = None) -> "Environment":
        """Build an environment from the settings that define it.

        scorer is a scorer id or a Scorer. Its version is part of the fingerprint unless one is
        given: an id is looked up in the scorer registry, so "strict" and get_scorer("strict")
        give the same environment. An id the registry does not know, with no version, is
        written bare. extra holds anything else that changes outputs or grades (top_p, a system prompt
        revision, a tool version); it becomes part of the fingerprint. Without an id the
        environment gets one derived from its fingerprint, so equal settings share an id.
        """
        if scorer_version is None and isinstance(scorer, str):
            from .scoring import get_scorer
            try:
                scorer_version = get_scorer(scorer).version
            except DriftAuditError:
                pass
        if scorer_version is None:
            scorer_version = getattr(scorer, "version", None)
        scorer_id = getattr(scorer, "id", scorer)
        decoding = decoding_key(temperature)
        fp = make_fingerprint(model, decoding, scorer_id, scorer_version, extra)
        detail: Dict[str, Any] = dict(extra or {})
        detail["temperature"] = float(temperature)
        if model:
            detail["model"] = model
        if scorer_version is not None:
            detail["scorer_version"] = scorer_version
        if id is None:
            id = "env-" + hashlib.sha1(fp.encode()).hexdigest()[:8]
        return cls(id=id, name=name, decoding=decoding, scorer=scorer_id, fingerprint=fp, detail=detail)

    def to_dict(self) -> Dict[str, Any]:
        """The entry stored under this environment's id in a run log."""
        return {"name": self.name, "decoding": self.decoding, "scorer": self.scorer,
                "fingerprint": self.fingerprint, "detail": dict(self.detail)}

    @classmethod
    def from_dict(cls, id: str, d: Mapping[str, Any]) -> "Environment":
        return cls(id=id, name=d.get("name", ""), decoding=d["decoding"], scorer=d["scorer"],
                   fingerprint=d["fingerprint"], detail=dict(d.get("detail") or {}))


def env_at(round_idx: int, schedule: Mapping[Any, str]) -> str:
    """Environment id in force at a round under a schedule {start_round: env_id}.

    Start rounds may be ints or the strings JSON turns them into. A round before the first
    start gets the first entry, as in the toolkit.
    """
    starts = sorted((int(start), env) for start, env in schedule.items())
    if not starts:
        raise DriftAuditError("the schedule is empty; it needs at least one entry such as {0: 'E1'}")
    current = starts[0][1]
    for start, env in starts:
        if round_idx >= start:
            current = env
    return current


def paper_environments(model_id: str) -> Dict[str, Environment]:
    """E1-E4 as the paper defines them: greedy or sampled decoding, strict or lenient extractor."""
    rows = [("E1", "Unchanged", 0.0, "v1"), ("E2", "Decoding", 0.2, "v1"),
            ("E3", "Extraction", 0.0, "v2"), ("E4", "Combined", 0.2, "v2")]
    scorer_names = {"v1": "strict numeric", "v2": "lenient numeric"}
    envs = {}
    for env_id, name, temperature, scorer in rows:
        decoding = decoding_key(temperature)
        envs[env_id] = Environment(id=env_id, name=name, decoding=decoding, scorer=scorer,
                                   fingerprint=make_fingerprint(model_id, decoding, scorer),
                                   detail={"temperature": temperature, "scorer_name": scorer_names[scorer]})
    return envs
