"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { DA, ROOT, SEEDS, readJson, exists, legacyRun, paperRun, paperRuns, close, roundsTo, differences, column } = require("./helpers.js");

// The numbers the paper reports, recomputed in JavaScript from the five saved runs, and the
// same runs checked against the files the toolkit wrote from them: replay/*.json (what the
// case study shows), results/stats.md, results/table7.md and results/table6_decisions.csv.
// Printed values are compared at the precision they are printed with.

const engine = DA.engine;
const study = engine.study(paperRuns());
const audits = new Map(SEEDS.map((seed) => [seed, engine.audit(paperRun(seed))]));

function assertRounds(value, printed, digits, what) {
  assert.ok(roundsTo(value, printed, digits), `${what}: ${value} does not round to ${printed}`);
}

test("the study covers five runs and 55 decisions", () => {
  assert.deepEqual([study.n_runs, study.n_decisions], [5, 55]);
  assert.deepEqual(study.runs.map((r) => r.seed), SEEDS);
  assert.deepEqual(study.runs.map((r) => r.id), SEEDS.map((s) => `gsm8k-qwen2.5-1.5b-seed${s}`));
});

// False accepts, accepts, false rejects, final accuracy mean and sd (%), model calls, reruns.
const TABLE_3 = {
  frozen: [13, 34, 0, 70.8, 2.0, 4411, 0],
  stored_incumbent: [0, 8, 8, 71.2, 2.0, 4411, 0],
  per_batch: [3, 13, 11, 69.7, 2.2, 6611, 11],
  env_triggered: [2, 16, 2, 72.5, 2.2, 4811, 2],
};

test("table 3: refresh policies", () => {
  for (const [policy, [falseAccepts, accepted, falseRejects, acc, sd, calls, reruns]] of Object.entries(TABLE_3)) {
    const row = study.policies[policy];
    assert.deepEqual([row.false_accepts, row.accepted, row.false_rejects], [falseAccepts, accepted, falseRejects], policy);
    assertRounds(100 * row.final_acc.mean, acc, 1, `${policy} final accuracy`);
    assertRounds(100 * row.final_acc.sd, sd, 1, `${policy} final accuracy sd`);
    assert.deepEqual([row.total_calls.mean, row.total_calls.sd], [calls, 0], policy);
    assert.deepEqual([row.refreshes.mean, row.refreshes.sd], [reruns, 0], policy);
    assert.equal(row.false_accept_rate_pooled, falseAccepts / accepted);
  }
});

test("table 6: pooled and per-seed false-accept rates", () => {
  const expected = {
    frozen: [38.2, 35.7, 22.6, ["4/7", "3/7", "2/7", "0/5", "4/8"]],
    per_batch: [23.1, 20.0, 20.9, ["0/2", "0/1", "1/4", "1/4", "1/2"]],
    env_triggered: [12.5, 13.3, 18.3, ["0/4", "0/1", "1/3", "0/5", "1/3"]],
  };
  for (const [policy, [pooled, seedMean, seedSd, perSeed]] of Object.entries(expected)) {
    const row = study.policies[policy];
    const rates = row.per_run.map((r) => r.false_accepts / r.accepted);
    assertRounds(100 * row.false_accept_rate_pooled, pooled, 1, `${policy} pooled`);
    assertRounds(100 * DA.stats.mean(rates), seedMean, 1, `${policy} seed mean`);
    assertRounds(100 * DA.stats.sd(rates), seedSd, 1, `${policy} seed sd`);
    assert.deepEqual(row.per_run.map((r) => `${r.false_accepts}/${r.accepted}`), perSeed);
  }
});

test("fisher tests against environment-triggered", () => {
  const tests = Object.fromEntries(study.policy_tests.map((t) => [t.b, t]));
  assert.ok(study.policy_tests.every((t) => t.a === "env_triggered" && t.errors_a === 4 && t.n === 55));
  for (const [policy, errors, p] of [["frozen", 13, 0.033], ["per_batch", 14, 0.019], ["stored_incumbent", 8, 0.360]]) {
    assert.equal(tests[policy].errors_b, errors);
    assertRounds(tests[policy].fisher_p, p, 3, `fisher p against ${policy}`);
  }
});

test("figure 4: drift inflation at reference age 3", () => {
  const probe = study.probe;
  assert.deepEqual([probe.age, probe.stored_env], [3, "E1"]);
  // Mean, interval, sd (pp), seeds above zero, seeds with the sign of the mean.
  const expected = {
    E1: [-0.12, -0.64, 0.39, 0.41, 2, 3],
    E2: [-0.59, -2.61, 1.43, 1.63, 2, 3],
    E3: [1.31, 0.65, 1.98, 0.53, 5, 5],
    E4: [1.54, 0.04, 3.04, 1.21, 4, 4],
  };
  assert.deepEqual(Object.keys(probe.by_env), Object.keys(expected));
  for (const [envId, [mean, lo, hi, sd, positive, sameSign]] of Object.entries(expected)) {
    const cell = probe.by_env[envId];
    assertRounds(cell.mean, mean, 2, `${envId} mean`);
    assertRounds(cell.lo, lo, 2, `${envId} lower bound`);
    assertRounds(cell.hi, hi, 2, `${envId} upper bound`);
    assertRounds(cell.sd, sd, 2, `${envId} sd`);
    assert.deepEqual([cell.n_positive, cell.same_sign, cell.per_run.length], [positive, sameSign, 5]);
  }
});

test("frozen false-accept causes", () => {
  assert.deepEqual(study.policies.frozen.causes, { stale: 6, anyway: 3, no_drift: 4 });
  assert.deepEqual(audits.get(5).policies.frozen.causes, { stale: 3, anyway: 0, no_drift: 1 });
});

test("scorer flips between the strict and the lenient extractor", () => {
  assert.deepEqual(study.scorer_flips[0],
    { from_env: "E1", to_env: "E3", prompts: 57, items: 11400, wrong_to_right: 638, right_to_wrong: 0 });
  assert.deepEqual(study.scorer_flips.map((f) => [f.from_env, f.to_env]), [["E1", "E3"], ["E2", "E4"]]);
  assert.equal(study.scorer_flips[1].right_to_wrong, 0);
});

test("verdicts that change with the extractor", () => {
  assert.deepEqual(study.verdict_flips, { n: 55, flipped: 18 });
});

// Every decision of the three policies on seed 1, as wins, losses, accepted.
const TABLE_2 = {
  frozen: [[25, 43, false], [26, 23, true], [14, 59, false], [22, 19, true], [22, 26, false], [25, 19, true],
    [25, 19, true], [7, 88, false], [27, 17, true], [24, 18, true], [24, 22, true]],
  per_batch: [[27, 42, false], [27, 21, true], [14, 62, false], [25, 25, false], [28, 23, true], [14, 19, false],
    [14, 19, false], [12, 104, false], [16, 19, false], [15, 22, false], [13, 24, false]],
  env_triggered: [[25, 43, false], [26, 23, true], [14, 62, false], [25, 25, false], [28, 23, true],
    [17, 7, true], [0, 0, false], [10, 97, false], [20, 18, true], [13, 17, false], [14, 22, false]],
};

test("table 2: decisions for seed 1", () => {
  const blocks = audits.get(1).policies;
  for (const [policy, rows] of Object.entries(TABLE_2)) {
    assert.deepEqual(blocks[policy].decisions.map((d) => [d.wins, d.losses, d.accepted]), rows, policy);
    assert.deepEqual(column(blocks[policy], "env"), ["E1", "E1", "E1", "E1", "E2", "E2", "E2", "E2", "E4", "E4", "E4"]);
  }
  for (const [policy, acc, falseAccepts, accepted] of [["frozen", 69, 4, 7], ["per_batch", 67, 0, 2], ["env_triggered", 73, 0, 4]]) {
    assertRounds(100 * blocks[policy].final_acc, acc, 1, `${policy} final accuracy`);
    assert.deepEqual([blocks[policy].false_accepts, blocks[policy].accepted], [falseAccepts, accepted]);
  }
});

// Pairs, the interval of drift inflation (pp), false accepts and promotions, by reference age.
const TABLE_7 = {
  E1: [[0, 55, -0.34, 0.21, 0, 18], [1, 50, -0.32, 0.26, 5, 20], [3, 40, -0.64, 0.39, 7, 17], [5, 30, -1.10, 0.53, 8, 15],
    [10, 5, -1.59, 0.79, 3, 4]],
  E4: [[0, 55, 0.22, 2.07, 18, 27], [1, 50, 0.30, 2.06, 16, 25], [3, 40, 0.04, 3.04, 10, 18], [5, 30, 0.90, 4.14, 10, 16],
    [10, 5, 1.92, 5.08, 4, 5]],
};

test("table 7: effect of reference age", () => {
  assert.deepEqual([study.age.stored_env, study.age.ages, Object.keys(study.age.by_env)], ["E1", [0, 1, 3, 5, 10], ["E1", "E4"]]);
  for (const [envId, rows] of Object.entries(TABLE_7)) {
    rows.forEach(([age, pairs, lo, hi, falseAccepts, promoted], i) => {
      const row = study.age.by_env[envId][i];
      assert.deepEqual([row.age, row.pairs, row.false_accepts, row.promoted, row.per_run.length], [age, pairs, falseAccepts, promoted, 5]);
      assertRounds(row.lo, lo, 2, `${envId} age ${age} lower bound`);
      assertRounds(row.hi, hi, 2, `${envId} age ${age} upper bound`);
    });
  }
  // The age-3 rows are the probe's Unchanged and Combined cells.
  assert.equal(study.age.by_env.E4[2].mean, study.probe.by_env.E4.mean);
});

test("appendix C: schedule ablations", () => {
  const frozenInflation = (schedule) =>
    SEEDS.map((seed) => 100 * engine.simulate(paperRun(seed), "frozen", { schedule }).inflation);
  const full = frozenInflation(null);
  // Mean and sd of the drop in drift inflation (pp), the paired t test, seeds with a drop.
  const expected = [[{ 0: "E1", 4: "E2", 8: "E2" }, 0.59, 0.25, 0.006, 5], [{ 0: "E1", 4: "E1", 8: "E3" }, 0.89, 1.19, 0.169, 4]];
  for (const [schedule, mean, sd, p, drops] of expected) {
    const other = frozenInflation(schedule);
    const d = full.map((x, i) => x - other[i]);
    assertRounds(DA.stats.mean(d), mean, 2, "mean drop");
    assertRounds(DA.stats.sd(d), sd, 2, "sd of the drop");
    assertRounds(DA.stats.tTestP(d), p, 3, "paired t test");
    assert.equal(d.filter((x) => x > 0).length, drops);
  }
});

test("environment-triggered final accuracy in each seed", () => {
  [73.0, 69.0, 73.0, 72.5, 75.0].forEach((acc, i) => {
    assertRounds(100 * audits.get(SEEDS[i]).policies.env_triggered.final_acc, acc, 1, `seed ${SEEDS[i]}`);
  });
});

// Against the files the toolkit wrote.

const TOOLKIT_POLICY = { P1: "frozen", P2: "per_batch", P3: "env_triggered" };

test("every decision matches the toolkit's decision table", () => {
  const lines = fs.readFileSync(path.join(ROOT, "toolkit", "results", "table6_decisions.csv"), "utf8").trim().split(/\r?\n/);
  const header = lines[0].split(",");
  const rows = lines.slice(1).map((line) => Object.fromEntries(line.split(",").map((cell, i) => [header[i], cell])));
  assert.equal(rows.length, 3 * 55);
  for (const row of rows) {
    const audit = audits.get(Number(row.seed));
    const index = audit.rounds.findIndex((r) => r.candidate_id === row.cid);
    const d = audit.policies[TOOLKIT_POLICY[row.policy]].decisions[index];
    assert.deepEqual([d.round, d.env, d.ref_env, d.wins, d.losses],
      [Number(row.round), row.env, row.ref_env, Number(row.wins), Number(row.losses)]);
    assert.deepEqual([d.accepted, d.false_accept, d.false_reject, d.ref_pass === "rerun", d.outcome],
      [row.accepted === "True", row.false_accept === "True", row.false_reject === "True", row.ref_fresh === "True", row.outcome]);
    assert.ok(close(d.inc_acc, Number(row.inc_acc)) && close(d.cand_acc, Number(row.cand_acc)) && close(d.delta_pp, Number(row.delta_pp)));
  }
});

test("the study matches the replay summary the case study reads", () => {
  const saved = readJson("replay", "all_seeds.json");
  assert.deepEqual([saved.seeds, saved.n_items, saved.rounds, saved.age], [SEEDS, 200, 11, study.probe.age]);
  for (const [legacy, policy] of Object.entries(TOOLKIT_POLICY)) {
    const ours = study.policies[policy], theirs = saved.policies[legacy];
    assert.deepEqual([ours.accepted, ours.false_accepts, ours.false_rejects], [theirs.accepted, theirs.false_accepts, theirs.false_rejects]);
    assert.ok(roundsTo(ours.final_acc.mean, theirs.final_acc[0]) && roundsTo(ours.final_acc.sd, theirs.final_acc[1]));
    assert.deepEqual([ours.total_calls.mean, ours.total_calls.sd], theirs.logical_calls);
    assert.deepEqual([ours.refreshes.mean, ours.refreshes.sd], theirs.refreshes);
    for (const row of ours.per_run) {
      const seed = saved.per_seed[String(row.seed)][legacy];
      assert.deepEqual([row.accepted, row.false_accepts, row.false_rejects, row.total_calls],
        [seed.accepted, seed.false_accepts, seed.false_rejects, seed.logical_calls]);
      assert.ok(roundsTo(row.final_acc, seed.final_acc));
    }
  }
  for (const [envId, theirs] of Object.entries(saved.inflation)) {
    const ours = study.probe.by_env[envId];
    for (const key of ["mean", "lo", "hi"]) assert.ok(roundsTo(ours[key], theirs[key]), `${envId} ${key}`);
    ours.per_run.forEach((x, i) => assert.ok(roundsTo(x, theirs.per_seed[i]), `${envId} seed ${i + 1}`));
    assert.equal(ours.same_sign, theirs.seeds_same_sign);
  }
  const causes = saved.false_promotion_causes;
  assert.deepEqual(study.policies.frozen.causes, { stale: causes.stale, anyway: causes.anyway, no_drift: causes.before_change });
  assert.deepEqual(study.verdict_flips, { n: saved.verdict_flips.n, flipped: saved.verdict_flips.flipped });
  const flips = study.scorer_flips[0];
  assert.deepEqual({ prompts: flips.prompts, items: flips.items, wrong_to_right: flips.wrong_to_right, right_to_wrong: flips.right_to_wrong },
    saved.answer_flips);
});

for (const seed of SEEDS) {
  test(`seed ${seed} matches its replay file`, () => {
    const saved = readJson("replay", `seed${seed}.json`);
    const run = paperRun(seed), audit = audits.get(seed);
    const label = (id) => DA.schema.promptLabel(run, id);
    const causes = { before_change: "no_drift", stale: "stale", anyway: "anyway", null: null };
    const decisions = audit.policies.frozen.decisions;
    assert.equal(decisions.length, saved.rounds.length);
    decisions.forEach((d, i) => {
      const r = saved.rounds[i];
      assert.deepEqual([d.round, d.env, label(d.incumbent), label(d.candidate), audit.rounds[i].note],
        [r.round, r.env, r.incumbent, r.candidate, r.note]);
      assert.deepEqual([d.wins, d.losses, d.rerun_wins, d.rerun_losses], [r.wins, r.losses, r.fresh_wins, r.fresh_losses]);
      assert.deepEqual([d.accepted, d.false_accept, d.false_reject, d.cause], [r.accepted, r.false_accept, r.false_reject, causes[r.cause]]);
      assert.ok(roundsTo(100 * (d.wins - d.losses) / 200, r.stale_net_pp) && roundsTo(100 * (d.rerun_wins - d.rerun_losses) / 200, r.fresh_net_pp));
      assert.ok(roundsTo(100 * d.inflation, r.inflation_pp) && roundsTo(d.delta_pp, r.delta_pp));
      assert.ok(roundsTo(d.inc_acc, r.incumbent_acc) && roundsTo(d.cand_acc, r.candidate_acc));
      assert.ok(roundsTo(d.accepted ? d.cand_acc : d.inc_acc, r.acc_after));
    });
    assert.deepEqual(decisions.filter((d) => d.cause === "stale" || d.cause === "anyway").map((d) => d.round),
      saved.meta.false_promotion_rounds);

    for (const [legacy, policy] of Object.entries(TOOLKIT_POLICY)) {
      const ours = audit.policies[policy], theirs = saved.policies[legacy];
      assert.deepEqual(
        ours.decisions.map((d) => [d.round, d.env, label(d.candidate), d.accepted, d.false_accept, d.false_reject, d.wins, d.losses, d.ref_pass === "rerun"]),
        theirs.decisions.map((d) => [d.round, d.env, d.candidate, d.accepted, d.false_accept, d.false_reject, d.wins, d.losses, d.reference_refreshed]));
      ours.decisions.forEach((d, i) => assert.ok(roundsTo(d.delta_pp, theirs.decisions[i].delta_pp)));
      assert.deepEqual([ours.accepted, ours.false_accepts, ours.false_rejects, ours.refreshes, ours.total_calls],
        [theirs.accepted, theirs.false_accepts, theirs.false_rejects, theirs.refreshes, theirs.logical_calls]);
      assert.ok(roundsTo(ours.final_acc, theirs.final_acc));
    }

    // The opening screen of the case study: the starting prompt under the strict and the lenient extractor.
    const meta = saved.meta, p0 = run.snapshots[0].prompt;
    assert.deepEqual([meta.seed, meta.n_items, meta.rounds, meta.reference.prompt_hash], [run.seed, 200, audit.run.n_rounds, p0]);
    assert.equal(label(p0), "p0");
    assert.equal(meta.reference.fingerprint, run.environments[meta.reference.env].fingerprint);
    const flips = engine.pair(DA.schema.labels(run, p0, "E3"), DA.schema.labels(run, p0, "E1"));
    assert.deepEqual({ n: 200, wrong_to_right: flips.wins, right_to_wrong: flips.losses }, meta.extractor_flips);
    assert.ok(roundsTo((flips.both_right + flips.losses) / 200, meta.baseline_strict_acc));
    assert.ok(roundsTo((flips.both_right + flips.wins) / 200, meta.baseline_lenient_acc));
    assert.deepEqual(meta.changes.map((c) => [c.round, c.env]),
      audit.environments.filter((e) => e.first_round > 0).map((e) => [e.first_round, e.id]));
    for (const [envId, fingerprint] of Object.entries(saved.fingerprints)) assert.equal(run.environments[envId].fingerprint, fingerprint);
    assert.deepEqual(Object.fromEntries(Object.keys(run.prompts).map((id) => [label(id), run.prompts[id]])), saved.prompts);
  });
}

test("promptLabel numbers prompts in the order the log lists them", () => {
  const run = paperRun(1);
  assert.deepEqual(Object.keys(run.prompts).slice(0, 3).map((id) => DA.schema.promptLabel(run, id)), ["p0", "p1", "p2"]);
  assert.equal(DA.schema.promptLabel(run, run.snapshots[0].prompt), "p0");
  assert.equal(DA.schema.promptLabel(run, "not-a-prompt"), "not-a-prompt");
  assert.equal(DA.schema.promptLabel(run, "toString"), "toString");
});

// The bundled v1 run logs were converted from the toolkit's files by the Python package.
// Loading either form must give the same audit.

const bundled = (seed) => ["data", "runs", "paper", `seed${seed}.json`];
const haveBundled = SEEDS.every((seed) => exists(...bundled(seed)));
const noBundle = haveBundled ? false : "data/runs/paper has not been built";

test("a bundled v1 run log audits exactly as the toolkit file it came from", { skip: noBundle }, () => {
  const options = [{}, { stored_scoring: "rescore", margin: 1, periodic_k: 2 }, { schedule: { 0: "E1", 4: "E1", 8: "E3" }, fixed_age: 1 }];
  for (const seed of SEEDS) {
    const v1 = readJson(...bundled(seed));
    assert.equal(v1.schema, "driftaudit.run/v1");
    assert.deepEqual(DA.schema.validate(v1), []);
    for (const o of options) {
      assert.deepEqual(differences(engine.audit(v1, o), engine.audit(legacyRun(seed), o), 0), [], `seed ${seed}`);
    }
    assert.deepEqual(engine.audit(v1), audits.get(seed));
  }
});

test("the bundled v1 run logs give the same study as the toolkit files", { skip: noBundle }, () => {
  const v1 = SEEDS.map((seed) => readJson(...bundled(seed)));
  assert.deepEqual(engine.study(v1), study);
  const index = readJson("data", "index.json");
  const listed = index.groups.flatMap((g) => g.runs).filter((r) => /data\/runs\/paper\//.test(r.url));
  assert.deepEqual(listed.map((r) => r.id), v1.map((r) => r.id));
});
