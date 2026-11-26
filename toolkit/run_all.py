"""Run the experiment for every seed, then build Tables 3, 4, 5, 6, 8, 9, and 10.

Usage (Kaggle / A100):
    python run_all.py              # Tables 3, 4, 5, 6, 8, 9, and 10
    python run_all.py 8            # just one of them

The model runs once per seed and every generation is cached in runs/generations.jsonl,
so if the session dies you can rerun the same command and it resumes.
"""
import runpy
import sys

MY_TABLES = [3, 4, 5, 6, 8, 9, 10]
tables = [int(a) for a in sys.argv[1:]] or MY_TABLES
for t in tables:
    print(f"\n===== table{t}.py =====")
    runpy.run_path(f"table{t}.py", run_name="__main__")

