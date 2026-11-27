# Command-line reference

    driftaudit [--version] COMMAND ...

Results go to standard output. Messages for you (progress, the address of a server, errors) go to standard error and start with `driftaudit:` when they are errors.

Exit status: 0 when the command did its job, 1 when something stopped it (a file that is not a run log, a bad option, a server that did not answer), and 2 when `audit --fail-on` found what it was asked to look for. Option mistakes also exit with 1, so 2 always means a finding.

A run log can be a v1 file or a toolkit run file from `toolkit/runs/`, which is upgraded when it is read. See [run-log-format.md](run-log-format.md).

Commands

- [demo](#demo)
- [view](#view)
- [audit](#audit)
- [report](#report)
- [run](#run)
- [convert](#convert)
- [validate](#validate)
- [rescore](#rescore)

## demo

Open the workbench on the five recorded GSM8K runs of the paper. It needs no network and no GPU.

    driftaudit demo [--port PORT] [--host HOST] [--no-open]

| Option | Meaning |
|---|---|
| `--port PORT` | Port to listen on. Default 8765. If it is taken, the next free port is used and the command says so. |
| `--host HOST` | Address to listen on. Default 127.0.0.1, which only this machine can reach. Any other address prints a warning, because other machines on the network can then read the workbench and the run logs opened in it. |
| `--no-open` | Do not open a browser. |

The server runs until you press Ctrl-C. It serves the site and nothing else on your machine.

~~~bash
driftaudit demo --no-open --port 8800
~~~

## view

Open the workbench on run logs of your own.

    driftaudit view RUN [RUN ...] [--title TITLE] [--port PORT] [--host HOST] [--no-open]

`RUN` is one or more run logs. They appear in the run picker as one group. `--title` names the group (default "Your run logs"). The port, host and no-open options are as for `demo`. If a run log has its raw outputs file next to it (`NAME.outputs.jsonl.gz`), the workbench can show the outputs.

~~~bash
driftaudit view run-a.json run-b.json --title "Ollama trials"
~~~

## audit

Replay the reference policies on a run log and print the result. No model is called. One run log prints its audit; several print a study across the runs.

    driftaudit audit RUN [RUN ...] [--policy ID] [--format text|md|json] [-o FILE]
                     [--schedule SPEC] [--stored-scoring as_recorded|rescore]
                     [--margin N] [--periodic-k K] [--fail-on stale-accept|false-accept] [--allow-mixed]

| Option | Meaning |
|---|---|
| `--policy ID` | The policy whose false accepts are listed under the summary. One of `frozen`, `stored_incumbent`, `per_batch`, `env_triggered`, `periodic`, `as_run`. Default `frozen`. |
| `--format` | `text` (default), `md` or `json`. JSON is the full result, unrounded. |
| `-o, --output FILE` | Write the result to FILE instead of printing it. |
| `--schedule SPEC` | What if the environments had changed at other rounds. `ROUND:ENV,...` with environment ids from the run log, for example `0:E1,4:E3`. |
| `--stored-scoring` | `as_recorded` (default) reads a stored reference with the labels it was given. `rescore` reads the stored text with the current scorer. |
| `--margin N` | A candidate is accepted when its wins minus its losses exceed N. Default 0. |
| `--periodic-k K` | List the `periodic` policy, which reruns the reference once it is K rounds old. Without this option the policy is left out of the tables; `--policy periodic` alone shows it with K = 3. |
| `--allow-mixed` | Pool runs that differ in task, number of items, number of rounds, schedule or environment fingerprints, or that share a run id. Without it such a study is refused with the first difference of each run; with it the command prints one warning and goes on. |
| `--fail-on` | Exit with status 2 if the policy made such a decision. `false-accept` is any accepted candidate that was not better. `stale-accept` is a false accept whose cause is a stale reference. With no `--policy`, the loop's own decisions are checked when the run log recorded them against references other than the incumbent in the same pass, and the frozen policy otherwise. A loop that compared each candidate with its own incumbent in the same pass, as the built-in loop does, cannot fail the check, and the audit leaves its `as_run` row out of the tables unless `--policy as_run` asks for it. |

A policy that needs labels the run log does not have is listed as not available, with the labels it would need. With `--fail-on`, a policy that cannot be replayed is an error (exit 1).

~~~bash
driftaudit audit run.json --policy env_triggered --format md -o audit.md
driftaudit audit run.json --fail-on stale-accept || echo "a stale reference promoted a prompt"
driftaudit audit run.json --schedule 0:E1,4:E3
~~~

## report

Write a single HTML file with the workbench and the run logs inlined, so it can be opened from disk or attached to an email.

    driftaudit report RUN [RUN ...] -o FILE [--title TITLE]

`-o` is required. Raw outputs are not included, and the batch layout of toolkit run files is left out.

~~~bash
driftaudit report run.json -o report.html
~~~

## run

Run the paper's self-improvement loop and write a run log. With no options it runs the bundled GSM8K sample on the mock backend, a simulator, and the run log says `"source": "synthetic"`.

    driftaudit run [--task gsm8k|FILE.jsonl] [--dev-file FILE.jsonl] [--n-dev N] [--n-eval N]
                   [--backend mock|hf|openai] [--model ID] [--base-url URL] [--concurrency N]
                   [--allow-insecure-http] [--rounds N] [--seed N] [--schedule SPEC] [--max-new-tokens N]
                   [--batch-size N] [--cache FILE] [--initial-prompt TEXT] [-o RUN.json]

| Option | Meaning |
|---|---|
| `--task` | `gsm8k` (default), the bundled sample of 200 development and 200 evaluation GSM8K items, or a JSONL file with one `{"question": ..., "answer": ...}` per line. In a file, the first `--n-dev` rows are the development set and the next `--n-eval` rows the evaluation set. An optional `id` names an item. |
| `--dev-file` | Take the development items from this file instead. The task file then supplies the `--n-eval` evaluation rows. Not allowed with `gsm8k`. |
| `--n-dev`, `--n-eval` | Number of development and evaluation items. Default 200 each. |
| `--backend` | `mock` (default), `hf` or `openai`. |
| `--model ID` | Model id. For `hf`, default Qwen/Qwen2.5-1.5B-Instruct. Required for `openai`. Not allowed with `mock`. |
| `--base-url URL` | OpenAI-compatible endpoint, `openai` backend only. Default https://api.openai.com/v1. |
| `--concurrency N` | Parallel requests for `openai`. Default 8. |
| `--allow-insecure-http` | Let `--base-url` use plain http to a host other than this machine. `openai` backend only. |
| `--rounds N` | Rounds of the loop. Default 11. |
| `--seed N` | Seed. Default 1. |
| `--schedule SPEC` | `ROUND:DECODING/SCORER,...`. DECODING is `greedy` or `sample@T`, SCORER is `strict`, `lenient`, `exact` or `exact-normalized`. Round 0 is required. Default `0:greedy/strict,4:sample@0.2/strict,8:sample@0.2/lenient` at 11 rounds; for other `--rounds` the two changes move in proportion (rounds 1 and 3 of 4, for example), with one combined change at round 1 for two rounds and none for one. |
| `--max-new-tokens N` | Longest generation. Default 640. |
| `--batch-size N` | Generation batch size. Default 64. |
| `--cache FILE` | Generation cache. Running the same command with the same file continues an interrupted run. For `hf` and `openai` the default is `NAME.cache.jsonl` next to the run log. |
| `--initial-prompt TEXT` | The instruction the loop starts from. The default is the paper's math tutor prompt for numeric answers and a short answer-only instruction for text answers. |
| `-o, --output FILE` | Where to write the run log. Default `driftaudit-run.json`. The raw outputs go next to it as `NAME.outputs.jsonl.gz`. |

The `hf` backend needs the extra: `pip install "driftaudit[hf] @ git+https://github.com/anupama-27/environment-drift-demo"`, or `pip install -e ".[hf]"` from a clone. The `openai` backend sends `DRIFTAUDIT_API_KEY` to the configured endpoint and uses `OPENAI_API_KEY` only when the host is api.openai.com. It says on stderr which variable it sends and to which host. Plain http is accepted for localhost, 127.0.0.1 and ::1 only; any other http address is refused unless `--allow-insecure-http` is given. Redirects are not followed, so the key never goes to a second host. Local servers do not need a key. The key is never written to the run log or the cache.

~~~bash
driftaudit run --n-dev 40 --n-eval 60 --rounds 6 -o small.json
driftaudit run --backend openai --model llama3.2 --base-url http://localhost:11434/v1 \
    --task questions.jsonl --n-dev 20 --n-eval 50 --rounds 4 -o ollama-run.json
driftaudit run --backend hf --n-dev 20 --n-eval 50 --rounds 4 -o qwen-run.json
~~~

## convert

Write a toolkit run file as a v1 run log. Other commands read toolkit run files directly, so this is only for producing a file in the new format.

    driftaudit convert LEGACY.json -o RUN.json [--slim]

`--slim` leaves out the batch layout (`meta.config.passes`), which the audit does not use.

~~~bash
driftaudit convert toolkit/runs/run_seed1_hf_Qwen2.5-1.5B-Instruct_n200_r11.json -o seed1.json
~~~

## validate

Check run logs against the v1 format and say what an audit can use from them.

    driftaudit validate RUN [RUN ...]

A valid run log prints one line (source, rounds, items, prompts, whether the label bank is complete or sparse), followed by a line for each policy that cannot be replayed and each note about completeness. An invalid one prints its problems. The exit status is 1 if any file is invalid.

~~~bash
driftaudit validate run.json
~~~

~~~text
run.json: valid run log (synthetic, 6 rounds, 60 items, 7 prompts, complete label bank)
~~~

## rescore

Grade the saved outputs of a run again with a scorer and compare the result with the labels in the run log. It shows how many labels a scorer change would flip, without calling a model.

    driftaudit rescore RUN --scorer ID [--env ENV] [--outputs FILE]

| Option | Meaning |
|---|---|
| `--scorer ID` | `strict`, `lenient`, `exact` or `exact-normalized`. Required. |
| `--env ENV` | Only this environment. Default all. |
| `--outputs FILE` | The outputs file. Default the one next to RUN. |

The run log needs the gold answers (`meta.gold`, which `driftaudit run` writes) or must be a run on the bundled GSM8K items. The outputs file is the sidecar written by `driftaudit run`. The five paper runs keep their outputs in chunk files, which `rescore` does not read.

~~~bash
driftaudit rescore run.json --scorer lenient
~~~

~~~text
run.json: outputs from run.outputs.jsonl.gz graded with the lenient scorer (version 1)
  env  stored scorer  labels  match  wrong to right  right to wrong  no outputs
  E1   strict            840    818              22               0           0
  E2   strict            840    816              24               0           0
  E3   lenient           840    840               0               0           0
  E4   lenient           840    840               0               0           0
~~~
