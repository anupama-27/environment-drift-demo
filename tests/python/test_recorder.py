"""The recorder SDK: a loop written elsewhere, recorded and audited."""
from __future__ import annotations

import os
import runpy

import pytest

import driftaudit as da
from conftest import ROOT
from driftaudit import schema
from driftaudit.errors import DriftAuditError
from driftaudit.recorder import Recorder, ReferenceStore

A, B, C = "prompt a", "prompt b", "prompt c"


def env(scorer="strict", **options):
    return da.Environment.make(model="m", scorer=da.get_scorer(scorer), **options)


def recorded():
    """Two rounds with a scorer change between them; the second decision uses a stale reference."""
    strict, lenient = env("strict"), env("lenient")
    rec = Recorder(task="toy", n_items=4, model="m", seed=7, n_dev=3)
    rec.add_labels(A, strict, [1, 0, 0, 1])
    rec.add_labels(B, strict, "1100")
    rec.add_round(candidate=B, incumbent=A, env=strict, accepted=False, reference=(A, strict), note="first")
    rec.add_labels(C, lenient, [True, True, True, False])
    rec.add_labels(A, lenient, [1, 1, 1, 1])
    rec.add_labels(A, lenient, [1, 1, 1, 1], rerun=True)
    rec.add_round(candidate=C, incumbent=A, env=lenient, accepted=True, reference=(A, strict))
    return rec


def test_recorded_loop_round_trips_through_an_audit(tmp_path):
    run = recorded().save(tmp_path / "run.json")
    assert schema.load(tmp_path / "run.json") == run
    assert (run["id"], run["seed"], run["source"]) == ("toy-m-seed7", 7, "measured")
    assert run["task"] == {"name": "toy", "n_items": 4, "n_dev": 3} and run["cost"] == {"n_dev": 3, "proposal_calls": 1}
    assert list(run["environments"]) == ["E1", "E2"] and run["schedule"] == {"0": "E1", "1": "E2"}
    assert run["snapshots"] == [{"round": 0, "prompt": schema.prompt_id(A), "env": "E1"},
                                {"round": 1, "prompt": schema.prompt_id(A), "env": "E2"}]
    first, second = run["candidates"]
    assert (first["id"], first["wins"], first["losses"], first["accepted"], first["note"]) == ("C1", 1, 1, False, "first")
    assert second["reference"] == {"prompt": schema.prompt_id(A), "env": "E1", "pass": "current"}
    assert (second["wins"], second["losses"]) == (2, 1)

    audit = da.audit(run)
    own = audit["policies"]["as_run"]
    assert own["available"] and [d["accepted"] for d in own["decisions"]] == [False, True]
    stale = own["decisions"][1]
    assert stale["false_accept"] and stale["cause"] == "stale" and stale["env_mismatch"]
    assert (stale["rerun_wins"], stale["rerun_losses"]) == (0, 1)


def test_environment_ids_follow_first_use_unless_given():
    rec = Recorder(task="toy", n_items=2)
    lenient, strict = env("lenient"), env("strict")
    named = da.Environment.make(id="prod-nov", model="m2", scorer="strict")
    rec.add_labels(A, lenient, "10")
    rec.add_labels(A, named, "10")
    rec.add_labels(A, strict, "10")
    rec.add_labels(B, env("lenient"), "01")          # same settings, same environment
    rec.add_round(candidate=B, incumbent=A, env=lenient, accepted=False)
    run = rec.to_run()
    assert list(run["environments"]) == ["E1", "prod-nov", "E3"]
    assert run["environments"]["E1"]["scorer"] == "lenient" and "reference" not in run["candidates"][0]
    assert list(run["labels"][schema.prompt_id(B)]) == ["E1"]
    clash = da.Environment.make(id="prod-nov", model="m3", scorer="strict")
    with pytest.raises(DriftAuditError, match="both called 'prod-nov'"):
        rec.add_labels(A, clash, "10")


def test_reference_may_be_a_rerun():
    rec = Recorder(task="toy", n_items=3)
    e = env()
    rec.add_labels(A, e, "100")
    rec.add_labels(A, e, "110", rerun=True)
    rec.add_labels(B, e, "011")
    record = rec.add_round(candidate=B, incumbent=A, env=e, accepted=True, reference=(A, e, "rerun"))
    assert record["reference"]["pass"] == "rerun" and (record["wins"], record["losses"]) == (1, 1)
    assert rec.to_run()["labels"][schema.prompt_id(A)]["E1"] == {"current": "100", "rerun": "110"}


def test_second_stored_evaluation_must_be_declared_a_rerun():
    rec = Recorder(task="toy", n_items=3)
    e = env()
    rec.add_labels(A, e, "100")
    rec.add_labels(A, e, [1, 0, 0])                  # the same evaluation again is fine
    with pytest.raises(DriftAuditError, match="rerun=True"):
        rec.add_labels(A, e, "110")
    rec.add_labels(A, e, "110", rerun=True)
    rec.add_labels(A, e, "111", rerun=True)          # a newer rerun replaces the older one
    assert rec._labels[schema.prompt_id(A)]["E1"] == {"current": "100", "rerun": "111"}


@pytest.mark.parametrize("call, hint", [
    (lambda rec, e: rec.add_labels(A, e, "10"), "Got 2 labels, but the task has 3"),
    (lambda rec, e: rec.add_labels(A, e, [1, 2, 0]), "only 0 and 1"),
    (lambda rec, e: rec.add_labels("", e, "100"), "non-empty string"),
    (lambda rec, e: rec.add_labels(A, "E1", "100"), "driftaudit.Environment"),
    (lambda rec, e: rec.add_round(candidate=C, incumbent=A, env=e, accepted=True), "Unknown candidate"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=C, env=e, accepted=True), "Unknown incumbent"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=A, env=env("lenient"), accepted=True), "no labels under E2"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=A, env=e, accepted=1), "True or False"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=A, env=e, accepted=True, reference=(A,)), "reference must be"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=A, env=e, accepted=True, reference=(C, e)), "Unknown reference"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=A, env=e, accepted=True, reference=(A, e, "rerun")), "no rerun labels"),
    (lambda rec, e: rec.add_round(candidate=B, incumbent=A, env=e, accepted=True, reference=(A, e, "later")), '"current" or "rerun"'),
])
def test_bad_input_is_refused_with_a_reason(call, hint):
    rec = Recorder(task="toy", n_items=3)
    e = env()
    rec.add_labels(A, e, "100")
    rec.add_labels(B, e, "010")
    with pytest.raises(DriftAuditError, match=hint):
        call(rec, e)
    assert rec._candidates == [] and list(rec._prompts.values()) == [A, B]


def test_recorder_needs_items_a_known_source_and_at_least_one_round():
    with pytest.raises(DriftAuditError, match="n_items"):
        Recorder(task="toy")
    with pytest.raises(DriftAuditError, match="source"):
        Recorder(task="toy", n_items=2, source="guessed")
    with pytest.raises(DriftAuditError, match="at least one round"):
        Recorder(task="toy", n_items=2).to_run()


def test_task_and_model_can_be_given_in_full():
    rec = Recorder(task={"name": "QA", "split": "dev"}, n_items=2, model={"id": "org/Model-7B", "revision": "abc"},
                   seed=None, source="synthetic", id="my-run")
    e = env()
    rec.add_labels(A, e, "10")
    rec.add_labels(B, e, "11")
    rec.add_round(candidate=B, incumbent=A, env=e, accepted=True, reference=(A, e))
    run = rec.to_run()
    assert run["id"] == "my-run" and run["source"] == "synthetic" and run["seed"] is None
    assert run["task"] == {"name": "QA", "split": "dev", "n_items": 2, "n_dev": 0}
    assert run["model"] == {"id": "org/Model-7B", "revision": "abc"}


def test_reference_store_flags_a_changed_fingerprint():
    strict, lenient = env("strict"), env("lenient")
    store = ReferenceStore()
    assert store.reference is None and store.stale(strict)
    reference = store.set(A, strict, [1, 0, 1])
    assert reference == (A, strict, "101") and store.reference.labels == "101"
    assert not store.stale(strict) and not store.stale(env("strict"))
    assert store.stale(lenient) and store.stale(env("strict", temperature=0.2))
    store.set(A, lenient, "111")
    assert not store.stale(lenient)


def test_reference_store_policies():
    strict, lenient = env("strict"), env("lenient")
    frozen, every = ReferenceStore("frozen"), ReferenceStore("per_batch")
    assert frozen.stale(strict) and every.stale(strict)
    frozen.set(A, strict, "1")
    every.set(A, strict, "1")
    assert not frozen.stale(lenient) and every.stale(strict)
    with pytest.raises(DriftAuditError, match="env_triggered, per_batch, frozen"):
        ReferenceStore("sometimes")
    with pytest.raises(DriftAuditError):
        frozen.set(A, "E1", "1")


def test_public_names_are_exported():
    assert da.Recorder is Recorder and da.ReferenceStore is ReferenceStore
    assert da.run_loop.__module__ == "driftaudit.loop"


def test_example_script_records_audits_and_prints(tmp_path, capsys):
    script = os.path.join(ROOT, "examples", "record_your_own_loop.py")
    out = tmp_path / "example.json"
    result = runpy.run_path(script)["main"](str(out))
    printed = capsys.readouterr().out
    assert printed.startswith("DriftAudit 0.1.0: audit of toy-addition-toy-adder-seed0\nsource: synthetic")
    assert "As run: the decisions the loop recorded" in printed and "stale reference" in printed
    run = schema.load(out)
    assert run["source"] == "synthetic" and run["schedule"] == {"0": "E1", "3": "E2"}
    assert [e["name"] for e in run["environments"].values()] == ["Strict scorer", "Lenient scorer"]
    own, triggered = result["policies"]["as_run"], result["policies"]["env_triggered"]
    assert own["causes"]["stale"] >= 1 and triggered["false_accepts"] < own["false_accepts"]
    assert result["completeness"]["full_bank"]
