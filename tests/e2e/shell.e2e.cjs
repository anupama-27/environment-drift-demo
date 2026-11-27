// The shell around the views: Summary, navigation, which policies are listed, and every way a
// run log gets in. Started by run.cjs, which prepares the files in E2E_FIXTURES and serves a
// session on E2E_SESSION:
//   node tests/e2e/shell.e2e.cjs http://localhost:8831
"use strict";

const fs = require("fs");
const path = require("path");
const { launch, suite, base } = require("./helper.cjs");

const BASE = base("http://localhost:8831");
const FIX = process.env.E2E_FIXTURES;
const SESSION = (process.env.E2E_SESSION || "").replace(/\/$/, "");
const SMOKE = (process.env.E2E_SMOKE || "").replace(/\/$/, "");
const SHOTS = process.env.E2E_SHOTS || "/tmp/shots/scratch";
const t = suite();
const check = t.check;

function squash(s) {
  return String(s).replace(/[\s ]+/g, " ").trim();
}

async function page(browser, label, options) {
  const p = await browser.newPage(Object.assign({ viewport: { width: 1440, height: 1000 } }, options || {}));
  t.watch(p, label);
  await p.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(e.violatedDirective + " " + e.blockedURI));
  });
  p.on("close", () => {});
  p.cspCheck = async () => {
    const found = await p.evaluate(() => window.__csp || []);
    t.check(found.length === 0, label + ": no content policy violation" + (found.length ? " (" + found[0] + ")" : ""));
  };
  p.on("dialog", (d) => {
    t.check(false, label + ": a dialog opened: " + d.message());
    d.dismiss();
  });
  return p;
}

async function ready(p, url) {
  await p.goto(url);
  await p.waitForSelector(".verdict", { timeout: 20000 });
}

// How far the page scrolls sideways, and what sticks out when it does.
async function sideways(p) {
  return p.evaluate(() => {
    const W = document.documentElement.clientWidth, over = document.documentElement.scrollWidth - W;
    if (over <= 0) return { over, who: "" };
    const who = Array.from(document.querySelectorAll("body *"))
      .filter((e) => e.getBoundingClientRect().right > W + 1 && !e.closest("[data-scroll]"))
      .slice(0, 3).map((e) => e.tagName.toLowerCase() + "." + String(e.className).split(" ")[0]).join(", ");
    return { over, who };
  });
}

async function view(p, name) {
  await p.evaluate((v) => { location.hash = "#/workbench/" + v; }, name);
  await p.waitForSelector(".view--" + name);
  await p.waitForTimeout(150);
}

async function pickRun(p, value) {
  await p.selectOption("select[name=run]", value);
  await p.waitForFunction((v) => {
    const s = DA.state.get();
    return s.selection.run === v && (v === "*" ? !!s.study : !!s.audit);
  }, value, { timeout: 20000 });
  await p.waitForTimeout(100);
}

async function openFiles(p, files) {
  const [chooser] = await Promise.all([p.waitForEvent("filechooser"), p.click("[data-open-run]")]);
  await chooser.setFiles(files);
}

async function rows(p) {
  return p.$$eval("[data-policy-row]", (els) => els.map((e) => e.getAttribute("data-policy-row")));
}

async function summary(browser) {
  const p = await page(browser, "summary");
  await ready(p, BASE + "/#/");
  check(squash(await p.innerText(".verdict")) === "A frozen reference promotes 8 candidates on this run. 4 of them do not raise accuracy, and 3 of the 4 pass only because the reference is stale.",
    "seed 5 verdict sentence");
  check(await p.evaluate(() => DA.ui.fmt.pp(-0.125) === "−0.12" && DA.ui.fmt.num(2.675, 2) === "2.67"), "formatters round ties to even in the page");
  await pickRun(p, "*");
  const counts = await p.$$eval("[data-key=summary-policies] tbody tr", (trs) => trs.map((tr) => tr.children[0].textContent.trim() + ": " + tr.children[2].textContent.trim()));
  check(JSON.stringify(counts) === JSON.stringify(["Frozen: 13 of 34", "Stored incumbent: 0 of 8", "Per-batch: 3 of 13", "Environment-triggered: 2 of 16"]),
    "all runs: false accepts 13 of 34, 0 of 8, 3 of 13, 2 of 16 (" + counts.join(", ") + ")");
  await p.cspCheck();
  await p.close();
}

async function navigation(browser) {
  const p = await page(browser, "navigation");
  await ready(p, BASE + "/#/");
  for (const v of ["rounds", "policies", "probe", "environments", "export", "summary"]) {
    await p.click(`.runbar a[data-key="view:${v}"]`);
    await p.waitForSelector(".view--" + v);
    await p.waitForTimeout(100);
    const info = await p.evaluate(() => ({ hash: location.hash, focus: document.activeElement.tagName, current: (document.querySelector(".runbar [aria-current=page]") || {}).textContent }));
    check(info.focus === "H1", v + ": focus on the view heading after the move (" + info.focus + ")");
    check(info.hash === (v === "summary" ? "#/" : "#/workbench/" + v), v + ": the hash follows (" + info.hash + ")");
  }
  await p.goBack();
  await p.waitForSelector(".view--export");
  check(true, "back returns to the previous view");
  await p.evaluate(() => { location.hash = "#/nowhere/at/all"; });
  await p.waitForFunction(() => location.hash === "#/");
  check(true, "an unknown hash goes to #/");

  await p.focus(".ruler__cell[data-round=\"0\"]");
  await p.keyboard.press("ArrowRight");
  await p.keyboard.press("ArrowRight");
  check(await p.evaluate(() => DA.state.get().round) === 2, "arrow keys move along the ruler");
  await p.keyboard.press("Escape");
  await p.waitForTimeout(50);
  check(await p.evaluate(() => DA.state.get().round) === null, "Escape clears the round");
  await p.focus(".summary .segmented__option[aria-checked=true]");
  await p.keyboard.press("ArrowRight");
  await p.waitForFunction(() => DA.state.get().policy === "stored_incumbent");
  check(true, "arrow keys move the policy switcher");

  await p.emulateMedia({ reducedMotion: "reduce" });
  await view(p, "rounds");
  await p.click(".rounds tr[data-round=\"8\"] .rounds__pick");
  await p.waitForTimeout(50);
  check(await p.evaluate(() => document.getAnimations().length) === 0, "reduced motion: the plate does not animate");
  await p.emulateMedia({ reducedMotion: "no-preference" });
  await p.click(".rounds tr[data-round=\"5\"] .rounds__pick");
  await p.waitForTimeout(30);
  check(await p.evaluate(() => document.getAnimations().length) > 0, "without the preference the changed cells settle in");

  await p.setViewportSize({ width: 360, height: 800 });
  for (const mode of ["gsm8k-qwen2.5-1.5b-seed5", "*"]) {
    await view(p, "summary");
    await pickRun(p, mode);
    for (const v of ["summary", "rounds", "policies", "probe", "environments", "export"]) {
      await view(p, v);
      await p.waitForTimeout(250);
      const s = await sideways(p);
      check(s.over <= 0, "360px, " + (mode === "*" ? "all runs" : "seed 5") + ", " + v + ": no sideways scroll (" + s.over + " " + s.who + ")");
    }
  }
  for (const h of ["#/case-study", "#/case-study/3", "#/case-study/5", "#/case-study/7", "#/case-study/9", "#/install"]) {
    await p.evaluate((x) => { location.hash = x; }, h);
    await p.waitForTimeout(500);
    const s = await sideways(p);
    check(s.over <= 0, "360px, " + h + ": no sideways scroll (" + s.over + " " + s.who + ")");
  }
  await p.close();
}

async function policies(browser) {
  const p = await page(browser, "policies");
  await ready(p, BASE + "/#/");
  check(JSON.stringify(await p.$$eval(".summary .segmented__option", (e) => e.map((x) => x.textContent))) === JSON.stringify(["Frozen", "Stored incumbent", "Per-batch", "Environment-triggered"]),
    "Summary: the switcher leaves out a trivial As run");
  await p.evaluate(() => DA.state.set({ policy: "as_run" }));
  await p.waitForTimeout(50);
  check(await p.evaluate(() => DA.state.get().policy) === "frozen", "a trivial As run falls back to Frozen");
  await view(p, "rounds");
  check(await p.locator(".rounds .segmented__option[data-value=as_run]").count() === 0, "Rounds: no As run in the switcher");
  await view(p, "policies");
  check(JSON.stringify(await rows(p)) === JSON.stringify(["frozen", "stored_incumbent", "per_batch", "env_triggered"]), "Policies: four rows on one run");
  check(await p.locator(".policies [data-as-run-note]").count() === 1, "Policies: the sentence on As run is there");
  const heads = await p.$$eval("[data-key=policies-matrix] thead th", (e) => e.map((x) => x.textContent.trim()));
  check(heads.indexOf("As run") < 0 && heads.indexOf("Every 3 rounds") < 0, "decision matrix: no As run, no Every k rounds");
  await p.click("[data-step=periodic_k][data-delta=\"1\"]");
  await p.waitForFunction(() => document.querySelector("[data-policy-row=periodic]"));
  check((await p.innerText("[data-policy-row=periodic]")).includes("Every 4 rounds"), "the stepper adds the Every 4 rounds row");
  await p.click("[data-preset=reset]");
  await p.waitForFunction(() => !document.querySelector("[data-policy-row=periodic]"));
  check(await p.evaluate(() => DA.state.get().options.periodic_k) === 3, "reset removes the row and restores k = 3");

  await pickRun(p, "*");
  await view(p, "policies");
  check(JSON.stringify(await rows(p)) === JSON.stringify(["frozen", "stored_incumbent", "per_batch", "env_triggered"]), "Policies, all runs: four rows");
  const tests = await p.$$eval("[data-test]", (e) => e.map((x) => x.getAttribute("data-test")));
  check(JSON.stringify(tests) === JSON.stringify(["frozen", "stored_incumbent", "per_batch"]), "Fisher lines: against frozen, stored incumbent and per-batch (" + tests + ")");
  const studyHeads = await p.$$eval("[data-key=policies-study-matrix] thead th", (e) => e.map((x) => x.textContent.trim()));
  check(studyHeads.indexOf("As run") < 0, "per-run table: no As run");
  await view(p, "summary");
  check(await p.locator("[data-key=summary-policies] [data-pick-policy=as_run]").count() === 0, "Summary, all runs: no As run row");

  await openFiles(p, [path.join(FIX, "recorded.json")]);
  await p.waitForFunction(() => DA.state.get().selection.run === "recorded" && DA.state.get().audit);
  await p.waitForTimeout(100);
  check(await p.evaluate(() => DA.state.get().policy) === "as_run", "a run with recorded references opens on As run");
  check(await p.locator(".summary .segmented__option[data-value=as_run]").count() === 1, "and offers it in the switcher");
  await view(p, "policies");
  check((await rows(p)).indexOf("as_run") >= 0 && await p.locator("[data-as-run-note]").count() === 0, "and lists it on Policies, without the sentence");
  await p.close();
}

async function mock(browser) {
  const p = await page(browser, "mock");
  await ready(p, BASE + "/#/");
  await openFiles(p, [path.join(FIX, "mock.json"), path.join(FIX, "mock.outputs.jsonl.gz")]);
  await p.waitForFunction(() => DA.state.get().selection.group === "yours" && DA.state.get().audit);
  await p.waitForSelector(".verdict");
  check((await p.innerText(".runbar .facts")).includes("synthetic"), "picker: the run bar tags the run synthetic");
  check((await p.$$eval("select[name=run] option", (o) => o.map((x) => x.textContent))).some((x) => /mock\.json \(synthetic\)/.test(x)), "picker: the run list says synthetic");
  check(/marked synthetic: its numbers are not measurements of a model/.test(await p.innerText(".summary")), "Summary says the numbers are simulated");
  await view(p, "rounds");
  await p.waitForFunction(() => document.querySelectorAll(".rounds__block pre").length === 3, null, { timeout: 15000 });
  check(true, "Rounds shows the three outputs from the sidecar");
  const plate = await p.evaluate(() => {
    const grid = document.querySelector(".plate__grid");
    const box = document.querySelector(".plate").getBoundingClientRect(), col = document.querySelector(".rounds__left").getBoundingClientRect();
    return { rows: grid.querySelectorAll(".plate__row").length, cells: grid.querySelectorAll(".plate__cell").length, inside: box.right <= col.right + 1 };
  });
  check(plate.cells === 50 && plate.rows === 5 && plate.inside, "50 items lay out as 5 rows of 10 inside the column");
  await p.locator(".plate").screenshot({ path: path.join(SHOTS, "mock-plate.png") });
  for (const v of ["policies", "probe", "environments", "export"]) {
    await view(p, v);
    check(/\S/.test(await p.innerText(".view--" + v)), "the mock run draws " + v);
  }
  await p.close();

  const q = await page(browser, "drop");
  await ready(q, BASE + "/#/");
  const files = ["mock.json", "mock.outputs.jsonl.gz"].map((name) => ({ name, b64: fs.readFileSync(path.join(FIX, name)).toString("base64") }));
  const transfer = await q.evaluateHandle((list) => {
    const dt = new DataTransfer();
    list.forEach((f) => dt.items.add(new File([Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0))], f.name)));
    return dt;
  }, files);
  await q.dispatchEvent("body", "dragenter", { dataTransfer: transfer });
  check(await q.locator("#da-drop.is-active").count() === 1, "drag: the drop overlay shows");
  await q.dispatchEvent("body", "drop", { dataTransfer: transfer });
  await q.waitForFunction(() => DA.state.get().selection.group === "yours" && DA.state.get().audit);
  check(await q.locator("#da-drop.is-active").count() === 0, "drop: the overlay goes");
  await view(q, "rounds");
  await q.waitForFunction(() => document.querySelectorAll(".rounds__block pre").length === 3, null, { timeout: 15000 });
  check(true, "drop: run and sidecar open, outputs shown");
  await q.close();
}

async function badFiles(browser) {
  const p = await page(browser, "bad files");
  await ready(p, BASE + "/#/");
  for (const [name, words] of [["broken.json", /not valid JSON/], ["other.json", /not a run log/], ["deep.json", /more than 64 levels deep/]]) {
    await openFiles(p, [path.join(FIX, name)]);
    await p.waitForSelector(".view .notice--error");
    const text = await p.innerText(".view .notice--error");
    check(words.test(text) && /The run you had open is unchanged\./.test(text), name + ": a clear error (" + squash(text).slice(0, 90) + ")");
    check(await p.evaluate(() => DA.state.get().selection.run) === "gsm8k-qwen2.5-1.5b-seed5" && await p.locator(".verdict").count() === 1, name + ": seed 5 stays open");
    await p.click(".view .notice--error [data-dismiss]");
  }
  await p.close();
}

async function hostile(browser) {
  const p = await page(browser, "hostile");
  await p.addInitScript(() => { window.alert = () => { window.__alerted = true; }; });
  await ready(p, BASE + "/#/");
  await openFiles(p, [path.join(FIX, "hostile.json")]);
  await p.waitForFunction(() => DA.state.get().selection.group === "yours" && DA.state.get().audit);
  for (const v of ["summary", "rounds", "policies", "probe", "environments", "export"]) {
    await view(p, v);
    await p.waitForTimeout(200);
    const r = await p.evaluate(() => ({
      imgs: document.querySelectorAll("img").length,
      text: (document.body.innerText.match(/<img src=x onerror=alert\(1\)><\/script>/g) || []).length
    }));
    check(r.imgs === 0 && r.text > 0, v + ": the markup shows as text (" + r.text + " times), no element made");
  }
  await p.click(".rounds__prompts summary").catch(() => {});
  check(await p.evaluate(() => !window.__alerted), "nothing executed");
  check(await p.evaluate(() => !/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/.test(document.body.innerText)), "control characters are stripped");
  await p.cspCheck();
  await p.close();
}

async function session(browser) {
  const p = await page(browser, "session");
  await p.goto(SESSION + "/?session=1#/workbench/rounds");
  await p.waitForSelector(".rounds__item", { timeout: 20000 });
  check(await p.evaluate(() => DA.state.get().selection.group) === "session", "session: the session run is selected first");
  check((await p.$$eval("select[name=group] option", (o) => o.map((x) => x.value)))[0] === "session", "session: its group is listed first");
  await p.waitForFunction(() => document.querySelectorAll(".rounds__block pre").length === 3, null, { timeout: 15000 });
  check(true, "session: the outputs load");
  await p.cspCheck();
  await p.close();
}

async function report(browser) {
  const p = await page(browser, "report");
  const remote = [];
  const messages = [];
  p.on("request", (r) => { if (!/^(file|data|blob):/.test(r.url())) remote.push(r.url()); });
  p.on("console", (m) => messages.push(m.type() + ": " + m.text()));
  await ready(p, "file://" + path.join(FIX, "report.html"));
  check(/promotes 8 candidates/.test(squash(await p.innerText(".verdict"))), "report: Summary");
  await view(p, "rounds");
  check(await p.locator(".rounds .plate__cell").count() === 400, "report: Rounds shows the grades");
  check(/Outputs are not attached to this report/.test(await p.innerText(".rounds__item")), "report: says outputs are not attached");
  await view(p, "policies");
  check(await p.locator("[data-policy-row]").count() === 4, "report: Policies");
  await view(p, "environments");
  check(await p.locator("[data-env-row]").count() === 4, "report: Environments");
  await p.evaluate(() => { location.hash = "#/case-study"; });
  await p.waitForSelector(".cs .notice");
  check(/needs the hosted site/.test(await p.innerText(".cs .notice")), "report: the case study shows its notice");
  check(messages.length === 0, "report: nothing in the console" + (messages.length ? " (" + messages[0] + ")" : ""));
  check(remote.length === 0, "report: no network requests" + (remote.length ? " (" + remote[0] + ")" : ""));
  await p.cspCheck();
  await p.close();
}

async function install(browser) {
  const p = await page(browser, "install");
  await p.goto(BASE + "/#/install");
  await p.waitForSelector(".install");
  const commands = await p.$$eval(".install .code code", (els) => els.map((e) => e.textContent));
  const bare = commands.filter((c) => /pip install\s+(-U\s+)?"?driftaudit\b/.test(c) && !/@ git\+https:\/\//.test(c));
  check(commands.length > 5 && bare.length === 0, "Install: no command installs driftaudit by bare name" + (bare.length ? " (" + bare[0] + ")" : ""));
  await p.cspCheck();
  await p.close();
}

async function pools(browser) {
  const p = await page(browser, "pools");
  await ready(p, BASE + "/#/");
  await openFiles(p, [path.join(FIX, "mock.json"), path.join(FIX, "measured.json")]);
  await p.waitForFunction(() => DA.state.get().selection.group === "yours" && DA.state.get().audit);
  await pickRun(p, "*");
  check(/2 runs, 1 of them synthetic/.test(squash(await p.innerText(".runbar .facts"))), "mixed pool: the header names the mix");
  check(/1 of the 2 runs in this set are marked synthetic/.test(squash(await p.innerText(".summary"))), "mixed pool: a plain warning");
  check(await p.evaluate(() => DA.state.get().study.source) === "mixed", "mixed pool: the study says mixed");
  await p.selectOption("select[name=group]", "paper");
  await p.waitForFunction(() => DA.state.get().selection.group === "paper" && DA.state.get().audit);
  await pickRun(p, "*");
  check(/5 measured runs/.test(squash(await p.innerText(".runbar .facts"))), "paper pool: 5 measured runs in the header");
  await p.close();

  const q = await page(browser, "incompatible");
  await ready(q, BASE + "/#/");
  await openFiles(q, [path.join(FIX, "mock.json"), path.resolve(__dirname, "..", "..", "toolkit", "runs", "run_seed1_hf_Qwen2.5-1.5B-Instruct_n200_r11.json")]);
  await q.waitForFunction(() => DA.state.get().selection.group === "yours" && DA.state.get().audit && document.querySelector("[data-pool-problem]"));
  check(await q.$eval("select[name=run] option[value='*']", (o) => o.disabled), "incompatible runs: All runs is unavailable");
  check(/cannot be pooled\. .+: number of items is 200, where .+ has 50\./.test(squash(await q.innerText("[data-pool-problem]"))), "incompatible runs: one sentence names the first difference (" + squash(await q.innerText("[data-pool-problem]")) + ")");
  await q.evaluate(() => DA.state.set({ selection: { group: "yours", run: "*" } }));
  await q.waitForTimeout(100);
  check(await q.evaluate(() => DA.state.get().selection.run !== "*" && !DA.state.get().study), "incompatible runs: asking for the pool falls back to one run");
  await view(q, "probe");
  check(/cannot be pooled/.test(await q.innerText(".probe")), "incompatible runs: the probe shows the selected run alone");
  await q.close();
}

async function smoke(browser) {
  const p = await page(browser, "smoke shape");
  await ready(p, SMOKE + "/#/");
  check(await p.evaluate(() => DA.state.get().selection.run) === "gsm8k-qwen2.5-1.5b-seed5", "with a second group the paper's seed 5 still opens");
  check(/five recorded runs behind the paper/.test(await p.innerText(".runbar")), "the paper group's note shows under the picker");
  await p.selectOption("select[name=group]", "smoke-shape");
  await p.waitForFunction(() => DA.state.get().selection.group === "smoke-shape" && DA.state.get().audit);
  await p.waitForSelector(".verdict");
  check(/shape of the laptop smoke run/.test(await p.innerText(".runbar")), "the second group's note shows");
  check(/Made with the mock backend/.test(await p.innerText(".summary")), "the run's note shows under the Summary title");
  check(await p.locator(".runbar .ruler__cell[data-round]").count() === 4, "the ruler has 4 rounds");
  const fit = await p.evaluate(() => { const r = document.querySelector(".runbar .ruler").getBoundingClientRect(); return r.right <= document.documentElement.clientWidth; });
  check(fit, "the ruler fits the page");
  await view(p, "rounds");
  await p.waitForFunction(() => document.querySelectorAll(".rounds__block pre").length === 3, null, { timeout: 15000 });
  check(true, "the item panel shows raw outputs from the statically served sidecar");
  const plate = await p.evaluate(() => ({ cells: document.querySelectorAll(".plate__grid[data-plate-grid=stored] .plate__cell").length, rows: document.querySelectorAll(".plate__grid[data-plate-grid=stored] .plate__row").length }));
  check(plate.cells === 40 && plate.rows === 4, "40 items lay out as 4 rows of 10");
  await p.screenshot({ path: path.join(SHOTS, "smoke-rounds.png"), fullPage: true });
  await p.cspCheck();
  await p.close();
}

async function legacy(browser) {
  const p = await page(browser, "legacy");
  await ready(p, BASE + "/#/");
  await openFiles(p, [path.resolve(__dirname, "..", "..", "toolkit", "runs", "run_seed1_hf_Qwen2.5-1.5B-Instruct_n200_r11.json")]);
  await p.waitForFunction(() => DA.state.get().selection.group === "yours" && DA.state.get().audit);
  check(/A frozen reference promotes 7 candidates on this run/.test(squash(await p.innerText(".verdict"))), "legacy run file opens through the picker");
  await view(p, "rounds");
  check(await p.locator(".rounds tr[data-round]").count() === 11, "legacy: eleven rounds");
  await p.close();
}

(async () => {
  if (!FIX || !SESSION || !SMOKE) {
    console.log("FAIL E2E_FIXTURES and E2E_SESSION are set by tests/e2e/run.cjs");
    process.exit(1);
  }
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await launch();
  for (const part of [summary, navigation, policies, mock, badFiles, hostile, session, report, legacy, install, pools, smoke]) {
    try {
      await part(browser);
    } catch (err) {
      check(false, part.name + " stopped: " + (err && err.message || err));
    }
  }
  await browser.close();
  t.finish();
})();
