**Table 6. False-accept analysis**

| Refresh policy | Candidates evaluated | Candidates accepted | Accepted candidates with no ground-truth improvement | False-accept rate, pooled (%) | False-accept rate, per-seed mean ± sd (%) | 95% CI of the seed-mean (pp) |
| :- | :- | :- | :- | :- | :- | :- |
| Frozen reference | 55 | 34 | 13 | 38.2 | 35.7 ± 22.6 | [+7.7, +63.8] |
| Per-batch refresh | 55 | 13 | 3 | 23.1 | 20.0 ± 20.9 | [-6.0, +46.0] |
| Environment-triggered refresh | 55 | 16 | 2 | 12.5 | 13.3 ± 18.3 | [-9.3, +36.0] |

- False-accept rate = accepted candidates whose ground-truth accuracy is no greater than the incumbent's, divided by all accepted candidates. The candidate pool is identical across policies, so evaluated is 55 in every row.
- Pooled sums the counts across seeds; the seed-mean averages the five per-seed rates and is the figure Table 3 reports. For environment-triggered refresh these are 2/16 = 12.5% and 13.3 ± 18.3, because a seed with one accept weighs the same as a seed with five in the average but not in the pool.
- False accepts / accepts per seed (1, 2, 3, 4, 5): frozen reference 4/7, 3/7, 2/7, 0/5, 4/8; per-batch refresh 0/2, 0/1, 1/4, 1/4, 1/2; environment-triggered refresh 0/4, 0/1, 1/3, 0/5, 1/3.
- Denominators are small: reclassifying one accept moves environment-triggered refresh by 6.2 pp, and the intervals overlap, so the ordering is a direction rather than an established gap.
- Table 7's stale-reference, changed-environment rate covers a subset of these accepts, not the same quantity.
- A policy lowers this rate by accepting less; results/table6_errors.md adds the improvements each one rejected.

