"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { DA, readJson } = require("./helpers.js");

const { strict, lenient, lenientRule, isCorrect, goldAnswer, normalizeText, get } = DA.scorers;

// Each row: text, what the strict scorer reads, what the lenient scorer reads, the lenient rule.
// The expected values were taken from src/driftaudit/scoring.py on the same text.
function check(rows) {
  for (const [text, strictValue, lenientValue, rule] of rows) {
    const label = JSON.stringify(text);
    assert.equal(strict(text), strictValue, `strict ${label}`);
    assert.equal(lenient(text), lenientValue, `lenient ${label}`);
    assert.equal(lenientRule(text), rule, `rule ${label}`);
  }
}

// Real model outputs from the paper runs with the answer each extractor read.
const cases = readJson("tests", "golden", "scorer_cases.json");

test("strict reads what the paper extractor read", () => {
  for (const c of cases) {
    assert.equal(strict(c.text), c.strict);
    assert.equal(isCorrect(strict(c.text), c.gold), c.strict_correct);
  }
});

test("lenient reads what the paper extractor read", () => {
  for (const c of cases) {
    assert.equal(lenient(c.text), c.lenient);
    assert.equal(isCorrect(lenient(c.text), c.gold), c.lenient_correct);
  }
});

test("lenientRule names the rule that fired", () => {
  const seen = new Set();
  for (const c of cases) {
    assert.equal(lenientRule(c.text), c.rule);
    seen.add(c.rule);
  }
  assert.deepEqual([...seen].sort(), ["answer_is", "bold", "boxed_loose", "last_number", "v1"]);
});

test("lenient never loses an answer strict read", () => {
  for (const c of cases) {
    const value = strict(c.text);
    if (value !== null) assert.equal(lenient(c.text), value);
  }
});

// Ported from toolkit/tests/test_extract.py.

test("strict reads a plain number in the box or after ####", () => {
  assert.equal(strict("so \\(\\boxed{18}\\) dollars"), 18);
  assert.equal(strict("work\n#### 42"), 42);
});

test("strict rejects formats lenient accepts", () => {
  const rows = [["\\boxed{70,000}", 70000], ["$\\boxed{\\$15}$", 15], ["\\boxed{540 \\text{ meters}}", 540],
    ["a total of **540** meters", 540], ["The answer is 1,200.", 1200], ["= 12 years", 12]];
  for (const [text, value] of rows) {
    assert.equal(strict(text), null, text);
    assert.equal(lenient(text), value, text);
  }
});

test("gold answers end with ####", () => {
  assert.equal(goldAnswer("blah\n#### 1,234"), 1234);
  assert.equal(goldAnswer("72"), 72);
  assert.equal(goldAnswer("not a number"), null);
});

test("lenient rules are tried in the extractor's order", () => {
  check([
    ["\\boxed{18}", 18, 18, "v1"],
    ["\\boxed{70,000}", null, 70000, "boxed_loose"],
    ["#### 1,234", null, 1234, "hashes_loose"],
    ["a total of **540** meters", null, 540, "bold"],
    ["The answer is 1,200.", null, 1200, "answer_is"],
    ["= 12 years", null, 12, "last_number"],
    ["no number at all", null, null, "none"],
    ["", null, null, "none"],
    // A box the loose rule cannot read falls through to the later rules.
    ["\\boxed{x} so the answer is 4", null, 4, "answer_is"],
    ["\\boxed{7}\n#### 8", 7, 7, "v1"],
    ["#### 18\n\\boxed{x}", 18, 18, "v1"],
  ]);
});

test("the last box wins, with one level of nested braces", () => {
  check([
    ["\\boxed{nineteen} \\boxed{18}", 18, 18, "v1"],
    ["\\boxed{18} \\boxed{nineteen}", null, 18, "last_number"],
    ["\\boxed{12} then \\boxed{1{2}3}", null, 1, "boxed_loose"],
    ["\\boxed{\\frac{3}{4}}", null, 3, "boxed_loose"],
    ["\\boxed{\\text{about } 15\\%}", null, 15, "boxed_loose"],
    ["\\boxed{\\$1{,}200}", null, 1, "boxed_loose"],
    ["\\boxed{{{1}}} 2", null, 2, "last_number"],
    ["\\boxed{5", null, 5, "last_number"],
    ["\\boxed{}", null, null, "none"],
  ]);
});

test("the box must hold a plain number for strict (re.fullmatch)", () => {
  check([
    ["\\boxed{ 42 }", 42, 42, "v1"],
    ["\\boxed{-0.5}", -0.5, -0.5, "v1"],
    ["\\boxed{1.}", null, 1, "boxed_loose"],
    ["\\boxed{.5}", null, 5, "boxed_loose"],
    ["\\boxed{+3}", null, 3, "boxed_loose"],
    ["\\boxed{1e3}", null, 1, "boxed_loose"],
  ]);
});

test("#### ends a line as $ does under re.M: before \\n only", () => {
  check([
    ["x\n#### 7 \n", 7, 7, "v1"],
    ["#### 42 \n\nmore text", 42, 42, "v1"],
    ["#### 42\r\nmore", 42, 42, "v1"],
    ["line\n####\n9\nend", 9, 9, "v1"],
    ["#### 42 dollars\n#### 7", 7, 7, "v1"],
    ["####5", 5, 5, "v1"],
    // JavaScript's own $ with the m flag would also stop before these two.
    ["#### 42\rmore", null, 42, "hashes_loose"],
    ["#### 42\u2028more", null, 42, "hashes_loose"],
    ["#### 3 ####", null, 3, "hashes_loose"],
  ]);
});

test("whitespace is Python's \\s, not JavaScript's", () => {
  check([
    // U+001C is whitespace to Python and is stripped from the box; U+FEFF is not.
    ["\\boxed{\u001c12\u001c}", 12, 12, "v1"],
    ["\\boxed{12\u00a0}", 12, 12, "v1"],
    ["\\boxed{\ufeff12}", null, 12, "boxed_loose"],
    ["#### 42\u000b", 42, 42, "v1"],
    ["answer is\u00a09", null, 9, "answer_is"],
    ["answer\u00a0is 9", null, 9, "last_number"],
  ]);
});

test("digits are any Unicode decimal digit, as \\d and float() take them", () => {
  check([
    ["\\boxed{\u0661\u0662}", 12, 12, "v1"],
    ["\\boxed{\uff11\uff12.\uff15}", 12.5, 12.5, "v1"],
    ["the total is \u0663\u0664 apples", null, 34, "last_number"],
    ["x\ud835\udfd7y", null, 9, "last_number"],
  ]);
});

test("loose numbers are cleaned the way _to_float cleans them", () => {
  check([
    ["#### $ 15", null, 15, "hashes_loose"],
    ["#### - 7", null, -7, "hashes_loose"],
    ["#### 1,2,3,", null, 123, "hashes_loose"],
    ["#### 1,200.50.", null, 1200.5, "hashes_loose"],
    ["The answer is: -$ 5.50", null, -5.5, "answer_is"],
    ["**$ 1,000**", null, 1000, "bold"],
    ["1,000,000", null, 1000000, "last_number"],
    // Only spaces are removed. A tab after the sign leaves a string float() refuses.
    ["#### $\t7", null, 7, "hashes_loose"],
    ["#### -$\t7", null, null, "none"],
    ["-\t3", null, null, "none"],
    // A number float() refuses is skipped and the one before it is used.
    ["1\u001c2", null, 1, "last_number"],
  ]);
});

test("the last number is the last match of a left-to-right scan", () => {
  check([
    ["first 3 then 4.", null, 4, "last_number"],
    ["10-5", null, -5, "last_number"],
    ["0.1.2", null, 2, "last_number"],
    ["costs $-5 or -$5", null, -5, "last_number"],
    ["999999999999999999999", null, 1e21, "last_number"],
    ["0.1 0.2 0.30000000000000004", null, 0.30000000000000004, "last_number"],
    ["$", null, null, "none"],
  ]);
  assert.equal(lenient("1".repeat(400)), Infinity);
});

test("bold answers allow twenty characters after the number", () => {
  check([
    ["**$1,200 total**", null, 1200, "bold"],
    ["**12** and **x 13 y**", null, 12, "bold"],
    ["**\n10\n**", null, 10, "bold"],
    ["** 15 units of measurement that go on far too long **", null, 15, "last_number"],
    ["**9*", null, 9, "last_number"],
  ]);
});

test("'answer is' ignores case the way re.I does", () => {
  check([
    ["ANSWER IS 9", null, 9, "answer_is"],
    ["Answer Is:\n\t8", null, 8, "answer_is"],
    ["the answer is: $1,200.00.", null, 1200, "answer_is"],
    // Long s and both Turkish i's fold onto the ASCII letters in Python.
    ["an\u017fwer i\u017f 5", null, 5, "answer_is"],
    ["answer \u0131s 6", null, 6, "answer_is"],
    ["ANSWER \u0130S 7", null, 7, "answer_is"],
    ["answer  is 9", null, 9, "last_number"],
    ["answer is -", null, null, "none"],
  ]);
});

test("something that is not text reads as no answer", () => {
  assert.equal(strict(null), null);
  assert.equal(lenient(undefined), null);
  assert.equal(lenientRule(null), "none");
});

test("numeric match uses the paper's tolerance", () => {
  assert.equal(isCorrect(18.0, 18.0000001), true);
  assert.equal(isCorrect(18.0, 18.00001), false);
  assert.equal(isCorrect(null, 18.0), false);
  assert.equal(isCorrect(18.0, null), false);
  assert.equal(isCorrect(undefined, 18.0), false);
});

test("numeric scorers take the gold answer as text too", () => {
  assert.equal(isCorrect(1234.0, "1,234"), true);
  assert.equal(isCorrect(72.0, "blah\n#### 72"), true);
  assert.equal(isCorrect(72.0, "not a number"), false);
});

test("the paper's names are aliases", () => {
  assert.equal(get("v1"), get("strict"));
  assert.equal(get("v2"), get("lenient"));
  assert.deepEqual([get("v1").id, get("v2").id], ["strict", "lenient"]);
  assert.deepEqual(["strict", "lenient", "exact", "exact-normalized"].map((id) => get(id).name),
    ["strict numeric", "lenient numeric", "exact match", "normalized exact match"]);
  for (const id of ["strict", "lenient", "exact", "exact-normalized"]) assert.equal(get(id).version, "1");
});

test("scorer objects read and compare like the functions", () => {
  assert.equal(get("strict").extract("\\boxed{18}"), 18);
  assert.equal(get("lenient").extract("\\boxed{70,000}"), 70000);
  assert.equal(get("strict").correct(18, 18), true);
  assert.equal(get("lenient").correct(70000, "70,000"), true);
});

test("an unknown scorer lists the known ones", () => {
  assert.throws(() => get("fuzzy"), /unknown scorer "fuzzy"; known scorers: strict, lenient, exact, exact-normalized/);
  assert.throws(() => get("constructor"), /unknown scorer/);
  assert.throws(() => get(undefined), /unknown scorer/);
});

test("exact compares stripped text", () => {
  const exact = get("exact");
  assert.equal(exact.extract("  Paris \n"), "Paris");
  assert.equal(exact.correct(exact.extract("  Paris \n"), "Paris"), true);
  assert.equal(exact.correct(exact.extract("paris"), "Paris"), false);
  assert.equal(exact.extract("   "), null);
  assert.equal(exact.correct(null, "Paris"), false);
  assert.equal(exact.correct("42", 42), true);
});

test("exact-normalized ignores case, spacing, punctuation and a leading article", () => {
  const norm = get("exact-normalized");
  assert.equal(norm.extract("  The  Eiffel   Tower. "), "eiffel tower");
  assert.equal(norm.correct(norm.extract("the Eiffel Tower!"), "Eiffel tower"), true);
  assert.equal(norm.correct(norm.extract("An apple"), "apple"), true);
  assert.equal(norm.correct(norm.extract("Tower of the Eiffel"), "Tower of Eiffel"), false);
  assert.equal(norm.extract("..."), null);
  assert.equal(norm.correct(null, "apple"), false);
});

test("normalizeText folds case as str.casefold does", () => {
  assert.equal(get("exact-normalized").correct(normalizeText("STRASSE"), "stra\u00dfe"), true);
  assert.equal(normalizeText("Stra\u00dfe"), "strasse");
  assert.equal(normalizeText("\u1e9e"), "ss");
  assert.equal(normalizeText("\u039f\u0394\u039f\u03a3"), "\u03bf\u03b4\u03bf\u03c3");
  assert.equal(normalizeText("\u03c2"), "\u03c3");
  assert.equal(normalizeText("\ufb01sh"), "fish");
  // Dotless i stays itself, and Cherokee folds to its capitals.
  assert.equal(normalizeText("\u0131"), "\u0131");
  assert.equal(normalizeText("I"), "i");
  assert.equal(normalizeText("\uab70"), "\u13a0");
  assert.equal(normalizeText("\u13a0"), "\u13a0");
  assert.equal(normalizeText("a\u2003b\u0085c"), "b c");
  assert.equal(normalizeText("the"), null);
});
