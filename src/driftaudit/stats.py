"""Statistics the audit reports: mean and sd over runs, t intervals, Fisher exact, t test.

The formulas are those of toolkit/stats.py and toolkit/drift/analysis.py. Sums are written
as loops that add left to right in plain floats: the JavaScript engine repeats them in the
same order, and Python's own sum() changed its rounding in 3.12, so calling it on floats
would give results that differ in the last digit between interpreter versions.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Tuple

# Two-sided t critical values at 95%, indexed by degrees of freedom. 1-15 are the toolkit's.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069,
        24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def mean(xs: Iterable[float]) -> Optional[float]:
    """Arithmetic mean, or None when there is nothing to average (never NaN, so results stay JSON)."""
    xs = list(xs)
    if not xs:
        return None
    total = 0.0
    for x in xs:
        total += x
    return total / len(xs)


def sd(xs: Iterable[float]) -> Optional[float]:
    """Sample standard deviation. One value has no spread to estimate and reports 0.0."""
    xs = list(xs)
    if not xs:
        return None
    if len(xs) == 1:
        return 0.0
    m = mean(xs)
    squares = 0.0
    for x in xs:
        squares += (x - m) * (x - m)
    return math.sqrt(squares / (len(xs) - 1))


def t95(df: int) -> float:
    """Two-sided 95% critical value of Student's t; the normal value beyond 30 degrees of freedom."""
    if df < 1:
        raise ValueError("a t interval needs at least two values")
    return _T95.get(df, 1.96)


def t_interval(xs: Iterable[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(mean, lower, upper) of a 95% t interval across runs. Read it against zero, not against other rows.

    With fewer than two values there is no interval and both bounds are None.
    """
    xs = list(xs)
    m = mean(xs)
    if len(xs) < 2:
        return m, None, None
    half = t95(len(xs) - 1) * sd(xs) / math.sqrt(len(xs))
    return m, m - half, m + half


def fisher_p(a: int, n1: int, b: int, n2: int) -> float:
    """Two-sided Fisher exact test for a/n1 against b/n2."""
    total, hits = n1 + n2, a + b
    tables = math.comb(total, hits)

    def h(x):
        return math.comb(n1, x) * math.comb(n2, hits - x) / tables

    p0 = h(a)
    p = 0.0
    for x in range(max(0, hits - n2), min(hits, n1) + 1):
        if h(x) <= p0 * (1 + 1e-9):
            p += h(x)
    # The terms of a table that is its own most extreme case can add up to a hair over one.
    return min(p, 1.0)


def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 / (1 - qab * x / qap)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d, c = 1 / (1 + aa * d), 1 + aa / c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d, c = 1 / (1 + aa * d), 1 + aa / c
        h *= d * c
        if abs(d * c - 1) < 1e-13:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0 or x >= 1:
        return float(x >= 1)
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return bt * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * _betacf(b, a, 1 - x) / b


def t_test_p(xs: Iterable[float]) -> Optional[float]:
    """Two-sided one-sample t test against zero. None with fewer than two values."""
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return None
    m, s = mean(xs), sd(xs)
    if s == 0:
        return 1.0 if m == 0 else 0.0
    t = m / (s / math.sqrt(n))
    df = n - 1
    return _ibeta(df / 2, 0.5, df / (df + t * t))
