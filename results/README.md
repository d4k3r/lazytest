# Compact public result evidence

`main_comparisons.csv` contains only the six matched conditions supporting the
headline table in the root README. The rows were selected deterministically from the
private final `run_summary.csv` where `included_in_main=yes` and
`comparison_group=main_baseline_vs_lazytest`. The internal condition identifiers are
retained so each public label remains traceable to its private aggregate row.

This is a compact, report-supporting extract—not the complete per-target experiment
dataset. It does not include generated tests, prompts, raw responses, detailed failure
logs or enough data to reproduce every dissertation analysis independently.

All six conditions use the controlled 1,144-file TheAlgorithms/Python target set.
`final_pass_percentage` is recomputed from the integer passing and target counts and
rounded to two decimal places. `matched_difference_pp` is the difference between the
two displayed, two-decimal percentages in each route, matching the README table.

Validate the public evidence without private data:

```bash
python testing/scripts/verify_public_results.py
```

Coverage, mutation and generation metrics may use different surviving denominators.
The compact CSV supports only the final generation-pass comparison shown in the root
README and should not be used as a universal model leaderboard.
