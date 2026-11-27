# Run-log format (driftaudit.run/v1)

A run log is one JSON file that holds everything an audit needs and nothing that needs a model: the instructions the loop tried, the environment in force in each round, the decisions, and one correct or incorrect label per evaluation item for each instruction under each environment. The audit in Python (`driftaudit audit`) and the audit in the browser read the same file and give the same numbers.

The format is a superset of the files `toolkit/` wrote for the paper, so those load without conversion.

## Shape

~~~text
{
  "schema": "driftaudit.run/v1",
  "id": "gsm8k-qwen2.5-1.5b-seed1",
  "created": "2026-10-03T05:40:00Z",
  "tool": {"name": "driftaudit", "version": "0.1.0"},
  "source": "measured",
  "seed": 1,
  "task": {"name": "GSM8K", "n_items": 200, "n_dev": 200},
  "model": {"id": "Qwen/Qwen2.5-1.5B-Instruct", "backend": "hf"},
  "environments": {"E1": {"name": "Unchanged", "decoding": "greedy-0.0", "scorer": "strict", "fingerprint": "..."}},
  "schedule": {"0": "E1", "4": "E2", "8": "E4"},
  "prompts": {"cf7e8a98a5cc": "You are a careful math tutor. ..."},
  "snapshots": [{"round": 0, "prompt": "cf7e8a98a5cc", "env": "E1"}],
  "candidates": [{"id": "C1", "round": 0, "prompt": "de70bbb7b9b9", "parent": "cf7e8a98a5cc", "env": "E1",
                  "accepted": false, "wins": 25, "losses": 43,
                  "reference": {"prompt": "cf7e8a98a5cc", "env": "E1", "pass": "current"}}],
  "labels": {"cf7e8a98a5cc": {"E1": {"current": "1101...", "rerun": "1101..."}}},
  "cost": {"n_dev": 200, "proposal_calls": 1},
  "outputs": {"layout": "sidecar", "file": "run.outputs.jsonl.gz"},
  "meta": {}
}
~~~

`driftaudit validate` checks all of the rules below and prints every problem it finds, so the quickest way to learn the format is to write a file and validate it. Rounds are numbered from 0. Values in `[]` below are the type.

## Fields

Required fields are marked. Everything else may be left out.

`schema` (required, string): `driftaudit.run/v1`. A file with a different schema string is refused with a message that says which version it is and that a newer file needs a newer driftaudit.

`id` (required, string): the name of the run. It is what the workbench and the audit call it. `driftaudit run` builds it from the task, the model and the seed, for example `gsm8k-qwen2.5-1.5b-seed1`.

`created` (string): UTC time in ISO 8601, written by the recorder and by `driftaudit run`.

`tool` (object): `name` and `version` of the program that wrote the file.

`source` (required, string): `measured` or `synthetic`. Anything produced by the mock backend, or by anything else that is not a real model, must be `synthetic`. The command line and the workbench label synthetic runs everywhere they show them.

`seed` (integer or null): the seed of the run. The study across runs lists runs by id and seed.

`task` (required, object): `n_items` is required and is the number of evaluation items, which is the length of every label string. The rest is descriptive: `name`, `split`, `n_dev` (development items, used in call counts), `dataset`, `revision`, and `items`, the name of a bundled item file the workbench can show questions from (`gsm8k/eval200`).

`model` (object): `id`, and optionally `revision` and `backend`.

`environments` (required, object): environment id to environment. An id is any string; `E1`, `E2` and so on are conventional. Each environment has three required strings and some optional ones.

- `decoding`: `greedy-0.0` or `sample-0.2`, the temperature after the dash. Two environments with the same `decoding` share generated text and differ only in `scorer`.
- `scorer`: the id of the scorer that grades the text. The numeric scorers are `strict` and `lenient`, the text scorers are `exact` and `exact-normalized`. Files from the paper use `v1` (strict) and `v2` (lenient).
- `fingerprint`: a string built from the settings a deployment can read for itself, for example `model=Qwen/Qwen2.5-1.5B-Instruct;decode=greedy-0.0;extract=strict@1`. The environment-triggered policy refreshes its reference when the fingerprint changes, so anything that changes outputs or grades belongs in it.
- `name` and `detail` (optional): a display name, and free-form settings for display such as the temperature.

`schedule` (required, object): the round from which each environment is in force, as strings, for example `{"0": "E1", "4": "E2"}`. An entry stays in force until the next one, and a round before the first entry gets the first environment. Every environment named must exist in `environments`.

`prompts` (required, object): prompt id to the text of the instruction. The id is the first 12 hex characters of the SHA-1 of the text when `driftaudit` writes it, but any string works.

`snapshots` (required, list): one entry per round, in order: `round` (the index), `prompt` (the incumbent at the start of that round) and optionally `env`. The number of snapshots is the number of rounds.

`candidates` (required, list): one entry per proposed instruction, ordered by round.

- `id` (required): unique, for example `C1`.
- `round` (required): a round that has a snapshot.
- `prompt` (required): the candidate's id in `prompts`.
- `parent`: the incumbent it was compared with.
- `env`: the environment in force in that round.
- `accepted` (true or false): the loop's own decision.
- `wins`, `losses`: the loop's own counts against its reference.
- `note`, `dev_acc`: free-form extras.
- `reference`: what the loop's gate compared the candidate with, as `{"prompt", "env", "pass"}` where `pass` is `current` or `rerun`. Without it the `as_run` policy cannot be replayed.

`labels` (required, object): prompt id to environment id to pass to a string of `0` and `1`, one character per evaluation item, in the same item order everywhere. `current` is the pass stored when the prompt was first evaluated under that environment. `rerun` is an independent later pass. Loaders also accept an array of 0 and 1, and `save` writes the string form.

`cost` (object): `n_dev` and `proposal_calls`, which enter the model-call estimates.

`outputs` (object): where the raw model outputs are. See below.

`meta` (object): anything else. `driftaudit run` stores its configuration, the gold answers (`gold`, needed by `rescore`) and the call counts. Files upgraded from `toolkit/` keep the original configuration under `meta.config`.

## The label bank

The bank may be sparse, and an analysis reports what it is missing instead of failing. For a candidate in round k, with `env` the environment in force in that round:

- Every replayed policy needs the `current` labels of the candidate and of the incumbent under `env`, and the labels of the reference it uses. The `frozen` policy uses the round-0 incumbent under the round-0 environment, `stored_incumbent` and `periodic` the labels of the last accepted candidate.
- The `per_batch` policy needs the incumbent's `rerun` labels under `env` in every round. The `env_triggered` policy needs them in the rounds where the fingerprint changed, and `periodic` in the rounds where the reference is k rounds old.
- Drift inflation and the cause of a false accept compare the candidate with the reference's `rerun` labels under `env`. Without them the decision is still listed, with the inflation and cause left empty.
- The `as_run` policy needs `reference` on every candidate and the `current` labels of the candidate and incumbent. If the reference's labels are in the bank, wins and losses are recomputed; otherwise the recorded `wins` and `losses` are used.
- The drift probe and the reference-age analysis (the study across several runs) need, for each candidate, the incumbent from some rounds earlier stored under its own environment and rerun under the candidate's environment.
- The list of labels flipped by a scorer change needs two environments with the same `decoding` and different `scorer`, and the same prompts labeled under both.

`driftaudit validate` says whether the bank is complete (every prompt, environment and pass) or sparse, and for each policy it cannot replay, how many label vectors are missing.

## Raw outputs

Raw model outputs are never stored inside the run log. The `outputs` field points to them. Two layouts exist.

`sidecar` is what `driftaudit run` writes: one gzip file of JSON lines next to the run log. The log carries `{"layout": "sidecar", "file": "run.outputs.jsonl.gz"}`, and if the field is missing the tools look for `NAME.outputs.jsonl.gz` and `NAME.outputs.jsonl` beside the run log. Each line is one output:

~~~text
{"prompt": "cf7e8a98a5cc", "decoding": "greedy-0.0", "pass": "current", "item": 0, "text": "..."}
~~~

`chunks` is what the bundled paper runs use, because a folder of small files can be fetched by the page one at a time. `base` is a folder relative to the run log, with one folder per prompt id inside it. Each chunk is a gzip file holding a JSON array of `n_items` strings, in item order:

~~~text
<base>/<prompt>/<decoding>.<pass>.json.gz        for example s1/1398fc7a648e/greedy-0.0.rerun.json.gz
~~~

Greedy decoding gives the same text in every seed, so a `shared` map in the `outputs` field can send a chunk kind such as `greedy-0.0.current` to one folder used by all runs (`"shared": {"greedy-0.0.current": "../../outputs/paper/shared/"}`). The local server serves chunk folders only when they are inside the site, and the workbench cannot read outputs that are somewhere else.

Raw outputs let the workbench show what each scorer read and let `driftaudit rescore` grade the text again. The audit itself never needs them.

## Toolkit run files

A file written by `toolkit/` has no `schema` and carries the keys `correct`, `config`, `snapshots` and `candidates`. When it is loaded, in Python or in the browser, it is upgraded in memory:

- `correct` becomes `labels`, with each label list turned into a string.
- `config.schedule` becomes `schedule`, and `config.n_eval` becomes `task.n_items`.
- The paper's four environments are filled in: E1 unchanged (greedy, strict extractor), E2 decoding (sampling at 0.2, strict), E3 extraction (greedy, lenient), E4 combined (sampling at 0.2, lenient), with fingerprints in the form the toolkit used.
- Each candidate gets a `reference`: its parent, under its own environment, `current` pass. That is the comparison the toolkit's gate made.
- The id becomes `gsm8k-qwen2.5-1.5b-seed<N>`. A run made with the mock backend gets a different id, so it cannot pass for a measured run.
- The whole configuration is kept under `meta.config`.

The input file is not changed. `driftaudit convert LEGACY.json -o RUN.json` writes the upgraded file.

## A minimal example

This file has two prompts, two environments (the scorer changes in round 1), four items and two rounds. It is a valid run log, and its label bank is sparse: it has no reruns for the first environment, so the per-batch policy cannot be replayed, and it records no reference for the candidates, so `as_run` cannot be either.

~~~json
{
  "schema": "driftaudit.run/v1",
  "id": "minimal-example",
  "source": "measured",
  "task": {"name": "toy", "n_items": 4},
  "environments": {
    "E1": {"decoding": "greedy-0.0", "scorer": "strict", "fingerprint": "model=m;decode=greedy-0.0;extract=strict@1"},
    "E2": {"decoding": "greedy-0.0", "scorer": "lenient", "fingerprint": "model=m;decode=greedy-0.0;extract=lenient@1"}
  },
  "schedule": {"0": "E1", "1": "E2"},
  "prompts": {"a1": "Answer briefly.", "b2": "Think step by step."},
  "snapshots": [
    {"round": 0, "prompt": "a1", "env": "E1"},
    {"round": 1, "prompt": "a1", "env": "E2"}
  ],
  "candidates": [
    {"id": "C1", "round": 0, "prompt": "b2", "parent": "a1", "env": "E1", "accepted": false},
    {"id": "C2", "round": 1, "prompt": "b2", "parent": "a1", "env": "E2", "accepted": true}
  ],
  "labels": {
    "a1": {"E1": {"current": "1010"}, "E2": {"current": "1110", "rerun": "1110"}},
    "b2": {"E1": {"current": "1010"}, "E2": {"current": "1111", "rerun": "1111"}}
  }
}
~~~

Saved as `minimal.json`:

~~~bash
driftaudit validate minimal.json
~~~

~~~text
minimal.json: valid run log (measured, 2 rounds, 4 items, 2 prompts, sparse label bank)
  - the Per-batch policy cannot be replayed: 1 label vector missing
  - the As run policy cannot be replayed: no reference recorded for the candidates
~~~

To write run logs from Python instead of by hand, use the `Recorder` (README, Section 4). Its output passes the same checks.
