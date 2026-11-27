(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  var ORDER = ["frozen", "stored_incumbent", "per_batch", "env_triggered", "periodic", "as_run"];
  var RULES = {
    frozen: function () { return "Never reruns; compares with the round 0 reference"; },
    stored_incumbent: function () { return "Never reruns; compares with the incumbent's stored outputs"; },
    per_batch: function () { return "Reruns the incumbent every round"; },
    env_triggered: function () { return "Reruns when the environment fingerprint changes"; },
    periodic: function (k) { return "Reruns once the reference is " + fmt.plural(k, "round") + " old"; },
    as_run: function () { return "The decisions the loop recorded"; }
  };
  var DEFAULTS = { schedule: null, stored_scoring: "as_recorded", margin: 0, periodic_k: 3 };
  var TESTED = ["frozen", "stored_incumbent", "per_batch"];
  var AS_RUN_NOTE = "As run is not listed: the loop compared each candidate with its own incumbent in the same pass, so its decisions match the ground-truth check by construction.";

  // The "Every k rounds" row appears once the reader has used its stepper, and goes again on reset.
  var periodicShown = false;

  function has(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  /* Schedules as one environment per round ------------------------------------------- */

  function starts(schedule) {
    return Object.keys(schedule).map(function (s) { return [parseInt(s, 10), schedule[s]]; })
      .sort(function (a, b) { return a[0] - b[0]; });
  }

  function perRound(schedule, n) {
    var list = starts(schedule), out = [], k, i, env;
    for (k = 0; k < n; k++) {
      env = list[0][1];
      for (i = 0; i < list.length; i++) if (k >= list[i][0]) env = list[i][1];
      out.push(env);
    }
    return out;
  }

  function compress(envs) {
    var out = {};
    envs.forEach(function (env, k) {
      if (k === 0 || envs[k - 1] !== env) out[String(k)] = env;
    });
    return out;
  }

  function sameList(a, b) {
    return a.length === b.length && a.every(function (x, i) { return x === b[i]; });
  }

  // Everything the what-ifs need, for one run or for every run of a study.
  function setting(ctx) {
    var runs = ctx.mode === "study" ? ctx.runs : [ctx.run];
    var first = runs[0], n, recorded, envIds, sharedSchedule;
    if (!first) return null;
    n = Math.min.apply(null, runs.map(function (r) { return r.snapshots.length; }));
    envIds = Object.keys(first.environments).filter(function (id) {
      return runs.every(function (r) { return has(r.environments, id); });
    });
    recorded = perRound(first.schedule, n);
    sharedSchedule = runs.every(function (r) { return sameList(perRound(r.schedule, n), recorded); });
    return {
      runs: runs, n: n, envs: first.environments, envIds: envIds, recorded: recorded, shared: sharedSchedule,
      current: ctx.state.options.schedule ? perRound(ctx.state.options.schedule, n) : recorded,
      nItems: first.task.n_items
    };
  }

  // Replace each recorded environment by the one that differs only in decoding (or scorer)
  // from the first environment. null when the run lacks such an environment or nothing changes.
  function preset(s, keep) {
    var base = s.envs[s.recorded[0]], out = [], ok = true;
    s.recorded.forEach(function (id) {
      var want = s.envs[id], match = null;
      s.envIds.forEach(function (other) {
        var e = s.envs[other];
        if (match !== null) return;
        if (keep === "scorer" && e.decoding === base.decoding && e.scorer === want.scorer) match = other;
        if (keep === "decoding" && e.decoding === want.decoding && e.scorer === base.scorer) match = other;
      });
      if (match === null) ok = false;
      out.push(match);
    });
    return ok && !sameList(out, s.recorded) ? out : null;
  }

  function envName(s, id) {
    var e = s.envs[id];
    return e && e.name ? e.name : id;
  }

  /* Tables ---------------------------------------------------------------------------- */

  function available(p) {
    return !!p && p.available !== false && typeof p.accepted === "number";
  }

  function showsPeriodic() {
    return periodicShown || DA.state.get().policy === "periodic";
  }

  // The policies a table lists: "As run" only when it is not trivial, "Every k rounds" only
  // after the reader asked for it.
  function listed(policies, id) {
    if (!policies[id]) return false;
    if (id === "periodic") return showsPeriodic();
    if (id === "as_run") return !DA.library.hidesAsRun(policies) && (available(policies[id]) || policies[id].missing_count > 0);
    return true;
  }

  function policyIds(policies) {
    return ORDER.filter(function (id) { return listed(policies, id); });
  }

  function asRunNote(policies) {
    return DA.library.hidesAsRun(policies) ? html`<p class="policies__note policies__as-run" data-as-run-note>${AS_RUN_NOTE}</p>` : "";
  }

  function leastErrors(policies, ids) {
    var best = null;
    ids.forEach(function (id) {
      var p = policies[id], e;
      if (!available(p)) return;
      e = p.false_accepts + p.false_rejects;
      if (best === null || e < best) best = e;
    });
    return function (id) {
      var p = policies[id];
      return available(p) && best !== null && p.false_accepts + p.false_rejects === best;
    };
  }

  function nameCell(id, k) {
    return html`<button type="button" class="linklike" data-pick-policy="${id}" data-key="${"policies-pick-" + id}">${fmt.policy(id, k)}</button>`;
  }

  function missingText(p, run) {
    var shown;
    if (!p.missing || !p.missing.length) {
      return p.id === "as_run"
        ? "the run log does not record which reference each candidate was compared against"
        : "the run log lacks labels it needs";
    }
    shown = p.missing.slice(0, 3).map(function (m) {
      return (m.pass === "rerun" ? "rerun" : "stored") + " labels for " + fmt.prompt(run, m.prompt) + " under " + m.env;
    });
    return "it needs " + fmt.list(shown) + (p.missing_count > shown.length ? ", and " + (p.missing_count - shown.length) + " more" : "");
  }

  function runTable(ctx, k) {
    var policies = ctx.audit.policies, ids = policyIds(policies), least = leastErrors(policies, ids);
    var rows = ids.map(function (id) { return { id: id, p: policies[id] }; });
    function cls(r) {
      return least(r.id) ? "policies__least" : "";
    }
    function alert(key) {
      return function (r) { return (least(r.id) ? "policies__least " : "") + (available(r.p) && r.p[key] ? "is-alert" : ""); };
    }
    function value(fn) {
      return function (r) { return available(r.p) ? fn(r.p) : html`<span class="muted">n/a</span>`; };
    }
    var unavailable = rows.filter(function (r) { return !available(r.p); });
    return html`${ui.ledger({
      key: "policies-table", caption: "Refresh policies replayed on this run",
      rows: rows,
      rowClass: function (r) { return r.id === ctx.policyId ? "is-selected" : null; },
      rowAttrs: function (r) { return { "data-policy-row": r.id }; },
      columns: [
        { label: "Policy", head: true, className: cls, cell: function (r) { return nameCell(r.id, k); } },
        { label: "Rule", cell: function (r) { return RULES[r.id](k); } },
        { label: "Promotions", num: true, cell: value(function (p) { return fmt.int(p.accepted); }) },
        { label: "False accepts", num: true, className: alert("false_accepts"), cell: value(function (p) { return fmt.count(p.false_accepts, p.accepted); }) },
        { label: "False rejects", num: true, className: alert("false_rejects"), cell: value(function (p) { return fmt.count(p.false_rejects, p.decisions.length - p.accepted); }) },
        { label: "Final accuracy", num: true, cell: value(function (p) { return fmt.pct(p.final_acc); }) },
        { label: "Reference reruns", num: true, cell: value(function (p) { return fmt.int(p.refreshes); }) },
        { label: "Model calls, estimated", num: true, cell: value(function (p) { return fmt.int(p.total_calls); }) }
      ]
    })}
    ${unavailable.length ? html`<ul class="policies__missing">${unavailable.map(function (r) {
      return html`<li>${fmt.policy(r.id, k)} cannot be replayed: ${missingText(r.p, ctx.run)}.</li>`;
    })}</ul>` : ""}
    ${asRunNote(policies)}`;
  }

  function studyTable(ctx, k) {
    var study = ctx.study, policies = study.policies, ids = ORDER.filter(function (id) { return listed(policies, id); });
    var least = leastErrors(policies, ids), left = ORDER.filter(function (id) { return !policies[id] && (id !== "periodic" || showsPeriodic()); });
    function cls(r) {
      return least(r.id) ? "policies__least" : "";
    }
    function alert(key) {
      return function (r) { return (least(r.id) ? "policies__least " : "") + (r.p[key] ? "is-alert" : ""); };
    }
    return html`${ui.ledger({
      key: "policies-study-table", caption: "Refresh policies pooled over all runs",
      rows: ids.map(function (id) { return { id: id, p: policies[id] }; }),
      rowClass: function (r) { return r.id === ctx.policyId ? "is-selected" : null; },
      rowAttrs: function (r) { return { "data-policy-row": r.id }; },
      columns: [
        { label: "Policy", head: true, className: cls, cell: function (r) { return nameCell(r.id, k); } },
        { label: "Rule", cell: function (r) { return RULES[r.id](k); } },
        { label: "Promotions", num: true, cell: function (r) { return fmt.int(r.p.accepted); } },
        { label: "False accepts", num: true, className: alert("false_accepts"), cell: function (r) { return fmt.count(r.p.false_accepts, r.p.accepted); } },
        { label: "False rejects", num: true, className: alert("false_rejects"), cell: function (r) { return fmt.int(r.p.false_rejects); } },
        { label: "Final accuracy, %", num: true, cell: function (r) { return fmt.meanSd(100 * r.p.final_acc.mean, 100 * r.p.final_acc.sd, 1); } },
        { label: "Reruns per run", num: true, cell: function (r) { return fmt.meanSd(r.p.refreshes.mean, r.p.refreshes.sd, r.p.refreshes.mean % 1 || r.p.refreshes.sd ? 1 : 0); } },
        { label: "Calls per run, estimated", num: true, cell: function (r) { return r.p.total_calls.sd ? fmt.int(r.p.total_calls.mean) + " ± " + fmt.int(r.p.total_calls.sd) : fmt.int(r.p.total_calls.mean); } }
      ]
    })}
    ${left.length ? html`<ul class="policies__missing">${left.map(function (id) {
      return html`<li>${fmt.policy(id, k)} is left out: ${id === "as_run" ? "not every run records which reference each candidate was compared against" : "not every run has the labels it needs"}.</li>`;
    })}</ul>` : ""}
    ${asRunNote(policies)}`;
  }

  function tests(ctx, k) {
    var list = ctx.study.policy_tests.filter(function (t) { return t.a === "env_triggered" && TESTED.indexOf(t.b) >= 0; });
    if (!list.length) {
      return html`<p class="policies__note">No tests: the environment-triggered policy cannot be replayed on every run.</p>`;
    }
    return html`<ul class="policies__tests">${list.map(function (t) {
      return html`<li data-test="${t.b}">${fmt.policy(t.a, k)} against ${fmt.policy(t.b, k).toLowerCase()}: ${fmt.plural(t.errors_a, "wrong decision")} against ${fmt.int(t.errors_b)}, out of ${fmt.int(t.n)} each. Fisher exact p = <span class="num">${fmt.num(t.fisher_p, 3)}</span>.</li>`;
    })}</ul>
    <p class="policies__note">Each test treats the ${fmt.int(list[0].n)} decisions as independent, which overstates the evidence: decisions in one run share their incumbent and their reference.</p>`;
  }

  /* Decision matrix ------------------------------------------------------------------- */

  var KIND_WORDS = { "false-accept": "false accept", "false-reject": "false reject" };

  function decisionCell(d) {
    var kind = ui.markOf(d);
    return html`<span class="policies__decision" data-decision="${kind}">${ui.mark(kind)}<span>${d.accepted ? "promoted" : "kept"}</span><span class="num policies__delta">${fmt.pp(d.delta_pp)}</span>${KIND_WORDS[kind] ? html`<span class="visually-hidden">, ${KIND_WORDS[kind]}</span>` : ""}</span>`;
  }

  function runMatrix(ctx, k) {
    var audit = ctx.audit, names = ui.envNames(audit);
    var ids = ORDER.filter(function (id) { return listed(audit.policies, id) && available(audit.policies[id]); });
    var byRound = {};
    ids.forEach(function (id) {
      byRound[id] = {};
      audit.policies[id].decisions.forEach(function (d) { byRound[id][d.round] = d; });
    });
    var columns = [
      { label: "Round", tight: true, num: true, cell: function (r) {
        return html`<button type="button" class="linklike" data-pick-round="${r.round}" data-key="${"policies-round-" + r.round}" aria-label="${"Select round " + r.round}">${r.round}</button>`;
      } },
      { label: "Environment", className: function (r) { return r.env_changed ? "is-changed" : ""; }, cell: function (r) { return names[r.env] || r.env; } },
      { label: "Candidate accuracy", num: true, cell: function (r) { return fmt.pct(r.candidate_acc); } }
    ].concat(ids.map(function (id) {
      return {
        label: fmt.policy(id, k),
        cell: function (r) {
          var d = byRound[id][r.round];
          return d ? decisionCell(d) : html`<span class="muted">no decision</span>`;
        }
      };
    }));
    return html`${ui.legend([
      { mark: "improved", label: "Promoted, an improvement" },
      { mark: "false-accept", label: "False accept" },
      { mark: "false-reject", label: "False reject" },
      { mark: "rejected", label: "Kept" },
      { swatch: "changed", label: "Environment changed" }
    ], "policies__legend")}
    ${ui.ledger({
      key: "policies-matrix", dense: true, caption: "Decision of each policy in each round",
      rows: audit.rounds,
      rowClass: function (r) { return r.round === ctx.round ? "is-selected" : null; },
      rowAttrs: function (r) { return { "data-round-row": r.round }; },
      columns: columns
    })}`;
  }

  function studyMatrix(ctx, k) {
    var policies = ctx.study.policies, ids = ORDER.filter(function (id) { return listed(policies, id); });
    var labels = {};
    (DA.library.group() || { runs: [] }).runs.forEach(function (e) { if (e.run) labels[e.run.id] = e; });
    var rows = ctx.study.runs.map(function (r, i) { return { id: r.id, i: i }; });
    return ui.ledger({
      key: "policies-study-matrix", dense: true, caption: "False accepts over promotions, by run and policy",
      rows: rows,
      columns: [
        { label: "Run", head: true, cell: function (r) {
          var e = labels[r.id];
          return e ? html`<button type="button" class="linklike" data-pick-run="${e.id}" data-key="${"policies-run-" + e.id}">${e.label}</button>${e.run.source === "synthetic" ? html` ${ui.sourceTag("synthetic")}` : ""}` : (r.id || "Run " + (r.i + 1));
        } }
      ].concat(ids.map(function (id) {
        return {
          label: fmt.policy(id, k), num: true,
          className: function (r) { return policies[id].per_run[r.i].false_accepts ? "is-alert" : ""; },
          cell: function (r) { var x = policies[id].per_run[r.i]; return fmt.count(x.false_accepts, x.accepted); }
        };
      }))
    });
  }

  /* What-ifs -------------------------------------------------------------------------- */

  function stepper(o) {
    var low = o.value <= o.min, high = o.value >= o.max;
    return html`<div class="policies__stepper" role="group" aria-label="${o.label}">
      <button type="button" class="btn btn--small" data-step="${o.name}" data-delta="-1" data-key="${o.name + "-down"}" aria-label="${o.down}"${ui.attrs({ "aria-disabled": low ? "true" : null })}>${fmt.MINUS}</button>
      <output class="policies__value num" data-value-of="${o.name}">${o.value}</output>
      <button type="button" class="btn btn--small" data-step="${o.name}" data-delta="1" data-key="${o.name + "-up"}" aria-label="${o.up}"${ui.attrs({ "aria-disabled": high ? "true" : null })}>+</button>
    </div>`;
  }

  function scheduleBlock(s) {
    var noDecoding = preset(s, "scorer"), noScorer = preset(s, "decoding");
    var changed = !sameList(s.current, s.recorded);
    if (!s.shared) {
      return html`<div class="policies__whatif policies__whatif--wide"><h3>Environment schedule</h3>
        <p class="policies__note">These runs do not follow one schedule, so the schedule cannot be changed for all of them at once. Pick one run to try another schedule.</p></div>`;
    }
    var presets = [{ id: "recorded", label: "As recorded", on: !changed }];
    if (noDecoding) presets.push({ id: "no-decoding", label: "No decoding change", on: sameList(s.current, noDecoding) });
    if (noScorer) presets.push({ id: "no-scorer", label: "No scorer change", on: sameList(s.current, noScorer) });
    return html`<div class="policies__whatif policies__whatif--wide">
      <h3>Environment schedule</h3>
      <p class="policies__note">Which environment is in force at each round. Every policy is replayed on the same candidates with the labels saved for that environment.</p>
      <div class="policies__strip">${s.current.map(function (env, k) {
        return html`<label class="field field--stack policies__slot"><span class="field__label">Round ${k}</span><span class="select"><select name="${"policies-env-" + k}" data-round="${k}" data-key="${"policies-env-" + k}"${ui.attrs({ "class": env !== s.recorded[k] ? "policies__moved" : null })}>${s.envIds.map(function (id) {
          return html`<option value="${id}"${ui.attrs({ selected: id === env })}>${envName(s, id)}</option>`;
        })}</select></span></label>`;
      })}</div>
      <div class="cluster policies__presets">${presets.map(function (p) {
        return html`<button type="button" class="btn btn--small" data-preset="${p.id}" data-key="${"policies-preset-" + p.id}" aria-pressed="${p.on ? "true" : "false"}">${p.label}</button>`;
      })}</div>
      ${changed ? html`<div class="policies__counter">${ui.notice({
        kind: "warning", key: "policies-counterfactual",
        title: "Counterfactual schedule",
        body: html`These are counterfactual replays of recorded labels under another schedule: ${scheduleWords(s)}. No run followed this schedule, and the loop's own decisions (As run) keep the recorded environments.`
      })}</div>` : ""}
    </div>`;
  }

  function scheduleWords(s) {
    var parts = [], i, j;
    for (i = 0; i < s.current.length; i = j) {
      for (j = i + 1; j < s.current.length && s.current[j] === s.current[i]; j++);
      parts.push(envName(s, s.current[i]) + (j - i > 1 ? " in rounds " + i + " to " + (j - 1) : " in round " + i));
    }
    return fmt.list(parts);
  }

  function whatIfs(ctx, s) {
    var o = ctx.state.options, k = o.periodic_k, margin = o.margin || 0;
    var touched = o.schedule || o.stored_scoring !== DEFAULTS.stored_scoring || margin !== DEFAULTS.margin || k !== DEFAULTS.periodic_k || periodicShown;
    return html`<section class="policies__bench" aria-labelledby="policies-whatifs">
      <div class="policies__bench-head">
        <h2 id="policies-whatifs">What if</h2>
        <button type="button" class="btn btn--small" data-preset="reset" data-key="policies-reset"${ui.attrs({ "aria-disabled": touched ? null : "true" })}>Reset all</button>
      </div>
      <p class="policies__note">Each change replays every policy again on the recorded labels. Nothing is regenerated.</p>
      <div class="policies__whatifs">
        ${scheduleBlock(s)}
        <div class="policies__whatif">
          <h3>How a stored reference is read</h3>
          ${ui.segmented({ name: "policies-scoring", label: "How a stored reference is read", value: o.stored_scoring, options: [
            { value: "as_recorded", label: "As recorded" },
            { value: "rescore", label: "Re-scored now" }
          ] })}
          <p class="policies__note">Re-scoring reads the reference's saved outputs with the scorer in force at the round. It costs no model calls; a rerun costs ${fmt.plural(s.nItems, "call")}.</p>
        </div>
        <div class="policies__whatif">
          <h3>Refresh every k rounds</h3>
          ${stepper({ name: "periodic_k", label: "Rounds between reruns", value: k, min: 1, max: s.n, down: "Rerun more often", up: "Rerun less often" })}
          <p class="policies__note">${showsPeriodic()
            ? "The " + fmt.policy("periodic", k) + " row reruns the reference once it is " + fmt.plural(k, "round") + " old."
            : "Step the number to add an " + fmt.policy("periodic") + " row to the tables, rerunning the reference once it is that many rounds old."}</p>
        </div>
        <div class="policies__whatif">
          <h3>Margin</h3>
          ${stepper({ name: "margin", label: "Margin, items", value: margin, min: 0, max: s.nItems, down: "Lower the margin", up: "Raise the margin" })}
          <p class="policies__note">A candidate is promoted when its wins minus losses exceed ${fmt.plural(margin, "item")}.</p>
        </div>
      </div>
      ${ctx.audit && ctx.audit.completeness.notes.length ? ui.notice({
        kind: "quiet", title: "Notes from the replay",
        body: html`<ul class="policies__missing">${ctx.audit.completeness.notes.map(function (n) { return html`<li>${n}</li>`; })}</ul>`
      }) : ""}
    </section>`;
  }

  /* View ------------------------------------------------------------------------------ */

  function render(ctx) {
    var k = ctx.state.options.periodic_k, s = setting(ctx), study = ctx.mode === "study", n, runsText;
    if (!s) return html`<p class="empty">Reading the run log.</p>`;
    if (study) {
      n = ctx.study.n_decisions;
      runsText = html`The ${fmt.plural(n, "candidate")} of the ${fmt.plural(ctx.study.n_runs, "run")} are replayed under every policy. Nothing is regenerated: every count comes from the labels saved in the run logs. Counts are pooled; accuracy, reruns and calls are per run.`;
    } else {
      n = ctx.audit.run.n_candidates;
      runsText = html`The ${fmt.plural(n, "candidate")} of this run are replayed under every policy. Nothing is regenerated: every count comes from the labels saved in the run log.`;
    }
    if (!n) {
      return html`<div class="policies"><h1>Refresh policies</h1><p class="empty">This run log has no candidates, so there are no decisions to replay.</p></div>`;
    }
    return html`<div class="policies">
      <h1>Refresh policies</h1>
      <p class="policies__lede" data-lede>${runsText}</p>
      <section class="policies__section">
        <h2>${study ? "The policies over all " + ctx.study.n_runs + " runs" : "The policies on this run"}</h2>
        <p class="policies__note">${study ? "False accepts are out of promotions, pooled over runs. Final accuracy is the mean with one standard deviation." : "False accepts are out of promotions, false rejects out of the candidates kept."} The row with the fewest wrong decisions is set in medium weight.</p>
        ${study ? studyTable(ctx, k) : runTable(ctx, k)}
        ${study ? html`<h3 class="policies__subhead">Environment-triggered against each other policy</h3>${tests(ctx, k)}` : ""}
      </section>
      <section class="policies__section">
        <h2>${study ? "False accepts in each run" : "Decisions round by round"}</h2>
        <p class="policies__note">${study ? "False accepts over promotions for each run and policy." : "Each cell gives the decision and the candidate's change in accuracy against that policy's own incumbent, in percentage points."}</p>
        ${study ? studyMatrix(ctx, k) : runMatrix(ctx, k)}
      </section>
      ${whatIfs(ctx, s)}
    </div>`;
  }

  function setOptions(patch) {
    DA.state.set({ options: Object.assign({}, DA.state.get().options, patch) });
  }

  function bind(rootEl, ctx) {
    var s = setting(ctx);
    if (!s) return;
    function applySchedule(list) {
      setOptions({ schedule: sameList(list, s.recorded) ? null : compress(list) });
    }
    rootEl.addEventListener("change", function (event) {
      var el = event.target, list;
      if (!el.name || el.name.indexOf("policies-env-") !== 0) return;
      list = s.current.slice();
      list[Number(el.getAttribute("data-round"))] = el.value;
      applySchedule(list);
    });
    rootEl.addEventListener("click", function (event) {
      var el = event.target.closest ? event.target.closest("[data-preset], [data-step]") : null, name, o, next, max;
      if (!el || el.getAttribute("aria-disabled") === "true") return;
      if (el.hasAttribute("data-preset")) {
        name = el.getAttribute("data-preset");
        if (name === "reset") {
          periodicShown = false;
          DA.state.set(DA.state.get().policy === "periodic" ? { policy: "frozen", options: Object.assign({}, DEFAULTS) } : { options: Object.assign({}, DEFAULTS) });
        }
        else if (name === "recorded") applySchedule(s.recorded);
        else applySchedule(preset(s, name === "no-decoding" ? "scorer" : "decoding"));
        return;
      }
      name = el.getAttribute("data-step");
      o = DA.state.get().options;
      max = name === "periodic_k" ? s.n : s.nItems;
      next = Math.max(name === "periodic_k" ? 1 : 0, Math.min(max, (o[name] || 0) + Number(el.getAttribute("data-delta"))));
      if (name === "periodic_k" && !periodicShown) {
        periodicShown = true;
        if (next === o[name]) DA.state.set({});
      }
      if (next !== o[name]) {
        setOptions(name === "periodic_k" ? { periodic_k: next } : { margin: next });
        ui.announce((name === "periodic_k" ? "Rerun every " : "Margin ") + next);
      }
    });
    ui.on(rootEl, "select", function (detail) {
      if (detail.name === "policies-scoring") setOptions({ stored_scoring: detail.value });
    });
  }

  DA.views.policies = {
    id: "policies",
    title: "Policies",
    render: render,
    bind: bind,
    // Shared with the export view, which writes the schedule in force on the command line.
    perRound: perRound,
    showsPeriodic: showsPeriodic
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
