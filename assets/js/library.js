(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  var YOURS = "yours";
  var sidecars = {};
  var memo = { audit: null, study: null };
  var asRunOf = typeof WeakMap === "function" ? new WeakMap() : null;
  var hidden = typeof WeakMap === "function" ? new WeakMap() : null;
  var lastRuns = null;
  var fileInput = null;
  var dragDepth = 0;

  function find(list, id) {
    var i;
    for (i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  function fetchJson(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error(url + " answered " + response.status);
      return response.json();
    });
  }

  function fail(title, message) {
    DA.state.set({ error: { title: title, message: message } });
  }

  /* Where runs come from ------------------------------------------------------------- */

  function embeddedGroup() {
    var node = document.getElementById("da-embedded"), data;
    if (!node) return null;
    data = JSON.parse(node.textContent);
    return {
      id: "embedded", title: data.title || "Runs in this report", source: null, note: null,
      runs: (data.runs || []).map(function (raw, i) {
        var run = DA.schema.load(raw);
        return { id: run.id || "run-" + (i + 1), label: run.id || "Run " + (i + 1), run: run };
      })
    };
  }

  function sessionGroup() {
    if (!/[?&]session=1(&|$)/.test(root.location.search)) return Promise.resolve(null);
    return fetchJson("session/index.json").then(function (data) {
      return {
        id: "session", title: data.title || "Your session", source: null, note: null,
        runs: (data.runs || []).map(function (r) { return { id: r.name, label: r.name, url: r.url, outputs: r.outputs || null }; })
      };
    });
  }

  // The gallery, or the five saved runs of the paper when no gallery has been built.
  function bundledGroups() {
    return fetchJson("data/index.json").then(function (data) {
      // The gallery's own run logs may point at outputs elsewhere in the site; a run log from
      // anywhere else may not (DA.outputs follows only pointers that stay beside the log).
      return (data.groups || []).map(function (g) {
        return Object.assign({}, g, { runs: (g.runs || []).map(function (r) { return Object.assign({}, r, { bundled: true }); }) });
      });
    }, function () {
      return [{
        id: "paper", title: "GSM8K case study, Qwen2.5-1.5B-Instruct", source: "measured", note: null,
        "default": "gsm8k-qwen2.5-1.5b-seed5",
        runs: [1, 2, 3, 4, 5].map(function (n) {
          return {
            id: "gsm8k-qwen2.5-1.5b-seed" + n, label: "Seed " + n,
            url: "toolkit/runs/run_seed" + n + "_hf_Qwen2.5-1.5B-Instruct_n200_r11.json"
          };
        })
      }];
    });
  }

  function ensure(entry) {
    if (entry.run) return Promise.resolve(entry);
    if (!entry.loading) {
      entry.loading = fetchJson(entry.url).then(function (raw) {
        entry.run = DA.schema.load(raw);
        return entry;
      });
    }
    return entry.loading;
  }

  function touch() {
    DA.state.set({ library: { groups: DA.state.get().library.groups.slice() } });
  }

  /* Audit and study ------------------------------------------------------------------ */

  // "As run" replays the loop's own decisions against the references it recorded. When every
  // candidate was compared with its own incumbent, in the same environment and pass, those
  // decisions match the ground-truth check by construction, so listing them beside the real
  // policies would only make them look like the best one.
  function trivialAsRun(block) {
    if (!block || block.available === false || !block.decisions || !block.decisions.length) return false;
    return block.decisions.every(function (d) {
      return d.ref_prompt === d.incumbent && d.ref_env === d.env && d.ref_pass === "current";
    });
  }

  function runTrivial(run) {
    var out;
    if (asRunOf && asRunOf.has(run)) return asRunOf.get(run);
    try {
      out = trivialAsRun(DA.engine.audit(run, { policies: ["as_run"] }).policies.as_run);
    } catch (err) {
      out = false;
    }
    if (asRunOf) asRunOf.set(run, out);
    return out;
  }

  // True when the policies of an audit or a study should leave "As run" out.
  function hidesAsRun(policies) {
    if (!policies || !policies.as_run) return false;
    if (policies.as_run.decisions) return trivialAsRun(policies.as_run);
    return !!hidden && hidden.get(policies) === true;
  }

  function offersAsRun(policies) {
    return !!policies && !!policies.as_run && policies.as_run.available !== false && !hidesAsRun(policies);
  }

  function engineOptions(options) {
    var out = {};
    Object.keys(options || {}).forEach(function (key) {
      if (options[key] !== null && options[key] !== undefined) out[key] = options[key];
    });
    return out;
  }

  // Registered with DA.state.derive: keeps audit and study in step with the selection,
  // the policy and the options, inside the same update.
  // Why the runs of a group cannot be pooled, as DA.engine.compatibility gives it: an empty
  // list when they can, null while some are still loading.
  var pools = typeof WeakMap === "function" ? new WeakMap() : null;
  function poolProblems(group) {
    var runs = group.runs.map(function (r) { return r.run; }), memoed;
    if (!runs.every(Boolean)) return null;
    memoed = pools && pools.get(group);
    if (memoed && memoed.runs.length === runs.length && memoed.runs.every(function (r, i) { return r === runs[i]; })) return memoed.result;
    memoed = { runs: runs, result: runs.length < 2 ? [] : DA.engine.compatibility(runs, group.runs.map(function (r) { return r.label; })) };
    if (pools) pools.set(group, memoed);
    return memoed.result;
  }

  function defaultRun(group) {
    return group["default"] && find(group.runs, group["default"]) ? group["default"] : group.runs[0].id;
  }

  function recompute(next, previous) {
    var group, entry, runs, options, key, out, runId, problems;
    if (next.selection === previous.selection && next.policy === previous.policy &&
        next.options === previous.options && next.library === previous.library) return null;
    out = { audit: null, study: null };
    group = find(next.library.groups, next.selection.group);
    if (!group) return out;
    options = engineOptions(next.options);
    key = JSON.stringify(options);
    runs = group.runs.map(function (r) { return r.run; });
    try {
      problems = poolProblems(group);
      runId = next.selection.run;
      // A pool the engine says should not be pooled falls back to one run.
      if (runId === "*" && problems && problems.length) {
        runId = defaultRun(group);
        out.selection = { group: group.id, run: runId };
      }
      if (runId !== "*") {
        entry = find(group.runs, runId);
        if (entry && entry.run) {
          if (!memo.audit || memo.audit.run !== entry.run || memo.audit.key !== key) {
            memo.audit = { run: entry.run, key: key, result: DA.engine.audit(entry.run, options) };
          }
          out.audit = memo.audit.result;
        }
      }
      if (runs.length >= 2 && problems && !problems.length) {
        if (!memo.study || memo.study.key !== key || memo.study.runs.length !== runs.length ||
            memo.study.runs.some(function (r, i) { return r !== runs[i]; })) {
          memo.study = { runs: runs, key: key, result: DA.engine.study(runs, options) };
        }
        out.study = memo.study.result;
        if (hidden && !hidden.has(out.study.policies)) hidden.set(out.study.policies, runs.every(runTrivial));
      }
    } catch (err) {
      out.error = { title: "The audit stopped on this run log", message: (err && err.message) || String(err) };
    }
    return Object.assign(out, policyFor(Object.assign({}, next, out.selection ? { selection: out.selection } : {}), out));
  }

  // A run with real recorded references opens on "As run"; a trivial one never shows it.
  function policyFor(next, out) {
    var policies = next.selection.run === "*" ? out.study && out.study.policies : out.audit && out.audit.policies;
    var runs = next.selection.run === "*" ? out.study && memo.study.runs : out.audit && [memo.audit.run], fresh;
    if (!policies) return null;
    fresh = !lastRuns || lastRuns.length !== runs.length || lastRuns.some(function (r, i) { return r !== runs[i]; });
    lastRuns = runs;
    if (fresh && offersAsRun(policies)) return { policy: "as_run" };
    if (next.policy === "as_run" && !offersAsRun(policies)) return { policy: "frozen" };
    return null;
  }

  function select(groupId, runId) {
    var state = DA.state.get(), group = find(state.library.groups, groupId), wanted;
    if (!group || !group.runs.length) return Promise.resolve();
    if (runId !== "*" && !find(group.runs, runId)) runId = defaultRun(group);
    wanted = runId === "*" ? group.runs : [find(group.runs, runId)];
    DA.state.set({ selection: { group: groupId, run: runId }, round: null, error: null });
    return Promise.all(wanted.map(ensure)).then(function () {
      touch();
      // The rest of the group is read afterwards, so the first audit is not kept waiting.
      return Promise.all(group.runs.map(ensure)).then(touch, function () {});
    }, function (err) {
      var message = (err && err.message) || String(err);
      fail("This run could not be loaded", err instanceof DA.schema.RunError ? message
        : message + ". If you opened the page from a file, serve the folder instead, for example with python3 -m http.server.");
    });
  }

  /* Files opened by the user --------------------------------------------------------- */

  function readFile(file) {
    if (file.text) return file.text();
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result)); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsText(file);
    });
  }

  var MAX_DEPTH = 64;

  // How deep the brackets of a JSON text nest, outside strings, stopping once past the limit.
  function depth(text) {
    var deepest = 0, level = 0, inString = false, i, c;
    for (i = 0; i < text.length; i++) {
      c = text.charCodeAt(i);
      if (inString) {
        if (c === 92) i++;
        else if (c === 34) inString = false;
      } else if (c === 34) {
        inString = true;
      } else if (c === 91 || c === 123) {
        level++;
        if (level > deepest && (deepest = level) > MAX_DEPTH) return deepest;
      } else if (c === 93 || c === 125) {
        level--;
      }
    }
    return deepest;
  }

  function sentence(text) {
    text = String(text || "").trim();
    if (!text) return "";
    text = text.charAt(0).toUpperCase() + text.slice(1);
    return /[.?]$/.test(text) ? text : text + ".";
  }

  // Why a file is not a run log, in words fit for the error notice.
  function whyNot(text, err) {
    var obj;
    try {
      obj = JSON.parse(text);
    } catch (parseError) {
      return "It is not valid JSON (" + parseError.message + "). A run log is one JSON object, written by driftaudit run, driftaudit convert or the Recorder.";
    }
    if (!obj || typeof obj !== "object" || Array.isArray(obj) || (!("schema" in obj) && !("candidates" in obj))) {
      return "It is JSON, but not a run log: a run log has a \"schema\" field, driftaudit.run/v1, or is a toolkit run file with its candidates and snapshots.";
    }
    return err instanceof DA.schema.RunError ? sentence(err.message) : "The audit could not read it: " + sentence((err && err.message) || String(err));
  }

  // Run logs go into the group "Your runs". They live in this page's memory and nowhere else.
  function openFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    var logs = files.filter(function (f) { return /\.json$/i.test(f.name); });
    var sides = files.filter(function (f) { return /\.outputs\.jsonl(\.gz)?$/i.test(f.name); });
    if (!logs.length) {
      fail("No run log among those files", "A run log is a .json file written by driftaudit run, driftaudit convert or the Recorder. The run you had open is unchanged.");
      return Promise.resolve();
    }
    return Promise.all(logs.map(function (file) {
      return readFile(file).then(function (text) {
        if (depth(text) > MAX_DEPTH) {
          return { name: file.name, error: "It nests JSON more than " + MAX_DEPTH + " levels deep. A run log needs fewer than ten, so the file was not read." };
        }
        try {
          return { name: file.name, run: DA.schema.load(text) };
        } catch (err) {
          return { name: file.name, error: whyNot(text, err) };
        }
      }, function () {
        return { name: file.name, error: "The browser could not read the file." };
      });
    })).then(function (results) {
      var good = results.filter(function (r) { return r.run; }), bad = results.filter(function (r) { return r.error; });
      var state = DA.state.get(), groups = state.library.groups.slice(), group = find(groups, YOURS), firstId = null;
      if (good.length) {
        group = group ? Object.assign({}, group, { runs: group.runs.slice() }) : {
          id: YOURS, title: "Your runs", source: null, runs: [],
          note: "Opened from your computer. They stay in this browser tab until you close or reload it, and nothing is uploaded."
        };
        good.forEach(function (r) {
          var base = r.name.replace(/\.json$/i, ""), old = null, side;
          group.runs.forEach(function (e) { if (e.file === r.name) old = e; });
          var entry = { id: old ? old.id : base, label: r.name, run: r.run, file: r.name }, n = 2;
          while (!old && find(group.runs, entry.id)) entry.id = base + " (" + n++ + ")";
          if (old) group.runs[group.runs.indexOf(old)] = entry;
          else group.runs.push(entry);
          side = sides.filter(function (s) { return s.name.indexOf(base + ".outputs.jsonl") === 0; })[0];
          if (side) sidecars[entry.id] = side;
          if (firstId === null) firstId = entry.id;
        });
        groups = [group].concat(groups.filter(function (g) { return g.id !== YOURS; }));
        DA.state.set({ library: { groups: groups } });
        select(YOURS, firstId);
        ui.toast(good.length === 1 ? "Opened " + good[0].name + "." : "Opened " + good.length + " run logs.");
      }
      if (bad.length) {
        fail(bad.length === 1 ? bad[0].name + " is not a run log this page can read" : bad.length + " files are not run logs this page can read",
          bad.map(function (b) { return bad.length === 1 ? b.error : b.name + ": " + b.error; }).join(" ") +
          (good.length ? "" : " The run you had open is unchanged."));
      }
    });
  }

  function hasFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return !!types && Array.prototype.indexOf.call(types, "Files") >= 0;
  }

  function overlay(on) {
    var el = document.getElementById("da-drop");
    if (el) el.classList.toggle("is-active", on);
  }

  function watchDrops() {
    root.addEventListener("dragenter", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth++;
      overlay(true);
    });
    root.addEventListener("dragover", function (event) {
      if (hasFiles(event)) event.preventDefault();
    });
    root.addEventListener("dragleave", function (event) {
      if (!hasFiles(event)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) overlay(false);
    });
    root.addEventListener("drop", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth = 0;
      overlay(false);
      openFiles(event.dataTransfer.files);
    });
  }

  /* Run bar: picker and facts -------------------------------------------------------- */

  function picker(state) {
    var groups = state.library.groups, group = find(groups, state.selection.group), options, problems;
    if (!group) return html``;
    options = group.runs.map(function (r) { return { value: r.id, label: r.label + (r.run && r.run.source === "synthetic" ? " (synthetic)" : "") }; });
    problems = poolProblems(group);
    if (group.runs.length >= 2) options.push({ value: "*", label: "All " + group.runs.length + " runs", disabled: !!(problems && problems.length) });
    return html`<div class="picker">
      ${groups.length > 1 ? ui.select({ name: "group", label: "Run set", key: "pick-group", value: group.id, options: groups.map(function (g) { return { value: g.id, label: g.title }; }) }) : ""}
      ${ui.select({ name: "run", label: "Run", key: "pick-run", value: state.selection.run, options: options })}
      <button type="button" class="btn" data-open-run data-key="open-run">Open run log</button>
      ${problems && problems.length ? html`<p class="picker__pool" data-pool-problem>All ${group.runs.length} runs cannot be pooled. ${problems[0]}.</p>` : ""}
      <p class="picker__hint">DriftAudit replays a self-improving loop's decisions against stored and rerun references. Pick a run, open your own, or drop a run log anywhere on this page; nothing is uploaded.</p>
    </div>`;
  }

  function same(runs, pick) {
    var first = pick(runs[0]);
    return runs.every(function (r) { return pick(r) === first; }) ? first : null;
  }

  // The note a bundled group carries in data/index.json, shown under the run picker.
  function groupNote(group) {
    return typeof group.note === "string" && group.note ? html`<p class="facts__note">${group.note}</p>` : "";
  }

  // One line that says what is being audited, with the measured or synthetic tag.
  function facts(state) {
    var group = find(state.library.groups, state.selection.group), runs, model, task, n, sources, synthetic, entry;
    if (!group) return html``;
    if (state.selection.run !== "*") {
      entry = find(group.runs, state.selection.run);
      if (!entry || !entry.run) return html`<p class="facts">${group.title}</p>`;
      return html`<p class="facts"><span class="facts__name">${entry.run.id || entry.label}</span> ${ui.sourceTag(entry.run.source)}
        <span class="facts__detail">${entry.run.model && entry.run.model.id ? entry.run.model.id + " on " : ""}${(entry.run.task && entry.run.task.name) || "unnamed task"}, ${fmt.plural(entry.run.task.n_items, "item")}, ${fmt.plural(entry.run.candidates.length, "round")}.${group.id === YOURS ? " Held in this tab's memory only." : ""}</span></p>${groupNote(group)}`;
    }
    runs = group.runs.map(function (r) { return r.run; }).filter(Boolean);
    if (runs.length < group.runs.length) return html`<p class="facts">${group.title}</p>${groupNote(group)}`;
    model = same(runs, function (r) { return r.model && r.model.id; });
    task = same(runs, function (r) { return r.task && r.task.name; });
    n = same(runs, function (r) { return r.task.n_items; });
    sources = DA.engine.studySource(runs.map(function (r) { return r.source; }));
    synthetic = runs.filter(function (r) { return r.source === "synthetic"; }).length;
    return html`<p class="facts"><span class="facts__title">${group.title}, ${sources === "mixed"
        ? fmt.plural(runs.length, "run") + ", " + synthetic + " of them synthetic"
        : runs.length + fmt.NBSP + (sources === "synthetic" ? "simulated runs" : "measured runs")}</span> ${sources === "mixed" ? ui.tag("mixed", "warning") : ui.sourceTag(sources)}
      <span class="facts__detail">${model ? model + " on " : ""}${task || "several tasks"}${n ? ", " + fmt.plural(n, "item") + " each" : ""}.${group.id === YOURS ? " Held in this tab's memory only." : ""}</span></p>${groupNote(group)}`;
  }

  function bind(rootEl) {
    if (rootEl.daLibrary) return;
    rootEl.daLibrary = true;
    rootEl.addEventListener("change", function (event) {
      var el = event.target, state = DA.state.get(), group;
      if (el.name === "group") {
        group = find(state.library.groups, el.value);
        if (group) select(group.id, group["default"] || group.runs[0].id);
      } else if (el.name === "run") {
        select(state.selection.group, el.value);
      }
    });
    rootEl.addEventListener("click", function (event) {
      if (!event.target.closest || !event.target.closest("[data-open-run]")) return;
      if (!fileInput) {
        fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.multiple = true;
        fileInput.accept = ".json,.jsonl,.gz,application/json";
        fileInput.hidden = true;
        fileInput.addEventListener("change", function () {
          openFiles(fileInput.files);
          fileInput.value = "";
        });
        document.body.appendChild(fileInput);
      }
      fileInput.click();
    });
  }

  function boot() {
    var start;
    DA.state.derive(recompute);
    watchDrops();
    try {
      start = embeddedGroup();
    } catch (err) {
      fail("The runs embedded in this report could not be read", (err && err.message) || String(err));
      return Promise.resolve();
    }
    return (start ? Promise.resolve([start]) : Promise.all([
      sessionGroup().catch(function (err) {
        fail("The session's run list could not be loaded", (err && err.message) || String(err));
        return null;
      }),
      bundledGroups()
    ]).then(function (parts) {
      return (parts[0] && parts[0].runs.length ? [parts[0]] : []).concat(parts[1]);
    })).then(function (list) {
      var usable = list.filter(function (g) { return g.runs && g.runs.length; });
      // A session comes first; otherwise the paper's runs open, wherever the index lists them.
      var first = usable[0] && usable[0].id === "session" ? usable[0] : find(usable, "paper") || usable[0];
      DA.state.set({ library: { groups: list } });
      if (!first) {
        fail("No runs to show", "The gallery is empty. Open a run log from your computer to audit it.");
        return null;
      }
      return select(first.id, first["default"] || first.runs[0].id);
    });
  }

  function current() {
    var state = DA.state.get(), group = find(state.library.groups, state.selection.group);
    var entry = group && state.selection.run !== "*" ? find(group.runs, state.selection.run) : null;
    return { group: group, entry: entry, run: entry ? entry.run || null : null };
  }

  DA.library = {
    boot: boot, select: select, trivialAsRun: trivialAsRun, hidesAsRun: hidesAsRun, offersAsRun: offersAsRun, openFiles: openFiles, picker: picker, facts: facts, bind: bind,
    // The loaded run log of the selection, or null while it loads or when all runs are selected.
    run: function () { return current().run; },
    // Every loaded run log of the selected group.
    runs: function () {
      var group = current().group;
      return group ? group.runs.map(function (r) { return r.run; }).filter(Boolean) : [];
    },
    group: function () { return current().group; },
    // The selected run's entry in the group: { id, label, url, note, run }, or null.
    entry: function () { return current().entry; },
    poolProblems: poolProblems,
    // The outputs file dropped beside a run log, for DA.outputs. A File, or null.
    sidecar: function (runId) { return sidecars[runId] || null; }
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
