# Examples

## Record your own loop

`record_your_own_loop.py` shows how to make a run log from an optimizer you already have. It
uses a toy model and a toy optimizer so that it runs anywhere in under a second:

    python examples/record_your_own_loop.py my-loop-run.json

The script calls the recorder in four places, and those are the lines to copy:

- `rec.add_labels(prompt, env, labels)` after every evaluation, with one 0/1 label per
  evaluation item, always in the same item order;
- `rec.add_round(candidate=..., incumbent=..., env=..., accepted=..., reference=(prompt, env))`
  after every decision, where `reference` is what your gate compared the candidate with;
- `rec.add_labels(prompt, env, labels, rerun=True)` for a second evaluation of a reference,
  which is what lets an audit tell a stale reference from a fresh one;
- `rec.save("run.json")`.

An environment is built with `Environment.make(model=..., temperature=..., scorer=...)`. Its
fingerprint changes when any of those settings change. In the toy loop the scorer is replaced
before round 3 while the stored reference stays as it was, and the audit printed at the end
lists the candidates that were accepted because of that.

## Run the built-in loop against a local model

Any server with an OpenAI-compatible `/v1/chat/completions` endpoint works: Ollama, vLLM,
LM Studio, llama.cpp or a hosted API. With Ollama running and a model pulled
(`ollama pull llama3.2`):

    driftaudit run --backend openai --base-url http://localhost:11434/v1 --model llama3.2 \
        --n-dev 50 --n-eval 100 --rounds 6 --concurrency 2 \
        --schedule "0:greedy/strict,2:sample@0.2/strict,4:sample@0.2/lenient" \
        -o ollama-run.json

This runs the bundled GSM8K sample; `--task FILE.jsonl` takes your own questions, one
`{"question": ..., "answer": ...}` object per line. The endpoint has to accept `temperature`,
`max_tokens` and, for the sampled rounds, `seed`. A run of this size sends a few thousand
short requests. Every generation is saved in `ollama-run.cache.jsonl` as it arrives, so the
same command resumes after an interruption instead of starting over.

A hosted endpoint needs a key in `DRIFTAUDIT_API_KEY` or `OPENAI_API_KEY`. It is sent in the
Authorization header and is not written to the cache, the run log or the terminal.

## Open the result in the workbench

    driftaudit audit ollama-run.json
    driftaudit view ollama-run.json
    driftaudit report ollama-run.json -o report.html

`audit` prints the policy table and each false accept in the terminal. `view` serves the
workbench on this machine only and opens it on your run; the raw outputs file written next to
the run log is picked up, so every item can be read with what each scorer made of it.
`report` writes one HTML file with the run inside it, which opens from disk and can be sent
to someone who does not have the tool installed.
