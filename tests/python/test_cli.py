"""Every command through main([...]), with its exit code and what it prints."""
from __future__ import annotations

import json
import os

import pytest

from app_fixtures import PAPER_SEED5, mock_loop, mock_run_file  # noqa: F401
from conftest import paper_run_path
from driftaudit import cli, schema
from driftaudit.loop import read_outputs


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    return code, captured.out, captured.err


def test_version_and_help(capsys):
    assert run_cli(capsys, "--version") == (0, "driftaudit 0.1.0\n", "")
    code, out, _ = run_cli(capsys, "--help")
    assert code == 0
    for command in ("demo", "view", "audit", "report", "run", "convert", "validate", "rescore"):
        assert command in out


def test_usage_errors_exit_with_1_not_2(capsys):
    code, out, err = run_cli(capsys)
    assert code == 1 and out == "" and "driftaudit: " in err
    code, _, err = run_cli(capsys, "audit", "x.json", "--format", "yaml")
    assert code == 1 and "invalid choice" in err


def test_run_without_arguments_uses_the_bundled_task_and_the_mock_backend(capsys, cwd):
    code, out, err = run_cli(capsys, "run")
    assert code == 0
    assert out.splitlines()[-3:] == ["Next:", "  driftaudit audit driftaudit-run.json", "  driftaudit view driftaudit-run.json"]
    assert "synthetic run" in out
    assert err.startswith("GSM8K: 200 development and 200 evaluation items, 11 rounds, seed 1, mock backend")
    assert sum(line.startswith("round ") for line in err.splitlines()) == 11
    assert sorted(os.listdir(cwd)) == ["driftaudit-run.json", "driftaudit-run.outputs.jsonl.gz"]
    run = schema.load(cwd / "driftaudit-run.json")
    assert run["source"] == "synthetic" and run["task"]["n_items"] == 200 and len(run["candidates"]) == 11
    assert run["schedule"] == {"0": "E1", "4": "E2", "8": "E4"}
    assert run["outputs"] == {"layout": "sidecar", "file": "driftaudit-run.outputs.jsonl.gz"}
    assert len(read_outputs(cwd / "driftaudit-run.outputs.jsonl.gz")) == len(run["prompts"]) * 4


def test_first_run_with_the_simulator_shows_a_stale_accept(capsys, cwd):
    assert run_cli(capsys, "run")[0] == 0
    code, out, err = run_cli(capsys, "audit", "driftaudit-run.json", "--fail-on", "stale-accept", "--policy", "frozen")
    assert code == cli.FAIL_EXIT and "driftaudit-run.json round 9" in err
    assert "1 false accept (1 stale reference)" in out


def test_run_options_reach_the_loop(capsys, cwd):
    code, out, _ = run_cli(capsys, "run", "--n-dev", "12", "--n-eval", "15", "--rounds", "3", "--seed", "4",
                           "--schedule", "0:greedy/strict,1:greedy/lenient", "--batch-size", "4",
                           "--initial-prompt", "Solve it. Put the number in \\boxed{}.", "--cache", "c.jsonl",
                           "-o", "my run.json")
    assert code == 0 and "driftaudit audit 'my run.json'" in out
    run = schema.load(cwd / "my run.json")
    assert (run["seed"], run["task"]["n_items"], run["task"]["n_dev"], len(run["candidates"])) == (4, 15, 12, 3)
    assert list(run["environments"]) == ["E1", "E2"] and run["schedule"] == {"0": "E1", "1": "E2"}
    assert next(iter(run["prompts"].values())) == "Solve it. Put the number in \\boxed{}."
    assert run["meta"]["config"]["batch_size"] == 4
    assert (cwd / "c.jsonl").stat().st_size > 0 and (cwd / "my run.outputs.jsonl.gz").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_written_files_get_the_usual_mode_for_new_files(capsys, cwd):
    old = os.umask(0o022)
    try:
        assert run_cli(capsys, "run", "--n-dev", "4", "--n-eval", "5", "--rounds", "2", "-o", "r.json")[0] == 0
        assert run_cli(capsys, "convert", "r.json", "-o", "c.json")[0] == 0
        assert run_cli(capsys, "report", "r.json", "-o", "r.html")[0] == 0
    finally:
        os.umask(old)
    for name in ("r.json", "r.outputs.jsonl.gz", "c.json", "r.html"):
        assert (cwd / name).stat().st_mode & 0o777 == 0o644, name


def test_run_scales_the_default_schedule_to_the_rounds_and_keeps_an_explicit_one(capsys, cwd):
    code, _, err = run_cli(capsys, "run", "--n-dev", "4", "--n-eval", "5", "--rounds", "4", "-o", "a.json")
    assert code == 0 and schema.load(cwd / "a.json")["schedule"] == {"0": "E1", "1": "E2", "3": "E4"}
    assert err.splitlines()[0].endswith("schedule 0:greedy/strict,1:sample@0.2/strict,3:sample@0.2/lenient")
    code, _, err = run_cli(capsys, "run", "--n-dev", "4", "--n-eval", "5", "--rounds", "4",
                           "--schedule", "0:greedy/strict,8:greedy/lenient", "-o", "b.json")
    assert code == 0 and schema.load(cwd / "b.json")["schedule"] == {"0": "E1", "8": "E2"}
    assert "after the last round" in err


def test_run_on_a_task_file(capsys, cwd):
    rows = [{"question": f"What is {i} plus {i + 1}?", "answer": 2 * i + 1} for i in range(20)]
    (cwd / "sums.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    code, _, _ = run_cli(capsys, "run", "--task", "sums.jsonl", "--n-dev", "8", "--n-eval", "12", "--rounds", "2", "-o", "s.json")
    assert code == 0
    run = schema.load(cwd / "s.json")
    assert run["task"]["name"] == "sums" and run["meta"]["gold"][:2] == [17.0, 19.0]


@pytest.mark.parametrize("argv, hint", [
    (["run", "--backend", "openai"], "needs --model"),
    (["run", "--model", "gpt-x"], "real backend"),
    (["run", "--backend", "hf", "--base-url", "http://localhost:1/v1"], "only applies to --backend openai"),
    (["run", "--task", "nowhere.jsonl"], "No task file"),
    (["run", "--schedule", "0:greedy/strict,2:greedy/exact"], "cannot mix"),
    (["run", "--n-eval", "500"], "200 evaluation items"),
    (["run", "--backend", "openai", "--model", "m", "--base-url", "ftp://x/v1"], "--base-url must look like"),
])
def test_run_refuses_what_it_cannot_do(capsys, cwd, argv, hint):
    code, out, err = run_cli(capsys, *argv)
    assert code == 1 and err.startswith("driftaudit: ") and hint in err
    assert os.listdir(cwd) == []


def test_audit_prints_the_report_for_one_run(capsys):
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5)
    assert code == 0 and err == ""
    assert out.startswith("DriftAudit 0.1.0: audit of gsm8k-qwen2.5-1.5b-seed5\n")
    assert "4 false accepts (3 stale reference, 1 no environment change)" in out
    assert "\x1b[" not in out


def test_audit_formats_and_output_file(capsys, cwd):
    code, out, _ = run_cli(capsys, "audit", PAPER_SEED5, "--format", "json")
    result = json.loads(out)
    assert code == 0 and result["schema"] == "driftaudit.audit/v1" and result["policies"]["frozen"]["false_accepts"] == 4
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5, "--format", "md", "-o", "audit.md", "--policy", "env_triggered")
    assert code == 0 and out == "" and "Wrote audit.md" in err
    text = (cwd / "audit.md").read_text(encoding="utf-8")
    assert text.startswith("# DriftAudit") and "## Environment-triggered: refresh after detected environment changes" in text


def test_audit_what_if_options(capsys):
    code, out, _ = run_cli(capsys, "audit", PAPER_SEED5, "--schedule", "0:E1,4:E1,8:E3", "--stored-scoring", "rescore",
                           "--margin", "1", "--periodic-k", "2", "--format", "json")
    options = json.loads(out)["options"]
    assert code == 0 and options["schedule"] == {"0": "E1", "4": "E1", "8": "E3"} and options["schedule_overridden"]
    assert (options["stored_scoring"], options["margin"], options["periodic_k"]) == ("rescore", 1, 2)
    code, _, err = run_cli(capsys, "audit", PAPER_SEED5, "--schedule", "0:E9")
    assert code == 1 and "E9" in err
    code, _, err = run_cli(capsys, "audit", PAPER_SEED5, "--schedule", "E1")
    assert code == 1 and "ROUND:ENV" in err


def test_audit_of_several_runs_prints_the_study_with_a_line_per_run(capsys):
    paths = [paper_run_path(seed) for seed in (1, 2, 3, 4, 5)]
    code, out, _ = run_cli(capsys, "audit", *paths)
    assert code == 0 and out.startswith("DriftAudit 0.1.0: study of 5 runs\n")
    assert "  Frozen                      34             13              0     70.8 ± 2.0%" in out
    assert sum("gsm8k-qwen2.5-1.5b-seed" in line for line in out.splitlines()) == 5
    code, out, _ = run_cli(capsys, "audit", *paths, "--format", "json")
    assert json.loads(out)["schema"] == "driftaudit.study/v1"


def test_fail_on_exit_codes(capsys, mock_run_file):
    # Seed 5 under the frozen policy has three stale accepts; the loop's own decisions have none.
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5, "--policy", "frozen", "--fail-on", "stale-accept")
    assert code == 2 and "stale reference" in out
    assert err == f"driftaudit: a false accept on a stale reference under the Frozen policy: {PAPER_SEED5} rounds 5, 8, 10\n"
    code, _, err = run_cli(capsys, "audit", PAPER_SEED5, "--policy", "frozen", "--fail-on", "false-accept")
    assert code == 2 and "rounds 3, 5, 8, 10" in err
    # The loop's own decisions compare each candidate with its incumbent in the same pass, so
    # they cannot fail the check: the gate asks the frozen policy instead.
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5, "--fail-on", "false-accept")
    assert code == 2 and "under the Frozen policy" in err and "As run is not listed" in out
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5, "--policy", "as_run", "--fail-on", "false-accept")
    assert code == 0 and err == "" and "As run: the decisions the loop recorded" in out
    code, _, err = run_cli(capsys, "audit", PAPER_SEED5, paper_run_path(4), "--policy", "frozen", "--fail-on", "stale-accept")
    assert code == 2 and paper_run_path(4) not in err


def test_fail_on_falls_back_to_frozen_and_refuses_what_it_cannot_check(capsys, tmp_path):
    run = schema.load(PAPER_SEED5)
    for cand in run["candidates"]:
        cand.pop("reference")
    bare = tmp_path / "bare.json"
    schema.save(run, bare)
    code, _, err = run_cli(capsys, "audit", str(bare), "--fail-on", "stale-accept")
    assert code == 2 and "under the Frozen policy" in err
    code, _, err = run_cli(capsys, "audit", str(bare), "--policy", "as_run", "--fail-on", "stale-accept")
    assert code == 1 and "cannot be replayed" in err


def test_convert_writes_v1_and_slim_drops_the_batch_layout(capsys, cwd):
    assert run_cli(capsys, "convert", PAPER_SEED5, "-o", "full.json")[0] == 0
    code, _, err = run_cli(capsys, "convert", PAPER_SEED5, "-o", "slim.json", "--slim")
    assert code == 0 and "id gsm8k-qwen2.5-1.5b-seed5" in err
    full, slim = (json.loads((cwd / name).read_text(encoding="utf-8")) for name in ("full.json", "slim.json"))
    assert full["schema"] == slim["schema"] == schema.SCHEMA
    assert "passes" in full["meta"]["config"] and "passes" not in slim["meta"]["config"]
    assert slim["meta"]["config"]["rounds"] == 11 and slim["labels"] == full["labels"]
    assert (cwd / "slim.json").stat().st_size < (cwd / "full.json").stat().st_size


def test_validate_reports_problems_and_exits_1(capsys, cwd, mock_run_file):
    code, out, _ = run_cli(capsys, "validate", PAPER_SEED5, str(mock_run_file))
    assert code == 0
    assert f"{PAPER_SEED5}: valid run log (measured, 11 rounds, 200 items, 12 prompts, complete label bank)" in out
    assert "small.json: valid run log (synthetic, 6 rounds, 40 items" in out
    run = json.loads(mock_run_file.read_text(encoding="utf-8"))
    run["schedule"]["3"] = "E9"
    del run["source"]
    (cwd / "broken.json").write_text(json.dumps(run), encoding="utf-8")
    (cwd / "notjson.json").write_text("{", encoding="utf-8")
    code, out, _ = run_cli(capsys, "validate", "broken.json", PAPER_SEED5, "notjson.json", "missing.json")
    assert code == 1
    assert "broken.json: 2 problems\n" in out and "  - schedule sends round 3 to environment 'E9'" in out
    assert "notjson.json: 1 problem\n" in out and "missing.json: 1 problem\n" in out and "no such file" in out


def test_validate_says_what_a_sparse_bank_cannot_support(capsys, cwd):
    run = schema.load(PAPER_SEED5)
    for per_env in run["labels"].values():
        per_env["E4"].pop("rerun")
    schema.save(run, cwd / "sparse.json")
    code, out, _ = run_cli(capsys, "validate", "sparse.json")
    assert code == 0 and "sparse label bank" in out
    assert "  - the Per-batch policy cannot be replayed: " in out and "label vector" in out
    assert "the Frozen policy" not in out


def test_rescore_compares_saved_outputs_with_the_stored_labels(capsys, mock_run_file):
    code, out, _ = run_cli(capsys, "rescore", str(mock_run_file), "--scorer", "strict", "--env", "E1")
    lines = out.splitlines()
    assert code == 0 and "small.outputs.jsonl.gz graded with the strict scorer (version 1)" in lines[0]
    assert lines[1].split() == ["env", "stored", "scorer", "labels", "match", "wrong", "to", "right", "right", "to", "wrong", "no", "outputs"]
    n_labels = len(schema.load(mock_run_file)["prompts"]) * 2 * 40
    assert lines[2].split() == ["E1", "strict", str(n_labels), str(n_labels), "0", "0", "0"]
    code, out, _ = run_cli(capsys, "rescore", str(mock_run_file), "--scorer", "lenient")
    rows = [line.split() for line in out.splitlines()[2:]]
    assert [row[0] for row in rows] == ["E1", "E2", "E3", "E4"]
    assert int(rows[0][4]) > 0 and rows[0][5] == "0"        # strict labels gain answers, lose none
    assert rows[2][2] == rows[2][3]                          # E3 was graded leniently to begin with


def test_rescore_needs_outputs_and_a_known_environment(capsys, mock_run_file, cwd):
    code, _, err = run_cli(capsys, "rescore", str(mock_run_file), "--scorer", "strict", "--env", "E7")
    assert code == 1 and "no environment 'E7'" in err
    code, _, err = run_cli(capsys, "rescore", str(mock_run_file), "--scorer", "fancy")
    assert code == 1 and "unknown scorer" in err
    code, _, err = run_cli(capsys, "rescore", PAPER_SEED5, "--scorer", "strict")
    assert code == 1 and "No outputs file next to" in err
    code, out, _ = run_cli(capsys, "rescore", PAPER_SEED5, "--scorer", "strict", "--outputs",
                           str(mock_run_file.parent / "small.outputs.jsonl.gz"))
    assert code == 0 and out.splitlines()[2].split()[2] == "0"       # other prompts: nothing to compare


def test_report_writes_one_html_file(capsys, cwd, mock_run_file):
    code, out, err = run_cli(capsys, "report", str(mock_run_file), PAPER_SEED5, "-o", "r.html", "--title", "Two <runs>")
    assert code == 0 and out == "" and "Wrote r.html" in err
    page = (cwd / "r.html").read_text(encoding="utf-8")
    assert "<title>Two &lt;runs&gt;</title>" in page and 'id="da-embedded"' in page


def test_demo_and_view_start_the_server_with_their_options(capsys, monkeypatch, mock_run_file):
    calls = []
    monkeypatch.setattr("driftaudit.server.serve", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert run_cli(capsys, "demo", "--no-open", "--port", "8791")[0] == 0
    assert run_cli(capsys, "view", str(mock_run_file), "--host", "0.0.0.0", "--title", "Mine")[0] == 0
    (demo_args, demo), (view_args, view) = calls
    assert demo_args == (None,) and (demo["port"], demo["open_browser"], demo["host"]) == (8791, False, "127.0.0.1")
    assert view_args == ([str(mock_run_file)],) and (view["port"], view["open_browser"], view["host"], view["title"]) == (8765, True, "0.0.0.0", "Mine")
    assert demo["announce"] is cli._say
    code, _, err = run_cli(capsys, "demo", "--port", "70000")
    assert code == 1 and "0 to 65535" in err


@pytest.mark.parametrize("argv", [
    ["audit", "missing.json"], ["view", "missing.json"], ["report", "missing.json", "-o", "r.html"],
    ["convert", "missing.json", "-o", "out.json"], ["rescore", "missing.json", "--scorer", "strict"]])
def test_missing_files_are_reported_in_one_line(capsys, cwd, argv):
    code, out, err = run_cli(capsys, *argv)
    assert (code, out) == (1, "") and err == "driftaudit: missing.json: no such file\n"


def test_file_that_is_not_a_run_log_is_explained(capsys, cwd):
    (cwd / "other.json").write_text('{"hello": 1}', encoding="utf-8")
    code, _, err = run_cli(capsys, "audit", "other.json")
    assert code == 1 and err.startswith("driftaudit: other.json is not a valid run log:")
    code, _, err = run_cli(capsys, "audit", PAPER_SEED5, "-o", "no/such/dir/a.txt")
    assert code == 1 and err.startswith("driftaudit: cannot write no/such/dir/a.txt")


def test_colour_needs_a_terminal_and_no_NO_COLOR(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    assert cli._color()
    monkeypatch.setenv("NO_COLOR", "1")
    assert not cli._color()
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    assert not cli._color()


def test_fail_on_checks_the_loop_itself_when_it_used_real_references(capsys, tmp_path):
    run = schema.load(PAPER_SEED5)
    first = run["snapshots"][0]
    for cand in run["candidates"]:
        cand["reference"] = {"prompt": first["prompt"], "env": first["env"], "pass": "current"}
    path = tmp_path / "real.json"
    schema.save(run, path)
    # The recorded verdicts have no false accepts, where the frozen policy has three stale ones.
    code, out, err = run_cli(capsys, "audit", str(path), "--fail-on", "stale-accept")
    assert code == 0 and err == "" and "\nAs run: the decisions the loop recorded" in out
    assert "As run is not listed" not in out


def test_study_of_loop_runs_leaves_out_the_trivial_as_run(capsys):
    code, out, _ = run_cli(capsys, "audit", PAPER_SEED5, paper_run_path(4))
    assert code == 0 and "As run is not listed" in out and "  As run  " not in out


def test_audit_refuses_to_pool_runs_that_differ_unless_allowed(capsys, mock_run_file):
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5, str(mock_run_file))
    assert code == 1 and out == "" and "cannot be pooled" in err and f"{mock_run_file}: task" not in err
    assert f"{mock_run_file}: number of items is 40, where {PAPER_SEED5} has 200" in err and "--allow-mixed" in err
    code, out, err = run_cli(capsys, "audit", PAPER_SEED5, str(mock_run_file), "--allow-mixed")
    assert code == 0 and err.startswith("driftaudit: warning: pooling runs that differ: ") and err.count("\n") == 1
    assert "source: mixed" in out
    code, _, err = run_cli(capsys, "audit", PAPER_SEED5, PAPER_SEED5)
    assert code == 1 and "is also the id of" in err


def test_periodic_policy_is_listed_only_when_its_k_is_given(capsys):
    _, out, _ = run_cli(capsys, "audit", PAPER_SEED5)
    assert "Every " not in out
    _, out, _ = run_cli(capsys, "audit", PAPER_SEED5, "--periodic-k", "2")
    assert "  Every 2 rounds  " in out
    _, out, _ = run_cli(capsys, "audit", PAPER_SEED5, "--policy", "periodic")
    assert "  Every 3 rounds  " in out and "\nEvery 3 rounds: " in out
    _, out, _ = run_cli(capsys, "audit", PAPER_SEED5, paper_run_path(4))
    assert "Every " not in out


def test_allow_insecure_http_goes_with_the_openai_backend_only(capsys, cwd):
    code, _, err = run_cli(capsys, "run", "--allow-insecure-http")
    assert code == 1 and "only applies to --backend openai" in err


def test_escape_sequences_in_a_run_log_never_reach_the_terminal(capsys, tmp_path):
    run = schema.load(PAPER_SEED5)
    run["id"] = "x\x1b]0;PWNED\x07\x1b[2J\x1b[31mRED\x00"
    run["environments"]["E1"]["name"] = "E\x9b2Jone"
    path = tmp_path / "ansi.json"
    schema.save(run, path)
    for argv in (["audit", str(path)], ["audit", str(path), "--format", "md"], ["validate", str(path)]):
        code, out, err = run_cli(capsys, *argv)
        assert code == 0 and "\x1b" not in out + err and "\x9b" not in out and "\x07" not in out
        assert argv[0] != "audit" or "xRED\\x00" in out
