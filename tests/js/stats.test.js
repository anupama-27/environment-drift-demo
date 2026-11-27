"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { DA, close } = require("./helpers.js");

const stats = DA.stats;

// Reference values below come from src/driftaudit/stats.py, which uses exact integer
// arithmetic for Fisher's test and CPython's math.lgamma for the t test.

test("mean and sample sd", () => {
  const xs = [0.69, 0.71, 0.73, 0.725, 0.685];
  assert.ok(close(stats.mean(xs), 0.708, 1e-15));
  assert.ok(close(stats.sd(xs), 0.020186629238186336, 1e-15));
});

test("sd of one value is zero", () => {
  assert.equal(stats.sd([0.7]), 0);
});

test("nothing to average gives null, not NaN", () => {
  assert.equal(stats.mean([]), null);
  assert.equal(stats.sd([]), null);
  assert.deepEqual(stats.tInterval([]), { mean: null, lo: null, hi: null });
});

test("mean adds left to right", () => {
  // Added one at a time the two small terms are absorbed, as in the Python engine.
  assert.equal(stats.mean([1e16, 1.0, 1.0]), 1e16 / 3);
});

test("t95 keeps the paper's table and extends it to thirty", () => {
  const table = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.16, 2.145,
    2.131, 2.12, 2.11, 2.101, 2.093, 2.086, 2.08, 2.074, 2.069, 2.064, 2.06, 2.056, 2.052, 2.048, 2.045, 2.042];
  table.forEach((value, i) => assert.equal(stats.t95(i + 1), value));
  assert.equal(stats.t95(31), 1.96);
  assert.equal(stats.t95(1000), 1.96);
});

test("t95 needs at least one degree of freedom", () => {
  assert.throws(() => stats.t95(0), RangeError);
});

test("t interval is the paper's interval", () => {
  // Extraction row of the probe at age 3: +1.31 [+0.65, +1.98].
  const t = stats.tInterval([1.75, 0.875, 0.625, 1.5, 1.8125]);
  assert.ok(close(t.mean, 1.3125));
  assert.ok(close(t.lo, 0.6495574308433649));
  assert.ok(close(t.hi, 1.975442569156635));
  assert.deepEqual(Object.keys(t), ["mean", "lo", "hi"]);
});

test("t interval of one value has no bounds", () => {
  assert.deepEqual(stats.tInterval([0.5]), { mean: 0.5, lo: null, hi: null });
});

const FISHER = [
  [4, 55, 13, 55, 0.032564974949330444],
  [4, 55, 14, 55, 0.01850247117470074],
  [4, 55, 8, 55, 0.35966201288947147],
  [0, 5, 5, 5, 0.007936507936507936],
  [3, 3, 0, 4, 0.02857142857142857],
  [0, 10, 0, 10, 1.0],
  [7, 20, 12, 31, 0.9999999999999998],
  [55, 55, 0, 55, 2.029895931132092e-32],
  [1, 1, 1, 1, 1.0],
  [17, 200, 31, 180, 0.01300846238304785],
  [0, 0, 0, 0, 1.0],
  [5, 20, 5, 20, 0.9999999999999999],
];

test("fisher matches exact arithmetic", () => {
  for (const [a, n1, b, n2, p] of FISHER) {
    assert.ok(close(stats.fisher(a, n1, b, n2), p, 1e-12), `fisher(${a}, ${n1}, ${b}, ${n2})`);
  }
});

test("fisher reproduces the policy tests in the paper", () => {
  assert.equal(stats.fisher(4, 55, 13, 55).toFixed(3), "0.033");
  assert.equal(stats.fisher(4, 55, 14, 55).toFixed(3), "0.019");
  assert.equal(stats.fisher(4, 55, 8, 55).toFixed(3), "0.360");
});

test("fisher handles tables whose binomial coefficients overflow a double", () => {
  assert.ok(close(stats.fisher(1500, 3000, 1400, 3000), 0.01053402783206603, 1e-12));
  assert.ok(close(stats.fisher(2, 40000, 9, 35000), 0.03006433238560121, 1e-12));
});

test("fisher does not depend on which group comes first", () => {
  assert.ok(close(stats.fisher(4, 55, 13, 55), stats.fisher(13, 55, 4, 55), 1e-15));
});

test("fisher never exceeds one", () => {
  for (let a = 0; a <= 12; a++) {
    for (let b = 0; b <= 12; b++) {
      const p = stats.fisher(a, 12, b, 12);
      assert.ok(p >= 0 && p <= 1, `fisher(${a}, 12, ${b}, 12) = ${p}`);
    }
  }
  assert.equal(stats.fisher(0, 10, 0, 10), 1);
});

test("fisher of counts that cannot occur", () => {
  assert.equal(stats.fisher(6, 5, 1, 5), 0);
  assert.equal(stats.fisher(-1, 5, 1, 5), null);
  assert.equal(stats.fisher(1.5, 5, 1, 5), null);
});

const T_TEST = [
  [[0.3, 0.9, 0.5, 0.7, 0.55], 0.004204602535707892],
  [[-2.25, 1.75, 0.375, -1.625, -1.1875], 0.46473529610169073],
  [[1.0, 1.1], 0.03029234437673632],
  [[0.2, -0.1, 0.05], 0.6220355269907729],
  [[5.0, 4.9, 5.2, 5.1, 4.8, 5.05, 4.95], 6.739380221233819e-11],
  [[0.001, -0.002, 0.004, 0.001], 0.47402138849506403],
];

test("t test matches the paper's script", () => {
  for (const [xs, p] of T_TEST) assert.ok(close(stats.tTestP(xs), p, 1e-12), JSON.stringify(xs));
});

test("t test edges", () => {
  assert.equal(stats.tTestP([0.4]), null);
  assert.equal(stats.tTestP([0, 0, 0]), 1);
  assert.equal(stats.tTestP([2, 2, 2]), 0);
  assert.ok(close(stats.tTestP([1, -1]), 1));
});

test("lgamma and the incomplete beta follow CPython", () => {
  const lgamma = [[0.5, 0.5723649429247004], [1.5, -0.12078223763524543], [2.5, 0.2846828704729196],
    [4.999, 3.1765478233491224], [5.0, 3.178053830347945], [10.0, 12.801827480081467], [100.5, 361.4355404677776]];
  for (const [x, y] of lgamma) assert.ok(close(stats.lgamma(x), y, 1e-13), `lgamma(${x})`);
  assert.equal(stats.lgamma(1), 0);
  assert.equal(stats.lgamma(2), 0);
  assert.ok(close(stats.ibeta(2.0, 0.5, 0.3), 0.03784096948581308, 1e-14));
  assert.ok(close(stats.ibeta(2.0, 0.5, 0.9), 0.5414697392755852, 1e-14));
  assert.ok(close(stats.ibeta(7.5, 0.5, 0.99), 0.7025618881551348, 1e-14));
  assert.equal(stats.ibeta(2, 0.5, 0), 0);
  assert.equal(stats.ibeta(2, 0.5, 1), 1);
});
