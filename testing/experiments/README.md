# Preserved research scripts

This directory preserves route-specific and historical scripts from the dissertation
work. They are research artefacts, not a stable command-line interface. Filenames
sometimes reflect an earlier route name rather than the model currently configured in
the preserved snapshot; the map below records the actual constants in this branch.

## Generator route map

| Preserved script | Configured model/tool | Preserved output/run | Status |
| --- | --- | --- | --- |
| `generators/generate_tests_qwen_3.5.py` | `cyankiwi/Qwen3.5-27B-AWQ-4bit` | `qwen_3.5/run_1_repeat` | Earlier AWQ Qwen route; filename is ambiguous. |
| `generators/generate_tests_qwen_3.5_base_prompt.py` | `cyankiwi/Qwen3.5-27B-AWQ-4bit` | `qwen_3.5_cyankiwi/run_2_repeat_base_prompt_long_traceback` | Repeated base-prompt variant. |
| `generators/generate_tests_qwen_3.5_notfixed_mut.py` | `cyankiwi/Qwen3.5-27B-AWQ-4bit` | `qwen_3.5_cyankiwi/run_3_no_repeat_mut_notfixed_long_trace` | Strict mutation-aware variant. |
| `generators/generate_tests_deepseek.py` | `cyankiwi/Qwen3.5-27B-AWQ-4bit` | `qwen_3.5/run_3` | Historical filename; not a DeepSeek model snapshot. |
| `generators/generate_tests_devstral.py` | `cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit` | `devstral/run_3` | Devstral route. |
| `generators/generate_tests_qwen_coder.py` | `cyankiwi/cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `qwen_coder/run_1` | Historical Qwen Coder route; model string contains the preserved duplicated prefix. |
| `generators/generate_tests_rwkv7.py` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `rwkv7/run_1` | Historical filename; configured model is Qwen Coder. |
| `generators/generate_tests_pynguin.py` | Pynguin | `pynguin/run_2` | Search-based evaluation route. |

The public reference implementation remains
`../scripts/generate_tests_qwen_3.5_fixed_mut.py`. Its configuration corresponds to
the Qwen/Qwen3.5-27B softened mutation-aware, no-repeat run-9 snapshot; it should not
be mistaken for the exact run-7 base-prompt condition in the headline comparison.

## Other preserved material

- `analysis/` contains route-specific plotting scripts tied to historical output paths.
- `utilities/` contains operational and CSV helpers that are not part of the canonical
  publication workflow.
- `workflows/local_llm_test.yml` is an early self-hosted local-endpoint smoke test. It
  is intentionally outside `.github/workflows/` and cannot execute as a GitHub Action.

When a canonical public script is refactored, its unmodified research snapshot is
retained here before semantics-affecting changes are made.

## Reference snapshots

`reference-snapshots/` contains the pre-portability research logic for the public
repository-aware generator, generic baseline and branch-coverage recalculator.
Machine-specific path defaults have been normalised for publication. The corresponding
files under `testing/scripts/` retain the research logic but add lazy dependency
loading, explicit paths and safe command-line configuration.
