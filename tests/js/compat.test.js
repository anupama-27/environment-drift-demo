"use strict";

// DA.engine.compatibility and the study's source, as in tests/python/test_engine.py.
const test = require("node:test");
const assert = require("node:assert/strict");

const { DA, paperRun } = require("./helpers.js");

test("compatibility names the first difference of each run", () => {
  const first = paperRun(1), second = paperRun(2);
  assert.deepEqual(DA.engine.compatibility([first, second]), []);
  const short = Object.assign({}, second, { snapshots: second.snapshots.slice(0, 5), candidates: second.candidates.slice(0, 5) });
  const otherTask = Object.assign({}, second, { id: "other", task: Object.assign({}, second.task, { name: "Other" }) });
  assert.deepEqual(DA.engine.compatibility([first, short, otherTask], ["a", "b", "c"]), [
    "b: number of rounds is 5, where a has 11", "c: task is Other, where a has GSM8K"]);
  const envs = {};
  Object.keys(second.environments).forEach((k) => { envs[k] = Object.assign({}, second.environments[k]); });
  envs.E2.fingerprint = "something else";
  assert.deepEqual(DA.engine.compatibility([first, Object.assign({}, second, { environments: envs })], ["a", "b"]), [
    "b: fingerprint of E2 is something else, where a has " + first.environments.E2.fingerprint]);
  assert.deepEqual(DA.engine.compatibility([first, first], ["a", "b"]), ["b: run id gsm8k-qwen2.5-1.5b-seed1 is also the id of a"]);
});

test("compatibility of no runs or one run is empty", () => {
  assert.deepEqual(DA.engine.compatibility([]), []);
  assert.deepEqual(DA.engine.compatibility([paperRun(3)]), []);
});

test("a study names its source", () => {
  const measured = DA.engine.study([paperRun(1), paperRun(2)], { policies: ["frozen"] });
  assert.equal(measured.source, "measured");
  assert.deepEqual(measured.runs.map((r) => r.source), ["measured", "measured"]);
  const fake = Object.assign({}, paperRun(2), { id: "fake", source: "synthetic" });
  assert.equal(DA.engine.study([paperRun(1), fake], { policies: ["frozen"] }).source, "mixed");
  assert.equal(DA.engine.studySource(["synthetic", "synthetic"]), "synthetic");
});
