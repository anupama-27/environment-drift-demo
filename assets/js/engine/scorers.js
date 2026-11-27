(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  // The two numeric scorers are the paper's extractors, kept as they were when the runs were
  // made. They were written against Python's re module, so the patterns below spell out what
  // Python means by \s, \d, $ under re.M and letters under re.I. JavaScript's own shorthands
  // differ on each of those and would read some outputs differently.

  // Python's \s, str.strip() and str.split() share this set. JS \s adds U+FEFF and lacks
  // U+001C-U+001F and U+0085.
  var WS = "\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
  var S = "[" + WS + "]";
  // Python's \d is any Unicode decimal digit, and float() reads them all.
  var D = "\\p{Nd}";
  var PLAIN = "-?" + D + "+(?:\\." + D + "+)?";
  var LOOSE = "-?\\$?" + S + "*" + D + "[" + D + ",]*(?:\\." + D + "+)?";
  // $ under re.M: the end of the text or just before \n, and before no other line terminator.
  var EOL = "(?=\\n|$)";

  var BOXED = new RegExp("\\\\boxed\\{((?:[^{}]|\\{[^{}]*\\})*)\\}", "gu");
  var PLAIN_FULL = new RegExp("^(?:" + PLAIN + ")$", "u");
  var HASHES_PLAIN = new RegExp("####" + S + "*(" + PLAIN + ")" + S + "*" + EOL, "gu");
  var BOX_NOISE = /\\text\{[^{}]*\}|\\[a-zA-Z]+|[{}%]/gu;
  var LOOSE_ANY = new RegExp(LOOSE, "gu");
  // The lenient rules that scan the whole response, in the order they are tried. Under re.I
  // Python also matches long s for s and both dotted and dotless i for i; the classes keep that.
  var TEXT_RULES = [
    ["hashes_loose", new RegExp("####" + S + "*(" + LOOSE + ")", "gu")],
    ["bold", new RegExp("\\*\\*" + S + "*(" + LOOSE + ")[^*]{0,20}\\*\\*", "gu")],
    ["answer_is", new RegExp("[aA][nN][sS\\u017f][wW][eE][rR] [iI\\u0130\\u0131][sS\\u017f][:" + WS + "]*(" + LOOSE + ")", "gu")]
  ];

  var ND = new RegExp("^" + D + "$", "u");
  var SPACE = new RegExp("^" + S + "$");
  var SPACES = new RegExp(S + "+");
  var ASCII_PUNCTUATION = /[!-\/:-@\[-`{-~]/g;
  var has = Object.prototype.hasOwnProperty;

  function strip(s) {
    var a = 0, b = s.length;
    while (a < b && SPACE.test(s[a])) a++;
    while (b > a && SPACE.test(s[b - 1])) b--;
    return s.slice(a, b);
  }

  // Every block of Unicode decimal digits runs 0..9 in order, and adjacent blocks form one run.
  function digitValue(cp) {
    var start = cp;
    if (cp >= 48 && cp <= 57) return cp - 48;
    while (ND.test(String.fromCodePoint(start - 1))) start--;
    return (cp - start) % 10;
  }

  // float(str) as CPython reads it; null where Python raises ValueError.
  function pyFloat(s) {
    var out = "", i = 0, cp, ch, lower;
    while (i < s.length) {
      cp = s.codePointAt(i);
      ch = String.fromCodePoint(cp);
      i += ch.length;
      if (cp < 127) out += ch;
      else if (SPACE.test(ch)) out += " ";
      else if (ND.test(ch)) out += digitValue(cp);
      else return null;
    }
    if (out.indexOf("_") >= 0) {
      if (/(?:^|[^0-9])_|_(?:[^0-9]|$)/.test(out)) return null;
      out = out.replace(/_/g, "");
    }
    out = out.replace(/^[ \t\n\v\f\r]+|[ \t\n\v\f\r]+$/g, "");
    if (/^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(out)) return Number(out);
    lower = out.toLowerCase();
    if (/^[+-]?inf(?:inity)?$/.test(lower)) return lower[0] === "-" ? -Infinity : Infinity;
    if (/^[+-]?nan$/.test(lower)) return NaN;
    return null;
  }

  function toFloat(s) {
    return pyFloat(s.replace(/[,$ ]/g, "").replace(/\.+$/, ""));
  }

  // re.findall for a pattern with at most one group: the group if there is one, else the match.
  function findAll(re, text) {
    var out = [], m;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) out.push(m.length > 1 ? m[1] : m[0]);
    return out;
  }

  function lastOf(xs) {
    return xs.length ? xs[xs.length - 1] : null;
  }

  // Content of the last \boxed{...}, allowing one level of nested braces.
  function lastBoxed(text) {
    var hit = lastOf(findAll(BOXED, text));
    return hit === null ? null : strip(hit);
  }

  function asText(text) {
    return text === null || text === undefined ? "" : String(text);
  }

  // The paper's extractor v1: a plain number in the last box, or after '####' at a line end.
  function strict(text) {
    var box, hit;
    text = asText(text);
    box = lastBoxed(text);
    if (box !== null && PLAIN_FULL.test(box)) return pyFloat(box);
    hit = lastOf(findAll(HASHES_PLAIN, text));
    return hit === null ? null : pyFloat(hit);
  }

  function lastReadable(hits) {
    var i, v;
    for (i = hits.length - 1; i >= 0; i--) {
      v = toFloat(hits[i]);
      if (v !== null) return v;
    }
    return null;
  }

  // Value and rule of the lenient extractor (v2); one function so the two can never disagree.
  function readLenient(text) {
    var v, box, hit, i;
    text = asText(text);
    v = strict(text);
    if (v !== null) return { value: v, rule: "v1" };
    box = lastBoxed(text);
    if (box !== null) {
      LOOSE_ANY.lastIndex = 0;
      hit = LOOSE_ANY.exec(box.replace(BOX_NOISE, " "));
      v = hit === null ? null : toFloat(hit[0]);
      if (v !== null) return { value: v, rule: "boxed_loose" };
    }
    for (i = 0; i < TEXT_RULES.length; i++) {
      v = lastReadable(findAll(TEXT_RULES[i][1], text));
      if (v !== null) return { value: v, rule: TEXT_RULES[i][0] };
    }
    v = lastReadable(findAll(LOOSE_ANY, text));
    if (v !== null) return { value: v, rule: "last_number" };
    return { value: null, rule: "none" };
  }

  function lenient(text) {
    return readLenient(text).value;
  }

  // Which rule of the lenient scorer produced its answer: v1, boxed_loose, hashes_loose, bold,
  // answer_is, last_number or none. Anything but v1 is an answer the strict scorer does not read.
  function lenientRule(text) {
    return readLenient(text).rule;
  }

  // GSM8K answers end with '#### 72'.
  function goldAnswer(answerField) {
    var parts = String(answerField).split("####");
    return toFloat(strip(parts[parts.length - 1]));
  }

  function absent(x) {
    return x === null || x === undefined;
  }

  function isCorrect(pred, gold) {
    if (typeof gold === "string") gold = goldAnswer(gold);
    return !absent(pred) && !absent(gold) && Math.abs(pred - gold) < 1e-6;
  }

  function stripped(text) {
    return strip(asText(text)) || null;
  }

  function sameText(pred, gold) {
    return !absent(pred) && !absent(gold) && pred === strip(String(gold));
  }

  // str.casefold(). Upper-casing then lower-casing each character gives Unicode full case
  // folding, except for dotless i (folds to itself), capital sharp s, and Cherokee (folds to capitals).
  function casefold(s) {
    var out = "", i = 0, cp, ch, up, j, u;
    if (/^[\x00-\x7f]*$/.test(s)) return s.toLowerCase();
    while (i < s.length) {
      cp = s.codePointAt(i);
      ch = String.fromCodePoint(cp);
      i += ch.length;
      if (cp === 0x131) {
        out += ch;
      } else if (cp === 0x1e9e) {
        out += "ss";
      } else if ((cp >= 0x13a0 && cp <= 0x13fd) || (cp >= 0xab70 && cp <= 0xabbf)) {
        out += ch.toUpperCase();
      } else {
        up = ch.toUpperCase();
        for (j = 0; j < up.length; j += u.length) {
          u = String.fromCodePoint(up.codePointAt(j));
          out += u.toLowerCase();
        }
      }
    }
    return out;
  }

  // Casefold, drop ASCII punctuation, collapse whitespace, drop one leading article.
  function normalizeText(text) {
    var words = casefold(asText(text)).replace(ASCII_PUNCTUATION, "").split(SPACES).filter(Boolean);
    if (words.length && (words[0] === "a" || words[0] === "an" || words[0] === "the")) words.shift();
    return words.join(" ") || null;
  }

  function sameNormalizedText(pred, gold) {
    return !absent(pred) && !absent(gold) && pred === normalizeText(String(gold));
  }

  function scorer(id, name, extract, correct) {
    return { id: id, name: name, version: "1", extract: extract, correct: correct };
  }

  var BUILTIN = {
    "strict": scorer("strict", "strict numeric", strict, isCorrect),
    "lenient": scorer("lenient", "lenient numeric", lenient, isCorrect),
    "exact": scorer("exact", "exact match", stripped, sameText),
    "exact-normalized": scorer("exact-normalized", "normalized exact match", normalizeText, sameNormalizedText)
  };
  // The paper and its run files call the numeric scorers v1 and v2.
  var ALIASES = { v1: "strict", v2: "lenient" };

  function get(id) {
    var name = typeof id === "string" && has.call(ALIASES, id) ? ALIASES[id] : id;
    if (typeof name === "string" && has.call(BUILTIN, name)) return BUILTIN[name];
    throw new Error("unknown scorer " + JSON.stringify(id) + "; known scorers: " + Object.keys(BUILTIN).join(", "));
  }

  DA.scorers = {
    strict: strict,
    lenient: lenient,
    lenientRule: lenientRule,
    isCorrect: isCorrect,
    goldAnswer: goldAnswer,
    normalizeText: normalizeText,
    toFloat: toFloat,
    get: get
  };

  if (typeof module === "object" && module.exports) module.exports = DA;
})(typeof globalThis !== "undefined" ? globalThis : this);
