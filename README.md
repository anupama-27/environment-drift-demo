# DriftAudit: A Toolkit for Auditing Stale References in Self-Improving LLM Agents

Code and interactive replay for DriftAudit (NAACL 2027 System Demonstrations). DriftAudit treats every reference in a self-improving loop as a measurement tied to an environment version: it logs the environment of each round, reruns any stored reference under the current environment, reports the drift inflation of every candidate–reference pair, and replays refresh policies on the same candidates while checking every accept against ground truth. Sections 5–10 reproduce the results and figures of the paper.

**Live replay:** https://anupama-27.github.io/environment-drift-demo/

## Repository Map

~~~text
toolkit/                        DriftAudit Source
  drift/                        Reference Manager, Environments, Extractors, Rerun Engine, Policy Replayer
  run_seeds.py                  Model Runs per Seed (the Only Script That Calls the Model)
  run_all.py                    Builds Tables From the Saved Runs, No Model Calls
  table3.py … table10.py        One Script per Result (Mapping in Section 4)
  stats.py                      Statistics Quoted in the Text, Figure 4 Intervals and Figure 6
  export_replay.py              Writes the Replay Files the Website Reads
  runs/                         The Five Saved Runs (run_seed1 … run_seed5, JSON)
  results/                      Generated Tables in Markdown, Including table7_trend.md and stats.md
  tests/                        23 Tests for Answer Extraction, Reference Age, Replay Export and the Backend
index.html, app.js, style.css   Interactive Replay (Plain HTML/CSS/JS, No Build Step)
replay/
  seed1.json … seed5.json       One File per Seed: Rounds, Decisions per Policy, Run Metadata
  all_seeds.json                Pooled Results, Inflation Intervals, Step-1 Questions
media/                          Images Used by the Site
README.md                       Setup and Result-by-Result Reproduction Guide
~~~

The case study uses Qwen2.5-1.5B-Instruct as both task model and proposer on GSM8K, over 11 rounds and five seeds (55 candidates). The environment changes on a fixed schedule:

| Rounds | Environment | Decoding | Answer Extractor |
|---|---|---|---|
| 0–3 | Unchanged (E1) | Greedy | Strict: a plain number in the last `\boxed{}` |
| 4–7 | Decoding (E2) | Sampling at T = 0.2 | Strict |
| 8–10 | Combined (E4) | Sampling at T = 0.2 | Lenient: also commas, currency, units and "answer is" phrasing, then the last number |

The Extraction environment (E3: greedy decoding, lenient extractor) is used by the Drift Probe and the ablations. The generation cache and model weights are not in the source tree; the five saved runs in `toolkit/runs/` are enough to rebuild every table without a GPU.

## 1. Open the Replay

The replay needs no GPU and no install. Use the live site, or serve the repository root locally (browsers block loading the data files from `file://`):

~~~bash
python3 -m http.server 8000
~~~

Then open http://localhost:8000. The replay walks through nine steps: questions graded by both extractors, the improvement loop, the environment change, candidates scored against the stored and rerun references, the per-round false-accept chart (Fig. 2), a choice between policies, the five-seed dashboard (Fig. 3), the same components on other tasks, and the architecture. Every number is precomputed from the saved runs, and nothing is generated in the browser. Step 8 is an illustration only: no runs were made on financial QA or code generation.

## 2. Prepare the Environment

Auditing a new loop requires the toolkit itself. The paper's runs used:

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

All commands below run from `toolkit/`. The scripts default to seeds 1–3, so set `DRIFT_SEEDS=1,2,3,4,5` to match the paper. The development set is the first 200 GSM8K training items, shown to the proposer only as errors; the evaluation set is the first 200 GSM8K test items, used for both acceptance and ground truth.

## 3. Run the Model

This is the only step that calls the model. Each seed runs 11 rounds; in each round the proposer sees four rotating development errors and rewrites the system prompt (T = 0.7, asked to stay under 120 words). To split seeds across two GPUs:

~~~bash
CUDA_VISIBLE_DEVICES=0 DRIFT_CACHE=runs/cache_gpu0.jsonl python3 run_seeds.py 1 3 5 &
CUDA_VISIBLE_DEVICES=1 DRIFT_CACHE=runs/cache_gpu1.jsonl python3 run_seeds.py 2 4
~~~

Every generation is cached as JSONL under a SHA-1 key of model, system prompt, item, decoding parameters, seed and pass tag, so an interrupted run resumes from the cache. Sampling is seeded per batch (64, 64, 64 and 8 items), top-k is 20 whenever sampling, and top-p is 1.0. The initial system prompt is:

> You are a careful math tutor. Solve the problem step by step. Put the final answer as a plain number in \boxed{} on the last line.

Skip this step to rebuild the results from the saved runs in `runs/`.

## 4. Build the Results

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
| Appendix D, per-seed results | `table9.py`, `table6.py` | `results/table9.md`, `results/table6_decisions.csv` |
| Statistics in the Setup and Evaluation text | `stats.py` | `results/stats.md` |

Adding a policy costs no model calls. The stored-incumbent policy, for example, is the frozen policy with a different reference. `stats.py` already reports its false accepts and rejects; to rebuild its row of Table 3 on its own:

~~~bash
DRIFT_SEEDS=1,2,3,4,5 DRIFT_FROZEN_MODE=last_accepted python3 table3.py
~~~

This overwrites `results/table3.md`; run `table3.py` again without `DRIFT_FROZEN_MODE` to restore it.

## 5. Reproduce Table 2 (Auditing One Run)

Table 2 lists every decision of the frozen, per-batch and environment-triggered policies for seed 1. Expected final accuracy: 69.0% (frozen), 67.0% (per-batch) and 73.0% (environment-triggered); false accepts/accepts: 4/7, 0/2 and 0/4.

## 6. Reproduce Table 3 (Refresh Policies)

The four policies are replayed on the same 55 candidates over five seeds.

| Policy | Acc (%) | False Accepts | False Rejects | Calls per Seed | Reruns per Seed |
|---|---|---|---|---|---|
| Frozen | 70.8 ± 2.0 | 13/34 | 0 | 4,411 | 0 |
| Stored incumbent | 71.2 ± 2.0 | 0/8 | 8 | 4,411 | 0 |
| Per-batch | 69.7 ± 2.2 | 3/13 | 11 | 6,611 | 11 |
| Environment-triggered | 72.5 ± 2.2 | 2/16 | 2 | 4,811 | 2 |

Accuracy, calls and reruns are in `results/table3.md`; false accepts and rejects for all four policies are in `results/stats.md`, which also gives the Fisher tests quoted in the text (p = 0.033, 0.019 and 0.360). Call counts are estimated per seed, not measured inference cost.

## 7. Reproduce Figures 4 and 5 and Table 4 (Drift Inflation and Reference Age)

Figure 4 is the Drift Probe at reference age 3 (mean over five seeds with 95% CI). Expected: −0.12 pp in Unchanged (95% CI −0.64 to 0.39), which sets the noise floor; −0.59 pp under decoding drift (−2.61 to 1.43), which has no consistent sign; +1.31 pp under extraction drift (0.65 to 1.98, positive in all five seeds); and +1.54 pp with both (0.04 to 3.04). The means are in `results/table4.md` and the intervals in `results/stats.md`.

Figure 5 reports drift inflation at every reference age. Table 4 (`results/table7_trend.md`) holds the candidate set fixed at the 30 candidates from rounds 5–10, so only the reference age changes. After the environment changes, drift inflation grows from 0.13 pp at age 0 (95% CI −1.73 to 2.00) to 2.52 pp at age 5, a paired increase of 2.38 pp (95% CI 0.30 to 4.46) in four of five seeds. With the environment unchanged, no age differs from zero.

## 8. Reproduce Figure 6 and Appendix C (What Causes False Accepts)

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

## 9. Export the Replay

~~~bash
python3 export_replay.py
~~~

This writes `seed1.json` … `seed5.json` and `all_seeds.json` to `toolkit/demo/replay/` from the saved runs. Copy them to `replay/` at the repository root to update the website.

## 10. Figures

Every figure is drawn from the outputs above.

| Figure | Contents | Source |
|---|---|---|
| 1 | Overview of DriftAudit | Diagram in the paper source; the counts in panel (b) are in `results/stats.md` |
| 2 | Per-round view of the replay (frozen policy, seed 5) | Replay step 5, drawn by `app.js` from `replay/seed5.json` |
| 3 | Five-seed dashboard | Replay step 7, drawn by `app.js` from `replay/all_seeds.json` |
| 4 | Drift inflation at reference age 3 | `results/table4.md`, intervals in `results/stats.md` |
| 5 | Drift inflation by reference age | `results/table7.md` |
| 6 | Pooled false accepts by reference prompt and stored environment | `results/stats.md` |

## License

DriftAudit is released under the MIT License. GSM8K (Cobbe et al., 2021) is released under the MIT License and Qwen2.5-1.5B-Instruct under the Apache-2.0 License; both keep their original licenses.
