"""Runs one seed of the experiment and saves everything the tables need.

Step 1 (trajectory): a prompt-level self-improvement loop over config.ROUNDS rounds.
    Each round k: snapshot the incumbent, show the proposer some dev errors, get a
    candidate, score candidate and incumbent on the eval items under the environment
    in force at round k, accept if the candidate has more wins than losses.
    This builds the candidate pool and the reference snapshots.

Step 2 (measurement): every prompt that appeared is scored under every environment
    E1-E4, with two independent generations for sampling environments:
      "current" = the record made when it was evaluated (what gets stored)
      "rerun"   = a fresh regeneration later (what a refresh would produce)
    The rerun is always generated again, including under greedy decoding. By default its
    items are sent to the model in a different (seeded, shuffled) batch order from the stored
    run; DRIFT_RERUN_ORDER=stored keeps the stored order instead.

Every generation pass is logged in the run file under config["passes"]: which prompt,
environment, tag and split, the batch size, and the exact order the items were sent in
(item indices; consecutive chunks of batch_size form the batches). Items served from the
cache are listed separately with the id of the pass that generated them, which may be in
another seed's run file (greedy "current" outputs are shared across seeds). E3 reuses E1's
text and E4 reuses E2's (same decoding), so their passes show up as fully cached.

Tables are computed from the saved run with no extra model calls.
"""
import hashlib
import json
import logging
import os
import platform
import random

from . import config
from .data import dataset_revision, load_items, model_revision
from .envs import ENVS, env_at
from .extract import EXTRACTORS, is_correct
from .model import Cache, generation_key, item_seed, make_generator
from .propose import parse_candidate, pick_failures, proposer_messages

log = logging.getLogger("drift")
TAGS = ("current", "rerun")


def phash(text):
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class Runner:
    def __init__(self, seed, gen=None, cache=None):
        self.seed = seed
        self.gen = gen
        self.cache = cache or Cache()
        self.passes = []

    def _gen(self):
        if self.gen is None:
            log.info("Loading model %s with backend %s", config.MODEL_ID, config.BACKEND)
            self.gen = make_generator()
        return self.gen

    def outputs(self, prompt, items, env, tag):
        keys = [generation_key(prompt, it["id"], env, self.seed, tag) for it in items]
        missing = [i for i, k in enumerate(keys) if self.cache.get(k) is None]
        if tag == "rerun" and config.RERUN_ORDER == "shuffled":
            # A rerun is a separate pass: shuffle the batch order so it is not a replay of
            # the stored run's batches. With RERUN_ORDER="stored" it keeps dataset order,
            # the same order and batch size as the stored pass.
            random.Random(f"{self.seed}-{phash(prompt)}").shuffle(missing)
        split = items[0]["id"].rsplit("-", 1)[0] if items else ""
        missing_set = set(missing)
        cached = [i for i in range(len(items)) if i not in missing_set]
        pass_id = None
        if missing:
            pass_id = f"s{self.seed}-{phash(prompt)}-{env.decoding_key}-{tag}-{split}-{len(self.passes)}"
            convs = [[{"role": "system", "content": prompt},
                      {"role": "user", "content": items[i]["question"]}] for i in missing]
            seeds = [item_seed(self.seed, tag, items[i]["id"]) for i in missing]
            texts = self._gen().chat(convs, env.temperature, seeds)
            self.cache.put_many([(keys[i], t) for i, t in zip(missing, texts)], pass_id=pass_id)
        self.passes.append({
            "id": pass_id, "prompt": phash(prompt), "env": env.env_id, "tag": tag,
            "split": split, "batch_size": config.BATCH_SIZE,
            "order": [int(items[i]["id"].rsplit("-", 1)[1]) for i in missing],
            # "all" when every item came from the cache, else the indices that did
            "cached": "all" if len(cached) == len(items) else [int(items[i]["id"].rsplit("-", 1)[1]) for i in cached],
            "cached_from": sorted({self.cache.origin.get(keys[i], "unknown") for i in cached}),
        })
        return [self.cache.get(k) for k in keys]

    @staticmethod
    def score(texts, items, extractor):
        fn = EXTRACTORS[extractor]
        return [int(is_correct(fn(t), it["gold"])) for t, it in zip(texts, items)]

    def propose(self, incumbent, failures, round_idx):
        if not failures:
            return incumbent, "no_failures"
        key = ("proposer", config.BACKEND == "mock", config.MODEL_ID, incumbent, json.dumps(failures), self.seed, round_idx)
        k = hashlib.sha1(json.dumps(key).encode()).hexdigest()
        text = self.cache.get(k)
        if text is None:
            text = self._gen().chat([proposer_messages(incumbent, failures)],
                                    config.PROPOSER_TEMPERATURE,
                                    [item_seed(self.seed, "proposer", str(round_idx))])[0]
            self.cache.put_many([(k, text)], pass_id=f"s{self.seed}-proposer-{round_idx}")
        return parse_candidate(text, incumbent)

    def run(self):
        dev = load_items("train", config.N_DEV)
        ev = load_items("test", config.N_EVAL)
        prompts = {}
        snapshots, candidates = [], []
        incumbent = config.INITIAL_PROMPT
        prompts[phash(incumbent)] = incumbent

        for k in range(config.ROUNDS):
            env = ENVS[env_at(k, config.ENV_SCHEDULE)]
            snapshots.append({"round": k, "prompt": phash(incumbent), "env": env.env_id})

            dev_out = self.outputs(incumbent, dev, env, "current")
            dev_ok = self.score(dev_out, dev, env.extractor)
            failures = pick_failures(dev, dev_out, dev_ok, k)
            cand, note = self.propose(incumbent, failures, k)
            prompts[phash(cand)] = cand

            c_ok = self.score(self.outputs(cand, ev, env, "current"), ev, env.extractor)
            i_ok = self.score(self.outputs(incumbent, ev, env, "current"), ev, env.extractor)
            wins = sum(c and not i for c, i in zip(c_ok, i_ok))
            losses = sum(i and not c for c, i in zip(c_ok, i_ok))
            # Strictly more wins than losses. A tie means the candidate is not measurably better
            # than the incumbent, so it is not promoted (with >=, tied candidates would be
            # accepted and, by definition, counted as false accepts).
            accepted = wins > losses
            candidates.append({"id": f"C{k + 1}", "round": k, "prompt": phash(cand),
                               "parent": phash(incumbent), "env": env.env_id, "note": note,
                               "wins": wins, "losses": losses, "accepted": accepted,
                               "dev_acc": sum(dev_ok) / len(dev_ok)})
            log.info("seed %d round %d env %s: cand acc %.3f vs inc %.3f (W%d/L%d) -> %s [%s]",
                     self.seed, k, env.env_id, sum(c_ok) / len(ev), sum(i_ok) / len(ev),
                     wins, losses, "ACCEPT" if accepted else "reject", note)
            if accepted:
                incumbent = cand

        log.info("Measurement step: %d unique prompts x 4 environments", len(prompts))
        correct = {}
        for h, text in prompts.items():
            correct[h] = {}
            for env_id, env in ENVS.items():
                correct[h][env_id] = {tag: self.score(self.outputs(text, ev, env, tag), ev, env.extractor)
                                      for tag in TAGS}

        return {
            "seed": self.seed,
            "config": {
                "model": config.MODEL_ID, "model_revision": model_revision(),
                "dataset": f"{config.DATASET_ID} ({config.DATASET_CONFIG})",
                "dataset_revision": dataset_revision(),
                "n_dev": len(dev), "n_eval": len(ev), "rounds": config.ROUNDS,
                "schedule": {str(r): e for r, e in config.ENV_SCHEDULE.items()},
                "sample_temperature": config.SAMPLE_TEMPERATURE,
                "proposer_temperature": config.PROPOSER_TEMPERATURE,
                "max_new_tokens": config.MAX_NEW_TOKENS, "backend": config.BACKEND,
                "batch_size": config.BATCH_SIZE, "rerun_order": config.RERUN_ORDER,
                "passes": self.passes,
                "stored_scoring": config.STORED_SCORING, "frozen_mode": config.FROZEN_MODE,
                "python": platform.python_version(), "packages": package_versions(),
            },
            "prompts": prompts,
            "snapshots": snapshots,
            "candidates": candidates,
            "correct": correct,
            "physical_calls": self.gen.physical_calls if self.gen else 0,
        }


def package_versions():
    out = {}
    for name in ("torch", "transformers", "datasets", "vllm", "huggingface_hub"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", "?")
        except Exception:
            out[name] = "not installed"
    return out


def run_path(seed):
    model = config.MODEL_ID.split("/")[-1]
    tag = f"{config.BACKEND}_{model}_n{config.N_EVAL}_r{config.ROUNDS}"
    return os.path.join(config.RUNS_DIR, f"run_seed{seed}_{tag}.json")


def get_run(seed, gen=None, cache=None):
    """Load a saved run for this seed, or execute it (resuming from the cache) and save it."""
    path = run_path(seed)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    run = Runner(seed, gen, cache).run()
    os.makedirs(config.RUNS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(run, f)
    log.info("Saved %s", os.path.relpath(path, config.ROOT))
    return run


_shared = {}


def get_runs(seeds=None):
    """All seeds, sharing one model and one cache so the model loads once."""
    seeds = seeds or config.SEEDS
    runs = []
    for s in seeds:
        if not os.path.exists(run_path(s)):
            if "cache" not in _shared:
                _shared["cache"] = Cache()
            r = Runner(s, _shared.get("gen"), _shared["cache"])
            run = r.run()
            _shared["gen"] = r.gen
            os.makedirs(config.RUNS_DIR, exist_ok=True)
            with open(run_path(s), "w") as f:
                json.dump(run, f)
            log.info("Saved %s", os.path.relpath(run_path(s), config.ROOT))
        runs.append(get_run(s))
    return runs

