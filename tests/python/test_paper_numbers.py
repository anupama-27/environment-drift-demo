"""The numbers the paper reports, recomputed by the engine from the five saved runs.

Values are compared the way the paper prints them: percentages to one decimal, percentage
points to two, p-values to three. The second half checks the engine against the files the
toolkit wrote from the same runs (results/table6_decisions.csv and replay/*.json).
"""
from __future__ import annotations

import csv
import json
import os

import pytest

from conftest import ROOT, SEEDS, TOOLKIT
from driftaudit import engine, stats


@pytest.fixture(scope="module")
def study(paper_runs):
    return engine.study([paper_runs[s] for s in SEEDS])


@pytest.fixture(scope="module")
def audits(paper_runs):
    return {s: engine.audit(paper_runs[s]) for s in SEEDS}


def pct(x):
    return f"{100 * x:.1f}"


def interval(cell):
    return f"{cell['mean']:+.2f} [{cell['lo']:+.2f}, {cell['hi']:+.2f}]"


# Table 3: false accepts/accepts, false rejects, final accuracy mean and sd, calls, reruns.
TABLE_3 = {
    "frozen": (13, 34, 0, "70.8", "2.0", 4411, 0),
    "stored_incumbent": (0, 8, 8, "71.2", "2.0", 4411, 0),
    "per_batch": (3, 13, 11, "69.7", "2.2", 6611, 11),
    "env_triggered": (2, 16, 2, "72.5", "2.2", 4811, 2),
}


def test_the_study_covers_five_runs_and_55_decisions(study):
    assert study["n_runs"] == 5 and study["n_decisions"] == 55
    assert [r["seed"] for r in study["runs"]] == [1, 2, 3, 4, 5]
    assert [r["id"] for r in study["runs"]] == [f"gsm8k-qwen2.5-1.5b-seed{s}" for s in SEEDS]


@pytest.mark.parametrize("policy", list(TABLE_3))
def test_table_3_refresh_policies(study, policy):
    false_accepts, accepted, false_rejects, acc, sd, calls, reruns = TABLE_3[policy]
    row = study["policies"][policy]
    assert (row["false_accepts"], row["accepted"], row["false_rejects"]) == (false_accepts, accepted, false_rejects)
    assert (pct(row["final_acc"]["mean"]), pct(row["final_acc"]["sd"])) == (acc, sd)
    assert (row["total_calls"]["mean"], row["total_calls"]["sd"]) == (calls, 0.0)
    assert (row["refreshes"]["mean"], row["refreshes"]["sd"]) == (reruns, 0.0)
    assert row["false_accept_rate_pooled"] == false_accepts / accepted


def test_table_6_pooled_and_per_seed_false_accept_rates(study):
    expected = {"frozen": ("38.2", "35.7", "22.6", ["4/7", "3/7", "2/7", "0/5", "4/8"]),
                "per_batch": ("23.1", "20.0", "20.9", ["0/2", "0/1", "1/4", "1/4", "1/2"]),
                "env_triggered": ("12.5", "13.3", "18.3", ["0/4", "0/1", "1/3", "0/5", "1/3"])}
    for policy, (pooled, seed_mean, seed_sd, per_seed) in expected.items():
        row = study["policies"][policy]
        rates = [r["false_accepts"] / r["accepted"] for r in row["per_run"]]
        assert pct(row["false_accept_rate_pooled"]) == pooled
        assert (pct(stats.mean(rates)), pct(stats.sd(rates))) == (seed_mean, seed_sd)
        assert [f"{r['false_accepts']}/{r['accepted']}" for r in row["per_run"]] == per_seed


def test_fisher_tests_against_environment_triggered(study):
    tests = {t["b"]: t for t in study["policy_tests"]}
    assert all(t["a"] == "env_triggered" and t["errors_a"] == 4 and t["n"] == 55 for t in tests.values())
    assert {b: (tests[b]["errors_b"], f"{tests[b]['fisher_p']:.3f}") for b in ("frozen", "per_batch", "stored_incumbent")} \
        == {"frozen": (13, "0.033"), "per_batch": (14, "0.019"), "stored_incumbent": (8, "0.360")}


def test_figure_4_drift_inflation_at_reference_age_3(study):
    probe = study["probe"]
    assert (probe["age"], probe["stored_env"]) == (3, "E1")
    assert {env: interval(cell) for env, cell in probe["by_env"].items()} == {
        "E1": "-0.12 [-0.64, +0.39]", "E2": "-0.59 [-2.61, +1.43]",
        "E3": "+1.31 [+0.65, +1.98]", "E4": "+1.54 [+0.04, +3.04]"}
    assert {env: cell["n_positive"] for env, cell in probe["by_env"].items()} == {"E1": 2, "E2": 2, "E3": 5, "E4": 4}
    assert {env: cell["same_sign"] for env, cell in probe["by_env"].items()} == {"E1": 3, "E2": 3, "E3": 5, "E4": 4}
    # Table 4 prints the same cells as mean and sd.
    assert {env: f"{cell['mean']:.2f} ± {cell['sd']:.2f}" for env, cell in probe["by_env"].items()} == {
        "E1": "-0.12 ± 0.41", "E2": "-0.59 ± 1.63", "E3": "1.31 ± 0.53", "E4": "1.54 ± 1.21"}


def test_frozen_false_accept_causes(study, audits):
    assert study["policies"]["frozen"]["causes"] == {"stale": 6, "anyway": 3, "no_drift": 4}
    assert audits[5]["policies"]["frozen"]["causes"] == {"stale": 3, "anyway": 0, "no_drift": 1}


def test_scorer_flips_between_the_strict_and_lenient_extractor(study):
    first = study["scorer_flips"][0]
    assert first == {"from_env": "E1", "to_env": "E3", "prompts": 57, "items": 11400,
                     "wrong_to_right": 638, "right_to_wrong": 0}
    assert [(f["from_env"], f["to_env"]) for f in study["scorer_flips"]] == [("E1", "E3"), ("E2", "E4")]
    assert study["scorer_flips"][1]["right_to_wrong"] == 0


def test_verdicts_that_change_with_the_extractor(study):
    assert study["verdict_flips"] == {"n": 55, "flipped": 18}


# Table 2: every decision of the three policies on seed 1, as (wins, losses, accepted).
TABLE_2 = {
    "frozen": [(25, 43, False), (26, 23, True), (14, 59, False), (22, 19, True), (22, 26, False), (25, 19, True),
               (25, 19, True), (7, 88, False), (27, 17, True), (24, 18, True), (24, 22, True)],
    "per_batch": [(27, 42, False), (27, 21, True), (14, 62, False), (25, 25, False), (28, 23, True), (14, 19, False),
                  (14, 19, False), (12, 104, False), (16, 19, False), (15, 22, False), (13, 24, False)],
    "env_triggered": [(25, 43, False), (26, 23, True), (14, 62, False), (25, 25, False), (28, 23, True),
                      (17, 7, True), (0, 0, False), (10, 97, False), (20, 18, True), (13, 17, False), (14, 22, False)],
}


@pytest.mark.parametrize("policy", list(TABLE_2))
def test_table_2_decisions_for_seed_1(audits, policy):
    decisions = audits[1]["policies"][policy]["decisions"]
    assert [(d["wins"], d["losses"], d["accepted"]) for d in decisions] == TABLE_2[policy]
    assert [d["env"] for d in decisions] == ["E1"] * 4 + ["E2"] * 4 + ["E4"] * 3


def test_table_2_summary_for_seed_1(audits):
    blocks = audits[1]["policies"]
    assert {p: (pct(blocks[p]["final_acc"]), blocks[p]["false_accepts"], blocks[p]["accepted"])
            for p in ("frozen", "per_batch", "env_triggered")} == \
        {"frozen": ("69.0", 4, 7), "per_batch": ("67.0", 0, 2), "env_triggered": ("73.0", 0, 4)}


# Table 7: pairs, drift inflation interval and false accepts/promotions by reference age.
TABLE_7 = {
    ("E1", 0): (55, "[-0.34, +0.21]", "0/18"), ("E4", 0): (55, "[+0.22, +2.07]", "18/27"),
    ("E1", 1): (50, "[-0.32, +0.26]", "5/20"), ("E4", 1): (50, "[+0.30, +2.06]", "16/25"),
    ("E1", 3): (40, "[-0.64, +0.39]", "7/17"), ("E4", 3): (40, "[+0.04, +3.04]", "10/18"),
    ("E1", 5): (30, "[-1.10, +0.53]", "8/15"), ("E4", 5): (30, "[+0.90, +4.14]", "10/16"),
    ("E1", 10): (5, "[-1.59, +0.79]", "3/4"), ("E4", 10): (5, "[+1.92, +5.08]", "4/5"),
}


def test_table_7_effect_of_reference_age(study):
    age = study["age"]
    assert (age["stored_env"], age["ages"]) == ("E1", [0, 1, 3, 5, 10])
    found = {(env, row["age"]): (row["pairs"], f"[{row['lo']:+.2f}, {row['hi']:+.2f}]",
                                 f"{row['false_accepts']}/{row['promoted']}")
             for env, rows in age["by_env"].items() for row in rows}
    assert found == TABLE_7


def test_appendix_c_schedule_ablations(paper_runs):
    def frozen_inflation(schedule):
        return [100 * engine.simulate(paper_runs[s], "frozen", schedule=schedule)["inflation"] for s in SEEDS]

    full = frozen_inflation(None)
    expected = {"no extraction": ({0: "E1", 4: "E2", 8: "E2"}, "0.59 ± 0.25", "0.006", 5),
                "no decoding": ({0: "E1", 4: "E1", 8: "E3"}, "0.89 ± 1.19", "0.169", 4)}
    for schedule, drop, p, seeds_with_a_drop in expected.values():
        d = [a - b for a, b in zip(full, frozen_inflation(schedule))]
        assert f"{stats.mean(d):.2f} ± {stats.sd(d):.2f}" == drop
        assert f"{stats.t_test_p(d):.3f}" == p
        assert sum(x > 0 for x in d) == seeds_with_a_drop


def test_environment_triggered_against_the_best_prompt_in_each_pool(audits):
    assert [pct(audits[s]["policies"]["env_triggered"]["final_acc"]) for s in SEEDS] == \
        ["73.0", "69.0", "73.0", "72.5", "75.0"]


# Against the files the toolkit wrote.

TOOLKIT_POLICY = {"P1": "frozen", "P2": "per_batch", "P3": "env_triggered"}


def test_every_decision_matches_the_toolkit_decision_table(audits):
    with open(os.path.join(TOOLKIT, "results", "table6_decisions.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3 * 55
    for row in rows:
        audit = audits[int(row["seed"])]
        index = [r["candidate_id"] for r in audit["rounds"]].index(row["cid"])
        d = audit["policies"][TOOLKIT_POLICY[row["policy"]]]["decisions"][index]
        assert (d["round"], d["env"], d["ref_env"], d["wins"], d["losses"]) == \
            (int(row["round"]), row["env"], row["ref_env"], int(row["wins"]), int(row["losses"]))
        assert (str(d["accepted"]), str(d["false_accept"]), str(d["false_reject"]), d["outcome"]) == \
            (row["accepted"], row["false_accept"], row["false_reject"], row["outcome"])
        assert (d["inc_acc"], d["cand_acc"], d["delta_pp"]) == \
            (float(row["inc_acc"]), float(row["cand_acc"]), float(row["delta_pp"]))


def replay(name):
    with open(os.path.join(ROOT, "replay", name), encoding="utf-8") as f:
        return json.load(f)


def test_study_matches_the_replay_summary_the_case_study_reads(study):
    saved = replay("all_seeds.json")
    for legacy, policy in TOOLKIT_POLICY.items():
        ours, theirs = study["policies"][policy], saved["policies"][legacy]
        assert (ours["accepted"], ours["false_accepts"], ours["false_rejects"]) == \
            (theirs["accepted"], theirs["false_accepts"], theirs["false_rejects"])
        assert [round(ours["final_acc"]["mean"], 4), round(ours["final_acc"]["sd"], 4)] == theirs["final_acc"]
        assert [ours["total_calls"]["mean"], ours["total_calls"]["sd"]] == theirs["logical_calls"]
        assert [ours["refreshes"]["mean"], ours["refreshes"]["sd"]] == theirs["refreshes"]
        for row in ours["per_run"]:
            seed = saved["per_seed"][str(row["seed"])][legacy]
            assert (row["accepted"], row["false_accepts"], row["false_rejects"], row["total_calls"],
                    round(row["final_acc"], 4)) == \
                (seed["accepted"], seed["false_accepts"], seed["false_rejects"], seed["logical_calls"], seed["final_acc"])
    for env, theirs in saved["inflation"].items():
        ours = study["probe"]["by_env"][env]
        assert [round(ours[k], 4) for k in ("mean", "lo", "hi")] == [theirs[k] for k in ("mean", "lo", "hi")]
        assert [round(x, 4) for x in ours["per_run"]] == theirs["per_seed"]
        assert ours["same_sign"] == theirs["seeds_same_sign"]
    causes = saved["false_promotion_causes"]
    assert study["policies"]["frozen"]["causes"] == {"stale": causes["stale"], "anyway": causes["anyway"],
                                                      "no_drift": causes["before_change"]}
    assert study["verdict_flips"] == {k: saved["verdict_flips"][k] for k in ("n", "flipped")}
    assert study["scorer_flips"][0]["wrong_to_right"] == saved["answer_flips"]["wrong_to_right"]
    assert study["scorer_flips"][0]["items"] == saved["answer_flips"]["items"]


@pytest.mark.parametrize("seed", SEEDS)
def test_frozen_decisions_match_the_replay_file_of_each_seed(audits, seed):
    saved = replay(f"seed{seed}.json")
    decisions = audits[seed]["policies"]["frozen"]["decisions"]
    causes = {"before_change": "no_drift", "stale": "stale", "anyway": "anyway", None: None}
    assert len(decisions) == len(saved["rounds"]) == 11
    for d, r in zip(decisions, saved["rounds"]):
        assert (d["round"], d["env"], d["wins"], d["losses"], d["rerun_wins"], d["rerun_losses"]) == \
            (r["round"], r["env"], r["wins"], r["losses"], r["fresh_wins"], r["fresh_losses"])
        assert (d["accepted"], d["false_accept"], d["false_reject"], d["cause"]) == \
            (r["accepted"], r["false_accept"], r["false_reject"], causes[r["cause"]])
        assert (round(100 * d["inflation"], 4), round(d["inc_acc"], 4), round(d["cand_acc"], 4), round(d["delta_pp"], 4)) == \
            (r["inflation_pp"], r["incumbent_acc"], r["candidate_acc"], r["delta_pp"])
    assert [d["round"] for d in decisions if d["cause"] in ("stale", "anyway")] == saved["meta"]["false_promotion_rounds"]
    for legacy, policy in TOOLKIT_POLICY.items():
        ours, theirs = audits[seed]["policies"][policy], saved["policies"][legacy]
        assert [(d["accepted"], d["wins"], d["losses"], d["ref_pass"] == "rerun") for d in ours["decisions"]] == \
            [(d["accepted"], d["wins"], d["losses"], d["reference_refreshed"]) for d in theirs["decisions"]]
        assert (ours["accepted"], ours["false_accepts"], ours["false_rejects"], ours["refreshes"], ours["total_calls"],
                round(ours["final_acc"], 4)) == \
            (theirs["accepted"], theirs["false_accepts"], theirs["false_rejects"], theirs["refreshes"],
             theirs["logical_calls"], theirs["final_acc"])
