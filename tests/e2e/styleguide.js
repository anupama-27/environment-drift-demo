(function (root) {
  "use strict";
  var DA = root.DA, ui = DA.ui, html = ui.html, fmt = ui.fmt;
  var BASE = "../../";
  var COLOURS = ["paper", "bench", "bench-2", "ink", "graphite", "steel", "rule", "signal-blue", "signal-blue-tint",
    "signal-yellow", "signal-yellow-tint", "signal-red", "signal-red-tint"];

  function json(path) {
    return fetch(BASE + path).then(function (r) { return r.json(); });
  }

  function section(title, body) {
    return html`<section><h2>${title}</h2>${body}</section>`;
  }

  function draw(replay, pooled, runs) {
    var run = runs[4], audit = DA.engine.audit(run, {}), study = DA.engine.study(runs, {});
    var frozen = audit.policies.frozen, names = ui.envNames(audit);
    var decision = frozen.decisions[9];
    var gain = {
      rounds: replay.rounds.map(function (r) {
        return { round: r.round, env: r.env, stored: r.stale_net_pp, rerun: r.fresh_net_pp, mark: r.false_accept ? "false-accept" : r.accepted ? "improved" : null };
      }),
      flags: replay.meta.changes.map(function (c) { return { round: c.round, name: names[c.env] }; }),
      first: names.E1, selected: 9
    };
    var ages = Object.keys(study.age.by_env).map(function (env, i) {
      return { label: names[env], plain: i === 0, points: study.age.by_env[env].map(function (p) { return { x: p.age, mean: p.mean, lo: p.lo, hi: p.hi }; }) };
    });

    ui.mount(document.getElementById("sg-body"), html`
      ${section("Colour tokens", html`<div class="sg__swatches">${COLOURS.map(function (c) {
        return html`<div class="sg__swatch"><div class="sg__chip" data-token="${c}"></div>--${c}</div>`;
      })}</div>`)}
      ${section("Text styles", html`
        <p class="t-display">Display: this run made 8 promotions</p>
        <p class="t-title">Title: Barlow Semi Condensed 600, 24 on 32</p>
        <p class="t-heading">Heading: Barlow Semi Condensed 600, 18 on 24</p>
        <p class="t-label">Label: table heads and chart labels, 14 on 20</p>
        <p class="t-body">Body: Barlow 400, 16 on 24. Numbers in tables are tabular: <span class="num">4,411 and 6,611</span>.</p>
        <p class="t-small">Small: Barlow 400, 14 on 20.</p>
        <p class="t-mono">Mono, literal strings only: ${audit.environments[0].fingerprint}</p>`)}
      ${section("Ruler", html`<div class="sg__bench">${ui.ruler(ui.rulerModel(audit, "frozen", 9))}${ui.rulerLegend()}</div>
        <div class="sg__bench">${ui.ruler(ui.rulerModel(audit, null))}</div>`)}
      ${section("Plate: round 9 under the frozen policy", ui.plate({ cells: DA.engine.itemCells(run, decision), key: "sg-plate" }))}
      ${section("Controls", html`
        <div class="cluster"><button type="button" class="btn btn--primary">Open run log</button><button type="button" class="btn">Copy command</button>
          <button type="button" class="btn" disabled>Disabled</button><button type="button" class="btn btn--small">Small</button><button type="button" class="linklike">Link-like button</button></div>
        <div class="cluster">${ui.policySwitcher(audit.policies, "frozen")}</div>
        <div class="cluster">${ui.select({ name: "sg-run", label: "Run", value: "b", options: [{ value: "a", label: "Seed 1" }, { value: "b", label: "Seed 5" }] })}
          <label class="check"><input type="checkbox" checked> Dim cells that did not change</label>
          <label class="field"><span class="field__label">Margin</span><input class="input" type="number" value="0"></label></div>
        <div class="sg__bench">${ui.tabs({ name: "sg-nav", label: "Example views", value: "summary", items: [{ id: "summary", label: "Summary", href: "#sg" }, { id: "rounds", label: "Rounds", href: "#sg" }] })}</div>
        ${ui.tabs({ name: "sg-tabs", label: "Example tabs", plain: true, value: "one", items: [{ id: "one", label: "Stored reading" }, { id: "two", label: "Rerun reading" }] })}
        <div class="cluster">${ui.tag("measured")}${ui.tag("synthetic", "warning")}${ui.tag("false accept", "error")}${ui.tag("rerun", "info")}${ui.tag("not scheduled", "quiet")}</div>`)}
      ${section("Readouts", ui.readouts([
        { label: "Drift inflation", value: fmt.ppOf(frozen.inflation), unit: "pp", note: "Mean over 11 decisions." },
        { label: "False accepts", value: fmt.count(frozen.false_accepts, frozen.accepted), state: "alert", note: "3 stale reference, 1 same environment." },
        { label: "False rejects", value: "0", note: "No rejected candidate would have raised accuracy." },
        { label: "Model calls", value: fmt.int(frozen.total_calls), note: "Estimated. No reference reruns." }
      ]))}
      ${section("Notices", html`
        ${ui.notice({ kind: "info", title: "Rerun labels found", body: "Both readings of the reference are available for every round." })}
        ${ui.notice({ kind: "warning", title: "Labels are missing", body: "The per-batch policy needs rerun labels for p3 under E2." })}
        ${ui.notice({ kind: "error", title: "notes.json is not a run log this page can read", body: "This file is not a run log: it has no \"schema\" field and is not a legacy run file. The run you had open is unchanged.", dismiss: true })}
        ${ui.notice({ kind: "quiet", body: "The Rounds view is not part of this build yet." })}
        <p class="empty">No run log open. Drop one here or choose Open run log.</p>`)}
      ${section("Ledger, key-value rows, code and disclosure", html`
        ${ui.ledger({
          key: "sg-ledger", caption: "Decisions under the frozen policy", rows: frozen.decisions,
          rowClass: function (d) { return d.false_accept ? "is-error" : d.round === 9 ? "is-selected" : null; },
          columns: [
            { label: "Round", key: "round", tight: true },
            { label: "Environment", cell: function (d) { return names[d.env]; } },
            { label: "Decision", cell: function (d) { return html`${ui.mark(ui.markOf(d))}`; } },
            { label: "Stored", num: true, cell: function (d) { return d.wins + " to " + d.losses; } },
            { label: "Rerun", num: true, cell: function (d) { return d.rerun_wins + " to " + d.rerun_losses; } },
            { label: "Drift inflation, pp", num: true, cell: function (d) { return fmt.ppOf(d.inflation); } },
            { label: "Accuracy change, pp", num: true, cell: function (d) { return fmt.pp(d.delta_pp, 1); } }
          ]
        })}
        ${ui.ledger({ key: "sg-empty", columns: [{ label: "Round", key: "round" }, { label: "Cause", key: "cause" }], rows: [], empty: "No false accepts under this policy." })}
        ${ui.kv([{ key: "Model", value: audit.run.model }, { key: "Fingerprint", value: audit.environments[2].fingerprint, mono: true, copy: true }])}
        ${ui.code("driftaudit audit run.json --policy frozen --format md", { label: "Copy command", done: "Command copied" })}
        ${ui.disclosure({ key: "sg-disclosure", summary: "Starting prompt", body: run.prompts[run.snapshots[0].prompt] })}`)}
      ${section("Chart: net gain per round (replay/seed5.json)", DA.charts.netGain(gain))}
      ${section("Chart: intervals (drift inflation at reference age 3, replay/all_seeds.json)", DA.charts.intervals(["E1", "E2", "E3", "E4"].map(function (e) {
        var r = pooled.inflation[e];
        return { label: names[e], mean: r.mean, lo: r.lo, hi: r.hi, values: r.per_seed };
      }), { caption: "Drift inflation by environment, percentage points" }))}
      ${section("Chart: mean by reference age", DA.charts.ageLines(ages, { caption: "Drift inflation by reference age, percentage points" }))}
      ${section("Chart: bars (final accuracy, mean and standard deviation)", DA.charts.bars(["P1", "P2", "P3"].map(function (p) {
        var r = pooled.policies[p];
        return { label: r.name, value: 100 * r.final_acc[0], sd: 100 * r.final_acc[1], tone: "steel", text: fmt.meanSd(100 * r.final_acc[0], 100 * r.final_acc[1], 1) + "%" };
      }), { max: 100, caption: "Final accuracy by policy" }))}
      ${section("Drop overlay and toast", html`<div class="cluster"><button type="button" class="btn" data-sg="toast">Show a toast</button><button type="button" class="btn" data-sg="error">Show an error toast</button></div>`)}`);

    Array.prototype.forEach.call(document.querySelectorAll("[data-token]"), function (chip) {
      chip.style.background = "var(--" + chip.getAttribute("data-token") + ")";
    });
    ui.bind(document.getElementById("sg"));
    document.getElementById("sg").addEventListener("click", function (event) {
      var kind = event.target.getAttribute && event.target.getAttribute("data-sg");
      if (kind === "toast") ui.toast("Opened my-run.json.");
      if (kind === "error") ui.toast("Copying was blocked by the browser. Select the text and copy it by hand.", { kind: "error" });
    });
    ui.on(document.getElementById("sg"), "cell", function (detail) {
      ui.toast("Cell handler called for item " + detail.index + ".");
    });
  }

  Promise.all([json("replay/seed5.json"), json("replay/all_seeds.json")].concat([1, 2, 3, 4, 5].map(function (n) {
    return json("toolkit/runs/run_seed" + n + "_hf_Qwen2.5-1.5B-Instruct_n200_r11.json").then(DA.schema.load);
  }))).then(function (all) {
    draw(all[0], all[1], all.slice(2));
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
