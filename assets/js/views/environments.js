(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  var EXAMPLES = ["\\boxed{18}", "\\boxed{70,000}", "\\boxed{\\$15}", "\\boxed{540 \\text{ meters}}", "The answer is 1,200."];
  var RULES = {
    v1: "read the same way as the strict scorer",
    boxed_loose: "the number in the last \\boxed{}, ignoring commas, dollar signs and units",
    hashes_loose: "the number after ####, ignoring commas and dollar signs",
    bold: "the number at the start of a bold phrase",
    answer_is: "the number after \"answer is\"",
    last_number: "the last number anywhere in the text",
    none: "no number anywhere in the text"
  };
  var bench = { text: "", gold: "" };
  var memo = null;

  function given(x) {
    return x !== null && x !== undefined;
  }

  // In a study there is no audit of one run; the versions come from the first run.
  function environmentsOf(ctx) {
    var options = {}, run;
    if (ctx.audit) return ctx.audit.environments;
    run = ctx.runs[0];
    if (!run) return [];
    Object.keys(ctx.state.options).forEach(function (k) {
      if (given(ctx.state.options[k])) options[k] = ctx.state.options[k];
    });
    options.policies = ["frozen"];
    if (!memo || memo.run !== run || memo.key !== JSON.stringify(options)) {
      memo = { run: run, key: JSON.stringify(options), result: DA.engine.audit(run, options).environments };
    }
    return memo.result;
  }

  function scorerName(e) {
    return e.detail && e.detail.scorer_name ? e.detail.scorer_name : e.scorer;
  }

  function name(e) {
    return e.name || e.id;
  }

  function differences(a, b) {
    var out = [];
    if (a.decoding !== b.decoding) out.push("decoding " + a.decoding + " to " + b.decoding);
    if (a.scorer !== b.scorer) out.push("scorer " + scorerName(a) + " to " + scorerName(b));
    if (!out.length && a.fingerprint !== b.fingerprint) out.push("fingerprint only");
    return out;
  }

  function changeText(row, first) {
    var diff;
    if (!row.prev) {
      if (row.env.rounds.length) return "first version";
      diff = first ? differences(first, row.env) : [];
      return "not scheduled" + (diff.length ? "; against " + name(first) + ": " + diff.join(", ") : "");
    }
    diff = differences(row.prev, row.env);
    return diff.length ? diff.join(", ") : "nothing";
  }

  function versions(ctx, envs) {
    var previous = null, first = null, rows, runs = ctx.mode === "study" ? ctx.runs : [], same;
    rows = envs.map(function (e) {
      var row = { env: e, prev: e.rounds.length ? previous : null };
      if (e.rounds.length) {
        if (!first) first = e;
        previous = e;
      }
      return row;
    });
    same = runs.every(function (r) {
      return envs.every(function (e) { return r.environments[e.id] && r.environments[e.id].fingerprint === e.fingerprint; });
    });
    return html`<section class="environments__section">
      <h2>Environment versions</h2>
      <p class="environments__note">${ctx.mode === "study"
        ? (same ? "As defined in the first run; all " + runs.length + " runs define the same versions with the same fingerprints." : "As defined in the first run. The other runs do not all share these fingerprints; pick one run to see its own.")
        : "One row per version, in the order the schedule uses them."} The last column says what changed from the previous scheduled version.</p>
      ${ui.ledger({
        key: "environments-versions", caption: "Environment versions",
        rows: rows,
        rowAttrs: function (r) { return { "data-env-row": r.env.id }; },
        columns: [
          { label: "Environment", head: true, cell: function (r) { return r.env.name && r.env.name !== r.env.id ? html`${r.env.name} <span class="muted">${r.env.id}</span>` : r.env.id; } },
          { label: "Rounds in force", cell: function (r) { return r.env.rounds.length ? fmt.rounds(r.env.rounds) : html`<span class="muted">not scheduled</span>`; } },
          { label: "Decoding", mono: true, cell: function (r) { return r.env.decoding; } },
          { label: "Scorer", cell: function (r) { return scorerName(r.env) !== r.env.scorer ? html`${scorerName(r.env)} <span class="muted">${r.env.scorer}</span>` : r.env.scorer; } },
          { label: "Fingerprint", cell: function (r) { return ui.copyable(r.env.fingerprint, { label: "Copy", done: "Copied", key: "environments-fp-" + r.env.id, ariaLabel: "Copy the fingerprint of " + r.env.id }); } },
          { label: "Changed from the version before", className: function (r) { return r.prev && differences(r.prev, r.env).length ? "is-changed" : ""; }, cell: function (r) { return changeText(r, first); } }
        ]
      })}
    </section>`;
  }

  function flips(ctx, envs) {
    var list = ctx.mode === "study" ? ctx.study.scorer_flips : ctx.audit.scorer_flips, byId = {}, verdicts;
    envs.forEach(function (e) { byId[e.id] = e; });
    verdicts = ctx.mode === "study" ? ctx.study.verdict_flips : null;
    function env(id) {
      return byId[id] || { id: id, scorer: id, decoding: "", detail: {} };
    }
    return html`<section class="environments__section">
      <h2>Labels changed by a scorer change</h2>
      <p class="environments__note">Pairs of environments with the same decoding and different scorers read the same saved outputs, so any label that differs between them was changed by the scorer alone.${ctx.mode === "study" ? " Counts are pooled over the " + ctx.study.n_runs + " runs." : ""}</p>
      ${list.length ? html`<ul class="environments__flips">${list.map(function (f) {
        var a = env(f.from_env), b = env(f.to_env);
        return html`<li data-flip="${f.from_env + ":" + f.to_env}"><span class="num">${fmt.count(f.wrong_to_right, f.items)}</span> saved labels go from wrong to right when the ${scorerName(b)} scorer reads the outputs that ${name(a)} scored with the ${scorerName(a)} scorer (decoding <span class="t-mono">${a.decoding}</span>, ${fmt.plural(f.prompts, "prompt")}); ${f.right_to_wrong ? html`<span class="num">${fmt.int(f.right_to_wrong)}</span> go the other way` : "none go the other way"}.</li>`;
      })}</ul>` : html`<p class="empty">No two environments share their decoding and differ in scorer, so no label can be traced to a scorer change alone.</p>`}
      ${verdicts && verdicts.n ? html`<p class="environments__after">Between ${name(env(list[0].from_env))} and ${name(env(list[0].to_env))}, ${fmt.count(verdicts.flipped, verdicts.n)} candidates change their verdict against their parent (improved, no change or worse).</p>` : ""}
    </section>`;
  }

  function show(value) {
    if (value === null) return html`<span class="muted">nothing</span>`;
    if (!isFinite(value)) return "a value that is not a finite number";
    return html`<span class="t-mono">${String(value)}</span>`;
  }

  function match(value, gold) {
    var g;
    if (!bench.gold.trim()) return html`<span class="muted">no gold answer given</span>`;
    g = DA.scorers.toFloat(bench.gold.trim());
    if (g === null || !isFinite(g)) return html`<span class="muted">the gold answer is not a number</span>`;
    if (value === null) return "no, nothing was read";
    return DA.scorers.isCorrect(value, g) ? "yes" : "no";
  }

  function result() {
    var text = bench.text, strict = DA.scorers.strict(text), lenient = DA.scorers.lenient(text), rule = DA.scorers.lenientRule(text);
    var rows = [
      { id: "strict", name: DA.scorers.get("strict").name, value: strict, rule: "a plain number in the last \\boxed{}, or after #### at the end of a line" },
      { id: "lenient", name: DA.scorers.get("lenient").name, value: lenient, rule: RULES[rule] || rule }
    ];
    return ui.ledger({
      key: "environments-bench-table", caption: "What each scorer reads from the pasted output",
      rows: rows,
      rowAttrs: function (r) { return { "data-scorer": r.id }; },
      columns: [
        { label: "Scorer", head: true, cell: function (r) { return r.name; } },
        { label: "Reads", cell: function (r) { return show(r.value); } },
        { label: "Matches the gold answer", cell: function (r) { return match(r.value, bench.gold); } },
        { label: "Rule that fired", cell: function (r) { return r.id === "lenient" && !text ? html`<span class="muted">nothing pasted yet</span>` : r.rule; } }
      ]
    });
  }

  function scorerBench() {
    return html`<section class="environments__section environments__bench" aria-labelledby="environments-bench">
      <h2 id="environments-bench">Scorer bench</h2>
      <p class="environments__note">See how the two numeric scorers read one model output. What you type here stays in this page: it is not stored or sent anywhere.</p>
      <div class="grid environments__bench-grid">
        <div class="span-6 stack stack--1">
          <label class="field field--stack environments__field"><span class="field__label">Paste a model output</span>
            <textarea class="textarea" rows="5" spellcheck="false" data-bench-text data-key="environments-bench-text">${bench.text}</textarea></label>
          <div class="cluster environments__examples" role="group" aria-label="Example outputs">
            ${EXAMPLES.map(function (x, i) {
              return html`<button type="button" class="btn btn--small environments__example" data-bench-example="${i}" data-key="${"environments-example-" + i}">${x}</button>`;
            })}
          </div>
          <label class="field field--stack environments__gold"><span class="field__label">Gold answer, optional</span>
            <input class="input" type="text" inputmode="decimal" autocomplete="off" data-bench-gold data-key="environments-bench-gold" value="${bench.gold}"></label>
        </div>
        <div class="span-6" data-bench-result aria-live="polite">${result()}</div>
      </div>
    </section>`;
  }

  function render(ctx) {
    var envs = environmentsOf(ctx);
    return html`<div class="environments">
      <h1>Environments</h1>
      <p class="environments__lede">An environment is the decoding and the answer scorer in force at a round, recorded with a fingerprint. ${envs.length === 1 ? "This run defines one environment." : "This " + (ctx.mode === "study" ? "group" : "run") + " defines " + envs.length + " environments, " + envs.filter(function (e) { return e.rounds.length; }).length + " of them scheduled."}</p>
      ${versions(ctx, envs)}
      ${flips(ctx, envs)}
      ${scorerBench()}
    </div>`;
  }

  function bind(rootEl) {
    var out = rootEl.querySelector("[data-bench-result]"), text = rootEl.querySelector("[data-bench-text]");
    if (!out) return;
    function update() {
      ui.mount(out, result());
      ui.bind(out);
    }
    rootEl.addEventListener("input", function (event) {
      if (event.target.hasAttribute("data-bench-text")) bench.text = event.target.value;
      else if (event.target.hasAttribute("data-bench-gold")) bench.gold = event.target.value;
      else return;
      update();
    });
    rootEl.addEventListener("click", function (event) {
      var el = event.target.closest ? event.target.closest("[data-bench-example]") : null;
      if (!el) return;
      bench.text = EXAMPLES[Number(el.getAttribute("data-bench-example"))];
      text.value = bench.text;
      update();
    });
  }

  DA.views.environments = { id: "environments", title: "Environments", render: render, bind: bind };
})(typeof globalThis !== "undefined" ? globalThis : this);
