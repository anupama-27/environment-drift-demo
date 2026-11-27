"""Loading tasks: the bundled sample and JSONL files."""
from __future__ import annotations

import json

import pytest

from driftaudit.errors import DriftAuditError
from driftaudit.tasks import load_task


def write_rows(path, rows):
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows), encoding="utf-8")
    return path


def sums(n, start=0):
    return [{"question": f"What is {i} + 1?", "answer": i + 1} for i in range(start, start + n)]


def test_bundled_gsm8k_is_the_split_the_paper_runs_used():
    task = load_task("gsm8k", 200, 200)
    assert (task.name, task.items_ref, task.gold, len(task.dev), len(task.eval)) == ("GSM8K", "gsm8k/eval200", "number", 200, 200)
    assert task.dev[0]["id"] == "train-0" and task.dev[0]["gold"] == 72.0 and task.eval[199]["id"] == "test-199"
    assert set(task.eval[0]) == {"id", "question", "gold"}
    assert task.describe() == {"name": "GSM8K", "n_items": 200, "n_dev": 200, "dataset": "openai/gsm8k (main)",
                               "split": "test", "dev_split": "train", "items": "gsm8k/eval200"}
    small = load_task("GSM8K", 3, 5)
    assert [i["id"] for i in small.eval] == [f"test-{i}" for i in range(5)] and len(small.dev) == 3


@pytest.mark.parametrize("n_dev, n_eval, hint", [(201, 10, "200 development"), (10, 0, "at least one"), (0, 10, "at least one")])
def test_bundled_task_sizes_are_checked(n_dev, n_eval, hint):
    with pytest.raises(DriftAuditError, match=hint):
        load_task("gsm8k", n_dev, n_eval)


def test_file_task_takes_development_rows_first_then_evaluation_rows(tmp_path):
    path = write_rows(tmp_path / "my-sums.jsonl", sums(10) + ["", "  "])
    task = load_task(path, 4, 5)
    assert task.name == "my-sums" and task.items_ref is None and task.gold == "number"
    assert [i["gold"] for i in task.dev] == [1.0, 2.0, 3.0, 4.0]
    assert [i["gold"] for i in task.eval] == [5.0, 6.0, 7.0, 8.0, 9.0]
    assert task.describe() == {"name": "my-sums", "n_items": 5, "n_dev": 4}


def test_numeric_answers_are_read_in_the_usual_spellings(tmp_path):
    rows = [{"question": f"q{i}", "answer": a} for i, a in enumerate([72, 3.5, "1,250", "$40", "so 9 + 9 = 18\n#### 18", "-7"])]
    task = load_task(write_rows(tmp_path / "t.jsonl", rows), 1, 5)
    assert [i["gold"] for i in task.dev + task.eval] == [72.0, 3.5, 1250.0, 40.0, 18.0, -7.0]


def test_text_answers_stay_strings(tmp_path):
    rows = [{"question": "Capital of France?", "answer": " Paris "}, {"question": "2 + 2?", "answer": 4},
            {"question": "GSM style?", "answer": "work #### blue"}]
    path = write_rows(tmp_path / "t.jsonl", rows)
    task = load_task(path, 1, 2)
    assert task.gold == "text" and [i["gold"] for i in task.dev + task.eval] == ["Paris", "4", "blue"]
    with pytest.raises(DriftAuditError, match="line 1: the answer ' Paris ' is not a number"):
        load_task(path, 1, 2, gold="number")
    numbers = write_rows(tmp_path / "n.jsonl", sums(4))
    assert load_task(numbers, 2, 2, gold="text").eval[0]["gold"] == "3"


def test_item_ids_are_stable_and_tied_to_the_wording(tmp_path):
    path = write_rows(tmp_path / "t.jsonl", sums(6))
    first = load_task(path, 2, 4)
    assert [i["id"] for i in load_task(path, 1, 5).eval][1:] == [i["id"] for i in first.eval]
    assert first.eval[0]["id"].startswith("t-2-") and len({i["id"] for i in first.dev + first.eval}) == 6
    rows = sums(6)
    rows[2]["question"] = "What is two plus one?"
    edited = load_task(write_rows(path, rows), 2, 4)
    assert edited.eval[0]["id"] != first.eval[0]["id"] and edited.eval[1]["id"] == first.eval[1]["id"]
    named = load_task(write_rows(path, [dict(r, id=f"item{i}") for i, r in enumerate(sums(4))]), 2, 2)
    assert named.eval[0]["id"].startswith("item2-")


def test_separate_development_file(tmp_path):
    main = write_rows(tmp_path / "eval.jsonl", sums(5))
    dev = write_rows(tmp_path / "dev.jsonl", sums(3, start=100))
    task = load_task(main, 2, 5, dev_file=dev)
    assert [i["gold"] for i in task.dev] == [101.0, 102.0] and len(task.eval) == 5
    with pytest.raises(DriftAuditError, match="has 3 rows, but 4 were asked for"):
        load_task(main, 4, 5, dev_file=dev)
    with pytest.raises(DriftAuditError, match="only goes with a task file"):
        load_task("gsm8k", 2, 2, dev_file=dev)
    with pytest.raises(DriftAuditError, match="No development file"):
        load_task(main, 2, 2, dev_file=tmp_path / "nope.jsonl")


@pytest.mark.parametrize("rows, hint", [
    ([{"question": "q"}], 'line 1 has no "answer" field'),
    ([{"answer": 1}], 'line 1 has no "question" field'),
    ([{"question": "q", "answer": 1}, "{not json"], "line 2 is not JSON"),
    ([[1, 2]], "line 1 is not an object"),
    ([{"question": "", "answer": 1}], "non-empty string"),
    ([{"question": "q", "answer": None}], "number or a string"),
    ([{"question": "q", "answer": True}], "number or a string"),
    ([], "has no rows"),
    (sums(3), "has 3 rows, but 2 development and 2 evaluation"),
    ([{"question": "q", "answer": 1, "id": "x"}] * 4, "same item twice"),
])
def test_file_problems_name_the_line_and_the_fix(tmp_path, rows, hint):
    with pytest.raises(DriftAuditError, match=hint):
        load_task(write_rows(tmp_path / "t.jsonl", rows), 2, 2)


def test_missing_file_and_bad_gold_mode(tmp_path):
    with pytest.raises(DriftAuditError, match="No task file at"):
        load_task(tmp_path / "nope.jsonl", 1, 1)
    with pytest.raises(DriftAuditError, match="auto, number or text"):
        load_task("gsm8k", 1, 1, gold="float")
