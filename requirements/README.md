# Dependency groups

The repository deliberately has no single all-backends environment. Install only
the group needed for the route being used:

| File | Purpose |
| --- | --- |
| `common.txt` | pytest execution, timeouts and coverage measurement |
| `workflow.txt` | GitHub Actions routes, including API clients and Pynguin |
| `local-generation.txt` | canonical and generic generators using an external OpenAI-compatible endpoint |
| `mutation.txt` | Cosmic Ray mutation evaluation |
| `analysis.txt` | optional pandas/matplotlib/seaborn result analysis |

For example:

```bash
python -m pip install -r requirements/local-generation.txt
```

The local-generation group supplies the client only. It does not install or configure
vLLM, LM Studio, a model, GPU drivers or model weights. Pynguin is declared in the
workflow group because the public workflow supports Pynguin routes. Cosmic Ray's
process handling is intended for a Unix-like environment; on Windows, use WSL or a
Linux host.

Dependencies are intentionally unpinned where the repository does not establish a
tested compatibility boundary. The removed research-machine freezes were environment
captures, not portable project specifications.
