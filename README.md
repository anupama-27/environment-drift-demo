# DriftAudit: A Toolkit for Auditing Stale References in Self-Improving LLM Agents

DriftAudit checks whether a self-improving LLM loop promoted a prompt because it was better or because the reference it was compared with had gone stale. It treats every reference as a measurement tied to an environment version (the model, the decoding settings and the answer extractor), logs the environment of each round, reruns a stored reference under the current environment, and reports the drift inflation of each candidate and reference pair. It then replays refresh policies on the same candidates and checks every accept against ground truth. This repository is the code and the interactive workbench for our NAACL 2027 System Demonstrations submission, and Sections 10 to 15 reproduce the results and figures of the paper.

There are three ways in:

- The hosted workbench at https://anupama-27.github.io/environment-drift-demo/ audits a run log in your browser. Five recorded GSM8K runs are bundled and nothing you open is uploaded.
- `pip install` gives you the `driftaudit` command, which runs the improvement loop on a model or a built-in simulator, audits run logs in the terminal, and serves the same workbench on your machine.
- The Python `Recorder` writes a run log from a loop you already have, so the same audit applies to it.

## Quick start

You need Python 3.9 or newer. The core package has no dependencies. It is not on PyPI, so install it from GitHub:

~~~bash
pip install "git+https://github.com/anupama-27/environment-drift-demo"
~~~

Open the workbench on the five recorded GSM8K runs. It serves the bundled site from a local server, needs no network and no GPU, and opens a browser tab (add `--no-open` to skip that). Stop it with Ctrl-C.

~~~bash
driftaudit demo
~~~

~~~text
Workbench at http://127.0.0.1:8765/ (Ctrl-C to stop)
~~~

Run a full improvement loop. With no options it uses the bundled GSM8K sample and a built-in simulator in place of a model, so it finishes in a few seconds. The simulator's numbers are synthetic: the run log is written with `"source": "synthetic"` and every command and page that shows it says so. It is there for trying the tool and says nothing about any model.

~~~bash
driftaudit run
~~~

~~~text
GSM8K: 200 development and 200 evaluation items, 11 rounds, seed 1, mock backend (driftaudit-mock), schedule 0:greedy/strict,4:sample@0.2/strict,8:sample@0.2/lenient
round 0  E1 Unchanged: candidate 61.0%, incumbent 65.5%, wins 23, losses 32, rejected (ok)
round 1  E1 Unchanged: candidate 59.0%, incumbent 65.5%, wins 21, losses 34, rejected (format_line_added)
round 2  E1 Unchanged: candidate 60.5%, incumbent 65.5%, wins 24, losses 34, rejected (format_line_added)
...
Wrote driftaudit-run.json and driftaudit-run.outputs.jsonl.gz (synthetic run: the mock backend simulates a model, so none of its numbers are measurements).
~~~

Audit the run. The audit replays six reference policies on the recorded candidates and counts the accepts that did not improve accuracy under the environment in force:

~~~bash
driftaudit audit driftaudit-run.json
~~~

~~~text
Policies
  policy                 accepts  false accepts  false rejects  final accuracy  reruns  model calls
  Frozen                       3              1              0           69.0%       0        4,411
  Stored incumbent             1              0              0           71.0%       0        4,411
  Per-batch                    1              0              0           71.0%      11        6,611
  Environment-triggered        1              0              0           71.0%       2        4,811
As run is not listed: the loop compared each candidate with its own incumbent in the same pass, so
its decisions match the ground-truth check by construction.
~~~

The frozen policy accepts the candidate of round 9 against the instruction it stored at round 0. Compared with a rerun of that instruction under the sampled decoding and lenient scorer now in force, the candidate loses, and it is 4.5 points less accurate than the incumbent: a false accept on a stale reference. The other policies reject it. Other seeds give other runs. To see what a finding looks like on a measured run, audit one of the paper's saved runs, `driftaudit audit toolkit/runs/run_seed5_hf_Qwen2.5-1.5B-Instruct_n200_r11.json` from a clone of this repository, which lists four false accepts under the frozen policy, three of them on a stale reference.

Look at the run in the workbench:

~~~bash
driftaudit view driftaudit-run.json
~~~

Every command and option is in [docs/cli.md](docs/cli.md).

## Repository Map

~~~text
src/driftaudit/                 The installable package (standard library only; extra: [hf])
  cli.py                        The driftaudit command
  schema.py                     Run log v1: load, validate, save, upgrade toolkit run files
  envs.py                       Environments, fingerprints, schedules
  scoring.py                    Scorers (strict and lenient numeric are the paper's extractors)
  engine.py                     Pair counts, policies, decisions, causes, drift probe, reference age
  stats.py                      Means, t intervals, Fisher exact test
  recorder.py                   Recorder and ReferenceStore, for logging your own loop
  loop.py                       The paper's self-improvement loop, parameterized
  backends/                     mock, hf and openai (any OpenAI-compatible endpoint)
  tasks.py                      JSONL tasks and the bundled GSM8K sample
  render.py, report.py          Text and Markdown audits, single-file HTML report
  server.py                     Local server behind driftaudit demo and driftaudit view
toolkit/                        The paper's experiment scripts (unchanged)
  drift/                        Reference manager, environments, extractors, rerun engine, policy replayer
  run_seeds.py                  Model runs per seed (the only script that calls the model)
  run_all.py                    Builds tables from the saved runs, no model calls
  table3.py … table10.py        One script per result (mapping in Section 9)
  stats.py                      Statistics quoted in the text, Figure 4 intervals and Figure 6
  export_replay.py              Writes the replay files the Case study page reads
  runs/                         The five saved runs (run_seed1 … run_seed5, JSON)
  results/                      Generated tables in Markdown, including table7_trend.md and stats.md
  tests/                        23 tests for answer extraction, reference age, replay export and the backend
  gt_audit/                     Independent scorer behind Table 5 and Appendix D, its 60 tests, audit labels and outputs
index.html, assets/, data/      The workbench: plain HTML, CSS and JavaScript, no build step
                                data/ holds the five paper runs as run logs, their raw outputs and the GSM8K sample
replay/
  seed1.json … seed5.json       One file per seed: rounds, decisions per policy, run metadata
  all_seeds.json                Pooled results, inflation intervals, step-1 questions
tests/                          pytest (python/), node:test (js/) and the golden results both engines are checked against
docs/                           run-log-format.md, cli.md, architecture.md
examples/                       record_your_own_loop.py
media/                          Images used by the site
README.md                       Install, usage and result-by-result reproduction guide
~~~

## 1. Open the workbench

The hosted workbench is at https://anupama-27.github.io/environment-drift-demo/. It is a static site: every audit is computed by JavaScript in your browser from the labels in the run log, no model runs there, and nothing is sent anywhere.

To use it offline, run `driftaudit demo` for the five recorded runs, or `driftaudit view` with one or more run logs of your own:

~~~bash
driftaudit view my-run.json other-run.json
~~~

Both commands listen on 127.0.0.1 only, starting at port 8765 and moving to the next free port if it is taken. `--port` and `--no-open` change that.

On the page, you can pick a run from the run picker, or drag a run log anywhere on the page to open it. The file is read by your browser and stays on your machine. Run logs in the v1 format of Section 5 open, and so do the run files in `toolkit/runs/`.

The run picker also lists a smoke run in `data/runs/smoke/`: one short run of Qwen2.5-0.5B-Instruct on 40 GSM8K items over 4 rounds with one seed, recorded on an M1 laptop to show the recorder working from start to finish. It was recorded with `driftaudit run --backend hf --model Qwen/Qwen2.5-0.5B-Instruct --task gsm8k --n-dev 20 --n-eval 40 --rounds 4 --seed 1 --schedule "0:greedy/strict,2:sample@0.2/strict,3:sample@0.2/lenient" --max-new-tokens 320 --batch-size 16 -o smoke-qwen2.5-0.5b.json`. The paper's numbers come only from the five GSM8K runs in `data/runs/paper/`, and the smoke run's accuracy figures are not results of the paper.

From a checkout of the repository you can also serve the site with `python3 -m http.server 8000` in the repository root and open http://localhost:8000. For a single HTML file you can send to someone, `driftaudit report my-run.json -o report.html` writes the workbench with your run logs inlined.

## 2. Audit a run from the command line

~~~bash
driftaudit audit my-run.json
~~~

The audit never calls a model. It replays refresh policies on the candidates the loop already produced and reads the recorded labels. Every policy chooses among the same candidates, so they differ only in which reference they compare against and how often they rerun it.

| Policy | Rule |
|---|---|
| `frozen` | Never refresh; compare with the reference stored at round 0 |
| `stored_incumbent` | Never refresh; compare with the outputs stored when the incumbent was accepted |
| `per_batch` | Refresh every batch |
| `env_triggered` | Refresh after detected environment changes |
| `periodic` | Refresh once the reference is k rounds old; listed by `driftaudit audit` only when `--periodic-k` is given |
| `as_run` | The decisions the loop recorded, against the reference it recorded |

`--policy` picks the policy whose errors are listed below the summary table (default `frozen`). The columns of the summary table:

- accepts: candidates the policy promoted.
- false accepts: accepted candidates whose accuracy under the current environment is not higher than the incumbent's.
- false rejects: rejected candidates that were in fact better than the incumbent.
- final accuracy: accuracy of the prompt the policy ends with, under the last environment.
- reruns: how many times the policy measured its reference again.
- model calls: an estimate from the run's sizes, not measured inference cost.

Under each false accept the audit prints the wins and losses against the stored reference and against the same reference rerun now, the drift inflation in percentage points (the gap between those two win rates), and a cause: a stale reference (the environment had changed, and a rerun reference would have rejected the candidate), accepted anyway (the environment had changed, but a rerun reference would also have accepted it), or no environment change.

A policy is replayed only when the run log holds the labels it needs. If it does not, the audit says which labels are missing instead of failing. Section 5 and [docs/run-log-format.md](docs/run-log-format.md) say what each analysis needs.

Other options: `--format md` or `--format json` with `-o FILE` writes the result to a file; `--schedule 0:E1,4:E3` replays under a different environment schedule; `--stored-scoring rescore` reads stored outputs with the current scorer; `--margin` changes how many more wins than losses a candidate needs. Several run logs together print a study across runs.

`--fail-on` turns the audit into a check. It exits with status 2 when the run contains a false accept, 0 when it does not, and 1 for any other failure such as a file that is not a run log.

~~~bash
driftaudit audit my-run.json --fail-on stale-accept
~~~

`stale-accept` fails only on false accepts caused by a stale reference. `false-accept` fails on any false accept. Without `--policy`, the check looks at the loop's own decisions when the run log recorded them and at the frozen policy otherwise.

## 3. Run the loop on your own model

`driftaudit run` runs the paper's pipeline: a trajectory of rounds in which a proposer rewrites the instruction and each candidate is compared with the incumbent, then a measurement pass over every instruction under every environment, once as stored and once as a rerun. It writes the run log and the raw outputs next to it (`NAME.outputs.jsonl.gz`).

Start small. Every round and every rerun is model calls, so try `--n-dev 20 --n-eval 50 --rounds 4` first.

Backends:

- `--backend mock` is the default, the simulator described in the quick start. Its runs are tagged synthetic.
- `--backend hf` runs a Hugging Face model on this machine, by default Qwen/Qwen2.5-1.5B-Instruct, or the one named by `--model`. It needs the `hf` extra (torch, transformers and accelerate): `pip install "driftaudit[hf] @ git+https://github.com/anupama-27/environment-drift-demo"`, or `pip install -e ".[hf]"` from a clone.
- `--backend openai` works with any server that speaks the OpenAI chat completions API. `--model` is required and `--base-url` points at the server. `DRIFTAUDIT_API_KEY` is sent to the server you configure. `OPENAI_API_KEY` is sent only to api.openai.com, so a key exported for OpenAI never reaches another host. Plain http is accepted for this machine only (localhost, 127.0.0.1, ::1); for another host use https, or pass `--allow-insecure-http` if the network is yours. Redirects are not followed. The key is optional for local servers and is never written to the run log or the cache. For a local Ollama server:

~~~bash
driftaudit run --backend openai --model llama3.2 --base-url http://localhost:11434/v1 \
    --task questions.jsonl --n-dev 20 --n-eval 50 --rounds 4 -o my-run.json
~~~

Without `--base-url` the OpenAI API is used. `--concurrency` sets how many requests run in parallel (default 8).

Generations from `hf` and `openai` are cached in a JSONL file next to the run log (`--cache FILE` to choose another), so running the same command again continues an interrupted run.

Tasks. `--task gsm8k` is a bundled sample of 200 development and 200 evaluation GSM8K items. To use your own questions, pass a JSONL file with one object per line:

~~~text
{"question": "What is 6 times 7?", "answer": 42}
~~~

An optional `id` field names the item. The first `--n-dev` rows are the development set, which the proposer sees as errors, and the next `--n-eval` rows are the evaluation set, so the file needs at least that many rows. `--dev-file` takes the development rows from a second file, and then the task file supplies `--n-eval` evaluation rows. Answers must have one checkable form. Numeric answers go with the strict and lenient scorers. For text answers use `exact` or `exact-normalized` in the schedule. One schedule cannot mix the two kinds.

Schedule. `--schedule` says which environment is in force from which round, as comma-separated `ROUND:DECODING/SCORER` entries. DECODING is `greedy` or `sample@T` with a temperature above 0, and SCORER is `strict`, `lenient`, `exact` or `exact-normalized`. Round 0 is required, and an entry stays in force until the next one. With 11 rounds the default is the paper's schedule:

~~~text
0:greedy/strict,4:sample@0.2/strict,8:sample@0.2/lenient
~~~

This moves from greedy decoding and the strict scorer to sampling at round 4 and to the lenient scorer at round 8. For other `--rounds` the two changes move in proportion, for example to rounds 1 and 3 of 4, so that both happen inside the run; with two rounds there is one combined change at round 1, and with one round none. A schedule for text answers might be `0:greedy/exact,3:greedy/exact-normalized`. Rounds go from 0 to `--rounds` minus 1, so a change scheduled after the last round never takes effect, and the command says so.

Also available: `--seed`, `--max-new-tokens`, `--batch-size` and `--initial-prompt`. `driftaudit run --help` lists everything.

## 4. Record a loop you already have

If your loop is not the built-in one, log it with the `Recorder` and audit the result. The recorder writes down what your loop measured: one 0/1 label per evaluation item for each prompt under each environment, and one entry per round with the decision.

~~~python
import driftaudit as da

strict = da.Environment.make(name="Strict", model="my-model", temperature=0, scorer="strict")
lenient = da.Environment.make(name="Lenient", model="my-model", temperature=0, scorer="lenient")

rec = da.Recorder(task="my-task", n_items=4, model="my-model")

# Round 0 runs under the strict scorer.
rec.add_labels("Answer briefly.", strict, [1, 0, 1, 0])
rec.add_labels("Think step by step.", strict, [1, 1, 1, 0])
rec.add_round(candidate="Think step by step.", incumbent="Answer briefly.", env=strict,
              accepted=True, reference=("Answer briefly.", strict))

# Round 1 runs under the lenient scorer, but the loop still compares with the stored reference.
rec.add_labels("Think step by step.", lenient, [1, 1, 1, 1])
rec.add_labels("Answer briefly.", lenient, [1, 1, 1, 0])
rec.add_labels("Check the sum twice.", lenient, [1, 1, 1, 1])
rec.add_round(candidate="Check the sum twice.", incumbent="Think step by step.", env=lenient,
              accepted=True, reference=("Think step by step.", strict))

run = rec.save("my-run.json")
result = da.audit(run)
print(result["policies"]["frozen"]["false_accepts"])
~~~

Four calls cover a loop: `add_labels` for every evaluation, `add_round` for every decision, `add_labels(..., rerun=True)` for a reference measured again, and `save`. `reference=` records what your loop compared the candidate with, which lets the audit replay your own decisions next to the other policies. The toy above has four items and leaves most of the label bank empty. `driftaudit validate my-run.json` lists the policies it cannot replay and the labels they would need, and `driftaudit audit my-run.json` gives the same list. The more of the bank you fill in, especially the reruns of each incumbent under each environment, the more of the audit you get.

`ReferenceStore` is a small helper for a live loop. It keeps the reference with the environment it was measured in, and `store.stale(env)` says whether the environment's fingerprint has changed since. [examples/record_your_own_loop.py](examples/record_your_own_loop.py) is a complete loop on a toy model that uses both; run it with `python examples/record_your_own_loop.py`.

## 5. The run-log format

A run log is one JSON file. The shape, with the fields an audit reads:

~~~text
{ "schema": "driftaudit.run/v1", "id": "...", "source": "measured" or "synthetic",
  "task": {"name": "...", "n_items": 200}, "model": {"id": "..."},
  "environments": {"E1": {"decoding": "greedy-0.0", "scorer": "strict", "fingerprint": "..."}},
  "schedule": {"0": "E1", "4": "E2"},            round from which each environment is in force
  "prompts": {"<id>": "instruction text"},
  "snapshots": [{"round": 0, "prompt": "<id>", "env": "E1"}],       incumbent at the start of each round
  "candidates": [{"id": "C1", "round": 0, "prompt": "<id>", "parent": "<id>", "accepted": false}],
  "labels": {"<prompt>": {"<env>": {"current": "1101...", "rerun": "1100..."}}} }   one 0/1 per item
~~~

The `labels` bank holds, for each prompt and environment, the stored pass (`current`) and an independent later pass (`rerun`). It may be sparse. Raw model outputs live in a separate file next to the run log, never inside it. Files written by `toolkit/` before this format existed load as they are and are upgraded in memory. [docs/run-log-format.md](docs/run-log-format.md) describes every field, what each analysis needs from the label bank, and a minimal example that `driftaudit validate` accepts.

The command-line reference is [docs/cli.md](docs/cli.md), and [docs/architecture.md](docs/architecture.md) explains how the two audit engines, the site and the package fit together.

## Reproducing the paper

The rest of this README reproduces the paper's tables and figures from the saved runs. The toolkit scripts are unchanged by the package.

The case study uses Qwen2.5-1.5B-Instruct as both task model and proposer on GSM8K, over 11 rounds and five seeds (55 candidates). The environment changes on a fixed schedule:

| Rounds | Environment | Decoding | Answer Extractor |
|---|---|---|---|
| 0–3 | Unchanged (E1) | Greedy | Strict: a plain number in the last `\boxed{}` |
| 4–7 | Decoding (E2) | Sampling at T = 0.2 | Strict |
| 8–10 | Combined (E4) | Sampling at T = 0.2 | Lenient: also commas, currency, units and "answer is" phrasing, then the last number |

The Extraction environment (E3: greedy decoding, lenient extractor) is used by the Drift Probe and the ablations. The generation cache and model weights are not in the source tree; the five saved runs in `toolkit/runs/` are enough to rebuild every table without a GPU.


## 6. Open the Replay

The case study needs no GPU and no install. Use the hosted workbench at https://anupama-27.github.io/environment-drift-demo/#/case-study, or run `driftaudit demo` and open the Case study page. From a checkout without installing the package, serve the repository root (browsers block loading the data files from `file://`):

~~~bash
python3 -m http.server 8000
~~~

Then open http://localhost:8000/#/case-study. The case study walks through nine steps: questions graded by both extractors, the improvement loop, the environment change, candidates scored against the stored and rerun references, the per-round false-accept chart (Fig. 2), a choice between policies, the five-seed dashboard (Fig. 3), the same components on other tasks, and the architecture. Every number is precomputed from the saved runs, and nothing is generated in the browser. Step 8 is an illustration only: no runs were made on financial QA or code generation.

## 7. Prepare the Environment

Reproducing the paper's results requires the toolkit. The paper's runs used:

- Python 3.13, PyTorch 2.11, Transformers 5.16 (no vLLM)
- Qwen2.5-1.5B-Instruct at Hugging Face revision `989aa79`, fp16, no weight updates
- GSM8K (`openai/gsm8k`, main) at revision `740312a`
- Two NVIDIA T4 GPUs (Kaggle)

~~~bash
git clone https://github.com/anupama-27/environment-drift-demo
cd environment-drift-demo/toolkit
pip install -r requirements.txt
python3 -m pytest tests
~~~

These are the toolkit's own 23 tests; they need only pytest and no GPU. The tests of the `driftaudit` package are separate: from the repository root, run `pip install -e ".[dev]"` and then `python -m pytest`.

All commands below run from `toolkit/`. The scripts default to seeds 1–3, so set `DRIFT_SEEDS=1,2,3,4,5` to match the paper. The development set is the first 200 GSM8K training items, shown to the proposer only as errors; the evaluation set is the first 200 GSM8K test items, used for both acceptance and ground truth.

## 8. Run the Model

This is the only step that calls the model. Each seed runs 11 rounds; in each round the proposer sees four rotating development errors and rewrites the system prompt (T = 0.7, asked to stay under 120 words). To split seeds across two GPUs:

~~~bash
CUDA_VISIBLE_DEVICES=0 DRIFT_CACHE=runs/cache_gpu0.jsonl python3 run_seeds.py 1 3 5 &
CUDA_VISIBLE_DEVICES=1 DRIFT_CACHE=runs/cache_gpu1.jsonl python3 run_seeds.py 2 4
~~~

Every generation is cached as JSONL under a SHA-1 key of model, system prompt, item, decoding parameters, seed and pass tag, so an interrupted run resumes from the cache. Sampling is seeded per batch (64, 64, 64 and 8 items), top-k is 20 whenever sampling, and top-p is 1.0. The initial system prompt is:

> You are a careful math tutor. Solve the problem step by step. Put the final answer as a plain number in \boxed{} on the last line.

Skip this step to rebuild the results from the saved runs in `runs/`.

## 9. Build the Results

~~~bash
DRIFT_SEEDS=1,2,3,4,5 python3 run_all.py
DRIFT_SEEDS=1,2,3,4,5 python3 table7.py
DRIFT_SEEDS=1,2,3,4,5 python3 stats.py
~~~

These read only the saved runs and make no model calls, and together take a few seconds. `run_all.py` builds Tables 3–6 and 8–10 of our working drafts; `table7.py` and `stats.py` run separately. Each script writes to `results/` and a log to `logs/`. The script numbers follow our working drafts, not the paper:

| Paper Result | Script | Output |
|---|---|---|
| Figure 1, policy counts in panel (b) | `table6.py`, `stats.py` | `results/table6.md`, `results/stats.md` |
| Table 2, decisions for seed 1 | `table6.py`, `table10.py` | `results/table6_decisions.csv`, `results/table10_demo_trace.md` |
| Table 3, refresh policies | `table3.py` (accuracy, calls, reruns), `stats.py` (false accepts and rejects) | `results/table3.md`, `results/stats.md` |
| Figure 4, drift inflation at age 3 | `table4.py`, `stats.py` (95% intervals) | `results/table4.md`, `results/stats.md` |
| Figure 5 and Table 4, reference age | `table7.py` | `results/table7.md`, `results/table7_trend.md` |
| Figure 6, false accepts by reference | `stats.py` | `results/stats.md` |
| Appendix C, ablations | `table8.py`, `stats.py` (tests and 2×2 effects) | `results/table8.md`, `results/stats.md` |
| Table 5, independent scorer | `gt_audit/gt_tables.py` | `gt_audit/gt_tables_output.txt` |
| Appendix D, scorer checks | `gt_audit/score_audit.py` | `gt_audit/audit_results.txt`, `gt_audit/spot-check-mandar.xlsx` |
| Appendix D, per-seed results | `table9.py`, `table6.py` | `results/table9.md`, `results/table6_decisions.csv` |
| Statistics in the Setup and Evaluation text | `stats.py` | `results/stats.md` |

Adding a policy costs no model calls. The stored-incumbent policy, for example, is the frozen policy with a different reference. `stats.py` already reports its false accepts and rejects; to rebuild its row of Table 3 on its own:

~~~bash
DRIFT_SEEDS=1,2,3,4,5 DRIFT_FROZEN_MODE=last_accepted python3 table3.py
~~~

This overwrites `results/table3.md`; run `table3.py` again without `DRIFT_FROZEN_MODE` to restore it.

## 10. Reproduce Table 2 (Auditing One Run)

Table 2 lists every decision of the frozen, per-batch and environment-triggered policies for seed 1. Expected final accuracy: 69.0% (frozen), 67.0% (per-batch) and 73.0% (environment-triggered); false accepts/accepts: 4/7, 0/2 and 0/4.

## 11. Reproduce Table 3 (Refresh Policies)

The four policies are replayed on the same 55 candidates over five seeds.

| Policy | Acc (%) | False Accepts | False Rejects | Calls per Seed | Reruns per Seed |
|---|---|---|---|---|---|
| Frozen | 70.8 ± 2.0 | 13/34 | 0 | 4,411 | 0 |
| Stored incumbent | 71.2 ± 2.0 | 0/8 | 8 | 4,411 | 0 |
| Per-batch | 69.7 ± 2.2 | 3/13 | 11 | 6,611 | 11 |
| Environment-triggered | 72.5 ± 2.2 | 2/16 | 2 | 4,811 | 2 |

Accuracy, calls and reruns are in `results/table3.md`; false accepts and rejects for all four policies are in `results/stats.md`, which also gives the Fisher tests quoted in the text (p = 0.033, 0.019 and 0.360). Call counts are estimated per seed, not measured inference cost.

## 12. Reproduce Figures 4 and 5 and Table 4 (Drift Inflation and Reference Age)

Figure 4 is the Drift Probe at reference age 3 (mean over five seeds with 95% CI). Expected: −0.12 pp in Unchanged (95% CI −0.64 to 0.39), which sets the noise floor; −0.59 pp under decoding drift (−2.61 to 1.43), which has no consistent sign; +1.31 pp under extraction drift (0.65 to 1.98, positive in all five seeds); and +1.54 pp with both (0.04 to 3.04). The means are in `results/table4.md` and the intervals in `results/stats.md`.

Figure 5 reports drift inflation at every reference age. Table 4 (`results/table7_trend.md`) holds the candidate set fixed at the 30 candidates from rounds 5–10, so only the reference age changes. After the environment changes, drift inflation grows from 0.13 pp at age 0 (95% CI −1.73 to 2.00) to 2.52 pp at age 5, a paired increase of 2.38 pp (95% CI 0.30 to 4.46) in four of five seeds. With the environment unchanged, no age differs from zero.

## 13. Reproduce Figure 6 and Appendix C (What Causes False Accepts)

Figure 6 applies the frozen policy's acceptance rule to the same 55 candidates while changing the reference prompt and the environment its outputs were stored in. `results/stats.md` gives every bar:

| Reference Prompt | Stored Environment | False Accepts | Drift Inflation (pp) |
|---|---|---|---|
| Initial prompt | Initial | 13/34 (38.2%) | +1.05 |
| Initial prompt | Previous round | 8/24 (33.3%) | −0.09 |
| Initial prompt | Current | 7/22 (31.8%) | −0.34 |
| Previous incumbent | Initial | 5/16 (31.2%) | −0.45 |
| Previous incumbent | Previous round | 3/17 (17.6%) | −0.39 |
| Previous incumbent | Current | 3/18 (16.7%) | −0.32 |

For Appendix C, `table8.py` switches parts of the environment schedule off: pooled false accepts are 18/37 (48.6%) with no decoding changes and 12/30 (40.0%) with no extraction changes. `results/stats.md` gives the paired tests (removing extraction drift lowers drift inflation by 0.59 ± 0.25 pp, p = 0.006; removing decoding drift by 0.89 ± 1.19 pp, p = 0.169) and the 2×2 factorial over rounds 8–10 (+1.33, +1.90 and +3.50 pp, interaction +0.27 ± 1.02 pp, p = 0.59).

## 14. Reproduce Table 5 and Appendix D (Independent Scorer)

Table 5 re-grades the frozen, per-batch and environment-triggered policies with an independent scorer that credits only a committed final answer, while the acceptance rule stays the same. The scorer, its tests, the audit labels and the outputs of the original audit are in `toolkit/gt_audit/`, whose README lists every file.

~~~bash
cd gt_audit
python3 -m pytest test_gt_scorer.py
python3 gt_tables.py
python3 score_audit.py
~~~

`gt_tables.py` reads the saved runs and the committed scorer labels (`gt_labels.json`) and writes `gt_tables_output.txt`. Expected, in section (iii) under "GT=gt": false accepts 17/34, 4/13 and 4/16 with drift and 19/37, 3/11 and 2/12 without, and final accuracy 70.6%, 69.7% and 72.3%. `score_audit.py` writes `audit_results.txt`: the lenient extractor's last-number fallback gives false credit in 4 of 123 cases (3.3%, 95% CI 1.3–8.1%), and the scorer agrees with the audit labels on 161 of 198 items (81%). The audit labels were written by an AI annotator; one author blind-checked 29 of them and agreed on 27 of the 28 unambiguous cases (`spot-check-mandar.xlsx`).

The committed `gt_scores.csv` and `gt_labels.json` come from `rescore.py`, which re-scores every decoded output and needs `all_outputs.csv` (65 MB, not in the repository) as input. Run against this toolkit, one line of `gt_tables_output.txt` outside Table 5 (Unchanged drift inflation, −0.125 pp) prints −0.12 rather than the recorded −0.13.

## 15. Export the Replay

~~~bash
python3 export_replay.py
~~~

This writes `seed1.json` … `seed5.json` and `all_seeds.json` to `toolkit/demo/replay/` from the saved runs. Copy them to `replay/` at the repository root to update the Case study page of the workbench.

## 16. Figures

Every figure is drawn from the outputs above.

| Figure | Contents | Source |
|---|---|---|
| 1 | Overview of DriftAudit | Diagram in the paper source; the counts in panel (b) are in `results/stats.md` |
| 2 | Per-round view of the case study (frozen policy, seed 5) | Case study step 5, drawn from `replay/seed5.json` |
| 3 | Five-seed dashboard | Case study step 7, drawn from `replay/all_seeds.json` |
| 4 | Drift inflation at reference age 3 | `results/table4.md`, intervals in `results/stats.md` |
| 5 | Drift inflation by reference age | `results/table7.md` |
| 6 | Pooled false accepts by reference prompt and stored environment | `results/stats.md` |

## License

DriftAudit is released under the MIT License. GSM8K (Cobbe et al., 2021) is released under the MIT License and Qwen2.5-1.5B-Instruct under the Apache-2.0 License; both keep their original licenses. The GSM8K items bundled with the package are MIT licensed (OpenAI), and the fonts in `assets/fonts/` (Barlow and IBM Plex Mono) are under the SIL Open Font License.
