(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  var MINUS = "−";
  var NBSP = " ";

  /* Escaping template ---------------------------------------------------------------- */

  // Markup that is safe to insert. Only html`` and raw() make one, so a plain string coming
  // from a run log can never reach the DOM unescaped.
  function Safe(text) {
    this.text = text;
  }
  Safe.prototype.toString = function () {
    return this.text;
  };

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };

  // Control characters other than tab and newline never reach the page: a run log from a
  // stranger could otherwise hide text or break a line where it likes.
  var CONTROLS = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/g;

  function escape(value) {
    return String(value).replace(CONTROLS, "").replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
  }

  function piece(value) {
    if (value === null || value === undefined || value === false || value === true) return "";
    if (value instanceof Safe) return value.text;
    if (Array.isArray(value)) return value.map(piece).join("");
    return escape(value);
  }

  function html(strings) {
    var out = strings[0], i;
    for (i = 1; i < strings.length; i++) out += piece(arguments[i]) + strings[i];
    return new Safe(out);
  }

  function raw(text) {
    return new Safe(text === null || text === undefined ? "" : String(text));
  }

  function join(parts, separator) {
    return new Safe(parts.map(piece).join(piece(separator === undefined ? "" : separator)));
  }

  // Attributes from an object. null, undefined and false are left out; true writes a bare name.
  function attrs(map) {
    var out = "";
    Object.keys(map || {}).forEach(function (name) {
      var value = map[name];
      if (value === null || value === undefined || value === false) return;
      if (!/^[a-zA-Z_:][-a-zA-Z0-9_:.]*$/.test(name)) return;
      out += " " + name + (value === true ? "" : "=\"" + escape(value) + "\"");
    });
    return new Safe(out);
  }

  /* Mounting ------------------------------------------------------------------------- */

  function keyed(scope, key) {
    var found = null;
    Array.prototype.some.call(scope.querySelectorAll("[data-key]"), function (el) {
      if (el.getAttribute("data-key") === key) found = el;
      return found !== null;
    });
    return found;
  }

  // Replace the content of el. Focus, scroll offsets and open disclosures carry over to the
  // elements that have the same data-key in the new markup.
  function mount(el, markup) {
    var active, focusKey = null, heading = false, scrolls = [], opened = [];
    if (!(markup instanceof Safe)) {
      throw new TypeError("DA.ui.mount takes the result of DA.ui.html, so that run data is escaped.");
    }
    active = document.activeElement;
    if (active && active !== el && el.contains(active)) {
      focusKey = active.getAttribute("data-key");
      heading = active.tagName === "H1";
    }
    Array.prototype.forEach.call(el.querySelectorAll("[data-key]"), function (node) {
      if (node.scrollLeft || node.scrollTop) scrolls.push([node.getAttribute("data-key"), node.scrollLeft, node.scrollTop]);
      if (node.tagName === "DETAILS") opened.push([node.getAttribute("data-key"), node.open]);
    });
    el.innerHTML = markup.text;
    scrolls.forEach(function (s) {
      var node = keyed(el, s[0]);
      if (node) {
        node.scrollLeft = s[1];
        node.scrollTop = s[2];
      }
    });
    opened.forEach(function (o) {
      var node = keyed(el, o[0]);
      if (node && node.tagName === "DETAILS") node.open = o[1];
    });
    if (focusKey !== null) {
      active = keyed(el, focusKey);
      if (active) active.focus({ preventScroll: true });
    } else if (heading) {
      active = el.querySelector("h1");
      if (active) {
        active.setAttribute("tabindex", "-1");
        active.focus({ preventScroll: true });
      }
    }
    return el;
  }

  /* Formatting ----------------------------------------------------------------------- */

  var POLICY_NAMES = {
    frozen: "Frozen",
    stored_incumbent: "Stored incumbent",
    per_batch: "Per-batch",
    env_triggered: "Environment-triggered",
    periodic: "Every k rounds",
    as_run: "As run"
  };
  var POLICY_PHRASES = {
    frozen: "the frozen policy",
    stored_incumbent: "the stored incumbent policy",
    per_batch: "the per-batch policy",
    env_triggered: "the environment-triggered policy",
    as_run: "the loop's own rule"
  };
  var CAUSES = {
    stale: "stale reference",
    anyway: "would have been accepted anyway",
    no_drift: "no environment change"
  };
  var CAUSE_SENTENCES = {
    stale: "A rerun reference would reject it.",
    anyway: "A rerun reference would also promote it.",
    no_drift: "The reference comes from the same environment, so drift does not explain it."
  };

  // toFixed already rounds by the exact binary value (2.675 is stored a little below 2.675,
  // so it gives 2.67 as Python does), but an exact tie such as 0.125 goes up. Python rounds
  // ties to even, and the CLI and the paper print with Python, so ties go to even here too.
  var TAIL = 25;

  function unsigned(a, digits) {
    var s = a.toFixed(digits), long, cut;
    if (a >= 1e15) return s;
    long = a.toFixed(digits + TAIL);
    if (long.slice(-TAIL) !== "5" + new Array(TAIL).join("0")) return s;
    cut = long.slice(0, -TAIL).replace(/\.$/, "");
    return Number(cut.charAt(cut.length - 1)) % 2 === 0 ? cut : s;
  }

  function fixed(x, digits) {
    var s = unsigned(Math.abs(x), digits);
    return (x < 0 && Number(s) !== 0 ? MINUS : "") + s;
  }

  var fmt = {
    MINUS: MINUS,
    NBSP: NBSP,

    int: function (n) {
      if (n === null || n === undefined || isNaN(n)) return "n/a";
      var s = unsigned(Math.abs(n), 0);
      return (n < 0 && Number(s) !== 0 ? MINUS : "") + s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    },

    num: function (x, digits) {
      if (x === null || x === undefined || isNaN(x)) return "n/a";
      return fixed(x, digits === undefined ? 2 : digits);
    },

    // A fraction as a percentage: 0.708 gives "70.8%".
    pct: function (x, digits) {
      if (x === null || x === undefined || isNaN(x)) return "n/a";
      return fixed(100 * x, digits === undefined ? 1 : digits) + "%";
    },

    // Percentage points with an explicit sign: 1.3125 gives "+1.31", -0.5875 gives "−0.59".
    pp: function (x, digits, unit) {
      var s;
      if (x === null || x === undefined || isNaN(x)) return "n/a";
      s = fixed(x, digits === undefined ? 2 : digits);
      if (x > 0 && Number(s) !== 0) s = "+" + s;
      return unit ? s + NBSP + "pp" : s;
    },

    // The same for a fraction, as the engine returns inflation: 0.015 gives "+1.50".
    ppOf: function (fraction, digits, unit) {
      if (fraction === null || fraction === undefined) return "n/a";
      return fmt.pp(100 * fraction, digits, unit);
    },

    count: function (part, whole) {
      return fmt.int(part) + " of " + fmt.int(whole);
    },

    plural: function (n, one, many) {
      return fmt.int(n) + NBSP + (n === 1 ? one : many || one + "s");
    },

    list: function (items) {
      if (items.length < 2) return items.join("");
      return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
    },

    // Round numbers as ranges: [4, 5, 6, 8] gives "4 to 6, 8".
    rounds: function (list) {
      var out = [], start = null, last = null;
      if (!list || !list.length) return "none";
      list.slice().sort(function (a, b) { return a - b; }).forEach(function (r) {
        if (start === null) {
          start = last = r;
        } else if (r === last + 1) {
          last = r;
        } else {
          out.push(start === last ? String(start) : start + " to " + last);
          start = last = r;
        }
      });
      out.push(start === last ? String(start) : start + " to " + last);
      return out.join(", ");
    },

    interval: function (lo, hi, digits) {
      if (lo === null || lo === undefined || hi === null || hi === undefined) return "n/a";
      return fmt.pp(lo, digits) + " to " + fmt.pp(hi, digits);
    },

    meanSd: function (mean, sd, digits) {
      if (mean === null || mean === undefined) return "n/a";
      if (!sd) return fmt.num(mean, digits);
      return fmt.num(mean, digits) + " ± " + fmt.num(sd, digits);
    },

    policy: function (id, k) {
      if (id === "periodic" && k) return "Every " + k + " rounds";
      return POLICY_NAMES[id] || id;
    },

    // The policy inside a sentence: "under the frozen policy".
    policyPhrase: function (id, k) {
      if (id === "periodic") return "a refresh every " + (k || "k") + " rounds";
      return POLICY_PHRASES[id] || id;
    },

    cause: function (id) {
      return CAUSES[id] || id;
    },

    causeSentence: function (id) {
      return CAUSE_SENTENCES[id] || "";
    },

    source: function (source) {
      return source === "synthetic" ? "synthetic" : "measured";
    },

    // Short name of a prompt: p0, p1, ... when the schema can number it, else the id itself.
    prompt: function (run, id) {
      if (run && DA.schema && typeof DA.schema.promptLabel === "function") {
        try {
          return DA.schema.promptLabel(run, id) || id;
        } catch (err) {
          return id;
        }
      }
      return id;
    }
  };

  /* Small components ----------------------------------------------------------------- */

  function tag(text, kind) {
    return html`<span class="tag${kind ? " tag--" + kind : ""}">${text}</span>`;
  }

  function sourceTag(source) {
    return source === "synthetic" ? tag("synthetic", "warning") : tag("measured");
  }

  // The warning for a synthetic run, or for a pool that holds synthetic runs. s: { source, name }
  // for one run, { source, runs: [run logs] } for a pool. Measured gives nothing.
  function sourceNotice(s) {
    var n, k, body;
    if (s.runs) {
      n = s.runs.length;
      k = s.runs.filter(function (r) { return r.source === "synthetic"; }).length;
      if (!k) return "";
      body = k === n ? "Every run in this set is marked synthetic: its numbers are not measurements of a model."
        : k + " of the " + n + " runs in this set are marked synthetic, so the pooled numbers mix measurements with simulated ones.";
      return notice({ kind: "warning", body: html`${tag(k === n ? "synthetic" : "mixed", "warning")} ${body}` });
    }
    if (s.source !== "synthetic") return "";
    return notice({ kind: "warning", body: html`${tag("synthetic", "warning")} ${s.name || "This run"} is marked synthetic: its numbers are not measurements of a model.` });
  }

  var MARK_NAMES = {
    improved: "promoted, an improvement",
    "false-accept": "false accept",
    "false-reject": "false reject",
    rejected: "kept"
  };

  // The four decision marks. Fill says promoted or not; the diamond says the decision was wrong.
  function mark(kind) {
    var diamond = kind === "false-accept" || kind === "false-reject";
    var shape = diamond
      ? (kind === "false-accept" ? "<path class=\"mark__shape\" d=\"M6 0.5 11.5 6 6 11.5 0.5 6Z\"/>" : "<path class=\"mark__shape\" d=\"M6 1.6 10.4 6 6 10.4 1.6 6Z\"/>")
      : (kind === "improved" ? "<circle class=\"mark__shape\" cx=\"6\" cy=\"6\" r=\"4.5\"/>" : "<circle class=\"mark__shape\" cx=\"6\" cy=\"6\" r=\"3.75\"/>");
    return html`<svg class="mark mark--${kind}" viewBox="0 0 12 12" aria-hidden="true" focusable="false">${raw(shape)}</svg>`;
  }

  function markOf(decision) {
    if (decision.false_accept) return "false-accept";
    if (decision.false_reject) return "false-reject";
    return decision.accepted ? "improved" : "rejected";
  }

  // items: [{ label, mark: "improved" } | { label, swatch: "stored" }]
  function legend(items, className) {
    return html`<ul class="legend${className ? " " + className : ""}">${items.map(function (item) {
      return html`<li class="legend__item">${item.mark ? mark(item.mark) : html`<span class="swatch swatch--${item.swatch}"></span>`}${item.label}</li>`;
    })}</ul>`;
  }

  // One reading: { label, value, unit, note, state: "alert" | "empty" }
  function readout(r) {
    return html`<div class="readout${r.state ? " readout--" + r.state : ""}">
      <dt class="readout__label">${r.label}</dt>
      <dd class="readout__value">${r.value}${r.unit ? html`<span class="readout__unit">${r.unit}</span>` : ""}</dd>
      ${r.note ? html`<dd class="readout__note">${r.note}</dd>` : ""}
    </div>`;
  }

  function readouts(items) {
    return html`<dl class="readouts">${items.map(readout)}</dl>`;
  }

  // kind: "info" | "warning" | "error" | "quiet". Errors interrupt (role alert); the rest wait.
  function notice(n) {
    var kind = n.kind || "info";
    return html`<div class="notice notice--${kind}" role="${kind === "error" ? "alert" : "status"}"${attrs({ "data-key": n.key })}>
      ${n.title ? html`<p class="notice__title">${n.title}</p>` : ""}
      ${n.body ? html`<div class="notice__body">${n.body}</div>` : ""}
      ${n.actions || n.dismiss ? html`<div class="notice__actions">${n.actions}${n.dismiss ? html`<button type="button" class="btn btn--small" data-dismiss${attrs({ "data-dismiss-name": n.dismiss === true ? null : n.dismiss })}>Dismiss</button>` : ""}</div>` : ""}
    </div>`;
  }

  function copyButton(c) {
    var label = c.label || "Copy";
    return html`<button type="button" class="btn btn--small" data-copy="${c.text}" data-label="${label}" data-done="${c.done || "Copied"}"${attrs({ "data-key": c.key, "aria-label": c.ariaLabel })}>${label}</button>`;
  }

  // A literal string (fingerprint, hash) with a copy button beside it.
  function copyable(text, c) {
    c = c || {};
    return html`<span class="copyable"><code class="copyable__text">${text}</code>${copyButton({ text: text, label: c.label, done: c.done, key: c.key, ariaLabel: c.ariaLabel })}</span>`;
  }

  function code(text, c) {
    c = c || {};
    return html`<div class="code"><pre data-scroll="Code, scrolls sideways"><code>${text}</code></pre>${copyButton({ text: text, label: c.label || "Copy", done: c.done, key: c.key })}</div>`;
  }

  // rows: [{ key, value, mono, copy }] where copy is true or { label, done }
  function kv(rows) {
    return html`<dl class="kv">${rows.map(function (r) {
      var value = html`<span class="kv__value${r.mono ? " kv__value--mono" : ""}">${r.value}</span>`;
      return html`<div class="kv__row"><dt>${r.key}</dt><dd>${value}${r.copy ? copyButton({ text: r.copyText || String(r.value), label: r.copy.label, done: r.copy.done }) : ""}</dd></div>`;
    })}</dl>`;
  }

  function disclosure(d) {
    return html`<details class="disclosure"${attrs({ open: !!d.open, "data-key": d.key })}>
      <summary>${d.summary}</summary>
      <div class="disclosure__body">${d.body}</div>
    </details>`;
  }

  // columns: [{ label, key | cell(row, i), num, mono, tight, className(row), head }]
  // rows: plain objects. t.rowClass(row, i) and t.rowAttrs(row, i) decorate the <tr>.
  function ledger(t) {
    var cols = t.columns, rows = t.rows || [];
    function classes(col, row) {
      var list = [];
      if (col.num) list.push("is-num");
      if (col.mono && row) list.push("is-mono");
      if (col.tight) list.push("is-tight");
      if (row && col.className) list.push(col.className(row) || "");
      return list.join(" ").trim();
    }
    var body = rows.length ? rows.map(function (row, i) {
      return html`<tr${attrs(Object.assign({ "class": t.rowClass ? t.rowClass(row, i) : null }, t.rowAttrs ? t.rowAttrs(row, i) : null))}>${cols.map(function (col) {
        var content = col.cell ? col.cell(row, i) : row[col.key];
        var cls = classes(col, row);
        return col.head
          ? html`<th scope="row"${attrs({ "class": cls || null })}>${content}</th>`
          : html`<td${attrs({ "class": cls || null })}>${content}</td>`;
      })}</tr>`;
    }) : html`<tr><td class="ledger__empty" colspan="${cols.length}">${t.empty || "Nothing to show."}</td></tr>`;
    return html`<div class="ledger-wrap" data-scroll${attrs({ "data-key": t.key, "aria-label": t.label })}>
      <table class="ledger${t.dense ? " ledger--dense" : ""}">
        ${t.caption ? html`<caption class="visually-hidden">${t.caption}</caption>` : ""}
        <thead><tr>${cols.map(function (col) {
          return html`<th scope="col"${attrs({ "class": classes(col) || null })}>${col.label}</th>`;
        })}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
  }

  // options: [{ value, label, unavailable, disabled }]. Emits da:select { name, value }.
  function segmented(s) {
    return html`<div class="segmented" role="radiogroup" aria-label="${s.label}" data-segmented="${s.name}">${s.options.map(function (o) {
      var on = o.value === s.value;
      return html`<button type="button" role="radio" class="segmented__option${o.unavailable ? " is-unavailable" : ""}" aria-checked="${on ? "true" : "false"}" tabindex="${on ? "0" : "-1"}" data-value="${o.value}" data-key="${s.name + ":" + o.value}"${attrs({ "aria-disabled": o.disabled ? "true" : null, title: o.title })}>${o.label}</button>`;
    })}</div>`;
  }

  var CORE_POLICIES = ["frozen", "stored_incumbent", "per_batch", "env_triggered"];

  // The four replayed policies, plus "As run" when the log records references of its own
  // (DA.library.offersAsRun), and whichever policy is selected, so the control shows the state.
  function policyOptions(policies, selected) {
    var ids = CORE_POLICIES.filter(function (id) { return policies[id]; });
    var asRun = DA.library ? DA.library.offersAsRun(policies) : !!(policies.as_run && policies.as_run.available);
    if (asRun) ids.push("as_run");
    if (selected && policies[selected] && ids.indexOf(selected) < 0 && (selected !== "as_run" || asRun)) ids.push(selected);
    return ids.map(function (id) {
      var p = policies[id];
      return {
        value: id, label: fmt.policy(id, p.k), unavailable: p.available === false,
        title: p.available === false ? "Not available for this run" : null
      };
    });
  }

  function policySwitcher(policies, selected) {
    return segmented({ name: "policy", label: "Refresh policy", value: selected, options: policyOptions(policies, selected) });
  }

  // items: [{ id, label, href }]. With hrefs this is navigation; without, a tablist that
  // emits da:select { name, value }.
  function tabs(t) {
    var links = t.items.some(function (item) { return item.href; });
    var cls = "tabs" + (t.plain ? " tabs--plain" : "");
    if (links) {
      return html`<nav class="${cls}" aria-label="${t.label}">${t.items.map(function (item) {
        return html`<a class="tabs__tab" href="${item.href}" data-label="${item.label}" data-key="${t.name + ":" + item.id}"${attrs({ "aria-current": item.id === t.value ? "page" : null })}>${item.label}</a>`;
      })}</nav>`;
    }
    return html`<div class="${cls}" role="tablist" aria-label="${t.label}" data-tabs="${t.name}">${t.items.map(function (item) {
      var on = item.id === t.value;
      return html`<button type="button" role="tab" class="tabs__tab" aria-selected="${on ? "true" : "false"}" tabindex="${on ? "0" : "-1"}" data-value="${item.id}" data-label="${item.label}" data-key="${t.name + ":" + item.id}">${item.label}</button>`;
    })}</div>`;
  }

  // options: [{ value, label }]. A native select, so it works with every input method.
  function select(s) {
    return html`<label class="field"><span class="field__label">${s.label}</span><span class="select"><select name="${s.name}" data-key="${s.key || s.name}"${attrs({ disabled: !!s.disabled })}>${s.options.map(function (o) {
      return html`<option value="${o.value}"${attrs({ selected: o.value === s.value, disabled: !!o.disabled })}>${o.label}</option>`;
    })}</select></span></label>`;
  }

  function dropOverlay() {
    return html`<div class="drop" id="da-drop" aria-hidden="true"><div class="drop__frame">
      <p class="drop__title">Drop run logs to audit them</p>
      <p class="drop__note">One or more .json run logs, with their .outputs.jsonl files if you have them. The files stay in this browser tab and nothing is uploaded.</p>
    </div></div>`;
  }

  /* Ruler ---------------------------------------------------------------------------- */

  function envNames(audit) {
    var names = {};
    audit.environments.forEach(function (e) { names[e.id] = e.name || e.id; });
    return names;
  }

  // The reading of one decision as a sentence. past is for the loop's own decisions (As run);
  // a replayed policy is described in the present tense.
  function reading(d, row, names, past) {
    var who = row && row.candidate_id ? row.candidate_id : "the candidate";
    var out = "Round " + d.round + ", " + (names[d.env] || d.env) + ": " + who + (d.accepted ? " promoted, " : " not promoted and the incumbent kept, ");
    out += d.wins + " wins to " + d.losses + " losses against the " + (d.ref_fresh ? "reference rerun this round" : "stored reference");
    out += d.ref_fresh ? ". " : " and " + d.rerun_wins + " to " + d.rerun_losses + " against the rerun reference. ";
    if (d.false_accept) {
      out += "False accept: accuracy " + (past ? "went" : "goes") + " from " + fmt.pct(d.inc_acc) + " to " + fmt.pct(d.cand_acc) + ". " + fmt.causeSentence(d.cause);
    } else if (d.false_reject) {
      out += "False reject: accuracy " + (past ? "would have gone" : "would go") + " from " + fmt.pct(d.inc_acc) + " to " + fmt.pct(d.cand_acc) + ".";
    } else if (d.accepted) {
      out += "Accuracy " + (past ? "went" : "goes") + " from " + fmt.pct(d.inc_acc) + " to " + fmt.pct(d.cand_acc) + ".";
    } else {
      out += "Accuracy " + (past ? "would have gone" : "would go") + " from " + fmt.pct(d.inc_acc) + " to " + fmt.pct(d.cand_acc) + ".";
    }
    return out;
  }

  // What the ruler draws for one audit under one policy. Without a policy (a study, or a
  // policy that cannot be replayed) it is the schedule alone.
  function rulerModel(audit, policyId, selected) {
    var names = envNames(audit), levels = {}, nextLevel = 0;
    var policy = policyId && audit.policies[policyId] && audit.policies[policyId].available !== false ? audit.policies[policyId] : null;
    var byRound = {};
    if (policy) policy.decisions.forEach(function (d) { byRound[d.round] = d; });
    var rounds = audit.rounds.map(function (row, i) {
      var d = byRound[row.round] || null;
      if (levels[row.env] === undefined) levels[row.env] = nextLevel++ % 4;
      return {
        round: row.round, env: row.env, envName: names[row.env] || row.env, level: levels[row.env],
        first: i === 0 || audit.rounds[i - 1].env !== row.env,
        stale: !!(d && d.env_mismatch),
        mark: d ? markOf(d) : null,
        reading: d ? reading(d, row, names, policyId === "as_run") : null
      };
    });
    rounds.forEach(function (r, i) {
      var j = i, run = 0;
      if (r.first) {
        while (j < rounds.length && rounds[j].env === r.env && (j === i || !rounds[j].first)) j++;
        r.span = j - i;
      }
      r.bandStart = r.stale && (r.first || !rounds[i - 1].stale);
      r.bandEnd = r.stale && (i === rounds.length - 1 || rounds[i + 1].first || !rounds[i + 1].stale);
      if (r.bandStart) {
        for (j = i; j < rounds.length && rounds[j].stale && (j === i || !rounds[j].first); j++) run++;
        r.bandRun = run;
      }
    });
    return { rounds: rounds, selected: selected === undefined ? null : selected, interactive: !!policy };
  }

  function ruler(model) {
    var rounds = model.rounds, last = rounds.length - 1, firstBand = true;
    var focusRound = model.selected !== null && model.selected !== undefined ? model.selected : (rounds.length ? rounds[0].round : null);
    var cells = rounds.map(function (r, i) {
      var on = r.round === model.selected;
      var cls = "ruler__cell ruler__cell--l" + r.level + (r.stale ? " is-stale" : "") + (r.bandStart ? " is-band-start" : "") +
        (r.bandEnd ? " is-band-end" : "") + (i === last ? " is-last" : "");
      var name = "Round " + r.round + ", " + r.envName + (r.mark ? ". " + MARK_NAMES[r.mark] : "") + (r.stale ? ". Stale reference" : "") + ".";
      var label = r.bandStart && firstBand;
      if (label) firstBand = false;
      var inner = html`${r.first ? html`<span class="ruler__env" data-span="${r.span}" data-name="${r.envName}" aria-hidden="true"></span>` : ""}
        <span class="ruler__mark">${r.mark ? mark(r.mark) : ""}</span>
        <span class="ruler__ticks" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>
        <span class="ruler__num">${r.round}</span>
        <span class="ruler__band">${label ? html`<span class="ruler__band-label" data-span="${r.bandRun}" data-name="Stale reference" aria-hidden="true"></span>` : ""}</span>`;
      var cell = model.interactive
        ? html`<div class="${cls}" role="option" aria-selected="${on ? "true" : "false"}" tabindex="${r.round === focusRound ? "0" : "-1"}" data-round="${r.round}" data-key="${"ruler-" + r.round}" aria-label="${name}" title="${name}">${inner}</div>`
        : html`<div class="${cls}" title="${name}">${inner}</div>`;
      return html`${r.first && i > 0 ? html`<span class="ruler__break" aria-hidden="true"></span>` : ""}${cell}`;
    });
    if (model.interactive) {
      return html`<div class="ruler" data-ruler data-key="ruler" role="listbox" aria-orientation="horizontal" aria-label="${model.label || "Rounds. Arrow keys move between rounds, Escape clears the selection."}"><div class="ruler__scale">${cells}</div></div>`;
    }
    return html`<div class="ruler ruler--static" data-ruler data-key="ruler" role="img" aria-label="${model.label || scheduleText(rounds)}"><div class="ruler__scale">${cells}</div></div>`;
  }

  function scheduleText(rounds) {
    var parts = [], i, j;
    for (i = 0; i < rounds.length; i = j) {
      for (j = i + 1; j < rounds.length && !rounds[j].first; j++);
      parts.push((j - i > 1 ? "rounds " + rounds[i].round + " to " + rounds[j - 1].round : "round " + rounds[i].round) + " " + rounds[i].envName);
    }
    return "Environment schedule: " + parts.join("; ") + ".";
  }

  var RULER_LEGEND = [
    { mark: "improved", label: "Promoted, an improvement" },
    { mark: "false-accept", label: "False accept" },
    { mark: "false-reject", label: "False reject" },
    { mark: "rejected", label: "Kept" },
    { swatch: "stale", label: "Stale reference" }
  ];

  /* Plate ---------------------------------------------------------------------------- */

  var CELL_NAMES = { w: "a win", l: "a loss", b: "both right", n: "neither right" };

  function cellText(i, stored, rerun, label) {
    var candRight = stored === "w" || stored === "b";
    var out = label + ": candidate " + (candRight ? "right" : "wrong") + ", stored reference " +
      (stored === "l" || stored === "b" ? "right" : "wrong");
    if (rerun === null) return out + ". Counts as " + CELL_NAMES[stored] + ".";
    out += ", rerun reference " + (rerun === "l" || rerun === "b" ? "right" : "wrong") + ". ";
    if (stored === rerun) return out + "Counts as " + CELL_NAMES[stored] + " in both readings.";
    return out + "Counts as " + CELL_NAMES[stored] + " against the stored reading and " + CELL_NAMES[rerun] + " against the rerun.";
  }

  function tally(cells) {
    var t = { w: 0, l: 0, b: 0, n: 0 }, i;
    for (i = 0; i < cells.length; i++) t[cells.charAt(i)]++;
    return t;
  }

  // p: { cells: { n, stored, rerun } as DA.engine.itemCells returns them, key, itemLabel(i) }
  // Emits da:cell { index, stored, rerun, which } when a cell is activated.
  function plate(p) {
    var cells = p.cells, n = cells.stored ? cells.stored.length : 0, cols = n >= 100 ? 20 : 10;
    var itemLabel = p.itemLabel || function (i) { return "Item " + i; };
    var key = p.key || "plate", changed = 0, i;
    if (!cells.stored) return notice({ kind: "quiet", body: "The labels for this decision are not in the run log, so its items cannot be shown." });
    if (cells.rerun) for (i = 0; i < n; i++) if (cells.stored.charAt(i) !== cells.rerun.charAt(i)) changed++;

    function side(which, title, string) {
      var t = tally(string), rows = [], r, c, start, row;
      for (r = 0; r * cols < n; r++) {
        row = [];
        for (c = 0; c < cols && r * cols + c < n; c++) {
          start = r * cols + c;
          row.push(html`<div role="gridcell" class="plate__cell plate__cell--${string.charAt(start)}${cells.rerun && cells.stored.charAt(start) !== cells.rerun.charAt(start) ? " is-changed" : ""}" tabindex="${start === 0 ? "0" : "-1"}" data-i="${start}" data-key="${key + "-" + which + "-" + start}" aria-label="${cellText(start, cells.stored.charAt(start), cells.rerun ? cells.rerun.charAt(start) : null, itemLabel(start))}"></div>`);
        }
        rows.push(html`<div role="row" class="plate__row">${row}</div>`);
      }
      return html`<section class="plate__side${cols === 10 ? " plate__side--10" : ""}">
        <h3 class="plate__title">${title}</h3>
        <p class="plate__count">${fmt.plural(t.w, "win")}, ${fmt.plural(t.l, "loss", "losses")}, ${t.b} both right, ${t.n} neither</p>
        <div class="plate__grid${cols === 10 ? " plate__grid--10" : ""}" role="grid" aria-label="${title}, ${n} items" data-plate-grid="${which}" data-cols="${cols}">${rows}</div>
      </section>`;
    }

    var idle = cells.rerun
      ? fmt.count(changed, n) + " items read differently against the rerun reference. Point at a cell, or move to it with the arrow keys, to read it."
      : "This run log has no rerun labels for this reference, so there is one reading only.";
    return html`<div class="plate" data-plate data-key="${key}" data-sig="${cells.stored + "|" + (cells.rerun || "")}">
      <div class="plate__bar">
        ${legend([
          { swatch: "win", label: "Candidate only" }, { swatch: "loss", label: "Reference only" },
          { swatch: "both", label: "Both right" }, { swatch: "neither", label: "Neither" }
        ].concat(cells.rerun ? [{ swatch: "changed", label: "Changed between readings" }] : []))}
        ${cells.rerun ? html`<label class="check"><input type="checkbox" data-plate-dim data-key="${key + "-dim"}"${attrs({ checked: !!p.dim })}> Dim cells that did not change</label>` : ""}
      </div>
      <div class="plate__pair">
        ${side("stored", p.storedTitle || "Against the stored reference", cells.stored)}
        ${cells.rerun ? side("rerun", p.rerunTitle || "Against the rerun reference", cells.rerun) : ""}
      </div>
      <p class="plate__reading" data-plate-reading data-idle="${idle}">${idle}</p>
    </div>`;
  }

  /* Behaviour ------------------------------------------------------------------------ */

  var bound = typeof WeakSet === "function" ? new WeakSet() : null;
  var settled = {};
  var resizeHooked = false;

  function emit(el, name, detail) {
    el.dispatchEvent(new CustomEvent("da:" + name, { bubbles: true, detail: detail }));
  }

  function closest(node, selector) {
    return node && node.closest ? node.closest(selector) : null;
  }

  function reducedMotion() {
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function copyText(text) {
    var area, ok;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () { return legacy(); });
    }
    return legacy();
    function legacy() {
      area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.className = "visually-hidden";
      document.body.appendChild(area);
      area.select();
      try {
        ok = document.execCommand("copy");
      } catch (err) {
        ok = false;
      }
      document.body.removeChild(area);
      return ok ? Promise.resolve() : Promise.reject(new Error("copy refused"));
    }
  }

  function choose(group, option, attr) {
    Array.prototype.forEach.call(group.children, function (o) {
      o.setAttribute(attr, o === option ? "true" : "false");
      o.tabIndex = o === option ? 0 : -1;
    });
  }

  function step(list, current, key) {
    var i = list.indexOf(current);
    if (key === "ArrowRight" || key === "ArrowDown") return list[Math.min(list.length - 1, i + 1)];
    if (key === "ArrowLeft" || key === "ArrowUp") return list[Math.max(0, i - 1)];
    if (key === "Home") return list[0];
    if (key === "End") return list[list.length - 1];
    return null;
  }

  function plateLink(cell, on) {
    var plateEl = closest(cell, "[data-plate]"), i = cell.getAttribute("data-i"), line;
    if (!plateEl) return;
    Array.prototype.forEach.call(plateEl.querySelectorAll(".plate__cell.is-linked"), function (c) { c.classList.remove("is-linked"); });
    line = plateEl.querySelector("[data-plate-reading]");
    if (!on) {
      if (line) line.textContent = line.getAttribute("data-idle");
      return;
    }
    Array.prototype.forEach.call(plateEl.querySelectorAll(".plate__cell[data-i=\"" + i + "\"]"), function (c) {
      if (c !== cell) c.classList.add("is-linked");
    });
    if (line) line.textContent = cell.getAttribute("aria-label");
  }

  function cellDetail(cell) {
    var plateEl = closest(cell, "[data-plate]"), i = Number(cell.getAttribute("data-i"));
    var sig = plateEl.getAttribute("data-sig").split("|");
    return {
      index: i, stored: sig[0].charAt(i), rerun: sig[1] ? sig[1].charAt(i) : null,
      which: closest(cell, "[data-plate-grid]").getAttribute("data-plate-grid")
    };
  }

  function onClick(event) {
    var target = event.target, el;
    if ((el = closest(target, "[data-copy]"))) {
      copyText(el.getAttribute("data-copy")).then(function () {
        el.textContent = el.getAttribute("data-done");
        announce(el.getAttribute("data-done"));
        setTimeout(function () { el.textContent = el.getAttribute("data-label"); }, 1600);
      }, function () {
        toast("Copying was blocked by the browser. Select the text and copy it by hand.", { kind: "error" });
      });
      return;
    }
    if ((el = closest(target, "[data-dismiss]"))) {
      emit(el, "dismiss", { name: el.getAttribute("data-dismiss-name") });
      el = closest(el, ".notice, .toast");
      if (el && el.parentNode) el.parentNode.removeChild(el);
      return;
    }
    if ((el = closest(target, ".segmented__option"))) {
      if (el.getAttribute("aria-disabled") === "true") return;
      choose(el.parentNode, el, "aria-checked");
      emit(el, "select", { name: el.parentNode.getAttribute("data-segmented"), value: el.getAttribute("data-value") });
      return;
    }
    if ((el = closest(target, "[data-tabs] > [role=tab]"))) {
      choose(el.parentNode, el, "aria-selected");
      emit(el, "select", { name: el.parentNode.getAttribute("data-tabs"), value: el.getAttribute("data-value") });
      return;
    }
    if ((el = closest(target, ".ruler__cell[data-round]"))) {
      emit(el, "round", { round: el.getAttribute("aria-selected") === "true" ? null : Number(el.getAttribute("data-round")) });
      return;
    }
    if ((el = closest(target, ".plate__cell"))) emit(el, "cell", cellDetail(el));
  }

  function onKeydown(event) {
    var target = event.target, key = event.key, next, list, cols, i, grid;
    if (closest(target, ".segmented") && target.getAttribute("role") === "radio") {
      list = Array.prototype.filter.call(target.parentNode.children, function (o) { return o.getAttribute("aria-disabled") !== "true"; });
      next = step(list, target, key);
      if (!next) return;
      event.preventDefault();
      if (next !== target) {
        next.focus();
        next.click();
      }
      return;
    }
    if (target.getAttribute("role") === "tab" && closest(target, "[data-tabs]")) {
      next = step(Array.prototype.slice.call(target.parentNode.children), target, key);
      if (!next) return;
      event.preventDefault();
      if (next !== target) {
        next.focus();
        next.click();
      }
      return;
    }
    if (target.classList.contains("ruler__cell") && target.hasAttribute("data-round")) {
      if (key === "Escape") {
        emit(target, "round", { round: null });
        return;
      }
      if (key === "Enter" || key === " ") {
        event.preventDefault();
        target.click();
        return;
      }
      list = Array.prototype.slice.call(closest(target, "[data-ruler]").querySelectorAll(".ruler__cell[data-round]"));
      next = step(list, target, key === "ArrowUp" || key === "ArrowDown" ? "" : key);
      if (!next) return;
      event.preventDefault();
      if (next !== target) {
        list.forEach(function (c) { c.tabIndex = c === next ? 0 : -1; });
        next.focus();
        emit(next, "round", { round: Number(next.getAttribute("data-round")) });
      }
      return;
    }
    if (target.classList.contains("plate__cell")) {
      grid = closest(target, "[data-plate-grid]");
      list = Array.prototype.slice.call(grid.querySelectorAll(".plate__cell"));
      cols = Number(grid.getAttribute("data-cols"));
      i = list.indexOf(target);
      if (key === "Enter" || key === " ") {
        event.preventDefault();
        emit(target, "cell", cellDetail(target));
        return;
      }
      if (key === "ArrowRight") next = list[i + 1];
      else if (key === "ArrowLeft") next = list[i - 1];
      else if (key === "ArrowDown") next = list[i + cols];
      else if (key === "ArrowUp") next = list[i - cols];
      else if (key === "Home") next = list[event.ctrlKey ? 0 : i - (i % cols)];
      else if (key === "End") next = list[event.ctrlKey ? list.length - 1 : Math.min(list.length - 1, i - (i % cols) + cols - 1)];
      else return;
      event.preventDefault();
      if (next) {
        target.tabIndex = -1;
        next.tabIndex = 0;
        next.focus();
      }
    }
  }

  function onPoint(event) {
    var cell = closest(event.target, ".plate__cell");
    if (cell) plateLink(cell, event.type === "mouseover" || event.type === "focusin");
  }

  function onChange(event) {
    var el = event.target, plateEl;
    if (el.hasAttribute && el.hasAttribute("data-plate-dim")) {
      plateEl = closest(el, "[data-plate]");
      plateEl.classList.toggle("plate--dim", el.checked);
      emit(el, "dim", { on: el.checked });
    }
  }

  // Geometry that depends on the rendered width: labels that span several cells of the ruler.
  function fitRuler(rulerEl) {
    Array.prototype.forEach.call(rulerEl.querySelectorAll(".ruler__env"), function (label) {
      label.style.maxWidth = "calc(" + (Number(label.getAttribute("data-span")) * 100) + "% - 6px)";
    });
    Array.prototype.forEach.call(rulerEl.querySelectorAll(".ruler__band-label"), function (label) {
      var room = label.parentNode.offsetWidth * Number(label.getAttribute("data-span")) - 12;
      label.style.visibility = label.scrollWidth > room ? "hidden" : "";
    });
  }

  // The one animation: when a plate shows a new reading, its changed cells settle in.
  function settlePlate(plateEl) {
    var key = plateEl.getAttribute("data-key"), sig = plateEl.getAttribute("data-sig");
    if (plateEl.querySelector("[data-plate-dim]:checked")) plateEl.classList.add("plate--dim");
    if (settled[key] === sig) return;
    settled[key] = sig;
    if (reducedMotion() || !plateEl.animate) return;
    Array.prototype.forEach.call(plateEl.querySelectorAll(".plate__grid"), function (grid) {
      var cells = grid.querySelectorAll(".is-changed"), n = cells.length;
      Array.prototype.forEach.call(cells, function (cell, i) {
        cell.animate([{ transform: "scale(1.7)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }], {
          duration: 140, delay: n > 1 ? Math.round(160 * i / (n - 1)) : 0,
          easing: "cubic-bezier(0.2, 0.8, 0.2, 1)", fill: "backwards"
        });
      });
    });
  }

  // A region that scrolls sideways has to be reachable from the keyboard.
  function fitScroll(el) {
    if (el.scrollWidth > el.clientWidth + 1) {
      el.tabIndex = 0;
      el.setAttribute("role", "region");
      if (!el.hasAttribute("aria-label")) {
        el.setAttribute("aria-label", el.getAttribute("data-scroll") || "Table, scrolls sideways");
        el.setAttribute("data-scroll-named", "");
      }
    } else {
      el.removeAttribute("tabindex");
      el.removeAttribute("role");
      if (el.hasAttribute("data-scroll-named")) {
        el.removeAttribute("aria-label");
        el.removeAttribute("data-scroll-named");
      }
    }
  }

  function fitAll(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-ruler]"), fitRuler);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-scroll]"), fitScroll);
  }

  // Wire the components inside rootEl. Safe to call again after every mount.
  function bind(rootEl) {
    if (!bound || !bound.has(rootEl)) {
      if (bound) bound.add(rootEl);
      rootEl.addEventListener("click", onClick);
      rootEl.addEventListener("keydown", onKeydown);
      rootEl.addEventListener("mouseover", onPoint);
      rootEl.addEventListener("mouseout", onPoint);
      rootEl.addEventListener("focusin", onPoint);
      rootEl.addEventListener("focusout", onPoint);
      rootEl.addEventListener("change", onChange);
    }
    if (!resizeHooked) {
      resizeHooked = true;
      var queued = false;
      root.addEventListener("resize", function () {
        if (queued) return;
        queued = true;
        requestAnimationFrame(function () {
          queued = false;
          fitAll(document);
        });
      });
    }
    fitAll(rootEl);
    Array.prototype.forEach.call(rootEl.querySelectorAll("[data-plate]"), settlePlate);
  }

  // Listen for a component event: on(rootEl, "cell", fn) calls fn(detail, event).
  function on(el, name, fn) {
    el.addEventListener("da:" + name, function (event) { fn(event.detail, event); });
  }

  function layer(id, className, live) {
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      el.className = className;
      if (live) el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    return el;
  }

  function announce(message) {
    var el = layer("da-live", "visually-hidden", true);
    el.textContent = "";
    setTimeout(function () { el.textContent = message; }, 30);
  }

  // A short message at the bottom of the window. kind "error" stays until dismissed.
  function toast(message, t) {
    var box = layer("da-toasts", "toasts", true), el = document.createElement("div");
    var text = document.createElement("span"), close = document.createElement("button");
    t = t || {};
    el.className = "toast" + (t.kind === "error" ? " toast--error" : "");
    text.textContent = message;
    close.type = "button";
    close.className = "toast__dismiss";
    close.textContent = "Dismiss";
    close.addEventListener("click", remove);
    el.appendChild(text);
    el.appendChild(close);
    box.appendChild(el);
    if (t.kind !== "error") setTimeout(remove, t.timeout || 5000);
    function remove() {
      if (el.parentNode) el.parentNode.removeChild(el);
    }
    return el;
  }

  DA.ui = {
    html: html, raw: raw, join: join, attrs: attrs, mount: mount, bind: bind, on: on, fmt: fmt,
    tag: tag, sourceTag: sourceTag, sourceNotice: sourceNotice, mark: mark, markOf: markOf, legend: legend,
    readout: readout, readouts: readouts, notice: notice, ledger: ledger, kv: kv,
    copyButton: copyButton, copyable: copyable, code: code, disclosure: disclosure,
    segmented: segmented, policySwitcher: policySwitcher, policyOptions: policyOptions, tabs: tabs, select: select,
    ruler: ruler, rulerModel: rulerModel, rulerLegend: function () { return legend(RULER_LEGEND); }, envNames: envNames, reading: reading,
    plate: plate, dropOverlay: dropOverlay, toast: toast, announce: announce,
    isSafe: function (value) { return value instanceof Safe; }
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
