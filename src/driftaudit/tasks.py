"""Tasks: questions that each have one checkable answer, split into a development set (shown
to the proposer) and an evaluation set (what candidates are compared on)."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ._paths import web_dir
from .errors import DriftAuditError
from .scoring import gold_answer

BUNDLED = "gsm8k"
EXAMPLE_ROW = '{"question": "What is 6 times 7?", "answer": 42}'
# The wording the paper's runs used for GSM8K; other tasks get a neutral one from the loop.
GSM8K_PROPOSER_SYSTEM = ("You improve instructions for a small model that solves "
                         "grade-school math word problems.")


@dataclass
class Task:
    """Items are {"id", "question", "gold"}; gold is a float or a string (see `gold`)."""

    name: str
    dev: List[Dict[str, Any]]
    eval: List[Dict[str, Any]]
    # Name of the bundled item file the workbench can show questions from, if there is one.
    items_ref: Optional[str] = None
    # "number": golds are floats, for the numeric scorers. "text": strings, for exact match.
    gold: str = "number"
    proposer_system: Optional[str] = None
    info: Dict[str, Any] = field(default_factory=dict)

    def describe(self) -> Dict[str, Any]:
        """The `task` entry of a run log."""
        out: Dict[str, Any] = {"name": self.name, "n_items": len(self.eval), "n_dev": len(self.dev)}
        out.update(self.info)
        if self.items_ref:
            out["items"] = self.items_ref
        return out


def load_task(spec: Union[str, Path], n_dev: int = 200, n_eval: int = 200, *,
              dev_file: Union[str, Path, None] = None, gold: str = "auto") -> Task:
    """The bundled GSM8K sample (`spec == "gsm8k"`) or a JSONL file of questions and answers.

    In a file the first n_dev rows are the development set and the next n_eval rows the
    evaluation set; with dev_file, the development rows come from that file instead and the
    evaluation set is the first n_eval rows of the task file.

    gold says how answers are read: "number" (numbers, numeric strings with commas, or
    GSM8K-style "... #### 72" text), "text" (compared as strings), or "auto", which picks
    "number" when every answer is one.
    """
    if gold not in ("auto", "number", "text"):
        raise DriftAuditError(f"gold must be auto, number or text, not {gold!r}")
    if n_dev < 1 or n_eval < 1:
        raise DriftAuditError("A run needs at least one development item and one evaluation item "
                              f"(got n_dev={n_dev}, n_eval={n_eval}).")
    if str(spec).lower() == BUNDLED:
        if dev_file is not None:
            raise DriftAuditError("The bundled gsm8k task has its own development set; "
                                  "--dev-file only goes with a task file.")
        folder = web_dir() / "data" / "tasks" / BUNDLED
        dev_rows = _read_rows(folder / "dev200.jsonl")
        eval_rows = _read_rows(folder / "eval200.jsonl")
        if n_dev > len(dev_rows) or n_eval > len(eval_rows):
            raise DriftAuditError(
                f"The bundled gsm8k task has {len(dev_rows)} development and {len(eval_rows)} "
                f"evaluation items; {n_dev} and {n_eval} were asked for.")
        dev_rows, eval_rows = dev_rows[:n_dev], eval_rows[:n_eval]
        kind = _kind(gold, dev_rows + eval_rows)
        task = Task(name="GSM8K", dev=_items(dev_rows, kind), eval=_items(eval_rows, kind),
                    items_ref="gsm8k/eval200", gold=kind, proposer_system=GSM8K_PROPOSER_SYSTEM,
                    info={"dataset": "openai/gsm8k (main)", "split": "test", "dev_split": "train"})
    else:
        path = Path(spec)
        if not path.is_file():
            raise DriftAuditError(
                f"No task file at {path}. Use --task gsm8k for the bundled task, or give a JSONL "
                f"file with one object per line, such as {EXAMPLE_ROW}")
        rows = _read_rows(path)
        if dev_file is None:
            if len(rows) < n_dev + n_eval:
                raise DriftAuditError(
                    f"{path} has {len(rows)} rows, but {n_dev} development and {n_eval} evaluation "
                    "items were asked for. Lower --n-dev or --n-eval, or pass a separate --dev-file.")
            dev_rows, eval_rows = rows[:n_dev], rows[n_dev:n_dev + n_eval]
        else:
            dev_path = Path(dev_file)
            if not dev_path.is_file():
                raise DriftAuditError(f"No development file at {dev_path}.")
            dev_rows = _read_rows(dev_path, id_prefix="dev")
            for name, got, want in ((dev_path, dev_rows, n_dev), (path, rows, n_eval)):
                if len(got) < want:
                    raise DriftAuditError(f"{name} has {len(got)} rows, but {want} were asked for.")
            dev_rows, eval_rows = dev_rows[:n_dev], rows[:n_eval]
        kind = _kind(gold, dev_rows + eval_rows)
        task = Task(name=path.stem, dev=_items(dev_rows, kind, pin_text=True),
                    eval=_items(eval_rows, kind, pin_text=True), gold=kind)
    _check_unique(task)
    return task


@dataclass
class _Row:
    where: str          # "file.jsonl line 3", for error messages
    id: str
    question: str
    answer: Any


def _read_rows(path: Path, id_prefix: str = "") -> List[_Row]:
    rows = []
    stem = f"{id_prefix}-{path.stem}" if id_prefix else path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DriftAuditError(f"Cannot read {path}: {exc}") from exc
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path} line {number}"
        try:
            obj = json.loads(line)
        except ValueError:
            raise DriftAuditError(f"{where} is not JSON. Each line must be one object, such as "
                                  f"{EXAMPLE_ROW}") from None
        if not isinstance(obj, dict):
            raise DriftAuditError(f"{where} is not an object. Each line must look like {EXAMPLE_ROW}")
        for name in ("question", "answer"):
            if name not in obj:
                raise DriftAuditError(f'{where} has no "{name}" field. Each line needs a question '
                                      f"and an answer, such as {EXAMPLE_ROW}")
        question, answer = obj["question"], obj["answer"]
        if not isinstance(question, str) or not question.strip():
            raise DriftAuditError(f'{where}: "question" must be a non-empty string.')
        if isinstance(answer, bool) or not isinstance(answer, (str, int, float)):
            raise DriftAuditError(f'{where}: "answer" must be a number or a string.')
        rows.append(_Row(where, str(obj.get("id", f"{stem}-{number - 1}")), question, answer))
    if not rows:
        raise DriftAuditError(f"{path} has no rows. Each line must look like {EXAMPLE_ROW}")
    return rows


def _as_number(answer: Any) -> Optional[float]:
    if isinstance(answer, str):
        value = gold_answer(answer)
    else:
        value = float(answer)
    return value if value is not None and math.isfinite(value) else None


def _kind(gold: str, rows: List[_Row]) -> str:
    if gold == "auto":
        return "number" if all(_as_number(r.answer) is not None for r in rows) else "text"
    return gold


def _items(rows: List[_Row], kind: str, pin_text: bool = False) -> List[Dict[str, Any]]:
    items = []
    for row in rows:
        if kind == "number":
            value: Any = _as_number(row.answer)
            if value is None:
                raise DriftAuditError(
                    f"{row.where}: the answer {row.answer!r} is not a number. For text answers "
                    "use the exact or exact-normalized scorer in --schedule.")
        else:
            value = str(row.answer).split("####")[-1].strip()
            if not value:
                raise DriftAuditError(f"{row.where}: the answer is empty.")
        item_id = row.id
        if pin_text:
            # Ids go into cache keys. Tying them to the wording means an edited question never
            # gets text that was generated for the old one.
            item_id += "-" + hashlib.sha1(row.question.encode("utf-8")).hexdigest()[:8]
        items.append({"id": item_id, "question": row.question, "gold": value})
    return items


def _check_unique(task: Task) -> None:
    seen: Dict[str, Tuple[str, int]] = {}
    for part, items in (("development", task.dev), ("evaluation", task.eval)):
        for index, item in enumerate(items):
            if item["id"] in seen:
                other_part, other_index = seen[item["id"]]
                raise DriftAuditError(
                    f"The task has the same item twice: {part} item {index} and {other_part} "
                    f"item {other_index} (id {item['id']}). Every item needs its own id.")
            seen[item["id"]] = (part, index)
