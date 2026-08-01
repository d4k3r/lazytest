# Reproducibility note

LazyTest's reported evidence comes from a controlled TheAlgorithms/Python case study
with a fixed 1,144-file target set after technical filtering. The final dissertation
does not identify a specific TheAlgorithms commit hash, so this repository does not
invent one. Select and record an upstream revision before starting a new run; results
from a different revision are not automatically comparable with the dissertation.

Clone the evaluation repository outside the public Git tree, for example:

```bash
git clone https://github.com/TheAlgorithms/Python.git testing/repos_for_testing/TheAlgorithms
git -C testing/repos_for_testing/TheAlgorithms rev-parse HEAD
```

Install only the environment needed for the selected route. The dependency groups
are documented in [`../requirements/README.md`](../requirements/README.md). Inspect
the canonical command-line interfaces without contacting a model:

```bash
python testing/scripts/generate_tests_qwen_3.5_fixed_mut.py --help
python testing/scripts/generate_baseline.py --help
python testing/scripts/recalc_branch_coverage.py --help
python testing/scripts/mutation_score.py --help
```

The canonical generator does not create `__init__.py` files in the target checkout
unless `--normalise-packages` is explicitly selected. Use that option only with a
disposable copy. Generated tests, prompts, raw responses, detailed failure logs and
complete run directories remain private and ignored.

The compact public result evidence can be verified without the private per-target
dataset:

```bash
python testing/scripts/verify_public_results.py
```

That check supports the six-row headline generation comparison only. It does not
reproduce every coverage, mutation, prompt-variant or secondary-route analysis.
Generation, coverage and mutation summaries can also use different surviving
denominators; consult the dissertation methodology before comparing them.
