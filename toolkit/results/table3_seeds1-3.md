**Table 3. Main comparison of reference-refresh policies**

| Policy | Reference refresh rule | Ground-truth accuracy (%) ↑ | False-accept rate (%) ↓ | Model calls ↓ | Reference refreshes ↓ |
| :- | :- | :- | :- | :- | :- |
| P1: Frozen reference | Never refresh | 71.00 ± 2.00 | 42.86 ± 14.29 | 4411 ± 0 | 0 ± 0 |
| P2: Per-batch refresh | Refresh every batch | 69.67 ± 3.06 | 8.33 ± 14.43 | 6611 ± 0 | 11 ± 0 |
| P3: Environment-triggered refresh | Refresh after detected environment changes | 71.67 ± 2.31 | 11.11 ± 19.25 | 4811 ± 0 | 2 ± 0 |

- Ground-truth accuracy = final incumbent under the final environment.
- Model calls are logical calls (proposer + dev pass + candidate eval + refreshes).
- Policies replay the same candidate pool in dry-run mode.

