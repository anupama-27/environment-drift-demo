# Statistics quoted in the paper

## Figure 4: drift inflation at reference age 3

| Environment | Mean [95% CI] (pp) | Seeds above zero |
| :- | :- | :- |
| Unchanged | -0.12 [-0.64, +0.39] | 2/5 |
| Decoding | -0.59 [-2.61, +1.43] | 2/5 |
| Extraction | +1.31 [+0.65, +1.98] | 5/5 |
| Combined | +1.54 [+0.04, +3.04] | 4/5 |

- References are stored under E1, as in Table 4 (results/table4.md); the interval is a t-interval over seeds.

## Figure 6: pooled false accepts by reference prompt and stored environment

| Reference prompt | Environment of stored outputs | False accepts / accepts | Rate (%) | Drift inflation (pp) |
| :- | :- | :- | :- | :- |
| Initial prompt | Initial | 13/34 | 38.2 | +1.05 |
| Initial prompt | Previous round | 8/24 | 33.3 | -0.09 |
| Initial prompt | Current | 7/22 | 31.8 | -0.34 |
| Previous incumbent | Initial | 5/16 | 31.2 | -0.45 |
| Previous incumbent | Previous round | 3/17 | 17.6 | -0.39 |
| Previous incumbent | Current | 3/18 | 16.7 | -0.32 |

- Initial prompt with initial environment is the full frozen policy (Table 8, A1); previous incumbent with previous-round environment is Table 8, A4.

## Appendix C: single-factor schedule ablations

| Ablation | Drop in drift inflation (pp, mean ± sd) | p (paired t-test) | Seeds with a drop |
| :- | :- | :- | :- |
| Removing extraction drift | 0.59 ± 0.25 | 0.006 | 5/5 |
| Removing decoding drift | 0.89 ± 1.19 | 0.169 | 4/5 |

## Appendix C: 2×2 factorial over rounds 8–10

| Drift | Effect on drift inflation vs Unchanged (pp) [95% CI] |
| :- | :- |
| Decoding | +1.33 [-1.45, +4.11] |
| Extraction | +1.90 [+1.71, +2.09] |
| Both | +3.50 [+1.56, +5.44] |

- Interaction: +0.27 ± 1.02 pp, p = 0.59 (paired t-test).

## Refresh policies: errors and Fisher tests

| Policy | False accepts | False rejects | Errors / decisions |
| :- | :- | :- | :- |
| Frozen | 13 | 0 | 13/55 |
| Stored incumbent | 0 | 8 | 8/55 |
| Per-batch | 3 | 11 | 14/55 |
| Environment-triggered | 2 | 2 | 4/55 |

- Fisher exact test, environment-triggered vs frozen: p = 0.033
- Fisher exact test, environment-triggered vs per-batch: p = 0.019
- Fisher exact test, environment-triggered vs stored incumbent: p = 0.360
- The test treats every decision as independent, which overstates the evidence.

## Environment-triggered policy vs the best prompt in each pool

| Seed | Final accuracy (%) | Best prompt in pool (%) | Gap (pp) |
| :- | :- | :- | :- |
| 1 | 73.0 | 73.5 | 0.5 |
| 2 | 69.0 | 74.0 | 5.0 |
| 3 | 73.0 | 73.0 | 0.0 |
| 4 | 72.5 | 72.5 | 0.0 |
| 5 | 75.0 | 75.0 | 0.0 |

- Mean gap 1.1 pp; mean final 72.5% vs mean best 73.6%.

## Numbers in the Setup and Evaluation text

| Quantity | Value |
| :- | :- |
| Candidate prompts over 120 words | 9/55 |
| Accuracy, greedy vs sampled at T = 0.2 (strict extractor, all prompts) | 65.8% vs 64.5% |
| Two sampled passes at T = 0.2, mean / max accuracy difference (candidates, E2 and E4) | 2.65 / 8.0 pp |
| Stored greedy labels flipped by the lenient extractor | 638/11400 incorrect→correct, 0 correct→incorrect |
