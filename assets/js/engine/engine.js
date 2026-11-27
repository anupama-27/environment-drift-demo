(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  // Replay refresh policies on a recorded run and measure what a stale reference cost.
  //
  // This file follows src/driftaudit/engine.py function for function and adds in the same
  // order, so both engines return the same numbers. Nothing here calls a model: every policy
  // chooses among the same recorded candidates and reads the same label bank.
  //
  // Fractions stay fractions (an inflation of 0.015 is 1.5 pp); only delta_pp is in
  // percentage points. Results are unrounded plain JSON, and an undefined value is null.

  var AUDIT_SCHEMA = "driftaudit.audit/v1";
  var STUDY_SCHEMA = "driftaudit.study/v1";

  // Ids are stable API; names are what the paper and the workbench show.
  var POLICIES = {
    frozen: { name: "Frozen", rule: "Never refresh; compare with the reference stored at round 0" },
    stored_incumbent: {
      name: "Stored incumbent",
      rule: "Never refresh; compare with the outputs stored when the incumbent was accepted"
    },
    per_batch: { name: "Per-batch", rule: "Refresh every batch" },
    env_triggered: { name: "Environment-triggered", rule: "Refresh after detected environment changes" },
    periodic: { name: "Every k rounds", rule: "Refresh once the reference is k rounds old" },
    as_run: { name: "As run", rule: "The decisions the loop recorded, against the reference it recorded" }
  };
  var POLICY_IDS = Object.keys(POLICIES);
  var CAUSES = ["stale", "anyway", "no_drift"];
  var DEFAULT_AGES = [0, 1, 3, 5, 10];
  var MISSING_SHOWN = 20;
  var TOTALS = ["accepted", "false_accepts", "false_rejects", "false_accept_rate", "refreshes", "calls", "total_calls",
    "final_acc", "final_prompt", "inflation", "causes"];
  var ONE = 49;
  var has = Object.prototype.hasOwnProperty;

  function tool() {
    return { name: "driftaudit", version: DA.schema.VERSION };
  }

  // An environment id from a run log may be spelled "__proto__"; it must become a key.
  function put(obj, key, value) {
    if (key === "__proto__") {
      Object.defineProperty(obj, key, { value: value, enumerable: true, writable: true, configurable: true });
    } else {
      obj[key] = value;
    }
  }

  function given(value) {
    return value !== undefined && value !== null;
  }

  // Order of Python's sorted() on strings: by code point, where JS compares UTF-16 units.
  function byCodePoint(a, b) {
    var i = 0, x, y;
    while (i < a.length && i < b.length) {
      x = a.codePointAt(i);
      y = b.codePointAt(i);
      if (x !== y) return x - y;
      i += x > 0xffff ? 2 : 1;
    }
    return a.length - b.length;
  }

  function ones(labels) {
    var k = 0, i;
    for (i = 0; i < labels.length; i++) if (labels.charCodeAt(i) === ONE) k++;
    return k;
  }

  // Wins, losses, both right and both wrong of a candidate against a reference, item by item.
  function pair(cand, ref) {
    var n = Math.min(cand.length, ref.length), wins = 0, losses = 0, both = 0, i;
    for (i = 0; i < n; i++) {
      if (cand.charCodeAt(i) === ONE) {
        if (ref.charCodeAt(i) === ONE) both++;
        else wins++;
      } else if (ref.charCodeAt(i) === ONE) {
        losses++;
      }
    }
    return { wins: wins, losses: losses, both_right: both, both_wrong: cand.length - wins - losses - both };
  }

  // A false accept is a gain "no greater than" zero, so the comparison is strict.
  function outcome(deltaPp) {
    if (deltaPp > 0) return "improved";
    return deltaPp === 0 ? "no change" : "worse";
  }

  function sortedStarts(schedule) {
    return Object.keys(schedule).map(function (start) {
      return [parseInt(start, 10), schedule[start]];
    }).sort(function (a, b) { return a[0] - b[0] || byCodePoint(a[1], b[1]); });
  }

  // Environment in force at a round. A round before the first start gets the first entry.
  function envAt(round, starts) {
    var current = starts[0][1], i;
    for (i = 0; i < starts.length; i++) if (round >= starts[i][0]) current = starts[i][1];
    return current;
  }

  // One run's label bank, read under the options of an audit.
  function Bank(run, schedule, storedScoring, margin) {
    this.run = run;
    this.n = run.task.n_items;
    this.envs = run.environments;
    this.starts = sortedStarts(schedule);
    this.recorded = sortedStarts(run.schedule);
    this.rescore = storedScoring === "rescore";
    this.margin = margin;
    this.notes = [];
  }

  Bank.prototype.labels = function (prompt, env, pass) {
    return DA.schema.labels(this.run, prompt, env, pass);
  };

  // Accuracy of a prompt under an environment from its stored pass (the record).
  Bank.prototype.acc = function (prompt, env) {
    var lab = this.labels(prompt, env);
    return lab === null ? null : ones(lab) / this.n;
  };

  Bank.prototype.envAt = function (round) {
    return envAt(round, this.starts);
  };

  Bank.prototype.sameFingerprint = function (a, b) {
    return this.envs[a].fingerprint === this.envs[b].fingerprint;
  };

  // Environment whose labels are read for a reference stored under storedEnv.
  // As recorded, that is storedEnv itself: the labels are an anchor from when the outputs
  // were stored. Under rescore the stored text is kept and read with today's scorer, which
  // is the environment with the stored decoding and the current scorer.
  Bank.prototype.scoredEnv = function (storedEnv, currentEnv) {
    var stored, current, ids, i, env, note;
    if (!this.rescore) return storedEnv;
    stored = this.envs[storedEnv];
    current = this.envs[currentEnv];
    if (stored.scorer === current.scorer) return storedEnv;
    ids = Object.keys(this.envs).sort(byCodePoint);
    for (i = 0; i < ids.length; i++) {
      env = this.envs[ids[i]];
      if (env.decoding === stored.decoding && env.scorer === current.scorer) return ids[i];
    }
    note = "rescore: no environment has decoding " + stored.decoding + " with scorer " + current.scorer +
      "; labels stored under " + storedEnv + " are used as recorded";
    if (this.notes.indexOf(note) < 0) this.notes.push(note);
    return storedEnv;
  };

  // One decision record. accepted is passed in only when the loop recorded the verdict;
  // wins and losses are null when neither the bank nor the log has them.
  function decision(bank, k, env, cand, inc, ref, fresh, scoredEnv, cLab, incLab, wins, losses, accepted) {
    var n = bank.n, margin = bank.margin;
    var rerun, r, rerunWins = null, rerunLosses = null, rerunAccepts = null, inflation = null;
    var incAcc, candAcc, better, deltaPp, mismatch, falseAccept, cause = null;
    if (accepted === undefined) accepted = wins - losses > margin;
    // What the same rule would have seen had the reference been rerun under the current environment.
    rerun = bank.labels(ref.prompt, env, "rerun");
    if (rerun !== null) {
      r = pair(cLab, rerun);
      rerunWins = r.wins;
      rerunLosses = r.losses;
      rerunAccepts = rerunWins - rerunLosses > margin;
      if (wins !== null) inflation = (wins - rerunWins) / n;
    }
    incAcc = ones(incLab) / n;
    candAcc = ones(cLab) / n;
    better = candAcc > incAcc;
    deltaPp = 100 * (candAcc - incAcc);
    mismatch = !fresh && !bank.sameFingerprint(ref.env, env);
    falseAccept = accepted && !better;
    if (falseAccept) {
      if (!mismatch) cause = "no_drift";
      else if (rerunAccepts !== null) cause = rerunAccepts ? "anyway" : "stale";
    }
    return {
      round: k, env: env, candidate: cand, incumbent: inc,
      ref_prompt: ref.prompt, ref_env: ref.env, ref_pass: ref.pass, ref_scored_env: scoredEnv,
      ref_fresh: fresh, ref_round: ref.round, ref_age: k - ref.round, env_mismatch: mismatch,
      wins: wins, losses: losses, rerun_wins: rerunWins, rerun_losses: rerunLosses,
      inflation: inflation, accepted: accepted, rerun_accepts: rerunAccepts,
      inc_acc: incAcc, cand_acc: candAcc, delta_pp: deltaPp, outcome: outcome(deltaPp),
      false_accept: falseAccept, false_reject: better && !accepted, cause: cause
    };
  }

  function count(decisions, test) {
    var k = 0, i;
    for (i = 0; i < decisions.length; i++) if (test(decisions[i])) k++;
    return k;
  }

  // Missing labels in the order they were first needed, each listed once.
  function Missing() {
    this.seen = {};
    this.list = [];
  }

  Missing.prototype.add = function (prompt, env, pass) {
    var key = JSON.stringify([prompt, env, pass]);
    if (has.call(this.seen, key)) return;
    this.seen[key] = true;
    this.list.push({ prompt: prompt, env: env, pass: pass });
  };

  // A policy's result. With labels missing it carries what to record and no numbers.
  // missing is null when the policy cannot be replayed for another reason.
  function block(policy, missing, decisions, refreshes, calls, finalPrompt, finalAcc) {
    var list = missing === null ? [] : missing.list, inflation = [], causes = {}, accepted, falseAccepts, out;
    out = {
      id: policy, name: POLICIES[policy].name, rule: POLICIES[policy].rule,
      available: missing !== null && !list.length,
      missing: list.slice(0, MISSING_SHOWN),
      missing_count: list.length
    };
    if (!out.available) {
      TOTALS.forEach(function (key) { out[key] = null; });
      out.decisions = [];
      return out;
    }
    accepted = count(decisions, function (d) { return d.accepted; });
    falseAccepts = count(decisions, function (d) { return d.false_accept; });
    decisions.forEach(function (d) {
      if (d.inflation !== null) inflation.push(d.inflation);
    });
    CAUSES.forEach(function (cause) {
      causes[cause] = count(decisions, function (d) { return d.cause === cause; });
    });
    out.accepted = accepted;
    out.false_accepts = falseAccepts;
    out.false_rejects = count(decisions, function (d) { return d.false_reject; });
    out.false_accept_rate = accepted ? falseAccepts / accepted : null;
    out.refreshes = refreshes;
    out.calls = calls;
    out.total_calls = calls.proposer + calls.candidate_eval + calls.reference_refresh;
    out.final_acc = finalAcc;
    out.final_prompt = finalPrompt;
    out.inflation = DA.stats.mean(inflation);
    out.causes = causes;
    out.decisions = decisions;
    return out;
  }

  // Model calls a round costs before any refresh: the proposer's share and the candidate's evaluation.
  function callCosts(run) {
    var cost = run.cost || {}, nDev = given(cost.n_dev) ? cost.n_dev : (run.task.n_dev || 0);
    return { proposal: (has.call(cost, "proposal_calls") ? cost.proposal_calls : 1) + nDev, evaluation: run.task.n_items };
  }

  // Replay the candidate pool through a reference policy (dry run: nothing is regenerated).
  //
  //   frozen            compare against the outputs stored at round 0, never rerun.
  //   stored_incumbent  compare against the outputs recorded when the incumbent was accepted, never rerun.
  //   per_batch         rerun the incumbent under the current environment every round.
  //   env_triggered     rerun when the current fingerprint differs from the one recorded with the
  //                     reference; after an accept the candidate's own outputs become the reference
  //                     at no extra cost. The policy never consults the schedule.
  //   periodic          as stored_incumbent, with a rerun whenever the reference is periodicK rounds old.
  //   fixedAge          (ablation) always use the snapshot from round k - fixedAge, stored at its time.
  //
  // A rerun stays the reference in later rounds until something replaces it. When a round
  // needs labels the bank lacks, the round is passed over and the replay goes on, so that
  // the result lists everything that is missing rather than only the first gap.
  function replay(bank, policy, fixedAge, periodicK) {
    var run = bank.run, snaps = run.snapshots, cands = run.candidates, n = bank.n;
    var costs = callCosts(run);
    var calls = { proposer: 0, candidate_eval: 0, reference_refresh: 0 };
    var missing = new Missing(), decisions = [], refreshes = 0;
    var inc = snaps.length ? snaps[0].prompt : null;
    var ref = { prompt: inc, env: bank.envAt(0), pass: "current", round: 0 };
    var finalEnv = null;

    function need(prompt, env, pass) {
      var lab = bank.labels(prompt, env, pass);
      if (lab === null) missing.add(prompt, env, pass);
      return lab;
    }

    cands.forEach(function (c) {
      var k = c.round, env = bank.envAt(k), fresh = false, old, scoredEnv, cLab, refLab, incLab, p, d;
      finalEnv = env;
      calls.proposer += costs.proposal;
      calls.candidate_eval += costs.evaluation;

      if (fixedAge !== null) {
        old = snaps[Math.max(0, k - fixedAge)];
        ref = { prompt: old.prompt, env: bank.envAt(old.round), pass: "current", round: old.round };
      } else if (policy === "per_batch" ||
          (policy === "env_triggered" && !bank.sameFingerprint(ref.env, env)) ||
          (policy === "periodic" && k - ref.round >= periodicK)) {
        ref = { prompt: inc, env: env, pass: "rerun", round: k };
        fresh = true;
        refreshes++;
        calls.reference_refresh += n;
      }

      scoredEnv = bank.scoredEnv(ref.env, env);
      cLab = need(c.prompt, env, "current");
      refLab = need(ref.prompt, scoredEnv, ref.pass);
      incLab = need(inc, env, "current");
      if (cLab === null || refLab === null || incLab === null) return;

      p = pair(cLab, refLab);
      d = decision(bank, k, env, c.prompt, inc, ref, fresh, scoredEnv, cLab, incLab, p.wins, p.losses);
      decisions.push(d);
      if (d.accepted) {
        inc = c.prompt;
        if (fixedAge === null && (policy === "stored_incumbent" || policy === "env_triggered" || policy === "periodic")) {
          ref = { prompt: inc, env: env, pass: "current", round: k };
        }
      }
    });

    if (missing.list.length) return block(policy, missing);
    return block(policy, missing, decisions, refreshes, calls, cands.length ? inc : null,
      cands.length ? bank.acc(inc, finalEnv) : null);
  }

  function recordedEnv(bank, entry, round) {
    return has.call(entry, "env") ? entry.env : envAt(round, bank.recorded);
  }

  // Round in which the trajectory first held or proposed a prompt under an environment (0 if never).
  function firstScored(bank, prompt, env, upto) {
    var run = bank.run, k, i, c;
    for (k = 0; k <= upto; k++) {
      if (run.snapshots[k].prompt === prompt && recordedEnv(bank, run.snapshots[k], k) === env) return k;
      for (i = 0; i < run.candidates.length; i++) {
        c = run.candidates[i];
        if (c.round === k && c.prompt === prompt && recordedEnv(bank, c, k) === env) return k;
      }
    }
    return 0;
  }

  // The loop's own decisions, judged against the same ground truth as the replayed policies.
  // Needs the reference each candidate was compared with. The verdict is the recorded one;
  // wins and losses are recomputed when the bank holds both sides and are otherwise the
  // recorded counts. Environments are the recorded ones, so a schedule override does not apply.
  function replayRecorded(bank) {
    var run = bank.run, snaps = run.snapshots, cands = run.candidates, n = bank.n;
    var costs, calls, missing, decisions = [], refreshes = 0, finalPrompt = null, finalEnv = null;
    if (cands.some(function (c) { return !has.call(c, "reference") || !has.call(c, "accepted"); })) {
      return block("as_run", null);
    }
    costs = callCosts(run);
    calls = { proposer: 0, candidate_eval: 0, reference_refresh: 0 };
    missing = new Missing();

    cands.forEach(function (c) {
      var k = c.round, env = recordedEnv(bank, c, k);
      var inc = has.call(c, "parent") ? c.parent : snaps[k].prompt;
      var recorded = c.reference, fresh, refRound, ref, cLab, incLab, refLab, p, wins, losses;
      finalEnv = env;
      calls.proposer += costs.proposal;
      calls.candidate_eval += costs.evaluation;
      if (recorded.pass === "rerun") {
        refreshes++;
        calls.reference_refresh += n;
      }
      fresh = recorded.pass === "rerun" && recorded.env === env;
      if (fresh) refRound = k;
      else if (Number.isInteger(recorded.round)) refRound = recorded.round;
      else refRound = firstScored(bank, recorded.prompt, recorded.env, k);
      ref = { prompt: recorded.prompt, env: recorded.env, pass: recorded.pass, round: refRound };

      finalPrompt = c.accepted ? c.prompt : inc;
      cLab = bank.labels(c.prompt, env);
      incLab = bank.labels(inc, env);
      if (cLab === null) missing.add(c.prompt, env, "current");
      if (incLab === null) missing.add(inc, env, "current");
      if (cLab === null || incLab === null) return;
      refLab = bank.labels(ref.prompt, ref.env, ref.pass);
      if (refLab === null) {
        wins = given(c.wins) ? c.wins : null;
        losses = given(c.losses) ? c.losses : null;
      } else {
        p = pair(cLab, refLab);
        wins = p.wins;
        losses = p.losses;
      }
      decisions.push(decision(bank, k, env, c.prompt, inc, ref, fresh, ref.env, cLab, incLab, wins, losses, c.accepted));
    });

    if (missing.list.length) return block("as_run", missing);
    return block("as_run", missing, decisions, refreshes, calls, finalPrompt,
      cands.length ? bank.acc(finalPrompt, finalEnv) : null);
  }

  function sameSchedule(a, b) {
    var keys = Object.keys(a);
    return keys.length === Object.keys(b).length &&
      keys.every(function (k) { return has.call(b, k) && a[k] === b[k]; });
  }

  // Options of audit() checked against a run. null and undefined both mean "not given".
  function readOptions(run, options, onlyPolicy) {
    var repr = DA.schema.repr, o = options || {};
    var policies = onlyPolicy !== undefined ? [onlyPolicy] : o.policies;
    var schedule = run.schedule, inForce;
    var storedScoring = given(o.stored_scoring) ? o.stored_scoring : "as_recorded";
    var margin = given(o.margin) ? o.margin : 0;
    var fixedAge = given(o.fixed_age) ? o.fixed_age : null;
    var periodicK = given(o.periodic_k) ? o.periodic_k : 3;

    if (!given(policies)) {
      policies = POLICY_IDS.slice();
    } else {
      policies = typeof policies === "string" ? [policies] : Array.prototype.slice.call(policies);
      policies.forEach(function (policy) {
        if (typeof policy !== "string" || !has.call(POLICIES, policy)) {
          throw new Error("unknown policy " + repr(policy) + "; choose from " + POLICY_IDS.join(", "));
        }
      });
      policies = POLICY_IDS.filter(function (p) { return policies.indexOf(p) >= 0; });
    }
    if (given(o.schedule)) {
      inForce = {};
      if (typeof o.schedule !== "object" || Array.isArray(o.schedule) ||
          !Object.keys(o.schedule).every(function (start) { return /^[ \t\n]*[+-]?[0-9]+[ \t\n]*$/.test(start); })) {
        throw new Error("schedule must map start rounds to environment ids, for example {0: 'E1', 4: 'E2'}");
      }
      Object.keys(o.schedule).forEach(function (start) { inForce[String(parseInt(start, 10))] = o.schedule[start]; });
      if (!Object.keys(inForce).length) throw new Error("schedule needs at least one entry, for example {0: 'E1'}");
      Object.keys(inForce).forEach(function (start) {
        var env = inForce[start];
        if (typeof env !== "string" || !has.call(run.environments, env)) {
          throw new Error("schedule names environment " + repr(env) + ", which the run does not define " +
            "(it defines " + Object.keys(run.environments).join(", ") + ")");
        }
      });
      schedule = inForce;
    }
    if (storedScoring !== "as_recorded" && storedScoring !== "rescore") {
      throw new Error("stored_scoring must be 'as_recorded' or 'rescore', not " + repr(storedScoring));
    }
    if (typeof margin !== "number") throw new Error("margin must be a number, not " + repr(margin));
    if (fixedAge !== null && !(Number.isInteger(fixedAge) && fixedAge >= 0)) {
      throw new Error("fixed_age must be a whole number of rounds, 0 or more, not " + repr(fixedAge));
    }
    if (!(Number.isInteger(periodicK) && periodicK >= 1)) {
      throw new Error("periodic_k must be a whole number of rounds, 1 or more, not " + repr(periodicK));
    }
    return {
      policies: policies, schedule: schedule, overridden: !sameSchedule(schedule, run.schedule),
      storedScoring: storedScoring, margin: margin, fixedAge: fixedAge, periodicK: periodicK
    };
  }

  function optionsRecord(opts) {
    return {
      stored_scoring: opts.storedScoring, margin: opts.margin, schedule: opts.schedule,
      schedule_overridden: opts.overridden, fixed_age: opts.fixedAge, periodic_k: opts.periodicK
    };
  }

  function bankOf(run, opts) {
    return new Bank(run, opts.schedule, opts.storedScoring, opts.margin);
  }

  function simulateWith(bank, policy, opts) {
    return policy === "as_run" ? replayRecorded(bank) : replay(bank, policy, opts.fixedAge, opts.periodicK);
  }

  // Replay one policy on a run and return its block of the audit result.
  function simulate(run, policy, options) {
    var opts;
    run = DA.schema.load(run);
    opts = readOptions(run, options, policy);
    return simulateWith(bankOf(run, opts), policy, opts);
  }

  // Environments in order of first use under the schedule in force, then the unused ones by id.
  function environments(bank) {
    var used = {}, first = [], rest, k, env;
    for (k = 0; k < bank.run.snapshots.length; k++) {
      env = bank.envAt(k);
      if (!has.call(used, env)) {
        put(used, env, []);
        first.push(env);
      }
      used[env].push(k);
    }
    rest = Object.keys(bank.envs).filter(function (id) { return !has.call(used, id); }).sort(byCodePoint);
    return first.concat(rest).map(function (id) {
      var e = bank.envs[id];
      return {
        id: id, name: has.call(e, "name") ? e.name : "", decoding: e.decoding, scorer: e.scorer,
        fingerprint: e.fingerprint, detail: e.detail || {},
        first_round: has.call(used, id) ? used[id][0] : null, rounds: has.call(used, id) ? used[id] : []
      };
    });
  }

  // The recorded trajectory, one row per candidate: what was proposed against which incumbent.
  function rounds(bank) {
    return bank.run.candidates.map(function (c) {
      var k = c.round, env = bank.envAt(k), inc = bank.run.snapshots[k].prompt;
      return {
        round: k, env: env, env_changed: k > 0 && bank.envAt(k - 1) !== env,
        incumbent: inc, candidate: c.prompt, candidate_id: c.id, note: given(c.note) ? c.note : null,
        candidate_acc: bank.acc(c.prompt, env), incumbent_acc: bank.acc(inc, env)
      };
    });
  }

  // Labels a scorer change flips on unchanged text, for each pair of environments that share their text.
  function scorerFlips(bank, order) {
    var flips = [], prompts = Object.keys(bank.run.prompts);
    order.forEach(function (a, i) {
      order.slice(i + 1).forEach(function (b) {
        var row = { from_env: a, to_env: b, prompts: 0, items: 0, wrong_to_right: 0, right_to_wrong: 0 };
        if (bank.envs[a].decoding !== bank.envs[b].decoding || bank.envs[a].scorer === bank.envs[b].scorer) return;
        prompts.forEach(function (h) {
          var before = bank.labels(h, a), after = bank.labels(h, b), p;
          if (before === null || after === null) return;
          p = pair(after, before);
          row.prompts++;
          row.items += before.length;
          row.wrong_to_right += p.wins;
          row.right_to_wrong += p.losses;
        });
        if (row.prompts) flips.push(row);
      });
    });
    return flips;
  }

  function fullBank(run) {
    var envs = Object.keys(run.environments);
    return Object.keys(run.prompts).every(function (h) {
      return envs.every(function (env) {
        return DA.schema.PASSES.every(function (pass) { return DA.schema.labels(run, h, env, pass) !== null; });
      });
    });
  }

  function auditWith(run, opts) {
    var bank = bankOf(run, opts), envs = environments(bank), policies = {};
    opts.policies.forEach(function (policy) { policies[policy] = simulateWith(bank, policy, opts); });
    return {
      schema: AUDIT_SCHEMA,
      tool: tool(),
      run: {
        id: run.id, seed: given(run.seed) ? run.seed : null, source: run.source, task: run.task,
        model: given(run.model) ? run.model : null, n_items: bank.n, n_rounds: run.snapshots.length,
        n_candidates: run.candidates.length
      },
      options: optionsRecord(opts),
      environments: envs,
      rounds: rounds(bank),
      policies: policies,
      scorer_flips: scorerFlips(bank, envs.map(function (e) { return e.id; })),
      completeness: { full_bank: fullBank(run), notes: bank.notes }
    };
  }

  // Audit one run: every policy replayed on its candidates, with each decision explained.
  //
  // run is a v1 run or a toolkit run file. Options, all optional:
  //   policies        the policy ids to replay (default: all).
  //   schedule        replaces the run's environment schedule (a what-if).
  //   stored_scoring  "as_recorded" keeps a stored reference's labels as they were recorded;
  //                   "rescore" reads its stored text with the current scorer.
  //   margin          accept iff wins - losses > margin.
  //   fixed_age       ablation: every policy uses the snapshot from that many rounds back.
  //   periodic_k      reference age at which the periodic policy reruns.
  //
  // A policy that needs labels the bank lacks comes back with available false and the list
  // of what to record; a sparse bank never throws.
  function audit(run, options) {
    run = DA.schema.load(run);
    return auditWith(run, readOptions(run, options));
  }

  function wholeAge(age, name) {
    if (!(Number.isInteger(age) && age >= 0)) {
      throw new Error(name + " must be a whole number of rounds, 0 or more, not " + DA.schema.repr(age));
    }
    return age;
  }

  function agePairsOf(bank, age, forceStoredEnv, currentEnv) {
    var snaps = bank.run.snapshots, n = bank.n, margin = bank.margin, out = [];
    bank.run.candidates.forEach(function (c) {
      var k = c.round, ref, storedEnv, env, cLab, stored, rerun, incLab, s, r, promote, promoteRerun, better;
      if (k - age < 0) return;
      ref = snaps[k - age].prompt;
      storedEnv = forceStoredEnv || bank.envAt(k - age);
      env = currentEnv || bank.envAt(k);
      if (!has.call(bank.envs, storedEnv) || !has.call(bank.envs, env)) return;
      cLab = bank.labels(c.prompt, env);
      stored = bank.labels(ref, bank.scoredEnv(storedEnv, env));
      rerun = bank.labels(ref, env, "rerun");
      incLab = bank.labels(snaps[k].prompt, env);
      if (cLab === null || stored === null || rerun === null || incLab === null) return;
      s = pair(cLab, stored);
      r = pair(cLab, rerun);
      promote = s.wins - s.losses > margin;
      // what the same rule decides after a refresh
      promoteRerun = r.wins - r.losses > margin;
      better = ones(cLab) / n > ones(incLab) / n;
      out.push({
        round: k,
        stored_win: s.wins / n,
        rerun_win: r.wins / n,
        inflation: (s.wins - r.wins) / n,
        promote: promote,
        false_accept: promote && !better,
        promote_rerun: promoteRerun,
        false_accept_rerun: promoteRerun && !better,
        env_changed: storedEnv !== env
      });
    });
    return out;
  }

  // Each candidate against the trajectory's incumbent from `age` rounds earlier, stored and rerun.
  //
  // The reference is stored under the environment of its own round and the candidate scored
  // under the environment of its round, unless options.force_stored_env and options.current_env
  // fix them. A false accept is judged against the incumbent of the candidate's round. Pairs
  // the bank cannot score are left out. Also takes schedule, stored_scoring and margin.
  function agePairs(run, age, options) {
    var o = options || {}, opts;
    run = DA.schema.load(run);
    opts = readOptions(run, { schedule: o.schedule, stored_scoring: o.stored_scoring, margin: o.margin });
    return agePairsOf(bankOf(run, opts), wholeAge(age, "age"), o.force_stored_env, o.current_env);
  }

  // A per-run quantity summarised over the runs that have it.
  function acrossRuns(values) {
    var xs = values.filter(function (v) { return v !== null; });
    var t = DA.stats.tInterval(xs), m = t.mean;
    return {
      mean: m, sd: DA.stats.sd(xs), lo: t.lo, hi: t.hi, per_run: values.slice(),
      n_positive: xs.filter(function (x) { return x > 0; }).length,
      // How many runs share the sign of the mean: one line of evidence that an effect is systematic.
      same_sign: xs.filter(function (x) { return x !== 0 && (x > 0) === (m > 0); }).length
    };
  }

  // One run's drift inflation in percentage points: the mean over its candidate/reference pairs.
  function runInflation(pairs) {
    return pairs.length ? 100 * DA.stats.mean(pairs.map(function (m) { return m.inflation; })) : null;
  }

  function sum(blocks, key) {
    var total = 0, i;
    for (i = 0; i < blocks.length; i++) total += blocks[i][key];
    return total;
  }

  function meanSd(xs) {
    return { mean: DA.stats.mean(xs), sd: DA.stats.sd(xs) };
  }

  function poolPolicy(policy, audits) {
    var blocks = audits.map(function (a) { return a.policies[policy]; });
    var accepted = sum(blocks, "accepted"), falseAccepts = sum(blocks, "false_accepts");
    var finals = blocks.map(function (b) { return b.final_acc; });
    var measured = finals.filter(function (x) { return x !== null; });
    var causes = {};
    CAUSES.forEach(function (cause) {
      causes[cause] = blocks.reduce(function (total, b) { return total + b.causes[cause]; }, 0);
    });
    return {
      name: POLICIES[policy].name,
      accepted: accepted,
      false_accepts: falseAccepts,
      false_rejects: sum(blocks, "false_rejects"),
      // Pooled sums numerators and denominators over runs. It is not the mean of the runs'
      // own rates, which weights a run with 2 accepts the same as a run with 9.
      false_accept_rate_pooled: accepted ? falseAccepts / accepted : null,
      final_acc: { mean: DA.stats.mean(measured), sd: DA.stats.sd(measured), per_run: finals },
      total_calls: meanSd(blocks.map(function (b) { return b.total_calls; })),
      refreshes: meanSd(blocks.map(function (b) { return b.refreshes; })),
      causes: causes,
      per_run: audits.map(function (a, i) {
        var b = blocks[i];
        return {
          id: a.run.id, seed: a.run.seed, accepted: b.accepted, false_accepts: b.false_accepts,
          false_rejects: b.false_rejects, final_acc: b.final_acc, total_calls: b.total_calls, refreshes: b.refreshes
        };
      })
    };
  }

  function poolScorerFlips(audits) {
    var rows = [], index = {};
    audits.forEach(function (a) {
      a.scorer_flips.forEach(function (flip) {
        var key = JSON.stringify([flip.from_env, flip.to_env]), row;
        if (!has.call(index, key)) {
          index[key] = rows.length;
          rows.push({ from_env: flip.from_env, to_env: flip.to_env, prompts: 0, items: 0, wrong_to_right: 0, right_to_wrong: 0 });
        }
        row = rows[index[key]];
        ["prompts", "items", "wrong_to_right", "right_to_wrong"].forEach(function (k) { row[k] += flip[k]; });
      });
    });
    return rows;
  }

  // Candidates whose improved/no change/worse verdict against their parent differs between two environments.
  function verdictFlips(banks, a, b) {
    var n = 0, flipped = 0;
    banks.forEach(function (bank) {
      bank.run.candidates.forEach(function (c) {
        var parent = has.call(c, "parent") ? c.parent : bank.run.snapshots[c.round].prompt;
        var accs = [bank.acc(c.prompt, a), bank.acc(parent, a), bank.acc(c.prompt, b), bank.acc(parent, b)];
        if (accs.indexOf(null) >= 0) return;
        n++;
        if (outcome(100 * (accs[0] - accs[1])) !== outcome(100 * (accs[2] - accs[3]))) flipped++;
      });
    });
    return { n: n, flipped: flipped };
  }

  // Pool the audits of several runs of one experiment (usually seeds) and probe for drift.
  //
  //   policies      every policy all runs can replay: counts summed, per-run values with mean and sd.
  //   policy_tests  Fisher exact test of environment-triggered against each other policy on decision
  //                 errors. It treats every decision as independent, which overstates the evidence.
  //   probe         drift inflation (pp) at one reference age: references stored under the first
  //                 scheduled environment, everything else scored under each environment in turn.
  //   age           the same quantity by reference age, under the first and the last scheduled environment.
  //
  // Options are those of audit(), applied to every run, plus probe_age and ages.
  function study(runs, options) {
    var o = options || {}, opts, audits, banks, nDecisions, policies = {}, tests = [];
    var lengths, storedEnv, lastEnv, probeAge, ages, probe = {}, byAge = {}, flips, verdicts = null;
    runs = Array.prototype.map.call(runs, function (run) { return DA.schema.load(run); });
    if (!runs.length) throw new Error("study needs at least one run");
    opts = runs.map(function (run) { return readOptions(run, o); });
    audits = runs.map(function (run, i) { return auditWith(run, opts[i]); });
    banks = runs.map(function (run, i) { return bankOf(run, opts[i]); });
    nDecisions = runs.reduce(function (total, run) { return total + run.candidates.length; }, 0);

    opts[0].policies.forEach(function (p) {
      if (audits.every(function (a) { return a.policies[p].available; })) policies[p] = poolPolicy(p, audits);
    });

    function errors(p) {
      return policies[p].false_accepts + policies[p].false_rejects;
    }

    if (has.call(policies, "env_triggered")) {
      Object.keys(policies).forEach(function (p) {
        if (p === "env_triggered") return;
        tests.push({
          a: "env_triggered", b: p, errors_a: errors("env_triggered"), errors_b: errors(p), n: nDecisions,
          fisher_p: DA.stats.fisher(errors("env_triggered"), nDecisions, errors(p), nDecisions)
        });
      });
    }

    lengths = runs.map(function (run) { return run.snapshots.length; });
    storedEnv = banks[0].envAt(0);
    probeAge = given(o.probe_age) ? wholeAge(o.probe_age, "probe_age")
      : Math.max(0, Math.min(3, Math.min.apply(null, lengths) - 1));
    Object.keys(runs[0].environments).forEach(function (env) {
      if (!runs.every(function (run) { return has.call(run.environments, env); })) return;
      put(probe, env, acrossRuns(banks.map(function (bank) {
        return runInflation(agePairsOf(bank, probeAge, storedEnv, env));
      })));
    });

    ages = given(o.ages)
      ? Array.prototype.map.call(o.ages, function (age) { return wholeAge(age, "ages"); })
      : DEFAULT_AGES.filter(function (age) { return age < Math.max.apply(null, lengths); });
    lastEnv = banks[0].envAt(Math.max(0, lengths[0] - 1));
    [storedEnv, lastEnv].forEach(function (env) {
      if (has.call(byAge, env)) return;
      put(byAge, env, ages.map(function (age) {
        var perRunPairs = banks.map(function (bank) { return agePairsOf(bank, age, storedEnv, env); });
        var pooled = [].concat.apply([], perRunPairs);
        var perRun = perRunPairs.map(runInflation);
        var t = DA.stats.tInterval(perRun.filter(function (x) { return x !== null; }));
        // Inflation stays per run; promotions are pooled, because at the largest ages a
        // run has too few pairs to give a rate of its own.
        return {
          age: age, pairs: pooled.length, mean: t.mean, lo: t.lo, hi: t.hi, per_run: perRun,
          promoted: count(pooled, function (m) { return m.promote; }),
          false_accepts: count(pooled, function (m) { return m.false_accept; })
        };
      }));
    });

    flips = poolScorerFlips(audits);
    if (flips.length) verdicts = verdictFlips(banks, flips[0].from_env, flips[0].to_env);

    return {
      schema: STUDY_SCHEMA,
      tool: tool(),
      options: optionsRecord(opts[0]),
      runs: runs.map(function (run) { return { id: run.id, seed: given(run.seed) ? run.seed : null, source: run.source }; }),
      source: studySource(runs.map(function (run) { return run.source; })),
      n_runs: runs.length,
      n_decisions: nDecisions,
      policies: policies,
      policy_tests: tests,
      probe: { age: probeAge, stored_env: storedEnv, by_env: probe },
      age: { stored_env: storedEnv, ages: ages, by_env: byAge },
      scorer_flips: flips,
      verdict_flips: verdicts
    };
  }

  // "measured" or "synthetic" when every run is, "mixed" otherwise.
  function studySource(sources) {
    var first = sources[0];
    return sources.every(function (x) { return x === first; }) ? first : "mixed";
  }

  // Python prints None for a missing value; the messages say the same here.
  function shown(value) {
    return value === null || value === undefined ? "None" : String(value);
  }

  // Why these runs should not be pooled in one study; empty when they can be.
  //
  // Every run is compared with the first on task name, number of items, number of rounds,
  // schedule and the fingerprint of each environment, and only the first difference is
  // reported for each run. Run ids must also be unique, or the per-run table cannot tell
  // the runs apart. names label the runs in the messages (default: their ids).
  function compatibility(runs, names) {
    var labels, problems = [], first, seen = {};
    runs = Array.prototype.map.call(runs || [], function (run) { return DA.schema.load(run); });
    labels = names ? Array.prototype.slice.call(names) : runs.map(function (run) { return run.id; });
    if (!runs.length) return problems;

    function traits(run) {
      var envs = run.environments, ids = Object.keys(envs).sort();
      var schedule = Object.keys(run.schedule).sort(function (a, b) { return Number(a) - Number(b); })
        .map(function (k) { return k + ":" + run.schedule[k]; }).join(",");
      return [
        ["task", run.task.name],
        ["number of items", run.task.n_items],
        ["number of rounds", run.snapshots.length],
        ["schedule", schedule],
        ["environments", ids.join(", ")]
      ].concat(ids.map(function (id) { return ["fingerprint of " + id, envs[id].fingerprint]; }));
    }

    first = traits(runs[0]);
    runs.slice(1).forEach(function (run, i) {
      var mine = traits(run), j;
      for (j = 0; j < Math.min(first.length, mine.length); j++) {
        if (mine[j][1] !== first[j][1]) {
          problems.push(labels[i + 1] + ": " + first[j][0] + " is " + shown(mine[j][1]) + ", where " + labels[0] + " has " + shown(first[j][1]));
          break;
        }
      }
    });
    runs.forEach(function (run, i) {
      if (has.call(seen, run.id)) problems.push(labels[i] + ": run id " + run.id + " is also the id of " + seen[run.id]);
      else seen[run.id] = labels[i];
    });
    return problems;
  }

  function cells(cand, ref) {
    var out = "", n, i, c, r;
    if (cand === null || ref === null) return null;
    n = Math.min(cand.length, ref.length);
    for (i = 0; i < n; i++) {
      c = cand.charCodeAt(i) === ONE;
      r = ref.charCodeAt(i) === ONE;
      out += c ? (r ? "b" : "w") : (r ? "l" : "n");
    }
    return out;
  }

  // Item-by-item view of one decision: the candidate against both readings of its reference.
  //
  // stored and rerun hold one character per item: w the candidate alone is right (a win),
  // l the reference alone (a loss), b both, n neither. An item whose character differs
  // between the two is one the refresh would have changed. rerun and reference_rerun are
  // null when the bank has no rerun of the reference under the decision's environment.
  function itemCells(run, d) {
    var cand, stored, rerun;
    run = DA.schema.load(run);
    cand = DA.schema.labels(run, d.candidate, d.env);
    stored = DA.schema.labels(run, d.ref_prompt, has.call(d, "ref_scored_env") ? d.ref_scored_env : d.ref_env,
      has.call(d, "ref_pass") ? d.ref_pass : "current");
    rerun = DA.schema.labels(run, d.ref_prompt, d.env, "rerun");
    return {
      n: run.task.n_items, stored: cells(cand, stored), rerun: cells(cand, rerun),
      candidate: cand, reference_stored: stored, reference_rerun: rerun
    };
  }

  DA.engine = {
    AUDIT_SCHEMA: AUDIT_SCHEMA,
    STUDY_SCHEMA: STUDY_SCHEMA,
    POLICIES: POLICIES,
    audit: audit,
    study: study,
    compatibility: compatibility,
    studySource: studySource,
    simulate: simulate,
    agePairs: agePairs,
    pair: pair,
    outcome: outcome,
    itemCells: itemCells
  };

  if (typeof module === "object" && module.exports) module.exports = DA;
})(typeof globalThis !== "undefined" ? globalThis : this);
