"""Shared logging and table output for tableN.py scripts."""
import logging
import os
import sys

from . import config


def setup(table_no):
    os.makedirs(config.LOGS_DIR, exist_ok=True)
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    log_path = os.path.join(config.LOGS_DIR, f"table{table_no}.log")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(log_path, mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        root.addHandler(h)
    log = logging.getLogger(f"table{table_no}")
    log.info("backend=%s model=%s n_dev=%d n_eval=%d rounds=%d seeds=%s schedule=%s",
             config.BACKEND, config.MODEL_ID, config.N_DEV, config.N_EVAL, config.ROUNDS,
             config.SEEDS, config.ENV_SCHEDULE)
    if config.BACKEND == "mock":
        log.warning("MOCK BACKEND: numbers are fake and only test the code path.")
    return log


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}"


def write_table(table_no, title, headers, rows, notes=(), suffix=""):
    lines = [f"**Table {table_no}. {title}**", "",
             "| " + " | ".join(headers) + " |",
             "| " + " | ".join(":-" for _ in headers) + " |"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    if notes:
        lines.append("")
        lines += [f"- {n}" for n in notes]
    text = "\n".join(lines) + "\n"
    path = os.path.join(config.RESULTS_DIR, f"table{table_no}{suffix}.md")
    with open(path, "w") as f:
        f.write(text)
    log = logging.getLogger(f"table{table_no}")
    log.info("Result table written to %s\n%s", os.path.relpath(path, config.ROOT), text)
    return text

