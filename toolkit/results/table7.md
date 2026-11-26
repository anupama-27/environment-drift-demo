**Table 7. Effect of reference age**

| Reference age (optimization rounds) | Environment status | Candidate/reference pairs | Stored-reference win rate (%) | Rerun-reference win rate (%) | Drift inflation (pp) | 95% CI of inflation (pp) | False-accept rate (%) | False-accept rate with rerun reference (%) |
| :- | :- | :- | :- | :- | :- | :- | :- | :- |
| 0 | Unchanged | 55 | 8.03 ± 1.37 | 8.09 ± 1.24 | -0.06 ± 0.22 | [-0.34, +0.21] | 0.0 (0/18) | 11.1 (2/18) |
| 0 | Changed (decoding + extraction) | 55 | 9.79 ± 1.08 | 8.65 ± 0.90 | 1.15 ± 0.74 | [+0.22, +2.07] | 66.7 (18/27) | 40.0 (6/15) |
| 1 | Unchanged | 50 | 8.53 ± 0.91 | 8.56 ± 0.75 | -0.03 ± 0.24 | [-0.32, +0.26] | 25.0 (5/20) | 27.8 (5/18) |
| 1 | Changed (decoding + extraction) | 50 | 9.96 ± 1.05 | 8.78 ± 0.98 | 1.18 ± 0.71 | [+0.30, +2.06] | 64.0 (16/25) | 33.3 (4/12) |
| 3 | Unchanged | 40 | 9.00 ± 1.04 | 9.12 ± 0.76 | -0.12 ± 0.41 | [-0.64, +0.39] | 41.2 (7/17) | 47.4 (9/19) |
| 3 | Changed (decoding + extraction) | 40 | 10.14 ± 1.39 | 8.60 ± 1.61 | 1.54 ± 1.21 | [+0.04, +3.04] | 55.6 (10/18) | 41.7 (5/12) |
| 5 | Unchanged | 30 | 10.03 ± 0.68 | 10.32 ± 1.09 | -0.28 ± 0.66 | [-1.10, +0.53] | 53.3 (8/15) | 56.2 (9/16) |
| 5 | Changed (decoding + extraction) | 30 | 10.60 ± 1.56 | 8.08 ± 1.84 | 2.52 ± 1.30 | [+0.90, +4.14] | 62.5 (10/16) | 45.5 (5/11) |
| 10 | Unchanged | 5 | 11.20 ± 0.91 | 11.60 ± 1.29 | -0.40 ± 0.96 | [-1.59, +0.79] | 75.0 (3/4) | 80.0 (4/5) |
| 10 | Changed (decoding + extraction) | 5 | 12.00 ± 0.79 | 8.50 ± 1.70 | 3.50 ± 1.27 | [+1.92, +5.08] | 80.0 (4/5) | 50.0 (1/2) |

- Drift inflation = stored-reference win rate − rerun-reference win rate, computed per candidate/reference pair, averaged within a seed, then averaged across seeds. Table 4 uses the same computation at a single age.
- Age 0 means no optimization rounds have elapsed: the reference is the incumbent prompt of the candidate's own round, so the age-0 Changed row is environment mismatch with no prompt staleness. Age changes which prompt is the reference, not how long its outputs were stored.
- References are stored under E1 at every age (labels kept as recorded, 'as_recorded'). Unchanged re-scores everything under E1 and is the noise floor; Changed scores under E4. Both describe the scoring only: the candidates came from a trajectory that ran under the E1, E2, E4 schedule. The age-3 rows are Table 4's Unchanged and Multiple changes rows.
- Higher ages can only use later candidates, so the rows do not share a candidate set. results/table7_trend.md repeats ages 0 to 5 on one fixed set and tests the age trend seed by seed.
- The pairs column is the denominator of the win-rate and inflation columns; the two false-accept columns are over promotions. Read each interval against zero, not against the other rows.
- A promotion is more wins than losses against the stored reference. It is false when the candidate's ground-truth accuracy under the current environment is no higher than the incumbent's at its round, pooled over seeds.
- At age 0 Unchanged that rule is identical to the ground-truth check, so 0.0% is arithmetic rather than a finding, and small ages are pulled down for the same reason. The two false-accept columns are like-for-like only where the reference is no longer the incumbent.
- The last column repeats the rule after re-running the same aged prompt under the current environment, so it prices a refresh.
- Not comparable with Table 6's rates. A row here is a never-refresh rule at one fixed age over every candidate it can reach, so the matching Table 6 row is frozen reference, 38.2% (13/34), not environment-triggered refresh, 12.5% (2/16).

