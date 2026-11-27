(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  // Every builder returns a <figure>: a legend, the drawing at two widths (CSS shows the one
  // that fits) and a visually hidden table with the same numbers. Pass { width } for one
  // drawing only. Colours live in components.css; nothing here names a colour.
  var WIDE = 760, NARROW = 360;

  function px(x) {
    return Math.round(x * 100) / 100;
  }

  function extent(values) {
    var lo = Infinity, hi = -Infinity;
    values.forEach(function (v) {
      if (v === null || v === undefined || isNaN(v)) return;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    });
    return lo === Infinity ? [0, 0] : [lo, hi];
  }

  // Round tick positions that cover [lo, hi] in about `count` steps.
  function axis(lo, hi, count) {
    var span = hi - lo || 1, rough = span / count, pow = Math.pow(10, Math.floor(Math.log(rough) / Math.LN10));
    var f = rough / pow, step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow, ticks = [], v;
    lo = Math.floor(lo / step) * step;
    hi = Math.ceil(hi / step) * step;
    for (v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v / step) * step);
    return { lo: lo, hi: hi, step: step, ticks: ticks, digits: step < 1 ? (step < 0.1 ? 2 : 1) : 0 };
  }

  function textWidth(text, size) {
    return String(text).length * size * 0.54;
  }

  function clip(text, max) {
    text = String(text);
    return text.length > max ? text.slice(0, max - 1) + "…" : text;
  }

  function figure(kind, label, legend, draw, table, opts) {
    var body = opts && opts.width
      ? draw(opts.width, opts.width < 520, label)
      : html`<div class="chart__wide">${draw(WIDE, false, label)}</div><div class="chart__narrow">${draw(NARROW, true, label)}</div>`;
    return html`<figure class="chart chart--${kind}">
      ${legend && !(opts && opts.legend === false) ? ui.legend(legend, "chart__legend") : ""}
      ${body}
      ${table}
    </figure>`;
  }

  function hiddenTable(caption, head, rows) {
    return html`<div class="visually-hidden"><table><caption>${caption}</caption>
      <thead><tr>${head.map(function (h) { return html`<th scope="col">${h}</th>`; })}</tr></thead>
      <tbody>${rows.map(function (r) { return html`<tr>${r.map(function (c) { return html`<td>${c}</td>`; })}</tr>`; })}</tbody>
    </table></div>`;
  }

  /* Net gain per round --------------------------------------------------------------- */

  // What netGain draws, from an audit: net gain against the stored and the rerun reading of
  // the reference, in percentage points of the evaluation set.
  function netGainData(audit, policyId, selected) {
    var policy = audit.policies[policyId], names = ui.envNames(audit), n = audit.run.n_items, envOf = {};
    audit.rounds.forEach(function (r) { envOf[r.round] = r; });
    return {
      rounds: policy.decisions.map(function (d) {
        return {
          round: d.round, env: names[d.env] || d.env,
          stored: 100 * (d.wins - d.losses) / n, rerun: 100 * (d.rerun_wins - d.rerun_losses) / n,
          mark: d.false_accept ? "false-accept" : d.accepted ? "improved" : null
        };
      }),
      flags: audit.rounds.filter(function (r) { return r.env_changed; }).map(function (r) {
        return { round: r.round, name: names[r.env] || r.env };
      }),
      first: audit.rounds.length ? names[audit.rounds[0].env] || audit.rounds[0].env : "",
      selected: selected === undefined ? null : selected
    };
  }

  function drawNetGain(d, W, compact, label) {
    var H = compact ? 236 : 300;
    var m = compact ? { l: 30, r: 4, t: 30, b: 38 } : { l: 64, r: 8, t: 30, b: 44 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b, N = d.rounds.length || 1, slot = pw / N;
    var values = [0], scale, bw = Math.max(3, Math.min(18, Math.floor(slot * 0.3))), every = Math.max(1, Math.ceil(20 / slot));
    var parts = [], index = {};
    d.rounds.forEach(function (r, i) {
      values.push(r.stored, r.rerun);
      index[r.round] = i;
    });
    scale = axis(Math.min(-1, extent(values)[0]), Math.max(1, extent(values)[1]), compact ? 4 : 5);
    function Y(v) {
      return m.t + ph * (scale.hi - v) / (scale.hi - scale.lo);
    }
    function bar(cls, x, v, inset) {
      var y = Math.min(Y(v), Y(0)), h = Math.max(Math.abs(Y(v) - Y(0)), 1);
      return html`<rect class="${cls}" x="${px(x + inset)}" y="${px(y + (h > 2 * inset ? inset : 0))}" width="${px(bw - 2 * inset)}" height="${px(Math.max(h - (h > 2 * inset ? 2 * inset : 0), 1))}"/>`;
    }

    scale.ticks.forEach(function (t) {
      if (t !== 0) parts.push(html`<line class="c-grid" x1="${m.l}" x2="${m.l + pw}" y1="${px(Y(t))}" y2="${px(Y(t))}"/>`);
      parts.push(html`<text x="${m.l - 8}" y="${px(Y(t))}" dy="0.32em" text-anchor="end">${fmt.pp(t, scale.digits)}</text>`);
    });
    parts.push(html`<text x="${m.l - 8}" y="${m.t - 10}" text-anchor="end">pp</text>`);

    d.rounds.forEach(function (r, i) {
      var cx = m.l + slot * (i + 0.5), base = m.t + ph;
      parts.push(bar("c-stored", cx - bw - 1, r.stored, 0));
      parts.push(bar("c-rerun", cx + 1, r.rerun, 0.75));
      if (i % every === 0) parts.push(html`<text x="${px(cx)}" y="${base + 16}" text-anchor="middle">${r.round}</text>`);
      if (r.mark === "improved") parts.push(html`<g class="mark--improved"><circle class="mark__shape" cx="${px(cx)}" cy="${base + 31}" r="4"/></g>`);
      if (r.mark === "false-accept") parts.push(html`<g class="mark--false-accept"><path class="mark__shape" d="M${px(cx)} ${base + 25.5}l5.5 5.5-5.5 5.5-5.5-5.5z"/></g>`);
    });
    parts.push(html`<line class="c-zero" x1="${m.l}" x2="${m.l + pw}" y1="${px(Y(0))}" y2="${px(Y(0))}"/>`);
    if (!compact) {
      parts.push(html`<text x="${m.l - 8}" y="${m.t + ph + 16}" text-anchor="end">Round</text>`);
      parts.push(html`<text x="${m.l - 8}" y="${m.t + ph + 35}" text-anchor="end">Promoted</text>`);
    }

    parts.push(html`<text class="c-strong" x="${m.l + 2}" y="19">${clip(d.first, compact ? 12 : 22)}</text>`);
    d.flags.forEach(function (f) {
      var i = index[f.round], x, name = clip(f.name, compact ? 12 : 22), w = Math.ceil(textWidth(name, 12)) + 14, left;
      if (i === undefined) return;
      x = Math.round(m.l + slot * i) + 0.5;
      left = x + w > W - m.r ? x - w : x;
      parts.push(html`<line class="c-change" x1="${x}" x2="${x}" y1="24" y2="${m.t + ph}"/>
        <rect class="c-flag" x="${left}" y="5.5" width="${w}" height="19"/>
        <text class="c-flag-text" x="${left + 7}" y="19">${name}</text>`);
    });
    if (d.selected !== null && index[d.selected] !== undefined) {
      parts.push(html`<rect class="c-cursor" x="${px(Math.round(m.l + slot * index[d.selected]) + 1.5)}" y="${m.t + 0.5}" width="${px(Math.round(slot) - 2)}" height="${ph + 40}"/>`);
    }
    return html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">${parts}</svg>`;
  }

  // d: { rounds: [{ round, env, stored, rerun, mark }], flags: [{ round, name }], first, selected }
  function netGain(d, opts) {
    var label = "Net gain of each candidate, in percentage points, against the stored and the rerun reference. " +
      d.rounds.map(function (r) {
        return "Round " + r.round + ": " + fmt.pp(r.stored, 1) + " stored, " + fmt.pp(r.rerun, 1) + " rerun" +
          (r.mark === "false-accept" ? ", false accept" : r.mark ? ", promoted" : "") + ".";
      }).join(" ");
    var table = hiddenTable("Net gain per round, percentage points", ["Round", "Environment", "Against the stored reference", "Against the rerun reference", "Decision"],
      d.rounds.map(function (r) {
        return [r.round, r.env, fmt.pp(r.stored, 1), fmt.pp(r.rerun, 1), r.mark === "false-accept" ? "promoted, false accept" : r.mark ? "promoted" : "kept"];
      }));
    return figure("netgain", label, [
      { swatch: "stored", label: "Against the stored reference" },
      { swatch: "rerun", label: "Against the rerun reference" },
      { mark: "improved", label: "Promoted, an improvement" },
      { mark: "false-accept", label: "False accept" },
      { swatch: "stale", label: "Environment changed" }
    ], function (W, compact, text) { return drawNetGain(d, W, compact, text); }, table, opts);
  }

  /* Intervals ------------------------------------------------------------------------ */

  function drawIntervals(rows, W, compact, label, unit) {
    var labelW = compact ? 0 : 150, valueW = compact ? 0 : 176, rowH = compact ? 54 : 38;
    var m = { l: labelW + 10, r: valueW + 10, t: 6, b: 26 }, pw = W - m.l - m.r, H = m.t + rowH * rows.length + m.b;
    var all = [], lim, scale, parts = [];
    rows.forEach(function (r) { all = all.concat([r.mean, r.lo, r.hi], r.values || []); });
    lim = Math.max(Math.abs(extent(all)[0]), Math.abs(extent(all)[1])) || 1;
    scale = axis(-lim, lim, compact ? 4 : 6);
    lim = Math.max(-scale.lo, scale.hi);
    function X(v) {
      return m.l + pw * (v + lim) / (2 * lim);
    }
    scale.ticks.forEach(function (t) {
      if (Math.abs(t) > lim) return;
      parts.push(html`<line class="${t === 0 ? "c-zero" : "c-grid"}" x1="${px(X(t))}" x2="${px(X(t))}" y1="${m.t}" y2="${H - m.b}"/>
        <text x="${px(X(t))}" y="${H - 8}" text-anchor="middle">${fmt.pp(t, scale.digits)}</text>`);
    });
    parts.push(html`<text x="${W - m.r + 8}" y="${H - 8}">${unit}</text>`);
    rows.forEach(function (r, i) {
      var top = m.t + rowH * i, y = top + (compact ? 36 : rowH / 2), clear = r.lo !== null && r.hi !== null && (r.lo > 0 || r.hi < 0);
      var value = fmt.pp(r.mean) + (r.lo === null || r.lo === undefined ? "" : " (" + fmt.interval(r.lo, r.hi) + ")");
      if (compact) {
        parts.push(html`<text class="c-strong" x="${m.l}" y="${top + 16}">${clip(r.label, 22)}</text>
          <text class="c-value" x="${W - m.r}" y="${top + 16}" text-anchor="end">${value}</text>`);
      } else {
        parts.push(html`<text class="c-strong" x="0" y="${y}" dy="0.32em">${clip(r.label, 24)}</text>
          <text class="c-value" x="${W - valueW}" y="${y}" dy="0.32em">${value}</text>`);
      }
      (r.values || []).forEach(function (v) {
        parts.push(html`<line class="c-rug" x1="${px(X(v))}" x2="${px(X(v))}" y1="${y + 6}" y2="${y + 12}"/>`);
      });
      if (r.lo !== null && r.lo !== undefined) {
        parts.push(html`<line class="c-whisker" x1="${px(X(r.lo))}" x2="${px(X(r.hi))}" y1="${y}" y2="${y}"/>
          <line class="c-whisker" x1="${px(X(r.lo))}" x2="${px(X(r.lo))}" y1="${y - 4}" y2="${y + 4}"/>
          <line class="c-whisker" x1="${px(X(r.hi))}" x2="${px(X(r.hi))}" y1="${y - 4}" y2="${y + 4}"/>`);
      }
      parts.push(html`<circle class="c-dot${clear ? "" : " c-dot--hollow"}" cx="${px(X(r.mean))}" cy="${y}" r="4.5"/>`);
    });
    return html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">${parts}</svg>`;
  }

  // rows: [{ label, mean, lo, hi, values }]. The dot is filled when the interval excludes zero.
  function intervals(rows, opts) {
    opts = opts || {};
    var unit = opts.unit || "pp", what = opts.caption || "Mean with 95% interval";
    var label = what + ". " + rows.map(function (r) {
      return r.label + ": " + fmt.pp(r.mean) + " " + unit + (r.lo === null || r.lo === undefined ? "" : ", 95% interval " + fmt.interval(r.lo, r.hi)) + ".";
    }).join(" ");
    var table = hiddenTable(what, ["Row", "Mean", "95% interval", "Per run"], rows.map(function (r) {
      return [r.label, fmt.pp(r.mean), fmt.interval(r.lo, r.hi), (r.values || []).map(function (v) { return fmt.pp(v); }).join(", ")];
    }));
    return figure("intervals", label, [
      { swatch: "loss", label: "Mean, interval excludes zero" },
      { swatch: "neither", label: "Mean, interval includes zero" },
      { swatch: "line-steel", label: "One run" }
    ], function (W, compact, text) { return drawIntervals(rows, W, compact, text, unit); }, table, opts);
  }

  /* Mean by reference age ------------------------------------------------------------ */

  function drawAgeLines(series, W, compact, label, o) {
    var H = compact ? 230 : 280, m = compact ? { l: 34, r: 10, t: 10, b: 44 } : { l: 48, r: 16, t: 10, b: 46 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b, xs = [], ys = [0], xr, scale, parts = [];
    series.forEach(function (s) {
      s.points.forEach(function (p) {
        if (xs.indexOf(p.x) < 0) xs.push(p.x);
        ys.push(p.mean, p.lo, p.hi);
      });
    });
    xs.sort(function (a, b) { return a - b; });
    xr = [xs[0], xs[xs.length - 1] === xs[0] ? xs[0] + 1 : xs[xs.length - 1]];
    scale = axis(extent(ys)[0], extent(ys)[1], compact ? 4 : 5);
    function X(v) {
      return m.l + pw * (v - xr[0]) / (xr[1] - xr[0]);
    }
    function Y(v) {
      return m.t + ph * (scale.hi - v) / (scale.hi - scale.lo);
    }
    scale.ticks.forEach(function (t) {
      parts.push(html`<line class="${t === 0 ? "c-zero" : "c-grid"}" x1="${m.l}" x2="${m.l + pw}" y1="${px(Y(t))}" y2="${px(Y(t))}"/>
        <text x="${m.l - 8}" y="${px(Y(t))}" dy="0.32em" text-anchor="end">${fmt.pp(t, scale.digits)}</text>`);
    });
    xs.forEach(function (x) {
      parts.push(html`<line class="c-axis" x1="${px(X(x))}" x2="${px(X(x))}" y1="${m.t + ph}" y2="${m.t + ph + 5}"/>
        <text x="${px(X(x))}" y="${m.t + ph + 19}" text-anchor="middle">${x}</text>`);
    });
    parts.push(html`<text x="${m.l}" y="${H - 6}">${o.xLabel}</text>`);
    series.forEach(function (s) {
      var pts = s.points.filter(function (p) { return p.lo !== null && p.lo !== undefined; });
      if (pts.length > 1) {
        parts.push(html`<path class="c-band${s.plain ? " c-band--plain" : ""}" fill-opacity="0.8" d="M${pts.map(function (p) { return px(X(p.x)) + " " + px(Y(p.hi)); }).join("L")}L${pts.slice().reverse().map(function (p) { return px(X(p.x)) + " " + px(Y(p.lo)); }).join("L")}Z"/>`);
      }
    });
    series.forEach(function (s) {
      parts.push(html`<polyline class="c-line${s.plain ? " c-line--plain" : ""}" points="${s.points.map(function (p) { return px(X(p.x)) + "," + px(Y(p.mean)); }).join(" ")}"/>`);
      s.points.forEach(function (p) {
        parts.push(html`<circle class="c-point${s.plain ? " c-point--plain" : ""}" cx="${px(X(p.x))}" cy="${px(Y(p.mean))}" r="3.5"/>`);
      });
    });
    return html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">${parts}</svg>`;
  }

  // series: [{ label, plain, points: [{ x, mean, lo, hi }] }]. Give the control series
  // plain: true; it is drawn hollow in steel so the two survive greyscale.
  function ageLines(series, opts) {
    opts = opts || {};
    var o = { xLabel: opts.xLabel || "Reference age, rounds", unit: opts.unit || "pp" }, what = opts.caption || "Mean with 95% interval by reference age";
    var label = what + ". " + series.map(function (s) {
      return s.label + ": " + s.points.map(function (p) {
        return "age " + p.x + ", " + fmt.pp(p.mean) + (p.lo === null || p.lo === undefined ? "" : " (" + fmt.interval(p.lo, p.hi) + ")");
      }).join("; ") + ".";
    }).join(" ");
    var rows = [];
    series.forEach(function (s) {
      s.points.forEach(function (p) { rows.push([s.label, p.x, fmt.pp(p.mean), fmt.interval(p.lo, p.hi)]); });
    });
    var legend = [];
    series.forEach(function (s) {
      legend.push({ swatch: s.plain ? "band-plain" : "band", label: s.label });
    });
    return figure("agelines", label, legend, function (W, compact, text) { return drawAgeLines(series, W, compact, text, o); },
      hiddenTable(what, ["Series", "Reference age", "Mean, " + o.unit, "95% interval"], rows), opts);
  }

  /* Horizontal bars ------------------------------------------------------------------ */

  function drawBars(rows, W, compact, label, o) {
    var labelW = compact ? 0 : 200, valueW = compact ? 96 : 120, rowH = compact ? 46 : 30;
    var pw = W - labelW - valueW, H = rowH * rows.length + 4, parts = [];
    rows.forEach(function (r, i) {
      var top = rowH * i, y = top + (compact ? 24 : 8), len = Math.max(1, pw * r.value / o.max), sd = r.sd ? pw * r.sd / o.max : 0;
      parts.push(compact
        ? html`<text class="c-strong" x="0" y="${top + 14}">${clip(r.label, 30)}</text>`
        : html`<text class="c-strong" x="0" y="${y + 7}" dy="0.32em">${clip(r.label, 32)}</text>`);
      parts.push(html`<rect class="c-bar${r.tone ? " c-bar--" + r.tone : ""}" x="${labelW}" y="${y}" width="${px(len)}" height="14"/>`);
      if (sd) {
        parts.push(html`<line class="c-halo" x1="${px(labelW + len - sd)}" x2="${px(labelW + len + sd)}" y1="${y + 7}" y2="${y + 7}"/>
          <line class="c-whisker" x1="${px(labelW + len - sd)}" x2="${px(labelW + len + sd)}" y1="${y + 7}" y2="${y + 7}"/>
          <line class="c-whisker" x1="${px(labelW + len - sd)}" x2="${px(labelW + len - sd)}" y1="${y + 3}" y2="${y + 11}"/>
          <line class="c-whisker" x1="${px(labelW + len + sd)}" x2="${px(labelW + len + sd)}" y1="${y + 3}" y2="${y + 11}"/>`);
      }
      parts.push(html`<text class="c-value" x="${px(labelW + len + sd + 8)}" y="${y + 7}" dy="0.32em">${r.text}</text>`);
    });
    return html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">${parts}</svg>`;
  }

  // rows: [{ label, value, sd, tone: "blue" | "steel" | "red", text }]; opts.max sets the scale.
  function bars(rows, opts) {
    opts = opts || {};
    var format = opts.format || function (r) { return fmt.num(r.value, 1); };
    var o = { max: opts.max || Math.max.apply(null, rows.map(function (r) { return r.value + (r.sd || 0); })) || 1 };
    rows = rows.map(function (r) { return Object.assign({}, r, { text: r.text || format(r) }); });
    var what = opts.caption || "Values";
    var label = what + ". " + rows.map(function (r) { return r.label + ": " + r.text + "."; }).join(" ");
    return figure("bars", label, null, function (W, compact, text) { return drawBars(rows, W, compact, text, o); },
      hiddenTable(what, ["Row", "Value"], rows.map(function (r) { return [r.label, r.text]; })), opts);
  }

  DA.charts = { netGain: netGain, netGainData: netGainData, intervals: intervals, ageLines: ageLines, bars: bars };
})(typeof globalThis !== "undefined" ? globalThis : this);
