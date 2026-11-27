(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  var NUMERIC = { strict: true, v1: true, lenient: true, v2: true };
  var RULES = {
    v1: "its strict rule",
    boxed_loose: "its loose rule for the box",
    hashes_loose: "its loose rule for ####",
    bold: "its rule for a bold number",
    answer_is: "its rule for \"answer is\"",
    last_number: "its last-number rule"
  };
  var CLIP_LINES = 12;

  // The view's own memory: which cell is picked for each decision, the dim toggle, the drawn
  // chart, and what the last render showed, so that picking a cell redraws the item panel only.
  var picks = {};
  var dimmed = false;
  var chart = { audit: null, policy: null, node: null };
  var shown = null;
  var loads = 0;
  var perRun = typeof WeakMap === "function" ? new WeakMap() : null;

  function label(run, id) {
    return fmt.prompt(run, id);
  }

  function promptText(run, id) {
    var p = run.prompts && run.prompts[id];
    if (typeof p === "string") return p;
    return p && typeof p.text === "string" ? p.text : "";
  }

  function envById(audit, id) {
    return audit.environments.filter(function (e) { return e.id === id; })[0] || null;
  }

  function defaultRound(decisions) {
    var stale = decisions.filter(function (d) { return d.false_accept && d.cause === "stale"; })[0];
    var wrong = decisions.filter(function (d) { return d.false_accept; })[0];
    return (stale || wrong || decisions[decisions.length - 1]).round;
  }

  function chosen(p, round) {
    var hit = p.decisions.filter(function (d) { return d.round === round; })[0];
    return hit || p.decisions.filter(function (d) { return d.round === defaultRound(p.decisions); })[0];
  }

  // The reference in use is already a rerun under this round's environment.
  function sameReading(d) {
    return d.ref_fresh || (d.ref_pass === "rerun" && d.ref_scored_env === d.env);
  }

  function changedCount(cells) {
    var n = 0, i;
    if (!cells.stored || !cells.rerun) return 0;
    for (i = 0; i < cells.stored.length; i++) if (cells.stored.charAt(i) !== cells.rerun.charAt(i)) n++;
    return n;
  }

  function firstCell(cells) {
    var i;
    if (!cells.stored) return 0;
    if (cells.rerun) for (i = 0; i < cells.stored.length; i++) if (cells.stored.charAt(i) !== cells.rerun.charAt(i)) return i;
    i = cells.stored.indexOf("w");
    return i < 0 ? 0 : i;
  }

  function tie(sentence) {
    return sentence.replace(/ (\S+)$/, fmt.NBSP + "$1");
  }

  /* Sentences ----------------------------------------------------------------------- */

  function refPhrase(d, policyId) {
    if (d.ref_fresh) return "a reference rerun this round";
    if (policyId === "frozen") return "the frozen reference";
    if (d.env_mismatch) return "a stale reference";
    if (sameReading(d)) return "a rerun reference";
    return "the stored reference";
  }

  // The decision in words. A replayed policy is told in the present tense, since its numbers
  // come from replaying it over recorded labels; the loop's own decisions (As run) in the past.
  function story(ctx, d, cells) {
    var run = ctx.run, names = ui.envNames(ctx.audit), margin = ctx.audit.options.margin || 0, past = ctx.policyId === "as_run";
    var cand = label(run, d.candidate), inc = label(run, d.incumbent), ref = label(run, d.ref_prompt);
    var here = names[d.env] || d.env, there = names[d.ref_env] || d.ref_env, out = [], changed = changedCount(cells);
    var rule = margin ? ", more than the margin of " + fmt.plural(margin, "item") + "," : "";
    var against = d.ref_fresh ? "against " + ref + " rerun this round"
      : sameReading(d) ? "against " + ref + " as rerun in round " + d.ref_round : "against the stored reference";
    var verdict = d.accepted ? (past ? "so it was promoted." : "so it is promoted.") : "so the incumbent " + inc + (past ? " was kept." : " is kept.");
    var won = past ? " won " : " wins ", lost = past ? " and lost " : " and loses ";
    function t(present, before) {
      return past ? before : present;
    }

    if (d.wins === null) {
      out.push("The run log has no paired counts for " + cand + " against " + ref + ". The loop " + (d.accepted ? "promoted it." : "kept the incumbent " + inc + "."));
    } else if (margin && d.wins - d.losses > 0 && !d.accepted) {
      out.push(cand + won + fmt.plural(d.wins, "item") + lost + d.losses + " " + against + ", not more than the margin of " + fmt.plural(margin, "item") + ", " + verdict);
    } else {
      out.push(cand + won + fmt.plural(d.wins, "item") + lost + d.losses + " " + against + (d.accepted ? rule : "") + ", " + verdict);
    }

    if (d.rerun_wins === null) {
      out.push("The run log has no rerun labels for " + ref + " under " + here + ", so this decision cannot be checked against a rerun reference.");
    } else if (sameReading(d)) {
      out.push("The reference was already rerun under " + here + ", so the stored and the rerun reading are the same.");
    } else {
      out.push("Against a rerun of the same reference it wins " + d.rerun_wins + " and loses " + d.rerun_losses + ", so the same rule " +
        (d.rerun_accepts ? (d.accepted ? t("would also promote it.", "would also have promoted it.") : t("would promote it.", "would have promoted it."))
          : (d.accepted ? t("would keep the incumbent.", "would have kept the incumbent.") : t("would also keep the incumbent.", "would also have kept the incumbent."))));
    }

    if (d.env_mismatch) {
      out.push("The stored reference was measured under " + there + (d.ref_scored_env !== d.ref_env ? ", rescored with the scorer of " + (names[d.ref_scored_env] || d.ref_scored_env) + "," : "") +
        t(" and is read under ", " and read under ") + here + ".");
    } else if (!sameReading(d)) {
      out.push("The stored reference was measured under " + there + (d.ref_env === d.env ? ", the environment of this round," : ", which has the same fingerprint as " + here + ",") +
        " so it is not stale" + (changed ? "; the " + fmt.plural(changed, "item") + " that read differently in the rerun come from new outputs." : "."));
    }

    var acc = "accuracy in " + here + t(" goes", " went") + " from " + fmt.pct(d.inc_acc) + " for " + inc + " to " + fmt.pct(d.cand_acc);
    var would = t("Promoted, it would bring accuracy in ", "Had it been promoted, accuracy in ") + here + t(" to ", " would have been ") + fmt.pct(d.cand_acc) + " against " + fmt.pct(d.inc_acc) + " for " + inc;
    var fa = t("so this is a false accept", "so this was a false accept");
    if (d.false_accept) {
      if (d.cause === "stale") out.push("Its " + acc + ", " + fa + " on a stale reference: a rerun reference " + t("would reject it.", "would have rejected it."));
      else if (d.cause === "anyway") out.push("Its " + acc + ", " + fa + ", and a rerun reference " + t("would promote it too", "would have promoted it too") + ", so a stale reference does not explain it.");
      else if (d.cause === "no_drift") {
        out.push("Its " + acc + ", " + fa + " that a stale reference does not explain" +
          (d.ref_prompt !== d.incumbent ? ": the reference is " + ref + ", not the incumbent " + inc + "." : "."));
      } else out.push("Its " + acc + ", " + fa + ". Without rerun labels its cause cannot be told.");
    } else if (d.false_reject) {
      out.push(would + t(", so keeping " + inc + " misses an improvement.", ", so keeping " + inc + " missed an improvement."));
    } else if (d.accepted) {
      out.push("Its " + acc + t(", so the promotion raises accuracy.", ", so the promotion raised accuracy."));
    } else {
      out.push(would + t(", so keeping " + inc + " is right.", ", so keeping " + inc + " was right."));
    }
    return out.join(" ");
  }

  function missingText(p, run) {
    var list;
    if (!p || !p.missing || !p.missing.length) {
      return p && p.id === "as_run"
        ? "The run log does not record which reference the loop compared each candidate against, so its own decisions cannot be inspected. Pick one of the replayed policies."
        : "The run log lacks labels this policy needs.";
    }
    list = p.missing.slice(0, 4).map(function (m) {
      return (m.pass === "rerun" ? "rerun" : "stored") + " labels for " + label(run, m.prompt) + " under " + m.env;
    });
    return "It needs labels the run log does not have: " + fmt.list(list) +
      (p.missing_count > list.length ? ", and " + (p.missing_count - list.length) + " more" : "") +
      ". Record them and open the run log again, or pick another policy.";
  }

  /* Ledger and totals --------------------------------------------------------------- */

  function check(d) {
    if (d.false_accept) return ui.tag("false accept", "error");
    if (d.false_reject) return ui.tag("false reject", "error");
    return d.accepted ? "improvement" : html`<span class="muted">not better</span>`;
  }

  function ledger(ctx, p, round) {
    var run = ctx.run, names = ui.envNames(ctx.audit);
    return ui.ledger({
      key: "rounds-ledger", caption: "Decision ledger, one row per round", label: "Decision ledger",
      rows: p.decisions,
      rowClass: function (d) { return d.round === round ? "is-selected rounds__row" : "rounds__row"; },
      rowAttrs: function (d) {
        return {
          "data-pick-round": d.round, "data-round": d.round,
          "data-check": d.false_accept ? "false-accept" : d.false_reject ? "false-reject" : d.accepted ? "improvement" : "kept",
          "data-cause": d.cause || null
        };
      },
      columns: [
        { label: "Round", head: true, tight: true, cell: function (d) {
          return html`<button type="button" class="linklike rounds__pick" data-pick-round="${d.round}" data-key="${"round-" + d.round}" aria-pressed="${d.round === round ? "true" : "false"}" aria-label="${"Inspect round " + d.round}">${d.round}</button>`;
        } },
        { label: "Environment", cell: function (d) { return names[d.env] || d.env; } },
        { label: "Candidate", tight: true, cell: function (d) { return label(run, d.candidate); } },
        { label: "Reference in use", cell: function (d) {
          return html`<span class="nowrap">${label(run, d.ref_prompt)} ${d.ref_pass === "rerun" ? "rerun" : "stored"}, age ${d.ref_age}</span>${d.env_mismatch ? html` ${ui.tag("stale", "warning")}` : ""}`;
        } },
        { label: "Stored", num: true, cell: function (d) { return d.wins === null ? "n/a" : d.wins + " to " + d.losses; } },
        { label: "Rerun", num: true, cell: function (d) { return d.rerun_wins === null ? "n/a" : d.rerun_wins + " to " + d.rerun_losses; } },
        { label: "Inflation, pp", num: true, cell: function (d) { return d.inflation === null ? "n/a" : fmt.ppOf(d.inflation); } },
        { label: "Decision", cell: function (d) { return html`<span class="rounds__decision">${ui.mark(ui.markOf(d))}${d.accepted ? "promoted" : "kept"}</span>`; } },
        { label: "Check", cell: check },
        { label: "Cause", cell: function (d) {
          if (!d.false_accept) return "";
          if (d.cause === "stale") return ui.tag("stale reference", "warning");
          return d.cause ? fmt.cause(d.cause) : html`<span class="muted">no rerun labels</span>`;
        } }
      ]
    });
  }

  function totals(p, id) {
    var n = p.decisions.length, stale = p.decisions.filter(function (d) { return d.env_mismatch; }).length;
    return ui.kv([
      { key: "Promotions", value: fmt.count(p.accepted, n) + " decisions" },
      { key: "False accepts", value: p.accepted ? fmt.count(p.false_accepts, p.accepted) + " promotions" : "none" },
      { key: "False rejects", value: n - p.accepted ? fmt.count(p.false_rejects, n - p.accepted) + " rejections" : "none" },
      { key: "Stale reference", value: stale ? "in " + fmt.count(stale, n) + " decisions" : "in no decision" },
      { key: "Reference reruns", value: p.refreshes ? fmt.int(p.refreshes) : "none" },
      { key: "Drift inflation", value: p.inflation === null || p.inflation === undefined ? "n/a" : fmt.ppOf(p.inflation, 2, true) + ", the mean over " + fmt.plural(n, "decision") }
    ]);
  }

  /* Round detail -------------------------------------------------------------------- */

  function detailRows(ctx, d) {
    var run = ctx.run, audit = ctx.audit, names = ui.envNames(audit);
    var stored = envById(audit, d.ref_env), now = envById(audit, d.env);
    var rows = [
      { key: "Reference prompt", value: label(run, d.ref_prompt) + (d.ref_pass === "rerun" ? ", rerun" : ", stored") + " in round " + d.ref_round +
        (d.ref_prompt === d.incumbent ? ", the incumbent" : ", while the incumbent is " + label(run, d.incumbent)) },
      { key: "Stored under", value: (names[d.ref_env] || d.ref_env) + " (" + d.ref_env + ")" }
    ];
    if (stored) rows.push({ key: "Stored fingerprint", value: stored.fingerprint, mono: true, copy: { label: "Copy", done: "Copied" } });
    rows.push({ key: "Current environment", value: (names[d.env] || d.env) + " (" + d.env + ")" });
    if (now) rows.push({ key: "Current fingerprint", value: now.fingerprint, mono: true, copy: { label: "Copy", done: "Copied" } });
    rows.push({ key: "Reference age", value: d.ref_age === 0 ? "0 rounds, rerun this round" : fmt.plural(d.ref_age, "round") });
    rows.push({ key: "Accuracy in " + (names[d.env] || d.env), value: label(run, d.candidate) + " " + fmt.pct(d.cand_acc) + ", " + label(run, d.incumbent) + " " + fmt.pct(d.inc_acc) +
      ", difference " + fmt.pp(d.delta_pp, 2, true) });
    return ui.kv(rows);
  }

  function cellWords(cells, i) {
    var s = cells.stored.charAt(i), r = cells.rerun ? cells.rerun.charAt(i) : null;
    var cand = s === "w" || s === "b", refStored = s === "l" || s === "b";
    var words = "The run log grades the candidate " + (cand ? "right" : "wrong") + " and the stored reference " + (refStored ? "right" : "wrong");
    if (r !== null) words += ", and the rerun reference " + (r === "l" || r === "b" ? "right" : "wrong");
    return words + ".";
  }

  function valueText(v) {
    if (v === null || v === undefined) return "nothing";
    if (typeof v === "number") return isNaN(v) ? "NaN" : (v < 0 ? fmt.MINUS : "") + String(Math.abs(v));
    return "\"" + v + "\"";
  }

  function scorerOf(env) {
    try {
      return DA.scorers.get(env.scorer);
    } catch (err) {
      return null;
    }
  }

  function numericRun(run) {
    return Object.keys(run.environments).every(function (id) { return NUMERIC[run.environments[id].scorer]; });
  }

  // What the scorer in force reads from one output, and, for the numeric scorers, both of them.
  function readings(run, audit, block, text, gold, graded) {
    var env = envById(audit, block.scoreEnv), scorer = env && scorerOf(env), name, value, right = null, parts = [], rule, strict, lenient;
    if (!scorer) return { right: null, markup: html`<p class="rounds__read">The scorer of ${block.scoreEnv} is not one this page knows, so the output is shown as it is.</p>` };
    name = (env.detail && env.detail.scorer_name) || scorer.name;
    value = scorer.extract(text);
    if (gold !== null) right = !!scorer.correct(value, gold);
    parts.push(html`<p class="rounds__read">The ${name} scorer of ${env.name || env.id} reads <strong>${valueText(value)}</strong>${right === null ? "." : html`, which is <strong>${right ? "right" : "wrong"}</strong>.`}</p>`);
    if (numericRun(run)) {
      rule = DA.scorers.lenientRule(text);
      strict = valueText(DA.scorers.strict(text));
      lenient = valueText(DA.scorers.lenient(text));
      parts.push(strict === lenient
        ? html`<p class="rounds__also">Both scorers read ${strict}.</p>`
        : html`<p class="rounds__also">Strict reads ${strict}. Lenient reads ${lenient}${RULES[rule] ? ", by " + RULES[rule] : ""}.</p>`);
    }
    if (right !== null && right !== graded) {
      parts.push(html`<p class="rounds__also">The run log grades this output ${graded ? "right" : "wrong"}, which this reading does not match.</p>`);
    }
    return { right: right, markup: parts };
  }

  function blocksOf(d, cells) {
    var list = [
      { id: "candidate", title: "Candidate output", prompt: d.candidate, env: d.env, scoreEnv: d.env, pass: "current", note: "as generated under" },
      { id: "stored", title: "Reference output as stored", prompt: d.ref_prompt, env: d.ref_scored_env || d.ref_env, scoreEnv: d.ref_scored_env || d.ref_env, pass: d.ref_pass || "current", note: "as stored under" }
    ];
    if (cells.rerun) list.push({ id: "rerun", title: "Reference output as rerun", prompt: d.ref_prompt, env: d.env, scoreEnv: d.env, pass: "rerun", note: "rerun under" });
    return list;
  }

  function graded(block, cells, i) {
    var s = cells.stored.charAt(i), r = cells.rerun ? cells.rerun.charAt(i) : null;
    if (block.id === "candidate") return s === "w" || s === "b";
    if (block.id === "stored") return s === "l" || s === "b";
    return r === "l" || r === "b";
  }

  function skeleton(lines) {
    var out = [], i;
    for (i = 0; i < lines; i++) out.push(html`<span class="rounds__skeleton-line"></span>`);
    return html`<div class="rounds__skeleton" aria-hidden="true">${out}</div>`;
  }

  function outputBlock(s, block, text, gold) {
    var run = s.run, names = ui.envNames(s.audit), heading = html`<h4 class="rounds__block-title">${block.title} <span class="rounds__block-meta">${label(run, block.prompt)} ${block.note} ${names[block.env] || block.env}</span></h4>`;
    var read, long;
    if (text === undefined) return html`<section class="rounds__block" data-block="${block.id}">${heading}${skeleton(4)}</section>`;
    if (text === null) {
      return html`<section class="rounds__block" data-block="${block.id}">${heading}<p class="rounds__read muted">This output could not be read from the saved outputs.</p></section>`;
    }
    read = readings(run, s.audit, block, text, gold, graded(block, s.cells, s.cell));
    long = text.split("\n").length > CLIP_LINES || text.length > 640;
    return html`<section class="rounds__block" data-block="${block.id}"${ui.attrs({ "data-right": read.right === null ? null : String(read.right) })}>
      ${heading}
      ${read.markup}
      <pre class="rounds__out${long ? " is-clipped" : ""}" data-key="${"out-" + block.id}">${text}</pre>
      ${long ? html`<button type="button" class="linklike rounds__expand" data-rounds-expand aria-expanded="false" data-key="${"expand-" + block.id}">Show full output</button>` : ""}
    </section>`;
  }

  // The item panel for the picked cell. complete is false while something is still loading.
  function itemPanel(s) {
    var run = s.run, d = s.d, cells = s.cells, i = s.cell, status = DA.outputs.status(run);
    var items = DA.outputs.peekItems(run), item = items ? items[i] || null : null, gold = item ? item.answer : null;
    var complete = items !== undefined, notices = [], blocks = [], question;
    if (!cells.stored) {
      return { complete: true, markup: ui.notice({ kind: "quiet", body: "The labels for this decision are not in the run log, so there are no items to read." }) };
    }
    if (status === "none" && run.outputs && run.outputs.file && !DA.library.entry().url && !document.getElementById("da-embedded")) {
      notices.push(ui.notice({ kind: "info", body: "This run log names its outputs file, " + run.outputs.file + ". A file opened from your computer cannot reach files beside it, so open that file together with the run log, or drop both on the page, to read the answers." }));
    } else if (status === "none") {
      notices.push(ui.notice({ kind: "info", body: document.getElementById("da-embedded")
        ? "Outputs are not attached to this report, so the answers cannot be shown; the grades above come from the run log. To read the answers, open the run log together with its .outputs.jsonl.gz file in driftaudit view."
        : "Outputs are not attached to this run log, so the answers cannot be shown; the grades above come from the run log. Open the run log together with its .outputs.jsonl.gz file to read them." }));
    } else if (status === "unsupported") {
      notices.push(ui.notice({ kind: "warning", body: "This browser cannot decompress the saved outputs, so the answers cannot be shown. Grades are shown. A current version of Chrome, Firefox or Safari can read them." }));
    } else {
      blocks = blocksOf(d, cells).map(function (b) {
        var list = DA.outputs.peek(run, b.prompt, b.env, b.pass);
        if (list === undefined) complete = false;
        return outputBlock(s, b, list === undefined ? undefined : list && typeof list[i] === "string" ? list[i] : null, gold);
      });
    }
    if (DA.outputs.problem(run)) notices.push(ui.notice({ kind: "warning", body: DA.outputs.problem(run) }));
    if (items === null) {
      notices.push(ui.notice({ kind: "quiet", body: "The question file for this task is not available, so the question and the gold answer cannot be shown, and readings are not checked against a gold answer." }));
    }
    question = items === undefined ? skeleton(3)
      : item ? html`<p class="rounds__question">${item.question}</p><p class="rounds__gold">Gold answer <strong>${item.answer}</strong></p>` : "";
    return {
      complete: complete,
      markup: html`<section class="rounds__item" aria-labelledby="rounds-item-title">
        <h3 class="rounds__item-title" id="rounds-item-title">Item ${i + 1} of ${fmt.int(cells.stored.length)}${item ? html` <span class="rounds__block-meta">id ${item.id}</span>` : ""}${run.source === "synthetic" ? html` ${ui.sourceTag("synthetic")}` : ""}</h3>
        <p class="rounds__cellstate">${cellWords(cells, i)}</p>
        ${question}
        ${notices}
        ${blocks}
        <div class="rounds__prompts">
          ${ui.disclosure({ summary: "Candidate prompt, " + label(run, d.candidate), key: "prompt-candidate", body: html`<pre class="rounds__out">${promptText(run, d.candidate)}</pre>` })}
          ${ui.disclosure({ summary: "Reference prompt, " + label(run, d.ref_prompt), key: "prompt-reference", body: html`<pre class="rounds__out">${promptText(run, d.ref_prompt)}</pre>` })}
        </div>
      </section>`
    };
  }

  function detail(ctx, p, d) {
    var cells = DA.engine.itemCells(ctx.run, d);
    var key = (ctx.run.id || "") + "|" + ctx.policyId + "|" + d.round + "|" + cells.stored + "|" + cells.rerun;
    var cell = picks[key] === undefined ? firstCell(cells) : picks[key];
    var panel;
    shown = { run: ctx.run, audit: ctx.audit, d: d, cells: cells, key: key, cell: cell };
    panel = itemPanel(shown);
    shown.complete = panel.complete;
    return html`<section class="rounds__section rounds__detail" aria-labelledby="rounds-detail-title">
      <div class="grid rounds__detail-grid">
        <div class="span-8 rounds__left">
          <h2 id="rounds-detail-title">${tie("Round " + d.round + ": " + label(ctx.run, d.candidate) + " against " + refPhrase(d, ctx.policyId))}</h2>
          <p class="rounds__story">${story(ctx, d, cells)}</p>
          ${ui.plate({
            cells: cells, key: "rounds-plate", dim: dimmed,
            itemLabel: function (i) { return "Item " + (i + 1); }
          })}
          ${detailRows(ctx, d)}
        </div>
        <div class="span-4 rounds__right" data-rounds-item>${panel.markup}</div>
      </div>
    </section>`;
  }

  /* Views ---------------------------------------------------------------------------- */

  function switcher(policies, id) {
    return html`<div class="rounds__policy"><span class="field__label">Refresh policy</span>${ui.policySwitcher(policies, id)}</div>`;
  }

  function renderRun(ctx) {
    var audit = ctx.audit, p = ctx.policy, id = ctx.policyId, d, k = p && p.k;
    var warn = ui.sourceNotice({ source: audit.run.source, name: audit.run.id });
    shown = null;
    if (!audit.rounds.length) {
      return html`<div class="rounds"><h1>This run log has no candidates, so there are no rounds to inspect.</h1>${warn}</div>`;
    }
    if (!p || p.available === false || !p.decisions.length) {
      return html`<div class="rounds">
        <h1>${tie(fmt.policy(id, k) + " cannot be replayed on this run.")}</h1>
        ${warn}
        ${switcher(audit.policies, id)}
        ${ui.notice({ kind: "warning", title: "Labels are missing", body: p ? missingText(p, ctx.run) : "This policy is not part of the audit." })}
      </div>`;
    }
    d = chosen(p, ctx.round);
    return html`<div class="rounds">
      <h1>${fmt.plural(p.decisions.length, "round")} under ${fmt.policyPhrase(id, k)}</h1>
      ${warn}
      ${switcher(audit.policies, id)}
      <div class="grid rounds__top">
        <section class="span-8 rounds__section">
          <h2>Net gain per round</h2>
          <p class="rounds__note">Wins minus losses, in percentage points of the ${fmt.int(audit.run.n_items)} items. Pick a column, a row of the ledger or a round on the scale to inspect it.</p>
          <div class="rounds__chart" data-rounds-chart></div>
        </section>
        <section class="span-4 rounds__section">
          <h2>${fmt.policy(id, k)}, all rounds</h2>
          <p class="rounds__note">Counts under this policy, replayed on the run's own candidates.</p>
          ${totals(p, id)}
        </section>
      </div>
      <section class="rounds__section">
        <h2>Decision ledger</h2>
        <p class="rounds__note">One row per round. Stored and rerun give wins to losses against each reading of the reference in use; drift inflation is the difference in win rate.</p>
        ${ledger(ctx, p, d.round)}
      </section>
      ${detail(ctx, p, d)}
    </div>`;
  }

  function engineOptions(options, id) {
    var out = { policies: [id] };
    Object.keys(options || {}).forEach(function (key) {
      if (options[key] !== null && options[key] !== undefined) out[key] = options[key];
    });
    return out;
  }

  // One run's block for the selected policy, for the mean drift inflation the study lacks.
  function runBlock(run, options, id) {
    var o = engineOptions(options, id), key = JSON.stringify(o), memo, result;
    memo = perRun ? perRun.get(run) : null;
    if (!memo) {
      memo = {};
      if (perRun) perRun.set(run, memo);
    }
    if (!Object.prototype.hasOwnProperty.call(memo, key)) {
      try {
        result = DA.engine.audit(run, o).policies[id] || null;
      } catch (err) {
        result = null;
      }
      memo[key] = result;
    }
    return memo[key];
  }

  function renderStudy(ctx) {
    var study = ctx.study, id = ctx.policyId, k = ctx.state.options.periodic_k, group = DA.library.group();
    var rows = (group ? group.runs : []).filter(function (e) { return e.run; }).map(function (e) {
      return { entry: e, p: runBlock(e.run, ctx.state.options, id) };
    });
    function ok(r) {
      return r.p && r.p.available !== false;
    }
    var warn = ui.sourceNotice({ runs: ctx.runs });
    return html`<div class="rounds">
      <h1>${fmt.plural(rows.length, "run")} under ${fmt.policyPhrase(id, k)}</h1>
      ${warn}
      ${switcher(study.policies, id)}
      <p class="rounds__lede">Rounds are inspected one run at a time, so pick a run to see its decisions round by round.</p>
      <section class="rounds__section">
        <h2>Each run</h2>
        ${ui.ledger({
          key: "rounds-runs", caption: "Each run under the selected policy",
          rows: rows,
          columns: [
            { label: "Run", head: true, cell: function (r) { return html`<button type="button" class="linklike" data-pick-run="${r.entry.id}" data-key="${"rounds-run-" + r.entry.id}">${r.entry.label}</button>${r.entry.run.source === "synthetic" ? html` ${ui.sourceTag("synthetic")}` : ""}`; } },
            { label: "Promotions", num: true, cell: function (r) { return ok(r) ? fmt.int(r.p.accepted) : "n/a"; } },
            { label: "False accepts", num: true, className: function (r) { return ok(r) && r.p.false_accepts ? "is-alert" : ""; }, cell: function (r) { return ok(r) ? fmt.count(r.p.false_accepts, r.p.accepted) : "n/a"; } },
            { label: "False rejects", num: true, className: function (r) { return ok(r) && r.p.false_rejects ? "is-alert" : ""; }, cell: function (r) { return ok(r) ? fmt.int(r.p.false_rejects) : "n/a"; } },
            { label: "Mean drift inflation, pp", num: true, cell: function (r) { return ok(r) && r.p.inflation !== null && r.p.inflation !== undefined ? fmt.ppOf(r.p.inflation) : "n/a"; } }
          ]
        })}
      </section>
    </div>`;
  }

  /* Behaviour ------------------------------------------------------------------------ */

  // The chart is drawn once per audit and policy and moved into each new render, so picking
  // a round only moves the outline over its column.
  function chartNode(audit, id) {
    var holder, node, decisions;
    if (chart.node && chart.audit === audit && chart.policy === id) return chart.node;
    decisions = audit.policies[id].decisions;
    holder = document.createElement("div");
    holder.innerHTML = String(DA.charts.netGain(DA.charts.netGainData(audit, id, null)));
    node = holder.firstElementChild;
    [["wide", ".chart__wide"], ["narrow", ".chart__narrow"]].forEach(function (pair) {
      var box = node.querySelector(pair[1]);
      if (!box) return;
      box.classList.add("rounds__plot");
      box.insertAdjacentHTML("beforeend", String(html`<div class="rounds__hits rounds__hits--${pair[0]}" aria-hidden="true">${decisions.map(function (d) {
        return html`<button type="button" class="rounds__hit" tabindex="-1" data-pick-round="${d.round}" data-hit="${d.round}" title="${"Round " + d.round}"></button>`;
      })}</div>`));
    });
    chart.audit = audit;
    chart.policy = id;
    chart.node = node;
    return node;
  }

  function markPicked(rootEl, i) {
    Array.prototype.forEach.call(rootEl.querySelectorAll(".plate__cell.rounds__picked"), function (c) {
      c.classList.remove("rounds__picked");
      c.removeAttribute("aria-selected");
    });
    Array.prototype.forEach.call(rootEl.querySelectorAll(".plate__cell[data-i=\"" + i + "\"]"), function (c) {
      c.classList.add("rounds__picked");
      c.setAttribute("aria-selected", "true");
    });
  }

  function fitOutputs(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".rounds__out.is-clipped"), function (pre) {
      var button;
      if (pre.scrollHeight > pre.clientHeight + 1) return;
      pre.classList.remove("is-clipped");
      button = pre.parentNode.querySelector("[data-rounds-expand]");
      if (button) button.parentNode.removeChild(button);
    });
  }

  function load(container, s) {
    var token = ++loads, run = s.run;
    var asks = [DA.outputs.items(run)].concat(DA.outputs.status(run) === "attached" ? blocksOf(s.d, s.cells).map(function (b) {
      return DA.outputs.get(run, b.prompt, b.env, b.pass);
    }) : []);
    Promise.all(asks).then(function () {
      if (token !== loads || !container.isConnected || shown !== s) return;
      mountPanel(container, s);
    });
  }

  function mountPanel(container, s) {
    var panel = itemPanel(s);
    s.complete = panel.complete;
    ui.mount(container, panel.markup);
    fitOutputs(container);
    if (!panel.complete) load(container, s);
  }

  function bind(rootEl, ctx) {
    var slot = rootEl.querySelector("[data-rounds-chart]"), container = rootEl.querySelector("[data-rounds-item]"), s = shown, node;
    if (slot && ctx.policy) {
      node = chartNode(ctx.audit, ctx.policyId);
      slot.appendChild(node);
      Array.prototype.forEach.call(node.querySelectorAll(".rounds__hit"), function (b) {
        b.classList.toggle("is-selected", !!s && Number(b.getAttribute("data-hit")) === s.d.round);
      });
    }
    if (!s || !container) return;
    markPicked(rootEl, s.cell);
    fitOutputs(container);
    if (!s.complete) load(container, s);

    ui.on(rootEl, "cell", function (cell) {
      if (shown !== s || cell.index === s.cell) return;
      s.cell = cell.index;
      picks[s.key] = cell.index;
      markPicked(rootEl, cell.index);
      mountPanel(container, s);
      ui.announce("Item " + (cell.index + 1) + " shown beside the plate. " + cellWords(s.cells, cell.index));
    });
    ui.on(rootEl, "dim", function (detail) {
      dimmed = detail.on;
    });
    rootEl.addEventListener("click", function (event) {
      var button = event.target.closest ? event.target.closest("[data-rounds-expand]") : null, pre, open;
      if (!button) return;
      pre = button.parentNode.querySelector(".rounds__out");
      open = pre.classList.toggle("is-clipped") === false;
      button.textContent = open ? "Show less" : "Show full output";
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  DA.views.rounds = {
    id: "rounds",
    title: "Rounds",
    render: function (ctx) {
      return ctx.mode === "study" ? renderStudy(ctx) : renderRun(ctx);
    },
    bind: function (rootEl, ctx) {
      if (ctx.mode !== "study") bind(rootEl, ctx);
    },
    story: story,
    defaultRound: defaultRound
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
