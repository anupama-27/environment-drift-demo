// Every browser suite in one go:
//   node tests/e2e/run.cjs
// Writes the fixtures to a temporary folder with the driftaudit command (DRIFTAUDIT_BIN, or
// the one on PATH), serves the workbench with driftaudit demo and a session with driftaudit
// view, runs the suites one after another, and exits non-zero if any of them failed.
// CHROME_PATH picks the browser; without it Playwright's own Chromium is used.
"use strict";

const fs = require("fs");
const os = require("os");
const net = require("net");
const http = require("http");
const path = require("path");
const { spawn, execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const BIN = process.env.DRIFTAUDIT_BIN || "driftaudit";
const SUITES = ["rounds.e2e.cjs", "analysis.e2e.cjs", "pages.e2e.cjs", "shell.e2e.cjs"];
const HOSTILE = "<img src=x onerror=alert(1)></script>";

function cli(args) {
  execFileSync(BIN, args, { cwd: ROOT, stdio: ["ignore", "ignore", "pipe"] });
}

function write(dir, name, value) {
  fs.writeFileSync(path.join(dir, name), typeof value === "string" ? value : JSON.stringify(value));
}

// The same run log with every string a reader can see carrying markup.
function hostile(text) {
  const run = JSON.parse(text);
  Object.keys(run.prompts).forEach((id) => { text = text.split(JSON.stringify(id)).join(JSON.stringify(HOSTILE + id)); });
  run.candidates.forEach((c) => { text = text.split(JSON.stringify(c.id)).join(JSON.stringify(HOSTILE + c.id)); });
  const out = JSON.parse(text);
  out.id = HOSTILE + "\u001b[31m\u0007" + out.id;
  delete out.outputs;
  Object.keys(out.prompts).forEach((k) => { out.prompts[k] = HOSTILE + out.prompts[k]; });
  out.candidates.forEach((c) => { c.note = HOSTILE; });
  Object.values(out.environments).forEach((e) => {
    e.name = HOSTILE + e.name;
    e.fingerprint = HOSTILE + e.fingerprint;
  });
  out.task.name = HOSTILE + out.task.name;
  out.model.id = HOSTILE + out.model.id;
  return out;
}

// The same run log as if the loop had compared every candidate with the round 0 reference.
function recorded(text) {
  const run = JSON.parse(text);
  run.id = "recorded-references";
  delete run.outputs;
  run.candidates.forEach((c) => { c.reference = { prompt: run.snapshots[0].prompt, env: run.snapshots[0].env, pass: "current" }; });
  return run;
}

// A copy of the site with one more bundled group: a run of the smoke run's shape (4 rounds,
// 40 items) with its outputs sidecar beside it, served as static files.
function smokeSite(dir) {
  const site = path.join(dir, "site");
  ["index.html", "favicon.svg", "assets", "data", "replay"].forEach((name) => {
    fs.cpSync(path.join(ROOT, name), path.join(site, name), { recursive: true });
  });
  const runs = path.join(site, "data", "runs", "smoke-shape");
  fs.mkdirSync(runs, { recursive: true });
  cli(["run", "--backend", "mock", "--n-dev", "20", "--n-eval", "40", "--rounds", "4", "--seed", "1",
    "--schedule", "0:greedy/strict,2:sample@0.2/strict,3:sample@0.2/lenient", "-o", path.join(runs, "smoke-shape.json")]);
  const index = JSON.parse(fs.readFileSync(path.join(site, "data", "index.json"), "utf8"));
  const id = JSON.parse(fs.readFileSync(path.join(runs, "smoke-shape.json"), "utf8")).id;
  index.groups.push({
    id: "smoke-shape", title: "Smoke run shape, mock backend", source: "synthetic",
    note: "One run of the shape of the laptop smoke run: 4 rounds, 40 items.", default: id,
    runs: [{ id, label: "Mock, seed 1", url: "data/runs/smoke-shape/smoke-shape.json", note: "Made with the mock backend for the browser tests." }]
  });
  write(site, path.join("data", "index.json"), JSON.stringify(index, null, 1));
  return site;
}

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".woff2": "font/woff2", ".gz": "application/gzip", ".png": "image/png" };

function staticServer(root, port) {
  const server = http.createServer((req, res) => {
    const clean = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const file = path.join(root, clean === "/" ? "index.html" : clean);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

function fixtures(dir) {
  cli(["run", "--n-dev", "30", "--n-eval", "50", "--rounds", "6", "-o", path.join(dir, "mock.json")]);
  cli(["report", path.join(ROOT, "data", "runs", "paper", "seed5.json"), "-o", path.join(dir, "report.html")]);
  const text = fs.readFileSync(path.join(dir, "mock.json"), "utf8");
  write(dir, "broken.json", "{\"schema\": \"driftaudit.run/v1\", \"id\": ");
  write(dir, "other.json", { name: "package", version: "1.0.0", private: true });
  write(dir, "hostile.json", hostile(text));
  write(dir, "recorded.json", recorded(text));
  const measured = recorded(text);
  measured.id = "measured-copy";
  measured.source = "measured";
  write(dir, "measured.json", measured);
  write(dir, "deep.json", "[".repeat(5000) + "]".repeat(5000));
}

function tryPort(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.on("error", () => resolve(null));
    server.listen(port, "127.0.0.1", () => {
      const got = server.address().port;
      server.close(() => resolve(got));
    });
  });
}

// A free port from E2E_PORTS (default 8831-8839), or any free port when none is left there.
const taken = new Set();
async function freePort() {
  const range = (process.env.E2E_PORTS || "8831-8839").split("-").map(Number);
  for (let port = range[0]; port <= (range[1] || range[0]); port++) {
    if (!taken.has(port) && await tryPort(port)) {
      taken.add(port);
      return port;
    }
  }
  return tryPort(0);
}

function answers(url) {
  return new Promise((resolve) => {
    http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    }).on("error", () => resolve(false));
  });
}

async function serve(args, url) {
  const child = spawn(BIN, args, { cwd: ROOT, stdio: ["ignore", "ignore", "pipe"] });
  let errors = "";
  child.stderr.on("data", (d) => { errors += d; });
  for (let i = 0; i < 100; i++) {
    if (await answers(url)) return child;
    if (child.exitCode !== null) break;
    await new Promise((r) => setTimeout(r, 150));
  }
  child.kill();
  throw new Error(BIN + " " + args.join(" ") + " did not start. " + errors.trim());
}

function suite(file, base, env) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [path.join(__dirname, file), base], { env, stdio: "inherit" });
    child.on("exit", (code) => resolve(code === 0));
  });
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "driftaudit-e2e-"));
  const servers = [];
  const results = [];
  let code = 1;
  try {
    console.log("fixtures in " + dir);
    fixtures(dir);
    const site = smokeSite(dir);
    const demo = await freePort();
    const view = await freePort();
    const copy = await freePort();
    const smoke = "http://127.0.0.1:" + copy;
    const statics = await staticServer(site, copy);
    servers.push({ kill: () => statics.close() });
    const base = "http://127.0.0.1:" + demo;
    const session = "http://127.0.0.1:" + view;
    servers.push(await serve(["demo", "--no-open", "--port", String(demo)], base + "/data/index.json"));
    servers.push(await serve(["view", path.join(dir, "mock.json"), "--no-open", "--port", String(view)], session + "/session/index.json"));
    const env = Object.assign({}, process.env, {
      E2E_FIXTURES: dir, E2E_SESSION: session, E2E_SMOKE: smoke, E2E_SHOTS: path.join(dir, "shots"), DRIFTAUDIT_BIN: BIN
    });
    for (const file of SUITES) {
      console.log("\n" + file);
      results.push([file, await suite(file, base, env)]);
    }
    const failed = results.filter((r) => !r[1]).map((r) => r[0]);
    console.log("\n" + (failed.length ? "e2e: " + failed.length + " of " + SUITES.length + " suites failed: " + failed.join(", ")
      : "e2e: all " + SUITES.length + " suites passed"));
    code = failed.length ? 1 : 0;
  } catch (err) {
    console.log("e2e: stopped: " + (err && err.message || err));
  } finally {
    servers.forEach((s) => s.kill());
    fs.rmSync(dir, { recursive: true, force: true });
  }
  process.exit(code);
})();
