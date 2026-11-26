**Table 6. Decision errors in both directions**

| Policy | Evaluated | Accepted | False accepts | False-accept rate (%) | False rejects | False-reject rate (%) | Total error rate (%) | False-accept rate, per-seed mean ± sd (%) |
| :- | :- | :- | :- | :- | :- | :- | :- | :- |
| P1: Frozen reference | 55 | 34 | 13 | 38.2 | 0 | 0.0 | 23.6 | 35.7 ± 22.6 |
| P2: Per-batch refresh | 55 | 13 | 3 | 23.1 | 11 | 26.2 | 25.5 | 20.0 ± 20.9 |
| P3: Environment-triggered refresh | 55 | 16 | 2 | 12.5 | 2 | 5.1 | 7.3 | 13.3 ± 18.3 |

- False reject = a candidate with strictly higher ground-truth accuracy that the gate turned down; the rate is over rejected candidates.
- Total error rate is over all candidates evaluated, so the two directions are comparable on one denominator.
- A policy can lower its false-accept rate simply by accepting less, so the false-reject column is needed to tell caution apart from accuracy.
