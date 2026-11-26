# DriftAudit: A Toolkit for Auditing Stale References in Self-Improving LLM Agents

Code and interactive replay for DriftAudit (NAACL 2027 System Demonstrations). DriftAudit treats every reference in a self-improving loop as a measurement tied to an environment version: it logs the environment of each round, reruns any stored reference under the current environment, reports the drift inflation of every candidate–reference pair, and replays refresh policies on the same candidates while checking every accept against ground truth. Sections 5–9 reproduce the tables and figures of the paper.

**Live replay:** https://anupama-27.github.io/environment-drift-demo/

## Repository Map

~~~text
toolkit/                        DriftAudit Source (Model Runs, Audit, Replay Export)
  run_seeds.py                  Cached Model Runs per Seed (the Only Script That Calls the Model)
  run_all.py                    All Tables and Figures From the Saved Runs, No Model Calls
  export_replay.py              Exports the Runs Into replay/ for the Website
  results/                      Generated Tables, Including table7_trend.md (Appendix B)
index.html, app.js, style.css   Interactive Replay (Plain HTML/CSS/JS, No Build Step)
replay/
  seed1.json … seed5.json       One File per Seed: Rounds, Decisions per Policy, Run Metadata
  all_seeds.json                Pooled Results, Inflation Intervals, Step-1 Questions
media/                          Images Used by the Site
README.md                       Setup and Result-by-Result Reproduction Guide
~~~

The case study uses Qwen2.5-1.5B-Instruct as both task model and proposer on GSM8K, over 11 rounds and five seeds (55 candidates). The environment changes on a fixed schedule:

| Environment | Decoding | Answer Extractor |
|---|---|---|
| Unchanged (U) | Greedy | Strict: a plain number in the last `\boxed{}` |
| Decoding (D) | Sampling at T = 0.2 | Strict |
| Extraction | Greedy | Lenient: also commas, currency, units and "answer is" phrasing, then the last number |
| Combined (C) | Sampling at T = 0.2 | Lenient |

Model weights, the generation cache and raw run logs are not in the source tree. All numbers in the replay are precomputed from the five saved runs; nothing is generated in the browser.

## 1. Open the Replay

The replay needs no GPU and no install. Use the live site, or serve this folder locally (browsers block loading the data files from `file://`):

~~~bash
python3 -m http.server 8000
~~~

Then open http://localhost:8000. The replay walks through nine steps: questions graded by both extractors, the improvement loop, the environment change, candidates scored against the stored and rerun references, the per-round false-accept chart (Fig. 2), a choice between policies, the five-seed dashboard (Fig. 3), the same components on other tasks, and the architecture. Step 8 is an illustration only: no runs were made on financial QA or code generation.

## 2. Prepare the Environment

Auditing a new loop requires the toolkit itself. The paper's runs used:

- Python 3.13, PyTorch 2.11, Transformers 5.16 (no vLLM)
- Qwen2.5-1.5B-Instruct at Hugging Face revision `989aa79`, fp16, no weight updates
- GSM8K (`openai/gsm8k`, main) at revision `740312a`
- Two NVIDIA T4 GPUs (Kaggle)

~~~bash
git clone https://github.com/anupama-27/environment-drift-demo
cd environment-drift-demo/toolkit
python3 --version
nvidia-smi
~~~

The development set is the first 200 GSM8K training items, shown to the proposer only as errors. The evaluation set is the first 200 GSM8K test items, used for both acceptance and ground truth.

## 3. Run the Model

Only this step calls the model. Each seed runs 11 rounds; in each round the proposer sees four rotating development errors and rewrites the system prompt (T = 0.7, asked to stay under 120 words).

~~~bash
python3 run_seeds.py 1 2 3 4 5
~~~

Generations are cached as JSONL under a SHA-1 key of model, system prompt, item, decoding parameters, seed and pass tag, so re-running a seed reads the cache instead of calling the model. Sampling is seeded per batch (64, 64, 64 and 8 items), top-k is 20 whenever sampling, and top-p is 1.0.

The initial system prompt is:

> You are a careful math tutor. Solve the problem step by step. Put the final answer as a plain number in \boxed{} on the last line.

## 4. Build Every Table and Figure

~~~bash
python3 run_all.py
~~~

This reads only the cache and the saved runs and makes no model calls. Adding a refresh policy costs no model calls either. For example, the stored-incumbent policy is replayed with:

~~~bash
DRIFT_FROZEN_MODE=last_accepted python3 run_all.py
~~~

## 5. Reproduce Table 1 (Auditing One Run)

Table 1 lists every decision of the frozen, per-batch and environment-triggered policies for seed 1, where the environment goes from U (rounds 0–3) to D (rounds 4–7) to C (rounds 8–10). Expected final accuracy: 69.0% (frozen), 67.0% (per-batch), 73.0% (environment-triggered); false accepts/accepts: 4/7, 0/2, 0/4.

## 6. Reproduce Table 2 (Refresh Policies)

The four policies are replayed on the same 55 candidates over five seeds.

| Policy | Acc (%) | False Accepts | False Rejects | Calls per Seed | Reruns per Seed |
|---|---|---|---|---|---|
| Frozen | 70.8 ± 2.0 | 13/34 | 0 | 4,411 | 0 |
| Stored incumbent | 71.2 ± 2.0 | 0/8 | 8 | 4,411 | 0 |
| Per-batch | 69.7 ± 2.2 | 3/13 | 11 | 6,611 | 11 |
| Environment-triggered | 72.5 ± 2.2 | 2/16 | 2 | 4,811 | 2 |

Call counts are estimates per seed, not measured inference cost.

## 7. Reproduce Figures 4 and 5 (Drift Inflation and Reference Age)

Figure 4 is the Drift Probe at reference age 3 (mean over five seeds with 95% CI). Expected: −0.13 pp in Unchanged (the noise floor) and +1.31 pp under extraction drift (95% CI 0.65 to 1.98, positive in all five seeds). Decoding drift has no consistent sign at this sample size. Across all stored greedy labels, the extractor switch turns 638 of 11,400 labels from incorrect to correct and none in reverse.

Figure 5 (Appendix B) reports drift inflation at every reference age. The same-candidate trend on a fixed set of 30 candidates (rounds 5–10, all ages) is written to `results/table7_trend.md`: drift inflation grows from 0.13 pp at age 0 (95% CI −1.73 to 2.00) to 2.52 pp at age 5, a paired increase of 2.38 pp (95% CI 0.30 to 4.46).

## 8. Reproduce Figure 6 (Ablations)

Figure 6 crosses the reference prompt (initial prompt or previous incumbent) with the environment in which its outputs were stored, using the frozen policy's acceptance rule on the same 55 candidates. Expected pooled false accepts: 38.2% for the full frozen policy, 31.8% with the environment matched, and 17.6% and 16.7% against the previous incumbent under the previous-round and current environment. The 2×2 factorial over rounds 8–10 gives an interaction of +0.27 ± 1.02 pp (p = 0.59).

## 9. Reproduce Table 3 (Independent Scorer)

Table 3 re-grades the frozen, per-batch and environment-triggered policies with a frozen scorer that credits only a committed final answer, with the acceptance rule unchanged. Expected false accepts/accepts under the independent scorer with drift: 17/34, 4/13 and 4/16, with final accuracy 70.6%, 69.7% and 72.3%.

## 10. Export the Replay

~~~bash
python3 export_replay.py
~~~

This writes `replay/seed1.json` … `seed5.json` and `replay/all_seeds.json`. The website reads these files unchanged.

## License

DriftAudit is released under the MIT License. GSM8K (Cobbe et al., 2021) is released under the MIT License, and Qwen2.5-1.5B-Instruct under the Apache-2.0 License; both keep their original licenses.
