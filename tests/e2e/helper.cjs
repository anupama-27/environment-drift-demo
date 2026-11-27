// What the browser suites share: the browser, the checks and the console watch.
"use strict";

const { chromium } = require("playwright");

// Chrome from CHROME_PATH when it is set, Playwright's own Chromium otherwise.
function launch() {
  const options = { args: ["--no-sandbox"] };
  if (process.env.CHROME_PATH) options.executablePath = process.env.CHROME_PATH;
  return chromium.launch(options);
}

function suite() {
  const failures = [];
  const noise = [];
  return {
    failures,
    noise,
    check(ok, what) {
      console.log((ok ? "ok   " : "FAIL ") + what);
      if (!ok) failures.push(what);
    },
    // Console errors and warnings, and uncaught errors, count as failures.
    watch(page, label) {
      const prefix = label ? label + ": " : "";
      page.on("console", (msg) => {
        if (msg.type() === "error" || msg.type() === "warning") noise.push(prefix + msg.type() + ": " + msg.text());
      });
      page.on("pageerror", (err) => noise.push(prefix + "page error: " + err.message));
    },
    finish() {
      noise.forEach((n) => console.log("CONSOLE " + n));
      const bad = failures.length + noise.length;
      console.log(bad ? bad + " problem(s)" : "all checks passed");
      process.exit(bad ? 1 : 0);
    }
  };
}

function base(fallback) {
  return (process.argv[2] || process.env.E2E_BASE || fallback).replace(/\/$/, "");
}

module.exports = { launch, suite, base };
