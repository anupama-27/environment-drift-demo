"""Regenerate the greedy "rerun" outputs (E1 and E3) for runs that were saved before the
rerun fix, without touching anything else in the run.

Before the fix, a greedy rerun reused the cached stored output, so stored and rerun were
identical by construction. This script generates the rerun for real (separate pass, shuffled
batch order) and replaces only correct[prompt]["E1"]["rerun"] and correct[prompt]["E3"]["rerun"].
The old file is kept as *.cachedrerun.json.

Usage: python rerun_greedy.py 1 2 3 4 5
"""
import json
import logging
import os
import shutil
import sys

from drift import config
from drift.data import load_items
from drift.envs import ENVS
from drift.model import Cache
from drift.pipeline import Runner, run_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("drift")

seeds = [int(a) for a in sys.argv[1:]] or config.SEEDS
ev = load_items("test", config.N_EVAL)
cache, gen = Cache(), None
for s in seeds:
    path = run_path(s)
    run = json.load(open(path))
    if run.get("config", {}).get("greedy_rerun_regenerated"):
        log.info("seed %d already fixed, skipping", s)
        continue
    r = Runner(s, gen, cache)
    changed = 0
    for h, text in run["prompts"].items():
        texts = r.outputs(text, ev, ENVS["E1"], "rerun")   # E1 and E3 share this text
        for env_id in ("E1", "E3"):
            new = r.score(texts, ev, ENVS[env_id].extractor)
            changed += sum(a != b for a, b in zip(new, run["correct"][h][env_id]["current"]))
            run["correct"][h][env_id]["rerun"] = new
    gen = r.gen
    shutil.copy(path, path.replace(".json", ".cachedrerun.json"))
    run["config"]["greedy_rerun_regenerated"] = True
    run["config"]["batch_size"] = config.BATCH_SIZE
    run["config"]["rerun_order"] = config.RERUN_ORDER
    # Replace the logged E1 rerun passes with the ones generated here.
    old = [p for p in run["config"].get("passes", []) if not (p["tag"] == "rerun" and p["env"] in ("E1", "E3"))]
    run["config"]["passes"] = old + r.passes
    json.dump(run, open(path, "w"))
    log.info("seed %d: %d prompts, %d item labels differ between stored and rerun (E1+E3)",
             s, len(run["prompts"]), changed)

