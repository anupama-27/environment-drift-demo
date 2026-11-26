"""Table 4. Environment-drift inflation at a fixed reference age.

References are stored under E1; the candidate and the rerun reference are scored under
each environment directly, so the environment is the only thing that changes.
"""
from drift import config
from drift.analysis import RunView, age_pairs, mean_sd, summarise
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(4)
views = [RunView(r) for r in get_runs()]
age = config.FIXED_AGE

labels = {"E1": "Unchanged", "E2": "Decoding change", "E3": "Extraction change", "E4": "Multiple changes"}
rows = []
for env_id, label in labels.items():
    sums = [summarise(age_pairs(v, age, force_stored_env="E1", current_env=env_id)) for v in views]
    for v, s in zip(views, sums):
        log.info("seed %d %s: %s", v.run["seed"], env_id, s)
    rows.append((label, age,
                 mean_sd([100 * s["stored_win"] for s in sums]),
                 mean_sd([100 * s["rerun_win"] for s in sums]),
                 mean_sd([100 * s["inflation"] for s in sums])))

write_table(4, "Environment-drift inflation",
            ["Environment condition", "Reference age (rounds)", "Stored-reference win rate (%)",
             "Rerun-reference win rate (%)", "Drift inflation (percentage points)"], rows,
            notes=["Drift inflation = stored-reference win rate − rerun-reference win rate.",
                   f"Each cell averages all candidate/reference pairs {age} rounds apart, then mean ± sd over seeds.",
                   f"The reference is the prompt snapshot from {age} rounds earlier. 'Stored' scores that prompt's E1 outputs from the measurement step (labels kept as recorded, '{config.STORED_SCORING}'); 'rerun' regenerates the same prompt under the current environment in a separate pass. It is not the exact output produced during the trajectory."])

