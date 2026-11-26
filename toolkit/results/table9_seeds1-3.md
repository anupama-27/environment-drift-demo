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
| Mean ± standard deviation | P1 | — | 71.0 ± 2.0 | 1.08 ± 2.28 | 3.0 ± 1.0 / 7.0 ± 0.0 | 42.9 ± 14.3 | 4411 ± 0 |
| Mean ± standard deviation | P2 | — | 69.7 ± 3.1 | 0.00 ± 0.00 | 0.3 ± 0.6 / 2.3 ± 1.5 | 8.3 ± 14.4 | 6611 ± 0 |
| Mean ± standard deviation | P3 | — | 71.7 ± 2.3 | -0.41 ± 0.60 | 0.3 ± 0.6 / 2.7 ± 1.5 | 11.1 ± 19.2 | 4811 ± 0 |
| Pooled (3 seeds, 33 evals) | P1 | — | — | — | 9/21 | 42.9 | 13233 |
| Pooled (3 seeds, 33 evals) | P2 | — | — | — | 1/7 | 14.3 | 19833 |
| Pooled (3 seeds, 33 evals) | P3 | — | — | — | 1/8 | 12.5 | 14433 |

- Seed controls the proposer's dev-error sampling and the temperature-0.2 evaluation decoding.
- Auditable denominators: 'False accepts / accepted' reports x/y for every seed/policy (out of 11 evaluated candidates per seed), followed by both the unweighted per-seed Mean ± standard deviation (matching Table 3) and the Pooled rate across all seeds (matching Table 6).
- Why P2 has 0.00 pp drift inflation yet nonzero false accepts: P2 refreshes the stored reference under the current environment before every comparison (ref_lab == rerun), making stored-minus-rerun inflation 0 by policy design rather than independent evidence that drift is absent. A nonzero P2 false-accept rate remains possible because paired promotion compares the candidate's primary evaluation pass ('current') against the incumbent's fresh pass ('rerun'), whereas ground-truth accuracy is scored on the canonical 'current' record.
- Why final ground-truth accuracy varies across P1/P2/P3 on a shared candidate pool: all three policies replay the exact same 11 candidates per seed, but each policy updates its running incumbent only when its own gate accepts (wins > losses). The 'Final incumbent' column reports the last candidate accepted by that policy in rounds 0–10, scored under the final environment E4.
- The 5-seed run (Seeds 1–5) is the primary reproducibility table; the 3-seed subset (table9_seeds1-3.md) is retained as a legacy/sensitivity analysis at the same post-fix code revision.

