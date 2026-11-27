(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html;

  DA.views = DA.views || {};

  var REPO = "https://github.com/anupama-27/environment-drift-demo";

  var RECORD = [
    "import driftaudit as da",
    "",
    "strict = da.Environment.make(name=\"Strict scorer\", model=\"my-model\", temperature=0,",
    "                             scorer=da.get_scorer(\"strict\"))",
    "lenient = da.Environment.make(name=\"Lenient scorer\", model=\"my-model\", temperature=0,",
    "                              scorer=da.get_scorer(\"lenient\"))",
    "rec = da.Recorder(task=\"my-task\", n_items=4, model=\"my-model\")",
    "",
    "# Round 0: the reference is measured, a candidate is compared with it and rejected.",
    "rec.add_labels(\"Solve it.\", strict, [1, 0, 1, 0])",
    "rec.add_labels(\"Solve it step by step.\", strict, [1, 0, 0, 0])",
    "rec.add_round(candidate=\"Solve it step by step.\", incumbent=\"Solve it.\", env=strict,",
    "              accepted=False, reference=(\"Solve it.\", strict))",
    "",
    "# Round 1: the scorer has changed, but the gate still uses the stored reference.",
    "rec.add_labels(\"Check each step.\", lenient, [1, 1, 1, 0])",
    "rec.add_round(candidate=\"Check each step.\", incumbent=\"Solve it.\", env=lenient,",
    "              accepted=True, reference=(\"Solve it.\", strict))",
    "",
    "# The reference measured again under the new scorer, so an audit can compare.",
    "rec.add_labels(\"Solve it.\", lenient, [1, 1, 1, 0])",
    "rec.add_labels(\"Solve it.\", lenient, [1, 1, 1, 0], rerun=True)",
    "rec.save(\"my-run.json\")"
  ].join("\n");

  var TASK_LINE = "{\"question\": \"A pen costs 3 dollars. How much do 4 pens cost?\", \"answer\": 12}";

  function cmd(text, key) {
    return ui.code(text, { label: "Copy command", done: "Command copied", key: key });
  }

  function block(title, parts) {
    return html`<section class="install-section">
      <h2>${title}</h2>
      ${parts}
    </section>`;
  }

  function p(text) {
    return html`<p class="install-text">${text}</p>`;
  }

  function render() {
    return html`<div class="install stack stack--6">
      <header class="install-head stack stack--1">
        <h1>Install</h1>
        ${p("DriftAudit is a Python package with a command line and the workbench on this site. Every command below is part of it.")}
      </header>

      ${block("Install", [
        cmd("pip install \"git+https://github.com/anupama-27/environment-drift-demo\"", "install-pip"),
        p(html`Needs Python 3.9 or newer and installs no other dependencies. The package is not on PyPI, so it is installed from the repository. Afterwards the <code>driftaudit</code> command is on your path; <code>driftaudit --help</code> lists its commands.`)
      ])}

      ${block("Open the workbench locally", [
        cmd("driftaudit demo", "install-demo"),
        p(html`Serves the same pages as this site from your machine, works offline, and opens them in your browser on the five bundled GSM8K runs. It listens on this machine only; <code>--port</code> picks another port and <code>--no-open</code> leaves the browser closed.`)
      ])}

      ${block("Try a full loop without a model", [
        cmd("driftaudit run", "install-run"),
        p(html`Runs the built-in self-improvement loop on a sample of GSM8K against a simulator, the mock backend, and writes <code>driftaudit-run.json</code>. Its numbers are synthetic: the run log says so, and the command line and the workbench tag it ${ui.tag("synthetic", "warning")} wherever it is shown.`),
        cmd("driftaudit audit driftaudit-run.json", "install-audit"),
        p("Replays the refresh policies on the run log and prints a table of promotions, false accepts, false rejects, final accuracy and model calls for each, followed by every false accept and its cause."),
        cmd("driftaudit view driftaudit-run.json", "install-view"),
        p("Opens the workbench on that run log, served from your machine.")
      ])}

      ${block("Run it on a real model", [
        cmd("pip install \"driftaudit[hf] @ git+https://github.com/anupama-27/environment-drift-demo\"", "install-hf"),
        p("With DriftAudit installed as above, this adds torch, transformers and accelerate, which the Hugging Face backend needs."),
        cmd("driftaudit run --backend hf --model Qwen/Qwen2.5-1.5B-Instruct", "install-run-hf"),
        p("Runs the loop on the model the paper used. Generations are cached in a file next to the run log, so the same command resumes after an interruption."),
        cmd("driftaudit run --backend openai --base-url http://localhost:11434/v1 --model qwen2.5:1.5b", "install-run-openai"),
        p(html`Any OpenAI-compatible endpoint works; this one is Ollama on your machine. A hosted endpoint reads its key from <code>DRIFTAUDIT_API_KEY</code> or <code>OPENAI_API_KEY</code>, and the key is not written to the cache or the run log.`),
        cmd("driftaudit run --task my-task.jsonl", "install-run-task"),
        p(html`Runs the loop on your own questions instead of GSM8K. The file holds one JSON object per line with <code>question</code> and <code>answer</code>:`),
        ui.code(TASK_LINE, { label: "Copy line", done: "Line copied", key: "install-task-line" }),
        cmd("driftaudit run --schedule \"0:greedy/strict,4:sample@0.2/strict,8:sample@0.2/lenient\"", "install-run-schedule"),
        p(html`The schedule says when the environment changes, as <code>ROUND:DECODING/SCORER</code> entries separated by commas. This is the default: greedy decoding and the strict scorer from round 0, sampling at temperature 0.2 from round 4, and the lenient scorer from round 8. Decoding is <code>greedy</code> or <code>sample@T</code>; the scorers are <code>strict</code>, <code>lenient</code>, <code>exact</code> and <code>exact-normalized</code>.`)
      ])}

      ${block("Record a loop you already have", [
        p(html`If your loop already exists, record what it measured and audit that. Every evaluation goes in with <code>add_labels</code>, one 0/1 label per evaluation item in a fixed order; every decision goes in with <code>add_round</code>, together with the reference the gate compared against; a second evaluation of a reference goes in with <code>rerun=True</code>; <code>save</code> writes the run log. This snippet runs as shown and writes <code>my-run.json</code>:`),
        ui.code(RECORD, { label: "Copy code", done: "Code copied", key: "install-record" }),
        p(html`Then run <code>driftaudit audit my-run.json</code>. A longer example that runs a toy loop end to end is <a href="${REPO + "/blob/main/examples/record_your_own_loop.py"}">examples/record_your_own_loop.py</a>.`)
      ])}

      ${block("The run log", [
        p("A run log is one JSON file with everything an audit needs and nothing that needs a model: the environments in force, each with a fingerprint of the settings that change outputs or grades; the prompts the loop tried; the rounds, with each candidate, its incumbent and the decision; and one right-or-wrong label per evaluation item for each prompt under each environment, for the stored pass and, where it was measured again, the rerun pass."),
        p(html`The fields are described in <a href="${REPO + "/blob/main/docs/run-log-format.md"}">docs/run-log-format.md</a>, and the <a href="${REPO + "#readme"}">README on GitHub</a> covers the rest of the tool.`)
      ])}

      ${block("Open your own run log in the browser", [
        p(html`Drag the file onto the <a href="#/">workbench</a>, or use Open run log above its views. The file is read in your browser tab and nothing is uploaded.`)
      ])}
    </div>`;
  }

  DA.views.install = {
    id: "install",
    title: "Install",
    render: render
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
