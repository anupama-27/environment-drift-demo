"""Build the data the workbench ships with, from the five saved runs and their decoded outputs.

    python scripts/build_data.py OUTPUTS_CSV

OUTPUTS_CSV is the decoded generation cache of the paper runs (one row per saved output:
seeds, prompt_hash, decoding, tag, split, item_id, output, ...). It is not part of the
repository; the chunk files this script writes are.

Writes
    data/runs/paper/seed<N>.json                         v1 run logs converted from toolkit/runs/
    data/outputs/paper/shared/<prompt>/greedy-0.0.current.json.gz
    data/outputs/paper/s<N>/<prompt>/<decoding>.<pass>.json.gz
    data/index.json                                      the run gallery (other groups are kept)

Every chunk is re-scored with the scorer of each environment that reads it and compared with
the labels in the run log. The script stops if a single label disagrees.
"""
from __future__ import annotations

import csv
import glob
import gzip
import json
import os
import sys

from driftaudit import schema
from driftaudit.scoring import get_scorer, score_outputs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = sorted(glob.glob(os.path.join(ROOT, "toolkit", "runs", "run_seed*_r11.json")))
OUT_RUNS = os.path.join(ROOT, "data", "runs", "paper")
OUT_CHUNKS = os.path.join(ROOT, "data", "outputs", "paper")
SHARED = "greedy-0.0.current"


def read_outputs(csv_path):
    """{(scope, prompt, decoding, pass): {item index: text}}; scope is 'shared' or a seed number."""
    csv.field_size_limit(10 ** 9)
    chunks = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["split"] != "test":
                continue
            item = int(row["item_id"].rsplit("-", 1)[1])
            name = f"{row['decoding']}.{row['tag']}"
            scopes = ["shared"] if name == SHARED else [int(s) for s in row["seeds"].split(",")]
            for scope in scopes:
                chunks.setdefault((scope, row["prompt_hash"], row["decoding"], row["tag"]), {})[item] = row["output"]
    return chunks


def write_chunk(path, texts):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = json.dumps(texts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as f:
        # mtime=0 keeps the bytes identical between builds
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0, compresslevel=9) as gz:
            gz.write(raw)
    return os.path.getsize(path)


def load_golds():
    path = os.path.join(ROOT, "data", "tasks", "gsm8k", "eval200.jsonl")
    with open(path, encoding="utf-8") as f:
        return [float(json.loads(line)["answer"]) for line in f]


def main():
    csv_path = sys.argv[1]
    chunks = read_outputs(csv_path)
    golds = load_golds()
    os.makedirs(OUT_RUNS, exist_ok=True)

    total_bytes = written = checked = 0
    gallery = []
    for path in RUNS:
        run = schema.load(path)
        seed = run["seed"]
        n = run["task"]["n_items"]
        config = run.get("meta", {}).get("config")
        if isinstance(config, dict):
            # 44 passes x 200 item indices, plus the note about how they were rebuilt; no analysis reads them
            config.pop("passes", None)
            config.pop("passes_reconstructed", None)
        run["outputs"] = {"layout": "chunks", "base": f"../../outputs/paper/s{seed}/",
                          "shared": {SHARED: "../../outputs/paper/shared/"}}

        for prompt in run["prompts"]:
            for env_id, env in run["environments"].items():
                scorer = get_scorer(env["scorer"])
                for tag in ("current", "rerun"):
                    name = f"{env['decoding']}.{tag}"
                    scope = "shared" if name == SHARED else seed
                    items = chunks.get((scope, prompt, env["decoding"], tag))
                    if items is None or len(items) != n:
                        sys.exit(f"missing outputs for seed {seed} prompt {prompt} {name}")
                    texts = [items[i] for i in range(n)]
                    got = schema.encode_labels(score_outputs(texts, golds, scorer))
                    want = schema.labels(run, prompt, env_id, tag)
                    if got != want:
                        sys.exit(f"labels differ for seed {seed} prompt {prompt} {env_id} {tag}")
                    checked += n
                    sub = "shared" if scope == "shared" else f"s{seed}"
                    target = os.path.join(OUT_CHUNKS, sub, prompt, name + ".json.gz")
                    if not os.path.exists(target):
                        total_bytes += write_chunk(target, texts)
                        written += 1

        out = os.path.join(OUT_RUNS, f"seed{seed}.json")
        schema.save(run, out)
        gallery.append({"id": run["id"], "label": f"Seed {seed}", "url": f"data/runs/paper/seed{seed}.json"})
        print(f"seed {seed}: {len(run['prompts'])} prompts -> {os.path.relpath(out, ROOT)} ({os.path.getsize(out) // 1024} KB)")

    index_path = os.path.join(ROOT, "data", "index.json")
    index = {"groups": []}
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    group = {
        "id": "paper",
        "title": "GSM8K case study, Qwen2.5-1.5B-Instruct",
        "source": "measured",
        "note": "The five recorded runs behind the paper: 11 rounds, 200 evaluation items, decoding changes at round 4 and the extractor at round 8.",
        "default": next(g["id"] for g in gallery if g["id"].endswith("seed5")),
        "runs": gallery,
    }
    index["groups"] = [group] + [g for g in index.get("groups", []) if g.get("id") != "paper"]
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print(f"{checked:,} labels reproduced from the saved outputs")
    print(f"{written} chunk files, {total_bytes / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
