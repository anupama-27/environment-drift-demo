from __future__ import annotations

import copy
import json
import os

import pytest

from conftest import make_legacy_run, paper_run_path, small_run
from driftaudit import __version__, schema
from driftaudit.envs import Environment, paper_environments
from driftaudit.errors import RunLogError


def skeleton(**overrides):
    args = dict(id="r1", seed=3, task={"name": "toy", "n_items": 4}, model={"id": "m"},
                environments=paper_environments("m"), schedule={0: "E1", 2: "E4"})
    args.update(overrides)
    return schema.new_run(**args)


def filled():
    """A small valid run with two rounds."""
    return small_run({"p0": {"E1": [1, 0, 0, 0]}, "p1": {"E1": [1, 1, 0, 0]}, "p2": {"E1": [0, 1, 0, 1]}},
                     schedule={0: "E1"}, snapshots=["p0", "p1"],
                     candidates=[{"id": "C1", "round": 0, "prompt": "p1", "parent": "p0", "accepted": True},
                                 {"id": "C2", "round": 1, "prompt": "p2", "parent": "p1", "accepted": False}],
                     n_items=4)


# Labels

def test_labels_round_trip_as_bitstrings():
    assert schema.encode_labels([1, 0, 0, 1]) == "1001"
    assert schema.decode_labels("1001") == [1, 0, 0, 1]
    assert schema.encode_labels([True, False]) == "10"
    assert schema.encode_labels("0110") == "0110"
    assert schema.encode_labels([]) == ""


def test_encode_labels_rejects_anything_but_zero_and_one():
    for bad in ([1, 2, 0], "01x1", [0.5], ["1", "0"], [None]):
        with pytest.raises(RunLogError, match="0 and 1"):
            schema.encode_labels(bad)


def test_prompt_id_is_the_toolkit_hash(legacy_runs):
    for run in legacy_runs.values():
        for h, text in run["prompts"].items():
            assert schema.prompt_id(text) == h
    assert len(schema.prompt_id("x")) == 12


# Legacy upgrade

def test_legacy_files_are_recognised(legacy_runs, paper_runs):
    assert schema.is_legacy(legacy_runs[1])
    assert not schema.is_legacy(paper_runs[1])
    assert not schema.is_legacy({"correct": {}})
    assert not schema.is_legacy([1, 2])


def test_upgrade_fills_in_what_the_v1_format_names(legacy_runs):
    old = legacy_runs[1]
    run = schema.upgrade_legacy(old)
    assert run["schema"] == schema.SCHEMA == "driftaudit.run/v1"
    assert run["id"] == "gsm8k-qwen2.5-1.5b-seed1"
    assert run["tool"] == {"name": "driftaudit", "version": __version__}
    assert run["source"] == "measured"
    assert run["seed"] == 1
    assert run["task"] == {"name": "GSM8K", "split": "test", "n_items": 200, "n_dev": 200,
                           "dataset": "openai/gsm8k (main)", "revision": old["config"]["dataset_revision"],
                           "items": "gsm8k/eval200"}
    assert run["model"] == {"id": "Qwen/Qwen2.5-1.5B-Instruct", "revision": old["config"]["model_revision"],
                            "backend": "hf"}
    assert run["schedule"] == {"0": "E1", "4": "E2", "8": "E4"}
    assert run["cost"] == {"n_dev": 200, "proposal_calls": 1}
    assert run["meta"]["config"] == old["config"]
    assert run["prompts"] == old["prompts"]
    assert schema.validate(run) == []


def test_upgrade_uses_the_paper_environments(legacy_runs):
    run = schema.upgrade_legacy(legacy_runs[2])
    expected = {k: e.to_dict() for k, e in paper_environments("Qwen/Qwen2.5-1.5B-Instruct").items()}
    assert run["environments"] == expected
    assert [e["name"] for e in run["environments"].values()] == ["Unchanged", "Decoding", "Extraction", "Combined"]


def test_upgrade_turns_correct_lists_into_label_strings(legacy_runs):
    old = legacy_runs[3]
    run = schema.upgrade_legacy(old)
    assert set(run["labels"]) == set(old["correct"])
    for h, per_env in old["correct"].items():
        for env, passes in per_env.items():
            for tag, values in passes.items():
                assert run["labels"][h][env][tag] == "".join(str(v) for v in values)


def test_upgrade_records_what_the_loop_compared_against(legacy_runs):
    # The toolkit's gate scored candidate and incumbent in the same pass under the round's
    # environment, so its recorded wins and losses are exactly that comparison.
    for old in legacy_runs.values():
        run = schema.upgrade_legacy(old)
        for before, after in zip(old["candidates"], run["candidates"]):
            assert after["reference"] == {"prompt": before["parent"], "env": before["env"], "pass": "current"}
            assert {k: after[k] for k in before} == before


def test_upgrade_ids_follow_the_seed(legacy_runs):
    assert [schema.upgrade_legacy(legacy_runs[s])["id"] for s in (1, 5)] == \
        ["gsm8k-qwen2.5-1.5b-seed1", "gsm8k-qwen2.5-1.5b-seed5"]


def test_upgrade_of_a_mock_run_is_tagged_synthetic_and_gets_its_own_id():
    run = schema.upgrade_legacy(make_legacy_run(seed=7))
    assert run["source"] == "synthetic"
    assert run["id"] == "gsm8k-qwen2.5-1.5b-instruct-mock-seed7"


def test_upgrade_of_another_model_derives_the_id_from_its_name():
    old = make_legacy_run(seed=2)
    old["config"].update(model="Qwen/Qwen2.5-0.5B-Instruct", backend="hf")
    assert schema.upgrade_legacy(old)["id"] == "gsm8k-qwen2.5-0.5b-instruct-seed2"


def test_upgrade_leaves_the_legacy_object_alone(legacy_runs):
    old = legacy_runs[4]
    before = json.dumps(old, sort_keys=True)
    schema.upgrade_legacy(old)
    assert json.dumps(old, sort_keys=True) == before


def test_upgrade_says_which_legacy_field_is_missing():
    old = make_legacy_run(seed=1)
    del old["config"]["n_eval"]
    with pytest.raises(RunLogError, match="n_eval"):
        schema.upgrade_legacy(old)


# load

def test_load_reads_a_legacy_file_from_disk(legacy_runs):
    run = schema.load(paper_run_path(5))
    assert run["id"] == "gsm8k-qwen2.5-1.5b-seed5"
    assert run == schema.load(legacy_runs[5])


def test_load_accepts_a_path_object(tmp_path):
    path = tmp_path / "run.json"
    schema.save(filled(), path)
    assert schema.load(path) == schema.load(str(path))


def test_load_turns_label_arrays_into_strings():
    run = skeleton()
    run["prompts"]["p0"] = "text"
    run["labels"] = {"p0": {"E1": {"current": [1, 0, 1, 1], "rerun": "1011"}}}
    loaded = schema.load(run)
    assert loaded["labels"]["p0"]["E1"] == {"current": "1011", "rerun": "1011"}
    assert run["labels"]["p0"]["E1"]["current"] == [1, 0, 1, 1]      # the argument is not modified


def test_load_writes_schedule_rounds_as_strings():
    run = skeleton()
    run["schedule"] = {0: "E1", 2: "E4"}
    assert schema.load(run)["schedule"] == {"0": "E1", "2": "E4"}


def test_load_is_idempotent(paper_runs):
    once = paper_runs[1]
    assert schema.load(once) == once


def test_load_reports_a_missing_file(tmp_path):
    with pytest.raises(RunLogError, match="no such file"):
        schema.load(str(tmp_path / "absent.json"))


def test_load_reports_text_that_is_not_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RunLogError, match="not valid JSON"):
        schema.load(str(path))


def test_load_reports_json_that_is_not_a_run_log(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(RunLogError, match="schema"):
        schema.load(str(path))
    with pytest.raises(RunLogError, match="JSON object"):
        schema.load([1, 2, 3])


def test_load_names_a_newer_format():
    run = skeleton()
    run["schema"] = "driftaudit.run/v2"
    with pytest.raises(RunLogError, match="driftaudit.run/v2"):
        schema.load(run)


def test_load_error_lists_the_problems_and_keeps_them():
    run = filled()
    run["labels"]["p0"]["E1"]["current"] = "10"
    run["schedule"]["3"] = "E9"
    with pytest.raises(RunLogError) as err:
        schema.load(run)
    assert "expected 4" in str(err.value) and "E9" in str(err.value)
    assert len(err.value.problems) == 2


# validate

def test_a_new_run_is_valid_and_empty():
    run = skeleton()
    assert schema.validate(run) == []
    assert run["schema"] == schema.SCHEMA
    assert run["tool"] == {"name": "driftaudit", "version": __version__}
    assert run["created"].endswith("Z") and len(run["created"]) == 20
    assert (run["prompts"], run["snapshots"], run["candidates"], run["labels"]) == ({}, [], [], {})
    assert run["source"] == "measured"
    assert run["schedule"] == {"0": "E1", "2": "E4"}
    assert run["environments"]["E1"] == paper_environments("m")["E1"].to_dict()
    assert run["cost"] == {} and run["meta"] == {}


def test_new_run_takes_environments_as_objects_dicts_or_a_list():
    a = Environment.make(id="A", model="m")
    b = Environment.make(id="B", model="m", temperature=0.2)
    by_list = skeleton(environments=[a, b], schedule={0: "A"})
    by_dict = skeleton(environments={"A": a.to_dict(), "B": b}, schedule={0: "A"})
    assert by_list["environments"] == by_dict["environments"] == {"A": a.to_dict(), "B": b.to_dict()}


def test_new_run_refuses_a_schedule_that_names_an_unknown_environment():
    with pytest.raises(RunLogError, match="E9"):
        skeleton(schedule={0: "E9"})


def test_new_run_keeps_source_cost_and_meta():
    run = skeleton(source="synthetic", cost={"n_dev": 5}, meta={"note": "x"})
    assert (run["source"], run["cost"], run["meta"]) == ("synthetic", {"n_dev": 5}, {"note": "x"})


def problems_after(change):
    run = copy.deepcopy(filled())
    change(run)
    return schema.validate(run)


def expect_problem(change, text):
    problems = problems_after(change)
    assert any(text in p for p in problems), problems


def test_validate_passes_the_paper_runs(paper_runs):
    for run in paper_runs.values():
        assert schema.validate(run) == []


def test_validate_accepts_a_legacy_file_as_it_would_load(legacy_runs):
    assert schema.validate(legacy_runs[1]) == []


def test_validate_names_each_kind_of_problem():
    expect_problem(lambda r: r.pop("schema"), "schema")
    expect_problem(lambda r: r.update(id=""), "id")
    expect_problem(lambda r: r.update(source="guessed"), "source")
    expect_problem(lambda r: r["task"].pop("n_items"), "task.n_items")
    expect_problem(lambda r: r["task"].update(n_items=True), "task.n_items")
    expect_problem(lambda r: r.update(environments={}), "environments")
    expect_problem(lambda r: r["environments"]["E1"].pop("fingerprint"), "environments.E1.fingerprint")
    expect_problem(lambda r: r.update(schedule={}), "schedule")
    expect_problem(lambda r: r["schedule"].update({"x": "E1"}), "schedule round 'x'")
    expect_problem(lambda r: r["schedule"].update({"2": "E9"}), "E9")
    expect_problem(lambda r: r["snapshots"][1].update(round=5), "snapshots[1]")
    expect_problem(lambda r: r["snapshots"][0].update(prompt="zz"), "zz")
    expect_problem(lambda r: r["candidates"][0].update(prompt="zz"), "zz")
    expect_problem(lambda r: r["candidates"][1].update(round=7), "round 7")
    expect_problem(lambda r: r["candidates"][1].update(id="C1"), "more than once")
    expect_problem(lambda r: r["candidates"][0].update(accepted="yes"), "accepted")
    expect_problem(lambda r: r["candidates"][0].update(reference={"prompt": "p0", "env": "E1", "pass": "later"}), "pass")
    expect_problem(lambda r: r["candidates"][0].update(reference={"prompt": "p0"}), "reference")
    expect_problem(lambda r: r["labels"].update(zz={}), "zz")
    expect_problem(lambda r: r["labels"]["p0"].update(E9={}), "E9")
    expect_problem(lambda r: r["labels"]["p0"]["E1"].update(extra="1010"), "extra")
    expect_problem(lambda r: r["labels"]["p0"]["E1"].update(current="101"), "expected 4")
    expect_problem(lambda r: r["labels"]["p0"]["E1"].update(current="10a1"), "0 and 1")
    expect_problem(lambda r: r["cost"].update(n_dev=-1), "cost.n_dev")


def test_validate_wants_candidates_in_round_order():
    def swap(run):
        run["candidates"].reverse()
    expect_problem(swap, "order")


def test_validate_of_something_that_is_not_an_object():
    assert schema.validate("nope") == ["a run log is a JSON object"]


# labels accessor

def test_labels_returns_none_for_anything_absent():
    run = filled()
    assert schema.labels(run, "p0", "E1") == "1000"
    assert schema.labels(run, "p0", "E1", "rerun") == "1000"
    assert schema.labels(run, "p0", "E4") is None
    assert schema.labels(run, "zz", "E1") is None
    assert schema.labels(run, "p0", "E1", "later") is None


# save

def test_save_then_load_gives_the_same_run(tmp_path, paper_runs):
    path = str(tmp_path / "seed2.json")
    schema.save(paper_runs[2], path)
    assert schema.load(path) == paper_runs[2]


def test_save_writes_compact_json_with_label_strings(tmp_path):
    path = tmp_path / "run.json"
    run = filled()
    run["labels"]["p0"]["E1"]["current"] = [1, 0, 0, 0]
    schema.save(run, str(path))
    text = path.read_text(encoding="utf-8")
    assert '"id":"small"' in text and "\n" not in text.rstrip("\n")
    assert json.loads(text)["labels"]["p0"]["E1"]["current"] == "1000"


def test_save_replaces_an_existing_file_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "run.json"
    path.write_text("old", encoding="utf-8")
    schema.save(filled(), str(path))
    assert json.loads(path.read_text(encoding="utf-8"))["id"] == "small"
    assert os.listdir(tmp_path) == ["run.json"]


def test_save_refuses_an_invalid_run_and_keeps_the_old_file(tmp_path):
    path = tmp_path / "run.json"
    path.write_text("old", encoding="utf-8")
    run = filled()
    run["labels"]["p0"]["E1"]["current"] = "1"
    with pytest.raises(RunLogError):
        schema.save(run, str(path))
    assert path.read_text(encoding="utf-8") == "old"
    assert os.listdir(tmp_path) == ["run.json"]


def test_save_keeps_non_ascii_prompts_readable(tmp_path):
    path = tmp_path / "run.json"
    run = filled()
    run["prompts"]["p0"] = "Réponds en français: 数学"
    schema.save(run, str(path))
    assert "Réponds en français: 数学" in path.read_text(encoding="utf-8")
    assert schema.load(str(path))["prompts"]["p0"] == "Réponds en français: 数学"


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_load_refuses_numbers_json_does_not_allow(tmp_path, text):
    path = tmp_path / "nan.json"
    run = filled()
    run["meta"] = {"x": 1}
    path.write_text(json.dumps(run).replace('{"x": 1}', '{"x": ' + text + "}"), encoding="utf-8")
    with pytest.raises(RunLogError, match="the run log > meta > x is .*which JSON does not allow"):
        schema.load(str(path))
    with pytest.raises(RunLogError, match="JSON does not allow"):
        schema.load(dict(run, meta={"x": float("nan")}))


def test_load_refuses_deep_nesting_without_a_traceback(tmp_path):
    path = tmp_path / "deep.json"
    path.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    with pytest.raises(RunLogError, match="nested too deeply"):
        schema.load(str(path))
    deep = filled()
    deep["meta"] = {}
    node = deep["meta"]
    for _ in range(100):
        node["a"] = {}
        node = node["a"]
    with pytest.raises(RunLogError, match="nested more than 64 levels"):
        schema.load(deep)
