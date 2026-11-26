**Table 10. End-to-end reproducible backend demonstration trace (Seed 1, Rounds 0–10 across P1, P2, P3)**

| Round | Candidate | Active env | Candidate GT acc (%) | P1 drift inflation vs rerun (pp) | P1 (Frozen ref) decision | P2 (Per-batch refresh) decision | P3 (Env-triggered refresh) decision |
| :- | :- | :- | :- | :- | :- | :- | :- |
| 0 | C1 | E1 | 59.0% | -1.00 | ref=h0(E1,stored): W25/L43 -> reject (vs h0: -9.0pp, inc=h0) | ref=h0(E1,fresh): W27/L42 -> reject (vs h0: -9.0pp, inc=h0) | ref=h0(E1,stored): W25/L43 -> reject (vs h0: -9.0pp, inc=h0) |
| 1 | C2 | E1 | 69.5% | -0.50 | ref=h0(E1,stored): W26/L23 -> ACCEPT (vs h0: +1.5pp, inc=C2) | ref=h0(E1,fresh): W27/L21 -> ACCEPT (vs h0: +1.5pp, inc=C2) | ref=h0(E1,stored): W26/L23 -> ACCEPT (vs h0: +1.5pp, inc=C2) |
| 2 | C3 | E1 | 45.5% | +0.00 | ref=h0(E1,stored): W14/L59 -> reject (vs C2: -24.0pp, inc=C2) | ref=C2(E1,fresh): W14/L62 -> reject (vs C2: -24.0pp, inc=C2) | ref=C2(E1,stored): W14/L62 -> reject (vs C2: -24.0pp, inc=C2) |
| 3 | C4 | E1 | 69.5% | -1.00 | ref=h0(E1,stored): W22/L19 -> FALSE ACCEPT (vs C2: +0.0pp, inc=C4) | ref=C2(E1,fresh): W25/L25 -> reject (vs C2: +0.0pp, inc=C2) | ref=C2(E1,stored): W25/L25 -> reject (vs C2: +0.0pp, inc=C2) |
| 4 | C5 | E2 | 66.0% | -3.50 | ref=h0(E1,stored): W22/L26 -> reject (vs C4: -4.5pp, inc=C4) | ref=C2(E2,fresh): W28/L23 -> ACCEPT (vs C2: +4.0pp, inc=C5) | ref=C2(E2,fresh): W28/L23 -> ACCEPT (vs C2: +4.0pp, inc=C5) |
| 5 | C6 | E2 | 71.0% | -3.00 | ref=h0(E1,stored): W25/L19 -> ACCEPT (vs C4: +0.5pp, inc=C6) | ref=C5(E2,fresh): W14/L19 -> false reject (vs C5: +5.0pp, inc=C5) | ref=C5(E2,stored): W17/L7 -> ACCEPT (vs C5: +5.0pp, inc=C6) |
| 6 | C7 | E2 | 71.0% | -3.00 | ref=h0(E1,stored): W25/L19 -> FALSE ACCEPT (vs C6: +0.0pp, inc=C7) | ref=C5(E2,fresh): W14/L19 -> false reject (vs C5: +5.0pp, inc=C5) | ref=C6(E2,stored): W0/L0 -> reject (vs C6: +0.0pp, inc=C6) |
| 7 | C8 | E2 | 27.5% | -1.50 | ref=h0(E1,stored): W7/L88 -> reject (vs C7: -43.5pp, inc=C7) | ref=C5(E2,fresh): W12/L104 -> reject (vs C5: -38.5pp, inc=C5) | ref=C6(E2,stored): W10/L97 -> reject (vs C6: -43.5pp, inc=C6) |
| 8 | C9 | E4 | 73.0% | +0.50 | ref=h0(E1,stored): W27/L17 -> ACCEPT (vs C7: +1.0pp, inc=C9) | ref=C5(E4,fresh): W16/L19 -> false reject (vs C5: +6.0pp, inc=C5) | ref=C6(E4,fresh): W20/L18 -> ACCEPT (vs C6: +1.0pp, inc=C9) |
| 9 | C10 | E4 | 71.0% | -0.50 | ref=h0(E1,stored): W24/L18 -> FALSE ACCEPT (vs C9: -2.0pp, inc=C10) | ref=C5(E4,fresh): W15/L22 -> false reject (vs C5: +4.0pp, inc=C5) | ref=C9(E4,stored): W13/L17 -> reject (vs C9: -2.0pp, inc=C9) |
| 10 | C11 | E4 | 69.0% | +1.50 | ref=h0(E1,stored): W24/L22 -> FALSE ACCEPT (vs C10: -2.0pp, inc=C11) | ref=C5(E4,fresh): W13/L24 -> false reject (vs C5: +2.0pp, inc=C5) | ref=C9(E4,stored): W14/L22 -> reject (vs C9: -4.0pp, inc=C9) |

- Reproducible with: DRIFT_SEEDS=1,2,3,4,5 python table10.py (and python -m unittest tests.test_demo_backend -v).
- Traces all 11 rounds of Seed 1 across environment shifts E1 (r0–3) -> E2 (r4–7) -> E4 (r8–10).
- Demonstrates how P1 accumulates 4 false accepts (C4, C7, C10, C11) and ends at 69.0% GT accuracy, P2 avoids late false accepts but suffers 5 false rejects (ending on C5 at 67.0% in 6,611 calls), and P3 refreshes only at the r=4 (E1->E2) and r=8 (E2->E4) transitions to finish on C9 at 73.0% GT accuracy with 0 false accepts in 4,811 calls.
