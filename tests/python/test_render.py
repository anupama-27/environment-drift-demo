"""Text and Markdown rendering of audits and studies."""
from __future__ import annotations

import copy

import pytest

from app_fixtures import PAPER_SEED5, mock_loop  # noqa: F401
from conftest import SEEDS, paper_run_path
from driftaudit import engine, render, schema

POLICY_TABLE = """\
Policies
  policy                 accepts  false accepts  false rejects  final accuracy  reruns  model calls
  Frozen                       8              4              0           68.5%       0        4,411
  Stored incumbent             1              0              1           72.0%       0        4,411
  Per-batch                    2              1              2           69.5%      11        6,611
  Environment-triggered        3              1              0           75.0%       2        4,811
  Every 3 rounds               3              1              0           75.0%       2        4,811
As run is not listed: the loop compared each candidate with its own incumbent in the same pass, so
its decisions match the ground-truth check by construction.
"""

FROZEN_ERRORS = """\
Frozen: never refresh; compare with the reference stored at round 0
4 false accepts (3 stale reference, 1 no environment change) and 0 false rejects in 11 decisions.
Mean drift inflation +1.50 pp.

False accepts. stored and rerun: wins/losses against the stored and the rerun reference;
inflation: drift inflation in pp; change: candidate accuracy minus incumbent accuracy in pp.
  round  env  reference  stored  rerun  inflation  change  cause
      3  E1   E1 age 3    26/22  28/22      -1.00   -4.00  no environment change
      5  E2   E1 age 5    23/22  17/22      +3.00   -2.00  stale reference
      8  E4   E1 age 8    21/18  16/22      +2.50   -5.50  stale reference
     10  E4   E1 age 10   22/21  14/22      +4.00   -3.50  stale reference
"""


@pytest.fixture(scope="module")
def paper_audit():
    return engine.audit(PAPER_SEED5)


@pytest.fixture(scope="module")
def paper_study():
    return engine.study([paper_run_path(seed) for seed in SEEDS])


def test_paper_run_header_environments_and_policy_table(paper_audit):
    text = render.render_audit(paper_audit)
    assert text.startswith("DriftAudit 0.1.0: audit of gsm8k-qwen2.5-1.5b-seed5\nsource: measured\n"
                           "GSM8K, Qwen/Qwen2.5-1.5B-Instruct, seed 5: 200 items, 11 rounds, 11 candidates\n")
    assert "  E1  Unchanged   rounds 0-3     greedy-0.0  v1\n" in text
    assert "  E3  Extraction  not scheduled  greedy-0.0  v2\n" in text
    assert "  E4  model=Qwen/Qwen2.5-1.5B-Instruct;decode=sample-0.2;extract=v2\n" in text
    assert POLICY_TABLE in text


def test_paper_run_lists_four_frozen_false_accepts_three_of_them_stale(paper_audit):
    text = render.render_audit(paper_audit)
    assert FROZEN_ERRORS in text
    assert text.count("stale reference\n") == 3


def test_another_policy_can_be_listed_with_its_false_rejects(paper_audit):
    text = render.render_audit(paper_audit, policy="per_batch")
    assert "Per-batch: refresh every batch\n1 false accept (1 no environment change) and 2 false rejects" in text
    assert "False rejects." in text and "rerun reference" in text
    assert "Frozen: never refresh" not in text
    assert "is not part of this audit" in render.render_audit(paper_audit, policy="nope")


def test_text_fits_a_100_column_terminal(paper_audit, paper_study, mock_loop):
    for text in (render.render_audit(paper_audit), render.render_study(paper_study),
                 render.render_audit(engine.audit(mock_loop[0]))):
        assert max(len(line) for line in text.splitlines()) <= 100
        assert not any(line != line.rstrip() for line in text.splitlines())


def test_long_fingerprints_wrap_after_a_semicolon(paper_audit):
    audit = copy.deepcopy(paper_audit)
    audit["environments"][0]["fingerprint"] += ";backend=hf;device=cuda;dtype=float16;revision=" + "a" * 40
    lines = render.render_audit(audit).splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("  E1  model="))
    assert lines[start].endswith(";") and lines[start + 1].startswith("      ")
    assert max(len(line) for line in lines) <= 100


def test_synthetic_run_is_tagged_and_colour_is_opt_in(mock_loop):
    audit = engine.audit(mock_loop[0])
    plain = render.render_audit(audit)
    assert "source: synthetic: simulated model, not a measurement\n" in plain
    assert "\x1b[" not in plain
    coloured = render.render_audit(audit, color=True)
    assert "\x1b[1m" in coloured and "\x1b[33msynthetic" in coloured
    assert coloured.replace("\x1b[1m", "").replace("\x1b[31m", "").replace("\x1b[33m", "").replace("\x1b[0m", "") == plain


def test_unavailable_policies_say_what_is_missing():
    run = copy.deepcopy(schema.load(PAPER_SEED5))
    for per_env in run["labels"].values():
        for passes in per_env.values():
            passes.pop("rerun", None)
    for cand in run["candidates"]:
        cand.pop("reference")
    text = render.render_audit(engine.audit(run))
    assert "Not available on this run log:" in text
    assert "  Per-batch: needs 3 label vectors the run log does not have, for example the rerun of prompt" in text
    assert "  As run: the run log does not say which reference the loop compared each candidate with" in text
    assert "The label bank is sparse" in text
    assert "n/a" in text     # rerun columns of the frozen false accepts


def test_what_if_options_are_stated(paper_audit):
    audit = engine.audit(PAPER_SEED5, schedule={0: "E1", 4: "E1", 8: "E3"}, stored_scoring="rescore", margin=2)
    text = render.render_audit(audit)
    assert "what-if: schedule 0:E1,4:E1,8:E3\n" in text
    assert "what-if: stored references rescored with the current scorer\n" in text
    assert "what-if: accept when wins exceed losses by more than 2\n" in text
    assert "what-if" not in render.render_audit(paper_audit)


def test_markdown_has_the_same_numbers_in_tables(paper_audit):
    md = render.audit_markdown(paper_audit)
    assert md.startswith("# DriftAudit 0.1.0: audit of gsm8k-qwen2.5-1.5b-seed5\n")
    assert "| policy | accepts | false accepts | false rejects | final accuracy | reruns | model calls |\n" in md
    assert "| Frozen | 8 | 4 | 0 | 68.5% | 0 | 4,411 |\n" in md
    assert "| 10 | E4 | E1 age 10 | 22/21 | 14/22 | +4.00 | -3.50 | stale reference |\n" in md
    assert "- E1: `model=Qwen/Qwen2.5-1.5B-Instruct;decode=greedy-0.0;extract=v1`\n" in md


def test_study_pools_the_five_paper_runs(paper_study):
    text = render.render_study(paper_study)
    assert text.startswith("DriftAudit 0.1.0: study of 5 runs\nsource: measured\n55 decisions in total.\n")
    assert "  Frozen                      34             13              0     70.8 ± 2.0%       0        4,411\n" in text
    assert "  Environment-triggered       16              2              2     72.5 ± 2.2%       2        4,811\n" in text
    assert "  Every 3 rounds              15              2              3     72.5 ± 2.2%     2.2        4,851\n" in text
    assert "By cause: 6 stale reference, 3 would have been accepted anyway, 4 no environment change.\n" in text
    assert "     5        8              4              0           68.5%        4,411  gsm8k-qwen2.5-1.5b-seed5\n" in text
    assert "  Environment-triggered       4  Frozen                13              55  0.033\n" in text
    assert "  E3            +1.31  [+0.65, +1.98]           5 of 5\n" in text
    assert "  E1            -0.12  [-0.64, +0.39]           2 of 5\n" in text


def test_study_can_list_runs_for_another_policy_and_render_markdown(paper_study):
    assert "Environment-triggered, run by run\n" in render.render_study(paper_study, policy="env_triggered")
    md = render.study_markdown(paper_study)
    assert "| Frozen | 34 | 13 | 0 | 70.8 ± 2.0% | 0 | 4,411 |\n" in md
    assert "| E4 | +1.54 | [+0.04, +3.04] | 4 of 5 |\n" in md


@pytest.mark.parametrize("value, text", [(0.685, "68.5%"), (None, "n/a"), (1.0, "100.0%")])
def test_percentages_have_one_decimal(value, text):
    assert render._pct(value) == text


@pytest.mark.parametrize("value, text", [(1.5000000000000002, "+1.50"), (-0.004, "+0.00"), (-2.5, "-2.50"), (None, "n/a")])
def test_points_have_two_decimals_and_a_sign(value, text):
    assert render._pp(value) == text


def test_counts_get_thousands_separators():
    assert render._count(4411) == "4,411" and render._count(4411.0) == "4,411" and render._count(2.2) == "2.2"


def with_real_references(run):
    """The run as if the loop had compared every candidate with the instruction it started from."""
    run = copy.deepcopy(run)
    first = run["snapshots"][0]
    for cand in run["candidates"]:
        cand["reference"] = {"prompt": first["prompt"], "env": first["env"], "pass": "current"}
    return run


def test_as_run_is_trivial_when_each_candidate_met_its_own_incumbent(paper_audit, mock_loop):
    assert engine.as_run_is_trivial(paper_audit["policies"]["as_run"])
    assert engine.as_run_is_trivial(engine.audit(mock_loop[0])["policies"]["as_run"])
    real = engine.audit(with_real_references(schema.load(PAPER_SEED5)))
    assert not engine.as_run_is_trivial(real["policies"]["as_run"])
    assert not engine.as_run_is_trivial(None) and not engine.as_run_is_trivial({"available": False})


def test_trivial_as_run_is_left_out_of_the_audit_unless_asked_for(paper_audit):
    text = render.render_audit(paper_audit)
    assert "  As run  " not in text and render.AS_RUN_NOTE.split(":")[0] in text
    assert "\nFrozen: never refresh" in text
    asked = render.render_audit(paper_audit, "as_run")
    assert "  As run                       2" in asked and "As run is not listed" not in asked
    assert "\nAs run: the decisions the loop recorded" in asked
    assert "As run is not listed" in render.audit_markdown(paper_audit)


def test_as_run_with_real_references_stays_in_the_audit():
    text = render.render_audit(engine.audit(with_real_references(schema.load(PAPER_SEED5))))
    assert "\n  As run  " in text and "As run is not listed" not in text


def test_trivial_as_run_is_left_out_of_the_study_and_its_tests(paper_study):
    text = render.render_study(paper_study, trivial_as_run=True)
    assert "As run  " not in text and "As run is not listed" in text
    tests = text.split("Decision errors compared")[1].split("\n\n")[0]
    assert "Environment-triggered" in tests and "As run" not in tests
    assert "As run" in render.render_study(paper_study)
    assert "As run is not listed" in render.study_markdown(paper_study, trivial_as_run=True)


def test_study_header_says_when_runs_are_simulated_or_mixed(mock_loop):
    synthetic = engine.study([mock_loop[0], dict(mock_loop[0], id="other")])
    assert synthetic["source"] == "synthetic" and [r["source"] for r in synthetic["runs"]] == ["synthetic"] * 2
    assert "\nsource: synthetic: every run is simulated" in render.render_study(synthetic)
    assert "source: synthetic: every run is simulated" in render.study_markdown(synthetic)
    mixed = engine.study([PAPER_SEED5, mock_loop[0]])
    assert mixed["source"] == "mixed"
    assert "\nsource: mixed: 1 of 2 runs simulated, the rest measured" in render.render_study(mixed)


def test_false_accept_without_a_rerun_says_so_instead_of_none(paper_audit):
    result = copy.deepcopy(paper_audit)
    for d in result["policies"]["frozen"]["decisions"]:
        if d["false_accept"]:
            d["cause"], d["rerun_wins"], d["rerun_losses"] = None, None, None
    text = render.render_audit(result)
    assert "rerun not recorded" in text and "None" not in text
