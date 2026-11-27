"""Golden results both engines are tested against.

    python -m driftaudit._golden            write tests/golden/
    python -m driftaudit._golden --check    exit 1 if a file on disk is not what the engine produces now

tests/golden/manifest.json lists every case: which run (or runs), which options, and the file
holding the audit or study result. The JavaScript engine replays the manifest and must match
each result to 1e-9; pytest runs the check, so a change to the Python engine that moves a
number fails until the goldens are regenerated on purpose.

The cases are the five paper runs (read from the toolkit's own run files), the paper study,
option variants on seeds 1 and 5, and three small synthetic runs that reach what the paper
runs do not: other sizes and schedules, six environments, a sparse label bank and recorded
references. The synthetic labels come from sha1 digests, so the files are identical on every
platform and Python version. They are tagged synthetic and measure nothing.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from . import engine, schema
from .envs import Environment, env_at
from .errors import DriftAuditError

log = logging.getLogger("driftaudit.golden")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN = os.path.join(ROOT, "tests", "golden")
PAPER_SEEDS = (1, 2, 3, 4, 5)
PAPER_RUN = "../../toolkit/runs/run_seed{seed}_hf_Qwen2.5-1.5B-Instruct_n200_r11.json"

# Option variants replayed on seeds 1 and 5 (seed 5 is the example seed of the paper's Figure 2).
VARIANTS = {
    "no-decoding-change": {"schedule": {"0": "E1", "4": "E1", "8": "E3"}},
    "no-extraction-change": {"schedule": {"0": "E1", "4": "E2", "8": "E2"}},
    "fixed-age-1": {"fixed_age": 1},
    "rescore": {"stored_scoring": "rescore"},
    "margin-2": {"margin": 2},
    "periodic-2": {"periodic_k": 2},
}

# id -> (name, temperature, scorer). Declared out of alphabetical order on purpose: results
# must not depend on the order of the environments object.
_ENVIRONMENTS = {
    "base": ("Baseline", 0.0, "strict"),
    "warm-lenient": ("Sampling, lenient scorer", 0.7, "lenient"),
    "base-lenient": ("Lenient scorer", 0.0, "lenient"),
    "warm": ("Sampling", 0.7, "strict"),
    "base-exact": ("Exact scorer", 0.0, "exact"),
    "warm-exact": ("Sampling, exact scorer", 0.7, "exact"),
}

# gate is the rule the pretend loop used, which decides what it recorded as its reference:
#   incumbent  the incumbent scored in the same pass as the candidate (the paper's loop)
#   frozen     the round-0 outputs, except that the loop reran its incumbent in the round an
#              environment change took effect
#   anchor     a baseline prompt whose labels were not kept, only the win and loss counts
# drop removes labels after the trajectory is fixed, as (prompt index, environment, pass).
_SYNTHETIC = {
    "synthetic-a": {"seed": 11, "n_items": 40, "rounds": 5, "n_dev": 12, "gate": "incumbent",
                    "environments": ("base", "warm-lenient"), "schedule": {0: "base", 3: "warm-lenient"}},
    "synthetic-b": {"seed": 12, "n_items": 64, "rounds": 8, "n_dev": 20, "gate": "frozen",
                    "environments": tuple(_ENVIRONMENTS),
                    "schedule": {0: "base", 3: "warm-lenient", 6: "base-exact"}},
    "synthetic-c": {"seed": 13, "n_items": 25, "rounds": 3, "n_dev": 0, "gate": "anchor",
                    "environments": ("base", "base-lenient"), "schedule": {0: "base", 2: "base-lenient"},
                    "drop": [(0, "base-lenient", "rerun"), (1, "base-lenient", "rerun"), (2, "base-lenient", "rerun"),
                             (3, "base-lenient", "rerun"), (3, "base", "rerun")]},
}


def _draw(key: str, per_mille: int) -> int:
    """1 with probability per_mille/1000, read off a sha1 digest so every platform draws the same."""
    return 1 if int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 1000 < per_mille else 0


def _skill(run_id: str, prompt: int) -> int:
    """Per-mille chance that a prompt solves an item. Later prompts tend to be better, so some get accepted."""
    return 430 + 35 * prompt + int(hashlib.sha1(f"{run_id}/{prompt}/skill".encode()).hexdigest()[:6], 16) % 160


def _labels(run_id: str, prompt: Any, skill: int, env_id: str, tag: str, n_items: int) -> str:
    """Labels of one pass. Environments with the same decoding grade the same pretend text.

    Greedy reruns nearly repeat the stored pass and sampled passes vary more, as in the
    measured runs. The lenient scorer reads every right answer, the strict one only those in
    plain format, and the exact one disagrees with strict on a few items in both directions.
    """
    _, temperature, scorer = _ENVIRONMENTS[env_id]
    decoding = "greedy" if temperature == 0 else "sample"
    out = []
    for item in range(n_items):
        where = f"{run_id}/{prompt}/{item}"
        right = _draw(f"{where}/solve", skill)
        if decoding == "sample":
            right ^= _draw(f"{where}/sample/{tag}", 110)
        elif tag == "rerun":
            right ^= _draw(f"{where}/greedy/rerun", 30)
        if scorer != "lenient":
            right &= _draw(f"{where}/{decoding}/plain", 820)
        if scorer == "exact":
            right ^= _draw(f"{where}/{decoding}/quirk", 60)
        out.append(str(right))
    return "".join(out)


def _wins_losses(cand: str, ref: str) -> Tuple[int, int]:
    wins, losses, _, _ = engine.pair(cand, ref)
    return wins, losses


def synthetic_run(run_id: str) -> Dict[str, Any]:
    """One of the synthetic runs as a v1 run log."""
    spec = _SYNTHETIC[run_id]
    n_items, rounds, schedule = spec["n_items"], spec["rounds"], spec["schedule"]
    environments = [Environment.make(id=env_id, name=_ENVIRONMENTS[env_id][0], model="synthetic",
                                     temperature=_ENVIRONMENTS[env_id][1], scorer=_ENVIRONMENTS[env_id][2],
                                     scorer_version="1")
                    for env_id in spec["environments"]]
    run = schema.new_run(id=run_id, seed=spec["seed"], source="synthetic",
                         task={"name": "synthetic", "n_items": n_items, "n_dev": spec["n_dev"]},
                         model={"id": "synthetic", "backend": "sha1"}, environments=environments,
                         schedule=schedule, cost={"n_dev": spec["n_dev"], "proposal_calls": 1},
                         meta={"note": "Labels drawn from sha1 digests by driftaudit._golden. Not a measurement."})
    run["created"] = "2026-11-27T00:00:00Z"

    texts = [f"Synthetic prompt {i} of {run_id}. Give the final answer as a number." for i in range(rounds + 1)]
    ids = [schema.prompt_id(text) for text in texts]
    bank = {i: {env_id: {tag: _labels(run_id, i, _skill(run_id, i), env_id, tag, n_items) for tag in schema.PASSES}
                for env_id in spec["environments"]}
            for i in range(rounds + 1)}

    first_env = env_at(0, schedule)
    anchor_text = f"Baseline prompt measured before {run_id} started."
    anchor = _labels(run_id, "anchor", 400, first_env, "current", n_items)
    incumbent = 0
    for k in range(rounds):
        env_id = env_at(k, schedule)
        cand = k + 1
        run["snapshots"].append({"round": k, "prompt": ids[incumbent], "env": env_id})
        if spec["gate"] == "anchor":
            reference = {"prompt": schema.prompt_id(anchor_text), "env": first_env, "pass": "current"}
            ref_labels = anchor
        elif spec["gate"] == "frozen" and k > 0 and k in schedule:
            reference = {"prompt": ids[incumbent], "env": env_id, "pass": "rerun"}
            ref_labels = bank[incumbent][env_id]["rerun"]
        elif spec["gate"] == "frozen":
            reference = {"prompt": ids[0], "env": first_env, "pass": "current"}
            ref_labels = bank[0][first_env]["current"]
        else:
            reference = {"prompt": ids[incumbent], "env": env_id, "pass": "current"}
            ref_labels = bank[incumbent][env_id]["current"]
        wins, losses = _wins_losses(bank[cand][env_id]["current"], ref_labels)
        run["candidates"].append({"id": f"C{cand}", "round": k, "prompt": ids[cand], "parent": ids[incumbent],
                                  "env": env_id, "note": "synthetic", "wins": wins, "losses": losses,
                                  "accepted": wins > losses, "reference": reference})
        if wins > losses:
            incumbent = cand

    for i, text in enumerate(texts):
        run["prompts"][ids[i]] = text
        run["labels"][ids[i]] = bank[i]
    if spec["gate"] == "anchor":
        run["prompts"][schema.prompt_id(anchor_text)] = anchor_text
    for i, env_id, tag in spec.get("drop", ()):
        del run["labels"][ids[i]][env_id][tag]
    return schema.load(run)


def _cases() -> List[Dict[str, Any]]:
    """The manifest: every case with its inputs, options and result file."""
    cases = []
    for seed in PAPER_SEEDS:
        cases.append({"name": f"paper-seed{seed}", "kind": "audit", "run": PAPER_RUN.format(seed=seed),
                      "options": {}, "result": f"audit-paper-seed{seed}.json"})
    cases.append({"name": "paper-study", "kind": "study", "runs": [PAPER_RUN.format(seed=s) for s in PAPER_SEEDS],
                  "options": {}, "result": "study-paper.json"})
    for seed in (1, 5):
        for variant, options in VARIANTS.items():
            cases.append({"name": f"paper-seed{seed}-{variant}", "kind": "audit", "run": PAPER_RUN.format(seed=seed),
                          "options": options, "result": f"audit-paper-seed{seed}-{variant}.json"})
    cases.append({"name": "paper-study-rescore", "kind": "study",
                  "runs": [PAPER_RUN.format(seed=s) for s in PAPER_SEEDS],
                  "options": {"stored_scoring": "rescore", "probe_age": 1, "ages": [0, 2, 4]},
                  "result": "study-paper-rescore.json"})

    for run_id in _SYNTHETIC:
        cases.append({"name": run_id, "kind": "audit", "run": f"runs/{run_id}.json", "options": {},
                      "result": f"audit-{run_id}.json"})
    synthetic_variants = [
        # No environment of synthetic-a has the stored decoding with the new scorer: the fallback note.
        ("synthetic-a", "rescore", {"stored_scoring": "rescore"}),
        ("synthetic-a", "margin-1", {"margin": 1, "policies": ["frozen", "env_triggered", "as_run"]}),
        ("synthetic-b", "rescore", {"stored_scoring": "rescore"}),
        ("synthetic-b", "what-if", {"schedule": {"0": "warm", "2": "base-lenient", "5": "warm-exact"},
                                    "periodic_k": 2, "margin": 1}),
        ("synthetic-b", "fixed-age-2", {"fixed_age": 2, "policies": ["frozen", "per_batch"]}),
        ("synthetic-c", "periodic-1", {"periodic_k": 1}),
        ("synthetic-c", "rescore", {"stored_scoring": "rescore"}),
    ]
    for run_id, variant, options in synthetic_variants:
        cases.append({"name": f"{run_id}-{variant}", "kind": "audit", "run": f"runs/{run_id}.json",
                      "options": options, "result": f"audit-{run_id}-{variant}.json"})
    studies = [
        ("synthetic-study-a-b", ["synthetic-a", "synthetic-b"], {}),
        # One run is sparse and three rounds long: fewer policies pool and some cells have no value.
        ("synthetic-study-b-c", ["synthetic-b", "synthetic-c"], {}),
        ("synthetic-study-all", ["synthetic-a", "synthetic-b", "synthetic-c"],
         {"probe_age": 1, "ages": [0, 1, 2, 4, 7], "margin": 1, "periodic_k": 2}),
    ]
    for name, run_ids, options in studies:
        cases.append({"name": name, "kind": "study", "runs": [f"runs/{r}.json" for r in run_ids],
                      "options": options, "result": name.replace("synthetic-study", "study-synthetic") + ".json"})
    return cases


def dumps(obj: Any) -> str:
    """The one serialisation of every golden file: sorted keys, indent 1, floats as Python's repr."""
    return json.dumps(obj, sort_keys=True, indent=1, allow_nan=False) + "\n"


def build(golden: str = GOLDEN) -> Dict[str, str]:
    """Every golden file as {path relative to the golden directory: text}.

    golden is where the manifest's run paths are resolved from. The default is tests/golden
    of the checkout this module was imported from; an installed wheel has no such directory
    and must be pointed at one.
    """
    if not os.path.isdir(golden):
        raise DriftAuditError(f"{golden} does not exist: the goldens live in tests/golden of a source checkout. "
                              "Run from one (pip install -e .) or pass --dir")
    files = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for run_id in _SYNTHETIC:
        run = synthetic_run(run_id)
        loaded[f"runs/{run_id}.json"] = run
        files[f"runs/{run_id}.json"] = dumps(run)

    def run_of(rel):
        if rel not in loaded:
            loaded[rel] = schema.load(os.path.normpath(os.path.join(golden, rel)))
        return loaded[rel]

    cases = _cases()
    for case in cases:
        if case["kind"] == "audit":
            result = engine.audit(run_of(case["run"]), **case["options"])
        else:
            result = engine.study([run_of(rel) for rel in case["runs"]], **case["options"])
        files[case["result"]] = dumps(result)
    files["manifest.json"] = dumps(cases)
    return files


def _owned(golden: str) -> List[str]:
    """Files in the golden directory that this module writes (scorer_cases.json is built elsewhere)."""
    found = [os.path.join(golden, "manifest.json")]
    for pattern in ("audit-*.json", "study-*.json", os.path.join("runs", "synthetic-*.json")):
        found.extend(glob.glob(os.path.join(golden, pattern)))
    return sorted(os.path.relpath(path, golden).replace(os.sep, "/") for path in found if os.path.exists(path))


def check(golden: str = GOLDEN) -> List[str]:
    """Problems with the goldens on disk, one line each; empty when they are current."""
    files = build(golden)
    problems = []
    for rel, text in sorted(files.items()):
        path = os.path.join(golden, rel)
        if not os.path.exists(path):
            problems.append(f"{rel}: missing")
            continue
        with open(path, encoding="utf-8") as f:
            if f.read() != text:
                problems.append(f"{rel}: differs from what the engine produces now")
    problems.extend(f"{rel}: not in the manifest any more" for rel in _owned(golden) if rel not in files)
    return problems


def write(golden: str = GOLDEN) -> List[str]:
    """Write every golden file, remove the ones no case produces any more, and return what changed."""
    files = build(golden)
    changed = []
    os.makedirs(os.path.join(golden, "runs"), exist_ok=True)
    for rel in _owned(golden):
        if rel not in files:
            os.unlink(os.path.join(golden, rel))
            changed.append(rel)
    for rel, text in sorted(files.items()):
        path = os.path.join(golden, rel)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    continue
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        changed.append(rel)
    return changed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m driftaudit._golden", description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="verify the files on disk instead of writing them")
    parser.add_argument("--dir", default=GOLDEN, help="golden directory (default: tests/golden of this checkout)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.check:
            problems = check(args.dir)
            for problem in problems:
                log.error("%s", problem)
            if problems:
                log.error("Goldens are stale. If the change is intended, run: python -m driftaudit._golden")
                return 1
            log.info("Goldens are current.")
            return 0
        changed = write(args.dir)
        log.info("Wrote %d golden file(s) under %s", len(changed), args.dir)
    except DriftAuditError as err:
        log.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
