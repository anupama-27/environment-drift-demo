"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 1) => `${(100 * x).toFixed(d)}%`;
const signed = (x, d = 2) => `${x >= 0 ? "+" : "-"}${Math.abs(x).toFixed(d)}`;
const int = (x) => Math.round(x).toLocaleString("en-US");
const fmtNum = (x) => (x == null ? "none" : String(+(+x).toFixed(4)));

const STEPS = ["Questions", "The improvement loop", "The drift event", "The trap springs", "The reveal",
  "Which defense?", "Dashboard", "Beyond GSM8K", "The system"];
const POLICY_FOR_OPTION = { A: "P1", B: "P2", C: "P3" };
const OPTIONS = {
  A: { title: "A. Frozen reference", text: "Never refresh. The stored reference is kept for the rest of the run." },
  B: { title: "B. Refresh every batch", text: "Regenerate the reference every round." },
  C: { title: "C. Refresh on environment change", text: "Regenerate the reference once, when the environment version changes." },
};
const LINKS = { Paper: "", Code: "", Video: "" }; // fill in when the URLs exist
const ENV_NAME = { E1: "Unchanged", E2: "Decoding change", E3: "Extraction change", E4: "Multiple changes" };
const SHORT = { P1: "Frozen", P2: "Every batch", P3: "On change" };

const EXTRACTOR_EXAMPLES = [
  ["\\boxed{18}", "18", "18"],
  ["\\boxed{70,000}", "none", "70000"],
  ["\\boxed{\\$15}", "none", "15"],
  ["\\boxed{540 \\text{ meters}}", "none", "540"],
  ["The answer is 1,200.", "none", "1200"],
];

// Rows of the "Beyond GSM8K" mapping. gsm8k is what the runs used; the domain columns are illustration.
const MAP_ROWS = [
  ["task", "Task and gold answers"],
  ["reference", "What the stored reference records"],
  ["change", "An environment change"],
  ["example", "The same output, read before and after"],
  ["check", "Independent check"],
  ["loop", "Loop, refresh policies, metrics"],
  ["supply", "What has to be written"],
  ["results", "Results"],
];
const GSM8K_COL = {
  task: "Grade school word problems. The gold answer is a number.",
  reference: "Instruction p0 and its version, 200 saved answers with their grades, the environment fingerprint and the scorer version.",
  change: "The answer extractor goes from strict (v1) to lenient (v2); decoding goes from greedy to sampling.",
  example: ["\\boxed{70,000}", "no answer, wrong", "70000, right"],
  check: "Both instructions measured in the environment in force.",
  loop: "Promote if wins > losses. Frozen, every batch, or on change. False accepts, inflation, call counts.",
  supply: "Already in the repository.",
  results: null,
};
const DOMAINS = {
  "Financial QA": {
    task: "Numeric questions over earnings reports, in the style of FinQA. Only questions with a numeric gold answer.",
    reference: "The same four records, plus the version of the report the answer was read from.",
    change: "The answer parser is updated to read currency, percent signs and unit scale, or the model version changes.",
    example: ["\\boxed{\\$94 million}", "no answer, wrong", "94, right if gold is in millions"],
    check: "Gold numbers compared after one fixed normalisation of $, %, commas and the unit scale the report declares.",
    supply: "A loader for the questions and gold numbers (drift/data.py); a strict and a lenient reader and the matching tolerance (drift/extract.py); a finance starting instruction (drift/config.py).",
  },
  "Code generation": {
    task: "Programming problems. The gold is a set of unit tests.",
    reference: "The instruction, the generated programs, their test results, and the version of the test runner and interpreter.",
    change: "The test runner starts ignoring whitespace in printed output, or the Python version, a timeout or a library changes.",
    example: ["prints [1, 2, 3] where the test expects [1,2,3]", "exact match, fail", "whitespace ignored, pass"],
    check: "A separate set of unit tests, run in a pinned container that does not change.",
    supply: "A loader for problems and tests (drift/data.py); a test runner in place of the answer extractor, with a strict and a forgiving mode (drift/extract.py); runner and interpreter versions in the fingerprint (drift/envs.py).",
  },
};

const COMPONENTS = [
  ["Reference manager", "Stores the reference prompt, raw outputs and graded answers.", "drift/pipeline.py, RunView.stored"],
  ["Environment version tracker", "Names each environment and its fingerprint.", "drift/envs.py"],
  ["Reference rerun", "Regenerates the reference under today's environment.", "Runner.outputs, RunView.rerun"],
  ["Candidate comparison", "Wins and losses of a candidate against a reference, stored and fresh.", "analysis.pair_measure"],
  ["Ground truth check", "Scores both prompts under the current environment.", "extract.is_correct, RunView.gt_acc"],
  ["Policy comparison", "Replays one candidate pool through three refresh rules.", "analysis.simulate"],
  ["Dashboard", "False accepts, missed gains, inflation and call counts.", "simulate(with_records=True)"],
  ["Reproducibility log", "Every generation is cached by prompt, item, decoding and seed.", "model.Cache, generation_key"],
];

const S = { all: null, cache: {}, seed: null, d: null, step: 1, max: 1, shown: 0, shownPost: 0, change: 0, vote: null, app: "Financial QA", q: 0 };

/* ---------- data ---------- */

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function loadSeed(n) {
  if (!S.cache[n]) S.cache[n] = await getJSON(`replay/seed${n}.json`);
  S.seed = n;
  S.d = S.cache[n];
  Object.assign(S, { step: 1, max: 1, shown: 0, shownPost: 0, change: 0, vote: null });
}

const firstChange = () => S.d.meta.changes[0].round;
const pre = () => S.d.rounds.filter((r) => r.round < firstChange());
const post = () => S.d.rounds.filter((r) => r.round >= firstChange());
const nChanges = () => S.d.meta.changes.length;
const edit = (r) => (r.incumbent === r.candidate ? `${r.incumbent} (same text)` : `${r.incumbent} → ${r.candidate}`);
const EXAMPLE_SEED = 5;
const CAUSE = {
  stale: "caused by the stale reference",
  anyway: "would have happened anyway",
  before_change: "before any change",
};
const REF_TEXT = {
  P1: "the starting instruction p0's saved answers, for the whole run",
  P2: "the current instruction, regenerated every round",
  P3: "the current instruction's saved answers, regenerated when the environment version changes",
};

function sameTextNote(hasRow) {
  if (!hasRow) return "";
  return `<p class="footnote">"Same text": the proposer's reply could not be parsed, so the candidate is the current instruction unchanged. The rule can still promote it, and because accuracy cannot rise it counts as a false promotion. This happens once among the frozen rule's ${S.all.policies.P1.false_accepts} false promotions.</p>`;
}
const envNow = () => (S.step >= 3 && S.change > 0 ? S.d.meta.changes[S.change - 1].env : "E1");

/* ---------- charts (plain SVG) ---------- */

function lineChart({ values, xLabels, yMin, yMax, label, width = 620, height = 230 }) {
  const m = { l: 42, r: 70, t: 14, b: 30 };
  const w = width - m.l - m.r, h = height - m.t - m.b, nx = xLabels.length - 1 || 1;
  const X = (i) => m.l + (w * i) / nx, Y = (v) => m.t + h - (h * (v - yMin)) / (yMax - yMin);
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = yMin + ((yMax - yMin) / 4) * k;
    g += `<line class="tick-line" x1="${m.l}" x2="${m.l + w}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${(100 * v).toFixed(0)}%</text>`;
  }
  xLabels.forEach((t, i) => { g += `<text x="${X(i)}" y="${height - 8}" text-anchor="middle">${esc(t)}</text>`; });
  const pts = values.map((v, i) => [X(i), Y(v)]);
  g += `<polyline class="s-ink" fill="none" stroke-width="2" points="${pts.map((p) => p.join(",")).join(" ")}"/>`;
  g += pts.map((p) => `<circle class="f-ink" cx="${p[0]}" cy="${p[1]}" r="3"/>`).join("");
  const last = pts[pts.length - 1];
  g += `<text class="lbl" x="${last[0] + 8}" y="${last[1] + 4}">${esc(label)}</text>`;
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)} by round">${g}</svg>`;
}

function gainChart(rounds, changes) {
  const width = 660, height = 270, m = { l: 44, r: 12, t: 40, b: 34 };
  const w = width - m.l - m.r, h = height - m.t - m.b, slot = w / rounds.length;
  const maxAbs = Math.max(4, ...rounds.flatMap((r) => [Math.abs(r.stale_net_pp), Math.abs(r.fresh_net_pp)]));
  const lim = Math.ceil(maxAbs / 2) * 2;
  const Y = (v) => m.t + h / 2 - (h / 2) * (v / lim);
  let g = "";
  for (const v of [-lim, -lim / 2, 0, lim / 2, lim]) g += `<line class="${v === 0 ? "zero" : "tick-line"}" x1="${m.l}" x2="${m.l + w}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${signed(v, 0)}</text>`;
  rounds.forEach((r, i) => {
    const x0 = m.l + slot * i, bw = slot * 0.34, cx = x0 + slot / 2;
    const bar = (v, dx, tone) => `<rect class="${tone}" x="${cx + dx}" y="${v >= 0 ? Y(v) : Y(0)}" width="${bw}" height="${Math.max(Math.abs(Y(v) - Y(0)), 1)}" rx="2"/>`;
    g += bar(r.stale_net_pp, -bw - 1, "f-ink") + bar(r.fresh_net_pp, 1, "f-soft");
    g += `<text x="${cx}" y="${height - 16}" text-anchor="middle">${r.round}</text>`;
    if (r.accepted) g += `<text class="${r.false_accept ? "f-accent" : ""}" x="${cx}" y="${height - 3}" text-anchor="middle">${r.false_accept ? "false" : "ok"}</text>`;
  });
  for (const c of changes) {
    const i = rounds.findIndex((r) => r.round === c.round);
    if (i < 0) continue;
    const x = m.l + slot * i;
    g += `<line class="s-accent" x1="${x}" x2="${x}" y1="${m.t - 8}" y2="${m.t + h}" stroke-width="1.5"/><text class="f-accent" x="${x + 4}" y="${m.t - 6}">${c.env}</text>`;
  }
  g += `<rect class="f-ink" x="${m.l}" y="2" width="9" height="9" rx="2"/><text x="${m.l + 13}" y="10">vs stored reference</text><rect class="f-soft" x="${m.l + 140}" y="2" width="9" height="9" rx="2"/><text x="${m.l + 153}" y="10">vs regenerated reference</text>`;
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Net gain of each candidate by round">${g}</svg>`;
}

function inflationTable(inflation) {
  const lim = 2, half = 70;
  const bar = (r) => {
    const len = (Math.min(Math.abs(r.mean), lim) / lim) * half, sig = r.lo > 0 || r.hi < 0;
    return `<svg class="mbar" viewBox="0 0 ${2 * half} 12" aria-hidden="true"><rect class="${sig ? "f-accent" : "f-soft"}" x="${r.mean >= 0 ? half : half - len}" y="2" width="${len}" height="8"/><line class="zero" x1="${half}" x2="${half}" y1="0" y2="12"/></svg>`;
  };
  const rows = ["E1", "E2", "E3", "E4"].map((e) => {
    const r = inflation[e], up = r.per_seed.filter((v) => v > 0).length;
    return `<tr><td>${ENV_NAME[e]}</td><td class="r">${signed(r.mean)}</td><td>${bar(r)}</td><td class="r">${signed(r.lo)} to ${signed(r.hi)}</td><td class="r">${up} of ${r.per_seed.length}</td></tr>`;
  }).join("");
  return `<table class="ledger"><thead><tr><th>Environment</th><th class="r">Mean inflation (pp)</th><th></th><th class="r">95% interval</th><th class="r">Seeds above 0</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function bars(rows, { max, fmt }) {
  const w = 400, rowH = 28, lab = 130, span = w - lab - 70;
  let g = "";
  rows.forEach((r, i) => {
    const y = i * rowH + 4, len = (span * r.value) / max, sd = r.sd ? (span * r.sd) / max : 0;
    g += `<text class="lbl" x="0" y="${y + 13}">${esc(r.label)}</text><rect class="f-${r.tone}" x="${lab}" y="${y + 2}" width="${Math.max(len, 1)}" height="15" rx="2"/>`;
    if (sd) g += `<line class="s-soft" x1="${lab + len - sd}" x2="${lab + len + sd}" y1="${y + 9.5}" y2="${y + 9.5}" stroke-width="2"/>`;
    g += `<text x="${lab + len + sd + 6}" y="${y + 13}">${esc(fmt(r))}</text>`;
  });
  return `<svg class="chart bars" viewBox="0 0 ${w} ${rows.length * rowH + 6}" role="img">${g}</svg>`;
}

/* ---------- screens ---------- */

function gradeText(x) {
  if (x.strict_correct) return "right under both readers";
  return x.lenient_correct ? "wrong strictly, right leniently" : "wrong under both readers";
}

function screen1() {
  const d = S.d, m = d.meta, qs = S.all.questions, q = qs[S.q];
  const list = qs.map((x, i) => `<li class="${i === S.q ? "sel" : ""}"><button data-q="${i}">${esc(x.question)}<span class="q-meta">item ${x.index} · gold ${fmtNum(x.gold)} · ${gradeText(x)}</span></button></li>`).join("");
  const verdict = (ok) => `<span class="verdict ${ok ? "yes" : "no"}">${ok ? "right" : "wrong"}</span>`;
  const raw = q.raw
    ? `<table class="answers"><tr><th>Strict reads</th><td>${fmtNum(q.answer_v1)}</td></tr><tr><th>Lenient reads</th><td>${fmtNum(q.answer_v2)}</td></tr></table>
       <div class="label">Calculation lines, recomputed here (shown, not graded)</div>
       <ul class="trace">${q.steps.length ? q.steps.map((s) => `<li><span class="tick ${s.ok ? "ok" : "bad"}">${s.ok ? "checks" : "off"}</span><span>${esc(s.text)}</span></li>`).join("") : `<li class="muted">No line of the form a op b = c.</li>`}</ul>
       <details class="raw"><summary>Model output</summary><pre>${esc(q.raw)}</pre></details>`
    : `<p class="footnote">This replay carries the measured grade of every answer, not the answer text itself.</p>`;
  return `
  <p class="lede">An agent rewrites its own instruction and keeps a new one only if it beats a stored reference. These are five recorded runs of that loop on GSM8K. Start with a question.</p>
  <div class="cols wide-left">
    <div class="panel"><ul class="qlist">${list}</ul></div>
    <div class="panel surface">
      <h3>${esc(q.question)}</h3>
      <table class="answers">
        <tr><th>Gold answer</th><td>${fmtNum(q.gold)}</td></tr>
        <tr><th>Strict reader</th><td>${verdict(q.strict_correct)}</td></tr>
        <tr><th>Lenient reader</th><td>${verdict(q.lenient_correct)}</td></tr>
      </table>
      ${!q.strict_correct && q.lenient_correct ? `<p class="callout">Same saved answer, two grades. Only the reader changed.</p>` : ""}
      ${raw}
    </div>
  </div>
  <details class="panel"><summary>Starting instruction</summary><div class="prompt">${esc(d.prompts.p0)}</div></details>`;
}

function loopRows(rounds) {
  return rounds.map((r, i) => `<tr class="${i === rounds.length - 1 ? "new" : ""}"><td>${r.round}</td><td>${edit(r)}</td><td class="r">${r.wins}</td><td class="r">${r.losses}</td><td><span class="tag ${r.accepted ? "accept" : "reject"}">${r.accepted ? "promoted" : "kept"}</span></td><td class="r">${pct(r.acc_after)}</td></tr>`).join("");
}

function screen2() {
  const d = S.d, rs = pre(), shown = rs.slice(0, S.shown), ref = d.meta.reference;
  const chart = lineChart({
    values: [d.meta.baseline_strict_acc, ...shown.map((r) => r.acc_after)],
    xLabels: ["start", ...shown.map((r) => `R${r.round}`)], yMin: 0.5, yMax: 0.9, label: "accuracy",
  });
  const last = shown[shown.length - 1];
  return `
  <p class="lede">Each round the agent proposes a candidate instruction and scores it against the stored reference on the same ${d.meta.n_items} questions. It is promoted if it wins more questions than it loses. Under the frozen rule replayed here, the reference stays the starting instruction p0 for the whole run: every candidate is compared with p0's saved answers, not with the instruction it would replace.</p>
  <div class="panel"><div class="label">What the stored reference records</div>
    <table class="answers">
      <tr><th>Reference instruction</th><td>p0, version ${esc(ref.prompt_hash)}</td></tr>
      <tr><th>Raw outputs and extracted answers</th><td>${ref.n_outputs} saved answers, each with its grade</td></tr>
      <tr><th>Environment version</th><td>${esc(ref.env)} · ${esc(ref.fingerprint)}</td></tr>
      <tr><th>Scorer version</th><td>${esc(ref.scorer)}</td></tr>
    </table></div>
  <div class="cols wide-left">
    <div class="panel"><div class="label">Rounds so far</div>
      <table class="ledger"><thead><tr><th>Round</th><th>Current → candidate</th><th class="r">Wins vs p0</th><th class="r">Losses vs p0</th><th>Decision</th><th class="r">Accuracy</th></tr></thead>
      <tbody>${loopRows(shown) || `<tr><td colspan="6" class="muted">No round has run yet.</td></tr>`}</tbody></table>
      ${sameTextNote(shown.some((r) => r.incumbent === r.candidate))}
      <p class="actions"><button class="btn primary" id="runround" ${S.shown >= rs.length ? "disabled" : ""}>${S.shown >= rs.length ? "All rounds before the first change shown" : `Run round ${rs[S.shown].round}`}</button></p></div>
    <div class="panel"><div class="label">Scoreboard</div>${chart}
      <p class="footnote">Accuracy of the current instruction on the ${d.meta.n_items} questions, in the environment in force. ${shown.some((r) => r.false_accept) ? `A promotion already lowered accuracy (round ${shown.filter((r) => r.false_accept).map((r) => r.round).join(", ")}). That is ordinary noise in a 200-question comparison, before anything has changed; step 5 counts it separately.` : "Nothing looks wrong yet."}</p></div>
  </div>
  ${last ? `<div class="panel"><div class="label">Latest decision</div><p>Candidate ${last.candidate} won ${last.wins} and lost ${last.losses} questions against p0's saved answers, so it was ${last.accepted ? "promoted" : "not promoted"}.</p></div>` : ""}`;
}

function screen3() {
  const d = S.d, ch = d.meta.changes, inf = S.all.inflation, f = d.meta.extractor_flips;
  const next = ch[S.change];
  const btn = next
    ? `<button class="btn alarm" id="change">Apply change ${S.change + 1} of ${ch.length}: round ${next.round}, ${esc(next.text.toLowerCase().replace(/\.$/, ""))}</button>`
    : `<button class="btn alarm" disabled>Both changes applied</button>`;
  let out = "";
  if (S.change >= 1) {
    out += `<div class="panel"><h3>Change 1: decoding</h3>
      <p>A regenerated reference now produces different text from the stored one, because the model samples. Across all ${S.all.seeds.length} seeds this alone shows no consistent inflation: mean <span class="num">${signed(inf.E2.mean)} pp</span>, 95% interval [${inf.E2.lo.toFixed(2)}, ${inf.E2.hi.toFixed(2)}], and the sign differs between seeds (${inf.E2.seeds_same_sign} of ${S.all.seeds.length} agree).</p></div>`;
  }
  if (S.change >= 2) {
    const af = S.all.answer_flips;
    const ex = EXTRACTOR_EXAMPLES.map(([t, a, b]) => `<tr><td>${esc(t)}</td><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join("");
    out += `<div class="panel"><h3>Change 2: the extractor becomes lenient</h3>
      <p>The agent did not change. The way its answers are read did. The questions and gold answers are unchanged. The strict extractor reads only a plain number; the lenient one also reads commas, dollar signs, units and some fallbacks, and it never rejects an answer the strict one accepts.</p>
      <table class="ledger"><thead><tr><th>Model wrote</th><th>Strict reads</th><th>Lenient reads</th></tr></thead><tbody>${ex}</tbody></table>
      <p class="footnote">Examples from the repository's extractor tests.</p>
      <p>Across every instruction in the five runs, <b class="num">${int(af.wrong_to_right)} of ${int(af.items)}</b> saved answers go from wrong to right under the lenient reader, and <b class="num">${af.right_to_wrong}</b> go the other way. For this seed's starting instruction it is ${f.wrong_to_right} of ${f.n}.</p>
      <p>Isolating the extractor change alone (reference age ${S.all.age} rounds, all seeds), inflation is <b class="num">${signed(inf.E3.mean)} pp</b> with a 95% interval of [${inf.E3.lo.toFixed(2)}, ${inf.E3.hi.toFixed(2)}], positive on ${inf.E3.seeds_same_sign} of ${S.all.seeds.length} seeds.</p></div>`;
  }
  return `
  <p class="lede">While the loop runs, the deployment changes underneath it, and the loop is not told. Press the button to apply the next change in the order it happened in the saved runs. The environment badge follows the paper's labels: E2 for a decoding change, E3 for an extractor change, E4 when both have changed.</p>
  <div class="panel surface drift-control">
    <p class="muted">Environment in force: <span class="envbadge ${S.change ? "drifted" : ""}"><b>${envNow()}</b> ${esc(d.envs[envNow()])}</span></p>
    <p>${btn}</p>
    <p class="footnote">The press reveals the next part of a saved run. The changes happen at rounds ${ch.map((c) => c.round).join(" and ")} in the data either way.</p>
  </div>${out}`;
}

function trapRows(rounds) {
  return rounds.map((r, i) => `<tr class="${i === rounds.length - 1 ? "new" : ""} ${r.false_accept ? "false" : ""}"><td>${r.round}</td><td>${r.env}</td><td>${edit(r)}</td><td class="r">${r.wins} / ${r.losses}</td><td><span class="tag ${r.accepted ? "accept" : "reject"}">${r.accepted ? "promoted" : "kept"}</span></td><td class="r">${r.fresh_wins} / ${r.fresh_losses}</td><td>${r.fresh_wins > r.fresh_losses ? "yes" : "no"}</td><td class="r">${signed(r.inflation_pp, 1)} pp</td></tr>`).join("");
}

function screen4() {
  const d = S.d, rs = post(), shown = rs.slice(0, S.shownPost), inf = S.all.inflation;
  const done = S.shownPost >= rs.length;
  const mean = shown.length ? shown.reduce((a, r) => a + r.inflation_pp, 0) / shown.length : null;
  return `
  <p class="lede">After the changes, candidates are still scored against the stored reference: the starting instruction p0's answers, read the old way. The candidate is read the new way. "Fresh" means p0 regenerated and read under today's environment. Inflation is the candidate's win rate against the stored reference minus its win rate against the fresh one.</p>
  <div class="panel"><div class="label">Candidates after the first change</div>
    <table class="ledger"><thead><tr><th>Round</th><th>Env</th><th>Current → candidate</th><th class="r">Wins / losses vs p0, stored</th><th>Decision</th><th class="r">Wins / losses vs p0, fresh</th><th>Fresh promotes</th><th class="r">Inflation</th></tr></thead>
    <tbody>${trapRows(shown) || `<tr><td colspan="8" class="muted">No candidate scored yet.</td></tr>`}</tbody></table>
    ${sameTextNote(shown.some((r) => r.incumbent === r.candidate))}
    <p class="actions"><button class="btn primary" id="runpost" ${done ? "disabled" : ""}>${done ? "All candidates shown" : `Score the round ${rs[S.shownPost].round} candidate`}</button>
    ${done ? "" : `<button class="btn-text" id="showall">Show all</button>`}</p>
    ${mean != null ? `<p>Mean inflation over these ${shown.length} decisions on this seed: <b class="num">${signed(mean)} pp</b> (percentage points of ${d.meta.n_items} questions). This is measured against p0, so the reference gets older every round; the all-seed table below fixes the reference age at ${S.all.age} rounds, so the two numbers are not directly comparable.</p>` : ""}
  </div>
  ${done ? `<div class="panel"><div class="label">All ${S.all.seeds.length} seeds, reference age ${S.all.age} rounds</div>${inflationTable(inf)}
    <p class="footnote">Inflation in percentage points of ${S.all.n_items} questions, over all ${S.all.seeds.length} seeds. The bars share one scale around zero; red marks an interval that excludes zero. Only the extraction change and the multiple changes qualify. The decoding change is not distinguishable from the unchanged control.</p></div>` : ""}`;
}

function screen5() {
  const d = S.d, fp = d.rounds.filter((r) => r.false_accept), fc = S.all.false_promotion_causes;
  const n = (k) => fp.filter((r) => r.cause === k).length;
  const chart = gainChart(d.rounds, d.meta.changes);
  const rows = fp.map((r) => `<tr class="${r.cause === "stale" ? "false" : ""}"><td>${r.round}</td><td>${r.env}</td><td>${edit(r)}</td><td class="r">${r.wins} / ${r.losses}</td><td class="r">${r.fresh_wins} / ${r.fresh_losses}</td><td class="r">${pct(r.candidate_acc)} / ${pct(r.incumbent_acc)}</td><td>${r.cause === "stale" ? `<b>${CAUSE.stale}</b>` : `<span class="muted">${CAUSE[r.cause]}</span>`}</td></tr>`).join("");
  const verdict = fp.length
    ? `<span class="stamp">False promotion</span><p>${fp.length} candidate${fp.length > 1 ? "s were" : " was"} promoted on this seed without being better than the instruction ${fp.length > 1 ? "they" : "it"} replaced. They do not all have the same cause. The test is the same promotion rule applied against a fresh reference: if the fresh reference would have rejected the candidate, the stale reference caused the promotion.</p>
       <p>On this seed: <b class="num">${n("stale")}</b> ${CAUSE.stale}, <b class="num">${n("anyway")}</b> that would have happened anyway, <b class="num">${n("before_change")}</b> before any change (noise in a comparison on ${d.meta.n_items} questions).</p>
       <table class="ledger"><thead><tr><th>Round</th><th>Env</th><th>Current → candidate</th><th class="r">vs p0, stored</th><th class="r">vs p0, fresh</th><th class="r">Accuracy, candidate / current</th><th>Cause</th></tr></thead><tbody>${rows}</tbody></table>
       ${sameTextNote(fp.some((r) => r.incumbent === r.candidate))}
       ${fp.some((r) => r.cause === "stale" && r.env === "E2") ? `<p class="footnote">Caution: ${fp.filter((r) => r.cause === "stale" && r.env === "E2").map((r) => `round ${r.round}`).join(", ")} happened under the decoding change alone (E2). Across all seeds that change shows no consistent inflation (step 3), so treat ${fp.filter((r) => r.cause === "stale" && r.env === "E2").length > 1 ? "these" : "this one"} as likely noise. The extractor change is the consistent effect.</p>` : ""}
       <p>Across all ${S.all.seeds.length} seeds the frozen rule made <b class="num">${fc.stale + fc.anyway + fc.before_change}</b> false promotions: <b class="num">${fc.stale}</b> ${CAUSE.stale}, <b class="num">${fc.anyway}</b> that a fresh reference would also have made, and <b class="num">${fc.before_change}</b> before any change.</p>
       <p class="footnote">A fresh reference is one regenerated run, so it carries a little noise of its own: with nothing changed, a rerun differs from the stored run by about a tenth of a point on average.</p>`
    : `<span class="stamp calm">No false promotion on this seed</span><p>Every promotion on this seed improved accuracy. Choose another seed from the list on the left to see one where the stale reference changed a decision.</p>`;
  return `
  <p class="lede">For every round, two bars: the candidate's net gain (wins minus losses, in points of ${d.meta.n_items} questions) against the stored reference, p0's saved answers, and against p0 regenerated today. A candidate is promoted when the first bar is above zero. Where the first bar is above zero and the second is not, the stale reference decided.</p>
  <div class="panel">${chart}<p class="footnote">Labels under the bars mark promoted candidates: "ok" if the promotion was an improvement, "false" if it was not. A false promotion means the candidate's accuracy was not higher than the incumbent's, with both measured in the environment in force. Promotion and this check use the same ${d.meta.n_items} questions.</p></div>
  <div class="panel surface">${verdict}</div>`;
}

function screen6() {
  const d = S.d, a = S.all;
  const opts = Object.entries(OPTIONS).map(([k, o]) => `<button class="option" data-vote="${k}" aria-pressed="${S.vote === k}"><b>${esc(o.title)}</b><span class="muted">${esc(o.text)}</span></button>`).join("");
  let result = "";
  if (S.vote) {
    const key = POLICY_FOR_OPTION[S.vote], p = d.policies[key], pooled = a.policies[key];
    const unparsed = (rd) => d.rounds.find((r) => r.round === rd)?.note === "fallback_unparsed";
    const rows = p.decisions.map((x) => `<tr class="${x.false_accept ? "false" : ""}"><td>${x.round}</td><td>${x.env}</td><td>${x.candidate}${unparsed(x.round) ? " (same text)" : ""}</td><td class="r">${x.wins} / ${x.losses}</td><td><span class="tag ${x.accepted ? "accept" : "reject"}">${x.accepted ? "promoted" : "kept"}</span></td><td>${x.false_accept ? '<span class="tag false">false accept</span>' : x.false_reject ? '<span class="tag false">missed gain</span>' : ""}</td><td>${x.reference_refreshed ? "regenerated" : "stored"}</td></tr>`).join("");
    result = `<div class="panel surface"><div class="label">${esc(OPTIONS[S.vote].title)}, seed ${d.meta.seed}</div>
      <p class="footnote">Wins and losses are counted against ${REF_TEXT[key]}.</p>
      <table class="ledger"><thead><tr><th>Round</th><th>Env</th><th>Candidate</th><th class="r">Wins / losses</th><th>Decision</th><th>Outcome</th><th>Reference</th></tr></thead><tbody>${rows}</tbody></table>
      ${sameTextNote(p.decisions.some((x) => unparsed(x.round)))}
      <p>This seed: promotions <b class="num">${p.accepted}</b> · false accepts <b class="num">${p.false_accepts}</b> · missed gains <b class="num">${p.false_rejects}</b> · regenerations <b class="num">${p.refreshes}</b> · logical model calls <b class="num">${int(p.logical_calls)}</b> (estimate).</p>
      <p>All ${a.seeds.length} seeds: <b class="num">${pooled.false_accepts} of ${pooled.accepted}</b> promotions were false accepts, and <b class="num">${pooled.false_rejects}</b> real improvements were missed.</p>
      <table class="ledger"><thead><tr><th>All ${a.seeds.length} seeds</th><th class="r">False accepts</th><th class="r">Missed gains</th><th class="r">Logical calls (est.)</th></tr></thead><tbody>${Object.entries(OPTIONS).map(([k, o]) => { const q = a.policies[POLICY_FOR_OPTION[k]]; return `<tr class="${k === S.vote ? "new" : ""}"><td>${esc(o.title)}${k === S.vote ? " (your pick)" : ""}</td><td class="r">${q.false_accepts} of ${q.accepted}</td><td class="r">${q.false_rejects}</td><td class="r">${int(q.logical_calls[0])}</td></tr>`; }).join("")}</tbody></table>
      <p class="footnote">All three policies choose among the same candidates and are scored on the same questions. Call counts are an estimate from a dry run.</p></div>`;
  }
  return `<p class="lede">Which defense would you deploy? The three rules run over the same candidate pool, so the counts are directly comparable.</p><div class="options">${opts}</div>${result}`;
}

function screen7() {
  const a = S.all, P = a.policies, n = a.seeds.length;
  const acc = bars(["P1", "P2", "P3"].map((p) => ({ label: SHORT[p], value: P[p].final_acc[0], sd: P[p].final_acc[1], tone: "ink" })), { max: 1, fmt: (r) => `${pct(r.value)} ± ${(100 * r.sd).toFixed(1)}` });
  const fa = bars(["P1", "P2", "P3"].map((p) => ({ label: SHORT[p], value: P[p].false_accepts / P[p].accepted, tone: "accent", text: `${P[p].false_accepts}/${P[p].accepted}` })), { max: 1, fmt: (r) => r.text });
  const maxCalls = Math.max(...["P1", "P2", "P3"].map((p) => P[p].logical_calls[0]));
  const calls = bars(["P1", "P2", "P3"].map((p) => ({ label: SHORT[p], value: P[p].logical_calls[0], tone: "soft" })), { max: maxCalls, fmt: (r) => int(r.value) });
  const seedRows = a.seeds.map((s) => {
    const r = a.per_seed[s];
    return `<tr><td>${s}</td>${["P1", "P2", "P3"].map((p) => `<td class="r">${r[p].false_accepts}/${r[p].accepted}</td>`).join("")}<td class="r">${r.false_promotion_rounds.length ? r.false_promotion_rounds.join(", ") : "none"}</td></tr>`;
  }).join("");
  return `
  <p class="lede">All ${n} seeds, same candidates and questions for every policy. False accepts are pooled counts; accuracy is the mean over seeds ± one standard deviation.</p>
  <div class="stat-grid">
    <div class="panel surface stat-main"><h3>False accepts</h3>${fa}<p class="footnote">Promotions that were not improvements, over all promotions, pooled across seeds. Missed real gains: ${["P1", "P2", "P3"].map((p) => `${SHORT[p].toLowerCase()} ${P[p].false_rejects}`).join(", ")}.</p></div>
    <div class="panel"><h3>Final accuracy</h3>${acc}<p class="footnote">Accuracy of the final instruction in the last environment, mean ± one standard deviation over seeds. The gaps are within one standard deviation, so the false-accept counts are the clearer evidence.</p></div>
    <div class="panel"><h3>Logical model calls <span class="muted">(estimate)</span></h3>${calls}<p class="footnote">Per run, from a dry run of each policy. Not measured inference cost.</p></div>
  </div>
  <details class="panel"><summary>False accepts and promotions by seed</summary>
    <table class="ledger"><thead><tr><th>Seed</th><th class="r">Frozen</th><th class="r">Every batch</th><th class="r">On change</th><th class="r">False promotion rounds (frozen)</th></tr></thead><tbody>${seedRows}</tbody></table></details>
  <p class="bigline">The agent didn't get worse. Its ruler did. In these runs, refreshing the reference when the environment changed cut false accepts from ${P.P1.false_accepts} of ${P.P1.accepted} to ${P.P3.false_accepts} of ${P.P3.accepted}, at about ${Math.round(100 * (P.P3.logical_calls[0] / P.P1.logical_calls[0] - 1))}% more model calls than never refreshing.</p>`;
}

function screen8() {
  const a = S.all, P = a.policies, vf = a.verdict_flips, w = vf.widest, dom = DOMAINS[S.app];
  const tabs = Object.keys(DOMAINS).map((n) => `<button class="tab" data-app="${esc(n)}" aria-pressed="${n === S.app}">${esc(n)}</button>`).join("");
  const reading = ([out, before, after]) => `<code>${esc(out)}</code><br><span class="muted">before:</span> ${esc(before)}<br><span class="muted">after:</span> ${esc(after)}`;
  const gsmResults = `Measured. False accepts ${["P1", "P2", "P3"].map((p) => `${P[p].false_accepts}/${P[p].accepted}`).join(", ")} for the three policies; inflation from the extractor change ${signed(a.inflation.E3.mean)} pp [${a.inflation.E3.lo.toFixed(2)}, ${a.inflation.E3.hi.toFixed(2)}].`;
  const cell = (row, col, isGsm) => {
    if (row === "example") return reading(col.example);
    if (row === "loop") return isGsm ? esc(col.loop) : "Reused unchanged.";
    if (row === "results") return isGsm ? gsmResults : `<span class="alarm">None reported.</span> Would need a run on this task.`;
    return esc(col[row]);
  };
  const rows = MAP_ROWS.map(([k, label]) => `<tr><th>${esc(label)}</th><td>${cell(k, GSM8K_COL, true)}</td><td>${cell(k, dom, false)}</td></tr>`).join("");
  return `
  <p class="lede">The system is not tied to arithmetic. Anywhere an agent is promoted by beating a stored reference, the same parts apply: a reference with its environment version, a change to how outputs are run or read, an independent check, and the three refresh rules. The left column is what the runs on this site used. The right column shows the same parts for another task. It is an illustration: no runs were made on these tasks and no results are reported for them.</p>
  <div class="tabs" role="group" aria-label="Task">${tabs}</div>
  <div class="panel"><table class="ledger mapping">
    <thead><tr><th>Part of the system</th><th>GSM8K, this paper <span class="tag accept">measured</span></th><th>${esc(S.app)} <span class="tag reject">illustration</span></th></tr></thead>
    <tbody>${rows}</tbody></table></div>
  <div class="panel"><div class="label">What carries over from the measurement</div>
    <p>The mechanism, not the number. On GSM8K, changing only the answer reader changed the verdict (improved, no change or worse) on <b class="num">${vf.flipped} of ${vf.n}</b> candidates, with the same instructions and the same saved outputs. The widest case, seed ${w.seed} ${esc(w.cid)}, read ${signed(w.e1_pp, 1)} pp under the strict reader and ${signed(w.e3_pp, 1)} pp under the lenient one. Any task whose outputs are read by a component that can be updated is exposed to the same effect; how large it is there is unknown until it is measured.</p></div>`;
}

function screen9() {
  const comps = COMPONENTS.map(([t, d, c]) => `<li><b>${esc(t)}</b><span>${esc(d)}</span><code>${esc(c)}</code></li>`).join("");
  const box = (x, y, t, s = "") => `<g class="node"><rect x="${x}" y="${y}" width="150" height="46" rx="8"/><text class="lbl" x="${x + 75}" y="${y + 20}" text-anchor="middle">${t}</text>${s ? `<text x="${x + 75}" y="${y + 36}" text-anchor="middle">${s}</text>` : ""}</g>`;
  const arrow = (x1, y1, x2, y2) => `<line class="arrow" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" marker-end="url(#ah)"/>`;
  const diagram = `<svg class="chart diagram" viewBox="0 0 700 230" role="img" aria-label="Data flow between components">
    <defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path class="arrowhead" d="M0 0L8 4L0 8z"/></marker></defs>
    ${box(0, 10, "Proposer", "writes a candidate")}${box(275, 10, "Comparison", "wins and losses")}${box(550, 10, "Promotion rule", "wins > losses")}
    ${box(275, 100, "Reference store", "outputs, answers, version")}${box(0, 100, "Environment tracker", "version fingerprint")}
    ${box(275, 180, "Reference rerun", "")}${box(550, 100, "Ground truth check", "same environment")}
    ${arrow(150, 33, 275, 33)}${arrow(425, 33, 550, 33)}${arrow(350, 100, 350, 56)}${arrow(150, 123, 275, 123)}${arrow(350, 180, 350, 146)}${arrow(625, 56, 625, 100)}
  </svg>`;
  return `
  <p class="lede">The system is a small Python package that records every reference with the environment it was measured in, and replays decisions under different refresh rules without calling the model again.</p>
  <div class="panel">${diagram}<p class="footnote">The environment tracker's fingerprint tells the refresh policy when to regenerate the reference. The ground truth check measures both prompts in the environment in force.</p></div>
  <div class="panel"><div class="label">Components</div><ul class="comps">${comps}</ul></div>
  <div class="panel"><div class="label">Run it yourself</div>
    <pre class="cmd">python run_seeds.py 1 2 3 4 5    # model runs, cached
python run_all.py                # tables from saved runs, no model
python export_replay.py          # writes the files this page reads
cd demo &amp;&amp; python3 -m http.server</pre></div>`;
}

const SCREENS = [null, screen1, screen2, screen3, screen4, screen5, screen6, screen7, screen8, screen9];

/* ---------- shell ---------- */

function canNext() {
  switch (S.step) {
    case 2: return S.shown >= pre().length;
    case 3: return S.change >= nChanges();
    case 4: return S.shownPost >= post().length;
    case 6: return S.vote != null;
    default: return S.step < STEPS.length;
  }
}

function render() {
  const m = S.d.meta;
  $("#sample-banner").hidden = m.precomputed;
  $("#runnote").textContent = `${m.model}, first ${m.n_items} ${m.dataset} test questions, ${m.rounds} rounds, ${S.all.seeds.length} seeds.`;
  $("#stepnav").innerHTML = STEPS.map((t, i) => {
    const n = i + 1;
    return `<li class="${n === S.step ? "current" : n < S.step ? "done" : ""}"><button data-step="${n}" ${n > S.max ? "disabled" : ""} ${n === S.step ? 'aria-current="step"' : ""}><span class="n">${n}</span><span>${esc(t)}</span></button></li>`;
  }).join("");
  const showEnv = S.step >= 2 && S.step <= 6;
  const env = showEnv ? `<span class="envbadge ${S.change && S.step >= 3 ? "drifted" : ""}">environment <b>${envNow()}</b> ${esc(S.d.envs[envNow()])}</span>` : "";
  const pooled = S.step === 7 || S.step === 8;
  const bar = S.step >= 2 ? `<div class="statusbar">${env}<span class="replaytag">Replay of recorded runs</span><span class="muted">${pooled ? `all ${S.all.seeds.length} seeds, measured in advance` : `seed ${m.seed}, measured in advance`}</span></div>` : "";
  $("#stage").innerHTML = `<div class="screen-head"><span class="n">${S.step} / ${STEPS.length}</span><h2>${STEPS[S.step - 1]}</h2></div>${bar}${SCREENS[S.step]()}
    <div class="nav-row"><button class="btn-text" id="back" ${S.step === 1 ? "disabled" : ""}>Back</button>${S.step < STEPS.length ? `<button class="btn primary" id="next" ${canNext() ? "" : "disabled"}>Next</button>` : ""}</div>`;
}

function go(n) {
  S.step = n;
  S.max = Math.max(S.max, n);
  render();
  $("#stage").focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

function onClick(e) {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.step) return go(+t.dataset.step);
  if (t.dataset.vote) { S.vote = t.dataset.vote; return render(); }
  if (t.dataset.app) { S.app = t.dataset.app; return render(); }
  if (t.dataset.q) { S.q = +t.dataset.q; return render(); }
  if (t.id === "next" && canNext()) return go(S.step + 1);
  if (t.id === "back") return go(S.step - 1);
  if (t.id === "runround") { S.shown++; return render(); }
  if (t.id === "runpost") { S.shownPost++; return render(); }
  if (t.id === "showall") { S.shownPost = post().length; return render(); }
  if (t.id === "change") { S.change++; return render(); }
}

async function init() {
  try {
    S.all = await getJSON("replay/all_seeds.json");
  } catch (err) {
    $("#stage").innerHTML = `<p class="alarm">Replay files could not be loaded (${esc(err.message)}). Serve this folder over HTTP, for example <code>python3 -m http.server</code>, instead of opening the file directly.</p>`;
    return;
  }
  const sel = $("#seed");
  const links = Object.entries(LINKS).filter(([, u]) => u);
  if (links.length) {
    $("#links").innerHTML = links.map(([t, u]) => `<a href="${esc(u)}">${esc(t)}</a>`).join("");
    $("#links").hidden = false;
  }
  sel.innerHTML = S.all.seeds.map((s) => `<option value="${s}">seed ${s}${s === EXAMPLE_SEED ? " (example)" : S.all.per_seed[s].false_promotion_rounds.length ? "" : " (no false promotion)"}</option>`).join("");
  const first = S.all.seeds.includes(EXAMPLE_SEED) ? EXAMPLE_SEED : S.all.seeds[0];
  sel.value = first;
  sel.addEventListener("change", async () => { await loadSeed(+sel.value); render(); });
  document.addEventListener("click", onClick);
  document.addEventListener("keydown", (e) => {
    if (/^(SELECT|INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === "ArrowRight" && canNext()) go(S.step + 1);
    if (e.key === "ArrowLeft" && S.step > 1) go(S.step - 1);
  });
  await loadSeed(first);
  render();
  fetch("media/demo.mp4", { method: "HEAD" }).then((r) => {
    if (r.ok) $("#video").innerHTML = `<h2>Video</h2><video controls preload="metadata" src="media/demo.mp4"></video>`;
  }).catch(() => {});
}

init();
