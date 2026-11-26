**Table 4. Environment-drift inflation**

| Environment condition | Reference age (rounds) | Stored-reference win rate (%) | Rerun-reference win rate (%) | Drift inflation (percentage points) |
| :- | :- | :- | :- | :- |
| Unchanged | 3 | 9.00 ± 1.04 | 9.12 ± 0.76 | -0.13 ± 0.41 |
| Decoding change | 3 | 9.14 ± 0.93 | 9.72 ± 2.05 | -0.59 ± 1.63 |
| Extraction change | 3 | 10.03 ± 1.08 | 8.71 ± 1.04 | 1.31 ± 0.53 |
| Multiple changes | 3 | 10.14 ± 1.39 | 8.60 ± 1.61 | 1.54 ± 1.21 |

- Drift inflation = stored-reference win rate − rerun-reference win rate.
- Each cell averages all candidate/reference pairs 3 rounds apart, then mean ± sd over seeds.
- The reference is the prompt snapshot from 3 rounds earlier. 'Stored' scores that prompt's E1 outputs from the measurement step (labels kept as recorded, 'as_recorded'); 'rerun' regenerates the same prompt under the current environment in a separate pass. It is not the exact output produced during the trajectory.

