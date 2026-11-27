(function (root) {
  "use strict";
  var DA = root.DA = root.DA || {};

  // Sums add left to right in plain doubles, the order the Python engine uses, so the two
  // agree to the last digit that matters.

  // Two-sided t critical values at 95%, indexed by degrees of freedom. 1-15 are the paper's table.
  var T95 = [null, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069,
    2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042];

  // Arithmetic mean, or null when there is nothing to average (never NaN, so results stay JSON).
  function mean(xs) {
    var n = xs.length, total = 0, i;
    if (!n) return null;
    for (i = 0; i < n; i++) total += xs[i];
    return total / n;
  }

  // Sample standard deviation. One value has no spread to estimate and reports 0.
  function sd(xs) {
    var n = xs.length, m, squares = 0, i;
    if (!n) return null;
    if (n === 1) return 0;
    m = mean(xs);
    for (i = 0; i < n; i++) squares += (xs[i] - m) * (xs[i] - m);
    return Math.sqrt(squares / (n - 1));
  }

  // Two-sided 95% critical value of Student's t; the normal value beyond 30 degrees of freedom.
  function t95(df) {
    if (!(df >= 1)) throw new RangeError("a t interval needs at least two values");
    return df < T95.length && T95[df] !== undefined ? T95[df] : 1.96;
  }

  // Mean with a 95% t interval across runs. Fewer than two values give no bounds.
  function tInterval(xs) {
    var n = xs.length, m = mean(xs), half;
    if (n < 2) return { mean: m, lo: null, hi: null };
    half = t95(n - 1) * sd(xs) / Math.sqrt(n);
    return { mean: m, lo: m - half, hi: m + half };
  }

  function isCount(x) {
    return typeof x === "number" && x >= 0 && Math.floor(x) === x && isFinite(x);
  }

  // Two-sided Fisher exact test for a/n1 against b/n2.
  // Python divides exact binomial coefficients. Those leave double range for long runs, so
  // the same hypergeometric terms are built here from their ratio, outward from the mode.
  function fisher(a, n1, b, n2) {
    var total = n1 + n2, hits = a + b;
    var lo = Math.max(0, hits - n2), hi = Math.min(hits, n1);
    var w, mode, x, sum = 0, p0, h, p = 0;
    if (!isCount(a) || !isCount(n1) || !isCount(b) || !isCount(n2) || hits > total) return null;
    if (a < lo || a > hi) return 0;
    mode = Math.min(hi, Math.max(lo, Math.floor((hits + 1) * (n1 + 1) / (total + 2))));
    w = new Array(hi - lo + 1);
    w[mode - lo] = 1;
    for (x = mode; x < hi; x++) {
      w[x + 1 - lo] = w[x - lo] * ((n1 - x) * (hits - x)) / ((x + 1) * (n2 - hits + x + 1));
    }
    for (x = mode; x > lo; x--) {
      w[x - 1 - lo] = w[x - lo] * (x * (n2 - hits + x)) / ((n1 - x + 1) * (hits - x + 1));
    }
    for (x = 0; x < w.length; x++) sum += w[x];
    p0 = w[a - lo] / sum;
    for (x = 0; x < w.length; x++) {
      h = w[x] / sum;
      if (h <= p0 * (1 + 1e-9)) p += h;
    }
    // The terms of a table that is its own most extreme case can add up to a hair over one.
    return Math.min(p, 1);
  }

  var LANCZOS_G = 6.024680040776729583740234375;
  var LANCZOS_NUM = [
    23531376880.410759688572007674451636754734846804940,
    42919803642.649098768957899047001988850926355848959,
    35711959237.355668049440185451547166705960488635843,
    17921034426.037209699919755754458931112671403265390,
    6039542586.3520280050642916443072979210699388420708,
    1439720407.3117216736632230727949123939715485786772,
    248874557.86205415651146038641322942321632125127801,
    31426415.585400194380614231628318205362874684987640,
    2876370.6289353724412254090516208496135991145378768,
    186056.26539522349504029498971604569928220784236328,
    8071.6720023658162106380029022722506138218516325024,
    210.82427775157934587250973392071336271166969580291,
    2.5066282746310002701649081771338373386264310793408
  ];
  var LANCZOS_DEN = [0, 39916800, 120543840, 150917976, 105258076, 45995730, 13339535,
    2637558, 357423, 32670, 1925, 66, 1];

  function lanczosSum(x) {
    var num = 0, den = 0, i;
    if (x < 5) {
      for (i = LANCZOS_NUM.length - 1; i >= 0; i--) {
        num = num * x + LANCZOS_NUM[i];
        den = den * x + LANCZOS_DEN[i];
      }
    } else {
      for (i = 0; i < LANCZOS_NUM.length; i++) {
        num = num / x + LANCZOS_NUM[i];
        den = den / x + LANCZOS_DEN[i];
      }
    }
    return num / den;
  }

  // log-gamma for x > 0, by the Lanczos approximation CPython's math.lgamma uses, so the
  // t test below returns what the Python engine returns.
  function lgamma(x) {
    if (!(x > 0)) return null;
    if (x === 1 || x === 2) return 0;
    if (x < 1e-20) return -Math.log(x);
    return Math.log(lanczosSum(x)) - LANCZOS_G + (x - 0.5) * (Math.log(x + LANCZOS_G - 0.5) - 1);
  }

  function betacf(a, b, x) {
    var qab = a + b, qap = a + 1, qam = a - 1;
    var c = 1, d = 1 / (1 - qab * x / qap), h = d, m, m2, aa;
    for (m = 1; m < 300; m++) {
      m2 = 2 * m;
      aa = m * (b - m) * x / ((qam + m2) * (a + m2));
      d = 1 / (1 + aa * d);
      c = 1 + aa / c;
      h *= d * c;
      aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
      d = 1 / (1 + aa * d);
      c = 1 + aa / c;
      h *= d * c;
      if (Math.abs(d * c - 1) < 1e-13) break;
    }
    return h;
  }

  // Regularized incomplete beta function I_x(a, b).
  function ibeta(a, b, x) {
    var bt;
    if (x <= 0 || x >= 1) return x >= 1 ? 1 : 0;
    bt = Math.exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * Math.log(x) + b * Math.log(1 - x));
    return x < (a + 1) / (a + b + 2) ? bt * betacf(a, b, x) / a : 1 - bt * betacf(b, a, 1 - x) / b;
  }

  // Two-sided one-sample t test against zero. null with fewer than two values.
  function tTestP(xs) {
    var n = xs.length, m, s, t, df;
    if (n < 2) return null;
    m = mean(xs);
    s = sd(xs);
    if (s === 0) return m === 0 ? 1 : 0;
    t = m / (s / Math.sqrt(n));
    df = n - 1;
    return ibeta(df / 2, 0.5, df / (df + t * t));
  }

  DA.stats = {
    mean: mean,
    sd: sd,
    t95: t95,
    tInterval: tInterval,
    fisher: fisher,
    tTestP: tTestP,
    lgamma: lgamma,
    ibeta: ibeta
  };

  if (typeof module === "object" && module.exports) module.exports = DA;
})(typeof globalThis !== "undefined" ? globalThis : this);
