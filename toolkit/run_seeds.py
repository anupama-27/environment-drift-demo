"""Run the GPU part of the experiment for some seeds only (no tables).

Used to split seeds across GPUs, e.g. on a Kaggle T4 x2 machine:
    CUDA_VISIBLE_DEVICES=0 DRIFT_CACHE=runs/cache_gpu0.jsonl python run_seeds.py 1 3 &
    CUDA_VISIBLE_DEVICES=1 DRIFT_CACHE=runs/cache_gpu1.jsonl python run_seeds.py 2
Then `python run_all.py` builds the tables from the saved runs without touching the GPU.
"""
import logging
import sys

from drift.pipeline import get_runs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
seeds = [int(a) for a in sys.argv[1:]]
get_runs(seeds)

