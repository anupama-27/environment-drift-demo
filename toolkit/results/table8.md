**Table 8. Ablation study**

| Ablation | Round schedule (0–3 / 4–7 / 8–10) | Decoding changes enabled | Extraction changes enabled | Reference-age variation enabled | Drift inflation (pp) | False-accept rate, mean ± sd (%) | Pooled false accepts / accepted (%) |
| :- | :- | :- | :- | :- | :- | :- | :- |
| A1: Full system | E1 -> E2 -> E4 | yes (T=0.2 in r4–10) | yes (v2 in r8–10) | yes (ref=r0, age k) | 1.05 ± 1.65 | 35.71 ± 22.59 | 13/34 (38.2%) |
| A2: No decoding changes | E1 -> E1 -> E3 | no (T=0.0 fixed) | yes (v2 in r8–10) | yes (ref=r0, age k) | 0.16 ± 0.84 | 48.61 ± 8.36 | 18/37 (48.6%) |
| A3: No extraction changes | E1 -> E2 -> E2 | yes (T=0.2 in r4–10) | no (v1 fixed) | yes (ref=r0, age k) | 0.46 ± 1.86 | 39.24 ± 12.74 | 12/30 (40.0%) |
| A4: Fixed reference age | E1 -> E2 -> E4 | yes (T=0.2 in r4–10) | yes (v2 in r8–10) | no (ref=r(k-1), age 1) | -0.39 ± 0.89 | 18.33 ± 17.08 | 3/17 (17.6%) |

- Controlled single-factor design over 5 seeds (55 candidate evaluations): all rows replay the exact same candidate prompts, seeds, 200 GSM8K evaluation items, and frozen-reference promotion rule (P1: accept iff wins > losses).
- Explicit schedule mapping: E1 = (temp=0.0, v1_strict), E2 = (temp=0.2, v1_strict), E3 = (temp=0.0, v2_lenient), E4 = (temp=0.2, v2_lenient). A2 differs from A1 only by disabling the temp=0.0->0.2 shift in rounds 4–10 (E2->E1, E4->E3); A3 differs from A1 only by disabling the v1->v2 extractor shift in rounds 8–10 (E3->E1, E4->E2).
- Descriptive schedule pattern vs. factorial contrast: across the 11-round schedule, A2 activates E3 in only 3/11 rounds (r8–10) while A3 activates E2 in 7/11 rounds (r4–10). Paired seed-level inflation differences are A1 - A2 = 0.89 ± 1.19 pp and A1 - A3 = 0.59 ± 0.25 pp; on a balanced 2x2 factorial evaluation across all 4 environments, the interaction contrast (E4 - E2) - (E3 - E1) is 0.27 ± 1.02 pp on rounds 8–10 and 0.34 ± 0.83 pp across all 11 rounds (approximately additive).
- Both unweighted per-seed mean ± sd (%) and pooled counts (false accepts / accepted candidates across all seeds) are reported because per-seed accepted denominators are small (2 to 9 accepted candidates per seed).
- A4 (fixed_age=1) compares round k against snapshots[max(0, k-1)] stored under env_at(k-1). Because environment shifts occur only at rounds 4 and 8, A4 compares matched environments (ref_env == cur_env) on 9/11 rounds and cross-environment outputs on only 2/11 boundary rounds (k=4, 8), while also updating the reference prompt to the round-(k-1) snapshot (holding the prompt fixed at h0 with env_at(k-1) yields -0.09 ± 0.94 pp inflation and 8/24 = 33.3% pooled false accepts).
