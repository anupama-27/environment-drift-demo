"""Build the small fixtures that both engines are tested against.

    python scripts/make_fixtures.py OUTPUTS_CSV GSM8K_TRAIN_JSONL GSM8K_TEST_JSONL

Writes
    data/tasks/gsm8k/dev200.jsonl, eval200.jsonl   first 200 items of each split, as the runs used them
    tests/golden/scorer_cases.json                 real model outputs with the answer each extractor read

The CSV is the decoded generation cache of the five paper runs (one row per saved output, with
the answers the original extractors read). The sample is stratified by which lenient rule fired
and by correctness, and is deterministic.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PER_STRATUM = 22
MAX_CHARS = 2600


def gold_number(answer_field: str) -> str:
    return answer_field.split("####")[-1].strip().replace(",", "")


def write_task(src: str, split: str, dst: str, n: int = 200) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as out:
        for i, line in enumerate(f):
            if i >= n:
                break
            row = json.loads(line)
            out.write(json.dumps({"id": f"{split}-{i}", "question": row["question"],
                                  "answer": gold_number(row["answer"])}, ensure_ascii=False) + "\n")


def num(cell: str):
    return None if cell in ("", "None") else float(cell)


def scorer_cases(csv_path: str) -> list:
    csv.field_size_limit(10 ** 9)
    strata: dict = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["split"] != "test" or len(row["output"]) > MAX_CHARS:
                continue
            key = (row["v2_rule"], row["v1_correct"], row["v2_correct"])
            rank = hashlib.sha1((row["prompt_hash"] + row["item_id"] + row["decoding"] + row["tag"]
                                 + row["seeds"]).encode()).hexdigest()
            strata.setdefault(key, []).append((rank, row))
    cases = []
    for key in sorted(strata):
        for _, row in sorted(strata[key], key=lambda x: x[0])[:PER_STRATUM]:
            cases.append({"text": row["output"], "gold": num(row["gold"]),
                          "strict": num(row["v1_extracted"]), "lenient": num(row["v2_extracted"]),
                          "rule": row["v2_rule"],
                          "strict_correct": row["v1_correct"] == "1", "lenient_correct": row["v2_correct"] == "1"})
    return cases


def main() -> None:
    csv_path, train, test = sys.argv[1:4]
    write_task(train, "train", os.path.join(ROOT, "data", "tasks", "gsm8k", "dev200.jsonl"))
    write_task(test, "test", os.path.join(ROOT, "data", "tasks", "gsm8k", "eval200.jsonl"))
    cases = scorer_cases(csv_path)
    out = os.path.join(ROOT, "tests", "golden", "scorer_cases.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=0)
    rules = {}
    for c in cases:
        rules[c["rule"]] = rules.get(c["rule"], 0) + 1
    print(f"{len(cases)} scorer cases -> {os.path.relpath(out, ROOT)} ({os.path.getsize(out) // 1024} KB) by rule {rules}")


if __name__ == "__main__":
    main()
