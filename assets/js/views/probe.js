(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  // The age the reader picked, per group; null keeps the study's own default.
  var picked = { group: null, age: null };
  var memo = null;

  function given(x) {
    return x !== null && x !== undefined;
  }

  function engineOptions(options) {
    var out = {};
    Object.keys(options || {}).forEach(function (key) {
      if (given(options[key])) out[key] = options[key];
    });
    return out;
  }

  function firstEnv(run, options) {
    var schedule = options.schedule || run.schedule;
    var first = Object.keys(schedule).map(Number).sort(function (a, b) { return a - b; })[0];
    return schedule[String(first)];
  }

  function names(run) {
    var out = {};
    Object.keys(run.environments).forEach(function (id) { out[id] = run.environments[id].name || id; });
    return out;
  }

  // The study at the picked age: the shared one when the ages agree, otherwise computed here.
  function studyAt(ctx, runs, age) {
    var options = engineOptions(ctx.state.options), key;
    if (ctx.study && (age === null || ctx.study.probe.age === age)) return ctx.study;
    key = JSON.stringify(options) + "/" + age;
    if (!memo || memo.key !== key || memo.runs.length !== runs.length || memo.runs.some(function (r, i) { return r !== runs[i]; })) {
      memo = { key: key, runs: runs, result: DA.engine.study(runs, Object.assign({}, options, age === null ? {} : { probe_age: age })) };
    }
    return memo.result;
  }

  function stepper(value, max) {
    var low = value <= 0, high = value >= max;
    return html`<div class="probe__control">
      <span class="field__label" id="probe-age-label">Reference age, rounds</span>
      <div class="probe__stepper" role="group" aria-labelledby="probe-age-label">
        <button type="button" class="btn btn--small" data-probe-age="-1" data-key="probe-age-down" aria-label="Younger reference"${ui.attrs({ "aria-disabled": low ? "true" : null })}>${fmt.MINUS}</button>
        <output class="probe__value num" data-probe-age-value>${value}</output>
        <button type="button" class="btn btn--small" data-probe-age="1" data-key="probe-age-up" aria-label="Older reference"${ui.attrs({ "aria-disabled": high ? "true" : null })}>+</button>
      </div>
    </div>`;
  }

  function excludes(e) {
    return given(e.lo) && given(e.hi) && (e.lo > 0 || e.hi < 0);
  }

  function measured(xs) {
    return xs.filter(given).length;
  }

  /* Block 1: by environment at one age ------------------------------------------------ */

  function byEnvironment(study, run, maxAge) {
    var probe = study.probe, n = names(run), ids = Object.keys(probe.by_env);
    var rows = ids.map(function (id) { return { id: id, label: n[id] || id, e: probe.by_env[id] }; });
    var drawn = rows.filter(function (r) { return given(r.e.mean); });
    var excluding = drawn.filter(function (r) { return excludes(r.e); });
    var finding;
    if (!drawn.length) {
      finding = "No environment has candidate-reference pairs at this age, so there is nothing to estimate.";
    } else if (!excluding.length) {
      finding = "No interval excludes zero at this age.";
    } else {
      finding = "The interval excludes zero for " + fmt.list(excluding.map(function (r) {
        return r.label + " (" + (r.e.mean > 0 ? "above" : "below") + " zero in " + fmt.count(r.e.mean > 0 ? r.e.n_positive : measured(r.e.per_run) - r.e.n_positive, measured(r.e.per_run)) + " runs)";
      })) + ".";
    }
    return html`<section class="probe__section">
      <h2>Drift inflation by environment</h2>
      <p class="probe__note">References are ${fmt.plural(probe.age, "round")} old and stored under ${n[probe.stored_env] || probe.stored_env}; candidates and reruns are scored under each environment in turn. Mean over ${fmt.plural(study.n_runs, "run")} with a 95% interval, in percentage points.</p>
      <div class="probe__bench">${stepper(probe.age, maxAge)}<p class="probe__finding" data-probe-finding>${finding}</p></div>
      <div class="grid probe__grid">
        <div class="span-7">
          ${drawn.length ? DA.charts.intervals(drawn.map(function (r) {
            return { label: r.label, mean: r.e.mean, lo: r.e.lo, hi: r.e.hi, values: r.e.per_run.filter(given) };
          }), { caption: "Drift inflation at reference age " + probe.age + ", pp" }) : html`<p class="empty">Nothing to draw at this age.</p>`}
        </div>
        <div class="span-5">
          ${ui.ledger({
            key: "probe-env-table", dense: true, caption: "Drift inflation by environment at reference age " + probe.age,
            rows: rows,
            rowAttrs: function (r) { return { "data-env-row": r.id }; },
            columns: [
              { label: "Environment", head: true, cell: function (r) { return r.label; } },
              { label: "Mean, pp", num: true, cell: function (r) { return given(r.e.mean) ? fmt.pp(r.e.mean) : html`<span class="muted">no pairs</span>`; } },
              { label: "95% interval", num: true, className: function (r) { return excludes(r.e) ? "probe__excludes" : ""; }, cell: function (r) {
                return given(r.e.lo) ? fmt.interval(r.e.lo, r.e.hi) : html`<span class="muted">${measured(r.e.per_run) < 2 ? "needs two runs" : "n/a"}</span>`;
              } },
              { label: "Runs above zero", num: true, cell: function (r) { return fmt.count(r.e.n_positive, measured(r.e.per_run)); } }
            ]
          })}
        </div>
      </div>
    </section>`;
  }

  /* Block 2: by reference age --------------------------------------------------------- */

  function byAge(study, run) {
    var n = names(run), stored = study.age.stored_env, ids = Object.keys(study.age.by_env);
    var last = ids[ids.length - 1], series, rows, top, samePairs;
    series = ids.map(function (id) {
      return {
        id: id, label: "Scored under " + (n[id] || id), plain: id === stored && ids.length > 1,
        points: study.age.by_env[id]
      };
    });
    samePairs = study.age.ages.every(function (a, i) { return series.every(function (s) { return s.points[i].pairs === series[0].points[i].pairs; }); });
    rows = study.age.ages.map(function (a, i) { return { age: a, i: i }; });
    top = series[0].points[series[0].points.length - 1];
    return html`<section class="probe__section">
      <h2>Drift inflation by reference age</h2>
      <p class="probe__note">References stored under ${n[stored] || stored}, scored ${ids.length > 1 ? html`under ${n[stored] || stored} and under ${n[last] || last}, the first and the last scheduled environment` : "under the same environment, the only one scheduled"}.</p>
      <div class="grid probe__grid">
        <div class="span-7">
          ${DA.charts.ageLines(series.map(function (s) {
            return { label: s.label, plain: s.plain, points: s.points.filter(function (p) { return given(p.mean); }).map(function (p) { return { x: p.age, mean: p.mean, lo: p.lo, hi: p.hi }; }) };
          }), { caption: "Drift inflation by reference age, pp" })}
        </div>
        <div class="span-5">
          ${ui.ledger({
            key: "probe-age-table", dense: true, caption: "Drift inflation and candidate-reference pairs by reference age",
            rows: rows,
            columns: [{ label: "Age", num: true, tight: true, cell: function (r) { return r.age; } }]
              .concat(samePairs ? [{ label: "Pairs", num: true, cell: function (r) { return fmt.int(series[0].points[r.i].pairs); } }] : [])
              .concat([].concat.apply([], series.map(function (s) {
                var short = n[s.id] || s.id;
                return [
                  { label: short + ", pp", num: true, cell: function (r) { var p = s.points[r.i]; return given(p.mean) ? fmt.pp(p.mean) : html`<span class="muted">no pairs</span>`; } },
                  { label: "95% interval", num: true, cell: function (r) { var p = s.points[r.i]; return given(p.lo) ? fmt.interval(p.lo, p.hi) : html`<span class="muted">n/a</span>`; } }
                ].concat(samePairs ? [] : [{ label: "Pairs", num: true, cell: function (r) { return fmt.int(s.points[r.i].pairs); } }]);
              })))
          })}
          <p class="probe__note probe__after">At age ${top.age} there ${top.pairs === 1 ? "is 1 pair" : "are " + fmt.int(top.pairs) + " pairs"}, against ${fmt.int(series[0].points[0].pairs)} at age ${series[0].points[0].age}: the oldest references have the fewest pairs, so their intervals are the widest and the least reliable.</p>
        </div>
      </div>
    </section>`;
  }

  function howToRead() {
    return html`<section class="probe__section">
      <h2>How to read it</h2>
      <div class="measure stack stack--1">
        <p>Drift inflation is the candidate's win rate against the stored reference minus its win rate against a rerun of the same reference in the current environment. Both use the same candidate outputs, so the difference comes from the reference alone.</p>
        <p>Near zero, the stored reference still stands for the incumbent. An interval that excludes zero marks an environment change that makes stored references stale; above zero, stale references make candidates look better than they are.</p>
      </div>
    </section>`;
  }

  /* One run only ---------------------------------------------------------------------- */

  function single(ctx, run, age, maxAge, apart) {
    var options = engineOptions(ctx.state.options), stored = firstEnv(run, options), n = names(run);
    var pairs = DA.engine.agePairs(run, age, { schedule: options.schedule, stored_scoring: options.stored_scoring, margin: options.margin, force_stored_env: stored });
    return html`<p class="probe__lede">${apart
        ? "The runs of this group cannot be pooled, so this page shows the selected run's own drift inflation round by round."
        : "This group has a single run. Intervals need several runs (seeds) of the same experiment, so this page shows the run's own drift inflation round by round instead."}</p>
      <section class="probe__section">
        <h2>Drift inflation per round</h2>
        <p class="probe__note">Each candidate against the incumbent from ${fmt.plural(age, "round")} earlier, stored under ${n[stored] || stored} and rerun in the candidate's own environment.</p>
        <div class="probe__bench">${stepper(age, maxAge)}</div>
        ${ui.ledger({
          key: "probe-single", caption: "Drift inflation per round for this run",
          rows: pairs, empty: "No round has a reference " + fmt.plural(age, "round") + " old with both readings saved.",
          columns: [
            { label: "Round", num: true, tight: true, cell: function (p) { return p.round; } },
            { label: "Environment", cell: function (p) { var env = DA.views.policies.perRound(options.schedule || run.schedule, p.round + 1)[p.round]; return n[env] || env; } },
            { label: "Wins against stored", num: true, cell: function (p) { return fmt.pct(p.stored_win); } },
            { label: "Wins against rerun", num: true, cell: function (p) { return fmt.pct(p.rerun_win); } },
            { label: "Drift inflation, pp", num: true, cell: function (p) { return fmt.ppOf(p.inflation); } }
          ]
        })}
      </section>
      ${howToRead()}`;
  }

  function render(ctx) {
    var group = DA.library.group(), entries = group ? group.runs : [], runs, study, age, maxAge, run, problems;
    if (!group) return html`<p class="empty">No run set is selected.</p>`;
    if (picked.group !== group.id) {
      picked = { group: group.id, age: null };
    }
    runs = entries.map(function (e) { return e.run; });
    problems = DA.library.poolProblems(group);
    if (entries.length === 1 || (problems && problems.length && ctx.run)) {
      run = entries.length === 1 ? runs[0] : ctx.run;
      maxAge = Math.max(0, run.snapshots.length - 1);
      age = given(picked.age) ? Math.min(picked.age, maxAge) : Math.min(3, maxAge);
      return html`<div class="probe"><h1>Drift probe</h1>${single(ctx, run, age, maxAge, entries.length > 1)}</div>`;
    }
    if (!runs.every(Boolean)) {
      return html`<div class="probe"><h1>Drift probe</h1>${ui.notice({ kind: "quiet", body: "Reading the other runs of this group. The probe pools all of them." })}</div>`;
    }
    maxAge = Math.max(0, Math.min.apply(null, runs.map(function (r) { return r.snapshots.length; })) - 1);
    age = given(picked.age) ? Math.min(picked.age, maxAge) : null;
    try {
      study = studyAt(ctx, runs, age);
    } catch (err) {
      return html`<div class="probe"><h1>Drift probe</h1>${ui.notice({ kind: "error", title: "The probe could not be computed for these runs", body: (err && err.message) || String(err) })}</div>`;
    }
    return html`<div class="probe">
      <h1>Drift probe</h1>
      <p class="probe__lede">${ctx.mode === "run"
        ? html`The probe is a property of the group, so it pools all ${fmt.plural(study.n_runs, "run")} whichever run is selected.`
        : html`Pooled over the ${fmt.plural(study.n_runs, "run")} of this group.`} It compares stored and rerun references on recorded labels and calls no model.</p>
      ${byEnvironment(study, runs[0], maxAge)}
      ${byAge(study, runs[0])}
      ${howToRead()}
    </div>`;
  }

  function bind(rootEl) {
    rootEl.addEventListener("click", function (event) {
      var el = event.target.closest ? event.target.closest("[data-probe-age]") : null, value;
      if (!el || el.getAttribute("aria-disabled") === "true") return;
      value = Number(rootEl.querySelector("[data-probe-age-value]").textContent) + Number(el.getAttribute("data-probe-age"));
      picked.age = Math.max(0, value);
      ui.announce("Reference age " + picked.age);
      DA.state.set({});
    });
  }

  DA.views.probe = { id: "probe", title: "Drift probe", render: render, bind: bind };
})(typeof globalThis !== "undefined" ? globalThis : this);
