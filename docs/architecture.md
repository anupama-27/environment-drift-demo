# Architecture

DriftAudit is a Python package, a static web page, and the paper's original scripts. The package and the page contain the same audit. This note says how they stay equal, why the page needs no server, how the wheel carries the page, and where the paper's eight components live.

## Two engines, one set of numbers

The audit exists twice. `src/driftaudit/engine.py` is the Python engine behind `driftaudit audit`, and `assets/js/engine/` (`stats.js`, `schema.js`, `scorers.js`, `engine.js`) is the JavaScript engine behind the workbench. Both take a run log and return the same JSON: per-round decisions, the six policies, causes of false accepts, scorer flips, and for several runs the policy tests, the drift probe and the reference-age curves. Fractions stay fractions, and only `delta_pp` is in percentage points.

Python is the reference. Its semantics are those of `toolkit/drift/analysis.py`, the code behind every number in the paper, generalized from the paper's fixed environments E1 to E4 to the environments a run log declares. Tests pin the paper's numbers in the Python engine and check it against the toolkit's own functions on every run, policy and schedule ablation.

Goldens keep the JavaScript engine equal to it. `python -m driftaudit._golden` runs the Python engine over a list of cases (the five paper runs, the study of all five, option variants such as `margin`, `periodic_k`, `fixed_age`, `stored_scoring` and a changed schedule, and three small synthetic runs that cover other sizes, six environments, a sparse label bank and recorded references) and writes the results to `tests/golden/`, with `manifest.json` listing every case. The JavaScript tests (`tests/js/`, run with `node --test tests/js/`) load the same run logs, run the JavaScript engine with the same options and compare each result with its golden to 1e-9. `python -m driftaudit._golden --check` fails if a file on disk is not what the Python engine produces now, and CI runs it, so a change to the Python engine that moves a number fails until the goldens are regenerated on purpose. The JavaScript engine never has behaviour the Python one lacks.

## Why the site is static

The workbench is `index.html`, `assets/` and `data/`: classic script files that attach to one global `DA` namespace, with no modules, no bundler and no CDN. Because nothing needs a backend, the same files run in four places: on GitHub Pages, from the local server behind `driftaudit demo` and `driftaudit view`, inside the wheel, and inlined into one HTML file by `driftaudit report`. A reviewer does not need a service that can go to sleep, and the audit of a run log never leaves the browser. No model runs in the page.

Run logs are untrusted input. Every dynamic string reaches the page through an escaping template helper, and the local server binds 127.0.0.1, serves only the site and the files named on the command line, and checks every path against the site directory after resolving symlinks.

## How the wheel includes the site

The site lives at the repository root so GitHub Pages can serve it. `pyproject.toml` copies the same files into the wheel under `driftaudit/web/` with hatchling's `force-include` (`index.html`, `favicon.svg`, `assets/`, `data/` and `replay/`). At run time `driftaudit._paths.web_dir()` returns `driftaudit/web/` when it exists and the repository root otherwise, which is the case for an editable install from a checkout. The bundled GSM8K sample that `driftaudit run` uses is read from the same `data/tasks/gsm8k/` folder, so one copy of the data serves the page, the CLI and the tests. The source distribution carries the site and the tests as well. CI builds the wheel, installs it into a clean environment and fetches the site from `driftaudit demo` to prove it.

## Where the paper's components live

The paper describes eight components. In this repository:

| Component | Python package | Workbench | Paper toolkit |
|---|---|---|---|
| Reference manager | `ReferenceStore` in `recorder.py` keeps a reference with the environment it was measured in and says when it is stale. The replay in `engine.py` models what each policy would hold. | Policies view | `toolkit/drift/pipeline.py` |
| Environment tracker | `envs.py`: `Environment`, `make_fingerprint`, `env_at`. The schedule and the fingerprints are stored in the run log (`schema.py`). | Summary view, environment timeline | `toolkit/drift/envs.py` |
| Rerun engine | `loop.py` measures every instruction under every environment, stored and rerun. `driftaudit rescore` grades saved outputs again. | Environments view, scorer flips | `toolkit/drift/pipeline.py`, `toolkit/rerun_greedy.py` |
| Comparison view | `pair` and `_decision` in `engine.py` count wins and losses against the stored and the rerun reference and compute drift inflation. `render.py` prints them. | Rounds view | `toolkit/drift/analysis.py` |
| Ground-truth panel | `_decision` checks each accept against the candidate's and the incumbent's accuracy under the current environment, and names false accepts and false rejects. | Rounds view, round detail | `candidate_truth` in `analysis.py` |
| False-accept dashboard | `study` pools decisions over runs and gives the causes, the policy tests, the drift probe and the age curves. `render.py` prints them. | Policies view, drift probe | `toolkit/stats.py`, `table*.py` |
| Policy replayer | `_replay` and `POLICIES` in `engine.py` replay frozen, stored incumbent, per-batch, environment-triggered and periodic refresh, and the loop's own decisions, on the same candidates. | Policies view | `simulate` in `analysis.py` |
| Reproducibility log | The run log itself (`schema.py`, [run-log-format.md](run-log-format.md)): prompts, environments, decisions, labels, tool version, and a pointer to the raw outputs. | Export | `toolkit/runs/`, `toolkit/logs/` |

The case study on the site is the nine-step walkthrough of the five paper runs. It reads the precomputed files in `replay/`, which `toolkit/export_replay.py` writes.
