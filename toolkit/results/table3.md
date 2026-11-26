**Table 3. Main comparison of reference-refresh policies**

| Policy | Reference refresh rule | Ground-truth accuracy (%) ↑ | False-accept rate (%) ↓ | Model calls (logical, estimated) ↓ | Reference refreshes ↓ |
| :- | :- | :- | :- | :- | :- |
| P1: Frozen reference | Never refresh | 70.80 ± 2.02 | 35.71 ± 22.59 | 4411 ± 0 | 0 ± 0 |
| P2: Per-batch refresh | Refresh every batch | 69.70 ± 2.17 | 20.00 ± 20.92 | 6611 ± 0 | 11 ± 0 |
| P3: Environment-triggered refresh | Refresh after detected environment changes | 72.50 ± 2.18 | 13.33 ± 18.26 | 4811 ± 0 | 2 ± 0 |

- Ground-truth accuracy = final incumbent under the final environment.
- Model calls are logical (estimated) counts: simulate() is a dry run, so it adds up the proposals, dev passes, candidate evaluations and refreshes each policy would need.
- The policies are reference-management rules compared on the same candidate pool, not different ways of improving accuracy; accuracy is capped by the best candidate in the pool.
- Policies replay the same candidate pool in dry-run mode.

