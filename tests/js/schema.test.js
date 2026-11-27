"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { DA, SEEDS, legacyRun, paperRun, smallRun } = require("./helpers.js");

const schema = DA.schema;
const MODEL = "Qwen/Qwen2.5-1.5B-Instruct";

// A small valid run with two rounds, as a plain object that has not been through load().
function filled() {
  const run = smallRun({
    labels: { p0: { E1: "1000" }, p1: { E1: "1100" }, p2: { E1: "0101" } },
    schedule: { 0: "E1" }, snapshots: ["p0", "p1"], nItems: 4,
    candidates: [{ id: "C1", round: 0, prompt: "p1", parent: "p0", accepted: true },
      { id: "C2", round: 1, prompt: "p2", parent: "p1", accepted: false }],
  });
  return JSON.parse(JSON.stringify(run));
}

function problemsAfter(change) {
  const run = filled();
  change(run);
  return schema.validate(run);
}

function expectProblem(change, text) {
  const problems = problemsAfter(change);
  assert.ok(problems.some((p) => p.includes(text)), `${JSON.stringify(text)} not in ${JSON.stringify(problems)}`);
}

// Labels

test("labels round trip as bitstrings", () => {
  assert.equal(schema.encodeLabels([1, 0, 0, 1]), "1001");
  assert.deepEqual(schema.decodeLabels("1001"), [1, 0, 0, 1]);
  assert.equal(schema.encodeLabels([true, false]), "10");
  assert.equal(schema.encodeLabels("0110"), "0110");
  assert.equal(schema.encodeLabels([]), "");
});

test("encodeLabels rejects anything but zero and one", () => {
  for (const bad of [[1, 2, 0], "01x1", [0.5], ["1", "0"], [null]]) {
    assert.throws(() => schema.encodeLabels(bad), (err) => err instanceof schema.RunError && /0 and 1/.test(err.message));
  }
});

// Legacy upgrade

test("legacy files are recognised", () => {
  assert.equal(schema.isLegacy(legacyRun(1)), true);
  assert.equal(schema.isLegacy(paperRun(1)), false);
  assert.equal(schema.isLegacy({ correct: {} }), false);
  assert.equal(schema.isLegacy([1, 2]), false);
  assert.equal(schema.isRun(legacyRun(1)), true);
  assert.equal(schema.isRun(paperRun(1)), true);
  assert.equal(schema.isRun({ hello: "world" }), false);
  assert.equal(schema.isRun(null), false);
});

test("upgrade fills in what the v1 format names", () => {
  const old = legacyRun(1);
  const run = schema.upgradeLegacy(old);
  assert.equal(run.schema, "driftaudit.run/v1");
  assert.equal(run.id, "gsm8k-qwen2.5-1.5b-seed1");
  assert.deepEqual(run.tool, { name: "driftaudit", version: schema.VERSION });
  assert.equal(run.source, "measured");
  assert.equal(run.seed, 1);
  assert.deepEqual(run.task, {
    name: "GSM8K", split: "test", n_items: 200, n_dev: 200, dataset: "openai/gsm8k (main)",
    revision: old.config.dataset_revision, items: "gsm8k/eval200",
  });
  assert.deepEqual(run.model, { id: MODEL, revision: old.config.model_revision, backend: "hf" });
  assert.deepEqual(run.schedule, { 0: "E1", 4: "E2", 8: "E4" });
  assert.deepEqual(run.cost, { n_dev: 200, proposal_calls: 1 });
  assert.equal(run.meta.config, old.config);
  assert.equal(run.meta.physical_calls, old.physical_calls);
  assert.deepEqual(run.prompts, old.prompts);
  assert.deepEqual(schema.validate(run), []);
  assert.deepEqual(Object.keys(run), ["schema", "id", "tool", "source", "seed", "task", "model", "environments",
    "schedule", "prompts", "snapshots", "candidates", "labels", "cost", "meta"]);
});

test("upgrade uses the paper's four environments", () => {
  const envs = schema.upgradeLegacy(legacyRun(2)).environments;
  assert.deepEqual(Object.keys(envs), ["E1", "E2", "E3", "E4"]);
  assert.deepEqual(Object.values(envs).map((e) => e.name), ["Unchanged", "Decoding", "Extraction", "Combined"]);
  assert.deepEqual(Object.values(envs).map((e) => e.decoding), ["greedy-0.0", "sample-0.2", "greedy-0.0", "sample-0.2"]);
  assert.deepEqual(Object.values(envs).map((e) => e.scorer), ["v1", "v1", "v2", "v2"]);
  assert.equal(envs.E1.fingerprint, `model=${MODEL};decode=greedy-0.0;extract=v1`);
  assert.equal(envs.E4.fingerprint, `model=${MODEL};decode=sample-0.2;extract=v2`);
  assert.deepEqual(envs.E2.detail, { temperature: 0.2, scorer_name: "strict numeric" });
  assert.deepEqual(envs.E3.detail, { temperature: 0, scorer_name: "lenient numeric" });
});

test("upgrade turns correct lists into label strings", () => {
  const old = legacyRun(3);
  const run = schema.upgradeLegacy(old);
  assert.deepEqual(Object.keys(run.labels), Object.keys(old.correct));
  for (const [h, perEnv] of Object.entries(old.correct)) {
    for (const [env, passes] of Object.entries(perEnv)) {
      for (const [tag, values] of Object.entries(passes)) assert.equal(run.labels[h][env][tag], values.join(""));
    }
  }
});

test("upgrade records what the loop compared against", () => {
  // The toolkit's gate scored candidate and incumbent in the same pass under the round's
  // environment, so its recorded wins and losses are exactly that comparison.
  for (const seed of SEEDS) {
    const old = legacyRun(seed);
    const run = schema.upgradeLegacy(old);
    old.candidates.forEach((before, i) => {
      const after = run.candidates[i];
      assert.deepEqual(after.reference, { prompt: before.parent, env: before.env, pass: "current" });
      for (const key of Object.keys(before)) assert.deepEqual(after[key], before[key]);
    });
  }
});

test("upgrade ids follow the seed, the model and the backend", () => {
  assert.equal(schema.upgradeLegacy(legacyRun(5)).id, "gsm8k-qwen2.5-1.5b-seed5");
  const mock = JSON.parse(JSON.stringify(legacyRun(1)));
  mock.config.backend = "mock";
  mock.seed = 7;
  const upgraded = schema.upgradeLegacy(mock);
  assert.equal(upgraded.source, "synthetic");
  assert.equal(upgraded.id, "gsm8k-qwen2.5-1.5b-instruct-mock-seed7");
  const other = JSON.parse(JSON.stringify(legacyRun(2)));
  other.config.model = "Qwen/Qwen2.5-0.5B-Instruct";
  assert.equal(schema.upgradeLegacy(other).id, "gsm8k-qwen2.5-0.5b-instruct-seed2");
});

test("upgrade leaves the legacy object alone", () => {
  const old = legacyRun(4);
  const before = JSON.stringify(old);
  schema.upgradeLegacy(old);
  schema.load(old);
  assert.equal(JSON.stringify(old), before);
});

test("upgrade says which legacy field is missing", () => {
  const old = JSON.parse(JSON.stringify(legacyRun(1)));
  delete old.config.n_eval;
  assert.throws(() => schema.upgradeLegacy(old), (err) => err instanceof schema.RunError && /n_eval/.test(err.message));
  assert.deepEqual(schema.validate(old), ["toolkit run file cannot be upgraded: toolkit run file has no config.n_eval"]);
});

// load

test("load upgrades a legacy file", () => {
  const run = schema.load(legacyRun(5));
  assert.equal(run.id, "gsm8k-qwen2.5-1.5b-seed5");
  assert.equal(run.labels.cf7e8a98a5cc.E1.current.length, 200);
  assert.deepEqual(schema.validate(run), []);
});

test("load reads JSON text", () => {
  const run = schema.load(JSON.stringify(filled()));
  assert.equal(run.id, "small");
});

test("load turns label arrays into strings", () => {
  const raw = filled();
  raw.labels.p0.E1 = { current: [1, 0, 1, 1], rerun: "1011" };
  const run = schema.load(raw);
  assert.deepEqual(run.labels.p0.E1, { current: "1011", rerun: "1011" });
  assert.deepEqual(raw.labels.p0.E1.current, [1, 0, 1, 1]);
});

test("load writes schedule rounds as plain integers", () => {
  const raw = filled();
  raw.schedule = { "000": "E1", "01": "E4" };
  assert.deepEqual(schema.load(raw).schedule, { 0: "E1", 1: "E4" });
});

test("load is idempotent and does not copy label strings", () => {
  const once = paperRun(1);
  assert.equal(schema.load(once), once);
  const raw = filled();
  const run = schema.load(raw);
  assert.notEqual(run, raw);
  assert.equal(run.labels.p0.E1.current, raw.labels.p0.E1.current);
  assert.equal(run.prompts, raw.prompts);
});

test("load reports text that is not JSON", () => {
  assert.throws(() => schema.load("{not json", "broken.json"),
    (err) => err instanceof schema.RunError && /^broken\.json: not valid JSON/.test(err.message));
});

test("load reports JSON that is not a run log", () => {
  assert.throws(() => schema.load({ hello: "world" }), (err) => err instanceof schema.RunError && /schema/.test(err.message));
  assert.throws(() => schema.load([1, 2, 3]), (err) => err instanceof schema.RunError && /JSON object/.test(err.message));
  assert.throws(() => schema.load(null), schema.RunError);
});

test("load names a newer format", () => {
  const raw = filled();
  raw.schema = "driftaudit.run/v2";
  assert.throws(() => schema.load(raw), /schema is "driftaudit\.run\/v2", but this version of driftaudit reads "driftaudit\.run\/v1"/);
});

test("load error lists the problems and keeps them", () => {
  const raw = filled();
  raw.labels.p0.E1.current = "10";
  raw.schedule["3"] = "E9";
  assert.throws(() => schema.load(raw, "my-run.json"), (err) => {
    assert.ok(err instanceof schema.RunError && err instanceof Error);
    assert.equal(err.message, "my-run.json is not a valid run log:\n" +
      "  - schedule sends round 3 to environment 'E9', which environments does not define\n" +
      "  - labels.p0.E1.current has 2 labels, expected 4 (task.n_items)");
    assert.equal(err.problems.length, 2);
    return true;
  });
});

test("a long list of problems is cut after five", () => {
  const raw = filled();
  for (const key of ["schema", "id", "source", "environments", "schedule", "snapshots", "candidates"]) delete raw[key];
  assert.throws(() => schema.load(raw), (err) => {
    assert.ok(err.problems.length > 5);
    assert.equal(err.message.split("\n  - ").length, 6);
    assert.ok(err.message.endsWith(`\n  (and ${err.problems.length - 5} more)`));
    assert.ok(err.message.startsWith("this object is not a valid run log:"));
    return true;
  });
});

// validate

test("validate passes the paper runs, loaded or as the toolkit wrote them", () => {
  for (const seed of SEEDS) {
    assert.deepEqual(schema.validate(paperRun(seed)), []);
    assert.deepEqual(schema.validate(legacyRun(seed)), []);
  }
});

test("validate names each kind of problem", () => {
  expectProblem((r) => delete r.schema, "schema");
  expectProblem((r) => { r.id = ""; }, "id must be a non-empty string");
  expectProblem((r) => { r.source = "guessed"; }, "source must be");
  expectProblem((r) => delete r.task.n_items, "task.n_items");
  expectProblem((r) => { r.task.n_items = true; }, "task.n_items");
  expectProblem((r) => { r.environments = {}; }, "environments must define at least one environment");
  expectProblem((r) => delete r.environments.E1.fingerprint, "environments.E1.fingerprint must be a string");
  expectProblem((r) => { r.schedule = {}; }, "schedule must map");
  expectProblem((r) => { r.schedule.x = "E1"; }, "schedule round 'x'");
  expectProblem((r) => { r.schedule["2"] = "E9"; }, "environment 'E9'");
  expectProblem((r) => { r.snapshots[1].round = 5; }, "snapshots[1] must be the snapshot of round 1");
  expectProblem((r) => { r.snapshots[0].prompt = "zz"; }, "snapshots[0] names prompt 'zz'");
  expectProblem((r) => { r.candidates[0].prompt = "zz"; }, "candidate 'C1' names prompt 'zz'");
  expectProblem((r) => { r.candidates[1].round = 7; }, "candidate 'C2' is in round 7, but snapshots cover rounds 0 to 1");
  expectProblem((r) => { r.candidates[1].id = "C1"; }, "candidate id 'C1' is used more than once");
  expectProblem((r) => { r.candidates[0].accepted = "yes"; }, "accepted must be true or false");
  expectProblem((r) => { r.candidates[0].reference = { prompt: "p0", env: "E1", pass: "later" }; }, "reference pass must be");
  expectProblem((r) => { r.candidates[0].reference = { prompt: "p0" }; }, "reference must name a prompt");
  expectProblem((r) => { r.labels.zz = {}; }, "labels has prompt 'zz'");
  expectProblem((r) => { r.labels.p0.E9 = {}; }, "labels.p0 has environment 'E9'");
  expectProblem((r) => { r.labels.p0.E1.extra = "1010"; }, "has pass 'extra'");
  expectProblem((r) => { r.labels.p0.E1.current = "101"; }, "has 3 labels, expected 4");
  expectProblem((r) => { r.labels.p0.E1.current = "10a1"; }, "must contain only 0 and 1");
  expectProblem((r) => { r.labels.p0.E1.current = [1, 0, "1", 0]; }, "must contain only 0 and 1");
  expectProblem((r) => { r.cost.n_dev = -1; }, "cost.n_dev must be a non-negative integer");
  expectProblem((r) => r.candidates.reverse(), "is out of order");
});

test("several candidates may share a round", () => {
  const raw = filled();
  raw.prompts.p3 = "text of p3";
  raw.candidates.push({ id: "C3", round: 1, prompt: "p3", parent: "p1", accepted: false });
  assert.deepEqual(schema.validate(raw), []);
});

test("validate of something that is not an object", () => {
  assert.deepEqual(schema.validate("nope"), ["a run log is a JSON object"]);
  assert.deepEqual(schema.validate(null), ["a run log is a JSON object"]);
});

test("ids from a run log never reach an object's prototype", () => {
  const raw = JSON.parse(JSON.stringify(filled()).replace(/"p2"/g, "\"__proto__\""));
  const run = schema.load(raw);
  assert.equal(schema.labels(run, "__proto__", "E1"), "0101");
  assert.equal(Object.getPrototypeOf(run.labels), Object.prototype);
  assert.equal({}.E1, undefined);
});

// labels accessor

test("labels returns null for anything absent", () => {
  const run = schema.load(filled());
  assert.equal(schema.labels(run, "p0", "E1"), "1000");
  assert.equal(schema.labels(run, "p0", "E1", "rerun"), "1000");
  assert.equal(schema.labels(run, "p0", "E4"), null);
  assert.equal(schema.labels(run, "zz", "E1"), null);
  assert.equal(schema.labels(run, "p0", "E1", "later"), null);
  assert.equal(schema.labels(run, "constructor", "E1"), null);
  assert.equal(schema.labels(run, "p0", "toString"), null);
});
