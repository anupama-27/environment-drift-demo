from __future__ import annotations

import pytest

from driftaudit.envs import Environment, env_at, paper_environments
from driftaudit.errors import DriftAuditError

MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def test_paper_fingerprints_are_the_toolkit_ones(toolkit):
    ours = paper_environments(toolkit.config.MODEL_ID)
    assert list(ours) == list(toolkit.envs.ENVS) == ["E1", "E2", "E3", "E4"]
    for env_id, legacy in toolkit.envs.ENVS.items():
        assert ours[env_id].fingerprint == legacy.fingerprint
        assert ours[env_id].decoding == legacy.decoding_key
        assert ours[env_id].scorer == legacy.extractor


def test_paper_environments_use_the_names_in_the_paper():
    envs = paper_environments(MODEL)
    assert [e.name for e in envs.values()] == ["Unchanged", "Decoding", "Extraction", "Combined"]
    assert [e.decoding for e in envs.values()] == ["greedy-0.0", "sample-0.2", "greedy-0.0", "sample-0.2"]
    assert [e.scorer for e in envs.values()] == ["v1", "v1", "v2", "v2"]
    assert envs["E1"].fingerprint == f"model={MODEL};decode=greedy-0.0;extract=v1"
    assert [e.id for e in envs.values()] == ["E1", "E2", "E3", "E4"]


def test_make_builds_the_decoding_key_from_the_temperature():
    assert Environment.make(temperature=0).decoding == "greedy-0.0"
    assert Environment.make(temperature=0.0).decoding == "greedy-0.0"
    assert Environment.make(temperature=0.2).decoding == "sample-0.2"
    assert Environment.make(temperature=1).decoding == "sample-1.0"


def test_make_fingerprint_names_model_decoding_and_scorer():
    env = Environment.make(id="A", name="Baseline", model="m", temperature=0.2, scorer="lenient")
    assert env.fingerprint == "model=m;decode=sample-0.2;extract=lenient@1"
    assert (env.id, env.name, env.scorer) == ("A", "Baseline", "lenient")


def test_a_scorer_id_and_the_scorer_itself_give_one_fingerprint():
    from driftaudit.recorder import ReferenceStore
    from driftaudit.scoring import get_scorer
    by_id, by_object = Environment.make(model="m", scorer="strict"), Environment.make(model="m", scorer=get_scorer("strict"))
    assert by_id.fingerprint == by_object.fingerprint == "model=m;decode=greedy-0.0;extract=strict@1"
    store = ReferenceStore()
    store.set("p", by_id, [1, 0])
    assert not store.stale(by_object)
    assert Environment.make(model="m", scorer="my-own").fingerprint == "model=m;decode=greedy-0.0;extract=my-own"


def test_make_fingerprint_carries_the_scorer_version_and_sorted_extras():
    env = Environment.make(model="m", scorer="strict", scorer_version="3", extra={"top_p": 0.9, "max_tokens": 64})
    assert env.fingerprint == "model=m;decode=greedy-0.0;extract=strict@3;max_tokens=64;top_p=0.9"


def test_make_accepts_a_scorer_object_and_reads_its_version():
    from driftaudit.scoring import get_scorer
    strict = get_scorer("strict")
    env = Environment.make(model="m", scorer=strict)
    assert env.scorer == "strict"
    assert env.fingerprint == f"model=m;decode=greedy-0.0;extract=strict@{strict.version}"


def test_make_without_an_id_derives_one_from_the_fingerprint():
    a = Environment.make(model="m", temperature=0.2)
    b = Environment.make(model="m", temperature=0.2)
    c = Environment.make(model="other", temperature=0.2)
    assert a.id == b.id and a.id != c.id
    assert a.id.startswith("env-") and len(a.id) == 12


def test_changing_any_component_changes_the_fingerprint():
    base = Environment.make(model="m", temperature=0.0, scorer="strict", scorer_version="1")
    for other in (Environment.make(model="m2", temperature=0.0, scorer="strict", scorer_version="1"),
                  Environment.make(model="m", temperature=0.2, scorer="strict", scorer_version="1"),
                  Environment.make(model="m", temperature=0.0, scorer="lenient", scorer_version="1"),
                  Environment.make(model="m", temperature=0.0, scorer="strict", scorer_version="2"),
                  Environment.make(model="m", temperature=0.0, scorer="strict", scorer_version="1", extra={"k": 1})):
        assert other.fingerprint != base.fingerprint


def test_environment_round_trips_through_its_dict():
    env = Environment.make(id="A", name="Baseline", model="m", temperature=0.2, scorer="lenient", extra={"top_p": 0.9})
    d = env.to_dict()
    assert set(d) == {"name", "decoding", "scorer", "fingerprint", "detail"}
    back = Environment.from_dict("A", d)
    assert back == env and back.detail == env.detail


def test_environments_are_hashable_and_frozen():
    env = Environment.make(id="A", model="m")
    assert len({env, Environment.make(id="A", model="m")}) == 1
    with pytest.raises(Exception):
        env.name = "changed"


def test_env_at_switches_on_the_start_round():
    schedule = {0: "E1", 4: "E2", 8: "E4"}
    assert [env_at(k, schedule) for k in range(11)] == ["E1"] * 4 + ["E2"] * 4 + ["E4"] * 3


def test_env_at_reads_string_keys_as_json_writes_them():
    schedule = {"0": "E1", "4": "E2", "10": "E4"}
    assert env_at(3, schedule) == "E1"
    assert env_at(4, schedule) == "E2"
    assert env_at(9, schedule) == "E2"      # "10" sorts before "4" as text, not as a round
    assert env_at(10, schedule) == "E4"


def test_env_at_before_the_first_start_uses_the_first_entry():
    assert env_at(0, {2: "A", 5: "B"}) == "A"


def test_env_at_matches_the_toolkit(toolkit):
    for schedule in ({0: "E1", 4: "E2", 8: "E4"}, {0: "E1", 4: "E1", 8: "E3"}, {3: "E2", 1: "E4"}):
        for k in range(12):
            assert env_at(k, schedule) == toolkit.envs.env_at(k, schedule)


def test_env_at_rejects_an_empty_schedule():
    with pytest.raises(DriftAuditError, match="schedule"):
        env_at(0, {})
