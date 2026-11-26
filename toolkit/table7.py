"""Table 7. Effect of reference age.

Table 4 fixes the reference age and varies the environment; this table varies the age as well.
References are stored under E1 at every age. The Unchanged rows are the proposal's
reference-age control: the candidate and both references are scored under E1. The Changed rows
score the same pairs under E4, so every age can be read with and without drift.

Age a can only use candidates from round a onward, so the rows of the main table do not share a
candidate set. results/table7_trend.md repeats the smaller ages on one fixed set and gives the
per-seed inflation behind every row.
"""
from drift import config
from drift.analysis import RunView, age_row, ci95, mean_sd, sign_count
from drift.pipeline import get_runs
from drift.report import setup, write_table

log = setup(7)
views = [RunView(r) for r in get_runs()]

AGES = (0, 1, 3, 5, 10)
MATCHED_FROM = 5               # candidates from this round on have a reference at every age up to 5
STATUS = {"E1": "Unchanged", "E4": "Changed (decoding + extraction)"}
HEADERS = ["Reference age (optimization rounds)", "Environment status",
           "Candidate/reference pairs", "Stored-reference win rate (%)",
           "Rerun-reference win rate (%)", "Drift inflation (pp)",
           "95% CI of inflation (pp)", "False-accept rate (%)",
           "False-accept rate with rerun reference (%)"]


def rate_with_counts(false_accepts, promoted):
    return f"{100 * false_accepts / promoted:.1f} ({false_accepts}/{promoted})" if promoted \
        else "n/a (0/0)"


def build(ages, min_round=0):
    """One cell per age and environment, dropping ages with no pairs that far apart."""
    cells = {}
    for age in ages:
        for env_id in STATUS:
            r = age_row(views, age, env_id, min_round=min_round)
            log.info("age %d %s from round %d: %s", age, env_id, min_round, r)
            if r["pairs"]:
                cells[(age, env_id)] = r
    return cells


def row(age, env_id, c):
    infl = [100 * x for x in c["inflation"]]
    return (age, STATUS[env_id], c["pairs"],
            mean_sd([100 * x for x in c["stored_win"]]),
            mean_sd([100 * x for x in c["rerun_win"]]),
            mean_sd(infl), ci95(infl),
            rate_with_counts(c["false_accepts"], c["promoted"]),
            rate_with_counts(c["rerun_false_accepts"], c["rerun_promoted"]))


INFLATION_NOTE = (
    "Drift inflation = stored-reference win rate − rerun-reference win rate, computed per "
    "candidate/reference pair, averaged within a seed, then averaged across seeds. Table 4 uses "
    "the same computation at a single age.")

AGE_ZERO_NOTE = (
    "Age 0 means no optimization rounds have elapsed: the reference is the incumbent prompt of "
    "the candidate's own round, so the age-0 Changed row is environment mismatch with no prompt "
    "staleness. Age changes which prompt is the reference, not how long its outputs were stored.")

COMMON_NOTES = [
    "The pairs column is the denominator of the win-rate and inflation columns; the two "
    "false-accept columns are over promotions. Read each interval against zero, not against the "
    "other rows.",
    "A promotion is more wins than losses against the stored reference. It is false when the "
    "candidate's ground-truth accuracy under the current environment is no higher than the "
    "incumbent's at its round, pooled over seeds.",
    "At age 0 Unchanged that rule is identical to the ground-truth check, so 0.0% is arithmetic "
    "rather than a finding, and small ages are pulled down for the same reason. The two "
    "false-accept columns are like-for-like only where the reference is no longer the incumbent.",
    "The last column repeats the rule after re-running the same aged prompt under the current "
    "environment, so it prices a refresh.",
    "Not comparable with Table 6's rates. A row here is a never-refresh rule at one fixed age "
    "over every candidate it can reach, so the matching Table 6 row is frozen reference, 38.2% "
    "(13/34), not environment-triggered refresh, 12.5% (2/16).",
]

cells = build(AGES)
table4_note = (f" The age-{config.FIXED_AGE} rows are Table 4's Unchanged and Multiple changes "
               "rows." if (config.FIXED_AGE, "E1") in cells else "")
write_table(7, "Effect of reference age", HEADERS,
            [row(age, env_id, c) for (age, env_id), c in cells.items()],
            notes=[INFLATION_NOTE, AGE_ZERO_NOTE,
                   "References are stored under E1 at every age (labels kept as recorded, "
                   f"'{config.STORED_SCORING}'). Unchanged re-scores everything under E1 and is "
                   "the noise floor; Changed scores under E4. Both describe the scoring only: the "
                   "candidates came from a trajectory that ran under the E1, E2, E4 schedule."
                   + table4_note,
                   "Higher ages can only use later candidates, so the rows do not share a "
                   "candidate set. results/table7_trend.md repeats ages 0 to "
                   f"{MATCHED_FROM} on one fixed set and tests the age trend seed by seed.",
                   *COMMON_NOTES])

# Mentor ask: show the age trend seed by seed instead of inferring it from the means.
MATCHED_AGES = [a for a in AGES if a <= MATCHED_FROM]
matched = build(MATCHED_AGES, min_round=MATCHED_FROM)
seeds = [v.run["seed"] for v in views]
trend_rows = []
for env_id, status in STATUS.items():
    per_age = {a: [100 * x for x in matched[(a, env_id)]["inflation"]]
               for a in MATCHED_AGES if (a, env_id) in matched}
    for age, infl in per_age.items():
        trend_rows.append((status, age, *[f"{x:+.2f}" for x in infl],
                           mean_sd(infl), ci95(infl), sign_count(infl)))
    if len(per_age) < 2:
        continue       # a short pilot run reaches only one age, so there is nothing to pair
    lo, hi = min(per_age), max(per_age)
    diffs = [h - l for l, h in zip(per_age[lo], per_age[hi])]
    trend_rows.append((status, f"age {hi} − age {lo}, paired", *[f"{x:+.2f}" for x in diffs],
                       mean_sd(diffs), ci95(diffs), sign_count(diffs)))

matched_pairs = next(iter(matched.values()))["pairs"] if matched else 0
write_table(7, "Reference-age trend, seed by seed",
            ["Environment status", "Reference age"] + [f"Seed {s} (pp)" for s in seeds]
            + ["Mean ± sd (pp)", "95% CI (pp)", "Seeds with the mean's sign"],
            trend_rows, suffix="_trend",
            notes=[INFLATION_NOTE,
                   f"Every row uses the same candidates, those proposed from round {MATCHED_FROM} "
                   f"on ({matched_pairs} pairs), so the only thing changing down a block is the "
                   "age of the reference. The main table cannot do this, because higher ages "
                   "there bring in later candidates as well as older references.",
                   "The paired row subtracts each seed's youngest-age inflation from its oldest, "
                   "so a trend that holds within every seed shows up as a column of same-signed "
                   "numbers rather than as a difference of two noisy means.",
                   "Seeds with the mean's sign counts how many seeds agree with the direction of "
                   "their own row. With five seeds a 5/5 column is the strongest evidence this "
                   "design can give that the trend is systematic rather than an artefact of one "
                   "seed."])

