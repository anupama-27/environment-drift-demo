(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  var state = {
    route: { page: "workbench", view: "summary", step: 1 },
    library: { groups: [] },
    selection: { group: null, run: null },
    policy: "frozen",
    options: { schedule: null, stored_scoring: "as_recorded", margin: 0, periodic_k: 3 },
    round: null,
    audit: null,
    study: null,
    error: null
  };
  var subscribers = [];
  var derivers = [];
  var notified = state;
  var pending = false;

  function get() {
    return state;
  }

  // Shallow merge. Subscribers hear about it once per tick, however many patches arrive.
  function set(patch) {
    var next = Object.assign({}, state, patch), i, extra;
    for (i = 0; i < derivers.length; i++) {
      extra = derivers[i](next, state);
      if (extra) Object.assign(next, extra);
    }
    state = next;
    if (!pending) {
      pending = true;
      Promise.resolve().then(flush);
    }
    return state;
  }

  function flush() {
    var previous = notified;
    pending = false;
    notified = state;
    subscribers.slice().forEach(function (fn) { fn(state, previous); });
  }

  function subscribe(fn) {
    subscribers.push(fn);
    return function () {
      var i = subscribers.indexOf(fn);
      if (i >= 0) subscribers.splice(i, 1);
    };
  }

  // fn(next, previous) runs inside set, before anyone is told, and may return more keys to
  // merge. The library uses it so that a new selection never shows with the old audit.
  function derive(fn) {
    derivers.push(fn);
  }

  DA.state = { get: get, set: set, subscribe: subscribe, derive: derive };
})(typeof globalThis !== "undefined" ? globalThis : this);
