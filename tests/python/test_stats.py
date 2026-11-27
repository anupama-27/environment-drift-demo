from __future__ import annotations

import ast
import math
import os
import statistics

import pytest

from conftest import TOOLKIT
from driftaudit import stats


@pytest.fixture(scope="module")
def toolkit_stats():
    """fisher_p and t_test_p as toolkit/stats.py defines them.

    That file is a script: importing it recomputes the paper's statistics and rewrites
    results/stats.md. Only the function definitions are compiled here.
    """
    path = os.path.join(TOOLKIT, "stats.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    wanted = {"_betacf", "_ibeta", "t_test_p", "fisher_p"}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    assert {node.name for node in body} == wanted
    namespace = {"math": math, "st": statistics}
    exec(compile(ast.Module(body=body, type_ignores=[]), path, "exec"), namespace)
    return namespace


def test_mean_and_sample_sd():
    xs = [0.69, 0.71, 0.73, 0.725, 0.685]
    assert stats.mean(xs) == pytest.approx(statistics.mean(xs), abs=1e-15)
    assert stats.sd(xs) == pytest.approx(statistics.stdev(xs), abs=1e-15)


def test_sd_of_one_value_is_zero():
    assert stats.sd([0.7]) == 0.0


def test_nothing_to_average_gives_none_not_nan():
    assert stats.mean([]) is None
    assert stats.sd([]) is None
    assert stats.t_interval([]) == (None, None, None)


def test_mean_accepts_a_generator():
    assert stats.mean(x / 10 for x in range(5)) == pytest.approx(0.2)


def test_mean_adds_left_to_right():
    # Added one at a time the two small terms are absorbed and lost. A compensated sum,
    # which is what sum() became in Python 3.12, keeps them and gives a different mean.
    assert stats.mean([1e16, 1.0, 1.0]) == 1e16 / 3


def test_t95_keeps_the_toolkit_table(toolkit):
    for df, value in toolkit.analysis._T95.items():
        assert stats.t95(df) == value


def test_t95_extends_to_thirty_then_uses_the_normal_value():
    assert [stats.t95(df) for df in (16, 20, 25, 30)] == [2.120, 2.086, 2.060, 2.042]
    assert stats.t95(31) == stats.t95(1000) == 1.96
    values = [stats.t95(df) for df in range(1, 32)]
    assert values == sorted(values, reverse=True)


def test_t95_needs_at_least_one_degree_of_freedom():
    with pytest.raises(ValueError):
        stats.t95(0)


def test_t_interval_is_the_toolkit_interval(toolkit):
    xs = [1.75, 0.875, 0.625, 1.5, 1.8125]
    m, lo, hi = stats.t_interval(xs)
    half = toolkit.analysis._T95[4] * statistics.stdev(xs) / math.sqrt(5)
    assert m == pytest.approx(statistics.mean(xs), abs=1e-12)
    assert lo == pytest.approx(statistics.mean(xs) - half, abs=1e-12)
    assert hi == pytest.approx(statistics.mean(xs) + half, abs=1e-12)
    assert toolkit.analysis.ci95(xs) == f"[{lo:+.2f}, {hi:+.2f}]"


def test_t_interval_of_one_value_has_no_bounds():
    assert stats.t_interval([0.5]) == (0.5, None, None)


def test_fisher_matches_the_toolkit(toolkit_stats):
    legacy = toolkit_stats["fisher_p"]
    for a, n1, b, n2 in [(4, 55, 13, 55), (4, 55, 14, 55), (4, 55, 8, 55), (0, 5, 5, 5), (3, 3, 0, 4),
                         (0, 10, 0, 10), (7, 20, 12, 31), (55, 55, 0, 55), (1, 1, 1, 1), (17, 200, 31, 180)]:
        assert stats.fisher_p(a, n1, b, n2) == pytest.approx(legacy(a, n1, b, n2), abs=1e-12)


def test_fisher_reproduces_the_policy_tests_in_the_paper():
    assert f"{stats.fisher_p(4, 55, 13, 55):.3f}" == "0.033"
    assert f"{stats.fisher_p(4, 55, 14, 55):.3f}" == "0.019"
    assert f"{stats.fisher_p(4, 55, 8, 55):.3f}" == "0.360"


def test_fisher_does_not_depend_on_which_group_comes_first():
    assert stats.fisher_p(4, 55, 13, 55) == pytest.approx(stats.fisher_p(13, 55, 4, 55), abs=1e-15)


def test_fisher_of_identical_groups_is_one():
    assert stats.fisher_p(5, 20, 5, 20) == pytest.approx(1.0, abs=1e-12)
    assert stats.fisher_p(0, 10, 0, 10) == 1.0


def test_fisher_never_exceeds_one():
    for a in range(0, 13):
        for b in range(0, 13):
            assert 0.0 <= stats.fisher_p(a, 12, b, 12) <= 1.0


def test_t_test_matches_the_toolkit(toolkit_stats):
    legacy = toolkit_stats["t_test_p"]
    for xs in ([0.3, 0.9, 0.5, 0.7, 0.55], [-2.25, 1.75, 0.375, -1.625, -1.1875], [1.0, 1.1], [0.2, -0.1, 0.05],
               [5.0, 4.9, 5.2, 5.1, 4.8, 5.05, 4.95], [1e-3, -2e-3, 4e-3, 1e-3]):
        assert stats.t_test_p(xs) == pytest.approx(legacy(xs), abs=1e-12)


def test_t_test_edges():
    assert stats.t_test_p([0.4]) is None
    assert stats.t_test_p([0.0, 0.0, 0.0]) == 1.0
    assert stats.t_test_p([2.0, 2.0, 2.0]) == 0.0
    assert stats.t_test_p([1.0, -1.0]) == pytest.approx(1.0)
