#!/usr/bin/env python3
# ==============================================================================
# Generic baseline LLM test generation script.
#
# Purpose:
# - Simple target-file baseline for comparison against repository-aware LazyTest.
# - No AST symbol extraction.
# - No deterministic import preamble.
# - No import stripping.
# - No mutation-aware prompt.
# - No repository-specific prompt engineering.
# - No prompt repetition.
#
# Behaviour:
# - For each Python source file, ask the LLM to generate pytest tests.
# - Run the generated tests with pytest.
# - If pytest passes, save the test file.
# - If pytest fails, send the previous test file and traceback back to the model.
# - Maximum 5 attempts per source file.
# - If all attempts fail, no final test file is kept.
# ==============================================================================

import os
import re
import csv
import sys
import time
import random
import shutil
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI


# ==============================================================================
# CONFIGURATION
# ==============================================================================

MAX_WORKERS = 60
MAX_RETRIES = 5

PYTEST_TIMEOUT_SECONDS = 30
API_TIMEOUT_SECONDS = 1200

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent

REPOS = [
    str(PROJECT_ROOT / "testing" / "repos_for_testing" / "TheAlgorithms")
]

OUT_DIR = str(
    PROJECT_ROOT
    / "testing"
    / "generated_tests"
    / "qwen_3.5"
    / "run_10_generic_baseline_no_repeat"
)

METRICS_CSV = os.path.join(
    OUT_DIR,
    "metrics_qwen_coder_TheAlgorithms_generic_baseline.csv"
)

API_BASE_URL = "http://localhost:18000/v1"
MODEL_NAME = "Qwen/Qwen3.5-27B"

client = OpenAI(base_url=API_BASE_URL, api_key="not-needed")

_log_lock = threading.Lock()

# Used inside prompt strings to avoid literal markdown fences inside this file.
BT3 = "\x60" * 3


# ==============================================================================
# FILE DISCOVERY / PATH HELPERS
# ==============================================================================

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def is_relative_to(path: str, possible_parent: str) -> bool:
    """
    Portable replacement for Path.is_relative_to for string paths.
    """
    try:
        path = os.path.abspath(path)
        possible_parent = os.path.abspath(possible_parent)
        return os.path.commonpath([path, possible_parent]) == possible_parent
    except ValueError:
        return False


def find_py_files(repo_path: str) -> list[str]:
    """
    Find Python source files in the repository.

    This intentionally performs only simple generic filtering. It excludes
    obvious generated/cache/test folders but does not do repository-specific
    analysis.
    """
    py_files = []

    skip_dirs = {
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        "node_modules",
        "build",
        "dist",
        "docs",
        "tests",
        "test",
    }

    skip_files = {
        "__init__.py",
        "setup.py",
        "conftest.py",
    }

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        norm_root = root.replace("\\", os.path.sep)
        if os.path.sep + "tests" + os.path.sep in norm_root:
            continue

        for filename in files:
            if filename in skip_files:
                continue
            if not filename.endswith(".py"):
                continue

            full_path = os.path.join(root, filename)
            py_files.append(full_path)

    return sorted(py_files)


def effective_import_root(repo_path: str, src_path: str) -> str:
    """
    Determine the root from which a dotted module name should be calculated.

    Examples:
        repo/maths/graphs/file.py      -> effective root = repo
        repo/src/package/module.py     -> effective root = repo/src

    This is still generic and not repository-specific. It only handles the
    common Python src/ layout.
    """
    repo_path = os.path.abspath(repo_path)
    src_path = os.path.abspath(src_path)

    src_root = os.path.join(repo_path, "src")

    if os.path.isdir(src_root) and is_relative_to(src_path, src_root):
        return src_root

    return repo_path


def module_name_from_path(repo_path: str, src_path: str) -> str:
    """
    Convert a source path into a conventional dotted module name.

    Examples:
        repo/maths/graphs/file.py  -> maths.graphs.file
        repo/src/pkg/module.py     -> pkg.module
    """
    root = effective_import_root(repo_path, src_path)

    rel_path = os.path.relpath(src_path, root)
    module_name = os.path.splitext(rel_path)[0]
    module_name = module_name.replace(os.path.sep, ".")
    module_name = module_name.replace("/", ".").replace("\\", ".")

    return module_name


def pythonpath_for_repo(repo_path: str) -> str:
    """
    Build a generic PYTHONPATH for pytest.

    The repository root is always included. If repo/src exists, it is also
    included because many Python projects use a src/ layout.
    """
    repo_path = os.path.abspath(repo_path)
    src_root = os.path.join(repo_path, "src")

    paths = []

    if os.path.isdir(src_root):
        paths.append(src_root)

    paths.append(repo_path)

    return os.pathsep.join(paths)


def final_out_path(out_root: str, repo_name: str, src_path: str, repo_root: str) -> str:
    """
    Mirror the source tree under the output directory.
    """
    rel_path = os.path.relpath(src_path, repo_root)
    rel_dir = os.path.dirname(rel_path)
    base_name = os.path.splitext(os.path.basename(src_path))[0]

    target_dir = os.path.join(out_root, repo_name, rel_dir)
    ensure_dir(target_dir)

    return os.path.join(target_dir, f"test_{base_name}.py")


def temp_attempt_path(
    out_root: str,
    repo_name: str,
    src_path: str,
    repo_root: str,
    attempt: int,
) -> str:
    """
    Temporary test file used only while validating an attempt.
    Failed attempts are deleted.
    """
    rel_path = os.path.relpath(src_path, repo_root)
    rel_dir = os.path.dirname(rel_path)
    base_name = os.path.splitext(os.path.basename(src_path))[0]

    target_dir = os.path.join(out_root, "_attempts", repo_name, rel_dir)
    ensure_dir(target_dir)

    return os.path.join(target_dir, f"test_{base_name}_attempt_{attempt}.py")


# ==============================================================================
# PROMPTS
# ==============================================================================

def build_base_prompt(
    module_name: str,
    source_path: str,
    source_code: str,
    uses_src_layout: bool,
) -> str:
    src_note = (
        "- If the repository has a src/ directory, that src/ directory will also be on PYTHONPATH."
        if uses_src_layout
        else "- No src/ layout is assumed for this file."
    )

    return f"""You are generating pytest unit tests for a Python source file.

Output rules:
- Output raw Python code only.
- Do not use markdown fences.
- Do not explain your answer.
- Do not reimplement source functions or classes.
- Prefer deterministic tests.
- Use pytest.
- Mock filesystem, network, randomness, stdin/stdout, time, and external services where necessary.

Execution context:
- The tests will be run from the repository root.
- The repository root will be on PYTHONPATH.
{src_note}
- The source file path relative to the repository root is: {source_path}
- The module under test should be imported as: {module_name}

Use this import pattern:

import importlib
target_module = importlib.import_module("{module_name}")

Then call functions and classes as target_module.<name>.

Source code:
{BT3}python
{source_code}
{BT3}
"""


def build_repair_prompt(
    source_path: str,
    module_name: str,
    source_code: str,
    previous_test_code: str,
    error_output: str,
    uses_src_layout: bool,
) -> str:
    src_note = (
        "- If the repository has a src/ directory, that src/ directory will also be on PYTHONPATH."
        if uses_src_layout
        else "- No src/ layout is assumed for this file."
    )

    return f"""Your previous pytest test file failed.

Fix the test file so that it is valid pytest code and passes against the source file.
Do not reimplement the source functions or classes.
Do not remove useful assertions only to make the tests pass.
Output raw Python code only. Do not use markdown fences. Do not explain your answer.

Execution context:
- The tests will be run from the repository root.
- The repository root will be on PYTHONPATH.
{src_note}
- The source file path relative to the repository root is: {source_path}
- The module under test should be imported as: {module_name}

Use this import pattern:

import importlib
target_module = importlib.import_module("{module_name}")

Then call functions and classes as target_module.<name>.

Source code:
{BT3}python
{source_code}
{BT3}

Previous test code:
{BT3}python
{previous_test_code}
{BT3}

Pytest output:
{BT3}text
{error_output}
{BT3}
"""


def build_invalid_output_prompt(
    source_path: str,
    module_name: str,
    source_code: str,
    previous_output: str,
    uses_src_layout: bool,
) -> str:
    src_note = (
        "- If the repository has a src/ directory, that src/ directory will also be on PYTHONPATH."
        if uses_src_layout
        else "- No src/ layout is assumed for this file."
    )

    return f"""Your previous response was invalid because it did not contain usable pytest tests.

Generate a valid pytest test file for the source file below.
Output raw Python code only.
Do not use markdown fences.
Do not explain your answer.
Do not reimplement source functions or classes.

Execution context:
- The tests will be run from the repository root.
- The repository root will be on PYTHONPATH.
{src_note}
- The source file path relative to the repository root is: {source_path}
- The module under test should be imported as: {module_name}

Use this import pattern:

import importlib
target_module = importlib.import_module("{module_name}")

Then call functions and classes as target_module.<name>.

Source code:
{BT3}python
{source_code}
{BT3}

Previous invalid output:
{BT3}text
{previous_output}
{BT3}
"""


# ==============================================================================
# LLM OUTPUT CLEANING
# ==============================================================================

def extract_python_code(text: str) -> str:
    """
    The baseline prompt asks for raw Python code only.

    This function is intentionally minimal. It only removes common markdown
    wrapping if the model ignores the instruction. It does not remove imports,
    rewrite code, inject preambles, or otherwise repair the generated tests.
    """
    if not text:
        return ""

    text = re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.DOTALL).strip()

    fenced = re.search(
        r"\x60\x60\x60(?:python|pytest)?\s*\n(.*?)\n\x60\x60\x60",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if fenced:
        return fenced.group(1).strip()

    return text.strip()


# ==============================================================================
# LOGGING
# ==============================================================================

def append_debug_log(
    out_root: str,
    module_name: str,
    attempt: int,
    prompt: str,
    raw_response: str,
) -> None:
    log_path = os.path.join(out_root, "prompt_debug.log")

    with _log_lock:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("\n\n" + "=" * 80 + "\n")
            log.write(f"FILE: {module_name} | ATTEMPT: {attempt}\n")
            log.write("=" * 80 + "\n\n")
            log.write(">>> PROMPT SENT TO LLM:\n")
            log.write(prompt)
            log.write("\n\n<<< RAW LLM RESPONSE:\n")
            log.write(raw_response)
            log.write("\n")


def append_failure_log(
    out_root: str,
    src_path: str,
    notes: str,
    error_output: str,
) -> None:
    log_path = os.path.join(out_root, "failed_tests_log.txt")

    with _log_lock:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("\n\n" + "=" * 80 + "\n")
            log.write(f"FAIL: {src_path}\n")
            log.write(f"Notes: {notes}\n")
            log.write("-" * 80 + "\n")
            log.write(error_output)
            log.write("\n")


# ==============================================================================
# LLM / PYTEST EXECUTION
# ==============================================================================

def call_llm(prompt: str) -> tuple[str, str]:
    """
    Return:
        raw_output, token_note
    """
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": "You are a Python QA engineer. Output only Python code.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.8,
        top_p=0.95,
        max_tokens=16384,
        timeout=API_TIMEOUT_SECONDS,
        extra_body={
            "top_k": 20,
            "min_p": 0.0,
            "repetition_penalty": 1.0,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )

    raw_output = response.choices[0].message.content or ""

    usage = getattr(response, "usage", None)
    if usage:
        token_note = (
            f"prompt_tokens={usage.prompt_tokens}, "
            f"completion_tokens={usage.completion_tokens}, "
            f"total_tokens={usage.total_tokens}"
        )
    else:
        token_note = "token_usage_unavailable"

    return raw_output, token_note


def run_pytest(test_file: str, repo_path: str) -> tuple[bool, str]:
    """
    Run pytest against one generated test file.

    No deterministic import preamble is used. The only environment setup is
    adding the repository root, and src/ when present, to PYTHONPATH so that
    conventional imports have a chance to work.
    """
    env = os.environ.copy()

    base_pythonpath = pythonpath_for_repo(repo_path)
    old_pythonpath = env.get("PYTHONPATH", "")

    if old_pythonpath:
        env["PYTHONPATH"] = base_pythonpath + os.pathsep + old_pythonpath
    else:
        env["PYTHONPATH"] = base_pythonpath

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        test_file,
        "--timeout=20",
        "--tb=short",
        "-q",
        "-p",
        "no:cacheprovider",
        "--disable-warnings",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=repo_path,
            env=env,
            timeout=PYTEST_TIMEOUT_SECONDS,
        )

        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output

    except subprocess.TimeoutExpired:
        return False, "Subprocess TimeoutExpired: generated test file timed out."


def short_error_summary(error_output: str) -> str:
    if not error_output:
        return "unknown_error"

    lines = [line.strip() for line in error_output.splitlines() if line.strip()]

    for line in reversed(lines):
        if line.startswith("E "):
            return line.replace("E ", "").strip()[:300]
        if "Error:" in line or "Exception:" in line or "Failed:" in line:
            return line[:300]

    return lines[-1][:300] if lines else "unknown_error"


# ==============================================================================
# PER-FILE PROCESSING
# ==============================================================================

def process_file(task: tuple[str, str, str, str]) -> tuple:
    repo_name, repo_path, src_path, out_root = task

    start_time = time.time()

    final_file = final_out_path(out_root, repo_name, src_path, repo_path)

    try:
        with open(src_path, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as exc:
        return (
            repo_name,
            src_path,
            "",
            "read_error",
            0.0,
            0,
            0,
            0,
            str(exc)[:300],
        )

    if not source_code.strip():
        return (
            repo_name,
            src_path,
            "",
            "empty_file",
            0.0,
            0,
            0,
            0,
            "empty source file",
        )

    source_path = os.path.relpath(src_path, repo_path)
    module_name = module_name_from_path(repo_path, src_path)

    src_root = os.path.join(os.path.abspath(repo_path), "src")
    uses_src_layout = os.path.isdir(src_root) and is_relative_to(src_path, src_root)

    base_prompt = build_base_prompt(
        module_name=module_name,
        source_path=source_path,
        source_code=source_code,
        uses_src_layout=uses_src_layout,
    )

    current_prompt = base_prompt
    status = "failed_all_retries"
    notes = ""
    test_code = ""
    error_output = ""
    attempt = 0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw_output, token_note = call_llm(current_prompt)
            print(f"[Tokens] {module_name} | attempt={attempt} | {token_note}")

        except Exception as exc:
            notes = f"API error: {str(exc)[:300]}"
            error_output = notes
            print(f"API error for {module_name}, attempt {attempt}: {notes}")
            time.sleep(3 + random.uniform(0, 2))
            continue

        append_debug_log(
            out_root=out_root,
            module_name=module_name,
            attempt=attempt,
            prompt=current_prompt,
            raw_response=raw_output,
        )

        test_code = extract_python_code(raw_output)

        if not test_code.strip() or "def test_" not in test_code:
            notes = "invalid_model_output_no_test_function"
            error_output = raw_output[-3000:]

            current_prompt = build_invalid_output_prompt(
                source_path=source_path,
                module_name=module_name,
                source_code=source_code,
                previous_output=raw_output[-3000:],
                uses_src_layout=uses_src_layout,
            )
            continue

        tmp_file = temp_attempt_path(
            out_root=out_root,
            repo_name=repo_name,
            src_path=src_path,
            repo_root=repo_path,
            attempt=attempt,
        )

        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(test_code)
            f.write("\n")

        passed, pytest_output = run_pytest(tmp_file, repo_path)

        if passed:
            ensure_dir(os.path.dirname(final_file))

            if os.path.exists(final_file):
                os.remove(final_file)

            shutil.move(tmp_file, final_file)

            status = "ok"
            notes = f"passed_on_attempt_{attempt}"
            error_output = ""
            break

        error_output = pytest_output[-15000:]
        notes = short_error_summary(error_output)

        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass

        current_prompt = build_repair_prompt(
            source_path=source_path,
            module_name=module_name,
            source_code=source_code,
            previous_test_code=test_code,
            error_output=error_output,
            uses_src_layout=uses_src_layout,
        )

    if status != "ok":
        append_failure_log(
            out_root=out_root,
            src_path=src_path,
            notes=notes,
            error_output=error_output,
        )

        if os.path.exists(final_file):
            os.remove(final_file)

    elapsed = round(time.time() - start_time, 3)

    return (
        repo_name,
        src_path,
        module_name,
        status,
        elapsed,
        len(test_code),
        test_code.count("def test_"),
        attempt,
        notes,
    )


# ==============================================================================
# REPOSITORY PROCESSING
# ==============================================================================

def process_repo(repo_path: str, out_root: str, metrics_writer: csv.writer) -> None:
    repo_path = os.path.abspath(repo_path)

    if not os.path.isdir(repo_path):
        print(f"[WARN] Repository not found: {repo_path}")
        return

    repo_name = os.path.basename(os.path.normpath(repo_path))

    print("=" * 80)
    print(f"Processing repo: {repo_name}")
    print(f"Path: {repo_path}")
    print("=" * 80)

    py_files = find_py_files(repo_path)

    print(f"Python source files found: {len(py_files)}")

    tasks = [
        (repo_name, repo_path, src_path, out_root)
        for src_path in py_files
    ]

    start_repo = time.time()
    file_results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, task) for task in tasks]

        for future in as_completed(futures):
            try:
                result = future.result()
                file_results.append(result)

                (
                    _repo_name,
                    src_path,
                    module_name,
                    status,
                    _elapsed,
                    _chars,
                    n_tests,
                    attempts,
                    notes,
                ) = result

                filename = os.path.basename(src_path)

                if status == "ok":
                    print(
                        f"OK: {filename} | module={module_name} | "
                        f"tests={n_tests} | attempt={attempts}"
                    )
                else:
                    clean_notes = str(notes).replace("\n", " ")
                    print(
                        f"FAIL: {filename} | status={status} | "
                        f"attempts={attempts} | notes={clean_notes[:180]}"
                    )

            except Exception as exc:
                print(f"[WORKER CRASH] {exc}")

    file_results.sort(key=lambda row: row[1])

    for result in file_results:
        metrics_writer.writerow(result)

    total_time = round(time.time() - start_repo, 2)
    print(f"Finished repo: {repo_name} in {total_time}s")
    print()


# ==============================================================================
# MAIN
# ==============================================================================

def main() -> None:
    ensure_dir(OUT_DIR)

    attempts_dir = os.path.join(OUT_DIR, "_attempts")
    if os.path.isdir(attempts_dir):
        shutil.rmtree(attempts_dir)

    if os.path.exists(METRICS_CSV):
        os.remove(METRICS_CSV)

    with open(METRICS_CSV, "w", newline="", encoding="utf-8") as metrics_file:
        writer = csv.writer(metrics_file)

        writer.writerow([
            "repo",
            "source_file",
            "module_name",
            "status",
            "gen_time_s",
            "chars",
            "n_tests",
            "attempts",
            "notes",
        ])

        for repo_path in REPOS:
            process_repo(repo_path, OUT_DIR, writer)

    print("All done.")
    print(f"Metrics: {METRICS_CSV}")
    print(f"Output directory: {OUT_DIR}")


if __name__ == "__main__":
    main()