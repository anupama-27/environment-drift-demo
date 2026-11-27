"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { DA, SEEDS, legacyRun, paperRun, smallRun, env, column, without, close } = require("./helpers.js");

const engine = DA.engine;
const POLICY_IDS = ["frozen", "stored_incumbent", "per_batch", "env_triggered", "periodic", "as_run"];

// Five rounds, four items. The environment changes from E1 to E3 at round 2: same decoding,
// lenient extractor, so every prompt's stored text is simply read more generously.
const LABELS = {
  p0: { E1: "1000", E3: "1110" },
  c1: { E1: "1100", E3: "1110" },     // a real gain over p0
  c2: { E1: "1010", E3: "1010" },     // ties c1, still beats the round-0 reference
  c3: { E1: "1100", E3: "1100" },     // beats p0 as stored, not p0 as it reads now
  c4: { E1: "1101", E3: "1111" },     // a real gain over everything
  c5: { E1: "1100", E3: "1110" },     // worse than c4
};
// The one rerun that does not repeat its stored pass.
const RERUNS = { "p0/E3": "1100" };
// The recorded loop kept the round-0 reference throughout and so accepted everything.
const CANDIDATES = [
  { id: "C1", round: 0, prompt: "c1", parent: "p0", env: "E1", note: "ok", wins: 1, losses: 0, accepted: true },
  { id: "C2", round: 1, prompt: "c2", parent: "c1", env: "E1", note: "ok", wins: 1, losses: 0, accepted: true },
  { id: "C3", round: 2, prompt: "c3", parent: "c2", env: "E3", note: "ok", wins: 1, losses: 0, accepted: true },
  { id: "C4", round: 3, prompt: "c4", parent: "c3", env: "E3", note: "ok", wins: 3, losses: 0, accepted: true },
  { id: "C5", round: 4, prompt: "c5", parent: "c4", env: "E3", note: "ok", wins: 2, losses: 0, accepted: true },
];
const SNAPSHOTS = ["p0", "c1", "c2", "c3", "c4"];

function make({ labels = LABELS, reruns = RERUNS, candidates = CANDIDATES, references = false, ...rest } = {}) {
  const cands = candidates.map((c) => (references ? { ...c, reference: { prompt: "p0", env: "E1", pass: "current" } } : { ...c }));
  return smallRun({
    labels, reruns, candidates: cands, schedule: { 0: "E1", 2: "E3" }, snapshots: SNAPSHOTS.slice(0, cands.length),
    nItems: 4, nDev: 3, ...rest,
  });
}

// A loaded run as a plain object again, for tests that change it before auditing.
function editable(run) {
  return JSON.parse(JSON.stringify(run));
}

// pair

test("pair counts wins, losses and agreements", () => {
  assert.deepEqual(engine.pair("1100", "1010"), { wins: 1, losses: 1, both_right: 1, both_wrong: 1 });
  assert.deepEqual(engine.pair("1111", "0000"), { wins: 4, losses: 0, both_right: 0, both_wrong: 0 });
  assert.deepEqual(engine.pair("", ""), { wins: 0, losses: 0, both_right: 0, both_wrong: 0 });
  assert.deepEqual(engine.pair("1011001", "0010101"), { wins: 2, losses: 1, both_right: 2, both_wrong: 2 });
});

// policies

test("policy ids and names are the published ones", () => {
  assert.deepEqual(Object.keys(engine.POLICIES), POLICY_IDS);
  assert.deepEqual(Object.values(engine.POLICIES).map((p) => p.name),
    ["Frozen", "Stored incumbent", "Per-batch", "Environment-triggered", "Every k rounds", "As run"]);
  assert.ok(Object.values(engine.POLICIES).every((p) => p.rule));
});

test("frozen keeps the round-zero reference and accepts on stale labels", () => {
  const block = engine.simulate(make(), "frozen");
  assert.deepEqual([block.id, block.name, block.available], ["frozen", "Frozen", true]);
  assert.deepEqual(column(block, "ref_prompt"), ["p0", "p0", "p0", "p0", "p0"]);
  assert.deepEqual(column(block, "ref_env"), ["E1", "E1", "E1", "E1", "E1"]);
  assert.deepEqual(column(block, "ref_round"), [0, 0, 0, 0, 0]);
  assert.deepEqual(column(block, "ref_age"), [0, 1, 2, 3, 4]);
  assert.deepEqual(column(block, "ref_fresh"), [false, false, false, false, false]);
  assert.deepEqual(column(block, "ref_pass"), ["current", "current", "current", "current", "current"]);
  assert.deepEqual(column(block, "env"), ["E1", "E1", "E3", "E3", "E3"]);
  assert.deepEqual(column(block, "env_mismatch"), [false, false, true, true, true]);
  assert.deepEqual(column(block, "incumbent"), ["p0", "c1", "c2", "c3", "c4"]);
  assert.deepEqual(column(block, "wins"), [1, 1, 1, 3, 2]);
  assert.deepEqual(column(block, "losses"), [0, 0, 0, 0, 0]);
  assert.deepEqual(column(block, "rerun_wins"), [1, 1, 0, 2, 1]);
  assert.deepEqual(column(block, "rerun_losses"), [0, 0, 0, 0, 0]);
  assert.deepEqual(column(block, "accepted"), [true, true, true, true, true]);
  assert.deepEqual(column(block, "rerun_accepts"), [true, true, false, true, true]);
  assert.deepEqual(column(block, "false_accept"), [false, true, true, false, true]);
  assert.deepEqual(column(block, "false_reject"), [false, false, false, false, false]);
  assert.deepEqual(column(block, "inflation"), [0, 0, 0.25, 0.25, 0.25]);
  assert.deepEqual([block.accepted, block.false_accepts, block.false_rejects, block.refreshes], [5, 3, 0, 0]);
  assert.equal(block.false_accept_rate, 3 / 5);
  assert.deepEqual([block.final_prompt, block.final_acc], ["c5", 0.75]);
  assert.ok(close(block.inflation, 0.15));
});

test("ground truth is judged under the current environment", () => {
  const block = engine.simulate(make(), "frozen");
  assert.deepEqual(column(block, "inc_acc"), [0.25, 0.5, 0.5, 0.5, 1]);
  assert.deepEqual(column(block, "cand_acc"), [0.5, 0.5, 0.5, 1, 0.75]);
  assert.deepEqual(column(block, "delta_pp"), [25, 0, 0, 50, -25]);
  assert.deepEqual(column(block, "outcome"), ["improved", "no change", "no change", "improved", "worse"]);
});

test("a false accept is attributed to its cause", () => {
  const block = engine.simulate(make(), "frozen");
  // Round 1: no environment change yet. Round 2: the rerun reference would have refused.
  // Round 4: the rerun reference would have accepted as well.
  assert.deepEqual(column(block, "cause"), [null, "no_drift", "stale", null, "anyway"]);
  assert.deepEqual(block.causes, { stale: 1, anyway: 1, no_drift: 1 });
});

test("stored incumbent compares with the outputs stored at the last accept", () => {
  const block = engine.simulate(make(), "stored_incumbent");
  assert.deepEqual(column(block, "ref_prompt"), ["p0", "c1", "c1", "c1", "c4"]);
  assert.deepEqual(column(block, "ref_env"), ["E1", "E1", "E1", "E1", "E3"]);
  assert.deepEqual(column(block, "ref_round"), [0, 0, 0, 0, 3]);
  assert.deepEqual(column(block, "ref_age"), [0, 1, 2, 3, 1]);
  assert.deepEqual(column(block, "env_mismatch"), [false, false, true, true, false]);
  assert.deepEqual(column(block, "accepted"), [true, false, false, true, false]);
  assert.deepEqual([block.false_accepts, block.false_rejects, block.refreshes], [0, 0, 0]);
  assert.deepEqual([block.final_prompt, block.final_acc], ["c4", 1]);
});

test("ties are not accepted", () => {
  const d = engine.simulate(make(), "stored_incumbent").decisions[1];
  assert.deepEqual([d.wins, d.losses, d.accepted], [1, 1, false]);
});

test("per-batch reruns the incumbent every round", () => {
  const block = engine.simulate(make(), "per_batch");
  assert.deepEqual(column(block, "ref_fresh"), [true, true, true, true, true]);
  assert.deepEqual(column(block, "ref_pass"), ["rerun", "rerun", "rerun", "rerun", "rerun"]);
  assert.deepEqual(column(block, "ref_prompt"), ["p0", "c1", "c1", "c1", "c4"]);
  assert.deepEqual(column(block, "ref_env"), column(block, "env"));
  assert.deepEqual(column(block, "ref_age"), [0, 0, 0, 0, 0]);
  assert.deepEqual(column(block, "env_mismatch"), [false, false, false, false, false]);
  assert.deepEqual(column(block, "inflation"), [0, 0, 0, 0, 0]);
  assert.deepEqual(column(block, "accepted"), [true, false, false, true, false]);
  assert.equal(block.refreshes, 5);
});

test("environment-triggered reruns only when the fingerprint changes", () => {
  const block = engine.simulate(make(), "env_triggered");
  assert.deepEqual(column(block, "ref_fresh"), [false, false, true, false, false]);
  // The rerun made at round 2 stays the reference until the next accept.
  assert.deepEqual(column(block, "ref_pass"), ["current", "current", "rerun", "rerun", "current"]);
  assert.deepEqual(column(block, "ref_prompt"), ["p0", "c1", "c1", "c1", "c4"]);
  assert.deepEqual(column(block, "ref_env"), ["E1", "E1", "E3", "E3", "E3"]);
  assert.deepEqual(column(block, "ref_round"), [0, 0, 2, 2, 3]);
  assert.deepEqual(column(block, "ref_age"), [0, 1, 0, 1, 1]);
  assert.deepEqual(column(block, "env_mismatch"), [false, false, false, false, false]);
  assert.deepEqual(column(block, "accepted"), [true, false, false, true, false]);
  assert.deepEqual([block.refreshes, block.false_accepts, block.false_rejects], [1, 0, 0]);
});

test("environment-triggered compares fingerprints, not ids", () => {
  const run = editable(make());
  run.environments.E3.fingerprint = run.environments.E1.fingerprint;
  const block = engine.simulate(run, "env_triggered");
  assert.equal(block.refreshes, 0);
  assert.deepEqual(column(block, "env_mismatch"), [false, false, false, false, false]);
});

test("a stale reference can also reject a real gain", () => {
  // The extractor gets stricter at round 1, so the stored reference now flatters the incumbent.
  const run = smallRun({
    labels: { p0: { E3: "1110", E1: "1000" }, c1: { E3: "1110", E1: "1000" }, c2: { E3: "1110", E1: "1100" } },
    schedule: { 0: "E3", 1: "E1" }, snapshots: ["p0", "p0"], nItems: 4,
    candidates: [{ id: "C1", round: 0, prompt: "c1", parent: "p0", accepted: false },
      { id: "C2", round: 1, prompt: "c2", parent: "p0", accepted: false }],
  });
  const frozen = engine.simulate(run, "frozen");
  assert.deepEqual(column(frozen, "accepted"), [false, false]);
  assert.deepEqual(column(frozen, "false_reject"), [false, true]);
  assert.deepEqual([frozen.false_rejects, frozen.final_prompt], [1, "p0"]);
  const triggered = engine.simulate(run, "env_triggered");
  assert.deepEqual(column(triggered, "accepted"), [false, true]);
  assert.equal(triggered.false_rejects, 0);
});

test("calls follow the toolkit's accounting", () => {
  const run = make();
  const [frozen, batch, triggered] = ["frozen", "per_batch", "env_triggered"].map((p) => engine.simulate(run, p));
  // Per round: one proposal plus the dev pass (3 items here), and the candidate on 4 items.
  assert.deepEqual(frozen.calls, { proposer: 20, candidate_eval: 20, reference_refresh: 0 });
  assert.deepEqual(batch.calls, { proposer: 20, candidate_eval: 20, reference_refresh: 20 });
  assert.deepEqual([frozen.total_calls, batch.total_calls, triggered.total_calls], [40, 60, 44]);
});

test("dev items come from cost before the task", () => {
  const run = editable(make());
  run.cost = { n_dev: 10, proposal_calls: 2 };
  assert.equal(engine.simulate(run, "frozen").calls.proposer, 5 * 12);
  run.cost = {};
  delete run.task.n_dev;
  assert.equal(engine.simulate(run, "frozen").calls.proposer, 5);
});

// periodic, margin, fixed age, rescore

test("periodic reruns once the reference is k rounds old", () => {
  const run = make();
  const one = engine.simulate(run, "periodic", { periodic_k: 1 });
  assert.deepEqual(column(one, "ref_fresh"), [false, true, true, true, true]);
  assert.equal(one.refreshes, 4);
  assert.deepEqual(column(one, "accepted"), [true, false, false, true, false]);
  const three = engine.simulate(run, "periodic", { periodic_k: 3 });
  assert.deepEqual(column(three, "ref_fresh"), [false, false, false, true, false]);
  assert.equal(three.refreshes, 1);
  assert.deepEqual(column(three, "ref_round"), [0, 0, 0, 3, 3]);
  assert.deepEqual(column(three, "ref_age"), [0, 1, 2, 0, 1]);
  // Round 2 still reads c1 as stored under E1, across the environment change.
  const d = three.decisions[2];
  assert.deepEqual([d.env_mismatch, d.ref_prompt, d.ref_env], [true, "c1", "E1"]);
  assert.equal(three.name, "Every k rounds");
});

test("periodic takes the candidate's labels as reference after an accept", () => {
  const block = engine.simulate(make(), "periodic", { periodic_k: 2 });
  assert.deepEqual(column(block, "ref_prompt"), ["p0", "c1", "c1", "c1", "c4"]);
  assert.deepEqual(column(block, "ref_pass"), ["current", "current", "rerun", "rerun", "current"]);
  assert.deepEqual(column(block, "ref_round"), [0, 0, 2, 2, 3]);
});

test("periodic default is three rounds", () => {
  const run = make();
  assert.deepEqual(engine.simulate(run, "periodic"), engine.simulate(run, "periodic", { periodic_k: 3 }));
  assert.equal(engine.audit(run).options.periodic_k, 3);
});

test("margin asks for more than a bare majority", () => {
  const block = engine.simulate(make(), "frozen", { margin: 1 });
  assert.deepEqual(column(block, "accepted"), [false, false, false, true, true]);
  assert.deepEqual(column(block, "false_reject"), [true, true, false, false, false]);
  assert.deepEqual(column(block, "incumbent"), ["p0", "p0", "p0", "p0", "c4"]);
  // The rerun reference gives round 4 one net win, which no longer clears the margin.
  assert.deepEqual(column(block, "cause"), [null, null, null, null, "stale"]);
});

test("fixed age uses the snapshot that many rounds back", () => {
  const block = engine.simulate(make(), "frozen", { fixed_age: 1 });
  assert.deepEqual(column(block, "ref_prompt"), ["p0", "p0", "c1", "c2", "c3"]);
  assert.deepEqual(column(block, "ref_env"), ["E1", "E1", "E1", "E3", "E3"]);
  assert.deepEqual(column(block, "ref_round"), [0, 0, 1, 2, 3]);
  assert.deepEqual(column(block, "ref_age"), [0, 1, 1, 1, 1]);
  assert.deepEqual(column(block, "ref_fresh"), [false, false, false, false, false]);
  for (const policy of ["stored_incumbent", "per_batch", "env_triggered", "periodic"]) {
    const other = engine.simulate(make(), policy, { fixed_age: 1 });
    assert.deepEqual(other.decisions, block.decisions);
    assert.equal(other.refreshes, 0);
  }
});

test("rescore reads the stored text with the current scorer", () => {
  const block = engine.simulate(make(), "frozen", { stored_scoring: "rescore" });
  assert.deepEqual(column(block, "ref_env"), ["E1", "E1", "E1", "E1", "E1"]);
  assert.deepEqual(column(block, "ref_scored_env"), ["E1", "E1", "E3", "E3", "E3"]);
  assert.deepEqual(column(block, "wins"), [1, 1, 0, 1, 0]);
  assert.deepEqual(column(block, "losses"), [0, 0, 1, 0, 0]);
  assert.deepEqual(column(block, "accepted"), [true, true, false, true, false]);
  assert.deepEqual(block.causes, { stale: 0, anyway: 0, no_drift: 1 });
  assert.deepEqual(column(engine.simulate(make(), "frozen"), "ref_scored_env"), ["E1", "E1", "E1", "E1", "E1"]);
});

test("rescore falls back and says so when no environment shares the text", () => {
  const environments = { A: env("", "greedy-0.0", "strict", "m"), B: env("", "sample-0.2", "lenient", "m") };
  const labels = Object.fromEntries(Object.entries(LABELS).map(([h, per]) => [h, { A: per.E1, B: per.E3 }]));
  const candidates = CANDIDATES.map((c) => ({ ...c, env: c.round < 2 ? "A" : "B" }));
  const run = smallRun({ labels, schedule: { 0: "A", 2: "B" }, snapshots: SNAPSHOTS, candidates, nItems: 4, environments });
  const rescored = engine.audit(run, { stored_scoring: "rescore" });
  const plain = engine.audit(run);
  assert.deepEqual(rescored.policies.frozen.decisions, plain.policies.frozen.decisions);
  assert.deepEqual(rescored.completeness.notes,
    ["rescore: no environment has decoding greedy-0.0 with scorer lenient; labels stored under A are used as recorded"]);
  assert.deepEqual(plain.completeness.notes, []);
});

// as run

test("as run needs the reference the loop recorded", () => {
  const block = engine.simulate(make(), "as_run");
  assert.deepEqual([block.available, block.missing, block.missing_count, block.decisions], [false, [], 0, []]);
  assert.equal(block.accepted, null);
  assert.equal(block.final_acc, null);
});

test("as run replays the recorded decisions", () => {
  const run = make({ references: true });
  const block = engine.simulate(run, "as_run"), frozen = engine.simulate(run, "frozen");
  assert.ok(block.available);
  assert.equal(block.name, "As run");
  // The recorded loop was a frozen-reference loop, so the two agree decision for decision.
  assert.deepEqual(block.decisions, frozen.decisions);
  for (const key of ["accepted", "false_accepts", "false_rejects", "refreshes", "calls", "final_acc", "final_prompt", "causes"]) {
    assert.deepEqual(block[key], frozen[key], key);
  }
});

test("as run keeps the recorded verdict even when the labels disagree", () => {
  const run = editable(make({ references: true }));
  run.candidates[3].accepted = false;        // the loop turned C4 down
  run.candidates[4].parent = "c3";
  const block = engine.simulate(run, "as_run");
  assert.deepEqual(column(block, "accepted"), [true, true, true, false, true]);
  assert.deepEqual(column(block, "incumbent"), ["p0", "c1", "c2", "c3", "c3"]);
  const d = block.decisions[3];
  assert.deepEqual([d.false_reject, d.wins, d.losses], [true, 3, 0]);
  assert.equal(block.false_rejects, 1);
});

test("as run counts recorded reruns as refreshes", () => {
  const run = editable(make({ references: true }));
  run.candidates[2].reference = { prompt: "c2", env: "E3", pass: "rerun" };
  const block = engine.simulate(run, "as_run");
  assert.equal(block.refreshes, 1);
  assert.equal(block.calls.reference_refresh, 4);
  const d = block.decisions[2];
  assert.deepEqual([d.ref_fresh, d.ref_pass, d.ref_round, d.ref_age, d.env_mismatch], [true, "rerun", 2, 0, false]);
  assert.deepEqual([d.wins, d.losses, d.inflation], [1, 1, 0]);
});

test("as run falls back to recorded counts when reference labels are absent", () => {
  const run = editable(make({ references: true }));
  run.prompts.old = "a reference from before the run";
  run.candidates[0].reference = { prompt: "old", env: "E1", pass: "current" };
  Object.assign(run.candidates[0], { wins: 9, losses: 2 });
  const block = engine.simulate(run, "as_run");
  const d = block.decisions[0];
  assert.ok(block.available);
  assert.deepEqual([d.wins, d.losses, d.accepted], [9, 2, true]);
  assert.deepEqual([d.rerun_wins, d.rerun_losses, d.inflation, d.rerun_accepts], [null, null, null, null]);
  assert.deepEqual([d.inc_acc, d.cand_acc, d.false_accept], [0.25, 0.5, false]);
  delete run.candidates[0].wins;
  assert.equal(engine.simulate(run, "as_run").decisions[0].wins, null);
});

test("as run dates a stored reference from the round it was produced", () => {
  const run = editable(make({ references: true }));
  run.candidates[4].reference = { prompt: "c3", env: "E3", pass: "current" };
  const block = engine.simulate(run, "as_run");
  // c3 was first scored under E3 as the candidate of round 2.
  assert.deepEqual([block.decisions[4].ref_round, block.decisions[4].ref_age], [2, 2]);
  assert.deepEqual(column(block, "ref_round").slice(0, 4), [0, 0, 0, 0]);
});

// sparse banks

test("a missing rerun blanks only what depends on it", () => {
  const block = engine.simulate(without(make(), ["p0", "E3", "rerun"]), "frozen");
  assert.ok(block.available);
  assert.deepEqual(block.missing, []);
  assert.deepEqual(column(block, "accepted"), [true, true, true, true, true]);
  assert.deepEqual(column(block, "rerun_wins"), [1, 1, null, null, null]);
  assert.deepEqual(column(block, "inflation"), [0, 0, null, null, null]);
  assert.deepEqual(column(block, "rerun_accepts"), [true, true, null, null, null]);
  // Without the rerun a false accept under a changed environment cannot be told apart.
  assert.deepEqual(column(block, "cause"), [null, "no_drift", null, null, null]);
  assert.deepEqual(block.causes, { stale: 0, anyway: 0, no_drift: 1 });
  assert.equal(block.false_accepts, 3);
  assert.equal(block.inflation, 0);
});

test("a policy that needs absent labels reports them instead of failing", () => {
  const run = without(make(), ["c1", "E3", "rerun"]);
  const block = engine.simulate(run, "per_batch");
  assert.equal(block.available, false);
  assert.deepEqual(block.decisions, []);
  assert.deepEqual(block.missing, [{ prompt: "c1", env: "E3", pass: "rerun" }]);
  assert.equal(block.missing_count, 1);
  assert.deepEqual([block.accepted, block.false_accepts, block.final_acc, block.inflation, block.calls, block.causes],
    [null, null, null, null, null, null]);
  assert.deepEqual([block.id, block.name], ["per_batch", "Per-batch"]);
  assert.equal(engine.simulate(run, "env_triggered").available, false);
  assert.equal(engine.simulate(run, "frozen").available, true);
});

test("missing labels are listed once, in the order they were needed, and capped", () => {
  const labels = Object.fromEntries(Object.entries(LABELS).map(([h, per]) => [h, { E1: per.E1 }]));   // nothing under E3
  const block = engine.simulate(make({ labels, reruns: {} }), "frozen");
  assert.equal(block.available, false);
  assert.deepEqual(block.missing, [{ prompt: "c3", env: "E3", pass: "current" }, { prompt: "c2", env: "E3", pass: "current" },
    { prompt: "c4", env: "E3", pass: "current" }, { prompt: "c5", env: "E3", pass: "current" }]);
  assert.equal(block.missing_count, 4);

  const many = {}, candidates = [];
  for (let i = 0; i <= 30; i++) many[`q${i}`] = { E1: "1000" };
  for (let i = 1; i <= 30; i++) candidates.push({ id: `C${i}`, round: i - 1, prompt: `q${i}`, parent: "q0", accepted: false });
  const run = smallRun({ labels: many, schedule: { 0: "E3" }, snapshots: new Array(30).fill("q0"), candidates, nItems: 4 });
  const capped = engine.simulate(run, "frozen");
  assert.equal(capped.missing.length, 20);
  assert.equal(capped.missing_count, 31);
});

test("audit never throws on a sparse bank", () => {
  const run = make({ labels: { p0: { E1: "1000" }, c1: { E1: "1100" } }, reruns: { "p0/E1": null, "c1/E1": null } });
  const result = engine.audit(run);
  assert.equal(result.completeness.full_bank, false);
  assert.deepEqual(Object.values(result.policies).map((b) => b.available), [false, false, false, false, false, false]);
  assert.equal(result.rounds[0].candidate_acc, 0.5);
  assert.equal(result.rounds[2].candidate_acc, null);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), result);
});

test("full bank means both passes for every prompt and environment", () => {
  assert.deepEqual(engine.audit(paperRun(1)).completeness, { full_bank: true, notes: [] });
  assert.equal(engine.audit(without(paperRun(1), ["cf7e8a98a5cc", "E2", "rerun"])).completeness.full_bank, false);
  assert.equal(engine.audit(make()).completeness.full_bank, false);       // E2 and E4 were never measured
});

// audit

test("audit result has the documented shape", () => {
  const result = engine.audit(make({ references: true }));
  assert.deepEqual(Object.keys(result),
    ["schema", "tool", "run", "options", "environments", "rounds", "policies", "scorer_flips", "completeness"]);
  assert.equal(result.schema, "driftaudit.audit/v1");
  assert.deepEqual(result.tool, { name: "driftaudit", version: DA.schema.VERSION });
  assert.deepEqual(result.run, {
    id: "small", seed: 1, source: "synthetic", task: { name: "toy", n_items: 4, n_dev: 3 }, model: { id: "test-model" },
    n_items: 4, n_rounds: 5, n_candidates: 5,
  });
  assert.deepEqual(result.options, {
    stored_scoring: "as_recorded", margin: 0, schedule: { 0: "E1", 2: "E3" }, schedule_overridden: false,
    fixed_age: null, periodic_k: 3,
  });
  assert.deepEqual(Object.keys(result.policies), POLICY_IDS);
  const block = result.policies.frozen;
  assert.deepEqual(Object.keys(block), ["id", "name", "rule", "available", "missing", "missing_count", "accepted",
    "false_accepts", "false_rejects", "false_accept_rate", "refreshes", "calls", "total_calls", "final_acc",
    "final_prompt", "inflation", "causes", "decisions"]);
  assert.deepEqual(Object.keys(block.decisions[0]), ["round", "env", "candidate", "incumbent", "ref_prompt", "ref_env",
    "ref_pass", "ref_scored_env", "ref_fresh", "ref_round", "ref_age", "env_mismatch", "wins", "losses", "rerun_wins",
    "rerun_losses", "inflation", "accepted", "rerun_accepts", "inc_acc", "cand_acc", "delta_pp", "outcome",
    "false_accept", "false_reject", "cause"]);
  for (const other of Object.values(engine.audit(make()).policies)) assert.deepEqual(Object.keys(other), Object.keys(block));
});

test("audit blocks are what simulate returns", () => {
  const run = make({ references: true });
  const result = engine.audit(run, { margin: 1, periodic_k: 2 });
  for (const [policy, block] of Object.entries(result.policies)) {
    assert.deepEqual(block, engine.simulate(run, policy, { margin: 1, periodic_k: 2 }));
  }
});

test("audit can be limited to some policies", () => {
  assert.deepEqual(Object.keys(engine.audit(make(), { policies: ["env_triggered", "frozen"] }).policies), ["frozen", "env_triggered"]);
  assert.deepEqual(Object.keys(engine.audit(make(), { policies: "per_batch" }).policies), ["per_batch"]);
});

test("environments are listed in order of first use", () => {
  const result = engine.audit(make());
  assert.deepEqual(result.environments.map((e) => [e.id, e.first_round, e.rounds]),
    [["E1", 0, [0, 1]], ["E3", 2, [2, 3, 4]], ["E2", null, []], ["E4", null, []]]);
  const first = result.environments[0];
  assert.deepEqual(Object.keys(first), ["id", "name", "decoding", "scorer", "fingerprint", "detail", "first_round", "rounds"]);
  assert.deepEqual([first.name, first.decoding, first.scorer], ["Unchanged", "greedy-0.0", "v1"]);
});

test("rounds describe the recorded trajectory", () => {
  const result = engine.audit(make());
  assert.deepEqual(result.rounds.map((r) => r.round), [0, 1, 2, 3, 4]);
  assert.deepEqual(result.rounds.map((r) => r.env), ["E1", "E1", "E3", "E3", "E3"]);
  assert.deepEqual(result.rounds.map((r) => r.env_changed), [false, false, true, false, false]);
  assert.deepEqual(result.rounds.map((r) => r.incumbent), SNAPSHOTS);
  assert.deepEqual(result.rounds.map((r) => r.candidate), ["c1", "c2", "c3", "c4", "c5"]);
  assert.deepEqual(result.rounds.map((r) => r.candidate_id), ["C1", "C2", "C3", "C4", "C5"]);
  assert.deepEqual(result.rounds.map((r) => r.candidate_acc), [0.5, 0.5, 0.5, 1, 0.75]);
  assert.deepEqual(result.rounds.map((r) => r.incumbent_acc), [0.25, 0.5, 0.5, 0.5, 1]);
  assert.deepEqual(Object.keys(result.rounds[0]),
    ["round", "env", "env_changed", "incumbent", "candidate", "candidate_id", "note", "candidate_acc", "incumbent_acc"]);
});

test("a schedule override moves the environment changes", () => {
  const run = make();
  const result = engine.audit(run, { schedule: { 0: "E1", 4: "E3" } });
  assert.deepEqual(result.options.schedule, { 0: "E1", 4: "E3" });
  assert.equal(result.options.schedule_overridden, true);
  assert.deepEqual(result.rounds.map((r) => r.env), ["E1", "E1", "E1", "E1", "E3"]);
  assert.deepEqual(result.environments.slice(0, 2).map((e) => e.rounds), [[0, 1, 2, 3], [4]]);
  assert.deepEqual(column(result.policies.frozen, "env_mismatch"), [false, false, false, false, true]);
  assert.deepEqual(run.schedule, { 0: "E1", 2: "E3" });
  assert.equal(engine.audit(run, { schedule: { 0: "E1", 2: "E3" } }).options.schedule_overridden, false);
  assert.equal(engine.audit(run, { schedule: null }).options.schedule_overridden, false);
});

test("scorer flips compare environments that share their text", () => {
  // p0 gains two items under the lenient reading, c1, c4 and c5 one each; nothing is lost.
  assert.deepEqual(engine.audit(make()).scorer_flips,
    [{ from_env: "E1", to_env: "E3", prompts: 6, items: 24, wrong_to_right: 5, right_to_wrong: 0 }]);
});

test("audit reads a toolkit run file and leaves it as it was", () => {
  const before = JSON.stringify(legacyRun(5));
  const result = engine.audit(legacyRun(5), { schedule: { 0: "E1", 4: "E1", 8: "E3" }, stored_scoring: "rescore", margin: 2 });
  assert.equal(result.run.id, "gsm8k-qwen2.5-1.5b-seed5");
  assert.equal(JSON.stringify(legacyRun(5)), before);
  const loaded = JSON.stringify(paperRun(2));
  engine.audit(paperRun(2), { stored_scoring: "rescore", margin: 2 });
  assert.equal(JSON.stringify(paperRun(2)), loaded);
});

test("audit of a run with no rounds yet is empty, not an error", () => {
  const run = smallRun({ labels: {}, schedule: { 0: "A" }, snapshots: [], candidates: [], nItems: 4, id: "empty",
    environments: { A: env("", "greedy-0.0", "strict", "m") } });
  const result = engine.audit(run);
  assert.deepEqual(result.rounds, []);
  assert.equal(result.run.n_rounds, 0);
  const block = result.policies.frozen;
  assert.ok(block.available);
  assert.deepEqual([block.decisions, block.accepted], [[], 0]);
  assert.deepEqual([block.final_acc, block.final_prompt, block.inflation, block.false_accept_rate], [null, null, null, null]);
  const study = engine.study([run]);
  assert.deepEqual(JSON.parse(JSON.stringify(study)), study);
});

test("results are plain JSON without NaN", () => {
  for (const seed of SEEDS) {
    const result = engine.audit(paperRun(seed));
    assert.deepEqual(JSON.parse(JSON.stringify(result)), result);
  }
});

test("bad options are refused with a reason", () => {
  const run = make();
  assert.throws(() => engine.simulate(run, "sometimes"), /^Error: unknown policy 'sometimes'; choose from frozen, /);
  assert.throws(() => engine.audit(run, { policies: ["frozen", "sometimes"] }), /unknown policy/);
  assert.throws(() => engine.audit(run, { stored_scoring: "relabel" }), /stored_scoring must be 'as_recorded' or 'rescore', not 'relabel'/);
  assert.throws(() => engine.audit(run, { schedule: { 0: "E9" } }), /schedule names environment 'E9', which the run does not define \(it defines E1, E2, E3, E4\)/);
  assert.throws(() => engine.audit(run, { schedule: { x: "E1" } }), /schedule must map start rounds/);
  assert.throws(() => engine.audit(run, { schedule: {} }), /schedule needs at least one entry/);
  assert.throws(() => engine.audit(run, { periodic_k: 0 }), /periodic_k must be a whole number of rounds, 1 or more, not 0/);
  assert.throws(() => engine.audit(run, { fixed_age: -1 }), /fixed_age must be a whole number of rounds, 0 or more, not -1/);
  assert.throws(() => engine.audit(run, { margin: "1" }), /margin must be a number, not '1'/);
  assert.throws(() => engine.audit({ hello: "world" }), DA.schema.RunError);
});

// item cells

test("item cells classify each item against both readings", () => {
  const run = make();
  const decision = engine.simulate(run, "frozen").decisions[2];
  assert.deepEqual(engine.itemCells(run, decision), {
    n: 4, stored: "bwnn", rerun: "bbnn", candidate: "1100", reference_stored: "1000", reference_rerun: "1100",
  });
});

test("item cells agree with the decision counts", () => {
  const run = paperRun(5);
  const tally = (cells, ch) => cells.split(ch).length - 1;
  for (const options of [{}, { stored_scoring: "rescore" }]) {
    for (const block of Object.values(engine.audit(run, options).policies)) {
      for (const d of block.decisions) {
        const cells = engine.itemCells(run, d);
        assert.deepEqual([tally(cells.stored, "w"), tally(cells.stored, "l")], [d.wins, d.losses]);
        assert.deepEqual([tally(cells.rerun, "w"), tally(cells.rerun, "l")], [d.rerun_wins, d.rerun_losses]);
        assert.deepEqual([cells.stored.length, cells.n], [200, 200]);
      }
    }
  }
});

test("item cells follow a rerun that became the reference", () => {
  const run = make();
  const cells = engine.itemCells(run, engine.simulate(run, "env_triggered").decisions[3]);
  assert.deepEqual([cells.candidate, cells.reference_stored, cells.stored], ["1111", "1110", "bbbw"]);
});

test("item cells leave out a rerun that was never recorded", () => {
  const run = without(make(), ["p0", "E3", "rerun"]);
  const cells = engine.itemCells(run, engine.simulate(run, "frozen").decisions[2]);
  assert.deepEqual([cells.rerun, cells.reference_rerun, cells.stored], [null, null, "bwnn"]);
});

// age pairs (ported from toolkit/tests/test_age.py)

const AGE_LABELS = {
  p0: { E1: "1000", E4: "1110" },
  p1: { E1: "1100", E4: "1110" },
  p2: { E1: "1001", E4: "1100" },
  p3: { E1: "1010", E4: "1110" },
};
// The reruns that do not repeat their stored labels: one reference and one candidate.
const AGE_RERUNS = { "p0/E1": "1100", "p3/E1": "1110" };

function ageRun(seed = 1, labels = AGE_LABELS) {
  const candidates = ["p0", "p1", "p1"].map((parent, i) => ({ id: `C${i + 1}`, round: i, prompt: `p${i + 1}`, parent, accepted: i === 0 }));
  return smallRun({ labels, schedule: { 0: "E1", 1: "E4" }, snapshots: ["p0", "p1", "p1"], candidates, nItems: 4,
    reruns: AGE_RERUNS, seed, id: `age-${seed}` });
}

function pairs(run, age, current) {
  return engine.agePairs(run, age, { force_stored_env: "E1", current_env: current });
}

function counts(ms) {
  return ["promote", "false_accept", "promote_rerun", "false_accept_rerun"].map((key) => ms.filter((m) => m[key]).length);
}

function average(ms, key) {
  return ms.reduce((total, m) => total + m[key], 0) / ms.length;
}

test("pairs shrink with age", () => {
  assert.deepEqual([0, 1, 2, 3].map((age) => pairs(ageRun(), age, "E1").length), [3, 2, 1, 0]);
});

test("age zero unchanged is the ground-truth gate", () => {
  const ms = pairs(ageRun(), 0, "E1");
  assert.deepEqual(counts(ms), [1, 0, 0, 0]);
  // p0's rerun differs from its stored labels on one item, and that is all the inflation there is.
  assert.ok(close(average(ms, "stored_win"), 1 / 4));
  assert.ok(close(average(ms, "rerun_win"), 1 / 6));
  assert.ok(close(average(ms, "inflation"), 1 / 12));
  assert.deepEqual(Object.keys(ms[0]), ["round", "stored_win", "rerun_win", "inflation", "promote", "false_accept",
    "promote_rerun", "false_accept_rerun", "env_changed"]);
});

test("a changed environment inflates against stored labels", () => {
  const ms = pairs(ageRun(), 0, "E4");
  assert.deepEqual(ms.map((m) => m.inflation), [0.5, 0, 0.25]);
  assert.deepEqual(counts(ms), [2, 2, 0, 0]);
  assert.ok(ms.every((m) => m.env_changed));
});

test("a false accept is judged against the incumbent of the candidate's round", () => {
  assert.deepEqual(counts(pairs(ageRun(), 1, "E1")).slice(0, 2), [1, 1]);
  assert.deepEqual(counts(pairs(ageRun(), 2, "E1")).slice(0, 2), [1, 1]);
});

test("refreshing an old reference does not make it the incumbent", () => {
  const weak = { ...AGE_LABELS, p0: { E1: "1000", E4: "1000" } };
  assert.deepEqual(counts(pairs(ageRun(1, weak), 2, "E4")), [1, 1, 1, 1]);
});

test("age pairs skip pairs the bank cannot score", () => {
  const run = without(ageRun(), ["p1", "E1", "rerun"]);
  assert.deepEqual(pairs(run, 0, "E1").map((m) => m.round), [0]);
  assert.deepEqual(pairs(run, 0, "E2"), []);
  assert.throws(() => engine.agePairs(run, -1), /age must be a whole number of rounds/);
});

// study

const OTHER = { ...AGE_LABELS, p3: { ...AGE_LABELS.p3, E4: "1111" } };

test("study pools counts and averages per-run values", () => {
  const runs = [ageRun(1), ageRun(2, OTHER)];
  const result = engine.study(runs, { ages: [0, 1, 2] });
  assert.deepEqual(Object.keys(result), ["schema", "tool", "options", "runs", "source", "n_runs", "n_decisions", "policies",
    "policy_tests", "probe", "age", "scorer_flips", "verdict_flips"]);
  assert.equal(result.schema, "driftaudit.study/v1");
  assert.deepEqual(result.runs, [{ id: "age-1", seed: 1, source: "synthetic" }, { id: "age-2", seed: 2, source: "synthetic" }]);
  assert.equal(result.source, "synthetic");
  assert.deepEqual([result.n_runs, result.n_decisions], [2, 6]);
  const audits = runs.map((r) => engine.audit(r));
  const row = result.policies.frozen;
  assert.deepEqual(Object.keys(row), ["name", "accepted", "false_accepts", "false_rejects", "false_accept_rate_pooled",
    "final_acc", "total_calls", "refreshes", "causes", "per_run"]);
  for (const key of ["accepted", "false_accepts", "false_rejects"]) {
    assert.equal(row[key], audits[0].policies.frozen[key] + audits[1].policies.frozen[key]);
  }
  assert.deepEqual(row.per_run, audits.map((a) => {
    const b = a.policies.frozen;
    return { id: a.run.id, seed: a.run.seed, accepted: b.accepted, false_accepts: b.false_accepts,
      false_rejects: b.false_rejects, final_acc: b.final_acc, total_calls: b.total_calls, refreshes: b.refreshes };
  }));
  const finals = audits.map((a) => a.policies.frozen.final_acc);
  assert.deepEqual(row.final_acc.per_run, finals);
  assert.equal(row.final_acc.mean, (finals[0] + finals[1]) / 2);
  assert.ok(close(row.final_acc.sd, Math.abs(finals[0] - finals[1]) / Math.SQRT2));
  assert.deepEqual([Object.keys(row.total_calls), Object.keys(row.refreshes)], [["mean", "sd"], ["mean", "sd"]]);
});

test("study age rows pool promotions over runs", () => {
  const result = engine.study([ageRun(1), ageRun(2, OTHER)], { ages: [0, 1, 2] });
  assert.deepEqual([result.age.stored_env, result.age.ages, Object.keys(result.age.by_env)], ["E1", [0, 1, 2], ["E1", "E4"]]);
  const row = result.age.by_env.E4[0];
  assert.deepEqual(Object.keys(row), ["age", "pairs", "mean", "lo", "hi", "per_run", "promoted", "false_accepts"]);
  assert.deepEqual([row.age, row.pairs, row.promoted, row.false_accepts], [0, 6, 4, 3]);
  assert.ok(close(row.per_run[0], 25) && close(row.per_run[1], 25));
  assert.deepEqual(result.age.by_env.E1.map((r) => r.pairs), [6, 4, 2]);
});

test("study default ages stop below the run length", () => {
  const result = engine.study([ageRun()]);
  assert.deepEqual(result.age.ages, [0, 1]);
  assert.equal(result.probe.age, 2);          // min(3, rounds - 1)
  assert.equal(engine.study([ageRun()], { probe_age: 1 }).probe.age, 1);
});

test("study of one run has values but no interval", () => {
  const result = engine.study([ageRun()], { probe_age: 0 });
  assert.deepEqual(result.probe.by_env.E4, { mean: 25, sd: 0, lo: null, hi: null, per_run: [25], n_positive: 1, same_sign: 1 });
  assert.equal(result.policies.frozen.final_acc.sd, 0);
});

test("study probe covers the environments every run defines", () => {
  const result = engine.study([ageRun(1), ageRun(2)]);
  assert.deepEqual(Object.keys(result.probe.by_env), ["E1", "E2", "E3", "E4"]);
  // E2 was never measured: there is no value to average, and that is not a zero.
  assert.deepEqual(result.probe.by_env.E2,
    { mean: null, sd: null, lo: null, hi: null, per_run: [null, null], n_positive: 0, same_sign: 0 });
});

test("study only pools policies every run can replay", () => {
  const full = make({ references: true });
  const sparse = without(make({ references: true, id: "sparse", seed: 2 }), ["c1", "E3", "rerun"]);
  const result = engine.study([full, sparse]);
  // Per-batch, environment-triggered and every-3-rounds all need the rerun that is absent.
  assert.deepEqual(Object.keys(result.policies), ["frozen", "stored_incumbent", "as_run"]);
  assert.deepEqual(result.policy_tests, []);
  const both = engine.study([full, make({ references: true, id: "again", seed: 2 })]);
  assert.deepEqual(Object.keys(both.policies), POLICY_IDS);
  assert.deepEqual(both.policy_tests.map((t) => [t.a, t.b]),
    ["frozen", "stored_incumbent", "per_batch", "periodic", "as_run"].map((p) => ["env_triggered", p]));
  const first = both.policy_tests[0];
  assert.deepEqual(Object.keys(first), ["a", "b", "errors_a", "errors_b", "n", "fisher_p"]);
  assert.deepEqual([first.errors_a, first.errors_b, first.n], [0, 6, 10]);
});

test("study passes audit options through", () => {
  const runs = [make(), make({ id: "two", seed: 2 })];
  const result = engine.study(runs, { margin: 1, policies: ["frozen", "env_triggered"] });
  assert.deepEqual(Object.keys(result.policies), ["frozen", "env_triggered"]);
  assert.equal(result.policies.frozen.accepted, 2 * engine.simulate(runs[0], "frozen", { margin: 1 }).accepted);
  assert.equal(result.options.margin, 1);
});

test("study verdict flips need two scorers on the same text", () => {
  const environments = { A: env("", "greedy-0.0", "strict", "m"), B: env("", "sample-0.2", "strict", "m") };
  const run = smallRun({ labels: { p0: { A: "1000" }, c1: { A: "1100" } }, schedule: { 0: "A" }, snapshots: ["p0"],
    candidates: [{ id: "C1", round: 0, prompt: "c1", parent: "p0" }], nItems: 4, environments });
  const result = engine.study([run]);
  assert.equal(result.verdict_flips, null);
  assert.deepEqual(result.scorer_flips, []);
  // In the five-round run C1 and C2 change verdict between the strict and the lenient reading.
  assert.deepEqual(engine.study([make()]).verdict_flips, { n: 5, flipped: 2 });
});

test("study needs at least one run", () => {
  assert.throws(() => engine.study([]), /study needs at least one run/);
});

test("study reads toolkit run files", () => {
  assert.deepEqual(engine.study([legacyRun(1), legacyRun(2)]), engine.study([paperRun(1), paperRun(2)]));
});

test("an audit of a paper run takes a few milliseconds", () => {
  const run = paperRun(3);
  engine.audit(run);
  const start = process.hrtime.bigint();
  for (let i = 0; i < 20; i++) engine.audit(run);
  const each = Number(process.hrtime.bigint() - start) / 20e6;
  assert.ok(each < 25, `${each.toFixed(2)} ms per audit`);
});
