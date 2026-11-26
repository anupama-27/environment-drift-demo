**Table 5. Ground-truth evaluation of candidate prompts (illustrative subset)**

| Candidate ID | Seed | Round | Environment | Incumbent accuracy (%) | Candidate accuracy (%) | Accuracy change (pp) | Ground-truth outcome |
| :- | :- | :- | :- | :- | :- | :- | :- |
| C1 | 1 | 0 | E1 Unchanged | 68.0 | 59.0 | -9.0 | worse |
| C2 | 1 | 1 | E1 Unchanged | 68.0 | 69.5 | +1.5 | improved |
| C3 | 1 | 2 | E1 Unchanged | 69.5 | 45.5 | -24.0 | worse |
| C4 | 1 | 3 | E1 Unchanged | 69.5 | 69.5 | +0.0 | no change |
| C5 | 1 | 4 | E2 Decoding change | 62.0 | 66.0 | +4.0 | improved |
| C6 | 1 | 5 | E2 Decoding change | 66.0 | 71.0 | +5.0 | improved |
| C7 | 1 | 6 | E2 Decoding change | 71.0 | 71.0 | +0.0 | no change |
| C8 | 1 | 7 | E2 Decoding change | 71.0 | 27.5 | -43.5 | worse |
| C9 | 1 | 8 | E4 Multiple changes | 72.0 | 73.0 | +1.0 | improved |
| C10 | 1 | 9 | E4 Multiple changes | 73.0 | 71.0 | -2.0 | worse |
| C11 | 1 | 10 | E4 Multiple changes | 73.0 | 69.0 | -4.0 | worse |

- One seed of 5, shown in full as an example. The evidence behind Table 6 is all 55 candidates, in results/table5.md.
- Rows are sequential rounds within a seed. The incumbent changes only when a candidate is accepted, so consecutive rows often share one incumbent accuracy.
- It also moves with no accept in 5 rows, where the environment changed and the same prompt was re-measured. Example: on seed 1 the incumbent reads 69.5% at C4 and 62.0% at C5 with no accept in between.
- 'Improved' means strictly higher accuracy, so one extra correct item (0.5 pp) counts. Table 6 calls an accept false when this column is not 'improved'.

