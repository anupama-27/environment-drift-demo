"""Experiment settings, taken from the Experimental Setup section of the proposal.

Quick pilot overrides (environment variables):
    DRIFT_BACKEND   hf | vllm | mock     (default: hf)
    DRIFT_N_DEV     number of dev items  (default: 200)
    DRIFT_N_EVAL    number of eval items (default: 200)
    DRIFT_ROUNDS    optimisation rounds  (default: 11 -> rounds 0..10)
    DRIFT_SEEDS     comma list           (default: 1,2,3)
    DRIFT_BATCH     generation batch size (default: 64)
    DRIFT_RERUN_ORDER shuffled | stored  (default: shuffled)
"""
import os

MODEL_ID = os.environ.get("DRIFT_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
DATASET_ID = "openai/gsm8k"
DATASET_CONFIG = "main"

BACKEND = os.environ.get("DRIFT_BACKEND", "hf")
N_DEV = int(os.environ.get("DRIFT_N_DEV", 200))
N_EVAL = int(os.environ.get("DRIFT_N_EVAL", 200))
ROUNDS = int(os.environ.get("DRIFT_ROUNDS", 11))
SEEDS = [int(s) for s in os.environ.get("DRIFT_SEEDS", "1,2,3").split(",")]

MAX_NEW_TOKENS = int(os.environ.get("DRIFT_MAX_NEW_TOKENS", 640))
BATCH_SIZE = int(os.environ.get("DRIFT_BATCH", 64))
# Batch order of a "rerun" pass:
#   "shuffled" -> seeded shuffle, so a rerun is an independent pass (E1 row = noise floor)
#   "stored"   -> same item order and batch size as the stored pass (dataset order)
RERUN_ORDER = os.environ.get("DRIFT_RERUN_ORDER", "shuffled")
SAMPLE_TEMPERATURE = 0.2       # alternative decoding (E2, E4)
PROPOSER_TEMPERATURE = 0.7     # used only when writing candidate prompts
N_FAILURES_SHOWN = 4           # dev errors shown to the proposer each round

# Round from which each environment applies (the loop never sees this).
# Rounds 0-3: E1, rounds 4-7: E2 (decoding change), rounds 8+: E4 (decoding + extraction).
ENV_SCHEDULE = {0: "E1", 4: "E2", 8: "E4"}

FIXED_AGE = 3                  # reference age used in Table 4

# How a stored reference is compared later:
#   "as_recorded" -> keep the correct/incorrect labels from when it was stored (an anchor)
#   "rescore"     -> keep the stored text but re-score it with today's extractor
STORED_SCORING = os.environ.get("DRIFT_STORED_SCORING", "as_recorded")

# Baseline P1 reference: "initial" (proposal wording: start of experiment)
# or "last_accepted" (the stored outputs of the last accepted prompt, never rerun)
FROZEN_MODE = os.environ.get("DRIFT_FROZEN_MODE", "initial")

INITIAL_PROMPT = (
    "You are a careful math tutor. Solve the problem step by step. "
    "Put the final answer as a plain number in \\boxed{} on the last line."
)
FORMAT_LINE = "Put the final answer as a plain number in \\boxed{} on the last line."

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(ROOT, "runs")
LOGS_DIR = os.path.join(ROOT, "logs")
RESULTS_DIR = os.path.join(ROOT, "results")
CACHE_PATH = os.environ.get("DRIFT_CACHE", os.path.join(ROOT, "runs", "generations.jsonl"))

