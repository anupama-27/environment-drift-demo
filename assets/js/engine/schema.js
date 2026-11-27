(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  // Run log v1, as src/driftaudit/schema.py reads it: validate, upgrade the files the paper's
  // toolkit wrote, and hand back labels as strings of 0 and 1. Problems are worded as the
  // Python package words them, so a file fails with the same message in the CLI and here.

  var SCHEMA = "driftaudit.run/v1";
  var VERSION = "0.1.0";
  var PASSES = ["current", "rerun"];
  var SOURCES = ["measured", "synthetic"];
  var LEGACY_KEYS = ["correct", "config", "snapshots", "candidates"];
  var SHOWN_PROBLEMS = 5;
  var has = Object.prototype.hasOwnProperty;

  // Runs that load() returned; loading one again hands it back without rechecking it.
  var loaded = new WeakSet();

  function RunError(message, problems) {
    this.name = "RunError";
    this.message = message;
    this.problems = problems ? problems.slice() : [];
    if (Error.captureStackTrace) Error.captureStackTrace(this, RunError);
  }
  RunError.prototype = Object.create(Error.prototype);
  RunError.prototype.constructor = RunError;

  function isObject(x) {
    return x !== null && typeof x === "object" && !Array.isArray(x);
  }

  function isCount(x, minimum) {
    return typeof x === "number" && Number.isInteger(x) && x >= (minimum || 0);
  }

  function owns(obj, key) {
    return typeof key === "string" && has.call(obj, key);
  }

  function get(obj, key) {
    return has.call(obj, key) && obj[key] !== undefined ? obj[key] : null;
  }

  // Run logs are untrusted: an id spelled "__proto__" must become a key, not a prototype.
  function put(obj, key, value) {
    if (key === "__proto__") {
      Object.defineProperty(obj, key, { value: value, enumerable: true, writable: true, configurable: true });
    } else {
      obj[key] = value;
    }
  }

  // str() and repr() of a JSON value as Python prints them.
  function pyRepr(v) {
    var quote;
    if (v === null || v === undefined) return "None";
    if (typeof v === "boolean") return v ? "True" : "False";
    if (typeof v === "number") return String(v);
    if (typeof v === "string") {
      quote = v.indexOf("'") >= 0 && v.indexOf("\"") < 0 ? "\"" : "'";
      return quote + v.replace(/[\\\x00-\x1f\x7f']/g, function (ch) {
        if (ch === "\\") return "\\\\";
        if (ch === "'") return quote === "'" ? "\\'" : ch;
        if (ch === "\n") return "\\n";
        if (ch === "\r") return "\\r";
        if (ch === "\t") return "\\t";
        return "\\x" + ("0" + ch.charCodeAt(0).toString(16)).slice(-2);
      }) + quote;
    }
    if (Array.isArray(v)) return "[" + v.map(pyRepr).join(", ") + "]";
    return "{" + Object.keys(v).map(function (k) { return pyRepr(k) + ": " + pyRepr(v[k]); }).join(", ") + "}";
  }

  function pyStr(v) {
    return typeof v === "string" ? v : pyRepr(v);
  }

  // Labels as a string of 0 and 1. Takes an array of 0/1 or booleans, or such a string.
  function encodeLabels(seq) {
    var out, i, v;
    if (typeof seq === "string") {
      if (!/^[01]*$/.test(seq)) throw new RunError("labels must contain only 0 and 1");
      return seq;
    }
    if (!Array.isArray(seq)) throw new RunError("labels must be a string of 0 and 1 (or an array of 0/1)");
    out = "";
    for (i = 0; i < seq.length; i++) {
      v = seq[i];
      if (v === 1 || v === true) out += "1";
      else if (v === 0 || v === false) out += "0";
      else throw new RunError("labels must contain only 0 and 1, found " + pyRepr(v));
    }
    return out;
  }

  function decodeLabels(s) {
    var out = new Array(s.length), i;
    for (i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) === 49 ? 1 : 0;
    return out;
  }

  // Labels of a prompt under an environment for one pass, or null when the bank lacks them.
  function labels(run, prompt, env, pass) {
    var bank = run.labels, perEnv, passes, value;
    pass = pass === undefined ? "current" : pass;
    if (!isObject(bank) || !owns(bank, prompt)) return null;
    perEnv = bank[prompt];
    if (!isObject(perEnv) || !owns(perEnv, env)) return null;
    passes = perEnv[env];
    if (!isObject(passes) || !owns(passes, pass)) return null;
    value = passes[pass];
    return value === undefined ? null : value;
  }

  // A run file written by toolkit/ before the v1 format existed.
  function isLegacy(obj) {
    return isObject(obj) && !has.call(obj, "schema") &&
      LEGACY_KEYS.every(function (k) { return has.call(obj, k); });
  }

  function isRun(obj) {
    if (!isObject(obj)) return false;
    return isLegacy(obj) || (typeof obj.schema === "string" && obj.schema.indexOf("driftaudit.run/") === 0);
  }

  function slug(text) {
    return pyStr(text).toLowerCase().replace(/[^a-z0-9.]+/g, "-").replace(/^-+|-+$/g, "");
  }

  function legacyId(config, seed) {
    var model = pyStr(has.call(config, "model") ? config.model : "").split("/").pop();
    var dataset = has.call(config, "dataset") ? config.dataset : "";
    var gsm8k = pyStr(dataset).toLowerCase().indexOf("gsm8k") >= 0;
    var mock = config.backend === "mock";
    if (model === "Qwen2.5-1.5B-Instruct" && gsm8k && !mock) return "gsm8k-qwen2.5-1.5b-seed" + pyStr(seed);
    // A mock run reuses the real model's name; its id must not pass for a measured run's.
    return [gsm8k ? "gsm8k" : slug(dataset), slug(model), mock ? "mock" : "", "seed" + pyStr(seed)]
      .filter(Boolean).join("-");
  }

  // E1-E4 as the paper defines them: greedy or sampled decoding, strict or lenient extractor.
  function paperEnvironments(modelId) {
    var rows = [["E1", "Unchanged", 0.0, "v1"], ["E2", "Decoding", 0.2, "v1"],
      ["E3", "Extraction", 0.0, "v2"], ["E4", "Combined", 0.2, "v2"]];
    var scorerNames = { v1: "strict numeric", v2: "lenient numeric" };
    var envs = {};
    rows.forEach(function (row) {
      var decoding = (row[2] === 0 ? "greedy" : "sample") + "-" + row[2].toFixed(1);
      envs[row[0]] = {
        name: row[1], decoding: decoding, scorer: row[3],
        fingerprint: "model=" + pyStr(modelId) + ";decode=" + decoding + ";extract=" + row[3],
        detail: { temperature: row[2], scorer_name: scorerNames[row[3]] }
      };
    });
    return envs;
  }

  function copy(obj) {
    var out = {};
    Object.keys(obj).forEach(function (k) { put(out, k, obj[k]); });
    return out;
  }

  function encodeBank(bank) {
    var out = {};
    Object.keys(bank).forEach(function (h) {
      var perEnv = {};
      if (!isObject(bank[h])) throw new RunError("labels of prompt " + h + " must map environments to passes");
      Object.keys(bank[h]).forEach(function (env) {
        var passes = {};
        if (!isObject(bank[h][env])) throw new RunError("labels of prompt " + h + " under " + env + " must map a pass to labels");
        Object.keys(bank[h][env]).forEach(function (tag) {
          put(passes, tag, encodeLabels(bank[h][env][tag]));
        });
        put(perEnv, env, passes);
      });
      put(out, h, perEnv);
    });
    return out;
  }

  // A toolkit run file as a v1 run log. The argument is left as it is.
  // The toolkit ran GSM8K under the paper's four environments and its gate compared each
  // candidate with the incumbent in the same pass, so those facts are filled in.
  function upgradeLegacy(legacy) {
    var config, seed, modelId, schedule = {};
    if (!isLegacy(legacy)) {
      throw new RunError("not a toolkit run file: expected the keys correct, config, snapshots and candidates");
    }
    config = legacy.config;
    if (!isObject(config)) throw new RunError("toolkit run file has no config object");
    ["n_eval", "schedule"].forEach(function (key) {
      if (!has.call(config, key)) throw new RunError("toolkit run file has no config." + key);
    });
    if (!has.call(legacy, "prompts")) throw new RunError("toolkit run file has no prompts");
    if (!isObject(config.schedule) || !isObject(legacy.prompts) || !isObject(legacy.correct) ||
        !Array.isArray(legacy.snapshots) || !Array.isArray(legacy.candidates)) {
      throw new RunError("config.schedule, prompts and correct must be objects, snapshots and candidates lists");
    }
    seed = get(legacy, "seed");
    modelId = has.call(config, "model") ? config.model : "";
    Object.keys(config.schedule).forEach(function (start) { schedule[start] = config.schedule[start]; });
    return {
      schema: SCHEMA,
      id: legacyId(config, seed),
      tool: { name: "driftaudit", version: VERSION },
      source: config.backend === "mock" ? "synthetic" : "measured",
      seed: seed,
      task: {
        name: "GSM8K", split: "test", n_items: config.n_eval, n_dev: get(config, "n_dev"),
        dataset: get(config, "dataset"), revision: get(config, "dataset_revision"), items: "gsm8k/eval200"
      },
      model: { id: modelId, revision: get(config, "model_revision"), backend: get(config, "backend") },
      environments: paperEnvironments(modelId),
      schedule: schedule,
      prompts: copy(legacy.prompts),
      snapshots: legacy.snapshots.map(copy),
      candidates: legacy.candidates.map(function (c) {
        c = copy(c);
        if (has.call(c, "parent") && has.call(c, "env")) c.reference = { prompt: c.parent, env: c.env, pass: "current" };
        return c;
      }),
      labels: encodeBank(legacy.correct),
      cost: { n_dev: get(config, "n_dev") || 0, proposal_calls: 1 },
      meta: { config: config, physical_calls: get(legacy, "physical_calls") }
    };
  }

  function labelProblem(value, nItems) {
    if (typeof value === "string") {
      if (!/^[01]*$/.test(value)) return "must contain only 0 and 1";
    } else if (Array.isArray(value)) {
      if (value.some(function (v) { return !(v === 0 || v === 1 || v === true || v === false); })) {
        return "must contain only 0 and 1";
      }
    } else {
      return "must be a string of 0 and 1 (or an array of 0/1)";
    }
    if (isCount(nItems) && value.length !== nItems) {
      return "has " + value.length + " labels, expected " + nItems + " (task.n_items)";
    }
    return null;
  }

  function checkCandidate(cand, i, ctx, problems) {
    var label, round, ref;
    if (!isObject(cand)) {
      problems.push("candidates[" + i + "] must be an object");
      return;
    }
    label = "candidate " + pyRepr(has.call(cand, "id") ? cand.id : i);
    if (typeof cand.id !== "string" || !cand.id) {
      problems.push("candidates[" + i + "].id must be a non-empty string");
    } else if (ctx.seen.indexOf(cand.id) >= 0) {
      problems.push("candidate id " + pyRepr(cand.id) + " is used more than once");
    }
    ctx.seen.push(cand.id);
    round = get(cand, "round");
    if (!isCount(round) || round >= ctx.snapshots.length) {
      problems.push(label + " is in round " + pyStr(round) + ", but snapshots cover rounds 0 to " + (ctx.snapshots.length - 1));
    } else if (round < ctx.lastRound) {
      problems.push(label + " is out of order: candidates are listed by round");
    } else {
      ctx.lastRound = round;
    }
    ["prompt", "parent"].forEach(function (key) {
      if ((key === "prompt" || has.call(cand, key)) && !owns(ctx.prompts, cand[key])) {
        problems.push(label + " names " + key + " " + pyRepr(get(cand, key)) + ", which is not in prompts");
      }
    });
    if (has.call(cand, "env") && !owns(ctx.envs, cand.env)) {
      problems.push(label + " names environment " + pyRepr(cand.env) + ", which environments does not define");
    }
    if (has.call(cand, "accepted") && typeof cand.accepted !== "boolean") {
      problems.push(label + ": accepted must be true or false");
    }
    ["wins", "losses"].forEach(function (key) {
      if (has.call(cand, key) && !isCount(cand[key])) problems.push(label + ": " + key + " must be a non-negative integer");
    });
    if (has.call(cand, "reference")) {
      ref = cand.reference;
      if (!isObject(ref) || !owns(ctx.prompts, ref.prompt) || !owns(ctx.envs, ref.env)) {
        problems.push(label + ": reference must name a prompt in prompts and an environment in environments");
      } else if (PASSES.indexOf(ref.pass) < 0) {
        problems.push(label + ": reference pass must be \"current\" or \"rerun\"");
      }
    }
  }

  function checkBank(bank, ctx, problems) {
    Object.keys(bank).forEach(function (h) {
      var perEnv = bank[h];
      if (!owns(ctx.prompts, h)) problems.push("labels has prompt " + pyRepr(h) + ", which is not in prompts");
      if (!isObject(perEnv)) {
        problems.push("labels." + h + " must map environments to passes");
        return;
      }
      Object.keys(perEnv).forEach(function (envId) {
        var passes = perEnv[envId];
        if (!owns(ctx.envs, envId)) {
          problems.push("labels." + h + " has environment " + pyRepr(envId) + ", which environments does not define");
        }
        if (!isObject(passes)) {
          problems.push("labels." + h + "." + envId + " must map a pass to a label string");
          return;
        }
        Object.keys(passes).forEach(function (tag) {
          var problem;
          if (PASSES.indexOf(tag) < 0) {
            problems.push("labels." + h + "." + envId + " has pass " + pyRepr(tag) + "; passes are \"current\" and \"rerun\"");
            return;
          }
          problem = labelProblem(passes[tag], ctx.nItems);
          if (problem) problems.push("labels." + h + "." + envId + "." + tag + " " + problem);
        });
      });
    });
  }

  // Everything that stops an object from being a v1 run log; empty when it is one.
  function problemsOf(run) {
    var problems = [], found, task, nItems, envs, schedule, prompts, snapshots, candidates, bank, cost, ctx;
    if (!isObject(run)) return ["a run log is a JSON object"];

    found = get(run, "schema");
    if (found === null) {
      problems.push("missing \"schema\": expected \"" + SCHEMA + "\" (or a toolkit run file with correct, config, " +
        "snapshots and candidates)");
    } else if (found !== SCHEMA) {
      problems.push("schema is \"" + pyStr(found) + "\", but this version of driftaudit reads \"" + SCHEMA + "\"; " +
        "a newer file needs a newer driftaudit");
    }
    if (typeof run.id !== "string" || !run.id) problems.push("id must be a non-empty string");
    if (SOURCES.indexOf(run.source) < 0) {
      problems.push("source must be \"measured\" or \"synthetic\" (synthetic for anything a mock backend produced)");
    }

    task = get(run, "task");
    nItems = isObject(task) ? get(task, "n_items") : null;
    if (!isCount(nItems, 1)) {
      problems.push("task.n_items must be a positive integer: the number of evaluation items per label string");
    }
    if (has.call(run, "model") && !isObject(run.model)) problems.push("model must be an object such as {\"id\": \"my-model\"}");

    envs = get(run, "environments");
    if (!isObject(envs) || !Object.keys(envs).length) {
      problems.push("environments must define at least one environment");
      envs = {};
    }
    Object.keys(envs).forEach(function (envId) {
      ["decoding", "scorer", "fingerprint"].forEach(function (key) {
        if (!isObject(envs[envId]) || typeof envs[envId][key] !== "string") {
          problems.push("environments." + envId + "." + key + " must be a string");
        }
      });
    });

    schedule = get(run, "schedule");
    if (!isObject(schedule) || !Object.keys(schedule).length) {
      problems.push("schedule must map a start round to an environment, for example {\"0\": \"E1\"}");
      schedule = {};
    }
    Object.keys(schedule).forEach(function (start) {
      if (!/^[0-9]+$/.test(start)) problems.push("schedule round " + pyRepr(start) + " must be a non-negative integer");
      if (!owns(envs, schedule[start])) {
        problems.push("schedule sends round " + start + " to environment " + pyRepr(schedule[start]) +
          ", which environments does not define");
      }
    });

    prompts = get(run, "prompts");
    if (!isObject(prompts) || !Object.keys(prompts).every(function (h) { return typeof prompts[h] === "string"; })) {
      problems.push("prompts must map each prompt id to its text");
      prompts = isObject(prompts) ? prompts : {};
    }

    snapshots = get(run, "snapshots");
    if (!Array.isArray(snapshots)) {
      problems.push("snapshots must be a list with the incumbent at the start of each round");
      snapshots = [];
    }
    snapshots.forEach(function (snap, i) {
      if (!isObject(snap) || snap.round !== i) {
        problems.push("snapshots[" + i + "] must be the snapshot of round " + i + "; snapshots are listed one per round, " +
          "in order");
      } else if (!owns(prompts, snap.prompt)) {
        problems.push("snapshots[" + i + "] names prompt " + pyRepr(get(snap, "prompt")) + ", which is not in prompts");
      } else if (has.call(snap, "env") && !owns(envs, snap.env)) {
        problems.push("snapshots[" + i + "] names environment " + pyRepr(snap.env) + ", which environments does not define");
      }
    });

    candidates = get(run, "candidates");
    if (!Array.isArray(candidates)) {
      problems.push("candidates must be a list");
      candidates = [];
    }
    ctx = { prompts: prompts, envs: envs, snapshots: snapshots, nItems: nItems, seen: [], lastRound: 0 };
    candidates.forEach(function (cand, i) { checkCandidate(cand, i, ctx, problems); });

    bank = get(run, "labels");
    if (!isObject(bank)) {
      problems.push("labels must map prompt id, environment and pass to a label string");
      bank = {};
    }
    checkBank(bank, ctx, problems);

    cost = has.call(run, "cost") ? run.cost : {};
    if (!isObject(cost)) {
      problems.push("cost must be an object");
    } else {
      ["n_dev", "proposal_calls"].forEach(function (key) {
        if (has.call(cost, key) && !isCount(cost[key])) problems.push("cost." + key + " must be a non-negative integer");
      });
    }
    return problems;
  }

  function upgraded(obj) {
    try {
      return { run: upgradeLegacy(obj), problems: null };
    } catch (err) {
      return { run: null, problems: ["toolkit run file cannot be upgraded: " + err.message] };
    }
  }

  // A toolkit run file is checked in the form it would load as.
  function validate(obj) {
    var up;
    if (!isLegacy(obj)) return problemsOf(obj);
    up = upgraded(obj);
    return up.problems || problemsOf(up.run);
  }

  // Shallow copy with labels as strings and schedule rounds as strings.
  function normalized(run) {
    var out = copy(run), schedule = {};
    Object.keys(run.schedule).forEach(function (start) { schedule[String(parseInt(start, 10))] = run.schedule[start]; });
    out.schedule = schedule;
    out.labels = encodeBank(run.labels);
    return out;
  }

  // Return a valid v1 run from a parsed run log (v1 or a toolkit file) or from its JSON text.
  // name is how messages refer to the file. The argument is not modified.
  function load(obj, name) {
    var what = name || "this object", up, run, problems;
    if (typeof obj === "string") {
      try {
        obj = JSON.parse(obj);
      } catch (err) {
        throw new RunError(what + ": not valid JSON (" + err.message + "); a run log is one JSON object");
      }
    }
    if (isObject(obj) && loaded.has(obj)) return obj;
    if (isLegacy(obj)) {
      up = upgraded(obj);
      run = up.run;
      problems = up.problems || problemsOf(run);
    } else {
      run = obj;
      problems = problemsOf(run);
    }
    if (problems.length) {
      throw new RunError(what + " is not a valid run log:" +
        problems.slice(0, SHOWN_PROBLEMS).map(function (p) { return "\n  - " + p; }).join("") +
        (problems.length > SHOWN_PROBLEMS ? "\n  (and " + (problems.length - SHOWN_PROBLEMS) + " more)" : ""), problems);
    }
    run = normalized(run);
    loaded.add(run);
    return run;
  }

  // Short name of a prompt for display: p0 for the first prompt of the log (the starting
  // prompt), p1 for the next, as in the case study's replay files. An unknown id is returned as is.
  function promptLabel(run, promptId) {
    var index = run && isObject(run.prompts) ? Object.keys(run.prompts).indexOf(promptId) : -1;
    return index < 0 ? promptId : "p" + index;
  }

  DA.schema = {
    SCHEMA: SCHEMA,
    VERSION: VERSION,
    PASSES: PASSES,
    RunError: RunError,
    load: load,
    validate: validate,
    isRun: isRun,
    isLegacy: isLegacy,
    upgradeLegacy: upgradeLegacy,
    labels: labels,
    promptLabel: promptLabel,
    encodeLabels: encodeLabels,
    decodeLabels: decodeLabels,
    repr: pyRepr
  };

  if (typeof module === "object" && module.exports) module.exports = DA;
})(typeof globalThis !== "undefined" ? globalThis : this);
