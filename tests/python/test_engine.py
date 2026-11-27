from __future__ import annotations

import copy
import json
import os

import pytest

from conftest import GOLDEN, ROOT, SEEDS, make_legacy_run, paper_run_path, small_run
from driftaudit import __version__, engine, schema
from driftaudit.envs import Environment
from driftaudit.errors import DriftAuditError

# Five rounds, four items. The environment changes from E1 to E3 at round 2: same decoding,
# lenient extractor, so every prompt's stored text is simply read more generously.
LABELS = {
    "p0": {"E1": [1, 0, 0, 0], "E3": [1, 1, 1, 0]},
    "c1": {"E1": [1, 1, 0, 0], "E3": [1, 1, 1, 0]},     # a real gain over p0
    "c2": {"E1": [1, 0, 1, 0], "E3": [1, 0, 1, 0]},     # ties c1, still beats the round-0 reference
    "c3": {"E1": [1, 1, 0, 0], "E3": [1, 1, 0, 0]},     # beats p0 as stored, not p0 as it reads now
    "c4": {"E1": [1, 1, 0, 1], "E3": [1, 1, 1, 1]},     # a real gain over everything
    "c5": {"E1": [1, 1, 0, 0], "E3": [1, 1, 1, 0]},     # worse than c4
}
# The one rerun that does not repeat its stored pass.
RERUNS = {("p0", "E3"): [1, 1, 0, 0]}
# The recorded loop kept the round-0 reference throughout and so accepted everything.
CANDIDATES = [
    {"id": "C1", "round": 0, "prompt": "c1", "parent": "p0", "env": "E1", "note": "ok", "wins": 1, "losses": 0, "accepted": True},
    {"id": "C2", "round": 1, "prompt": "c2", "parent": "c1", "env": "E1", "note": "ok", "wins": 1, "losses": 0, "accepted": True},
    {"id": "C3", "round": 2, "prompt": "c3", "parent": "c2", "env": "E3", "note": "ok", "wins": 1, "losses": 0, "accepted": True},
    {"id": "C4", "round": 3, "prompt": "c4", "parent": "c3", "env": "E3", "note": "ok", "wins": 3, "losses": 0, "accepted": True},
    {"id": "C5", "round": 4, "prompt": "c5", "parent": "c4", "env": "E3", "note": "ok", "wins": 2, "losses": 0, "accepted": True},
]
SNAPSHOTS = ["p0", "c1", "c2", "c3", "c4"]
SCHEDULE = {0: "E1", 2: "E3"}


def make(labels=LABELS, reruns=RERUNS, candidates=CANDIDATES, schedule=SCHEDULE, references=False, **extra):
    candidates = [dict(c) for c in candidates]
    if references:
        for c in candidates:
            c["reference"] = {"prompt": "p0", "env": "E1", "pass": "current"}
    return small_run(labels, schedule, SNAPSHOTS[:len(candidates)], candidates, n_items=4, reruns=reruns,
                     n_dev=3, **extra)


def column(block, key):
    return [d[key] for d in block["decisions"]]


# pair

def test_pair_counts_wins_losses_and_agreements():
    assert engine.pair("1100", "1010") == (1, 1, 1, 1)
    assert engine.pair("1111", "0000") == (4, 0, 0, 0)
    assert engine.pair("", "") == (0, 0, 0, 0)


def test_pair_matches_the_toolkit_on_lists(toolkit):
    cand, ref = [1, 0, 1, 1, 0, 0, 1], [0, 0, 1, 0, 1, 0, 1]
    assert engine.pair(schema.encode_labels(cand), schema.encode_labels(ref)) == toolkit.analysis.pair(cand, ref)


# policies

def test_policy_ids_and_names_are_the_published_ones():
    assert list(engine.POLICIES) == ["frozen", "stored_incumbent", "per_batch", "env_triggered", "periodic", "as_run"]
    assert [p["name"] for p in engine.POLICIES.values()] == \
        ["Frozen", "Stored incumbent", "Per-batch", "Environment-triggered", "Every k rounds", "As run"]
    assert all(p["rule"] for p in engine.POLICIES.values())


def test_frozen_keeps_the_round_zero_reference_and_accepts_on_stale_labels():
    block = engine.simulate(make(), "frozen")
    assert (block["id"], block["name"], block["available"]) == ("frozen", "Frozen", True)
    assert column(block, "ref_prompt") == ["p0"] * 5 and column(block, "ref_env") == ["E1"] * 5
    assert column(block, "ref_round") == [0] * 5 and column(block, "ref_age") == [0, 1, 2, 3, 4]
    assert column(block, "ref_fresh") == [False] * 5 and column(block, "ref_pass") == ["current"] * 5
    assert column(block, "env") == ["E1", "E1", "E3", "E3", "E3"]
    assert column(block, "env_mismatch") == [False, False, True, True, True]
    assert column(block, "incumbent") == ["p0", "c1", "c2", "c3", "c4"]
    assert list(zip(column(block, "wins"), column(block, "losses"))) == [(1, 0), (1, 0), (1, 0), (3, 0), (2, 0)]
    assert list(zip(column(block, "rerun_wins"), column(block, "rerun_losses"))) == [(1, 0), (1, 0), (0, 0), (2, 0), (1, 0)]
    assert column(block, "accepted") == [True] * 5
    assert column(block, "rerun_accepts") == [True, True, False, True, True]
    assert column(block, "false_accept") == [False, True, True, False, True]
    assert column(block, "false_reject") == [False] * 5
    assert column(block, "inflation") == [0.0, 0.0, 0.25, 0.25, 0.25]
    assert (block["accepted"], block["false_accepts"], block["false_rejects"], block["refreshes"]) == (5, 3, 0, 0)
    assert block["false_accept_rate"] == 3 / 5
    assert (block["final_prompt"], block["final_acc"]) == ("c5", 0.75)
    assert block["inflation"] == pytest.approx(0.15)


def test_ground_truth_is_judged_under_the_current_environment():
    block = engine.simulate(make(), "frozen")
    assert column(block, "inc_acc") == [0.25, 0.5, 0.5, 0.5, 1.0]
    assert column(block, "cand_acc") == [0.5, 0.5, 0.5, 1.0, 0.75]
    assert column(block, "delta_pp") == [25.0, 0.0, 0.0, 50.0, -25.0]
    assert column(block, "outcome") == ["improved", "no change", "no change", "improved", "worse"]


def test_a_false_accept_is_attributed_to_its_cause():
    block = engine.simulate(make(), "frozen")
    # Round 1: no environment change yet. Round 2: the rerun reference would have refused.
    # Round 4: the rerun reference would have accepted as well.
    assert column(block, "cause") == [None, "no_drift", "stale", None, "anyway"]
    assert block["causes"] == {"stale": 1, "anyway": 1, "no_drift": 1}


def test_stored_incumbent_compares_with_the_outputs_stored_at_the_last_accept():
    block = engine.simulate(make(), "stored_incumbent")
    assert column(block, "ref_prompt") == ["p0", "c1", "c1", "c1", "c4"]
    assert column(block, "ref_env") == ["E1", "E1", "E1", "E1", "E3"]
    assert column(block, "ref_round") == [0, 0, 0, 0, 3] and column(block, "ref_age") == [0, 1, 2, 3, 1]
    assert column(block, "env_mismatch") == [False, False, True, True, False]
    assert column(block, "accepted") == [True, False, False, True, False]
    assert (block["false_accepts"], block["false_rejects"], block["refreshes"]) == (0, 0, 0)
    assert (block["final_prompt"], block["final_acc"]) == ("c4", 1.0)


def test_per_batch_reruns_the_incumbent_every_round():
    block = engine.simulate(make(), "per_batch")
    assert column(block, "ref_fresh") == [True] * 5 and column(block, "ref_pass") == ["rerun"] * 5
    assert column(block, "ref_prompt") == ["p0", "c1", "c1", "c1", "c4"]
    assert column(block, "ref_env") == column(block, "env")
    assert column(block, "ref_age") == [0] * 5 and column(block, "env_mismatch") == [False] * 5
    assert column(block, "inflation") == [0.0] * 5
    assert column(block, "accepted") == [True, False, False, True, False]
    assert block["refreshes"] == 5


def test_environment_triggered_reruns_only_when_the_fingerprint_changes():
    block = engine.simulate(make(), "env_triggered")
    assert column(block, "ref_fresh") == [False, False, True, False, False]
    # The rerun made at round 2 stays the reference until the next accept.
    assert column(block, "ref_pass") == ["current", "current", "rerun", "rerun", "current"]
    assert column(block, "ref_prompt") == ["p0", "c1", "c1", "c1", "c4"]
    assert column(block, "ref_env") == ["E1", "E1", "E3", "E3", "E3"]
    assert column(block, "ref_round") == [0, 0, 2, 2, 3] and column(block, "ref_age") == [0, 1, 0, 1, 1]
    assert column(block, "env_mismatch") == [False] * 5
    assert column(block, "accepted") == [True, False, False, True, False]
    assert (block["refreshes"], block["false_accepts"], block["false_rejects"]) == (1, 0, 0)


def test_environment_triggered_compares_fingerprints_not_ids():
    run = make()
    run["environments"]["E3"]["fingerprint"] = run["environments"]["E1"]["fingerprint"]
    block = engine.simulate(run, "env_triggered")
    assert block["refreshes"] == 0 and column(block, "env_mismatch") == [False] * 5


def test_a_stale_reference_can_also_reject_a_real_gain():
    # The extractor gets stricter at round 1, so the stored reference now flatters the incumbent.
    labels = {"p0": {"E3": [1, 1, 1, 0], "E1": [1, 0, 0, 0]}, "c1": {"E3": [1, 1, 1, 0], "E1": [1, 0, 0, 0]},
              "c2": {"E3": [1, 1, 1, 0], "E1": [1, 1, 0, 0]}}
    cands = [{"id": "C1", "round": 0, "prompt": "c1", "parent": "p0", "accepted": False},
             {"id": "C2", "round": 1, "prompt": "c2", "parent": "p0", "accepted": False}]
    run = small_run(labels, {0: "E3", 1: "E1"}, ["p0", "p0"], cands, n_items=4)
    frozen = engine.simulate(run, "frozen")
    assert column(frozen, "accepted") == [False, False] and column(frozen, "false_reject") == [False, True]
    assert (frozen["false_rejects"], frozen["final_prompt"]) == (1, "p0")
    triggered = engine.simulate(run, "env_triggered")
    assert column(triggered, "accepted") == [False, True] and triggered["false_rejects"] == 0


def test_calls_follow_the_toolkit_accounting():
    run = make()
    frozen, batch, triggered = (engine.simulate(run, p) for p in ("frozen", "per_batch", "env_triggered"))
    # Per round: one proposal plus the dev pass (3 items here), and the candidate on 4 items.
    assert frozen["calls"] == {"proposer": 20, "candidate_eval": 20, "reference_refresh": 0}
    assert batch["calls"] == {"proposer": 20, "candidate_eval": 20, "reference_refresh": 20}
    assert (frozen["total_calls"], batch["total_calls"], triggered["total_calls"]) == (40, 60, 44)


def test_dev_items_come_from_cost_before_the_task():
    run = make()
    run["cost"] = {"n_dev": 10, "proposal_calls": 2}
    assert engine.simulate(run, "frozen")["calls"]["proposer"] == 5 * 12
    run["cost"] = {}
    run["task"].pop("n_dev")
    assert engine.simulate(run, "frozen")["calls"]["proposer"] == 5


# periodic, margin, fixed age, rescore

def test_periodic_reruns_once_the_reference_is_k_rounds_old():
    run = make()
    one = engine.simulate(run, "periodic", periodic_k=1)
    assert column(one, "ref_fresh") == [False, True, True, True, True] and one["refreshes"] == 4
    assert column(one, "accepted") == [True, False, False, True, False]
    three = engine.simulate(run, "periodic", periodic_k=3)
    assert column(three, "ref_fresh") == [False, False, False, True, False] and three["refreshes"] == 1
    assert column(three, "ref_round") == [0, 0, 0, 3, 3] and column(three, "ref_age") == [0, 1, 2, 0, 1]
    # Round 2 still reads c1 as stored under E1, across the environment change.
    assert three["decisions"][2]["env_mismatch"] and (three["decisions"][2]["ref_prompt"], three["decisions"][2]["ref_env"]) == ("c1", "E1")
    assert three["name"] == "Every k rounds"


def test_periodic_takes_the_candidates_labels_as_reference_after_an_accept():
    block = engine.simulate(make(), "periodic", periodic_k=2)
    assert column(block, "ref_prompt") == ["p0", "c1", "c1", "c1", "c4"]
    assert column(block, "ref_pass") == ["current", "current", "rerun", "rerun", "current"]
    assert column(block, "ref_round") == [0, 0, 2, 2, 3]


def test_periodic_default_is_three_rounds():
    run = make()
    assert engine.simulate(run, "periodic") == engine.simulate(run, "periodic", periodic_k=3)
    assert engine.audit(run)["options"]["periodic_k"] == 3


def test_margin_asks_for_more_than_a_bare_majority():
    block = engine.simulate(make(), "frozen", margin=1)
    assert column(block, "accepted") == [False, False, False, True, True]
    assert column(block, "false_reject") == [True, True, False, False, False]
    assert column(block, "incumbent") == ["p0", "p0", "p0", "p0", "c4"]
    # The rerun reference gives round 4 one net win, which no longer clears the margin.
    assert column(block, "cause") == [None, None, None, None, "stale"]


def test_ties_are_not_accepted():
    block = engine.simulate(make(), "stored_incumbent")
    assert (block["decisions"][1]["wins"], block["decisions"][1]["losses"], block["decisions"][1]["accepted"]) == (1, 1, False)


def test_fixed_age_uses_the_snapshot_that_many_rounds_back():
    block = engine.simulate(make(), "frozen", fixed_age=1)
    assert column(block, "ref_prompt") == ["p0", "p0", "c1", "c2", "c3"]
    assert column(block, "ref_env") == ["E1", "E1", "E1", "E3", "E3"]
    assert column(block, "ref_round") == [0, 0, 1, 2, 3] and column(block, "ref_age") == [0, 1, 1, 1, 1]
    assert column(block, "ref_fresh") == [False] * 5
    for policy in ("stored_incumbent", "per_batch", "env_triggered", "periodic"):
        other = engine.simulate(make(), policy, fixed_age=1)
        assert other["decisions"] == block["decisions"] and other["refreshes"] == 0


def test_rescore_reads_the_stored_text_with_the_current_scorer():
    block = engine.simulate(make(), "frozen", stored_scoring="rescore")
    assert column(block, "ref_env") == ["E1"] * 5
    assert column(block, "ref_scored_env") == ["E1", "E1", "E3", "E3", "E3"]
    assert list(zip(column(block, "wins"), column(block, "losses"))) == [(1, 0), (1, 0), (0, 1), (1, 0), (0, 0)]
    assert column(block, "accepted") == [True, True, False, True, False]
    assert block["causes"] == {"stale": 0, "anyway": 0, "no_drift": 1}
    assert column(engine.simulate(make(), "frozen"), "ref_scored_env") == ["E1"] * 5


def test_rescore_falls_back_and_says_so_when_no_environment_shares_the_text():
    envs = {"A": Environment.make(id="A", model="m", temperature=0.0, scorer="strict"),
            "B": Environment.make(id="B", model="m", temperature=0.2, scorer="lenient")}
    labels = {h: {"A": per["E1"], "B": per["E3"]} for h, per in LABELS.items()}
    cands = [dict(c, env="A" if c["round"] < 2 else "B") for c in CANDIDATES]
    run = small_run(labels, {0: "A", 2: "B"}, SNAPSHOTS, cands, n_items=4, environments=envs)
    rescored = engine.audit(run, stored_scoring="rescore")
    plain = engine.audit(run)
    assert rescored["policies"]["frozen"]["decisions"] == plain["policies"]["frozen"]["decisions"]
    assert rescored["completeness"]["notes"] == [
        "rescore: no environment has decoding greedy-0.0 with scorer lenient; labels stored under A are used as recorded"]
    assert plain["completeness"]["notes"] == []


# as run

def test_as_run_needs_the_reference_the_loop_recorded():
    block = engine.simulate(make(), "as_run")
    assert (block["available"], block["missing"], block["missing_count"], block["decisions"]) == (False, [], 0, [])
    assert block["accepted"] is None and block["final_acc"] is None


def test_as_run_replays_the_recorded_decisions():
    run = make(references=True)
    block, frozen = engine.simulate(run, "as_run"), engine.simulate(run, "frozen")
    assert block["available"] and block["name"] == "As run"
    # The recorded loop was a frozen-reference loop, so the two agree decision for decision.
    assert block["decisions"] == frozen["decisions"]
    for key in ("accepted", "false_accepts", "false_rejects", "refreshes", "calls", "final_acc", "final_prompt", "causes"):
        assert block[key] == frozen[key]


def test_as_run_keeps_the_recorded_verdict_even_when_the_labels_disagree():
    run = make(references=True)
    run["candidates"][3]["accepted"] = False        # the loop turned C4 down
    run["candidates"][4]["parent"] = "c3"
    block = engine.simulate(run, "as_run")
    assert column(block, "accepted") == [True, True, True, False, True]
    assert column(block, "incumbent") == ["p0", "c1", "c2", "c3", "c3"]
    assert block["decisions"][3]["false_reject"] and (block["decisions"][3]["wins"], block["decisions"][3]["losses"]) == (3, 0)
    assert block["false_rejects"] == 1


def test_as_run_counts_recorded_reruns_as_refreshes():
    run = make(references=True)
    run["candidates"][2]["reference"] = {"prompt": "c2", "env": "E3", "pass": "rerun"}
    block = engine.simulate(run, "as_run")
    assert block["refreshes"] == 1 and block["calls"]["reference_refresh"] == 4
    d = block["decisions"][2]
    assert (d["ref_fresh"], d["ref_pass"], d["ref_round"], d["ref_age"], d["env_mismatch"]) == (True, "rerun", 2, 0, False)
    assert (d["wins"], d["losses"], d["inflation"]) == (1, 1, 0.0)


def test_as_run_falls_back_to_recorded_counts_when_reference_labels_are_absent():
    run = make(references=True)
    run["prompts"]["old"] = "a reference from before the run"
    run["candidates"][0]["reference"] = {"prompt": "old", "env": "E1", "pass": "current"}
    run["candidates"][0].update(wins=9, losses=2)
    block = engine.simulate(run, "as_run")
    d = block["decisions"][0]
    assert block["available"] and (d["wins"], d["losses"], d["accepted"]) == (9, 2, True)
    assert (d["rerun_wins"], d["inflation"], d["rerun_accepts"]) == (None, None, None)
    assert (d["inc_acc"], d["cand_acc"], d["false_accept"]) == (0.25, 0.5, False)


def test_as_run_dates_a_stored_reference_from_the_round_it_was_produced():
    run = make(references=True)
    run["candidates"][4]["reference"] = {"prompt": "c3", "env": "E3", "pass": "current"}
    block = engine.simulate(run, "as_run")
    # c3 was first scored under E3 as the candidate of round 2.
    assert (block["decisions"][4]["ref_round"], block["decisions"][4]["ref_age"]) == (2, 2)
    assert column(block, "ref_round")[:4] == [0, 0, 0, 0]


# sparse banks

def without(run, *keys):
    run = copy.deepcopy(run)
    for prompt, env, tag in keys:
        del run["labels"][prompt][env][tag]
    return run


def test_a_missing_rerun_blanks_only_what_depends_on_it():
    block = engine.simulate(without(make(), ("p0", "E3", "rerun")), "frozen")
    assert block["available"] and block["missing"] == []
    assert column(block, "accepted") == [True] * 5
    assert column(block, "rerun_wins") == [1, 1, None, None, None]
    assert column(block, "inflation") == [0.0, 0.0, None, None, None]
    assert column(block, "rerun_accepts") == [True, True, None, None, None]
    # Without the rerun a false accept under a changed environment cannot be told apart.
    assert column(block, "cause") == [None, "no_drift", None, None, None]
    assert block["causes"] == {"stale": 0, "anyway": 0, "no_drift": 1} and block["false_accepts"] == 3
    assert block["inflation"] == 0.0


def test_a_policy_that_needs_absent_labels_reports_them_instead_of_failing():
    run = without(make(), ("c1", "E3", "rerun"))
    block = engine.simulate(run, "per_batch")
    assert block["available"] is False and block["decisions"] == []
    assert block["missing"] == [{"prompt": "c1", "env": "E3", "pass": "rerun"}] and block["missing_count"] == 1
    assert (block["accepted"], block["false_accepts"], block["final_acc"], block["inflation"], block["calls"]) == \
        (None, None, None, None, None)
    assert (block["id"], block["name"]) == ("per_batch", "Per-batch")
    assert engine.simulate(run, "env_triggered")["available"] is False
    assert engine.simulate(run, "frozen")["available"] is True


def test_missing_labels_are_listed_once_and_capped():
    labels = {h: {"E1": per["E1"]} for h, per in LABELS.items()}       # nothing recorded under E3
    block = engine.simulate(make(labels=labels, reruns={}), "frozen")
    assert block["available"] is False
    assert block["missing"] == [{"prompt": "c3", "env": "E3", "pass": "current"},
                                {"prompt": "c2", "env": "E3", "pass": "current"},
                                {"prompt": "c4", "env": "E3", "pass": "current"},
                                {"prompt": "c5", "env": "E3", "pass": "current"}]
    assert block["missing_count"] == 4

    many = {f"q{i}": {"E1": [1, 0, 0, 0]} for i in range(31)}
    cands = [{"id": f"C{i}", "round": i - 1, "prompt": f"q{i}", "parent": "q0", "accepted": False} for i in range(1, 31)]
    run = small_run(many, {0: "E3"}, ["q0"] * 30, cands, n_items=4)
    block = engine.simulate(run, "frozen")
    assert len(block["missing"]) == 20 and block["missing_count"] == 31


def test_audit_never_raises_on_a_sparse_bank():
    labels = {"p0": {"E1": [1, 0, 0, 0]}, "c1": {"E1": [1, 1, 0, 0]}}
    run = make(labels=labels, reruns={("p0", "E1"): None, ("c1", "E1"): None})
    result = engine.audit(run)
    assert result["completeness"]["full_bank"] is False
    assert {p: b["available"] for p, b in result["policies"].items()} == {p: False for p in engine.POLICIES}
    assert result["rounds"][0]["candidate_acc"] == 0.5 and result["rounds"][2]["candidate_acc"] is None
    json.dumps(result, allow_nan=False)


def test_full_bank_means_both_passes_for_every_prompt_and_environment(paper_runs):
    assert engine.audit(paper_runs[1])["completeness"] == {"full_bank": True, "notes": []}
    assert engine.audit(without(paper_runs[1], ("cf7e8a98a5cc", "E2", "rerun")))["completeness"]["full_bank"] is False
    assert engine.audit(make())["completeness"]["full_bank"] is False       # E2 and E4 were never measured


# audit

def test_audit_result_has_the_documented_shape():
    result = engine.audit(make(references=True))
    assert set(result) == {"schema", "tool", "run", "options", "environments", "rounds", "policies", "scorer_flips",
                           "completeness"}
    assert result["schema"] == "driftaudit.audit/v1"
    assert result["tool"] == {"name": "driftaudit", "version": __version__}
    assert result["run"] == {"id": "small", "seed": 1, "source": "synthetic",
                             "task": {"name": "toy", "n_items": 4, "n_dev": 3}, "model": {"id": "test-model"},
                             "n_items": 4, "n_rounds": 5, "n_candidates": 5}
    assert result["options"] == {"stored_scoring": "as_recorded", "margin": 0, "schedule": {"0": "E1", "2": "E3"},
                                 "schedule_overridden": False, "fixed_age": None, "periodic_k": 3}
    assert list(result["policies"]) == list(engine.POLICIES)
    block = result["policies"]["frozen"]
    assert set(block) == {"id", "name", "rule", "available", "missing", "missing_count", "accepted", "false_accepts",
                          "false_rejects", "false_accept_rate", "refreshes", "calls", "total_calls", "final_acc",
                          "final_prompt", "inflation", "causes", "decisions"}
    assert set(block["decisions"][0]) == {
        "round", "env", "candidate", "incumbent", "ref_prompt", "ref_env", "ref_pass", "ref_scored_env", "ref_fresh",
        "ref_round", "ref_age", "env_mismatch", "wins", "losses", "rerun_wins", "rerun_losses", "inflation",
        "accepted", "rerun_accepts", "inc_acc", "cand_acc", "delta_pp", "outcome", "false_accept", "false_reject",
        "cause"}
    for other in result["policies"].values():
        assert set(other) == set(block)


def test_audit_blocks_are_what_simulate_returns():
    run = make(references=True)
    result = engine.audit(run, margin=1, periodic_k=2)
    for policy, block in result["policies"].items():
        assert block == engine.simulate(run, policy, margin=1, periodic_k=2)


def test_audit_can_be_limited_to_some_policies():
    result = engine.audit(make(), policies=["env_triggered", "frozen"])
    assert list(result["policies"]) == ["frozen", "env_triggered"]


def test_environments_are_listed_in_order_of_first_use():
    result = engine.audit(make())
    assert [(e["id"], e["first_round"], e["rounds"]) for e in result["environments"]] == \
        [("E1", 0, [0, 1]), ("E3", 2, [2, 3, 4]), ("E2", None, []), ("E4", None, [])]
    first = result["environments"][0]
    assert set(first) == {"id", "name", "decoding", "scorer", "fingerprint", "detail", "first_round", "rounds"}
    assert (first["name"], first["decoding"], first["scorer"]) == ("Unchanged", "greedy-0.0", "v1")


def test_rounds_describe_the_recorded_trajectory():
    result = engine.audit(make())
    assert [r["round"] for r in result["rounds"]] == [0, 1, 2, 3, 4]
    assert [r["env"] for r in result["rounds"]] == ["E1", "E1", "E3", "E3", "E3"]
    assert [r["env_changed"] for r in result["rounds"]] == [False, False, True, False, False]
    assert [r["incumbent"] for r in result["rounds"]] == SNAPSHOTS
    assert [r["candidate"] for r in result["rounds"]] == ["c1", "c2", "c3", "c4", "c5"]
    assert [r["candidate_id"] for r in result["rounds"]] == ["C1", "C2", "C3", "C4", "C5"]
    assert [r["candidate_acc"] for r in result["rounds"]] == [0.5, 0.5, 0.5, 1.0, 0.75]
    assert [r["incumbent_acc"] for r in result["rounds"]] == [0.25, 0.5, 0.5, 0.5, 1.0]
    assert set(result["rounds"][0]) == {"round", "env", "env_changed", "incumbent", "candidate", "candidate_id", "note",
                                        "candidate_acc", "incumbent_acc"}


def test_a_schedule_override_moves_the_environment_changes():
    run = make()
    result = engine.audit(run, schedule={0: "E1", 4: "E3"})
    assert result["options"]["schedule"] == {"0": "E1", "4": "E3"} and result["options"]["schedule_overridden"]
    assert [r["env"] for r in result["rounds"]] == ["E1", "E1", "E1", "E1", "E3"]
    assert [e["rounds"] for e in result["environments"][:2]] == [[0, 1, 2, 3], [4]]
    assert column(result["policies"]["frozen"], "env_mismatch") == [False, False, False, False, True]
    assert run["schedule"] == {"0": "E1", "2": "E3"}
    same = engine.audit(run, schedule={"0": "E1", "2": "E3"})
    assert same["options"]["schedule_overridden"] is False


def test_scorer_flips_compare_environments_that_share_their_text():
    result = engine.audit(make())
    # p0 gains two items under the lenient reading, c1, c4 and c5 one each; nothing is lost.
    assert result["scorer_flips"] == [{"from_env": "E1", "to_env": "E3", "prompts": 6, "items": 24,
                                       "wrong_to_right": 5, "right_to_wrong": 0}]


def test_audit_reads_a_legacy_object_or_a_path(legacy_runs):
    by_object = engine.audit(legacy_runs[5])
    assert by_object["run"]["id"] == "gsm8k-qwen2.5-1.5b-seed5"
    assert engine.audit(paper_run_path(5)) == by_object


def test_audit_does_not_modify_the_run(paper_runs):
    before = json.dumps(paper_runs[2], sort_keys=True)
    engine.audit(paper_runs[2], schedule={0: "E1", 4: "E1", 8: "E3"}, stored_scoring="rescore", margin=2)
    assert json.dumps(paper_runs[2], sort_keys=True) == before


def test_audit_of_a_run_with_no_rounds_yet_is_empty_not_an_error():
    run = schema.new_run(id="empty", seed=0, task={"n_items": 4}, model={"id": "m"},
                         environments=[Environment.make(id="A", model="m")], schedule={0: "A"})
    result = engine.audit(run)
    assert result["rounds"] == [] and result["run"]["n_rounds"] == 0
    block = result["policies"]["frozen"]
    assert block["available"] and block["decisions"] == [] and block["accepted"] == 0
    assert (block["final_acc"], block["final_prompt"], block["inflation"], block["false_accept_rate"]) == (None,) * 4
    json.dumps(engine.study([run]), allow_nan=False)


def test_results_are_plain_json_without_nan(paper_runs):
    for seed in SEEDS:
        text = json.dumps(engine.audit(paper_runs[seed]), allow_nan=False)
        assert json.loads(text) == engine.audit(paper_runs[seed])


def test_bad_options_are_refused_with_a_reason():
    run = make()
    with pytest.raises(DriftAuditError, match="unknown policy"):
        engine.simulate(run, "sometimes")
    with pytest.raises(DriftAuditError, match="unknown policy"):
        engine.audit(run, policies=["frozen", "sometimes"])
    with pytest.raises(DriftAuditError, match="stored_scoring"):
        engine.audit(run, stored_scoring="relabel")
    with pytest.raises(DriftAuditError, match="E9"):
        engine.audit(run, schedule={0: "E9"})
    with pytest.raises(DriftAuditError, match="periodic_k"):
        engine.audit(run, periodic_k=0)
    with pytest.raises(DriftAuditError, match="fixed_age"):
        engine.audit(run, fixed_age=-1)


# item cells

def test_item_cells_classify_each_item_against_both_readings():
    run = make()
    decision = engine.simulate(run, "frozen")["decisions"][2]
    assert engine.item_cells(run, decision) == {
        "n": 4, "candidate": "1100", "reference_stored": "1000", "reference_rerun": "1100",
        "stored": "bwnn", "rerun": "bbnn"}


def test_item_cells_agree_with_the_decision_counts(paper_runs):
    run = paper_runs[5]
    result = engine.audit(run, stored_scoring="rescore")
    for block in result["policies"].values():
        for d in block["decisions"]:
            cells = engine.item_cells(run, d)
            assert (cells["stored"].count("w"), cells["stored"].count("l")) == (d["wins"], d["losses"])
            assert (cells["rerun"].count("w"), cells["rerun"].count("l")) == (d["rerun_wins"], d["rerun_losses"])
            assert len(cells["stored"]) == cells["n"] == 200


def test_item_cells_follow_a_rerun_that_became_the_reference():
    run = make()
    decision = engine.simulate(run, "env_triggered")["decisions"][3]
    cells = engine.item_cells(run, decision)
    assert (cells["candidate"], cells["reference_stored"], cells["stored"]) == ("1111", "1110", "bbbw")


def test_item_cells_leave_out_a_rerun_that_was_never_recorded():
    run = without(make(), ("p0", "E3", "rerun"))
    cells = engine.item_cells(run, engine.simulate(run, "frozen")["decisions"][2])
    assert (cells["rerun"], cells["reference_rerun"]) == (None, None) and cells["stored"] == "bwnn"


# age pairs (ported from toolkit/tests/test_age.py)

AGE_LABELS = {
    "p0": {"E1": [1, 0, 0, 0], "E4": [1, 1, 1, 0]},
    "p1": {"E1": [1, 1, 0, 0], "E4": [1, 1, 1, 0]},
    "p2": {"E1": [1, 0, 0, 1], "E4": [1, 1, 0, 0]},
    "p3": {"E1": [1, 0, 1, 0], "E4": [1, 1, 1, 0]},
}
AGE_RERUNS = {("p0", "E1"): [1, 1, 0, 0], ("p3", "E1"): [1, 1, 1, 0]}


def age_run(seed=1, labels=AGE_LABELS):
    cands = [{"id": f"C{i + 1}", "round": i, "prompt": f"p{i + 1}", "parent": p, "accepted": i == 0}
             for i, p in enumerate(["p0", "p1", "p1"])]
    return small_run(labels, {0: "E1", 1: "E4"}, ["p0", "p1", "p1"], cands, n_items=4, reruns=AGE_RERUNS,
                     seed=seed, id=f"age-{seed}")


def pairs(run, age, env):
    return engine.age_pairs(run, age, force_stored_env="E1", current_env=env)


def counts(ms):
    return (sum(m["promote"] for m in ms), sum(m["false_accept"] for m in ms),
            sum(m["promote_rerun"] for m in ms), sum(m["false_accept_rerun"] for m in ms))


def test_pairs_shrink_with_age():
    assert [len(pairs(age_run(), a, "E1")) for a in (0, 1, 2, 3)] == [3, 2, 1, 0]


def test_age_zero_unchanged_is_the_ground_truth_gate():
    ms = pairs(age_run(), 0, "E1")
    assert counts(ms) == (1, 0, 0, 0)
    assert sum(m["stored_win"] for m in ms) / 3 == pytest.approx(1 / 4)
    assert sum(m["rerun_win"] for m in ms) / 3 == pytest.approx(1 / 6)
    assert sum(m["inflation"] for m in ms) / 3 == pytest.approx(1 / 12)


def test_changed_environment_inflates_against_stored_labels():
    ms = pairs(age_run(), 0, "E4")
    assert [m["inflation"] for m in ms] == [0.5, 0.0, 0.25] and counts(ms) == (2, 2, 0, 0)
    assert all(m["env_changed"] for m in ms)


def test_false_accept_is_judged_against_the_incumbent_of_the_candidates_round():
    assert counts(pairs(age_run(), 1, "E1"))[:2] == (1, 1)
    assert counts(pairs(age_run(), 2, "E1"))[:2] == (1, 1)


def test_refreshing_an_old_reference_does_not_make_it_the_incumbent():
    weak = {**AGE_LABELS, "p0": {"E1": [1, 0, 0, 0], "E4": [1, 0, 0, 0]}}
    assert counts(pairs(age_run(1, weak), 2, "E4")) == (1, 1, 1, 1)


def test_age_pairs_skip_pairs_the_bank_cannot_score():
    run = without(age_run(), ("p1", "E1", "rerun"))
    assert [m["round"] for m in pairs(run, 0, "E1")] == [0]
    assert pairs(run, 0, "E2") == []


# study

def test_study_pools_counts_and_averages_per_run_values():
    other = {**AGE_LABELS, "p3": {**AGE_LABELS["p3"], "E4": [1, 1, 1, 1]}}
    runs = [age_run(1), age_run(2, other)]
    result = engine.study(runs, ages=(0, 1, 2))
    assert set(result) == {"schema", "tool", "options", "runs", "source", "n_runs", "n_decisions", "policies", "policy_tests",
                           "probe", "age", "scorer_flips", "verdict_flips"}
    assert result["schema"] == "driftaudit.study/v1"
    assert result["runs"] == [{"id": "age-1", "seed": 1, "source": "synthetic"},
                              {"id": "age-2", "seed": 2, "source": "synthetic"}]
    assert result["source"] == "synthetic"
    assert (result["n_runs"], result["n_decisions"]) == (2, 6)
    audits = [engine.audit(r) for r in runs]
    row = result["policies"]["frozen"]
    assert set(row) == {"name", "accepted", "false_accepts", "false_rejects", "false_accept_rate_pooled", "final_acc",
                        "total_calls", "refreshes", "causes", "per_run"}
    for key in ("accepted", "false_accepts", "false_rejects"):
        assert row[key] == sum(a["policies"]["frozen"][key] for a in audits)
    assert row["per_run"] == [{"id": a["run"]["id"], "seed": a["run"]["seed"],
                               **{k: a["policies"]["frozen"][k] for k in ("accepted", "false_accepts", "false_rejects",
                                                                           "final_acc", "total_calls", "refreshes")}}
                              for a in audits]
    finals = [a["policies"]["frozen"]["final_acc"] for a in audits]
    assert set(row["final_acc"]) == {"mean", "sd", "per_run"} and row["final_acc"]["per_run"] == finals
    assert row["final_acc"]["mean"] == sum(finals) / 2
    assert row["final_acc"]["sd"] == pytest.approx(abs(finals[0] - finals[1]) / 2 ** 0.5)
    assert set(row["total_calls"]) == set(row["refreshes"]) == {"mean", "sd"}
    assert row["causes"] == {k: sum(a["policies"]["frozen"]["causes"][k] for a in audits) for k in ("stale", "anyway", "no_drift")}


def test_study_age_rows_pool_promotions_over_runs():
    other = {**AGE_LABELS, "p3": {**AGE_LABELS["p3"], "E4": [1, 1, 1, 1]}}
    result = engine.study([age_run(1), age_run(2, other)], ages=(0, 1, 2))
    assert (result["age"]["stored_env"], result["age"]["ages"], list(result["age"]["by_env"])) == ("E1", [0, 1, 2], ["E1", "E4"])
    row = result["age"]["by_env"]["E4"][0]
    assert set(row) == {"age", "pairs", "mean", "lo", "hi", "per_run", "promoted", "false_accepts"}
    assert (row["age"], row["pairs"], row["promoted"], row["false_accepts"]) == (0, 6, 4, 3)
    assert row["per_run"] == pytest.approx([25.0, 25.0])
    assert [r["pairs"] for r in result["age"]["by_env"]["E1"]] == [6, 4, 2]


def test_study_default_ages_stop_below_the_run_length():
    result = engine.study([age_run()])
    assert result["age"]["ages"] == [0, 1]
    assert result["probe"]["age"] == 2          # min(3, rounds - 1)
    assert engine.study([age_run()], probe_age=1)["probe"]["age"] == 1


def test_study_of_one_run_has_values_but_no_interval():
    result = engine.study([age_run()], probe_age=0)
    cell = result["probe"]["by_env"]["E4"]
    assert set(cell) == {"mean", "lo", "hi", "sd", "per_run", "n_positive", "same_sign"}
    assert (cell["mean"], cell["sd"], cell["lo"], cell["hi"], cell["per_run"], cell["n_positive"]) == \
        (25.0, 0.0, None, None, [25.0], 1)
    assert result["policies"]["frozen"]["final_acc"]["sd"] == 0.0


def test_study_probe_covers_environments_every_run_defines():
    result = engine.study([age_run(1), age_run(2)])
    assert list(result["probe"]["by_env"]) == ["E1", "E2", "E3", "E4"]
    # E2 was never measured: there is no value to average, and that is not a zero.
    assert result["probe"]["by_env"]["E2"] == {"mean": None, "sd": None, "lo": None, "hi": None,
                                               "per_run": [None, None], "n_positive": 0, "same_sign": 0}


def test_study_only_pools_policies_every_run_can_replay():
    full = make(references=True)
    sparse = without(make(references=True, id="sparse", seed=2), ("c1", "E3", "rerun"))
    result = engine.study([full, sparse])
    # Per-batch, environment-triggered and every-3-rounds all need the rerun that is absent.
    assert list(result["policies"]) == ["frozen", "stored_incumbent", "as_run"]
    assert result["policy_tests"] == []
    both = engine.study([full, make(references=True, id="again", seed=2)])
    assert list(both["policies"]) == list(engine.POLICIES)
    assert [(t["a"], t["b"]) for t in both["policy_tests"]] == \
        [("env_triggered", p) for p in ("frozen", "stored_incumbent", "per_batch", "periodic", "as_run")]
    first = both["policy_tests"][0]
    assert set(first) == {"a", "b", "errors_a", "errors_b", "n", "fisher_p"}
    assert (first["errors_a"], first["errors_b"], first["n"]) == (0, 6, 10)


def test_study_passes_audit_options_through():
    runs = [make(), make(id="two", seed=2)]
    result = engine.study(runs, margin=1, policies=["frozen", "env_triggered"])
    assert list(result["policies"]) == ["frozen", "env_triggered"]
    assert result["policies"]["frozen"]["accepted"] == 2 * engine.simulate(runs[0], "frozen", margin=1)["accepted"]
    assert result["options"]["margin"] == 1


def test_study_verdict_flips_need_two_scorers_on_the_same_text():
    envs = [Environment.make(id="A", model="m"), Environment.make(id="B", model="m", temperature=0.2)]
    labels = {"p0": {"A": [1, 0, 0, 0]}, "c1": {"A": [1, 1, 0, 0]}}
    run = small_run(labels, {0: "A"}, ["p0"], [{"id": "C1", "round": 0, "prompt": "c1", "parent": "p0"}],
                    n_items=4, environments=envs)
    result = engine.study([run])
    assert result["verdict_flips"] is None and result["scorer_flips"] == []
    # In the five-round run C1 and C2 change verdict between the strict and the lenient reading.
    assert engine.study([make()])["verdict_flips"] == {"n": 5, "flipped": 2}


def test_study_needs_at_least_one_run():
    with pytest.raises(DriftAuditError, match="at least one run"):
        engine.study([])


def test_study_reads_legacy_objects(legacy_runs, paper_runs):
    assert engine.study([legacy_runs[1], legacy_runs[2]]) == engine.study([paper_runs[1], paper_runs[2]])


def test_generated_runs_audit_without_surprises():
    for seed in range(40, 46):
        run = schema.load(make_legacy_run(seed, n_items=20, rounds=5))
        result = engine.audit(run)
        assert result["completeness"]["full_bank"] and all(b["available"] for b in result["policies"].values())
        json.dumps(result, allow_nan=False)


# goldens

def test_goldens_are_current():
    # Fails when the engine's output has moved away from tests/golden. If the change is
    # intended, regenerate with: python -m driftaudit._golden
    from driftaudit import _golden
    assert _golden.check(GOLDEN) == []


def test_golden_check_names_a_stale_or_missing_file(tmp_path):
    import shutil
    from driftaudit import _golden
    copy_dir = tmp_path / "tests" / "golden"
    shutil.copytree(GOLDEN, copy_dir)
    shutil.copytree(os.path.join(ROOT, "toolkit", "runs"), tmp_path / "toolkit" / "runs")
    assert _golden.check(str(copy_dir)) == []
    stale = copy_dir / "audit-paper-seed5.json"
    stale.write_text(stale.read_text(encoding="utf-8").replace('"accepted": 8', '"accepted": 9'), encoding="utf-8")
    (copy_dir / "study-paper.json").unlink()
    (copy_dir / "audit-old-case.json").write_text("{}", encoding="utf-8")
    assert _golden.check(str(copy_dir)) == [
        "audit-paper-seed5.json: differs from what the engine produces now",
        "study-paper.json: missing",
        "audit-old-case.json: not in the manifest any more"]
    assert _golden.main(["--check", "--dir", str(copy_dir)]) == 1
    assert sorted(_golden.write(str(copy_dir))) == ["audit-old-case.json", "audit-paper-seed5.json", "study-paper.json"]
    assert _golden.main(["--check", "--dir", str(copy_dir)]) == 0
    assert (copy_dir / "scorer_cases.json").exists()


def golden_cases():
    with open(os.path.join(GOLDEN, "manifest.json"), encoding="utf-8") as f:
        return {case["name"]: case for case in json.load(f)}


def golden(name):
    with open(os.path.join(GOLDEN, golden_cases()[name]["result"]), encoding="utf-8") as f:
        return json.load(f)


def test_manifest_names_inputs_options_and_result_of_every_case():
    cases = golden_cases()
    assert {f"paper-seed{s}" for s in SEEDS} | {"paper-study", "synthetic-a", "synthetic-b", "synthetic-c"} <= set(cases)
    for seed in (1, 5):
        for variant in ("no-decoding-change", "no-extraction-change", "fixed-age-1", "rescore", "margin-2", "periodic-2"):
            assert f"paper-seed{seed}-{variant}" in cases
    for case in cases.values():
        assert set(case) == {"name", "kind", "options", "result", "run" if case["kind"] == "audit" else "runs"}
        assert case["kind"] in ("audit", "study") and isinstance(case["options"], dict)
        for rel in [case["run"]] if case["kind"] == "audit" else case["runs"]:
            assert os.path.exists(os.path.join(GOLDEN, rel)), rel
        assert os.path.exists(os.path.join(GOLDEN, case["result"]))
    assert cases["paper-seed1"]["run"] == "../../toolkit/runs/run_seed1_hf_Qwen2.5-1.5B-Instruct_n200_r11.json"
    assert len({case["result"] for case in cases.values()}) == len(cases)


def test_synthetic_golden_runs_differ_in_shape_and_say_what_they_are():
    shapes = {}
    for name in ("synthetic-a", "synthetic-b", "synthetic-c"):
        run = schema.load(os.path.join(GOLDEN, "runs", f"{name}.json"))
        assert run["source"] == "synthetic" and run["id"] == name
        assert all("reference" in c for c in run["candidates"])
        shapes[name] = (run["task"]["n_items"], len(run["snapshots"]), len(run["environments"]))
    assert shapes == {"synthetic-a": (40, 5, 2), "synthetic-b": (64, 8, 6), "synthetic-c": (25, 3, 2)}


def test_golden_cases_reach_what_the_paper_runs_do_not():
    sparse = golden("synthetic-c")
    assert sparse["completeness"]["full_bank"] is False
    assert sparse["policies"]["per_batch"]["available"] is False and sparse["policies"]["per_batch"]["missing"]
    frozen = sparse["policies"]["frozen"]
    assert frozen["available"] and any(d["rerun_wins"] is None for d in frozen["decisions"])
    assert any(d["false_accept"] and d["cause"] is None for d in frozen["decisions"])
    # The loop of the sparse run kept only win and loss counts of its reference.
    recorded = schema.load(os.path.join(GOLDEN, "runs", "synthetic-c.json"))["candidates"]
    assert [(d["wins"], d["losses"]) for d in sparse["policies"]["as_run"]["decisions"]] == \
        [(c["wins"], c["losses"]) for c in recorded]

    six = golden("synthetic-b")
    assert len(six["environments"]) == 6 and [e["first_round"] for e in six["environments"]][:3] == [0, 3, 6]
    assert six["policies"]["as_run"]["refreshes"] == 2
    assert any(f["right_to_wrong"] > 0 for f in six["scorer_flips"])
    assert golden("synthetic-b-what-if")["options"]["schedule_overridden"]
    assert any(b["false_rejects"] for b in golden("synthetic-b-what-if")["policies"].values())
    assert golden("synthetic-a-rescore")["completeness"]["notes"]
    assert golden("synthetic-c-periodic-1")["policies"]["periodic"]["available"] is False

    pooled = golden("synthetic-study-b-c")
    assert "per_batch" not in pooled["policies"] and "frozen" in pooled["policies"] and pooled["policy_tests"] == []
    assert any(None in row["per_run"] for rows in pooled["age"]["by_env"].values() for row in rows)
    seen = {d["cause"] for name in golden_cases() if golden_cases()[name]["kind"] == "audit"
            for b in golden(name)["policies"].values() for d in b["decisions"]}
    assert seen == {None, "stale", "anyway", "no_drift"}


def test_the_bundled_v1_paper_runs_audit_like_the_toolkit_files():
    path = os.path.join(ROOT, "data", "runs", "paper", "seed5.json")
    if not os.path.exists(path):
        pytest.skip("data/runs/paper is not built yet")
    assert json.loads(json.dumps(engine.audit(path))) == golden("paper-seed5")


def test_compatibility_names_the_first_difference_of_each_run():
    from conftest import paper_run_path
    first, second = schema.load(paper_run_path(1)), schema.load(paper_run_path(2))
    assert engine.compatibility([first, second]) == []
    short = dict(second, snapshots=second["snapshots"][:5], candidates=second["candidates"][:5])
    other_task = dict(second, id="other", task=dict(second["task"], name="Other"))
    assert engine.compatibility([first, short, other_task], names=["a", "b", "c"]) == [
        "b: number of rounds is 5, where a has 11", "c: task is Other, where a has GSM8K"]
    envs = {k: dict(v) for k, v in second["environments"].items()}
    envs["E2"]["fingerprint"] = "something else"
    assert engine.compatibility([first, dict(second, environments=envs)], names=["a", "b"]) == [
        "b: fingerprint of E2 is something else, where a has " + first["environments"]["E2"]["fingerprint"]]
    assert engine.compatibility([first, first], names=["a", "b"]) == ["b: run id gsm8k-qwen2.5-1.5b-seed1 is also the id of a"]
