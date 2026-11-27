(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  var INSTALL = "pip install \"git+https://github.com/anupama-27/environment-drift-demo\"";
  var CORE = ["frozen", "stored_incumbent", "per_batch", "env_triggered", "periodic", "as_run"];

  function given(x) {
    return x !== null && x !== undefined;
  }

  function safeName(text) {
    return String(text || "run").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "run";
  }

  function shellWord(text) {
    return /^[A-Za-z0-9._\/:,=+-]+$/.test(text) ? text : "'" + String(text).replace(/'/g, "'\\''") + "'";
  }

  /* Where each run log lives, for the command line ------------------------------------ */

  function entries(ctx) {
    var group = DA.library.group(), sel = ctx.state.selection.run;
    if (!group) return [];
    return group.runs.filter(function (e) { return sel === "*" || e.id === sel; });
  }

  function pathOf(entry) {
    if (entry.url && /^data\//.test(entry.url)) return entry.url;
    return entry.file || entry.label || entry.id;
  }

  function scheduleSpec(schedule) {
    return Object.keys(schedule).map(Number).sort(function (a, b) { return a - b; })
      .map(function (k) { return k + ":" + schedule[String(k)]; }).join(",");
  }

  function command(ctx) {
    var o = ctx.state.options, parts = ["driftaudit", "audit"], list = entries(ctx);
    list.forEach(function (e) { parts.push(shellWord(pathOf(e))); });
    parts.push("--policy", ctx.policyId);
    if (o.schedule) parts.push("--schedule", shellWord(scheduleSpec(o.schedule)));
    if (o.stored_scoring === "rescore") parts.push("--stored-scoring", "rescore");
    if (o.margin) parts.push("--margin", String(o.margin));
    if (o.periodic_k !== 3 || ctx.policyId === "periodic") parts.push("--periodic-k", String(o.periodic_k));
    return parts.join(" ");
  }

  function optionWords(ctx) {
    var o = ctx.state.options, out = [];
    if (o.schedule) out.push("the schedule " + scheduleSpec(o.schedule) + " in place of the recorded one");
    if (o.stored_scoring === "rescore") out.push("stored references re-scored with the current scorer");
    if (o.margin) out.push("a margin of " + fmt.plural(o.margin, "item"));
    if (o.periodic_k !== 3 || ctx.policyId === "periodic") out.push("a rerun every " + fmt.plural(o.periodic_k, "round"));
    return out;
  }

  /* Markdown -------------------------------------------------------------------------- */

  function cell(text) {
    return String(given(text) ? text : "").replace(/\|/g, "\\|").replace(/[\r\n]+/g, " ");
  }

  function table(head, rows) {
    return ["| " + head.map(cell).join(" | ") + " |", "|" + head.map(function (h, i) { return i ? " ---: |" : " --- |"; }).join("")]
      .concat(rows.map(function (r) { return "| " + r.map(cell).join(" | ") + " |"; })).join("\n");
  }

  function markdown(ctx) {
    var a = ctx.audit, o = a.options, k = ctx.state.options.periodic_k, names = ui.envNames(a), p = ctx.policy;
    var model = a.run.model && a.run.model.id ? a.run.model.id : "model not recorded";
    var lines = [
      "# DriftAudit audit of " + (a.run.id || "an unnamed run"),
      "",
      "Source: " + fmt.source(a.run.source) + ". Model: " + model + ". Task: " + ((a.run.task && a.run.task.name) || "unnamed") +
        ", " + fmt.plural(a.run.n_items, "item") + ", " + fmt.plural(a.run.n_candidates, "candidate") + ". Tool: " + a.tool.name + " " + a.tool.version + ".",
      "",
      "Options: " + (o.schedule_overridden ? "schedule " + scheduleSpec(o.schedule) + " (a counterfactual, not the recorded one)" : "schedule as recorded") +
        "; stored references " + (o.stored_scoring === "rescore" ? "re-scored with the current scorer" : "read as recorded") +
        "; margin " + o.margin + "; periodic policy reruns every " + fmt.plural(o.periodic_k, "round") + ".",
      "",
      "## Environments",
      "",
      table(["Environment", "Rounds", "Decoding", "Scorer", "Fingerprint"], a.environments.map(function (e) {
        return [(e.name ? e.name + " (" + e.id + ")" : e.id), e.rounds.length ? fmt.rounds(e.rounds) : "not scheduled", e.decoding,
          e.detail && e.detail.scorer_name ? e.detail.scorer_name + " (" + e.scorer + ")" : e.scorer, e.fingerprint];
      })),
      "",
      "## Policies",
      "",
      "Every policy is replayed on the recorded candidates; nothing is regenerated. Model calls are estimates.",
      "",
      table(["Policy", "Promotions", "False accepts", "False rejects", "Final accuracy", "Reference reruns", "Model calls"], CORE.filter(function (id) {
        if (!a.policies[id]) return false;
        if (id === "as_run") return !DA.library.hidesAsRun(a.policies);
        return id !== "periodic" || DA.views.policies.showsPeriodic();
      }).map(function (id) {
        var q = a.policies[id];
        if (q.available === false) return [fmt.policy(id, k), "not available", "", "", "", "", ""];
        return [fmt.policy(id, k), fmt.int(q.accepted), fmt.count(q.false_accepts, q.accepted), fmt.count(q.false_rejects, q.decisions.length - q.accepted),
          fmt.pct(q.final_acc), fmt.int(q.refreshes), fmt.int(q.total_calls)];
      })),
      "",
      "## Decisions under " + fmt.policyPhrase(ctx.policyId, k),
      ""
    ];
    if (!p || p.available === false) {
      lines.push("This policy cannot be replayed on this run: the run log lacks " + (p ? fmt.plural(p.missing_count, "label set") + " it needs" : "what it needs") + ".");
    } else {
      lines.push(table(["Round", "Environment", "Candidate", "Decision", "Stored reference, wins to losses", "Rerun reference, wins to losses", "Accuracy", "Change, pp", "Verdict"],
        p.decisions.map(function (d) {
          var row = a.rounds.filter(function (r) { return r.round === d.round; })[0];
          return [d.round, names[d.env] || d.env, row && row.candidate_id ? row.candidate_id : fmt.prompt(ctx.run, d.candidate), d.accepted ? "promoted" : "kept",
            given(d.wins) ? d.wins + " to " + d.losses : "not recorded",
            given(d.rerun_wins) ? d.rerun_wins + " to " + d.rerun_losses : "no rerun saved",
            fmt.pct(d.inc_acc) + " to " + fmt.pct(d.cand_acc), fmt.pp(d.delta_pp),
            d.false_accept ? "false accept, " + fmt.cause(d.cause) : d.false_reject ? "false reject" : "correct"];
        })));
    }
    return lines.join("\n") + "\n";
  }

  /* Files ------------------------------------------------------------------------------ */

  function files(ctx) {
    var group = DA.library.group(), study = ctx.study, base, out = {};
    if (ctx.audit) {
      base = safeName(ctx.audit.run.id) + "-audit-" + safeName(ctx.policyId);
      out["audit-json"] = { name: base + ".json", type: "application/json", build: function () { return JSON.stringify(ctx.audit, null, 2) + "\n"; } };
      out["audit-md"] = { name: base + ".md", type: "text/markdown", build: function () { return markdown(ctx); } };
    }
    if (study) {
      out["study-json"] = { name: safeName(group ? group.id : "runs") + "-study.json", type: "application/json", build: function () { return JSON.stringify(study, null, 2) + "\n"; } };
    }
    return out;
  }

  function render(ctx) {
    var list = files(ctx), group = DA.library.group(), opened = entries(ctx).some(function (e) { return !(e.url && /^data\//.test(e.url)); });
    var words = optionWords(ctx), n = group ? group.runs.length : 0;
    function button(id, label, primary) {
      return html`<button type="button" class="btn${primary ? " btn--primary" : ""}" data-export="${id}" data-key="${"export-" + id}">${label}</button>`;
    }
    return html`<div class="export">
      <h1>Export</h1>
      <p class="export__lede">The files are built in this browser from the audit on screen, with the options in force. Nothing is uploaded.</p>
      <section class="export__section">
        <h2>Download</h2>
        <div class="export__files">
          ${list["audit-json"] ? html`<div class="export__file">
            ${button("audit-json", "Download audit (JSON)", true)}
            <p class="export__note">Every policy and every decision, as <span class="t-mono export__name">${list["audit-json"].name}</span>.</p>
          </div>
          <div class="export__file">
            ${button("audit-md", "Download audit (Markdown)")}
            <p class="export__note">The run, its environments, the policy table and the decisions under ${fmt.policyPhrase(ctx.policyId, ctx.state.options.periodic_k)}, as <span class="t-mono export__name">${list["audit-md"].name}</span>.</p>
          </div>` : html`<p class="export__note export__file">Pick one run to download its audit.</p>`}
          ${list["study-json"] ? html`<div class="export__file">
            ${button("study-json", "Download study (JSON)", !list["audit-json"])}
            <p class="export__note">All ${fmt.plural(ctx.study.n_runs, "run")} of the group pooled, with the tests and the drift probe, as <span class="t-mono export__name">${list["study-json"].name}</span>.</p>
          </div>` : n >= 2 ? html`<p class="export__note export__file">The study is ready once every run of the group has loaded.</p>` : ""}
        </div>
      </section>
      <section class="export__section">
        <h2>Reproduce on the command line</h2>
        <p class="export__note">Install the package, then run the audit${ctx.mode === "study" ? " of all the runs; several runs print a study" : ""}. ${words.length ? "The command carries " + fmt.list(words) + "." : "No option differs from the defaults, so the command needs only the policy."}</p>
        <div class="export__commands stack stack--1">
          ${ui.code(INSTALL, { label: "Copy", done: "Copied", key: "export-install" })}
          <div data-command>${ui.code(command(ctx), { label: "Copy command", done: "Command copied", key: "export-command" })}</div>
        </div>
        <p class="export__note">${opened
          ? "Run it in the folder that holds the run log you opened."
          : "Run it from a clone of the repository; the bundled run logs are under data/runs."}</p>
      </section>
    </div>`;
  }

  function bind(rootEl, ctx) {
    var list = files(ctx);
    rootEl.addEventListener("click", function (event) {
      var el = event.target.closest ? event.target.closest("[data-export]") : null, file, url, link;
      if (!el || !list[el.getAttribute("data-export")]) return;
      file = list[el.getAttribute("data-export")];
      url = URL.createObjectURL(new Blob([file.build()], { type: file.type }));
      link = document.createElement("a");
      link.href = url;
      link.download = file.name;
      link.hidden = true;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      ui.announce("Saved " + file.name + ".");
    });
  }

  DA.views["export"] = { id: "export", title: "Export", render: render, bind: bind, command: command, markdown: markdown };
})(typeof globalThis !== "undefined" ? globalThis : this);
