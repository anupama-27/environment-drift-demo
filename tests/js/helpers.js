"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");

// Load the engine as index.html does: the four files in order, each attaching to the global DA.
for (const name of ["stats", "schema", "scorers", "engine"]) {
  require(path.join(ROOT, "assets", "js", "engine", `${name}.js`));
}
const DA = globalThis.DA;

const SEEDS = [1, 2, 3, 4, 5];

function readJson(...parts) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, ...parts), "utf8"));
}

function exists(...parts) {
  return fs.existsSync(path.join(ROOT, ...parts));
}

const legacyCache = new Map();

// A saved paper run exactly as the toolkit wrote it.
function legacyRun(seed) {
  if (!legacyCache.has(seed)) {
    legacyCache.set(seed, readJson("toolkit", "runs", `run_seed${seed}_hf_Qwen2.5-1.5B-Instruct_n200_r11.json`));
  }
  return legacyCache.get(seed);
}

// The same run upgraded to v1. load() returns one object per input, so repeated calls share it.
const paperCache = new Map();
function paperRun(seed) {
  if (!paperCache.has(seed)) paperCache.set(seed, DA.schema.load(legacyRun(seed)));
  return paperCache.get(seed);
}

function paperRuns() {
  return SEEDS.map(paperRun);
}

function close(a, b, tol = 1e-12) {
  return typeof a === "number" && typeof b === "number" && Math.abs(a - b) <= tol;
}

// Whether saved is x rounded to the given number of decimals, which is how the replay files
// and the paper's tables hold their values. Half a unit of the last place, so ties pass either way.
function roundsTo(x, saved, digits = 4) {
  return typeof x === "number" && typeof saved === "number" && Math.abs(x - saved) <= 0.5 * 10 ** -digits + 1e-12;
}

function show(v) {
  const text = v === undefined ? "undefined" : JSON.stringify(v);
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

// Where two JSON values differ: numbers within tol, everything else exactly, key sets equal.
// A number against null is a difference, and so is an undefined value against anything.
function differences(actual, expected, tol = 1e-9, at = "$", out = []) {
  if (out.length >= 25) return out;
  if (typeof actual === "number" && typeof expected === "number") {
    if (!(Math.abs(actual - expected) <= tol)) out.push(`${at}: ${actual} is not ${expected}`);
  } else if (actual === null || expected === null || typeof actual !== "object" || typeof expected !== "object") {
    if (actual !== expected) out.push(`${at}: ${show(actual)} is not ${show(expected)}`);
  } else if (Array.isArray(actual) !== Array.isArray(expected)) {
    out.push(`${at}: ${show(actual)} is not ${show(expected)}`);
  } else if (Array.isArray(expected)) {
    if (actual.length !== expected.length) {
      out.push(`${at}: ${actual.length} entries, expected ${expected.length}`);
    } else {
      expected.forEach((e, i) => differences(actual[i], e, tol, `${at}[${i}]`, out));
    }
  } else {
    const have = Object.keys(actual), want = Object.keys(expected);
    for (const k of want) if (!have.includes(k)) out.push(`${at}.${k}: missing`);
    for (const k of have) if (!want.includes(k)) out.push(`${at}.${k}: not expected`);
    for (const k of want) if (have.includes(k)) differences(actual[k], expected[k], tol, `${at}.${k}`, out);
  }
  return out;
}

// A v1 run from plain label arrays: labels[prompt][env] is the stored pass. reruns["prompt/env"]
// overrides the rerun pass, which otherwise repeats the stored one; null leaves it out of the bank.
function smallRun({ labels, schedule, snapshots, candidates, nItems, reruns = {}, environments, nDev = 0, id = "small", seed = 1 }) {
  const model = "test-model";
  const envs = environments || {
    E1: env("Unchanged", "greedy-0.0", "v1", model),
    E2: env("Decoding", "sample-0.2", "v1", model),
    E3: env("Extraction", "greedy-0.0", "v2", model),
    E4: env("Combined", "sample-0.2", "v2", model),
  };
  const run = {
    schema: "driftaudit.run/v1", id, source: "synthetic", seed,
    task: { name: "toy", n_items: nItems, n_dev: nDev }, model: { id: model },
    environments: envs, schedule, prompts: {}, snapshots: snapshots.map((prompt, round) => ({ round, prompt })),
    candidates: candidates.map((c) => ({ ...c })), labels: {}, cost: { n_dev: nDev, proposal_calls: 1 }, meta: {},
  };
  for (const [prompt, perEnv] of Object.entries(labels)) {
    run.prompts[prompt] = `text of ${prompt}`;
    run.labels[prompt] = {};
    for (const [envId, stored] of Object.entries(perEnv)) {
      const entry = { current: stored };
      const key = `${prompt}/${envId}`;
      const rerun = key in reruns ? reruns[key] : stored;
      if (rerun !== null) entry.rerun = rerun;
      run.labels[prompt][envId] = entry;
    }
  }
  // A prompt the loop held or proposed belongs in the log even when nothing was measured for it.
  for (const h of [...snapshots, ...candidates.flatMap((c) => [c.prompt, c.parent])]) {
    if (h !== undefined && !(h in run.prompts)) run.prompts[h] = `text of ${h}`;
  }
  return DA.schema.load(run);
}

// The value of one field in every decision of a policy block.
function column(block, key) {
  return block.decisions.map((d) => d[key]);
}

// A deep copy of a run with some labels removed, as a plain object that load() checks again.
function without(run, ...keys) {
  const copy = JSON.parse(JSON.stringify(run));
  for (const [prompt, envId, pass] of keys) delete copy.labels[prompt][envId][pass];
  return copy;
}

function env(name, decoding, scorer, model) {
  return { name, decoding, scorer, fingerprint: `model=${model};decode=${decoding};extract=${scorer}`, detail: {} };
}

module.exports = {
  DA, ROOT, SEEDS, readJson, exists, legacyRun, paperRun, paperRuns, close, roundsTo, differences, smallRun, env,
  column, without,
};
