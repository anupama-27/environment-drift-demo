// Walks the Case study and the Install page in Chrome.
//   NODE_PATH=$(npm root -g) node tests/e2e/pages.e2e.cjs http://localhost:8823
// Exits non-zero on a failed check or on any console error or warning.
"use strict";

const { launch } = require("./helper.cjs");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const BASE = (process.argv[2] || "http://localhost:8823").replace(/\/$/, "");
const SHOTS = process.env.E2E_SHOTS || "/tmp/shots/w2";
const CLI = process.env.DRIFTAUDIT_BIN || "driftaudit";

const failures = [];
const consoleProblems = [];

function check(ok, what) {
  if (ok) console.log("ok   " + what);
  else {
    console.log("FAIL " + what);
    failures.push(what);
  }
}

function watch(page, label) {
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") consoleProblems.push(label + ": " + msg.type() + ": " + msg.text());
  });
  page.on("pageerror", (err) => consoleProblems.push(label + ": page error: " + err.message));
}

async function text(page, selector) {
  return (await page.locator(selector).first().innerText()).replace(/\s+/g, " ");
}

async function step(page) {
  return page.evaluate(() => DA.state.get().route.step);
}

async function heading(page) {
  return text(page, "#cs-step-title");
}

async function waitStep(page, n) {
  await page.waitForFunction((k) => {
    const h = document.querySelector("#cs-step-title");
    return DA.state.get().route.step === k && h && h.textContent.indexOf("Step " + k + " of 9") >= 0;
  }, n);
}

async function next(page) {
  const n = await step(page);
  await page.click("[data-key=cs-next]");
  await waitStep(page, n + 1);
}

async function clickUntilDisabled(page, selector, max) {
  for (let i = 0; i < max; i++) {
    const el = page.locator(selector);
    if (await el.isDisabled()) return i;
    await el.click();
    await page.waitForTimeout(20);
  }
  return max;
}

async function caseStudy(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  watch(page, "case study");
  await page.goto(BASE + "/#/case-study", { waitUntil: "networkidle" });
  await page.waitForSelector("#cs-step-title");

  // Step 1
  check((await heading(page)).includes("Grade one answer two ways"), "step 1 is Grade one answer two ways");
  check((await page.locator("select[name=cs-seed]").inputValue()) === "5", "seed 5 is the example");
  check((await text(page, ".cs-run")).includes("Replay of recorded runs"), "replay tag shown");
  check((await text(page, ".cs-run")).includes("Qwen2.5-1.5B-Instruct, first 200 GSM8K test questions, 11 rounds, 5 seeds."), "run note shown");
  check((await text(page, ".cs-step__body")).includes("toolkit/export_replay.py"), "step 1 says where the replay files come from");
  check(await page.locator(".cs-stepper__item.is-locked").count() === 8, "steps 2 to 9 locked at the start");
  await page.click("[data-cs-q='1']");
  await page.waitForFunction(() => document.querySelector(".cs-panel h3").textContent.indexOf("bag of chips") >= 0);
  check((await text(page, ".cs-panel")).includes("Same saved answer, two grades"), "picking a question shows its grades");
  await page.keyboard.press("ArrowRight");
  await waitStep(page, 2);
  check(await page.evaluate(() => document.activeElement && document.activeElement.id === "cs-step-title"), "focus moves to the step heading");
  check(page.url().endsWith("#/case-study/2"), "the step is in the route");

  // Step 2: rounds one at a time
  check(await page.locator("[data-key=cs-next]").isDisabled(), "step 2 Next waits for the rounds");
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(100);
  check(await step(page) === 2, "arrow key does not skip an unfinished step");
  const rounds = await clickUntilDisabled(page, "[data-key=cs-round]", 10);
  check(rounds === 4, "four rounds before the first change (" + rounds + ")");
  check((await text(page, ".cs-step__body")).includes("Candidate p4 wins 26 and loses 22"), "latest decision line");
  await next(page);

  // Step 3: the two changes
  check(await page.locator("[data-key=cs-next]").isDisabled(), "step 3 Next waits for the changes");
  const changes = await clickUntilDisabled(page, "[data-key=cs-change]", 5);
  check(changes === 2, "two changes to apply (" + changes + ")");
  const s3 = await text(page, ".cs-step__body");
  check(s3.includes("638 of 11,400"), "answer flips 638 of 11,400");
  check(s3.includes("+1.31 pp"), "extractor inflation +1.31 pp in step 3");
  await next(page);

  // Step 4: candidates one at a time, then show all
  await page.click("[data-key=cs-score]");
  await page.click("[data-key=cs-score-all]");
  await page.waitForSelector("[data-key=cs-score]:disabled");
  const s4 = await text(page, ".cs-step__body");
  check(s4.includes("All 5 seeds, reference age 3 rounds"), "all-seed inflation table appears");
  check(/Extraction[^]*\+1\.31/.test(await page.locator(".cs-step__body .chart--intervals").first().textContent()), "inflation table: +1.31 for the extraction change");
  await next(page);

  // Step 5
  const s5 = await text(page, ".cs-verdict");
  check(s5.includes("On this seed the frozen rule promotes 4 candidates that are not better"), "step 5: four false accepts on seed 5");
  check(/Causes on this seed: stale reference 3, would have been accepted anyway 0, no environment change 1/.test(s5), "step 5: 3 stale, 0 anyway, 1 no environment change");
  check(/makes 13 false accepts\. By cause: stale reference 6, would have been accepted anyway 3, no environment change 4/.test(s5), "step 5: 13 across all seeds as 6, 3, 4");
  check(await page.locator(".cs-step__body .chart--netgain").count() === 1, "step 5 draws the net gain chart");
  check(await page.locator(".chart--netgain .chart__wide .mark--false-accept").count() === 4, "four false accepts marked under the axis");
  await page.screenshot({ path: path.join(SHOTS, "case-5-1440.png"), fullPage: true });
  await next(page);

  // Step 6: vote
  check(await page.locator("[data-key=cs-next]").isDisabled(), "step 6 Next waits for a vote");
  await page.click("[data-cs-vote=C]");
  await page.waitForSelector("[data-cs-vote=C][aria-pressed=true]");
  const s6 = await text(page, ".cs-step__body");
  check(s6.includes("C. Environment-triggered (your pick)"), "vote marks the pick");
  check(s6.includes("2 of 16"), "pooled false accepts for the pick");
  await next(page);

  // Step 7
  const s7 = await page.locator(".cs-dash").textContent();
  ["13/34", "3/13", "2/16", "4,411", "6,611", "4,811"].forEach((v) => check(s7.includes(v), "step 7 shows " + v));
  await page.screenshot({ path: path.join(SHOTS, "case-7-1440.png"), fullPage: true });
  await next(page);

  // Step 8: pick a task
  await page.click("[data-tabs=cs-app] [data-value='Code generation']");
  await page.waitForFunction(() => document.querySelector("[data-key=cs-map]").textContent.indexOf("unit tests") >= 0);
  const s8 = await text(page, ".cs-step__body");
  check(s8.includes("No runs were made on financial QA or code generation"), "step 8 keeps the illustration statement");
  check(await page.locator(".cs-step__body a[href='#/install']").count() === 1, "step 8 links the Install page");
  await next(page);

  // Step 9
  const s9 = await text(page, ".cs-step__body");
  check(s9.includes("ran with the scripts in toolkit/"), "step 9 names toolkit/");
  check(s9.includes("python export_replay.py"), "step 9 keeps the commands");
  check(await page.locator("[data-key=cs-next]").count() === 0, "no Next on the last step");
  await page.keyboard.press("ArrowLeft");
  await waitStep(page, 8);
  check(true, "arrow left goes back");

  // Changing the seed keeps the step and fills the steps before it.
  await page.goto(BASE + "/#/case-study/5", { waitUntil: "networkidle" });
  await waitStep(page, 5);
  await page.selectOption("select[name=cs-seed]", "4");
  await page.waitForFunction(() => document.querySelector(".cs-verdict").textContent.indexOf("no false accept") >= 0);
  check(await step(page) === 5, "seed 4 keeps step 5");
  await page.close();
}

// The rule for links: a linked step opens with every step before it completed.
async function deepLink(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  watch(page, "deep link");
  await page.goto(BASE + "/#/case-study/7", { waitUntil: "networkidle" });
  await page.reload({ waitUntil: "networkidle" });
  await waitStep(page, 7);
  check((await heading(page)).includes("Compare the policies on five seeds"), "#/case-study/7 opens the dashboard after reload");
  check((await page.locator(".cs-dash").textContent()).includes("13/34"), "the linked dashboard has its numbers");
  check(await page.locator(".cs-stepper__item.is-locked").count() === 2, "steps 8 and 9 stay locked");
  await page.click(".cs-stepper a[href='#/case-study/4']");
  await waitStep(page, 4);
  check(await page.locator("[data-key=cs-score]").isDisabled(), "steps before the link are completed");
  await page.click(".cs-stepper a[href='#/case-study/6']");
  await waitStep(page, 6);
  check(await page.locator("[data-key=cs-next]").isDisabled(), "the vote is left to the reader");
  await page.close();
}

async function narrow(browser) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  watch(page, "390");
  await page.goto(BASE + "/#/case-study", { waitUntil: "networkidle" });
  await page.waitForSelector("#cs-step-title");
  check(await page.locator(".cs-stepper__list").isHidden(), "390: numbered list collapses");
  check((await text(page, ".cs-stepper__compact")).includes("Step 1 of 9"), "390: shows Step 1 of 9");
  const wide = await page.evaluate(() => document.documentElement.scrollWidth);
  check(wide <= 390, "390: no sideways scroll (" + wide + ")");
  await page.screenshot({ path: path.join(SHOTS, "case-1-390.png"), fullPage: true });
  await page.click("[data-key=cs-top-next]");
  await waitStep(page, 2);
  check((await text(page, ".cs-stepper__compact")).includes("Step 2 of 9"), "390: compact next moves on");
  await page.close();
}

async function unavailable(browser) {
  const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
  watch(page, "missing files");
  await page.route("**/replay/**", (route) => route.fulfill({ status: 404, body: "" }));
  await page.goto(BASE + "/#/case-study", { waitUntil: "networkidle" });
  await page.waitForSelector(".cs .notice");
  check((await text(page, ".cs .notice")).includes("driftaudit demo"), "missing replay files give a notice");
  await page.close();
  // The 404s above are expected; drop their console lines.
  for (let i = consoleProblems.length - 1; i >= 0; i--) {
    if (consoleProblems[i].indexOf("missing files:") === 0 && /404/.test(consoleProblems[i])) consoleProblems.splice(i, 1);
  }
}

function helpOf(args) {
  return execFileSync(CLI, args.concat(["--help"]), { encoding: "utf8" });
}

async function install(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  watch(page, "install");
  await page.goto(BASE + "/#/install", { waitUntil: "networkidle" });
  await page.waitForSelector(".install");
  const blocks = await page.locator(".install .code pre").allInnerTexts();
  check(blocks.some((b) => b.trim() === 'pip install "git+https://github.com/anupama-27/environment-drift-demo"'), "Install shows the pip line");
  check(!blocks.some((b) => /pip install driftaudit\b(?!\[)/.test(b)), "no pip install driftaudit from PyPI");
  const top = helpOf([]);
  const helps = {};
  blocks.forEach((b) => {
    b.split("\n").forEach((line) => {
      const m = line.trim().match(/^driftaudit\s+(\S+)(.*)$/);
      if (!m) return;
      const sub = m[1];
      check(new RegExp("^\\s{4}" + sub + "\\s", "m").test(top), "driftaudit " + sub + " exists");
      helps[sub] = helps[sub] || helpOf([sub]);
      (m[2].match(/--[a-z][a-z-]*/g) || []).forEach((flag) => check(helps[sub].includes(flag), "driftaudit " + sub + " " + flag + " is in --help"));
    });
  });
  check(blocks.some((b) => b.includes("rec.save(")), "recorder snippet shown");
  check(await page.locator(".install a[href$='docs/run-log-format.md']").count() === 1, "links the run-log format");
  await page.screenshot({ path: path.join(SHOTS, "install-1440.png"), fullPage: true });
  await page.close();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await launch();
  try {
    await caseStudy(browser);
    await deepLink(browser);
    await narrow(browser);
    await unavailable(browser);
    await install(browser);
  } catch (err) {
    failures.push("script error: " + (err && err.stack || err));
    console.log(err && err.stack || err);
  } finally {
    await browser.close();
  }
  consoleProblems.forEach((p) => console.log("CONSOLE " + p));
  const bad = failures.length + consoleProblems.length;
  console.log(bad ? bad + " problem(s)" : "all checks passed");
  process.exit(bad ? 1 : 0);
})();
