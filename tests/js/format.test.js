"use strict";

// The number formatters of the web pages print what Python's format() prints, ties included.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

require(path.resolve(__dirname, "..", "..", "assets", "js", "ui.js"));
const fmt = globalThis.DA.ui.fmt;
const M = "−";

test("exact ties round half to even", () => {
  assert.equal(fmt.pp(-0.125), M + "0.12");
  assert.equal(fmt.pp(0.125), "+0.12");
  assert.equal(fmt.pp(0.375), "+0.38");
  assert.equal(fmt.num(0.625, 2), "0.62");
  assert.equal(fmt.num(2.5, 0), "2");
  assert.equal(fmt.num(3.5, 0), "4");
  assert.equal(fmt.int(2.5), "2");
  assert.equal(fmt.int(-1234567.5), M + "1,234,568");
});

test("values that only look like ties follow their binary value", () => {
  assert.equal(fmt.num(2.675, 2), "2.67");
  assert.equal(fmt.num(1.005, 2), "1.00");
  assert.equal(fmt.pct(0.7085), "70.9%");
});

test("ordinary values are unchanged", () => {
  assert.equal(fmt.pp(1.3125), "+1.31");
  assert.equal(fmt.pp(-0.5875), M + "0.59");
  assert.equal(fmt.ppOf(0.015), "+1.50");
  assert.equal(fmt.pct(0.708), "70.8%");
  assert.equal(fmt.int(4411), "4,411");
  assert.equal(fmt.pp(-0.001), "0.00");
  assert.equal(fmt.interval(0.65, 1.98), "+0.65 to +1.98");
});
