"""The built-in loop: schedule parsing, the run it produces on the mock backend, and resuming."""
from __future__ import annotations

import importlib
import json
import sys

import pytest

from app_fixtures import SMALL_SCHEDULE, mock_loop, small_loop  # noqa: F401
from conftest import TOOLKIT
from driftaudit import engine, schema
from driftaudit.backends import make_backend
from driftaudit.backends.cache import generation_key
from driftaudit.errors import DriftAuditError
from driftaudit.loop import (DEFAULT_SCHEDULE, build_environments, default_schedule, gold_kind, item_seed, parse_candidate,
                             parse_schedule, read_outputs, run_loop, write_outputs)
from driftaudit.scoring import get_scorer, score_outputs
from driftaudit.tasks import Task, load_task


def test_default_schedule_gives_the_papers_four_environments():
    schedule = parse_schedule(DEFAULT_SCHEDULE)
    assert schedule.starts == {0: "E1", 4: "E2", 8: "E4"}
    assert [(e.id, e.name, e.decoding, e.scorer) for e in schedule.environments.values()] == [
        ("E1", "Unchanged", "greedy-0.0", "strict"), ("E2", "Decoding", "sample-0.2", "strict"),
        ("E3", "Extraction", "greedy-0.0", "lenient"), ("E4", "Combined", "sample-0.2", "lenient")]


def test_schedule_accepts_the_papers_scorer_names_and_spaces():
    schedule = parse_schedule(" 0 : greedy / v1 , 3:sample@0.20/v2 ")
    assert schedule.starts == {0: "E1", 3: "E4"}
    assert schedule.environments["E4"].scorer == "lenient"


def test_schedule_with_three_decodings_says_which_one_each_environment_is():
    schedule = parse_schedule("0:greedy/strict,2:sample@0.2/strict,4:sample@0.7/strict")
    assert [e.name for e in schedule.environments.values()] == [
        "Unchanged", "Decoding (sample@0.2)", "Decoding (sample@0.7)"]


@pytest.mark.parametrize("spec, hint", [
    ("", "round 0"), ("4:greedy/strict", "round 0"), ("0:greedy", "ROUND:DECODING/SCORER"),
    ("0:warm/strict", "sample@T"), ("0:sample@0/strict", "above 0"), ("0:greedy/nope", "unknown scorer"),
    ("0:greedy/strict,0:greedy/lenient", "twice")])
def test_schedule_errors_say_what_to_write(spec, hint):
    with pytest.raises(DriftAuditError, match=hint):
        parse_schedule(spec)


def test_a_schedule_cannot_mix_numeric_and_exact_scorers():
    assert gold_kind(parse_schedule(DEFAULT_SCHEDULE)) == "number"
    assert gold_kind(parse_schedule("0:greedy/exact,2:greedy/exact-normalized")) == "text"
    with pytest.raises(DriftAuditError, match="cannot mix"):
        gold_kind(parse_schedule("0:greedy/strict,2:greedy/exact"))


def test_cache_keys_and_seeds_are_the_toolkits(toolkit, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    model = importlib.import_module("drift.model")
    prompt = toolkit.config.INITIAL_PROMPT
    for env in toolkit.envs.ENVS.values():
        for tag in ("current", "rerun"):
            ours = generation_key(False, toolkit.config.MODEL_ID, prompt, "test-7", env.decoding_key, 3, tag,
                                  toolkit.config.MAX_NEW_TOKENS)
            assert ours == model.generation_key(prompt, "test-7", env, 3, tag)
    assert item_seed(3, "rerun", "test-7") == model.item_seed(3, "rerun", "test-7")


def test_run_loads_as_v1_and_every_policy_can_be_replayed(mock_loop):
    run, _ = mock_loop
    assert schema.validate(run) == []
    assert run["source"] == "synthetic" and "created" not in run
    assert run["schedule"] == {"0": "E1", "2": "E2", "4": "E4"}
    assert [s["round"] for s in run["snapshots"]] == list(range(6))
    audit = engine.audit(run)
    assert audit["completeness"]["full_bank"]
    assert all(audit["policies"][p]["available"] for p in engine.POLICIES)
    # The loop compares with the incumbent in the same pass, which is what it records.
    for cand, snap in zip(run["candidates"], run["snapshots"]):
        assert cand["reference"] == {"prompt": snap["prompt"], "env": snap["env"], "pass": "current"}
    recorded = audit["policies"]["as_run"]["decisions"]
    assert [d["accepted"] for d in recorded] == [c["accepted"] for c in run["candidates"]]
    assert [(d["wins"], d["losses"]) for d in recorded] == [(c["wins"], c["losses"]) for c in run["candidates"]]


def test_labels_cover_every_prompt_environment_and_pass(mock_loop):
    run, _ = mock_loop
    for prompt in run["prompts"]:
        for env in ("E1", "E2", "E3", "E4"):
            for tag in ("current", "rerun"):
                assert len(schema.labels(run, prompt, env, tag)) == 40


def test_outputs_reproduce_the_labels(mock_loop, tmp_path):
    run, outputs = mock_loop
    assert set(outputs[0]) == {"prompt", "decoding", "pass", "item", "text"}
    assert len(outputs) == len(run["prompts"]) * 2 * 2 * 40
    path = write_outputs(tmp_path / "o.jsonl.gz", outputs)
    texts = read_outputs(path)
    gold = run["meta"]["gold"]
    for env_id, env in run["environments"].items():
        for prompt in run["prompts"]:
            saved = texts[(prompt, env["decoding"], "rerun")]
            assert schema.encode_labels(score_outputs(saved, gold, env["scorer"])) == schema.labels(run, prompt, env_id, "rerun")


def test_strict_and_lenient_disagree_on_the_same_text(mock_loop):
    run, _ = mock_loop
    flips = sum(a != b for p in run["prompts"]
                for a, b in zip(schema.labels(run, p, "E1"), schema.labels(run, p, "E3")))
    assert flips > 0
    # The lenient scorer only ever adds answers.
    assert all(not (a == "1" and b == "0") for p in run["prompts"]
               for a, b in zip(schema.labels(run, p, "E1"), schema.labels(run, p, "E3")))


def test_sampling_makes_stored_and_rerun_differ_but_greedy_repeats(mock_loop):
    run, _ = mock_loop
    first = next(iter(run["prompts"]))
    assert schema.labels(run, first, "E1") == schema.labels(run, first, "E1", "rerun")
    assert any(schema.labels(run, p, "E2") != schema.labels(run, p, "E2", "rerun") for p in run["prompts"])


def test_same_seed_gives_the_same_run_byte_for_byte(mock_loop, tmp_path):
    run, outputs = mock_loop
    again, outputs_again = small_loop()
    assert json.dumps(again, sort_keys=True) == json.dumps(run, sort_keys=True)
    a = write_outputs(tmp_path / "a.jsonl.gz", outputs).read_bytes()
    assert a == write_outputs(tmp_path / "b.jsonl.gz", outputs_again).read_bytes()
    other, _ = small_loop(seed=2)
    assert other["labels"] != run["labels"]


def test_second_run_with_the_same_cache_calls_the_model_for_nothing(tmp_path):
    cache = tmp_path / "cache.jsonl"
    first, _ = small_loop(rounds=3, cache_path=cache)
    assert first["meta"]["physical_calls"] > 0
    second, _ = small_loop(rounds=3, cache_path=cache)
    assert second["meta"]["physical_calls"] == 0
    assert second["labels"] == first["labels"] and second["candidates"] == first["candidates"]
    assert all(p["cached"] == "all" for p in second["meta"]["config"]["passes"])


def test_rerun_passes_are_sent_in_a_shuffled_order(mock_loop):
    run, _ = mock_loop
    passes = run["meta"]["config"]["passes"]
    stored = next(p for p in passes if p["tag"] == "current" and p["split"] == "eval" and p["order"])
    rerun = next(p for p in passes if p["tag"] == "rerun" and p["order"])
    assert stored["order"] == sorted(stored["order"])
    assert rerun["order"] != sorted(rerun["order"]) and sorted(rerun["order"]) == list(range(40))


def test_fingerprint_follows_the_model_and_the_scorer_version(monkeypatch):
    task = load_task("gsm8k", 2, 2)
    backend = make_backend("mock", items=task.dev + task.eval)
    schedule = parse_schedule(DEFAULT_SCHEDULE)
    before = build_environments(schedule, backend)["E1"].fingerprint
    assert before == "model=driftaudit-mock;decode=greedy-0.0;extract=strict@1;backend=mock;revision=2"
    monkeypatch.setattr(get_scorer("strict"), "version", "2")
    assert "extract=strict@2" in build_environments(schedule, backend)["E1"].fingerprint
    monkeypatch.setattr(backend, "describe", lambda: {"backend": "mock", "model": "other", "revision": None})
    assert build_environments(schedule, backend)["E3"].fingerprint == "model=other;decode=greedy-0.0;extract=lenient@1;backend=mock"


@pytest.mark.parametrize("rounds, starts", [
    (1, {0: "E1"}), (2, {0: "E1", 1: "E4"}), (3, {0: "E1", 1: "E2", 2: "E4"}), (4, {0: "E1", 1: "E2", 3: "E4"}),
    (6, {0: "E1", 2: "E2", 4: "E4"}), (11, {0: "E1", 4: "E2", 8: "E4"}), (20, {0: "E1", 7: "E2", 15: "E4"}),
])
def test_default_schedule_keeps_both_changes_inside_the_run(rounds, starts):
    assert parse_schedule(default_schedule(rounds)).starts == starts


def test_default_schedule_at_eleven_rounds_is_the_papers():
    assert default_schedule(11) == DEFAULT_SCHEDULE


def test_loop_without_a_schedule_scales_it_and_names_it_in_the_header():
    said = []
    run, _ = small_loop(rounds=4, n_dev=5, n_eval=6, schedule=None, progress=said.append)
    assert run["schedule"] == {"0": "E1", "1": "E2", "3": "E4"}
    assert said[0].endswith("schedule 0:greedy/strict,1:sample@0.2/strict,3:sample@0.2/lenient")


def test_schedule_entry_after_the_last_round_is_reported_not_refused():
    said = []
    run, _ = small_loop(rounds=2, n_dev=5, n_eval=6, schedule=DEFAULT_SCHEDULE, progress=said.append)
    assert run["schedule"] == {"0": "E1", "4": "E2", "8": "E4"}
    assert any("round 4" in line and "after the last round" in line for line in said)
    assert sum(line.startswith("round ") for line in said) == 2


def test_text_answers_run_with_the_exact_scorers(tmp_path):
    path = tmp_path / "capitals.jsonl"
    rows = [{"question": f"What is the capital of country {i}?", "answer": f"City {i}"} for i in range(16)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    schedule = parse_schedule("0:greedy/exact,2:greedy/exact-normalized")
    task = load_task(path, 6, 10, gold=gold_kind(schedule))
    run, outputs = run_loop(task, make_backend("mock", items=task.dev + task.eval), schedule=schedule, rounds=3)
    assert run["task"]["name"] == "capitals" and "items" not in run["task"]
    first = next(iter(run["prompts"]))
    assert "answer only" in run["prompts"][first]
    assert schema.labels(run, first, "E1").count("1") <= schema.labels(run, first, "E2").count("1")


def test_scorers_that_cannot_grade_the_task_are_refused():
    numeric = load_task("gsm8k", 2, 2)
    backend = make_backend("mock", items=numeric.dev + numeric.eval)
    with pytest.raises(DriftAuditError, match="exact-match scorer"):
        run_loop(numeric, backend, schedule="0:greedy/exact")
    text = Task(name="t", dev=[{"id": "a", "question": "q1", "gold": "x"}],
                eval=[{"id": "b", "question": "q2", "gold": "y"}], gold="text")
    with pytest.raises(DriftAuditError, match="text answers"):
        run_loop(text, make_backend("mock", items=text.dev + text.eval), schedule=DEFAULT_SCHEDULE)


def test_candidate_parsing_keeps_the_answer_format():
    line = "Put the final answer as a plain number in \\boxed{} on the last line."
    assert parse_candidate("<prompt>Think carefully about every single step.</prompt>", "old", line) == (
        "Think carefully about every single step. " + line, "format_line_added")
    assert parse_candidate("<prompt>Think carefully and use \\boxed{} at the end.</prompt>", "old", line)[1] == "ok"
    assert parse_candidate("Looks fine.", "old", line) == ("old", "fallback_unparsed")
    assert parse_candidate("<prompt>Think carefully about every single step.</prompt>", "old", "")[1] == "ok"


def test_outputs_file_that_is_something_else_is_refused(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"prompt": "p"}\n', encoding="utf-8")
    with pytest.raises(DriftAuditError, match="not an outputs file"):
        read_outputs(bad)
    with pytest.raises(DriftAuditError, match="no such file"):
        read_outputs(tmp_path / "missing.jsonl.gz")


def test_reading_outputs_stops_at_the_size_cap(tmp_path, monkeypatch):
    import gzip as gz
    from driftaudit import loop
    path = tmp_path / "bomb.outputs.jsonl.gz"
    path.write_bytes(gz.compress(b" " * 100000))
    monkeypatch.setattr(loop, "MAX_OUTPUTS_BYTES", 1000)
    with pytest.raises(DriftAuditError, match="more than 0 MB of outputs once decompressed"):
        loop.read_outputs(path)
