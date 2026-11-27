(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  // Raw model outputs, read only when a view asks for them. Every lookup is cached as a
  // promise, and its result is kept as well so that a view can draw from it synchronously.
  var pending = {};
  var resolved = {};
  var fileIndex = new WeakMap();
  var fileReady = new WeakMap();

  function canGunzip() {
    return typeof root.DecompressionStream === "function";
  }

  function isGzip(bytes) {
    return bytes.length > 1 && bytes[0] === 0x1f && bytes[1] === 0x8b;
  }

  // The most a sidecar may inflate to. A small gzip of zeros can otherwise fill the tab's memory.
  var CAP = 512 * 1024 * 1024;
  var problems = {};

  function TooLarge() {
    this.message = "The outputs file inflates to more than 512 MB, so this page does not read it.";
  }

  function bytesToText(buffer) {
    var bytes = new Uint8Array(buffer), reader, chunks = [], total = 0;
    if (!isGzip(bytes)) return Promise.resolve(new TextDecoder().decode(bytes));
    if (!canGunzip()) return Promise.reject(new Error("gzip is not supported here"));
    reader = new Blob([bytes]).stream().pipeThrough(new root.DecompressionStream("gzip")).getReader();
    function pump() {
      return reader.read().then(function (step) {
        if (step.done) return new Blob(chunks).text();
        total += step.value.length;
        if (total > CAP) {
          reader.cancel();
          throw new TooLarge();
        }
        chunks.push(step.value);
        return pump();
      });
    }
    return pump();
  }

  // A pointer in a run log is followed only when it stays beside the log: no scheme, no
  // absolute path, no way up.
  function safePointer(text) {
    return typeof text === "string" && text !== "" && !/^[a-z][a-z0-9+.-]*:/i.test(text) && text.charAt(0) !== "/" &&
      text.charAt(0) !== "\\" && text.indexOf("..") < 0;
  }

  function fetchText(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error(url + " answered " + response.status);
      return response.arrayBuffer();
    }).then(bytesToText);
  }

  function once(key, load) {
    if (!pending[key]) {
      pending[key] = load().then(function (value) {
        resolved[key] = value;
        return value;
      }, function (err) {
        if (err instanceof TooLarge) problems[key] = err.message;
        resolved[key] = null;
        return null;
      });
    }
    return pending[key];
  }

  function entryOf(run) {
    var groups = DA.state.get().library.groups, i, j;
    for (i = 0; i < groups.length; i++) {
      for (j = 0; j < groups[i].runs.length; j++) if (groups[i].runs[j].run === run) return groups[i].runs[j];
    }
    return null;
  }

  function absolute(url, base) {
    try {
      return new URL(url, base ? new URL(base, document.baseURI) : document.baseURI).href;
    } catch (err) {
      return null;
    }
  }

  // Where the outputs of a run come from: chunk files beside the run log, one sidecar file
  // the user opened, or one sidecar URL. null when the run has none.
  function source(run) {
    var entry = run ? entryOf(run) : null, out = run && run.outputs, file;
    if (!entry) return null;
    file = DA.library.sidecar ? DA.library.sidecar(entry.id) : null;
    if (file) return { kind: "sidecar", file: file, gz: /\.gz$/i.test(file.name), id: "file:" + entry.id };
    if (entry.outputs) return { kind: "sidecar", url: absolute(entry.outputs), gz: /\.gz$/i.test(entry.outputs) };
    if (!out || !entry.url) return null;
    if (out.layout === "chunks" && (entry.bundled || safePointer(out.base))) {
      return { kind: "chunks", base: absolute(out.base, entry.url), shared: entry.bundled ? out.shared || {} : safeShared(out.shared), from: entry.url, gz: true };
    }
    if (out.layout === "sidecar" && (entry.bundled || safePointer(out.file))) {
      return { kind: "sidecar", url: absolute(out.file, entry.url), gz: /\.gz$/i.test(out.file) };
    }
    return null;
  }

  function safeShared(shared) {
    var out = {};
    Object.keys(shared || {}).forEach(function (k) {
      if (safePointer(shared[k])) out[k] = shared[k];
    });
    return out;
  }

  // Why the outputs of a run could not be read, in a sentence; null when nothing went wrong.
  function problem(run) {
    var src = source(run), key;
    if (!src) return null;
    if (src.file) return problems["file:" + src.id] || null;
    key = src.kind === "sidecar" ? "sidecar:" + src.url : null;
    if (key) return problems[key] || null;
    return Object.keys(problems).length ? problems[Object.keys(problems)[0]] : null;
  }

  function status(run) {
    var src = source(run);
    if (!src) return "none";
    return src.gz && !canGunzip() ? "unsupported" : "attached";
  }

  function decodingOf(run, envId) {
    var env = run.environments && run.environments[envId];
    return env ? env.decoding : null;
  }

  function chunkUrl(src, promptId, decoding, pass) {
    var shared = src.shared[decoding + "." + pass];
    var base = typeof shared === "string" ? absolute(shared, src.from) : src.base;
    return base ? absolute(encodeURIComponent(promptId) + "/" + encodeURIComponent(decoding) + "." + pass + ".json.gz", base) : null;
  }

  function parseChunk(text) {
    var list = JSON.parse(text);
    if (!Array.isArray(list)) throw new Error("not a list of outputs");
    return list.map(function (t) { return t === null || t === undefined ? "" : String(t); });
  }

  // One pass over the JSON lines, grouped by prompt, decoding and pass.
  function indexLines(text) {
    var index = {};
    text.split("\n").forEach(function (line) {
      var row, key;
      line = line.trim();
      if (!line) return;
      try {
        row = JSON.parse(line);
      } catch (err) {
        return;
      }
      if (!row || typeof row.item !== "number") return;
      key = row.prompt + "\u0000" + row.decoding + "\u0000" + row.pass;
      (index[key] = index[key] || [])[row.item] = row.text === null || row.text === undefined ? "" : String(row.text);
    });
    return index;
  }

  function sidecarOf(src) {
    var key = src.file ? null : "sidecar:" + src.url, load;
    load = function () {
      var read = src.file ? src.file.arrayBuffer().then(bytesToText) : fetchText(src.url);
      return read.then(indexLines);
    };
    if (key) return once(key, load);
    if (!fileIndex.has(src.file)) {
      fileIndex.set(src.file, load().catch(function (err) {
        if (err instanceof TooLarge) problems["file:" + src.id] = err.message;
        return null;
      }).then(function (index) {
        fileReady.set(src.file, index);
        return index;
      }));
    }
    return fileIndex.get(src.file);
  }

  function listOf(index, promptId, decoding, pass) {
    var list = index && index[promptId + "\u0000" + decoding + "\u0000" + pass];
    return list ? Array.prototype.map.call(list, function (t) { return t === undefined ? "" : t; }) : null;
  }

  function get(run, promptId, envId, pass) {
    var src, decoding, url;
    try {
      src = source(run);
      decoding = decodingOf(run, envId);
      if (!src || !decoding || (src.gz && !canGunzip())) return Promise.resolve(null);
      pass = pass === "rerun" ? "rerun" : "current";
      if (src.kind === "chunks") {
        url = chunkUrl(src, promptId, decoding, pass);
        return url ? once(url, function () { return fetchText(url).then(parseChunk); }) : Promise.resolve(null);
      }
      return sidecarOf(src).then(function (index) { return listOf(index, promptId, decoding, pass); });
    } catch (err) {
      return Promise.resolve(null);
    }
  }

  // The same lookup without waiting: the outputs if they are already here, null if they
  // could not be read, undefined while they have not been read yet.
  function peek(run, promptId, envId, pass) {
    var src = source(run), decoding = decodingOf(run, envId), key;
    if (!src || !decoding || (src.gz && !canGunzip())) return null;
    pass = pass === "rerun" ? "rerun" : "current";
    if (src.file) return fileReady.has(src.file) ? listOf(fileReady.get(src.file), promptId, decoding, pass) : undefined;
    if (src.kind === "sidecar") {
      key = "sidecar:" + src.url;
      return Object.prototype.hasOwnProperty.call(resolved, key) ? listOf(resolved[key], promptId, decoding, pass) : undefined;
    }
    key = chunkUrl(src, promptId, decoding, pass);
    return key && Object.prototype.hasOwnProperty.call(resolved, key) ? resolved[key] : undefined;
  }

  function itemsUrl(run) {
    var name = run && run.task && run.task.items;
    if (typeof name !== "string" || !/^[A-Za-z0-9_.\-\/]+$/.test(name) || name.indexOf("..") >= 0) return null;
    return absolute("data/tasks/" + name + ".jsonl");
  }

  function parseItems(text) {
    return text.split("\n").filter(function (line) { return line.trim(); }).map(function (line) {
      var row = JSON.parse(line);
      return { id: String(row.id), question: String(row.question), answer: String(row.answer) };
    });
  }

  function items(run) {
    var url = itemsUrl(run);
    if (!url || document.getElementById("da-embedded")) return Promise.resolve(null);
    return once(url, function () { return fetchText(url).then(parseItems); });
  }

  function peekItems(run) {
    var url = itemsUrl(run);
    if (!url || document.getElementById("da-embedded")) return null;
    return Object.prototype.hasOwnProperty.call(resolved, url) ? resolved[url] : undefined;
  }

  DA.outputs = { get: get, items: items, status: status, peek: peek, peekItems: peekItems, problem: problem, safePointer: safePointer };
})(typeof globalThis !== "undefined" ? globalThis : this);
