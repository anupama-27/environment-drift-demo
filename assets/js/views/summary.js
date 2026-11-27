(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  // Keep the last two words of a sentence on one line.
  function tie(sentence) {
    return sentence.replace(/ (\S+)$/, fmt.NBSP + "$1");
  }

  // Who promotes. A replayed policy is described in the present tense, because its numbers
  // come from replaying it over recorded labels; "As run" is what the loop did, in the past.
  var SUBJECTS = {
    frozen: "a frozen reference",
    stored_incumbent: "a stored incumbent reference",
    per_batch: "a reference rerun every round",
    env_triggered: "a reference rerun when the environment changes"
  };

  function subject(id, k) {
    if (id === "periodic") return "a reference rerun every " + (k || "k") + " rounds";
    return SUBJECTS[id] || fmt.policyPhrase(id, k);
  }

  function capital(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  // The words that change with the tense.
  var PRESENT = {
    promotes: "promotes", raise: "raise", raises: "raises", notRaise: "do not raise", notRaises: "does not raise",
    pass: "pass", passes: "passes", is: "is", turns: "turns down", would: "would raise"
  };
  var PAST = {
    promotes: "promoted", raise: "raised", raises: "raised", notRaise: "did not raise", notRaises: "did not raise",
    pass: "passed", passes: "passed", is: "was", turns: "turned down", would: "would have raised"
  };

  // How many promotions did not raise accuracy, and how many of those a stale reference explains.
  // pooled uses the shorter wording of a study.
  function wrongPromotions(w, accepted, fa, stale, pooled) {
    var out, only = " only because the reference " + w.is + " stale.";
    if (fa === 0) {
      return accepted === 1 ? "It " + w.raises + " accuracy." : accepted === 2 ? "Both " + w.raise + " accuracy." : "All " + accepted + " " + w.raise + " accuracy.";
    }
    if (fa === accepted) {
      out = accepted === 1 ? "It " + w.notRaises + " accuracy" : accepted === 2 ? "Neither " + w.raises + " accuracy" : "None of them " + w.raises + " accuracy";
    } else if (pooled) {
      out = fa === 1 ? "1 " + w.notRaises + " accuracy" : fa + " " + w.notRaise + " accuracy";
    } else {
      out = fa === 1 ? "1 of them " + w.notRaises + " accuracy" : fa + " of them " + w.notRaise + " accuracy";
    }
    if (pooled) {
      if (stale === 0) return out + ", and a stale reference explains none of them.";
      if (stale === fa) return out + (fa === 1 ? ", and a stale reference explains it." : fa === 2 ? ", and a stale reference explains both." : ", and a stale reference explains all " + fa + ".");
      return out + ", and a stale reference explains " + stale + " of them.";
    }
    if (fa === 1) return out + (stale === 1 ? ", and it " + w.passes + only : ", and a stale reference does not explain it.");
    if (stale === 0) return out + ", and a stale reference explains none of them.";
    if (stale === fa) return out + (fa === 2 ? ", and both " : ", and all " + fa + " ") + w.pass + only;
    return out + ", and " + stale + " of the " + fa + " " + w.pass + only;
  }

  function turnedDown(w, n) {
    return "It also " + w.turns + " " + (n === 1 ? "1 candidate that " + w.would + " accuracy." : n + " candidates that " + w.would + " accuracy.");
  }

  function noneTurnedDown(w, n) {
    if (n === 0) return "None of the candidates it " + w.turns + " " + w.would + " accuracy.";
    return n + " of the candidates it " + w.turns + " " + w.would + " accuracy.";
  }

  function verdict(p, w, opening, none, pooled) {
    var parts;
    if (p.accepted === 0) {
      parts = [none, noneTurnedDown(w, p.false_rejects)];
    } else {
      parts = [opening, wrongPromotions(w, p.accepted, p.false_accepts, p.causes.stale, pooled)];
      if (p.false_rejects > 0) parts.push(turnedDown(w, p.false_rejects));
    }
    return parts.map(tie).join(" ");
  }

  function candidates(n) {
    return n === 1 ? "1 candidate" : fmt.plural(n, "candidate");
  }

  function runVerdict(p, id) {
    if (id === "as_run") {
      return verdict(p, PAST, "This run promoted " + candidates(p.accepted) + ".", "This run promoted no candidate.");
    }
    var who = capital(subject(id, p.k));
    return verdict(p, PRESENT, who + " promotes " + candidates(p.accepted) + " on this run.", who + " promotes no candidate on this run.");
  }

  function studyVerdict(p, id, k, nRuns) {
    var runs = fmt.plural(nRuns, "run");
    if (id === "as_run") {
      return verdict(p, PAST, "Across " + runs + ", the loops promoted " + candidates(p.accepted) + ".", "Across " + runs + ", the loops promoted no candidate.", true);
    }
    return verdict(p, PRESENT, "Across " + runs + ", " + subject(id, k) + " promotes " + candidates(p.accepted) + ".",
      "Across " + runs + ", " + subject(id, k) + " promotes no candidate.", true);
  }

  function times(n) {
    return n === 1 ? "once" : n === 2 ? "twice" : n + " times";
  }

  // Where the reference went stale under this policy, and what refreshing it costs.
  function lede(audit, p, id) {
    var names = ui.envNames(audit), total = p.decisions.length, out = [];
    var changes = audit.rounds.filter(function (r) { return r.env_changed; });
    var stale = p.decisions.filter(function (d) { return d.env_mismatch; }).map(function (d) { return d.round; });
    var reruns = p.decisions.filter(function (d) { return d.ref_fresh; }).map(function (d) { return d.round; });
    var other = audit.policies.env_triggered, frozen = audit.policies.frozen, extra, past = id === "as_run";
    if (!changes.length) {
      out.push("The environment did not change during this run, so the reference never went stale.");
    } else {
      out.push("The environment changed at " + fmt.list(changes.map(function (r) { return "round " + r.round + " (" + names[r.env] + ")"; })) + ".");
      if (stale.length) {
        out.push(fmt.count(stale.length, total) + " decisions, in " + (stale.length === 1 ? "round " : "rounds ") + fmt.rounds(stale) +
          (past ? ", compared" : ", compare") + " the candidate with a reference measured in an earlier environment.");
      } else if (p.refreshes) {
        out.push((past ? "The loop reran the reference " : "This policy reruns the reference ") + times(p.refreshes) + (reruns.length && reruns.length <= 4 ? ", at " + (reruns.length === 1 ? "round " : "rounds ") + fmt.list(reruns.map(String)) : "") +
          (past ? ", so no decision used a stale reference." : ", so no decision uses a stale reference."));
      } else {
        out.push(past ? "No decision of the loop used a stale reference." : "No decision under this policy uses a stale reference.");
      }
    }
    if (id !== "env_triggered" && other && other.available !== false && changes.length) {
      extra = other.total_calls - p.total_calls;
      out.push("Replayed on the same candidates, the environment-triggered policy reruns the reference " + times(other.refreshes) +
        ", uses about " + fmt.int(Math.abs(extra)) + (extra >= 0 ? " more" : " fewer") + " model calls (" + fmt.int(other.total_calls) + " against " + fmt.int(p.total_calls) + ") and makes " +
        (other.false_accepts === p.false_accepts ? "the same number of false accepts (" + p.false_accepts + ")."
          : fmt.plural(other.false_accepts, "false accept") + " instead of " + p.false_accepts + "."));
    } else if (id === "env_triggered" && frozen && frozen.available !== false && p.refreshes) {
      out.push("Those reruns cost about " + fmt.int(p.total_calls - frozen.total_calls) + " model calls more than never rerunning (" +
        fmt.int(p.total_calls) + " against " + fmt.int(frozen.total_calls) + ").");
    }
    return out.join(" ");
  }

  function causeNote(p) {
    var parts = [];
    ["stale", "anyway", "no_drift"].forEach(function (k) {
      if (p.causes[k]) parts.push(fmt.cause(k) + " " + p.causes[k]);
    });
    return parts.join(", ") + ".";
  }

  function readings(p, id) {
    var rejected = p.decisions.length - p.accepted, past = id === "as_run";
    return ui.readouts([
      {
        label: "Drift inflation", value: fmt.ppOf(p.inflation), unit: "pp",
        note: "Mean over " + fmt.plural(p.decisions.length, "decision") + " of the win rate against the stored reference minus the win rate against the rerun."
      },
      {
        label: "False accepts", value: p.accepted ? fmt.count(p.false_accepts, p.accepted) : "0", state: p.false_accepts ? "alert" : null,
        note: !p.accepted ? (past ? "No candidate was promoted." : "No candidate is promoted.")
          : p.false_accepts ? (past ? "Promotions that did not raise accuracy: " : "Promotions that do not raise accuracy: ") + causeNote(p)
          : past ? "Every promotion raised accuracy." : "Every promotion raises accuracy."
      },
      {
        label: "False rejects", value: rejected ? fmt.count(p.false_rejects, rejected) : "0", state: p.false_rejects ? "alert" : null,
        note: !rejected ? (past ? "No candidate was turned down." : "No candidate is turned down.")
          : p.false_rejects ? (past ? "Candidates turned down that would have raised accuracy." : "Candidates turned down that would raise accuracy.")
          : past ? "No candidate turned down would have raised accuracy." : "No candidate turned down would raise accuracy."
      },
      {
        label: "Model calls", value: fmt.int(p.total_calls),
        note: "Estimated. " + (p.refreshes ? fmt.plural(p.refreshes, "reference rerun") + " took " + fmt.int(p.calls.reference_refresh) + " of them." : "No reference reruns.")
      }
    ]);
  }

  function wrongDecisions(audit, p, round) {
    var rows = p.decisions.filter(function (d) { return d.false_accept || d.false_reject; });
    return ui.ledger({
      key: "summary-wrong", dense: true, caption: "False accepts and false rejects under this policy",
      empty: "No false accepts and no false rejects under this policy.",
      rows: rows,
      rowClass: function (d) { return d.round === round ? "is-selected" : null; },
      columns: [
        { label: "Round", tight: true, cell: function (d) { return html`<button type="button" class="linklike" data-pick-round="${d.round}" data-key="${"wrong-" + d.round}" aria-label="${"Select round " + d.round}">${d.round}</button>`; } },
        { label: "Decision", cell: function (d) { return ui.tag(d.false_accept ? "false accept" : "false reject", "error"); } },
        { label: "Stored", num: true, cell: function (d) { return d.wins + " to " + d.losses; } },
        { label: "Rerun", num: true, cell: function (d) { return d.rerun_wins + " to " + d.rerun_losses; } },
        { label: "Accuracy, %", num: true, cell: function (d) { return fmt.num(100 * d.inc_acc, 1) + " to " + fmt.num(100 * d.cand_acc, 1); } },
        { label: "Cause", cell: function (d) { return d.false_accept ? (d.cause === "stale" ? ui.tag("stale reference", "warning") : fmt.cause(d.cause)) : ""; } }
      ]
    });
  }

  function revisions(audit) {
    var previous = null;
    var rows = audit.environments.map(function (e) {
      var scheduled = e.rounds.length > 0;
      var row = { env: e, scheduled: scheduled, changed: {} };
      if (scheduled && previous) {
        ["decoding", "scorer", "fingerprint"].forEach(function (k) { row.changed[k] = e[k] !== previous[k]; });
      }
      if (scheduled) previous = e;
      return row;
    });
    function mark(key) {
      return function (r) { return r.changed[key] ? "is-changed" : ""; };
    }
    return ui.ledger({
      key: "summary-envs", caption: "Environment versions",
      rows: rows,
      columns: [
        { label: "Environment", head: true, cell: function (r) { return r.env.name && r.env.name !== r.env.id ? html`${r.env.name} <span class="muted">${r.env.id}</span>` : r.env.id; } },
        { label: "Rounds", cell: function (r) { return r.scheduled ? fmt.rounds(r.env.rounds) : html`<span class="muted">not scheduled</span>`; } },
        { label: "Decoding", mono: true, className: mark("decoding"), cell: function (r) { return r.env.decoding; } },
        { label: "Scorer", className: mark("scorer"), cell: function (r) { return r.env.detail && r.env.detail.scorer_name ? html`${r.env.detail.scorer_name} <span class="muted">${r.env.scorer}</span>` : r.env.scorer; } },
        { label: "Fingerprint", className: mark("fingerprint"), cell: function (r) { return ui.copyable(r.env.fingerprint, { label: "Copy", done: "Copied", key: "fp-" + r.env.id, ariaLabel: "Copy the fingerprint of " + r.env.id }); } }
      ]
    });
  }

  function missingText(p, ctx) {
    var shown;
    if (!p.missing || !p.missing.length) {
      return p.id === "as_run"
        ? "The run log does not record which reference the loop compared each candidate against, so its own decisions cannot be audited. Pick one of the replayed policies."
        : "The run log lacks labels this policy needs.";
    }
    shown = p.missing.slice(0, 4).map(function (m) {
      return (m.pass === "rerun" ? "rerun" : "stored") + " labels for " + fmt.prompt(ctx.run, m.prompt) + " under " + m.env;
    });
    return "It needs labels the run log does not have: " + fmt.list(shown) +
      (p.missing_count > shown.length ? ", and " + (p.missing_count - shown.length) + " more" : "") +
      ". Record them and open the run log again, or pick another policy.";
  }

  // A bundled run may carry a note in data/index.json; it sits under the title.
  function runNote() {
    var entry = DA.library.entry && DA.library.entry();
    return entry && typeof entry.note === "string" && entry.note ? html`<p class="summary__run-note">${entry.note}</p>` : "";
  }

  function switcher(policies, id) {
    return html`<div class="summary__policy"><span class="field__label">Refresh policy</span>${ui.policySwitcher(policies, id)}</div>`;
  }

  function renderRun(ctx) {
    var audit = ctx.audit, p = ctx.policy, id = ctx.policyId;
    var synthetic = ui.sourceNotice({ source: audit.run.source, name: audit.run.id });
    if (!audit.rounds.length) {
      return html`<div class="summary"><h1 class="verdict">This run log has no candidates, so there is nothing to audit.</h1>${synthetic}</div>`;
    }
    if (!p || p.available === false) {
      return html`<div class="summary">
        <h1 class="verdict">${tie(fmt.policy(id, p && p.k) + " cannot be replayed on this run.")}</h1>
        ${synthetic}
        ${switcher(audit.policies, id)}
        ${ui.notice({ kind: "warning", title: "Labels are missing", body: p ? missingText(p, ctx) : "This policy is not part of the audit." })}
        <section class="summary__section"><h2>Environment versions</h2>${revisions(audit)}</section>
      </div>`;
    }
    return html`<div class="summary">
      <h1 class="verdict">${runVerdict(p, id)}</h1>
      ${runNote()}
      ${synthetic}
      ${switcher(audit.policies, id)}
      <p class="summary__lede">${lede(audit, p, id)}</p>
      ${readings(p, id)}
      <div class="grid summary__grid">
        <section class="span-7 summary__section">
          <h2>Net gain per round</h2>
          <p class="summary__note">Wins minus losses, in percentage points of the ${fmt.int(audit.run.n_items)} items. A candidate is promoted when its net gain against the reference in use is above ${audit.options.margin ? fmt.int(audit.options.margin) + " items" : "zero"}.</p>
          ${DA.charts.netGain(DA.charts.netGainData(audit, id, ctx.round))}
        </section>
        <section class="span-5 summary__section">
          <h2>Decisions that were wrong</h2>
          <p class="summary__note">Judged by accuracy in the round's own environment. Pick a round to mark it on the scale.</p>
          ${wrongDecisions(audit, p, ctx.round)}
        </section>
      </div>
      <section class="summary__section">
        <h2>Environment versions</h2>
        <p class="summary__note">One row per version. Shaded cells changed from the version before.</p>
        ${revisions(audit)}
      </section>
    </div>`;
  }

  // A pooled policy block has counts only when every run of the set could be replayed.
  function pooledOk(p) {
    return !!p && p.available !== false && typeof p.accepted === "number";
  }

  function renderStudy(ctx) {
    var study = ctx.study, id = ctx.policyId, k = ctx.state.options.periodic_k, p = study.policies[id];
    var ids = ui.policyOptions(study.policies, id).map(function (o) { return o.value; });
    var synthetic = ui.sourceNotice({ runs: ctx.runs });
    var labels = {};
    (DA.library.group() || { runs: [] }).runs.forEach(function (r) { labels[r.run && r.run.id] = r; });
    var table = ui.ledger({
      key: "summary-policies", caption: "Refresh policies over all runs",
      rows: ids.map(function (pid) { return { id: pid, p: study.policies[pid] }; }),
      rowClass: function (r) { return r.id === id ? "is-selected" : null; },
      columns: [
        { label: "Policy", head: true, cell: function (r) { return html`<button type="button" class="linklike" data-pick-policy="${r.id}" data-key="${"study-" + r.id}">${fmt.policy(r.id, k)}</button>`; } },
        { label: "Promotions", num: true, cell: function (r) { return pooledOk(r.p) ? fmt.int(r.p.accepted) : "n/a"; } },
        { label: "False accepts", num: true, className: function (r) { return pooledOk(r.p) && r.p.false_accepts ? "is-alert" : ""; }, cell: function (r) { return pooledOk(r.p) ? fmt.count(r.p.false_accepts, r.p.accepted) : "n/a"; } },
        { label: "False rejects", num: true, className: function (r) { return pooledOk(r.p) && r.p.false_rejects ? "is-alert" : ""; }, cell: function (r) { return pooledOk(r.p) ? fmt.int(r.p.false_rejects) : "n/a"; } },
        { label: "Final accuracy, %", num: true, cell: function (r) { return pooledOk(r.p) ? fmt.meanSd(100 * r.p.final_acc.mean, 100 * r.p.final_acc.sd, 1) : "n/a"; } },
        { label: "Model calls", num: true, cell: function (r) { return pooledOk(r.p) ? fmt.int(r.p.total_calls.mean) : "n/a"; } },
        { label: "Reference reruns", num: true, cell: function (r) { return pooledOk(r.p) ? fmt.num(r.p.refreshes.mean, r.p.refreshes.mean % 1 ? 1 : 0) : "n/a"; } }
      ]
    });
    if (!pooledOk(p)) {
      return html`<div class="summary">
        <h1 class="verdict">${tie(fmt.policy(id, k) + " cannot be replayed on every run of this set.")}</h1>
        ${synthetic}${switcher(study.policies, id)}
        <section class="summary__section"><h2>The policies over all ${study.n_runs} runs</h2>${table}</section>
      </div>`;
    }
    return html`<div class="summary">
      <h1 class="verdict">${studyVerdict(p, id, k, study.n_runs)}</h1>
      ${synthetic}
      ${switcher(study.policies, id)}
      <p class="summary__lede">Counts are pooled over the ${study.n_runs} runs and their ${fmt.int(study.n_decisions)} decisions. Final accuracy, model calls and reruns are means per run; accuracy is shown with one standard deviation, and model calls are estimates.</p>
      <section class="summary__section">
        <h2>The policies over all ${study.n_runs} runs</h2>
        ${table}
      </section>
      <section class="summary__section">
        <h2>Each run under ${fmt.policyPhrase(id, k)}</h2>
        <p class="summary__note">Pick a run to audit it on its own.</p>
        ${ui.ledger({
          key: "summary-runs", caption: "Each run under the selected policy",
          rows: p.per_run,
          columns: [
            { label: "Run", head: true, cell: function (r) {
              var entry = labels[r.id];
              return entry ? html`<button type="button" class="linklike" data-pick-run="${entry.id}" data-key="${"run-" + entry.id}">${entry.label}</button>${entry.run.source === "synthetic" ? html` ${ui.sourceTag("synthetic")}` : ""}` : (r.id || "run");
            } },
            { label: "Promotions", num: true, cell: function (r) { return fmt.int(r.accepted); } },
            { label: "False accepts", num: true, className: function (r) { return r.false_accepts ? "is-alert" : ""; }, cell: function (r) { return fmt.count(r.false_accepts, r.accepted); } },
            { label: "False rejects", num: true, className: function (r) { return r.false_rejects ? "is-alert" : ""; }, cell: function (r) { return fmt.int(r.false_rejects); } },
            { label: "Final accuracy", num: true, cell: function (r) { return fmt.pct(r.final_acc); } },
            { label: "Model calls", num: true, cell: function (r) { return fmt.int(r.total_calls); } }
          ]
        })}
      </section>
    </div>`;
  }

  DA.views.summary = {
    id: "summary",
    title: "Summary",
    render: function (ctx) {
      return ctx.mode === "study" ? renderStudy(ctx) : renderRun(ctx);
    },
    // Exposed for tests: the sentences are plain functions of the audit numbers.
    verdict: runVerdict,
    studyVerdict: studyVerdict,
    lede: lede
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
