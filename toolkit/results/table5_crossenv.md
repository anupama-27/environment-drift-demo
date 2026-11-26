**Table 5. The same candidates judged under every environment**

| Environment | ID | Candidates | Improved | No change | Worse | Improved (%) | Mean accuracy change (pp) |
| :- | :- | :- | :- | :- | :- | :- | :- |
| Unchanged | E1 | 55 | 18 | 5 | 32 | 32.7 | -4.9 |
| Decoding change | E2 | 55 | 13 | 5 | 37 | 23.6 | -5.2 |
| Extraction change | E3 | 55 | 16 | 8 | 31 | 29.1 | -1.1 |
| Multiple changes | E4 | 55 | 16 | 9 | 30 | 29.1 | -1.3 |

- Every row scores all 55 candidates against their own incumbent, so the pool is identical across rows and the environment is the only thing that changes.
- 31 of 55 candidates (56.4%) get a different verdict under E1 than under E4. That disagreement is what Table 6 turns into a false-accept rate.
- E1 and E3 differ only in the answer extractor, and 18 of 55 candidates (32.7%) still change verdict between them. The widest is seed 1 C1: -9.0 pp under E1 and +4.0 pp under E3, same prompt and same responses. Reading the answer out of an unchanged response is enough to flip a promotion decision, which is why the parser audit in Table 2 matters for every number downstream.
- Unlike the main table, these columns are not a restatement of the gate's wins and losses, because the gate only ever saw the environment in force at the round.
