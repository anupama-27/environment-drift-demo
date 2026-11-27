"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { DA, ROOT, differences } = require("./helpers.js");

// The Python engine writes tests/golden/manifest.json (python -m driftaudit._golden): every case
// names its run or runs, the options and the file holding the result. This replays whatever the
// manifest lists through the JavaScript engine and requires the same result: numbers within
// 1e-9, everything else exactly, the same keys, null where Python has None.

const GOLDEN = path.join(ROOT, "tests", "golden");
const MANIFEST = path.join(GOLDEN, "manifest.json");
const TOLERANCE = 1e-9;

const files = new Map();

function golden(rel) {
  if (!files.has(rel)) files.set(rel, JSON.parse(fs.readFileSync(path.resolve(GOLDEN, rel), "utf8")));
  return files.get(rel);
}

// Runs and results are named by a path relative to tests/golden; an inline object is taken as it is.
function resolve(value) {
  return typeof value === "string" ? golden(value) : value;
}

const REPLAY = {
  audit: (c) => DA.engine.audit(resolve(c.run), c.options || {}),
  study: (c) => DA.engine.study(c.runs.map(resolve), c.options || {}),
};

if (!fs.existsSync(MANIFEST)) {
  test("golden parity with the Python engine", { skip: "tests/golden/manifest.json has not been generated" }, () => {});
} else {
  const cases = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));

  test("the golden manifest lists audit and study cases", () => {
    assert.ok(Array.isArray(cases) && cases.length > 0);
    const names = cases.map((c) => c.name);
    assert.equal(new Set(names).size, names.length, "case names are unique");
    assert.ok(cases.some((c) => c.kind === "audit") && cases.some((c) => c.kind === "study"));
  });

  for (const c of cases) {
    const replay = REPLAY[c.kind];
    if (!replay) {
      test(`golden ${c.name}`, { skip: `no JavaScript replay for kind "${c.kind}"` }, () => {});
      continue;
    }
    test(`golden ${c.kind} ${c.name}`, () => {
      const expected = resolve(c.result);
      const actual = replay(c);
      const found = differences(actual, expected, TOLERANCE);
      assert.deepEqual(found, [], `${found.length} difference(s) from ${c.result}`);
      // What the workbench exports has to be JSON: no NaN, no Infinity, nothing undefined.
      assert.deepEqual(differences(JSON.parse(JSON.stringify(actual)), expected, TOLERANCE), []);
    });
  }
}
