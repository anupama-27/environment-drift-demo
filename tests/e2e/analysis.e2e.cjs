// Policies, Drift probe, Environments and Export on the five bundled runs.
// NODE_PATH=$(npm root -g) node tests/e2e/analysis.e2e.cjs http://localhost:8822
"use strict";

const fs = require("fs");
const path = require("path");
const { launch } = require("./helper.cjs");

const BASE = (process.argv[2] || "http://localhost:8822").replace(/\/$/, "");
const SHOTS = process.env.E2E_SHOTS || "/tmp/shots/w2";
const MINUS = "−";

const failures = [];
const consoleProblems = [];

function check(ok, what) {
  if (ok) {
    console.log("ok   " + what);
  } else {
    console.log("FAIL " + what);
    failures.push(what);
  }
}

async function text(page, selector) {
  return (await page.locator(selector).innerText()).replace(/\s+/g, " ").trim();
}

async function open(page, view) {
  await page.evaluate((v) => { location.hash = "#/workbench/" + v; }, view);
  await page.waitForSelector(".view--" + view);
}

async function selectRun(page, value) {
  await page.selectOption("select[name=run]", value);
  await page.waitForFunction((v) => {
    const s = window.DA.state.get();
    return s.selection.run === v && (v === "*" ? !!s.study : !!s.audit);
  }, value);
}

async function settle(page) {
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 30))));
}

async function rowText(page, attr, id) {
  return text(page, "[" + attr + "=\"" + id + "\"]");
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") consoleProblems.push(msg.type() + ": " + msg.text());
  });
  page.on("pageerror", (err) => consoleProblems.push("pageerror: " + err.message));

  try {
    await page.goto(BASE + "/#/workbench/policies");
    await page.waitForFunction(() => window.DA && window.DA.state.get().audit);
    await selectRun(page, "*");
    await open(page, "policies");
    await settle(page);

    // Pooled table
    const rows = {
      frozen: ["13 of 34", "4,411"],
      stored_incumbent: ["0 of 8", "4,411"],
      per_batch: ["3 of 13", "6,611"],
      env_triggered: ["2 of 16", "4,811"]
    };
    for (const id of Object.keys(rows)) {
      const t = await rowText(page, "data-policy-row", id);
      check(t.includes(rows[id][0]) && t.includes(rows[id][1]), "pooled " + id + " shows " + rows[id].join(" and ") + " (" + t + ")");
    }
    const tests = await text(page, ".policies__tests");
    for (const p of ["0.033", "0.019", "0.360"]) check(tests.includes("p = " + p), "Fisher p = " + p);
    check((await text(page, ".policies")).includes("overstates the evidence"), "Fisher caveat shown");
    check((await text(page, "[data-lede]")).includes("55 candidates"), "lede counts 55 candidates");
    await page.screenshot({ path: path.join(SHOTS, "policies-1440.png"), fullPage: true });

    // Seed 1 decision matrix, paper Table 2
    await selectRun(page, "gsm8k-qwen2.5-1.5b-seed1");
    await settle(page);
    const cols = await page.$$eval("[data-key=policies-matrix] thead th", (ths) => ths.map((th) => th.textContent.trim()));
    async function decision(round, policy) {
      const i = cols.indexOf(policy);
      return page.$eval("[data-round-row=\"" + round + "\"]", (tr, idx) => {
        const cell = tr.children[idx].querySelector("[data-decision]");
        return cell ? cell.getAttribute("data-decision") : null;
      }, i);
    }
    check(await decision(3, "Frozen") === "false-accept", "seed 1 round 3: frozen false accept");
    check(await decision(5, "Per-batch") === "false-reject", "seed 1 round 5: per-batch false reject");
    check(await decision(10, "Frozen") === "false-accept", "seed 1 round 10: frozen false accept");
    check(await decision(4, "Environment-triggered") === "improved", "seed 1 round 4: environment-triggered promotes");
    check((await rowText(page, "data-round-row", "5")).includes("+5.00"), "seed 1 round 5 shows the +5.00 pp change");

    // What-ifs
    const frozenBefore = await rowText(page, "data-policy-row", "frozen");
    check(frozenBefore.includes("4 of 7"), "seed 1 frozen: 4 of 7 (" + frozenBefore + ")");
    await page.click("[data-preset=no-scorer]");
    await settle(page);
    const frozenWhatIf = await rowText(page, "data-policy-row", "frozen");
    check(frozenWhatIf !== frozenBefore, "no scorer change alters the frozen row (" + frozenWhatIf + ")");
    check(await page.locator("[data-key=policies-counterfactual]").isVisible(), "counterfactual notice shown");
    check((await page.$eval("[data-key=policies-counterfactual]", (n) => n.className)).includes("notice--warning"), "counterfactual notice is the yellow kind");
    await page.click("[data-preset=reset]");
    await settle(page);
    check(await rowText(page, "data-policy-row", "frozen") === frozenBefore, "reset restores the frozen row");
    check(await page.locator("[data-key=policies-counterfactual]").count() === 0, "reset removes the notice");

    const promotions = async () => Number((await page.$eval("[data-policy-row=frozen]", (tr) => tr.children[2].textContent)).replace(/,/g, ""));
    const before = await promotions();
    await page.click("[data-step=margin][data-delta=\"1\"]");
    await page.click("[data-step=margin][data-delta=\"1\"]");
    await settle(page);
    check(await page.evaluate(() => window.DA.state.get().options.margin) === 2, "margin stepper reaches 2");
    check(await promotions() < before, "margin 2 lowers frozen promotions (" + before + " to " + (await promotions()) + ")");
    await page.click("[data-step=periodic_k][data-delta=\"1\"]");
    await settle(page);
    check((await rowText(page, "data-policy-row", "periodic")).includes("Every 4 rounds"), "periodic row follows k");
    await page.click("[data-key=\"policies-scoring:rescore\"]");
    await settle(page);
    check(await page.evaluate(() => window.DA.state.get().options.stored_scoring) === "rescore", "stored reading switches to rescore");
    await page.click("[data-preset=reset]");
    await settle(page);
    await page.setViewportSize({ width: 390, height: 900 });
    await settle(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(overflow <= 0, "no sideways page scroll at 390px (" + overflow + ")");
    await page.screenshot({ path: path.join(SHOTS, "policies-390.png"), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });

    // Drift probe
    await selectRun(page, "*");
    await open(page, "probe");
    await settle(page);
    const expected = {
      E1: [MINUS + "0.12", MINUS + "0.64 to +0.39"],
      E2: [MINUS + "0.59", MINUS + "2.61 to +1.43"],
      E3: ["+1.31", "+0.65 to +1.98"],
      E4: ["+1.54", "+0.04 to +3.04"]
    };
    for (const id of Object.keys(expected)) {
      const t = await rowText(page, "data-env-row", id);
      check(t.includes(expected[id][0]) && t.includes(expected[id][1]), "probe " + id + " at age 3: " + t);
    }
    check((await text(page, "[data-probe-age-value]")) === "3", "probe age starts at 3");
    await page.screenshot({ path: path.join(SHOTS, "probe-1440.png"), fullPage: true });
    const atThree = await rowText(page, "data-env-row", "E3");
    await page.click("[data-probe-age=\"-1\"]");
    await page.click("[data-probe-age=\"-1\"]");
    await settle(page);
    check((await text(page, "[data-probe-age-value]")) === "1", "probe age set to 1");
    check((await rowText(page, "data-env-row", "E3")) !== atThree, "probe numbers change at age 1");

    // Environments
    await open(page, "environments");
    await settle(page);
    check((await text(page, "[data-flip=\"E1:E3\"]")).includes("638 of 11,400"), "638 of 11,400 labels flip from wrong to right");
    check((await text(page, "[data-env-row=E2]")).includes("decoding greedy-0.0 to sample-0.2"), "what changed is stated in words");
    await page.click("[data-bench-example=\"1\"]");
    await settle(page);
    check((await text(page, "[data-scorer=strict]")).includes("nothing"), "strict reads \\boxed{70,000} as nothing");
    check((await text(page, "[data-scorer=lenient]")).includes("70000"), "lenient reads \\boxed{70,000} as 70000");
    await page.fill("[data-bench-gold]", "70000");
    await settle(page);
    check((await text(page, "[data-scorer=lenient]")).includes("yes"), "lenient matches the gold answer");
    await page.fill("[data-bench-text]", "#### 12");
    await settle(page);
    check((await text(page, "[data-scorer=strict]")).includes("12"), "bench updates as you type");
    await page.screenshot({ path: path.join(SHOTS, "environments-1440.png"), fullPage: true });

    // Export
    await selectRun(page, "gsm8k-qwen2.5-1.5b-seed1");
    await open(page, "export");
    await settle(page);
    const [download] = await Promise.all([page.waitForEvent("download"), page.click("[data-export=audit-json]")]);
    const saved = await download.path();
    let parsed = null;
    try {
      parsed = JSON.parse(fs.readFileSync(saved, "utf8"));
    } catch (err) {
      parsed = null;
    }
    check(parsed && parsed.schema === "driftaudit.audit/v1", "audit JSON download parses (" + download.suggestedFilename() + ")");
    const [md] = await Promise.all([page.waitForEvent("download"), page.click("[data-export=audit-md]")]);
    check(fs.readFileSync(await md.path(), "utf8").includes("## Decisions under the frozen policy"), "Markdown download holds the decisions");
    const cmd = await text(page, "[data-command] code");
    check(cmd.includes("--policy frozen") && cmd.startsWith("driftaudit audit "), "command line: " + cmd);
    check((await text(page, ".export")).includes("pip install \"git+https://github.com/anupama-27/environment-drift-demo\""), "install line shown");
    await page.screenshot({ path: path.join(SHOTS, "export-1440.png"), fullPage: true });
  } catch (err) {
    failures.push("script stopped: " + (err && err.stack || err));
    console.log("FAIL script stopped: " + (err && err.stack || err));
  }

  await browser.close();
  consoleProblems.forEach((p) => console.log("console " + p));
  check(consoleProblems.length === 0, "no console errors or warnings");
  console.log(failures.length ? failures.length + " failed" : "all passed");
  process.exit(failures.length ? 1 : 0);
})();
