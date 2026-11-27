(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  var VIEWS = ["summary", "rounds", "policies", "probe", "environments", "export"];
  var STEPS = 9;

  // "#/workbench/rounds" gives { page, view, step }; an unknown hash gives null.
  function parse(hash) {
    var parts = String(hash || "").replace(/^#\/?/, "").split("/").filter(Boolean), step;
    if (!parts.length) return { page: "workbench", view: "summary", step: 1 };
    if (parts[0] === "workbench" && parts.length <= 2) {
      if (parts.length === 1) return { page: "workbench", view: "summary", step: 1 };
      return VIEWS.indexOf(parts[1]) >= 0 ? { page: "workbench", view: parts[1], step: 1 } : null;
    }
    if (parts[0] === "case-study" && parts.length <= 2) {
      if (parts.length === 1) return { page: "case-study", view: "summary", step: 1 };
      step = /^[1-9]$/.test(parts[1]) ? Number(parts[1]) : 0;
      return step >= 1 && step <= STEPS ? { page: "case-study", view: "summary", step: step } : null;
    }
    if (parts[0] === "install" && parts.length === 1) return { page: "install", view: "summary", step: 1 };
    return null;
  }

  function href(route) {
    if (route.page === "case-study") return "#/case-study" + (route.step && route.step > 1 ? "/" + route.step : "");
    if (route.page === "install") return "#/install";
    return !route.view || route.view === "summary" ? "#/" : "#/workbench/" + route.view;
  }

  function sync() {
    var route = parse(root.location.hash);
    if (!route) {
      route = parse("");
      root.history.replaceState(null, "", root.location.pathname + root.location.search + "#/");
    }
    DA.state.set({ route: route });
  }

  function go(route) {
    var target = href(route);
    if (root.location.hash === target) sync();
    else root.location.hash = target.slice(1);
  }

  function start() {
    root.addEventListener("hashchange", sync);
    sync();
  }

  DA.router = { VIEWS: VIEWS, parse: parse, href: href, go: go, start: start };
})(typeof globalThis !== "undefined" ? globalThis : this);
