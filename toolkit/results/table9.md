**Table 9. Reproducibility across random seeds**

| Seed | Refresh policy | Final incumbent | Ground-truth accuracy (%) | Drift inflation (pp) | False accepts / accepted | False-accept rate (%) | Model calls |
| :- | :- | :- | :- | :- | :- | :- | :- |
| 1 | P1 | C11 | 69.0 | -1.09 | 4/7 | 57.1 | 4411 |
| 1 | P2 | C5 | 67.0 | 0.00 | 0/2 | 0.0 | 6611 |
| 1 | P3 | C9 | 73.0 | -0.95 | 0/4 | 0.0 | 4811 |
| 2 | P1 | C11 | 71.0 | 3.45 | 3/7 | 42.9 | 4411 |
| 2 | P2 | C1 | 69.0 | 0.00 | 0/1 | 0.0 | 6611 |
| 2 | P3 | C1 | 69.0 | 0.23 | 0/1 | 0.0 | 4811 |
| 3 | P1 | C11 | 73.0 | 0.86 | 2/7 | 28.6 | 4411 |
| 3 | P2 | C11 | 73.0 | 0.00 | 1/4 | 25.0 | 6611 |
| 3 | P3 | C11 | 73.0 | -0.50 | 1/3 | 33.3 | 4811 |
| 4 | P1 | C11 | 72.5 | 0.55 | 0/5 | 0.0 | 4411 |
| 4 | P2 | C9 | 70.0 | 0.00 | 1/4 | 25.0 | 6611 |
| 4 | P3 | C11 | 72.5 | -0.82 | 0/5 | 0.0 | 4811 |
| 5 | P1 | C11 | 68.5 | 1.50 | 4/8 | 50.0 | 4411 |
| 5 | P2 | C7 | 69.5 | 0.00 | 1/2 | 50.0 | 6611 |
| 5 | P3 | C8 | 75.0 | 0.09 | 1/3 | 33.3 | 4811 |
| Mean ± standard deviation | P1 | — | 70.8 ± 2.0 | 1.05 ± 1.65 | 2.6 ± 1.7 / 6.8 ± 1.1 | 35.7 ± 22.6 | 4411 ± 0 |
| Mean ± standard deviation | P2 | — | 69.7 ± 2.2 | 0.00 ± 0.00 | 0.6 ± 0.5 / 2.6 ± 1.3 | 20.0 ± 20.9 | 6611 ± 0 |
| Mean ± standard deviation | P3 | — | 72.5 ± 2.2 | -0.39 ± 0.53 | 0.4 ± 0.5 / 3.2 ± 1.5 | 13.3 ± 18.3 | 4811 ± 0 |
| Pooled (5 seeds, 55 evals) | P1 | — | — | — | 13/34 | 38.2 | 22055 |
| Pooled (5 seeds, 55 evals) | P2 | — | — | — | 3/13 | 23.1 | 33055 |
| Pooled (5 seeds, 55 evals) | P3 | — | — | — | 2/16 | 12.5 | 24055 |

- Seed controls the proposer's dev-error sampling and the temperature-0.2 evaluation decoding.
- Auditable denominators: 'False accepts / accepted' reports x/y for every seed/policy (out of 11 evaluated candidates per seed), followed by both the unweighted per-seed Mean ± standard deviation (matching Table 3) and the Pooled rate across all seeds (matching Table 6).
- Why P2 has 0.00 pp drift inflation yet nonzero false accepts: P2 refreshes the stored reference under the current environment before every comparison (ref_lab == rerun), making stored-minus-rerun inflation 0 by policy design rather than independent evidence that drift is absent. A nonzero P2 false-accept rate remains possible because paired promotion compares the candidate's primary evaluation pass ('current') against the incumbent's fresh pass ('rerun'), whereas ground-truth accuracy is scored on the canonical 'current' record.
- Why final ground-truth accuracy varies across P1/P2/P3 on a shared candidate pool: all three policies replay the exact same 11 candidates per seed, but each policy updates its running incumbent only when its own gate accepts (wins > losses). The 'Final incumbent' column reports the last candidate accepted by that policy in rounds 0–10, scored under the final environment E4.
- The 5-seed run (Seeds 1–5) is the primary reproducibility table; the 3-seed subset (table9_seeds1-3.md) is retained as a legacy/sensitivity analysis at the same post-fix code revision.

