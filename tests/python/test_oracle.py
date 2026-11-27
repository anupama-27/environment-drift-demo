"""The new engine against toolkit/drift/analysis.py, field by field.

Every number in the paper came from the toolkit's simulate and age_pairs. These tests put
the same runs through both and require the same decisions and the same totals: the five
saved runs, and a few dozen generated ones with other sizes and schedules.

Integers, booleans, strings and accuracies must be identical. Drift inflation is compared to
1e-12: the toolkit's simulate subtracts two win rates, the engine divides the difference of
the counts once, and the two can differ in the last bit.
"""
from __future__ import annotations

import pytest

from conftest import SEEDS, make_legacy_run
from driftaudit import engine, schema

# Engine policy id -> (toolkit policy, frozen_mode).
LEGACY = {"frozen": ("P1", "initial"), "stored_incumbent": ("P1", "last_accepted"),
          "per_batch": ("P2", None), "env_triggered": ("P3", None)}

ABLATIONS = {"no decoding change": {0: "E1", 4: "E1", 8: "E3"},
             "no extraction change": {0: "E1", 4: "E2", 8: "E2"}}

SAME_VALUE = {"round": "round", "env": "env", "incumbent": "inc_prompt", "candidate": "cand_prompt",
              "ref_env": "ref_env", "wins": "wins", "losses": "losses", "rerun_wins": "fresh_wins",
              "rerun_losses": "fresh_losses", "accepted": "accepted", "inc_acc": "inc_acc", "cand_acc": "cand_acc",
              "delta_pp": "delta_pp", "outcome": "outcome", "false_accept": "false_accept",
              "false_reject": "false_reject"}

SAME_TOTAL = {"accepted": "accepted", "false_accepts": "false_accepts", "false_rejects": "false_rejects",
              "false_accept_rate": "false_accept_rate", "refreshes": "refreshes", "calls": "calls",
              "total_calls": "total_calls", "final_acc": "final_gt_acc"}


def close(a, b):
    return a == pytest.approx(b, rel=0, abs=1e-12)


def assert_same_replay(toolkit, legacy_run, policy, schedule=None, fixed_age=None, stored_scoring="as_recorded"):
    legacy_policy, frozen_mode = LEGACY[policy]
    view = toolkit.analysis.RunView(legacy_run, stored_scoring=stored_scoring)
    expected = toolkit.analysis.simulate(view, legacy_policy, schedule=schedule, frozen_mode=frozen_mode,
                                         fixed_age=fixed_age, with_records=True)
    run = schema.load(legacy_run)
    block = engine.simulate(run, policy, schedule=schedule, fixed_age=fixed_age, stored_scoring=stored_scoring)

    assert block["available"] and block["missing"] == []
    assert len(block["decisions"]) == expected["evaluated"] == len(expected["records"])
    for ours, theirs in SAME_TOTAL.items():
        assert block[ours] == expected[theirs], (policy, ours)
    assert close(block["inflation"], expected["inflation"])
    for decision, record, cand in zip(block["decisions"], expected["records"], run["candidates"]):
        assert record["cid"] == cand["id"]
        for ours, theirs in SAME_VALUE.items():
            assert decision[ours] == record[theirs], (policy, cand["id"], ours)
        # The toolkit's flag says the reference labels are a rerun, in this round or an earlier one.
        assert (decision["ref_pass"] == "rerun") == record["ref_fresh"], (policy, cand["id"])
        assert close(decision["inflation"], record["inflation"])


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("policy", list(LEGACY))
def test_paper_runs_replay_as_the_toolkit_does(toolkit, legacy_runs, seed, policy):
    assert_same_replay(toolkit, legacy_runs[seed], policy)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("policy", list(LEGACY))
@pytest.mark.parametrize("ablation", list(ABLATIONS))
def test_schedule_ablations_replay_as_the_toolkit_does(toolkit, legacy_runs, seed, policy, ablation):
    assert_same_replay(toolkit, legacy_runs[seed], policy, schedule=ABLATIONS[ablation])


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("policy", list(LEGACY))
@pytest.mark.parametrize("fixed_age", [0, 1, 3, 20])
def test_fixed_age_replays_as_the_toolkit_does(toolkit, legacy_runs, seed, policy, fixed_age):
    assert_same_replay(toolkit, legacy_runs[seed], policy, fixed_age=fixed_age)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("policy", list(LEGACY))
def test_rescored_references_replay_as_the_toolkit_does(toolkit, legacy_runs, seed, policy):
    assert_same_replay(toolkit, legacy_runs[seed], policy, stored_scoring="rescore")
    assert_same_replay(toolkit, legacy_runs[seed], policy, stored_scoring="rescore",
                       schedule=ABLATIONS["no decoding change"])


GENERATED = [dict(seed=s, n_items=n, rounds=r, schedule=sch, accept_bias=bias)
             for s, (n, r, sch, bias) in enumerate([
                 (30, 6, {0: "E1", 2: "E2", 4: "E4"}, 0),
                 (17, 9, {0: "E1", 3: "E3", 6: "E2"}, 0),
                 (64, 4, {0: "E2"}, 1),
                 (25, 12, {0: "E4", 1: "E3", 2: "E2", 3: "E1", 7: "E4"}, 0),
                 (40, 7, {0: "E3", 5: "E1"}, 2),
                 (8, 5, {0: "E1", 1: "E2", 2: "E1", 3: "E2"}, 0),
                 (50, 1, {0: "E1"}, 0),
                 (33, 10, {0: "E2", 4: "E4", 8: "E3"}, -1),
                 (21, 8, {0: "E1", 6: "E4"}, 3),
             ], start=11)]


@pytest.mark.parametrize("shape", GENERATED, ids=lambda s: f"seed{s['seed']}")
@pytest.mark.parametrize("policy", list(LEGACY))
def test_generated_runs_replay_as_the_toolkit_does(toolkit, shape, policy):
    legacy_run = make_legacy_run(**shape)
    assert_same_replay(toolkit, legacy_run, policy)
    assert_same_replay(toolkit, legacy_run, policy, fixed_age=2)
    assert_same_replay(toolkit, legacy_run, policy, stored_scoring="rescore")
    assert_same_replay(toolkit, legacy_run, policy, schedule={0: "E3", 2: "E4", 3: "E1"})


AGE_KEYS = ("round", "stored_win", "rerun_win", "inflation", "promote", "false_accept", "promote_rerun",
            "false_accept_rerun", "env_changed")


def assert_same_pairs(toolkit, legacy_run, age, stored_scoring="as_recorded", **where):
    view = toolkit.analysis.RunView(legacy_run, stored_scoring=stored_scoring)
    expected = toolkit.analysis.age_pairs(view, age, **where)
    ours = engine.age_pairs(schema.load(legacy_run), age, stored_scoring=stored_scoring, **where)
    assert [{k: m[k] for k in AGE_KEYS} for m in ours] == [{k: m[k] for k in AGE_KEYS} for m in expected]


@pytest.mark.parametrize("seed", SEEDS)
def test_age_pairs_are_the_toolkit_pairs(toolkit, legacy_runs, seed):
    for age in range(0, 12):
        assert_same_pairs(toolkit, legacy_runs[seed], age)
        for env in ("E1", "E2", "E3", "E4"):
            assert_same_pairs(toolkit, legacy_runs[seed], age, force_stored_env="E1", current_env=env)
    assert_same_pairs(toolkit, legacy_runs[seed], 3, stored_scoring="rescore", force_stored_env="E1", current_env="E4")
    assert_same_pairs(toolkit, legacy_runs[seed], 2, schedule=ABLATIONS["no extraction change"])


@pytest.mark.parametrize("shape", GENERATED, ids=lambda s: f"seed{s['seed']}")
def test_age_pairs_on_generated_runs(toolkit, shape):
    legacy_run = make_legacy_run(**shape)
    for age in range(0, shape["rounds"] + 1):
        assert_same_pairs(toolkit, legacy_run, age)
        assert_same_pairs(toolkit, legacy_run, age, force_stored_env="E2", current_env="E3")
        assert_same_pairs(toolkit, legacy_run, age, stored_scoring="rescore")


def test_study_age_rows_are_the_toolkit_age_rows(toolkit, legacy_runs, paper_runs):
    views = [toolkit.analysis.RunView(legacy_runs[s], stored_scoring="as_recorded") for s in SEEDS]
    result = engine.study([paper_runs[s] for s in SEEDS])
    assert result["age"]["stored_env"] == "E1" and result["age"]["ages"] == [0, 1, 3, 5, 10]
    assert list(result["age"]["by_env"]) == ["E1", "E4"]
    for env, rows in result["age"]["by_env"].items():
        for row in rows:
            expected = toolkit.analysis.age_row(views, row["age"], env)
            assert row["pairs"] == expected["pairs"]
            assert row["promoted"] == expected["promoted"]
            assert row["false_accepts"] == expected["false_accepts"]
            assert len(row["per_run"]) == len(expected["inflation"]) == 5
            assert all(close(a, 100 * b) for a, b in zip(row["per_run"], expected["inflation"]))
            assert toolkit.analysis.ci95(row["per_run"]) == f"[{row['lo']:+.2f}, {row['hi']:+.2f}]"


def test_study_probe_is_the_toolkit_probe(toolkit, legacy_runs, paper_runs):
    views = [toolkit.analysis.RunView(legacy_runs[s], stored_scoring="as_recorded") for s in SEEDS]
    result = engine.study([paper_runs[s] for s in SEEDS])
    assert (result["probe"]["age"], result["probe"]["stored_env"]) == (3, "E1")
    for env in ("E1", "E2", "E3", "E4"):
        sums = [toolkit.analysis.summarise(toolkit.analysis.age_pairs(v, 3, force_stored_env="E1", current_env=env))
                for v in views]
        per_seed = [100 * s["inflation"] for s in sums]
        cell = result["probe"]["by_env"][env]
        assert all(close(a, b) for a, b in zip(cell["per_run"], per_seed))
        assert toolkit.analysis.ci95(per_seed) == f"[{cell['lo']:+.2f}, {cell['hi']:+.2f}]"
        assert toolkit.analysis.sign_count(per_seed) == f"{cell['same_sign']}/5"


def test_verdict_flips_are_the_toolkit_verdict_flips(toolkit, legacy_runs, paper_runs):
    # export_replay.extractor_flips, written out: it cannot be imported without its model code.
    rows = [r for s in SEEDS
            for r in toolkit.analysis.candidate_truth(toolkit.analysis.RunView(legacy_runs[s], "as_recorded"))]
    flipped = [r for r in rows if toolkit.analysis.outcome(r["delta_E1"]) != toolkit.analysis.outcome(r["delta_E3"])]
    result = engine.study([paper_runs[s] for s in SEEDS])
    assert result["verdict_flips"] == {"n": len(rows), "flipped": len(flipped)}
