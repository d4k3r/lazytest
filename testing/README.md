# Local evaluation workspace

The dissertation evaluation used a separate checkout of TheAlgorithms/Python. Target
repositories and generated outputs are intentionally excluded from the public source
tree.

Clone the evaluation repository outside this repository, or into the ignored local
workspace, and pass its path explicitly to the canonical scripts:

```bash
git clone https://github.com/TheAlgorithms/Python.git /path/to/TheAlgorithms
```

The final dissertation does not identify a specific TheAlgorithms commit hash, so
this repository does not invent one. For a new run, record the selected checkout's
commit with:

```bash
git -C /path/to/TheAlgorithms rev-parse HEAD
```

Generated tests, prompts, raw responses, metrics and detailed failure logs belong in
an ignored local output directory. Only the compact matched-comparison evidence in
`../results/` is intended for publication.
