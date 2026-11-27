(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  var STEPS = ["Grade one answer two ways", "Run the loop", "Change the environment", "Score candidates after the change",
    "Find the false accepts", "Pick a refresh policy", "Compare the policies on five seeds", "Map the parts to other tasks",
    "See the components"];
  var EXAMPLE_SEED = 5;
  var HOSTED = "https://anupama-27.github.io/environment-drift-demo/#/case-study";
  var POLICY_FOR_OPTION = { A: "P1", B: "P2", C: "P3" };
  var OPTIONS = {
    A: { title: "A. Frozen", text: "Never rerun. The stored reference is kept for the rest of the run." },
    B: { title: "B. Per-batch", text: "Rerun the reference every round." },
    C: { title: "C. Environment-triggered", text: "Rerun the reference once, when the environment version changes." }
  };
  var ENV_NAME = { E1: "Unchanged", E2: "Decoding", E3: "Extraction", E4: "Combined" };
  var SHORT = { P1: "Frozen", P2: "Per-batch", P3: "Environment-triggered" };
  var CAUSE = {
    stale: "stale reference",
    anyway: "would have been accepted anyway",
    before_change: "no environment change"
  };
  var REF_TEXT = {
    P1: "the starting instruction p0's saved answers, for the whole run",
    P2: "the current instruction, rerun every round",
    P3: "the current instruction's saved answers, rerun when the environment version changes"
  };

  var EXTRACTOR_EXAMPLES = [
    ["\\boxed{18}", "18", "18"],
    ["\\boxed{70,000}", "none", "70000"],
    ["\\boxed{\\$15}", "none", "15"],
    ["\\boxed{540 \\text{ meters}}", "none", "540"],
    ["The answer is 1,200.", "none", "1200"]
  ];

  // Rows of the "Beyond GSM8K" mapping. The GSM8K column is what the runs used; the others are illustration.
  var MAP_ROWS = [
    ["task", "Task and gold answers"],
    ["reference", "What the stored reference records"],
    ["change", "An environment change"],
    ["example", "The same output, read before and after"],
    ["check", "Independent check"],
    ["loop", "Loop, refresh policies, metrics"],
    ["supply", "What has to be written"],
    ["results", "Results"]
  ];
  var GSM8K_COL = {
    task: "Grade school word problems. The gold answer is a number.",
    reference: "Instruction p0 and its version, 200 saved answers with their grades, the environment fingerprint and the scorer version.",
    change: "The answer extractor goes from strict (v1) to lenient (v2); decoding goes from greedy to sampling.",
    example: ["\\boxed{70,000}", "no answer, wrong", "70000, right"],
    check: "Both instructions measured in the environment in force.",
    loop: "Promote if wins > losses. Frozen, per-batch or environment-triggered. False accepts, drift inflation, call counts.",
    supply: "Already in the repository."
  };
  var DOMAINS = {
    "Financial QA": {
      task: "Numeric questions over earnings reports, in the style of FinQA. Only questions with a numeric gold answer.",
      reference: "The same four records, plus the version of the report the answer was read from.",
      change: "The answer parser is updated to read currency, percent signs and unit scale, or the model version changes.",
      example: ["\\boxed{\\$94 million}", "no answer, wrong", "94, right if gold is in millions"],
      check: "Gold numbers compared after one fixed normalization of $, %, commas and the unit scale the report declares.",
      supply: "A loader for the questions and gold numbers (drift/data.py); a strict and a lenient reader and the matching tolerance (drift/extract.py); a finance starting instruction (drift/config.py)."
    },
    "Code generation": {
      task: "Programming problems. The gold is a set of unit tests.",
      reference: "The instruction, the generated programs, their test results, and the version of the test runner and interpreter.",
      change: "The test runner starts ignoring whitespace in printed output, or the Python version, a timeout or a library changes.",
      example: ["prints [1, 2, 3] where the test expects [1,2,3]", "exact match, fail", "whitespace ignored, pass"],
      check: "A separate set of unit tests, run in a pinned container that does not change.",
      supply: "A loader for problems and tests (drift/data.py); a test runner in place of the answer extractor, with a strict and a forgiving mode (drift/extract.py); runner and interpreter versions in the fingerprint (drift/envs.py)."
    }
  };

  var COMPONENTS = [
    ["Reference manager", "Stores the reference prompt, raw outputs and graded answers.", "drift/pipeline.py, RunView.stored"],
    ["Environment version tracker", "Names each environment and its fingerprint.", "drift/envs.py"],
    ["Reference rerun", "Regenerates the reference under today's environment.", "Runner.outputs, RunView.rerun"],
    ["Candidate comparison", "Wins and losses of a candidate against a reference, stored and rerun.", "analysis.pair_measure"],
    ["Ground truth check", "Scores both prompts under the current environment.", "extract.is_correct, RunView.gt_acc"],
    ["Policy comparison", "Replays one candidate pool through three refresh rules.", "analysis.simulate"],
    ["Dashboard", "False accepts, false rejects, drift inflation and call counts.", "simulate(with_records=True)"],
    ["Reproducibility log", "Every generation is cached by prompt, item, decoding and seed.", "model.Cache, generation_key"]
  ];

  var COMMANDS = "python run_seeds.py 1 2 3 4 5    # model runs, cached\n" +
    "python run_all.py                # tables from saved runs, no model\n" +
    "python export_replay.py          # writes the replay files this page reads";

  // Progress through the steps lives here; the step itself is in the route.
  var S = {
    status: "idle", error: null, all: null, cache: {}, seed: null, d: null, loadingSeed: null,
    max: 1, shown: 0, shownPost: 0, change: 0, vote: null, app: "Financial QA", q: 0
  };
  var lastStep = null;
  var focusNext = false;
  var keysHooked = false;

  /* Data -------------------------------------------------------------------------------- */

  function refresh() {
    DA.state.set({});
  }

  function canFetch() {
    return root.location.protocol !== "file:" && !document.getElementById("da-embedded") && typeof root.fetch === "function";
  }

  function getJSON(path) {
    if (!S.cache[path]) {
      S.cache[path] = root.fetch(path).then(function (r) {
        if (!r.ok) throw new Error(path + " answered " + r.status);
        return r.json();
      });
      S.cache[path].catch(function () { delete S.cache[path]; });
    }
    return S.cache[path];
  }

  function seedPath(n) {
    return "replay/seed" + n + ".json";
  }

  function start() {
    if (S.status !== "idle") return;
    if (!canFetch()) {
      S.status = "unavailable";
      return;
    }
    S.status = "loading";
    getJSON("replay/all_seeds.json").then(function (all) {
      var first = all.seeds.indexOf(EXAMPLE_SEED) >= 0 ? EXAMPLE_SEED : all.seeds[0];
      S.all = all;
      return getJSON(seedPath(first)).then(function (d) {
        useSeed(first, d);
        S.status = "ready";
      });
    }).catch(function (err) {
      S.status = "unavailable";
      S.error = (err && err.message) || String(err);
    }).then(refresh);
  }

  function useSeed(n, d) {
    S.seed = n;
    S.d = d;
    S.max = 1;
    S.shown = 0;
    S.shownPost = 0;
    S.change = 0;
    S.vote = null;
  }

  // A new seed keeps the reader on the same step, with the steps before it completed.
  function pickSeed(n, step) {
    if (n === S.seed || n === S.loadingSeed) return;
    S.loadingSeed = n;
    getJSON(seedPath(n)).then(function (d) {
      if (S.loadingSeed !== n) return;
      S.loadingSeed = null;
      useSeed(n, d);
      reach(step);
      refresh();
    }, function (err) {
      S.loadingSeed = null;
      ui.toast("Seed " + n + " could not be loaded: " + ((err && err.message) || String(err)), { kind: "error" });
      refresh();
    });
  }

  /* The sequence -------------------------------------------------------------------------- */

  function firstChange() { return S.d.meta.changes[0].round; }
  function pre() { return S.d.rounds.filter(function (r) { return r.round < firstChange(); }); }
  function post() { return S.d.rounds.filter(function (r) { return r.round >= firstChange(); }); }
  function nChanges() { return S.d.meta.changes.length; }

  function done(step) {
    switch (step) {
      case 2: return S.shown >= pre().length;
      case 3: return S.change >= nChanges();
      case 4: return S.shownPost >= post().length;
      case 6: return S.vote !== null;
      default: return true;
    }
  }

  function canNext(step) {
    return step < STEPS.length && done(step);
  }

  // The rule for links: opening step n directly shows every step before it completed, so a
  // linked step always has its data. Only the vote in step 6 is left to the reader.
  function reach(step) {
    if (step <= S.max) return;
    if (step > 2) S.shown = pre().length;
    if (step > 3) S.change = nChanges();
    if (step > 4) S.shownPost = post().length;
    S.max = step;
  }

  function go(step) {
    DA.router.go({ page: "case-study", step: step });
  }

  /* Small pieces -------------------------------------------------------------------------- */

  function edit(r) {
    return r.incumbent === r.candidate ? r.incumbent + " (same text)" : r.incumbent + " to " + r.candidate;
  }

  function fmtNum(x) {
    return x === null || x === undefined ? "none" : String(+(+x).toFixed(4));
  }

  function bracket(lo, hi) {
    return "[" + fmt.num(lo, 2) + ", " + fmt.num(hi, 2) + "]";
  }

  function decisionTag(accepted) {
    return accepted ? ui.tag("promoted", "info") : ui.tag("kept", "quiet");
  }

  function envNow(step) {
    return step >= 3 && S.change > 0 ? S.d.meta.changes[S.change - 1].env : "E1";
  }

  function sameTextNote(hasRow) {
    if (!hasRow) return "";
    return html`<p class="cs-note">"Same text": the proposer's reply could not be parsed, so the candidate is the current instruction unchanged. The rule can still promote it, and because accuracy cannot rise it counts as a false accept. This happens once among the frozen rule's ${S.all.policies.P1.false_accepts} false accepts.</p>`;
  }

  function lede(text) {
    return html`<p class="cs-lede">${text}</p>`;
  }

  function section(title, body, cls) {
    return html`<section class="${"cs-section" + (cls ? " " + cls : "")}"><h3>${title}</h3>${body}</section>`;
  }

  /* Step 2 chart: accuracy of the current instruction after each round -------------------- */

  function drawAccuracy(values, labels, W, H, label) {
    var m = { l: 44, r: 12, t: 10, b: 28 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
    var lo = 0.5, hi = 0.9, n = Math.max(labels.length - 1, 1), parts = [], pts;
    function X(i) { return m.l + pw * i / n; }
    function Y(v) { return m.t + ph * (hi - v) / (hi - lo); }
    [0.5, 0.6, 0.7, 0.8, 0.9].forEach(function (t) {
      parts.push(html`<line class="c-grid" x1="${m.l}" x2="${m.l + pw}" y1="${Y(t)}" y2="${Y(t)}"/>
        <text x="${m.l - 8}" y="${Y(t)}" dy="0.32em" text-anchor="end">${Math.round(100 * t) + "%"}</text>`);
    });
    labels.forEach(function (t, i) {
      parts.push(html`<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${t}</text>`);
    });
    pts = values.map(function (v, i) { return [Math.round(X(i) * 100) / 100, Math.round(Y(v) * 100) / 100]; });
    if (pts.length > 1) parts.push(html`<polyline class="c-line" points="${pts.map(function (p) { return p.join(","); }).join(" ")}"/>`);
    pts.forEach(function (p) {
      parts.push(html`<circle class="c-point" cx="${p[0]}" cy="${p[1]}" r="3.5"/>`);
    });
    return html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">${parts}</svg>`;
  }

  function accuracyChart(values, labels) {
    var label = "Accuracy by round: " + labels.map(function (t, i) { return t + " " + fmt.pct(values[i]); }).join(", ") + ".";
    return html`<figure class="chart cs-acc">
      <div class="cs-acc__wide">${drawAccuracy(values, labels, 460, 230, label)}</div>
      <div class="cs-acc__narrow">${drawAccuracy(values, labels, 340, 210, label)}</div>
    </figure>`;
  }

  /* Step 9 diagram ------------------------------------------------------------------------ */

  var BOXES = {
    proposer: ["Proposer", "writes a candidate"],
    comparison: ["Comparison", "wins and losses"],
    rule: ["Promotion rule", "wins > losses"],
    store: ["Reference store", "outputs, answers, version"],
    tracker: ["Environment tracker", "version fingerprint"],
    rerun: ["Reference rerun", ""],
    truth: ["Ground truth check", "same environment"]
  };

  // Each drawing has its own marker id, since the wide and the narrow drawing share a page.
  function drawSystem(layout, W, H, label, id) {
    var bw = 150, bh = 46, parts = [], head = "cs-arrow-" + id;
    function mid(id, side) {
      var p = layout.at[id];
      if (side === "l") return [p[0], p[1] + bh / 2];
      if (side === "r") return [p[0] + bw, p[1] + bh / 2];
      if (side === "t") return [p[0] + bw / 2, p[1]];
      return [p[0] + bw / 2, p[1] + bh];
    }
    layout.links.forEach(function (l) {
      var pts = [mid(l[0], l[1])].concat(l[4] || [], [mid(l[2], l[3])]);
      parts.push(html`<polyline class="cs-diagram__link" points="${pts.map(function (p) { return p.join(","); }).join(" ")}" marker-end="${"url(#" + head + ")"}"/>`);
    });
    Object.keys(layout.at).forEach(function (id) {
      var p = layout.at[id], b = BOXES[id];
      parts.push(html`<rect class="cs-diagram__box" x="${p[0] + 0.5}" y="${p[1] + 0.5}" width="${bw - 1}" height="${bh - 1}"/>
        <text class="c-strong" x="${p[0] + bw / 2}" y="${p[1] + (b[1] ? 20 : 27)}" text-anchor="middle">${b[0]}</text>
        ${b[1] ? html`<text x="${p[0] + bw / 2}" y="${p[1] + 36}" text-anchor="middle">${b[1]}</text>` : ""}`);
    });
    return html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}"><defs><marker id="${head}" class="cs-diagram__head" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0 10 5 0 10Z"/></marker></defs>${parts}</svg>`;
  }

  function systemDiagram() {
    var label = "Data flow between components. The proposer writes a candidate for the comparison, which counts wins and losses against the reference store and passes them to the promotion rule. The environment tracker and the reference rerun feed the reference store. The ground truth check follows the promotion rule.";
    var wide = {
      at: { proposer: [0, 10], comparison: [275, 10], rule: [550, 10], tracker: [0, 100], store: [275, 100], rerun: [275, 180], truth: [550, 100] },
      links: [["proposer", "r", "comparison", "l"], ["comparison", "r", "rule", "l"], ["store", "t", "comparison", "b"],
        ["tracker", "r", "store", "l"], ["rerun", "t", "store", "b"], ["rule", "b", "truth", "t"]]
    };
    var narrow = {
      at: { proposer: [0, 0], comparison: [0, 76], rule: [180, 76], store: [0, 152], truth: [180, 152], rerun: [0, 228], tracker: [180, 228] },
      links: [["proposer", "b", "comparison", "t"], ["comparison", "r", "rule", "l"], ["store", "t", "comparison", "b"],
        ["rule", "b", "truth", "t"], ["rerun", "t", "store", "b"], ["tracker", "l", "store", "r", [[165, 251], [165, 175]]]]
    };
    return html`<figure class="chart cs-diagram">
      <div class="chart__wide">${drawSystem(wide, 700, 230, label, "wide")}</div>
      <div class="chart__narrow">${drawSystem(narrow, 330, 276, label, "narrow")}</div>
    </figure>`;
  }

  /* Screens ------------------------------------------------------------------------------- */

  function gradeText(x) {
    if (x.strict_correct) return "right under both readers";
    return x.lenient_correct ? "wrong strictly, right leniently" : "wrong under both readers";
  }

  function verdict(ok) {
    return ok ? "right" : ui.tag("wrong", "error");
  }

  function screen1() {
    var d = S.d, qs = S.all.questions, q = qs[S.q] || qs[0];
    var list = qs.map(function (x, i) {
      return html`<li><button type="button" class="${"cs-q" + (i === S.q ? " is-selected" : "")}" data-cs-q="${i}" data-key="${"cs-q-" + i}" aria-pressed="${i === S.q ? "true" : "false"}">${x.question}<span class="cs-q__meta">item ${x.index}, gold ${fmtNum(x.gold)}, ${gradeText(x)}</span></button></li>`;
    });
    var raw = q.raw
      ? html`${ui.kv([{ key: "Strict reads", value: fmtNum(q.answer_v1) }, { key: "Lenient reads", value: fmtNum(q.answer_v2) }])}
        <h4>Calculation lines, recomputed here (shown, not graded)</h4>
        <ul class="cs-trace">${q.steps && q.steps.length ? q.steps.map(function (s) {
          return html`<li><span class="cs-trace__tick">${s.ok ? "checks" : ui.tag("off", "error")}</span><span>${s.text}</span></li>`;
        }) : html`<li class="muted">No line of the form a op b = c.</li>`}</ul>
        ${ui.disclosure({ summary: "Model output", body: html`<pre class="cs-raw">${q.raw}</pre>`, key: "cs-raw" })}`
      : html`<p class="cs-note">This replay carries the measured grade of every answer, not the answer text itself.</p>`;
    return html`
      ${ui.notice({ kind: "info", body: html`These screens replay files written by <code>toolkit/export_replay.py</code>. The numbers on them are precomputed; the <a href="#/">workbench</a> next door recomputes the same audit in the browser from the run logs.` })}
      ${lede("An agent rewrites its own instruction and keeps a new one only if it beats a stored reference. These are five recorded runs of that loop on GSM8K. Start with a question.")}
      <div class="grid cs-cols">
        <div class="span-5"><ul class="cs-qlist" aria-label="Questions" data-key="cs-qlist">${list}</ul></div>
        <div class="span-7 cs-panel">
          <h3>${q.question}</h3>
          ${ui.kv([{ key: "Gold answer", value: fmtNum(q.gold) }, { key: "Strict reader", value: verdict(q.strict_correct) }, { key: "Lenient reader", value: verdict(q.lenient_correct) }])}
          ${!q.strict_correct && q.lenient_correct ? ui.notice({ kind: "warning", body: "Same saved answer, two grades. Only the reader changed." }) : ""}
          ${raw}
        </div>
      </div>
      ${ui.disclosure({ summary: "Starting instruction", body: html`<p class="cs-prompt">${d.prompts.p0}</p>`, key: "cs-p0" })}`;
  }

  function loopTable(rows) {
    return ui.ledger({
      key: "cs-loop", caption: "Rounds so far", empty: "No round has run yet.", rows: rows,
      rowClass: function (r, i) { return i === rows.length - 1 ? "is-selected" : null; },
      columns: [
        { label: "Round", num: true, tight: true, key: "round" },
        { label: "Current to candidate", cell: edit },
        { label: "Wins vs p0", num: true, key: "wins" },
        { label: "Losses vs p0", num: true, key: "losses" },
        { label: "Decision", cell: function (r) { return decisionTag(r.accepted); } },
        { label: "Accuracy", num: true, cell: function (r) { return fmt.pct(r.acc_after); } }
      ]
    });
  }

  function screen2() {
    var d = S.d, rs = pre(), shown = rs.slice(0, S.shown), ref = d.meta.reference, last = shown[shown.length - 1];
    var falses = shown.filter(function (r) { return r.false_accept; });
    var all = S.shown >= rs.length;
    return html`
      ${lede("Each round the agent proposes a candidate instruction and scores it against the stored reference on the same " + d.meta.n_items + " questions. It is promoted if it wins more questions than it loses. Under the frozen rule replayed here, the reference stays the starting instruction p0 for the whole run: every candidate is compared with p0's saved answers, not with the instruction it would replace.")}
      ${section("What the stored reference records", ui.kv([
        { key: "Reference instruction", value: "p0, version " + ref.prompt_hash },
        { key: "Raw outputs and extracted answers", value: ref.n_outputs + " saved answers, each with its grade" },
        { key: "Environment version", value: html`${ref.env}, <code>${ref.fingerprint}</code>` },
        { key: "Scorer version", value: ref.scorer }
      ]))}
      <div class="grid cs-cols">
        <section class="span-7 cs-section">
          <h3>Rounds so far</h3>
          ${loopTable(shown)}
          ${sameTextNote(shown.some(function (r) { return r.incumbent === r.candidate; }))}
          <p class="cs-actions"><button type="button" class="btn" data-cs-action="round" data-key="cs-round"${ui.attrs({ disabled: all })}>${all ? "All rounds before the first change shown" : "Run round " + rs[S.shown].round}</button></p>
        </section>
        <section class="span-5 cs-section">
          <h3>Scoreboard</h3>
          ${accuracyChart([d.meta.baseline_strict_acc].concat(shown.map(function (r) { return r.acc_after; })), ["start"].concat(shown.map(function (r) { return "R" + r.round; })))}
          <p class="cs-note">Accuracy of the current instruction on the ${d.meta.n_items} questions, in the environment in force. ${falses.length
            ? "A promotion already lowered accuracy (round " + falses.map(function (r) { return r.round; }).join(", ") + "). That is ordinary noise in a 200-question comparison, before anything has changed; step 5 counts it separately."
            : "Nothing looks wrong yet."}</p>
        </section>
      </div>
      ${last ? section("Latest decision", html`<p>Candidate ${last.candidate} wins ${last.wins} and loses ${last.losses} questions against p0's saved answers, so the frozen rule ${last.accepted ? "promotes it" : "keeps the current instruction"}.</p>`) : ""}`;
  }

  function screen3(step) {
    var d = S.d, ch = d.meta.changes, inf = S.all.inflation, f = d.meta.extractor_flips, n = S.all.seeds.length;
    var next = ch[S.change], out = [], af, now = envNow(step);
    var button = next
      ? html`<button type="button" class="btn cs-change" data-cs-action="change" data-key="cs-change">Apply change ${S.change + 1} of ${ch.length}: round ${next.round}, ${next.text.toLowerCase().replace(/\.$/, "")}</button>`
      : html`<button type="button" class="btn" data-key="cs-change" disabled>Both changes applied</button>`;
    if (S.change >= 1) {
      out.push(section("Change 1: decoding", html`<p>A regenerated reference now produces different text from the stored one, because the model samples. Across all ${n} seeds this alone shows no consistent drift inflation: mean <span class="num">${fmt.pp(inf.E2.mean, 2, true)}</span>, 95% interval ${bracket(inf.E2.lo, inf.E2.hi)}, and the sign differs between seeds (${inf.E2.seeds_same_sign} of ${n} agree).</p>`));
    }
    if (S.change >= 2) {
      af = S.all.answer_flips;
      out.push(section("Change 2: the extractor becomes lenient", html`
        <p>The agent, the questions and the gold answers stay the same; only the reader of the answers changes. The strict extractor reads only a plain number; the lenient one also reads commas, dollar signs, units and some fallbacks, and it never rejects an answer the strict one accepts.</p>
        ${ui.ledger({
          key: "cs-extract", caption: "What each extractor reads", dense: true, rows: EXTRACTOR_EXAMPLES,
          columns: [
            { label: "Model wrote", mono: true, cell: function (r) { return r[0]; } },
            { label: "Strict reads", mono: true, cell: function (r) { return r[1]; } },
            { label: "Lenient reads", mono: true, cell: function (r) { return r[2]; } }
          ]
        })}
        <p class="cs-note">Examples from the repository's extractor tests.</p>
        <p>Across every instruction in the five runs, <strong class="num">${fmt.int(af.wrong_to_right)} of ${fmt.int(af.items)}</strong> saved answers go from wrong to right under the lenient reader, and <strong class="num">${af.right_to_wrong}</strong> go the other way. For this seed's starting instruction it is ${f.wrong_to_right} of ${f.n}.</p>
        <p>Isolating the extractor change alone (reference age ${S.all.age} rounds, all seeds), drift inflation is <strong class="num">${fmt.pp(inf.E3.mean, 2, true)}</strong> with a 95% interval of ${bracket(inf.E3.lo, inf.E3.hi)}, positive on ${inf.E3.seeds_same_sign} of ${n} seeds.</p>`));
    }
    return html`
      ${lede("While the loop runs, the deployment changes underneath it, and the loop is not told. Press the button to apply the next change in the order it happened in the saved runs. The environment badge follows the paper's labels: E2 for a decoding change, E3 for an extractor change, E4 when both have changed.")}
      <div class="cs-bench stack stack--1">
        <p>Environment in force: ${ui.tag(now, S.change ? "warning" : null)} ${d.envs[now]}</p>
        <p>${button}</p>
        <p class="cs-note">The press reveals the next part of a saved run. The changes happen at rounds ${ch.map(function (c) { return c.round; }).join(" and ")} in the data either way.</p>
      </div>
      ${out}`;
  }

  function inflationFigure() {
    var inf = S.all.inflation, envs = ["E1", "E2", "E3", "E4"], n = S.all.seeds.length;
    var above = envs.map(function (e) {
      return ENV_NAME[e].toLowerCase() + " " + inf[e].per_seed.filter(function (v) { return v > 0; }).length + " of " + inf[e].per_seed.length;
    });
    return section("All " + n + " seeds, reference age " + S.all.age + " rounds", html`
      ${DA.charts.intervals(envs.map(function (e) {
        return { label: ENV_NAME[e], mean: inf[e].mean, lo: inf[e].lo, hi: inf[e].hi, values: inf[e].per_seed };
      }), { unit: "pp", caption: "Mean drift inflation with 95% interval, all " + n + " seeds" })}
      <p class="cs-note">Drift inflation in percentage points of ${S.all.n_items} questions, over all ${n} seeds; the short ticks are the seeds. The rows share one scale around zero; a filled dot marks an interval that excludes zero. Seeds above zero: ${fmt.list(above)}. Only the extraction change and the multiple changes qualify. The decoding change is not distinguishable from the unchanged control.</p>`, "cs-figure");
  }

  function screen4() {
    var d = S.d, rs = post(), shown = rs.slice(0, S.shownPost), all = S.shownPost >= rs.length;
    var mean = shown.length ? shown.reduce(function (a, r) { return a + r.inflation_pp; }, 0) / shown.length : null;
    return html`
      ${lede("After the changes, candidates are still scored against the stored reference: the starting instruction p0's answers, read the old way. The candidate is read the new way. \"Rerun\" means p0 regenerated and read under today's environment: the rerun reference. Drift inflation is the candidate's win rate against the stored reference minus its win rate against the rerun one.")}
      <section class="cs-section">
        <h3>Candidates after the first change</h3>
        ${ui.ledger({
          key: "cs-trap", caption: "Candidates after the first change", empty: "No candidate scored yet.", rows: shown,
          rowClass: function (r, i) { return i === shown.length - 1 ? "is-selected" : null; },
          columns: [
            { label: "Round", num: true, tight: true, key: "round" },
            { label: "Env", key: "env" },
            { label: "Current to candidate", cell: edit },
            { label: "Wins / losses vs p0, stored", num: true, cell: function (r) { return r.wins + " / " + r.losses; } },
            { label: "Decision", cell: function (r) { return decisionTag(r.accepted); } },
            { label: "Wins / losses vs p0, rerun", num: true, cell: function (r) { return r.fresh_wins + " / " + r.fresh_losses; } },
            { label: "Rerun promotes", cell: function (r) { return r.fresh_wins > r.fresh_losses ? "yes" : "no"; } },
            { label: "Drift inflation", num: true, cell: function (r) { return fmt.pp(r.inflation_pp, 1, true); } }
          ]
        })}
        ${sameTextNote(shown.some(function (r) { return r.incumbent === r.candidate; }))}
        <p class="cs-actions">
          <button type="button" class="btn" data-cs-action="score" data-key="cs-score"${ui.attrs({ disabled: all })}>${all ? "All candidates shown" : "Score the round " + rs[S.shownPost].round + " candidate"}</button>
          ${all ? "" : html`<button type="button" class="linklike" data-cs-action="score-all" data-key="cs-score-all">Show all</button>`}
        </p>
        ${mean !== null ? html`<p class="cs-text">Mean drift inflation over these ${shown.length} decisions on this seed: <strong class="num">${fmt.pp(mean, 2, true)}</strong> (percentage points of ${d.meta.n_items} questions). This is measured against p0, so the reference gets older every round; the all-seed table below fixes the reference age at ${S.all.age} rounds, so the two numbers are not directly comparable.</p>` : ""}
      </section>
      ${all ? inflationFigure() : ""}`;
  }

  function screen5() {
    var d = S.d, fp = d.rounds.filter(function (r) { return r.false_accept; }), fc = S.all.false_promotion_causes, n = S.all.seeds.length;
    var count = function (k) { return fp.filter(function (r) { return r.cause === k; }).length; };
    var e2 = fp.filter(function (r) { return r.cause === "stale" && r.env === "E2"; });
    var chart = DA.charts.netGain({
      rounds: d.rounds.map(function (r) {
        return { round: r.round, env: r.env + " " + ENV_NAME[r.env].toLowerCase(), stored: r.stale_net_pp, rerun: r.fresh_net_pp,
          mark: r.false_accept ? "false-accept" : r.accepted ? "improved" : null };
      }),
      flags: d.meta.changes.map(function (c) { return { round: c.round, name: c.env + " " + ENV_NAME[c.env].toLowerCase() }; }),
      first: "E1 " + ENV_NAME.E1.toLowerCase(),
      selected: null
    });
    var verdictBlock = fp.length
      ? html`<p>${ui.tag("false accept", "error")}</p>
        <p>On this seed the frozen rule promotes ${fp.length === 1 ? "1 candidate that is" : fp.length + " candidates that are"} not better than the instruction ${fp.length > 1 ? "they replace" : "it replaces"}. The causes differ. The test applies the same promotion rule against the rerun reference: when the rerun reference would reject the candidate, the promotion is counted as a stale reference.</p>
        <p data-cs-seed-causes>Causes on this seed: ${CAUSE.stale} <strong class="num">${count("stale")}</strong>, ${CAUSE.anyway} <strong class="num">${count("anyway")}</strong>, ${CAUSE.before_change} <strong class="num">${count("before_change")}</strong> (noise in a comparison on ${d.meta.n_items} questions).</p>
        ${ui.ledger({
          key: "cs-false", caption: "False promotions on this seed", rows: fp,
          columns: [
            { label: "Round", num: true, tight: true, key: "round" },
            { label: "Env", key: "env" },
            { label: "Current to candidate", cell: edit },
            { label: "vs p0, stored", num: true, cell: function (r) { return r.wins + " / " + r.losses; } },
            { label: "vs p0, rerun", num: true, cell: function (r) { return r.fresh_wins + " / " + r.fresh_losses; } },
            { label: "Accuracy, candidate / current", num: true, cell: function (r) { return fmt.pct(r.candidate_acc) + " / " + fmt.pct(r.incumbent_acc); } },
            { label: "Cause", cell: function (r) { return r.cause === "stale" ? ui.tag(CAUSE.stale, "warning") : html`<span class="muted">${CAUSE[r.cause] || r.cause}</span>`; } }
          ]
        })}
        ${sameTextNote(fp.some(function (r) { return r.incumbent === r.candidate; }))}
        ${e2.length ? html`<p class="cs-note">Caution: ${e2.map(function (r) { return "round " + r.round; }).join(", ")} fall under the decoding change alone (E2). Across all seeds that change shows no consistent inflation (step 3), so treat ${e2.length > 1 ? "these" : "this one"} as likely noise. The extractor change is the consistent effect.</p>` : ""}
        <p data-cs-all-causes>Across all ${n} seeds the frozen rule makes <strong class="num">${fc.stale + fc.anyway + fc.before_change}</strong> false accepts. By cause: ${CAUSE.stale} <strong class="num">${fc.stale}</strong>, ${CAUSE.anyway} <strong class="num">${fc.anyway}</strong>, ${CAUSE.before_change} <strong class="num">${fc.before_change}</strong>.</p>
        <p class="cs-note">A rerun reference is one regenerated run, so it carries a little noise of its own: with nothing changed, a rerun differs from the stored run by about a tenth of a point on average.</p>`
      : html`<p>${ui.tag("no false accept on this seed", "quiet")}</p><p>Every promotion of the frozen rule on this seed raises accuracy. Choose another seed from the list above to see one where the stale reference changes a decision.</p>`;
    return html`
      ${lede("For every round, two bars: the candidate's net gain (wins minus losses, in points of " + d.meta.n_items + " questions) against the stored reference, p0's saved answers, and against p0 regenerated today. A candidate is promoted when the first bar is above zero. Where the first bar is above zero and the second is not, the stale reference decides.")}
      <section class="cs-section cs-figure">
        <h3>Net gain per round, seed ${d.meta.seed}</h3>
        ${chart}
        <p class="cs-note">Marks under the bars show promoted candidates: a dot if the promotion raises accuracy, a red diamond if it does not. A false accept means the candidate's accuracy is not higher than the incumbent's, with both measured in the environment in force. Promotion and this check use the same ${d.meta.n_items} questions.</p>
      </section>
      <section class="cs-section cs-verdict stack stack--1" aria-label="False promotions">${verdictBlock}</section>`;
  }

  function screen6() {
    var d = S.d, a = S.all, key, p, pooled, result = "";
    var unparsed = function (round) {
      var r = d.rounds.filter(function (x) { return x.round === round; })[0];
      return !!r && r.note === "fallback_unparsed";
    };
    var opts = Object.keys(OPTIONS).map(function (k) {
      return html`<button type="button" class="cs-option" data-cs-vote="${k}" data-key="${"cs-vote-" + k}" aria-pressed="${S.vote === k ? "true" : "false"}"><span class="cs-option__title">${OPTIONS[k].title}</span><span class="cs-option__text">${OPTIONS[k].text}</span></button>`;
    });
    if (S.vote) {
      key = POLICY_FOR_OPTION[S.vote];
      p = d.policies[key];
      pooled = a.policies[key];
      result = html`<section class="cs-section">
        <h3>${OPTIONS[S.vote].title}, seed ${d.meta.seed}</h3>
        <p class="cs-note">Wins and losses are counted against ${REF_TEXT[key]}.</p>
        ${ui.ledger({
          key: "cs-policy", caption: "Decisions under this policy", rows: p.decisions,
          columns: [
            { label: "Round", num: true, tight: true, key: "round" },
            { label: "Env", key: "env" },
            { label: "Candidate", cell: function (x) { return x.candidate + (unparsed(x.round) ? " (same text)" : ""); } },
            { label: "Wins / losses", num: true, cell: function (x) { return x.wins + " / " + x.losses; } },
            { label: "Decision", cell: function (x) { return decisionTag(x.accepted); } },
            { label: "Outcome", cell: function (x) { return x.false_accept ? ui.tag("false accept", "error") : x.false_reject ? ui.tag("false reject", "error") : ""; } },
            { label: "Reference", cell: function (x) { return x.reference_refreshed ? "rerun" : "stored"; } }
          ]
        })}
        ${sameTextNote(p.decisions.some(function (x) { return unparsed(x.round); }))}
        <p>This seed: ${fmt.plural(p.accepted, "promotion")}, ${fmt.plural(p.false_accepts, "false accept")}, ${fmt.plural(p.false_rejects, "false reject")}, ${fmt.plural(p.refreshes, "reference rerun")} and ${fmt.int(p.logical_calls)} logical model calls (estimate).</p>
        <p>All ${a.seeds.length} seeds: <strong class="num">${pooled.false_accepts} of ${pooled.accepted}</strong> promotions were false accepts, and <strong class="num">${pooled.false_rejects}</strong> improvements were turned down as false rejects.</p>
        ${ui.ledger({
          key: "cs-pooled", caption: "All three policies over all seeds", rows: Object.keys(OPTIONS),
          rowClass: function (k) { return k === S.vote ? "is-selected" : null; },
          columns: [
            { label: "All " + a.seeds.length + " seeds", head: true, cell: function (k) { return OPTIONS[k].title + (k === S.vote ? " (your pick)" : ""); } },
            { label: "False accepts", num: true, cell: function (k) { var q = a.policies[POLICY_FOR_OPTION[k]]; return q.false_accepts + " of " + q.accepted; } },
            { label: "False rejects", num: true, cell: function (k) { return a.policies[POLICY_FOR_OPTION[k]].false_rejects; } },
            { label: "Logical calls (est.)", num: true, cell: function (k) { return fmt.int(a.policies[POLICY_FOR_OPTION[k]].logical_calls[0]); } }
          ]
        })}
        <p class="cs-note">All three policies choose among the same candidates and are scored on the same questions. Call counts are an estimate from a dry run.</p>
      </section>`;
    }
    return html`
      ${lede("Pick the refresh policy you would deploy. The three policies run over the same candidates, so their counts compare directly.")}
      <div class="cs-options" role="group" aria-label="Defenses">${opts}</div>
      ${result}`;
  }

  function screen7() {
    var a = S.all, P = a.policies, n = a.seeds.length, ids = ["P1", "P2", "P3"];
    var maxCalls = Math.max.apply(null, ids.map(function (p) { return P[p].logical_calls[0]; }));
    var fa = DA.charts.bars(ids.map(function (p) {
      return { label: SHORT[p], value: P[p].false_accepts / P[p].accepted, tone: "red", text: P[p].false_accepts + "/" + P[p].accepted };
    }), { max: 1, caption: "False accepts over promotions, pooled over " + n + " seeds" });
    var acc = DA.charts.bars(ids.map(function (p) {
      return { label: SHORT[p], value: P[p].final_acc[0], sd: P[p].final_acc[1], text: fmt.pct(P[p].final_acc[0]) + " ± " + fmt.num(100 * P[p].final_acc[1], 1) };
    }), { max: 1, caption: "Final accuracy, mean and one standard deviation over seeds" });
    var calls = DA.charts.bars(ids.map(function (p) {
      return { label: SHORT[p], value: P[p].logical_calls[0], tone: "steel", text: fmt.int(P[p].logical_calls[0]) };
    }), { max: maxCalls, caption: "Logical model calls per run, estimated" });
    return html`
      ${lede("All " + n + " seeds, same candidates and questions for every policy. False accepts are pooled counts; accuracy is the mean over seeds ± one standard deviation.")}
      <div class="grid cs-dash">
        <section class="span-4 cs-section" data-cs-panel="false-accepts">
          <h3>False accepts</h3>
          ${fa}
          <p class="cs-note">Promotions that were not improvements, over all promotions, pooled across seeds. False rejects: ${ids.map(function (p) { return SHORT[p].toLowerCase() + " " + P[p].false_rejects; }).join(", ")}.</p>
        </section>
        <section class="span-4 cs-section">
          <h3>Final accuracy</h3>
          ${acc}
          <p class="cs-note">Accuracy of the final instruction in the last environment, mean ± one standard deviation over seeds. The gaps are within one standard deviation, so the false-accept counts are the clearer evidence.</p>
        </section>
        <section class="span-4 cs-section" data-cs-panel="calls">
          <h3>Logical model calls <span class="muted">(estimate)</span></h3>
          ${calls}
          <p class="cs-note">Per run, from a dry run of each policy. Not measured inference cost.</p>
        </section>
      </div>
      ${ui.disclosure({
        summary: "False accepts and promotions by seed", key: "cs-by-seed",
        body: ui.ledger({
          key: "cs-seeds", caption: "False accepts and promotions by seed", rows: a.seeds,
          columns: [
            { label: "Seed", num: true, tight: true, cell: function (s) { return s; } },
            { label: "Frozen", num: true, cell: function (s) { return a.per_seed[s].P1.false_accepts + "/" + a.per_seed[s].P1.accepted; } },
            { label: "Every batch", num: true, cell: function (s) { return a.per_seed[s].P2.false_accepts + "/" + a.per_seed[s].P2.accepted; } },
            { label: "On change", num: true, cell: function (s) { return a.per_seed[s].P3.false_accepts + "/" + a.per_seed[s].P3.accepted; } },
            { label: "False promotion rounds (frozen)", num: true, cell: function (s) { var r = a.per_seed[s].false_promotion_rounds; return r.length ? r.join(", ") : "none"; } }
          ]
        })
      })}
      <p class="cs-bigline">Replayed on the same candidates, a reference rerun when the environment changes gives ${P.P3.false_accepts} false accepts in ${P.P3.accepted} promotions, against ${P.P1.false_accepts} in ${P.P1.accepted} for a frozen reference, at about ${Math.round(100 * (P.P3.logical_calls[0] / P.P1.logical_calls[0] - 1))}% more model calls.</p>`;
  }

  function screen8() {
    var a = S.all, P = a.policies, vf = a.verdict_flips, w = vf.widest, dom = DOMAINS[S.app];
    var gsmResults = "Measured. False accepts " + ["P1", "P2", "P3"].map(function (p) { return P[p].false_accepts + "/" + P[p].accepted; }).join(", ") +
      " for the three policies; drift inflation from the extractor change " + fmt.pp(a.inflation.E3.mean) + " pp " + bracket(a.inflation.E3.lo, a.inflation.E3.hi) + ".";
    function reading(ex) {
      return html`<code>${ex[0]}</code><br><span class="muted">before:</span> ${ex[1]}<br><span class="muted">after:</span> ${ex[2]}`;
    }
    function cell(row, col, isGsm) {
      if (row === "example") return reading(col.example);
      if (row === "loop") return isGsm ? col.loop : "Reused unchanged.";
      if (row === "results") return isGsm ? gsmResults : html`<span class="cs-alarm">None reported.</span> Would need a run on this task.`;
      return col[row];
    }
    return html`
      ${lede("None of the parts depends on arithmetic. Each needs a reference stored with its environment version, a way of running or reading outputs that can change, an independent check, and the three refresh rules. The left column is what the runs on this site used. The right column shows the same parts for another task. It is an illustration: no runs were made on these tasks and no results are reported for them.")}
      ${ui.tabs({ name: "cs-app", label: "Task", value: S.app, plain: true, items: Object.keys(DOMAINS).map(function (k) { return { id: k, label: k }; }) })}
      ${ui.ledger({
        key: "cs-map", caption: "The parts of the system on GSM8K and on " + S.app, rows: MAP_ROWS,
        columns: [
          { label: "Part of the system", head: true, cell: function (r) { return r[1]; } },
          { label: html`GSM8K, this paper ${ui.tag("measured")}`, cell: function (r) { return cell(r[0], GSM8K_COL, true); } },
          { label: html`${S.app} ${ui.tag("illustration", "quiet")}`, cell: function (r) { return cell(r[0], dom, false); } }
        ]
      })}
      ${section("What carries over from the measurement", html`<p>The mechanism, not the number. On GSM8K, changing only the answer reader changed the verdict (improved, no change or worse) on <strong class="num">${vf.flipped} of ${vf.n}</strong> candidates, with the same instructions and the same saved outputs. The widest case, seed ${w.seed} ${w.cid}, read ${fmt.pp(w.e1_pp, 1, true)} under the strict reader and ${fmt.pp(w.e3_pp, 1, true)} under the lenient one. Any task whose outputs are read by a component that can be updated is exposed to the same effect; how large it is there is unknown until it is measured.</p>`)}
      <p class="cs-text">No runs were made on financial QA or code generation; the right-hand column is an illustration. To run the loop on another task or model, see the <a href="#/install">Install page</a>.</p>`;
  }

  function screen9() {
    return html`
      ${lede("The system is a small Python package that records every reference with the environment it was measured in, and replays decisions under different refresh rules without calling the model again.")}
      <section class="cs-section cs-figure">
        ${systemDiagram()}
        <p class="cs-note">The environment tracker's fingerprint tells the refresh policy when to regenerate the reference. The ground truth check measures both prompts in the environment in force.</p>
      </section>
      ${section("Components", html`<ul class="cs-comps">${COMPONENTS.map(function (c) {
        return html`<li><strong>${c[0]}</strong><span>${c[1]}</span><code>${c[2]}</code></li>`;
      })}</ul>`)}
      ${section("How these files were produced", html`
        <p class="cs-note">These steps ran with the scripts in <code>toolkit/</code>, from inside that folder. These screens only read the precomputed files in <code>replay/</code>.</p>
        ${ui.code(COMMANDS, { label: "Copy commands", done: "Commands copied", key: "cs-commands" })}`)}`;
  }

  var SCREENS = [null, screen1, screen2, screen3, screen4, screen5, screen6, screen7, screen8, screen9];

  /* Frame --------------------------------------------------------------------------------- */

  function seedPicker() {
    var all = S.all;
    return ui.select({
      name: "cs-seed", key: "cs-seed", label: "Run", value: String(S.loadingSeed || S.seed),
      options: all.seeds.map(function (s) {
        return { value: String(s), label: "seed " + s + (s === EXAMPLE_SEED ? " (example)" : all.per_seed[s].false_promotion_rounds.length ? "" : " (no false accept)") };
      })
    });
  }

  function synthetic() {
    return S.d.meta.precomputed === false || S.all.precomputed === false;
  }

  function bench() {
    var m = S.d.meta;
    return html`<div class="cs-bench cs-run">
      ${seedPicker()}
      <p class="cs-run__note">${ui.tag("Replay of recorded runs")}${synthetic() ? html` ${ui.tag("synthetic", "warning")}` : ""} <span>${m.model}, first ${m.n_items} ${m.dataset} test questions, ${m.rounds} rounds, ${S.all.seeds.length} seeds.</span></p>
      ${synthetic() ? html`<p class="cs-run__line">The numbers on these screens are simulated, not measured.</p>` : ""}
    </div>`;
  }

  function stepper(step) {
    var items = STEPS.map(function (title, i) {
      var n = i + 1, cls = "cs-stepper__item" + (n === step ? " is-current" : n < step || n <= S.max ? " is-open" : " is-locked");
      var inner = html`<span class="cs-stepper__n">${n}</span> <span class="cs-stepper__label">${title}</span>`;
      return html`<li class="${cls}">${n <= S.max
        ? html`<a class="cs-stepper__link" href="${DA.router.href({ page: "case-study", step: n })}" data-key="${"cs-step-" + n}"${ui.attrs({ "aria-current": n === step ? "step" : null })}>${inner}</a>`
        : html`<span class="cs-stepper__link" aria-disabled="true">${inner}<span class="visually-hidden"> (opens after step ${n - 1} is completed)</span></span>`}</li>`;
    });
    return html`<nav class="cs-stepper" aria-label="Case study steps">
      <ol class="cs-stepper__list">${items}</ol>
      <div class="cs-stepper__compact">
        <button type="button" class="btn btn--small" data-cs-action="back" data-key="cs-top-back"${ui.attrs({ disabled: step === 1 })}>Previous</button>
        <span class="cs-stepper__where">Step ${step} of ${STEPS.length}</span>
        <button type="button" class="btn btn--small" data-cs-action="next" data-key="cs-top-next"${ui.attrs({ disabled: !canNext(step) })}>Next</button>
      </div>
    </nav>`;
  }

  function statusLine(step) {
    var now, pooled = step === 7 || step === 8;
    if (step < 2) return "";
    now = envNow(step);
    return html`<p class="cs-status">
      ${step <= 6 ? html`<span>Environment ${ui.tag(now, S.change && step >= 3 ? "warning" : null)} ${S.d.envs[now]}</span>` : ""}
      <span class="muted">${pooled ? "all " + S.all.seeds.length + " seeds, measured in advance" : "seed " + S.d.meta.seed + ", measured in advance"}</span>
    </p>`;
  }

  function header() {
    return html`<header class="cs-head">
      <h1>Environment drift in self-improving LLM agents</h1>
      <p class="cs-dek">An interactive replay of five measured runs on GSM8K.</p>
    </header>`;
  }

  function skeleton() {
    return html`<div class="cs-skeleton" aria-busy="true"><span class="visually-hidden">Loading the replay.</span><i></i><i></i><i></i><i></i></div>`;
  }

  function unavailable() {
    return ui.notice({
      kind: "info", title: "The case study needs the hosted site or driftaudit demo",
      body: html`<p>Its nine steps read replay files from the site, which a single-file report or a page opened from disk cannot do. Open the <a href="${HOSTED}">hosted case study</a>, or run <code>driftaudit demo</code> to serve the same pages from your machine.${S.error ? html` The files could not be read: ${S.error}.` : ""}</p>`
    });
  }

  function render(ctx) {
    var step = ctx.route.step || 1;
    start();
    if (S.status === "unavailable") return html`<div class="cs">${header()}${unavailable()}</div>`;
    if (S.status !== "ready") return html`<div class="cs">${header()}${skeleton()}</div>`;
    reach(step);
    return html`<div class="cs">
      ${header()}
      ${bench()}
      ${stepper(step)}
      <section class="cs-step" aria-labelledby="cs-step-title">
        <h2 class="cs-step__title" id="cs-step-title" tabindex="-1"><span class="cs-step__n" aria-hidden="true">${step}</span><span class="visually-hidden">Step ${step} of ${STEPS.length}: </span>${STEPS[step - 1]}</h2>
        ${statusLine(step)}
        <div class="cs-step__body stack stack--4">${SCREENS[step](step)}</div>
        <div class="cs-nav">
          <button type="button" class="btn" data-cs-action="back" data-key="cs-back"${ui.attrs({ disabled: step === 1 })}>Back</button>
          ${step < STEPS.length ? html`<button type="button" class="btn btn--primary" data-cs-action="next" data-key="cs-next"${ui.attrs({ disabled: !canNext(step) })}>Next</button>` : ""}
        </div>
      </section>
    </div>`;
  }

  function act(action, step) {
    switch (action) {
      case "next": if (canNext(step)) go(step + 1); return;
      case "back": if (step > 1) go(step - 1); return;
      case "round": if (S.shown < pre().length) S.shown++; break;
      case "score": if (S.shownPost < post().length) S.shownPost++; break;
      case "score-all": S.shownPost = post().length; break;
      case "change": if (S.change < nChanges()) S.change++; break;
      default: return;
    }
    if (done(step)) focusNext = true;
    refresh();
  }

  function onKey(event) {
    var state = DA.state.get(), t = event.target, step;
    if (state.route.page !== "case-study" || S.status !== "ready") return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    if (t && t.closest && t.closest("input, select, textarea, [contenteditable], [role=tablist], [role=radiogroup], [role=grid], [role=listbox], [data-scroll], pre")) return;
    step = state.route.step || 1;
    if (event.key === "ArrowRight" && canNext(step)) go(step + 1);
    else if (event.key === "ArrowLeft" && step > 1) go(step - 1);
    else return;
    event.preventDefault();
  }

  function bind(rootEl, ctx) {
    var step = ctx.route.step || 1, heading, next;
    if (!keysHooked) {
      keysHooked = true;
      document.addEventListener("keydown", onKey);
    }
    rootEl.addEventListener("click", function (event) {
      var el = event.target.closest ? event.target.closest("[data-cs-action], [data-cs-q], [data-cs-vote]") : null;
      if (!el || el.disabled) return;
      if (el.hasAttribute("data-cs-q")) {
        S.q = Number(el.getAttribute("data-cs-q"));
        refresh();
      } else if (el.hasAttribute("data-cs-vote")) {
        S.vote = el.getAttribute("data-cs-vote");
        refresh();
      } else {
        act(el.getAttribute("data-cs-action"), step);
      }
    });
    rootEl.addEventListener("change", function (event) {
      if (event.target.name === "cs-seed") pickSeed(Number(event.target.value), step);
    });
    ui.on(rootEl, "select", function (detail) {
      if (detail.name === "cs-app" && DOMAINS[detail.value]) {
        S.app = detail.value;
        refresh();
      }
    });
    if (S.status !== "ready") return;
    if (lastStep !== null && lastStep !== step) {
      heading = rootEl.querySelector("#cs-step-title");
      root.scrollTo(0, 0);
      if (heading) heading.focus({ preventScroll: true });
    } else if (focusNext) {
      next = rootEl.querySelector("[data-key=cs-next]");
      if (next && !next.disabled && (!document.activeElement || document.activeElement === document.body)) next.focus();
    }
    focusNext = false;
    lastStep = step;
  }

  DA.views.casestudy = {
    id: "casestudy",
    title: "Case study",
    steps: STEPS,
    render: render,
    bind: bind
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
