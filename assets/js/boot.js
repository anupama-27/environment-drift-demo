(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};
  var ui = DA.ui, html = ui.html, fmt = ui.fmt;

  DA.views = DA.views || {};

  var TABS = [
    { id: "summary", label: "Summary" },
    { id: "rounds", label: "Rounds" },
    { id: "policies", label: "Policies" },
    { id: "probe", label: "Drift probe" },
    { id: "environments", label: "Environments" },
    { id: "export", label: "Export" }
  ];
  var PAGES = { workbench: "Workbench", "case-study": "Case study", install: "Install" };
  var FONTS = [
    "400 16px Barlow", "500 16px Barlow", "600 16px Barlow",
    "500 16px \"Barlow Semi Condensed\"", "600 16px \"Barlow Semi Condensed\"", "400 13px \"IBM Plex Mono\""
  ];

  var els = {};
  var ready = false;
  var lastRoute = null;
  var shared = { runs: null, schedule: null, model: null };

  // What a view's render and bind receive.
  function context(state) {
    var audit = state.audit;
    return {
      state: state,
      route: state.route,
      mode: state.selection.run === "*" ? "study" : "run",
      run: DA.library.run(),
      runs: DA.library.runs(),
      audit: audit,
      study: state.study,
      policyId: state.policy,
      policy: audit && audit.policies[state.policy] ? audit.policies[state.policy] : null,
      round: state.round
    };
  }

  // The scale for several runs at once: drawn only when they all follow one schedule.
  function sharedModel(runs, schedule) {
    var first, key, same;
    if (!runs.length) return null;
    same = shared.runs && shared.schedule === schedule && shared.runs.length === runs.length &&
      shared.runs.every(function (r, i) { return r === runs[i]; });
    if (same) return shared.model;
    first = runs[0];
    key = JSON.stringify(first.schedule) + "/" + first.candidates.length;
    shared.runs = runs;
    shared.schedule = schedule;
    shared.model = runs.every(function (r) { return JSON.stringify(r.schedule) + "/" + r.candidates.length === key; })
      ? ui.rulerModel(DA.engine.audit(first, schedule ? { policies: ["frozen"], schedule: schedule } : { policies: ["frozen"] }), null)
      : null;
    return shared.model;
  }

  function runbar(state, ctx) {
    var model = null, scale, key, reading = null, selected;
    if (ctx.mode === "run" && ctx.audit) {
      model = ui.rulerModel(ctx.audit, ctx.policyId, state.round);
    } else if (ctx.mode === "study" && state.study) {
      model = sharedModel(ctx.runs, state.options.schedule);
    }
    if (!model) {
      scale = ctx.mode === "study" && state.study
        ? html`<p class="runbar__note">These runs do not follow one schedule, so there is no common scale to draw.</p>`
        : html`<div class="runbar__blank"></div>`;
      key = "";
    } else if (model.interactive) {
      scale = ui.ruler(model);
      key = html`<div class="runbar__key"><span class="runbar__under">Decisions under ${fmt.policyPhrase(ctx.policyId, ctx.policy && ctx.policy.k)}</span>${ui.rulerLegend()}</div>`;
      selected = model.rounds.filter(function (r) { return r.round === state.round; })[0];
      if (selected && selected.reading) {
        reading = html`<p class="runbar__reading" role="status">${selected.reading} <button type="button" class="linklike" data-clear-round data-key="clear-round">Clear selection</button></p>`;
      }
    } else {
      scale = ui.ruler(model);
      key = html`<p class="runbar__note">${ctx.mode === "study"
        ? "The schedule these runs share. Pick one run to see its decisions on the scale."
        : "This policy cannot be replayed on this run, so the scale shows the schedule only."}</p>`;
    }
    return html`<div class="wrap">
      <div class="runbar__top">${DA.library.picker(state)}${DA.library.facts(state)}</div>
      ${scale}
      ${key}
      ${reading}
      ${ui.tabs({
        name: "view", label: "Workbench views", value: state.route.view,
        items: TABS.map(function (t) { return { id: t.id, label: t.label, href: DA.router.href({ page: "workbench", view: t.id }) }; })
      })}
    </div>`;
  }

  function quiet(text) {
    return ui.notice({ kind: "quiet", body: text });
  }

  function outlet(state, ctx) {
    var page = state.route.page, view = null, id, body, error = "";
    if (state.error) {
      error = ui.notice({ kind: "error", title: state.error.title, body: state.error.message, dismiss: "error", key: "error" });
    }
    if (page === "workbench") {
      id = state.route.view;
      view = DA.views[id] || null;
      if (ctx.mode === "study" ? !ctx.study : !ctx.audit) {
        view = null;
        body = state.error ? "" : quiet("Reading the run log.");
      } else if (!view) {
        body = quiet("The " + TABS.filter(function (t) { return t.id === id; })[0].label + " view is not part of this build yet.");
      }
    } else {
      id = page;
      view = DA.views[page === "case-study" ? "casestudy" : page] || DA.views[page] || null;
      if (!view) body = quiet(page === "install" ? "The install page is not part of this build yet." : "The case study is not part of this build yet.");
    }
    if (view) {
      try {
        body = view.render(ctx);
        if (!ui.isSafe(body)) throw new TypeError("its render must return DA.ui.html markup, not a plain string");
      } catch (err) {
        if (root.console) root.console.error(err);
        view = null;
        body = ui.notice({ kind: "error", title: "This view could not be drawn", body: (err && err.message) || String(err) });
      }
    }
    return { view: view, markup: html`<div class="wrap view view--${id}" data-view="${id}">${error}${body}</div>` };
  }

  function render(state) {
    var ctx = context(state), route = state.route, out, moved, onWorkbench = route.page === "workbench";
    Array.prototype.forEach.call(document.querySelectorAll("[data-nav]"), function (link) {
      if (link.getAttribute("data-nav") === route.page) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = (onWorkbench ? TABS.filter(function (t) { return t.id === route.view; })[0].label : PAGES[route.page]) + " - DriftAudit";
    if (!ready) return;

    els.runbar.hidden = !onWorkbench || !state.library.groups.length;
    if (!els.runbar.hidden) {
      ui.mount(els.runbar, runbar(state, ctx));
      ui.bind(els.runbar);
    }
    out = outlet(state, ctx);
    ui.mount(els.view, out.markup);
    ui.bind(els.view);
    if (out.view && out.view.bind) out.view.bind(els.view.firstElementChild, ctx);
    els.main.removeAttribute("aria-busy");

    moved = lastRoute && (lastRoute.page !== route.page || lastRoute.view !== route.view || lastRoute.step !== route.step);
    // The case study moves focus between its own steps; every other move lands on the heading.
    if (moved && !(lastRoute.page === "case-study" && route.page === "case-study")) focusHeading();
    if (lastRoute && lastRoute.page !== route.page) root.scrollTo(0, 0);
    lastRoute = route;
  }

  function focusHeading() {
    var heading = els.view.querySelector("h1");
    if (!heading) {
      els.main.focus({ preventScroll: true });
      return;
    }
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }

  function fonts() {
    if (!document.fonts || !document.fonts.load) return Promise.resolve();
    return Promise.race([
      Promise.all(FONTS.map(function (f) { return document.fonts.load(f); })).catch(function () {}),
      new Promise(function (resolve) { setTimeout(resolve, 1500); })
    ]);
  }

  function start() {
    var layer = document.createElement("div");
    els.runbar = document.getElementById("da-runbar");
    els.view = document.getElementById("da-view");
    els.main = document.getElementById("main");
    document.body.appendChild(layer);
    ui.mount(layer, ui.dropOverlay());
    DA.library.bind(els.runbar);

    document.addEventListener("da:round", function (event) {
      DA.state.set({ round: event.detail.round });
    });
    document.addEventListener("da:select", function (event) {
      if (event.detail.name === "policy") DA.state.set({ policy: event.detail.value });
    });
    document.addEventListener("da:dismiss", function (event) {
      if (event.detail.name === "error") DA.state.set({ error: null });
    });
    document.addEventListener("click", function (event) {
      var el = event.target.closest ? event.target.closest("[data-clear-round], [data-pick-round], [data-pick-policy], [data-pick-run]") : null;
      if (!el) return;
      if (el.hasAttribute("data-clear-round")) DA.state.set({ round: null });
      else if (el.hasAttribute("data-pick-round")) DA.state.set({ round: Number(el.getAttribute("data-pick-round")) });
      else if (el.hasAttribute("data-pick-policy")) DA.state.set({ policy: el.getAttribute("data-pick-policy") });
      else DA.library.select(DA.state.get().selection.group, el.getAttribute("data-pick-run"));
    });

    DA.state.subscribe(render);
    DA.router.start();
    Promise.all([fonts(), DA.library.boot()]).catch(function (err) {
      DA.state.set({ error: { title: "The workbench could not start", message: (err && err.message) || String(err) } });
    }).then(function () {
      ready = true;
      render(DA.state.get());
    });
  }

  DA.boot = { start: start, TABS: TABS };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})(typeof globalThis !== "undefined" ? globalThis : this);
