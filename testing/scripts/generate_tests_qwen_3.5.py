#!/usr/bin/env python3
# ==============================================================================
# The full source code of the project, including **detailed comments** and
# commit history, is available in the public GitHub repository:
# https://github.com/d4k3r/lazytest
# ==============================================================================

"""
generate_llm_tests.py

Pipeline: generate tests for Python files using Local LLM (vLLM/LM Studio).
"""

import os
import re
import time
import ast
import csv
import sys
import subprocess
import json
import types
import importlib.util
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

##### CONFIGURATION #####
MAX_WORKERS = 8

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
REPOS = [str(PROJECT_ROOT / "testing" / "repos_for_testing" / "TheAlgorithms")]
OUT_DIR = str(PROJECT_ROOT / "testing" / "generated_tests" / "qwen_3.5" / "run_1_repeat")
METRICS_CSV = os.path.join(OUT_DIR, "metrics_qwen_coder_TheAlgorithms.csv")

##### LLM CONFIGURATION #####
API_BASE_URL = "http://localhost:8000/v1"
MODEL_NAME = "cyankiwi/Qwen3.5-27B-AWQ-4bit"

client = OpenAI(base_url=API_BASE_URL, api_key="not-needed")

# Лок для безопасной записи логов из нескольких потоков
_log_lock = threading.Lock()


def find_py_files(repo_path):
    py_files = []
    for root, dirs, files in os.walk(repo_path):
        skip = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'build', 'dist', 'docs', 'setup.py'}
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f == "__init__.py" or not f.endswith(".py"):
                continue
            full = os.path.join(root, f)
            norm = full.replace("\\", os.path.sep)
            if os.path.sep + "tests" + os.path.sep in norm:
                continue
            py_files.append(full)
    return sorted(py_files)


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def ensure_init_files_in_repo(repo_path):
    for root, dirs, files in os.walk(repo_path):
        if any(part.startswith('.') or part in ('venv', '__pycache__', 'node_modules') for part in root.split(os.sep)):
            continue
        init_file = os.path.join(root, "__init__.py")
        if not os.path.exists(init_file):
            try:
                with open(init_file, 'w') as f:
                    pass
            except Exception:
                pass


def strip_llm_imports(code: str) -> str:
    lines = code.splitlines()
    cleaned = []
    skip_next_blank = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            skip_next_blank = True
            continue
        if skip_next_blank and stripped == "":
            skip_next_blank = False
            continue
        skip_next_blank = False
        cleaned.append(line)
    return "\n".join(cleaned)


def build_preamble(repo_path: str, src_path: str, module_name: str) -> str:
    parts = module_name.split(".")
    package_name = ".".join(parts[:-1])

    lines = [
        "import sys, os, types, importlib.util",
        "import pytest",
        "import math, base64, string, re, collections, itertools",
        "import io",
        "from io import StringIO",
        "from contextlib import redirect_stdout, redirect_stderr",
        "from unittest.mock import MagicMock, patch, Mock",
        "",
        f"_REPO = r'{repo_path}'",
        "if _REPO not in sys.path:",
        "    sys.path.insert(0, _REPO)",
        "",
    ]

    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        pkg_path = os.path.join(repo_path, *parts[:i]).replace('\\', '/')
        lines += [
            f"if '{pkg}' in sys.modules:",
            f"    _file = getattr(sys.modules['{pkg}'], '__file__', '')",
            f"    if _file and 'generated_tests' in _file:",
            f"        del sys.modules['{pkg}']",

            f"if '{pkg}' not in sys.modules:",
            f"    _pkg = types.ModuleType('{pkg}')",
            f"    _pkg.__path__ = [r'{pkg_path}']",
            f"    _pkg.__package__ = '{pkg}'",
            f"    sys.modules['{pkg}'] = _pkg",
            f"else:",
            f"    if hasattr(sys.modules['{pkg}'], '__path__') and r'{pkg_path}' not in sys.modules['{pkg}'].__path__:",
            f"        sys.modules['{pkg}'].__path__.insert(0, r'{pkg_path}')"
        ]

    lines += [
        "",
        f"for _key in ['{module_name}', 'target_module', '{parts[-1]}']:",
        f"    sys.modules.pop(_key, None)",
        "",
        f"_spec = importlib.util.spec_from_file_location('{module_name}', r'{src_path}')",
        "_mod = importlib.util.module_from_spec(_spec)",
        f"_mod.__package__ = '{package_name}'",
        f"_mod.__spec__ = _spec",
        f"if '{package_name}':",  # Защита от установки __path__ для одиночных файлов
        f"    _mod.__path__ = [os.path.dirname(r'{src_path}')]",
        f"sys.modules['{module_name}'] = _mod",
        f"sys.modules['target_module'] = _mod",
        "",
        "try:",
        "    _spec.loader.exec_module(_mod)",
        "except Exception as _import_err:",
        f"    raise RuntimeError(f'Failed to import {module_name}: {{type(_import_err).__name__}}: {{_import_err}}')",
        "",
        "target_module = _mod",
        "globals().update({k: v for k, v in vars(_mod).items() if not k.startswith('_')})",
        "",
        "# " + "=" * 40,
    ]
    return "\n".join(lines)


def mirror_out_path(out_root, repo_name, src_path, repo_root):
    rel = os.path.relpath(src_path, repo_root)
    rel_dir = os.path.dirname(rel)
    base = os.path.splitext(os.path.basename(rel))[0]

    target_dir = os.path.join(out_root, repo_name, rel_dir)
    ensure_dir(target_dir)

    current = os.path.join(out_root, repo_name)
    for part in rel_dir.split(os.path.sep):
        if not part: continue
        current = os.path.join(current, part)
        init_file = os.path.join(current, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f: pass

    return os.path.join(target_dir, f"test_{base}.py")


def extract_python_code(text: str) -> str:
    text = re.sub(r'<think>.*?(?:</think>|$)', '', text, flags=re.DOTALL).strip()
    if not text:
        return ""
    match = re.search(r'\x60\x60\x60(?:python|pytest)\s*\n(.*?)\n\x60\x60\x60', text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        code = match.group(1).strip()
        if "def test_" in code:
            return code
    match = re.search(r'\x60\x60\x60\s*\n(.*?)\n\x60\x60\x60', text, flags=re.DOTALL)
    if match:
        code = match.group(1).strip()
        if "def test_" in code:
            return code
    match = re.search(r'\x60\x60\x60(?:python|pytest)?\s*\n(.*)', text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        code = match.group(1).strip()[:10_000]
        if "def test_" in code:
            return code
    if "def test_" in text:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "def test_", "class Test")):
                candidate = "\n".join(lines[i:]).strip()
                if "def test_" in candidate:
                    return candidate
    return ""


def get_symbols_with_signatures(tree):
    sigs = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_') and node.name != 'main':
            args = []
            for arg in node.args.args:
                if arg.annotation:
                    try:
                        args.append(f"{arg.arg}: {ast.unparse(arg.annotation)}")
                    except Exception:
                        args.append(arg.arg)
                else:
                    args.append(arg.arg)
            ret = ""
            if node.returns:
                try:
                    ret = f" -> {ast.unparse(node.returns)}"
                except Exception:
                    pass
            sigs.append(f"{node.name}({', '.join(args)}){ret}")
        elif isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
            sigs.append(f"class {node.name}")
    return sigs[:50]


MAX_RETRIES = 5


def process_file(args):
    repo_name, repo_path, src, out_root = args
    out_file = mirror_out_path(out_root, repo_name, src, repo_path)
    t0 = time.time()

    try:
        with open(src, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        return (repo_name, src, "read_error", 0, 0, 0, 0, str(e)[:200])

    if not source_code.strip():
        return (repo_name, src, "empty_file", 0, 0, 0, 0, "")

    src_dir = os.path.join(repo_path, "src")
    effective_root = src_dir if os.path.isdir(src_dir) and src.startswith(src_dir) else repo_path

    rel_path = os.path.relpath(src, effective_root)
    module_name = os.path.splitext(rel_path)[0].replace(os.path.sep, ".")

    try:
        tree = ast.parse(source_code)
        sigs = get_symbols_with_signatures(tree)
        symbols_str = "\n".join(sigs) if sigs else "No top-level functions or classes found."

        has_docstrings = any(
            ast.get_docstring(node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        )
    except SyntaxError:
        symbols_str = "AST parsing failed due to syntax error in source code."
        has_docstrings = False

    docstring_rule = (
        "- Extract logic from docstrings and implement as formal pytest cases."
        if has_docstrings else
        "- No docstrings found. Analyze the function signatures and implementation to infer expected behavior. Write happy-path tests for standard valid inputs."
    )

    _PRELOADED = "target_module, pytest, math, io, StringIO, redirect_stdout, base64, string, re, MagicMock, patch, Mock"

    base_prompt = f"""Output a single \x60\x60\x60python\x60\x60\x60 code block containing pytest unit tests for the code below.

    IMPORTS — READ CAREFULLY:
    - Do NOT write any import statements. Not even `import pytest` or `import math`.
    - Pre-loaded for you: {_PRELOADED}.
    - Call functions strictly as `target_module.<name>(...)`.
    - Any import line you write will be automatically deleted before the test runs.

    TESTING RULES:
    - Test ONLY these explicitly defined symbols and respect their signatures: 
    {symbols_str}
    {docstring_rule}
    - Focus on valid, standard inputs. Do not test edge cases unless explicitly covered by the logic.
    - Mocking: Use `patch` for I/O or network calls. Ensure mocked return values have all required attributes explicitly set.
    - NEVER reconstruct file contents as inline string literals. For file I/O tests, use a minimal 3-item mock: `patch('builtins.open', mock_open(read_data='item1\\nitem2\\nitem3'))`.
    - KEEP TEST DATA CONCISE: Use a maximum of 5-7 elements in any list or parameterized set. DO NOT generate exhaustive loops.
    - DO NOT test code inside "if __name__ == '__main__':" blocks. DO NOT write performance benchmarks or use `timeit`.
    - NEVER test functions named main or main(). They are for demonstration only.
    - If testing functions that return lists where order does not matter (like sets of coordinates, combinations, or graphs), use set() or sorted() in your assertions. DO NOT assert strict list equality unless order is mathematically guaranteed. This also applies to dictionary keys/values.
    - No explanations, no prose. Output only the code block.

    Source code to test:
    \x60\x60\x60python
    {source_code}
    \x60\x60\x60"""

    current_prompt = base_prompt
    attempts = 0
    status = "failed_all_retries"
    notes = ""
    test_code = ""
    error_output = "No subprocess run attempted."
    run_res = None

    while attempts < MAX_RETRIES:
        attempts += 1
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system",
                     "content": "You are a Python QA engineer. Output only code. No reasoning, no explanation."},
                    {"role": "user", "content": current_prompt}
                ],
                frequency_penalty=0.0,
                presence_penalty=0.0,
                temperature=0.1 + max(0, attempts - 1) * 0.15,
                top_p=0.8,
                max_tokens=12288,
                timeout=1200,
                extra_body={
                    "top_k": 20,
                    "min_p": 0.0,
                    "repetition_penalty": 1.0,
                    "chat_template_kwargs": {"enable_thinking": False}
                }
            )
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens

            print(
                f"📊 [Tokens] Prompt: {prompt_tokens} | Generated: {completion_tokens} | Overall: {total_tokens} | File: {module_name}")
            llm_output = response.choices[0].message.content
        except Exception as e:
            notes = f"API Error: {str(e)[:200]}"
            print(f"API Retry for {module_name} (sleeping with jitter)...")
            time.sleep(3 + random.uniform(0, 2))
            continue

        prompt_debug_path = os.path.join(out_root, "prompt_debug.log")
        with _log_lock:
            with open(prompt_debug_path, "a", encoding="utf-8") as pdf:
                pdf.write(f"\n\n{'=' * 50}\n")
                pdf.write(f"🚀 FILE: {module_name} | ATTEMPT: {attempts}\n")
                pdf.write(f"{'=' * 50}\n\n")
                pdf.write(">>> 📥 1. FULL PROMPT SENT TO LLM:\n")
                pdf.write(current_prompt)
                pdf.write("\n\n")
                pdf.write("<<< 📤 2. FULL RAW RESPONSE FROM LLM:\n")
                pdf.write(llm_output)
                pdf.write("\n\n")
                pdf.write(f"{'-' * 50}\n")

        test_code = extract_python_code(llm_output)
        if not test_code.strip() or "def test_" not in test_code:
            notes = "No valid tests generated"

            debug_log_path = os.path.join(out_root, "hallucinations_debug.log")
            with _log_lock:
                with open(debug_log_path, "a", encoding="utf-8") as hf:
                    hf.write(f"\n\n{'=' * 20}\nFILE: {module_name} (Attempt: {attempts})\n{'=' * 20}\n")
                    hf.write("--- RAW LLM OUTPUT START ---\n")
                    hf.write(llm_output[-3000:])
                    hf.write("\n--- RAW LLM OUTPUT END ---\n")

            current_prompt = f"{base_prompt}\n\nYOUR PREVIOUS RESPONSE WAS INVALID. You must generate valid python code containing at least one 'def test_...' function. Ensure it is strictly enclosed in a \x60\x60\x60python ... \x60\x60\x60 block."
            continue

        clean_code = strip_llm_imports(test_code)
        preamble = build_preamble(repo_path, src, module_name)
        final_test_code = preamble + "\n\n" + clean_code

        with open(out_file, "w", encoding="utf-8") as wf:
            wf.write(final_test_code)

        # Динамическое добавление src/ в PYTHONPATH, если нужно
        env = os.environ.copy()
        paths_to_add = [src_dir, repo_path] if os.path.isdir(src_dir) else [repo_path]
        env["PYTHONPATH"] = os.pathsep.join(paths_to_add) + os.pathsep + env.get('PYTHONPATH', '')

        cmd = [
            sys.executable, "-m", "pytest", out_file,
            "--timeout=20",
            "-vv",
            "--tb=short",
            "-p", "no:cacheprovider",
            "--disable-warnings"
        ]

        try:
            run_res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=repo_path, timeout=30)
            if run_res.returncode == 0:
                status = "ok"
                notes = f"Passed on attempt {attempts}"
                break
            else:
                error_output = (run_res.stdout + run_res.stderr).strip()[-1000:]
        except subprocess.TimeoutExpired:
            error_output = "Subprocess Timeout: The generated test caused an infinite loop or deadlock."
            notes = "TimeoutExpired"
            run_res = None

        if run_res is not None:
            error_lines = [l.strip() for l in error_output.split('\n') if l.strip()]
            extracted_error = "Unknown Error"
            for line in reversed(error_lines):
                if line.startswith("E ") or "Error:" in line or "Exception:" in line:
                    extracted_error = line.replace("E ", "").strip()
                    break

            # Если сломалось прямо на импорте (из-за отсутствия либ или кривых связей), записываем это четко
            if "Failed to import" in error_output:
                notes = extracted_error
            else:
                notes = extracted_error

            current_prompt = f"""[FIX ATTEMPT {attempts}/{MAX_RETRIES}] Your previous pytest file failed. Analyze the traceback and output a fully fixed version.

SAME RULES APPLY:
- Output ONLY a single \x60\x60\x60python\x60\x60\x60 code block. No explanations.
- NO IMPORTS: Pre-loaded: {_PRELOADED}.
- Call functions as `target_module.<name>(...)`. Do not invent function names.
- Fix the root cause. Do not "fix" the test by removing valid assertions.
- AssertionError → check if you hardcoded an exact result for an algorithm with multiple valid outputs.
- AttributeError on `NoneType` → your mock is incomplete. Set all required attributes on the `MagicMock`.
- If testing functions that return lists where order does not matter, use set() or sorted().

Target source code (for reference):
\x60\x60\x60python
{source_code}
\x60\x60\x60

Your test code that failed:
\x60\x60\x60python
{test_code}
\x60\x60\x60

Pytest traceback:
\x60\x60\x60plaintext
{error_output[-3000:]}
\x60\x60\x60"""

    if status != "ok":
        log_path = os.path.join(out_root, "failed_tests_log.txt")
        with _log_lock:
            with open(log_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"FAIL: {src}\n")
                log_f.write(f"Notes: {notes}\n")
                log_f.write(f"Full Pytest Output:\n{error_output}\n")
                log_f.write("=" * 50 + "\n\n")
        if os.path.exists(out_file):
            os.remove(out_file)

    elapsed = round(time.time() - t0, 3)
    return (repo_name, src, status, elapsed, len(test_code), test_code.count("def test_"), attempts, notes)


def process_repo(repo_path, out_root, metrics_writer):
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        return
    ensure_init_files_in_repo(repo_path)
    repo_name = os.path.basename(os.path.normpath(repo_path))
    print(f"Processing repo: {repo_name} ({repo_path})")

    py_files = find_py_files(repo_path)
    print(f"  Python files found: {len(py_files)}")

    tasks = [(repo_name, repo_path, src, out_root) for src in py_files]
    start_repo = time.time()

    file_results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, t) for t in tasks]
        for future in as_completed(futures):
            try:
                res = future.result()
                repo_name, src, status, elapsed, chars, test_count, attempts, notes = res
                file_results.append(res)

                if status == "ok":
                    print(f"OK: {os.path.basename(src)} -> {test_count} tests (Attempt: {attempts})")
                elif status == "llm_error":
                    print(f"LLM_ERROR: {os.path.basename(src)} | API/Connection failed: {notes}")
                else:
                    clean_note = notes.replace('\n', ' ')
                    print(f"FAIL: {os.path.basename(src)} ({status}) | Error: {clean_note[:150]}")
            except Exception as e:
                print(f"WORKER CRASHED on a file: {e}")

    total_gen_time = round(time.time() - start_repo, 2)
    print(f"Generation finished in {total_gen_time}s. Running pytest for coverage...")

    repo_out_dir = os.path.join(out_root, repo_name)
    cov_json_path = os.path.join(out_root, f"{repo_name}_coverage.json")

    repo_cov = 0.0
    file_cov_dict = {}

    if os.path.exists(repo_out_dir):
        # Корректируем PYTHONPATH и для финального отчета pytest
        env = os.environ.copy()
        src_dir = os.path.join(repo_path, "src")
        paths_to_add = [src_dir, repo_path] if os.path.isdir(src_dir) else [repo_path]
        env["PYTHONPATH"] = os.pathsep.join(paths_to_add) + os.pathsep + env.get('PYTHONPATH', '')

        pytest_cmd = [
            "pytest",
            repo_out_dir,
            f"--cov={repo_path}",
            f"--cov-report=json:{cov_json_path}",
            "--cov-append",
            "-p", "no:cacheprovider",
            "--continue-on-collection-errors",
            "--timeout=30",
            "-q"
        ]

        try:
            proc = subprocess.run(pytest_cmd, capture_output=True, text=True, timeout=900, env=env, cwd=repo_path)
            if os.path.exists(cov_json_path):
                with open(cov_json_path, "r", encoding="utf-8") as f:
                    cov_data = json.load(f)
                    repo_cov = cov_data.get("totals", {}).get("percent_covered", 0.0)
                    for filepath, fdata in cov_data.get("files", {}).items():
                        abs_filepath = os.path.normpath(os.path.join(repo_path, filepath))
                        file_cov_dict[abs_filepath] = fdata.get("summary", {}).get("percent_covered", 0.0)
                os.remove(cov_json_path)
        except subprocess.TimeoutExpired:
            print("[WARN] Pytest timeout expired!")

    for res in file_results:
        repo_name, src, status, elapsed, chars, test_count, attempts, notes = res
        norm_src = os.path.normpath(src)
        file_cov = file_cov_dict.get(norm_src, 0.0) if status == "ok" else 0.0

        metrics_writer.writerow([
            repo_name, src, status, elapsed, chars, test_count,
            attempts, round(file_cov, 2), round(repo_cov, 2), notes
        ])

    print(f"Finished repo: {repo_name} totally in {round(time.time() - start_repo, 2)}s\n")


def main():
    ensure_dir(OUT_DIR)
    if os.path.exists(METRICS_CSV):
        os.remove(METRICS_CSV)

    with open(METRICS_CSV, "w", newline="", encoding="utf-8") as mf:
        cw = csv.writer(mf)
        cw.writerow(["repo", "source_file", "status", "gen_time_s", "chars",
                     "n_tests", "attempts", "file_cov_pct", "repo_cov_pct", "notes"])
        for repo in REPOS:
            process_repo(repo, OUT_DIR, cw)

    print("All done. Metrics:", METRICS_CSV)


if __name__ == "__main__":
    main()