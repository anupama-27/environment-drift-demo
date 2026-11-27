# Independent ground-truth scorer (Table 5, Appendix D)

The code and data behind Table 5 (independent scorer) and the scorer checks in Appendix D. It was built on Oct 24, 2026. The files are as they were when the numbers were produced; the only change is that the scripts now find `drift/` and `runs/` relative to this folder instead of through a hard-coded local path. Re-running them reproduces the committed outputs.

## Where each number comes from

| Paper | Number | File |
|---|---|---|
| Table 5 | false accepts 17/34 (P1), 4/13 (P2), 4/16 (P3) | `gt_tables_output.txt`, section (iii), "[drift schedule] GT=gt" |
| Table 5 | final accuracy 70.6 / 69.7 / 72.3 | same section |
| Appendix D | 3.3% of 123: last-number fallback credits by coincidence (4/123) | `audit_results.txt`, part (a) |
| Appendix D | 81% of 198: gt scorer agrees with the audit labels (161/198) | `audit_results.txt`, last lines |
| Appendix D | 27/28: blind human spot-check of the audit labels | `spot-check-mandar.xlsx` (sheet 1 = human calls, sheet 2 = AI labels) |

The audit labels in `labels_a.py` / `labels_b.py` were written by an AI annotator. A human then blind-checked 29 of them and agreed on 27 of the 28 definite calls. Appendix D should say this.

## Files

- `gt_scorer.py`: the scorer, frozen. `gt_scorer.sha256` holds its hash.
- `test_gt_scorer.py`: 60 tests.
- `rescore.py`: re-scores every decoded output with v1, v2 and gt. Writes `gt_scores.csv` and `gt_labels.json`.
- `gt_tables.py`: replays Tables 3 and 4 with gt labels. Writes `gt_tables_output.txt` and `acc_per_prompt.csv`.
- `draw_audit_sample.py`: draws the audit samples. Writes `audit_sample_{a,b}.csv` and `audit_dump_{a,b}.txt`; the blind versions without labels are `blind_dump_{a,b}.txt`.
- `labels_a.py`, `labels_b.py`, `score_audit.py`: the audit labels and scoring. Writes `audit_labels_{a,b}.csv` and `audit_results.txt`.
- `make_spotcheck.py`: builds the blind spot-check workbook, `spot-check.xlsx`.
- `mathverify_crosscheck.py`: cross-check against math-verify (`mathverify_disagreements.csv`).

## Input

`all_outputs.csv` from Nischae's `parser_audit_outputs.zip` (65 MB, not committed). `rescore.py`, `draw_audit_sample.py` and `mathverify_crosscheck.py` take the directory that holds it as their first argument.

## Running

`rescore.py`, `gt_tables.py` and one test in `test_gt_scorer.py` import `drift/` and read `runs/` from the `toolkit/` folder above this one. Run them from `toolkit/gt_audit/`.

```
python rescore.py <dir with all_outputs.csv>
python gt_tables.py
python draw_audit_sample.py <dir with all_outputs.csv>
python score_audit.py
python -m pytest test_gt_scorer.py
```
