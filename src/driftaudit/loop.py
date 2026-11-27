"""The built-in self-improvement loop: the paper's pipeline (toolkit/drift/pipeline.py) with the
task, the model backend, the scorers and the environment schedule as parameters.

Step 1 (trajectory). Each round snapshots the incumbent instruction, shows the proposer some
    development errors, gets a candidate, scores candidate and incumbent on the evaluation
    items under the environment in force, and accepts the candidate when it has more wins
    than losses. This builds the candidate pool and the reference snapshots.

Step 2 (measurement). Every instruction that appeared is scored under every environment,
    twice: "current" is the record made when it was evaluated (what a loop stores) and
    "rerun" is a fresh generation later (what a refresh would produce). The rerun is always
    generated again, also under greedy decoding, with its items sent in a seeded shuffled
    batch order so that it is not a replay of the stored pass.

The run log that comes out holds labels only. An audit replays reference policies on it
without calling the model again.
"""
from __future__ import annotations

import dataclasses
import gzip
import io
import json
import os
import platform
import random
import re
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from . import schema
from ._paths import write_atomic
from .backends.base import Backend
from .backends.cache import Cache, generation_key, key
from .envs import Environment, decoding_key, env_at
from .errors import DriftAuditError
from .scoring import Scorer, get_scorer, score_outputs
from .tasks import Task

# The paper's schedule: greedy and strict, then sampling from round 4, then the lenient
# scorer as well from round 8.
DEFAULT_SCHEDULE = "0:greedy/strict,4:sample@0.2/strict,8:sample@0.2/lenient"
PASSES = ("current", "rerun")

FORMAT_LINE = "Put the final answer as a plain number in \\boxed{} on the last line."
INITIAL_PROMPT = "You are a careful math tutor. Solve the problem step by step. " + FORMAT_LINE
TEXT_FORMAT_LINE = "Reply with the answer only, with no explanation."
TEXT_INITIAL_PROMPT = "Answer the question. " + TEXT_FORMAT_LINE
PROPOSER_SYSTEM = "You improve instructions for a model that answers questions with one short, checkable answer."

_NUMERIC_SCORERS = ("strict", "lenient")
_TEXT_SCORERS = ("exact", "exact-normalized")
_HEARTBEAT_SECONDS = 10.0
# Largest outputs file read, after decompression. A 2,000-item, 50-round run writes about 20 MB.
MAX_OUTPUTS_BYTES = 512 * 2 ** 20

Progress = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class EnvSpec:
    """One environment of a schedule, before a model is attached to it."""

    id: str
    name: str
    temperature: float
    scorer: str

    @property
    def decoding(self) -> str:
        return decoding_key(self.temperature)


@dataclass(frozen=True)
class Schedule:
    spec: str
    # Round from which each environment applies.
    starts: Dict[int, str]
    # Every decoding crossed with every scorer that appears, whether scheduled or not: the
    # measurement step needs the unscheduled combinations to tell the two changes apart.
    environments: Dict[str, EnvSpec]


def default_schedule(rounds: int) -> str:
    """The paper's schedule stretched or shrunk to `rounds` rounds.

    The paper changes the decoding at round 4 and the extractor at round 8 of 11. A shorter
    or longer run keeps those proportions, so that both changes happen inside it: with two
    rounds there is room for one combined change only, and with one round for none.
    """
    if rounds <= 1:
        return "0:greedy/strict"
    if rounds == 2:
        return "0:greedy/strict,1:sample@0.2/lenient"
    decoding = max(1, round(4 * rounds / 11))
    extractor = min(rounds - 1, max(decoding + 1, round(8 * rounds / 11)))
    return f"0:greedy/strict,{decoding}:sample@0.2/strict,{extractor}:sample@0.2/lenient"


def parse_schedule(spec: str) -> Schedule:
    """Read "ROUND:DECODING/SCORER,..." such as the default, DEFAULT_SCHEDULE.

    DECODING is `greedy` or `sample@T`; SCORER is a scorer id (strict, lenient, exact,
    exact-normalized, or one you registered). Ids run E1, E2, ... with the first scorer under
    each decoding, then the second scorer, so the default gives the paper's E1 greedy/strict,
    E2 sample/strict, E3 greedy/lenient and E4 sample/lenient.
    """
    example = f"for example {DEFAULT_SCHEDULE}"
    entries: Dict[int, Tuple[float, str]] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)\s*:\s*([^/\s]+)\s*/\s*(\S+)", part)
        if not match:
            raise DriftAuditError(f"Cannot read the schedule entry {part!r}. Write ROUND:DECODING/SCORER, {example}.")
        start, decoding, scorer_id = int(match.group(1)), match.group(2).lower(), match.group(3)
        if start in entries:
            raise DriftAuditError(f"The schedule sets round {start} twice.")
        if decoding == "greedy":
            temperature = 0.0
        else:
            sampled = re.fullmatch(r"sample@(\d+(?:\.\d+)?)", decoding)
            temperature = float(sampled.group(1)) if sampled else 0.0
            if temperature <= 0:
                raise DriftAuditError(
                    f"Cannot read the decoding {match.group(2)!r} in the schedule. Use greedy, or "
                    "sample@T with a temperature above 0 such as sample@0.2.")
        entries[start] = (temperature, get_scorer(scorer_id).id)
    if 0 not in entries:
        raise DriftAuditError(f"The schedule must say which environment applies from round 0, {example}.")

    ordered = [entries[start] for start in sorted(entries)]
    temperatures = list(dict.fromkeys(t for t, _ in ordered))
    scorers = list(dict.fromkeys(s for _, s in ordered))
    first = ordered[0]
    combos = [(t, s) for s in scorers for t in temperatures]
    names = [_relation(combo, first) for combo in combos]
    environments: Dict[str, EnvSpec] = {}
    ids: Dict[Tuple[float, str], str] = {}
    for number, (combo, name) in enumerate(zip(combos, names), 1):
        if names.count(name) > 1:
            # More than two decodings or scorers: say which one this is.
            changed = [_decoding_label(combo[0])] if combo[0] != first[0] else []
            changed += [combo[1]] if combo[1] != first[1] else []
            name = f"{name} ({'/'.join(changed)})"
        ids[combo] = f"E{number}"
        environments[f"E{number}"] = EnvSpec(f"E{number}", name, combo[0], combo[1])
    starts = {start: ids[entries[start]] for start in sorted(entries)}
    return Schedule(spec=spec.strip(), starts=starts, environments=environments)


def _relation(combo: Tuple[float, str], first: Tuple[float, str]) -> str:
    """Name of an environment by what differs from the one the run starts in."""
    decoding_changed, scorer_changed = combo[0] != first[0], combo[1] != first[1]
    if decoding_changed and scorer_changed:
        return "Combined"
    if decoding_changed:
        return "Decoding"
    return "Extraction" if scorer_changed else "Unchanged"


def _decoding_label(temperature: float) -> str:
    return "greedy" if temperature == 0 else f"sample@{temperature:g}"


def build_environments(schedule: Schedule, backend: Backend) -> Dict[str, Environment]:
    """The schedule's environments with fingerprints for this backend.

    Everything the backend says about itself goes into the fingerprint next to the decoding
    and the scorer version, so a new model revision or serving stack is a new environment.
    """
    info = dict(backend.describe())
    model = str(info.pop("model"))
    extra = {name: value for name, value in info.items() if value is not None}
    environments = {}
    for spec in schedule.environments.values():
        scorer = get_scorer(spec.scorer)
        env = Environment.make(id=spec.id, name=spec.name, model=model, temperature=spec.temperature,
                               scorer=scorer, extra=extra)
        detail = dict(env.detail, scorer_name=scorer.name)
        environments[spec.id] = dataclasses.replace(env, detail=detail)
    return environments


def item_seed(seed: int, tag: str, item_id: str) -> int:
    return int(key(seed, tag, item_id)[:8], 16)


def proposer_messages(current_prompt: str, failures: Sequence[Dict[str, Any]], system: str) -> List[Dict[str, str]]:
    lines = [f"Current instruction:\n{current_prompt}\n", "The model got these problems wrong:\n"]
    for i, failure in enumerate(failures, 1):
        gold = failure["gold"]
        lines.append(f"Problem {i}: {failure['question']}")
        lines.append(f"Model's answer: {failure['output'][-600:]}")
        lines.append(f"Correct final answer: {gold if isinstance(gold, str) else format(gold, 'g')}\n")
    lines.append("Write an improved instruction that would help the model avoid these mistakes. "
                 "Keep it under 120 words. Return only the new instruction inside <prompt></prompt>.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]


def parse_candidate(text: str, current_prompt: str, format_line: str) -> Tuple[str, str]:
    """(candidate instruction, note). Falls back to the current instruction if parsing fails."""
    match = re.search(r"<prompt>(.*?)</prompt>", text, flags=re.S)
    cand = match.group(1).strip() if match else ""
    if not cand and "<prompt>" in text:
        cand = text.split("<prompt>", 1)[1].strip()
    if not cand and len(text.strip()) < 1200:
        cand = text.strip()   # the model sometimes skips the tags
    cand = re.sub(r"^\s*(\*\*)?(new |improved )?(prompt|instruction)s?:?(\*\*)?\s*", "", cand, flags=re.I).strip()
    if len(cand) < 20:
        return current_prompt, "fallback_unparsed"
    if format_line:
        # Keep the answer format fixed so that an edit to the instruction does not change what
        # the scorer sees. With the default line, a rewrite that still asks for \boxed{} counts
        # as keeping it, as in the paper's runs.
        marker = "boxed" if "boxed" in format_line else format_line
        if marker not in cand:
            return cand + " " + format_line, "format_line_added"
    return cand, "ok"


def pick_failures(dev_items: Sequence[Dict[str, Any]], dev_outputs: Sequence[str],
                  dev_correct: Sequence[int], round_idx: int, k: int) -> List[Dict[str, Any]]:
    wrong = [i for i, ok in enumerate(dev_correct) if not ok]
    if not wrong or k < 1:
        return []
    start = (round_idx * k) % len(wrong)   # rotate so each round sees different errors
    chosen = (wrong[start:] + wrong[:start])[:k]
    return [{"question": dev_items[i]["question"], "output": dev_outputs[i], "gold": dev_items[i]["gold"]}
            for i in chosen]


class _Status:
    """Sends one-line messages to the caller, and a sign of life during long generations."""

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._last = time.monotonic()

    def say(self, message: str) -> None:
        self._last = time.monotonic()
        if self._progress is not None:
            self._progress(message)

    def heartbeat(self, message: str) -> None:
        if time.monotonic() - self._last >= _HEARTBEAT_SECONDS:
            self.say(message)


class _Runner:
    def __init__(self, backend: Backend, cache: Cache, seed: int, max_new_tokens: int,
                 batch_size: int, status: _Status) -> None:
        self.backend = backend
        self.cache = cache
        self.seed = seed
        self.max_new_tokens = max_new_tokens
        self.batch_size = batch_size
        self.status = status
        self.passes: List[Dict[str, Any]] = []
        self._model = backend.cache_id

    def outputs(self, prompt: str, items: Sequence[Dict[str, Any]], split: str,
                env: EnvSpec, tag: str) -> List[str]:
        pid = schema.prompt_id(prompt)
        keys = [generation_key(self.backend.synthetic, self._model, prompt, item["id"], env.decoding,
                               self.seed, tag, self.max_new_tokens) for item in items]
        missing = [i for i, k in enumerate(keys) if self.cache.get(k) is None]
        if tag == "rerun":
            # A rerun is a separate pass: shuffle the batch order so it is not a replay of the
            # stored run's batches.
            random.Random(f"{self.seed}-{pid}").shuffle(missing)
        missing_set = set(missing)
        cached = [i for i in range(len(items)) if i not in missing_set]
        pass_id = None
        if missing:
            pass_id = f"s{self.seed}-{pid}-{env.decoding}-{tag}-{split}-{len(self.passes)}"
            for start in range(0, len(missing), self.batch_size):
                batch = missing[start:start + self.batch_size]
                conversations = [[{"role": "system", "content": prompt},
                                  {"role": "user", "content": items[i]["question"]}] for i in batch]
                seeds = [item_seed(self.seed, tag, items[i]["id"]) for i in batch]
                texts = self.backend.chat(conversations, env.temperature, seeds, self.max_new_tokens)
                # Saved batch by batch, so an interrupted run loses at most one batch.
                self.cache.put_many([(keys[i], text) for i, text in zip(batch, texts)], pass_id=pass_id)
                self.status.heartbeat(f"  generated {min(start + self.batch_size, len(missing))} of "
                                      f"{len(missing)} outputs ({split} items, {env.decoding}, {tag})")
        self.passes.append({
            "id": pass_id, "prompt": pid, "env": env.id, "tag": tag, "split": split,
            "batch_size": self.batch_size,
            # Positions in the split, in the order sent; consecutive chunks of batch_size
            # are the batches.
            "order": missing,
            "cached": "all" if len(cached) == len(items) else cached,
            "cached_from": sorted({self.cache.origin.get(keys[i], "unknown") for i in cached}),
        })
        return [self.cache.data[k] for k in keys]

    def propose(self, incumbent: str, failures: List[Dict[str, Any]], round_idx: int,
                system: str, temperature: float, format_line: str) -> Tuple[str, str]:
        if not failures:
            return incumbent, "no_failures"
        k = key("proposer", self.backend.synthetic, self._model, incumbent, json.dumps(failures),
                self.seed, round_idx)
        text = self.cache.get(k)
        if text is None:
            text = self.backend.chat([proposer_messages(incumbent, failures, system)], temperature,
                                     [item_seed(self.seed, "proposer", str(round_idx))], self.max_new_tokens)[0]
            self.cache.put_many([(k, text)], pass_id=f"s{self.seed}-proposer-{round_idx}")
        return parse_candidate(text, incumbent, format_line)


def run_loop(task: Task, backend: Backend, *, schedule: Union[str, Schedule, None] = None,
             rounds: int = 11, seed: int = 1, max_new_tokens: int = 640, batch_size: int = 64,
             cache_path: Union[str, "os.PathLike[str]", None] = None,
             initial_prompt: Optional[str] = None, format_line: Optional[str] = None,
             n_failures: int = 4, proposer_temperature: float = 0.7,
             progress: Progress = None, run_id: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the loop and return (run log, raw outputs).

    The run log is a valid v1 run. The outputs are one row per evaluation item, instruction,
    decoding and pass: {"prompt", "decoding", "pass", "item", "text"}; save them next to the
    run log with write_outputs. Generations go through the JSONL cache at cache_path, so a
    second call with the same arguments resumes instead of starting over.

    initial_prompt and format_line default to the paper's wording for numeric answers and to
    an answer-only instruction for text answers; pass format_line="" to leave candidates as
    the proposer wrote them. Without a schedule the loop uses default_schedule(rounds), which
    is DEFAULT_SCHEDULE at 11 rounds.
    """
    if schedule is None:
        schedule = default_schedule(rounds)
    sched = parse_schedule(schedule) if isinstance(schedule, str) else schedule
    _check_arguments(task, sched, rounds, batch_size, max_new_tokens)
    numeric = task.gold == "number"
    if initial_prompt is None:
        initial_prompt = INITIAL_PROMPT if numeric else TEXT_INITIAL_PROMPT
    if format_line is None:
        format_line = FORMAT_LINE if numeric else TEXT_FORMAT_LINE
    proposer_system = task.proposer_system or PROPOSER_SYSTEM

    status = _Status(progress)
    runner = _Runner(backend, Cache(cache_path), seed, max_new_tokens, batch_size, status)
    calls_before = backend.physical_calls
    specs = sched.environments
    scorers: Dict[str, Scorer] = {env_id: get_scorer(spec.scorer) for env_id, spec in specs.items()}
    dev, ev = task.dev, task.eval
    dev_gold, ev_gold = [item["gold"] for item in dev], [item["gold"] for item in ev]
    status.say(f"{task.name}: {len(dev)} development and {len(ev)} evaluation items, {rounds} rounds, "
               f"seed {seed}, {backend.name} backend ({backend.describe()['model']}), schedule {sched.spec}")
    for start in sched.starts:
        if start >= rounds:
            # Allowed, as in the paper's scripts: the environment is still measured, it is just
            # never in force.
            status.say(f"note: the schedule's change at round {start} comes after the last round ({rounds - 1})")

    prompts: Dict[str, str] = {}
    snapshots: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    incumbent = initial_prompt
    prompts[schema.prompt_id(incumbent)] = incumbent

    for k in range(rounds):
        env = specs[env_at(k, sched.starts)]
        scorer = scorers[env.id]
        snapshots.append({"round": k, "prompt": schema.prompt_id(incumbent), "env": env.id})

        dev_out = runner.outputs(incumbent, dev, "dev", env, "current")
        dev_ok = score_outputs(dev_out, dev_gold, scorer)
        failures = pick_failures(dev, dev_out, dev_ok, k, n_failures)
        cand, note = runner.propose(incumbent, failures, k, proposer_system, proposer_temperature, format_line)
        prompts[schema.prompt_id(cand)] = cand

        c_ok = score_outputs(runner.outputs(cand, ev, "eval", env, "current"), ev_gold, scorer)
        i_ok = score_outputs(runner.outputs(incumbent, ev, "eval", env, "current"), ev_gold, scorer)
        wins = sum(1 for c, i in zip(c_ok, i_ok) if c and not i)
        losses = sum(1 for c, i in zip(c_ok, i_ok) if i and not c)
        # Strictly more wins than losses. A tie means the candidate is not measurably better
        # than the incumbent, so it is not promoted.
        accepted = wins > losses
        candidates.append({
            "id": f"C{k + 1}", "round": k, "prompt": schema.prompt_id(cand),
            "parent": schema.prompt_id(incumbent), "env": env.id, "note": note,
            "wins": wins, "losses": losses, "accepted": accepted, "dev_acc": sum(dev_ok) / len(dev_ok),
            # What this loop's own gate compared against: the incumbent, scored in the same pass.
            "reference": {"prompt": schema.prompt_id(incumbent), "env": env.id, "pass": "current"},
        })
        status.say(f"round {k}  {env.id} {env.name}: candidate {100 * sum(c_ok) / len(ev):.1f}%, incumbent "
                   f"{100 * sum(i_ok) / len(ev):.1f}%, wins {wins}, losses {losses}, "
                   f"{'accepted' if accepted else 'rejected'} ({note})")
        if accepted:
            incumbent = cand

    status.say(f"measuring {len(prompts)} instructions under {len(specs)} environments, stored pass and rerun")
    labels: Dict[str, Dict[str, Dict[str, str]]] = {}
    texts_by_pass: Dict[Tuple[str, str, str], List[str]] = {}
    for pid, text in prompts.items():
        labels[pid] = {}
        for env_id, env in specs.items():
            labels[pid][env_id] = {}
            for tag in PASSES:
                texts = runner.outputs(text, ev, "eval", env, tag)
                texts_by_pass.setdefault((pid, env.decoding, tag), texts)
                labels[pid][env_id][tag] = schema.encode_labels(score_outputs(texts, ev_gold, scorers[env_id]))

    # Fingerprints are built after generation: part of what identifies the model, such as an
    # endpoint's system_fingerprint, is only known once it has answered.
    envs = build_environments(sched, backend)
    info = dict(backend.describe())
    model_id = str(info.pop("model"))
    model = {"id": model_id, **{name: value for name, value in info.items() if value is not None}}
    meta: Dict[str, Any] = {
        "config": {
            "rounds": rounds, "schedule": sched.spec, "max_new_tokens": max_new_tokens,
            "batch_size": batch_size, "rerun_order": "shuffled",
            "proposer_temperature": proposer_temperature, "n_failures": n_failures,
            "format_line": format_line, "passes": runner.passes,
        },
        "physical_calls": backend.physical_calls - calls_before,
        # Gold answers of the evaluation items, so that `driftaudit rescore` can grade the
        # saved outputs again without the task file.
        "gold": ev_gold,
    }
    if not backend.synthetic:
        meta["software"] = dict({"python": platform.python_version()}, **backend.versions())
    run = schema.new_run(
        id=run_id or default_run_id(task.name, model_id, seed), seed=seed, task=task.describe(),
        model=model, environments=envs, schedule=sched.starts,
        source="synthetic" if backend.synthetic else "measured",
        cost={"n_dev": len(dev), "proposal_calls": 1}, meta=meta)
    if backend.synthetic:
        # A simulated run is fully determined by its arguments. Without the timestamp the
        # same arguments give the same file, byte for byte.
        run.pop("created", None)
    run.update(prompts=prompts, snapshots=snapshots, candidates=candidates, labels=labels)
    outputs = [{"prompt": pid, "decoding": decoding, "pass": tag, "item": i, "text": text}
               for (pid, decoding, tag), texts in texts_by_pass.items() for i, text in enumerate(texts)]
    return schema.load(run), outputs


def _check_arguments(task: Task, sched: Schedule, rounds: int, batch_size: int, max_new_tokens: int) -> None:
    if rounds < 1 or batch_size < 1 or max_new_tokens < 1:
        raise DriftAuditError("rounds, batch size and max new tokens must all be at least 1.")
    if not task.dev or not task.eval:
        raise DriftAuditError("The task needs at least one development item and one evaluation item.")
    used = {spec.scorer for spec in sched.environments.values()}
    if task.gold == "text" and used & set(_NUMERIC_SCORERS):
        raise DriftAuditError(
            "The task has text answers, which the strict and lenient scorers cannot grade. "
            "Use exact or exact-normalized in the schedule, for example 0:greedy/exact.")
    if task.gold == "number" and used & set(_TEXT_SCORERS):
        raise DriftAuditError(
            "The task was loaded with numeric answers, but the schedule uses an exact-match scorer. "
            "Load it with gold='text', or use the strict and lenient scorers.")


def gold_kind(schedule: Schedule) -> str:
    """How a task must be loaded for this schedule: "number", "text" or "auto"."""
    used = {spec.scorer for spec in schedule.environments.values()}
    if used & set(_NUMERIC_SCORERS) and used & set(_TEXT_SCORERS):
        raise DriftAuditError("A schedule cannot mix numeric scorers (strict, lenient) with exact-match "
                              "scorers (exact, exact-normalized): they read different kinds of answers.")
    if used <= set(_NUMERIC_SCORERS):
        return "number"
    return "text" if used <= set(_TEXT_SCORERS) else "auto"


def default_run_id(task_name: str, model_id: str, seed: int) -> str:
    def slug(text: str) -> str:
        return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")
    return "-".join(part for part in (slug(task_name), slug(model_id.split("/")[-1]), f"seed{seed}") if part)


def write_outputs(path: Union[str, "os.PathLike[str]"], outputs: Sequence[Dict[str, Any]]) -> Path:
    """Save raw outputs as JSON lines; gzip when the name ends in .gz.

    The gzip header carries no timestamp and no file name, so equal outputs give equal bytes.
    """
    data = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in outputs).encode("utf-8")
    if str(path).endswith(".gz"):
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
            gz.write(data)
        data = buffer.getvalue()
    return write_atomic(path, data)


def read_outputs(path: Union[str, "os.PathLike[str]"]) -> Dict[Tuple[str, str, str], List[str]]:
    """Raw outputs keyed by (prompt id, decoding, pass), each a list of texts in item order."""
    too_big = DriftAuditError(f"{path} holds more than {MAX_OUTPUTS_BYTES // 2 ** 20:,} MB of outputs once "
                              "decompressed, which is more than any run writes, so it is not read.")
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_OUTPUTS_BYTES + 1)
        if len(data) > MAX_OUTPUTS_BYTES:
            raise too_big
        if data[:2] == b"\x1f\x8b":
            # Read through the stream with a cap: a small gzip file can expand to gigabytes.
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                data = gz.read(MAX_OUTPUTS_BYTES + 1)
        if len(data) > MAX_OUTPUTS_BYTES:
            raise too_big
        rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
        by_item: Dict[Tuple[str, str, str], Dict[int, str]] = {}
        for row in rows:
            by_item.setdefault((row["prompt"], row["decoding"], row["pass"]), {})[int(row["item"])] = row["text"]
    except FileNotFoundError:
        raise DriftAuditError(f"{path}: no such file") from None
    except (OSError, EOFError, zlib.error, ValueError, KeyError, TypeError) as exc:
        raise DriftAuditError(
            f"{path} is not an outputs file: each line must be an object with prompt, decoding, "
            f"pass, item and text ({type(exc).__name__}).") from None
    texts: Dict[Tuple[str, str, str], List[str]] = {}
    for group, items in by_item.items():
        if sorted(items) != list(range(len(items))):
            raise DriftAuditError(f"{path}: the outputs for prompt {group[0]}, {group[1]}, {group[2]} "
                                  "do not cover items 0 to n-1 exactly once.")
        texts[group] = [items[i] for i in range(len(items))]
    return texts
