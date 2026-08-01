#!/usr/bin/env python3
# ==============================================================================
# The full source code of the project, including **detailed comments** and
# commit history, is available in the public GitHub repository:
# https://github.com/d4k3r/lazytest
# ==============================================================================


# llama-server \
#   --hf-repo shoumenchougou/RWKV7-G1e-13.3b-GGUF \
#   --hf-file rwkv7-g1e-13.3b-Q8_0.gguf \
#   --host 0.0.0.0 \
#   --port 8000 \
#   -ngl 99 \
#   --ctx-size 8192 \
#   --chat-template rwkv-world
  
# vllm serve "cyankiwi/Qwen3.5-27B-AWQ-INT4" --max-model-len 20480
# vllm serve "cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit" --max-model-len 20480

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import textwrap

##### CONFIGURATION #####
MAX_WORKERS = 8

REPOS = [os.path.expanduser("~/clown/3rd_year_project/testing/repos_for_testing/TheAlgorithms")]
OUT_DIR = os.path.expanduser("~/clown/3rd_year_project/testing/generated_tests/rwkv7/run_1")
METRICS_CSV = os.path.join(OUT_DIR, "metrics_rwkv7_TheAlgorithms.csv")

##### LLM CONFIGURATION #####
API_BASE_URL = "http://localhost:8000/v1"
MODEL_NAME = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"

client = OpenAI(base_url=API_BASE_URL, api_key="not-needed")


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
    """Пробегается по исходному репозиторию и добавляет __init__.py во все папки"""
    import os
    for root, dirs, files in os.walk(repo_path):
        # Пропускаем скрытые папки и виртуальные окружения
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
    """Удаляет все импорты, которые написала LLM, чтобы они не конфликтовали с нашими."""
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
    """Создает пуленепробиваемую шапку файла с импортами."""
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
        "# --- 1. Регистрация корня репозитория ---",
        f"_REPO = r'{repo_path}'",
        "if _REPO not in sys.path:",
        "    sys.path.insert(0, _REPO)",
        "",
        "# --- 1.5. Удаление фейковых пакетов Pytest и фикс путей ---",
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
        "# --- 2. ПРИНУДИТЕЛЬНАЯ ПЕРЕЗАГРУЗКА (Фикс для Coverage) ---",
        f"for _key in ['{module_name}', 'target_module', '{parts[-1]}']:",
        f"    sys.modules.pop(_key, None)",
        "",
        f"_spec = importlib.util.spec_from_file_location('{module_name}', r'{src_path}')",
        "_mod = importlib.util.module_from_spec(_spec)",
        f"_mod.__package__ = '{package_name}'",
        f"_mod.__spec__ = _spec",  # <--- Тоже добавлено от Клода
        f"sys.modules['{module_name}'] = _mod",
        f"sys.modules['target_module'] = _mod",
        "_spec.loader.exec_module(_mod)",
        "",
        "# --- 3. Экспорт функций модуля в глобальную область ---",
        "target_module = _mod",
        "globals().update({k: v for k, v in vars(_mod).items() if not k.startswith('_')})",
        "",
        "# " + "=" * 40,
        "# КОНЕЦ АВТОМАТИЧЕСКИХ ИМПОРТОВ",
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
    # Strip <think>...</think> blocks (handles unclosed tags too)
    text = re.sub(r'<think>.*?(?:</think>|$)', '', text, flags=re.DOTALL).strip()
    if not text:
        return ""
    # Strategy 1: find a properly closed ```python / ```pytest block
    # Non-greedy, requires the closing fence to be present
    match = re.search(
        r'```(?:python|pytest)\s*\n(.*?)\n```',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    if match:
        code = match.group(1).strip()
        if "def test_" in code:
            return code
    # Strategy 2: generic ``` block (no language tag), closed fence required
    match = re.search(r'```\s*\n(.*?)\n```', text, flags=re.DOTALL)
    if match:
        code = match.group(1).strip()
        if "def test_" in code:
            return code
    # Strategy 3: unclosed fence — take everything AFTER the opening fence,
    # but cap at 10,000 chars to avoid swallowing the whole response
    match = re.search(r'```(?:python|pytest)?\s*\n(.*)', text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        code = match.group(1).strip()[:10_000]
        if "def test_" in code:
            return code
    # Strategy 4: no fences at all — find first import/def/class line onwards
    if "def test_" in text:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "def test_", "class Test")):
                candidate = "\n".join(lines[i:]).strip()
                if "def test_" in candidate:
                    return candidate

    return ""


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

    rel_path = os.path.relpath(src, repo_path)
    module_name = os.path.splitext(rel_path)[0].replace(os.path.sep, ".")
    base_filename = os.path.basename(src)[:-3]  # имя файла без .py

    try:
        tree = ast.parse(source_code)
        # Ищем только функции и классы на верхнем уровне файла
        symbols = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
        symbols_str = ", ".join(symbols[:50])  # Берем первые 50, чтобы не переполнять промпт
        if not symbols_str:
            symbols_str = "No top-level functions or classes found."
    except SyntaxError:
        symbols_str = "AST parsing failed due to syntax error in source code."

    # === РЕКОМЕНДАЦИЯ 1: УЛЬТИМАТИВНЫЙ ИМПОРТ ПРЕАМБУЛОЙ ===
    preamble = textwrap.dedent(f"""\
        import sys
        import types
        import importlib.util
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        # Добавляем корень репозитория в пути
        if r"{repo_path}" not in sys.path:
            sys.path.insert(0, r"{repo_path}")

        # Динамически загружаем целевой модуль
        spec = importlib.util.spec_from_file_location("target_module", r"{src}")
        if spec and spec.loader:
            target_module = importlib.util.module_from_spec(spec)

            # Регистрируем модуль в sys.modules под всеми возможными именами
            # Это гарантирует, что любой импорт модели (короткий или полный) сработает
            sys.modules["target_module"] = target_module
            sys.modules["{module_name}"] = target_module
            sys.modules["{base_filename}"] = target_module

            try:
                spec.loader.exec_module(target_module)
            except Exception as e:
                raise RuntimeError("Import failed: " + str(e))

        # Теперь функции доступны как target_module.function_name
        # -----------------------------------------------------------
    """)

    # === РЕКОМЕНДАЦИЯ 2: УСИЛЕННЫЙ ПРОМПТ (МОКИ И ОБЪЕКТЫ) ===
    # base_prompt = f"""You are an expert Python QA automation engineer. Write comprehensive pytest unit tests for the following Python code.
    #
    # CRITICAL REQUIREMENTS:
    # 1. Output ONLY valid Python code inside a single \x60\x60\x60python block. No explanations.
    # 2. IMPORTING (STRICT AND CRITICAL):
    # The target module is ALREADY loaded into the environment as `target_module`.
    # - DO NOT write ANY import statements for the target module.
    # - DO NOT use sys.path hacks.
    # - You MUST call functions and classes directly from `target_module`.
    # Example: `result = target_module.my_function()`
    # 3. EXTRACT LOGIC FROM DOCTESTS & COMMENTS:
    # Read the docstrings and inline comments carefully. They hold the absolute truth about how the code should behave. If there are doctests, implement them as formal pytest cases.
    # 4. FOCUS ON THE HAPPY PATH (NO ADVERSARIAL TESTING):
    # Write tests ONLY for standard, valid, and expected inputs.
    # DO NOT test adversarial edge cases (like negative numbers, empty lists, or invalid types) UNLESS the source code or docstrings explicitly check for them. The goal is to verify the algorithm works correctly on valid data, not to break it.
    # 5. MULTIPLE VALID OUTPUTS:
    # If the target algorithm can produce multiple valid results (like graphs or permutations), do NOT hardcode an exact expected output. Verify the properties of the result instead.
    # 6. EXPECTED EXCEPTIONS:
    # Do NOT assume the target code has type checking. Do NOT use `pytest.raises(TypeError)` unless the code explicitly raises it.
    # 7. AVAILABLE OBJECTS: You can ONLY test the following explicitly defined functions/classes:
    # [{symbols_str}]
    # 8. MOCKING & FIXTURES (CRITICAL):
    # Use `unittest.mock.patch` if the target code performs File I/O, network requests, time-based operations, or random generation.
    # IMPORTANT: If mocking HTTP responses (requests) or Nodes/Trees, create FULL mock objects (e.g., using `MagicMock()`). Do NOT let mocked functions return `None`. Ensure required attributes like `.text`, `.content`, `.status_code`, or `.value` are explicitly set on the mock.
    # 9. KEEP TEST DATA CONCISE. Do not use excessively large arrays or loops in test data. Use edge cases with 5-10 elements maximum.
    # Target source code:
    # \x60\x60\x60python
    # {source_code}
    # \x60\x60\x60
    # """

    _PRELOADED = "target_module, pytest, math, io, StringIO, redirect_stdout, base64, string, re, MagicMock, patch, Mock"

    base_prompt = f"""
    Output a single ```python``` code block containing pytest unit tests for the code below.

    IMPORTS — READ CAREFULLY:
    - Do NOT write any import statements. Not even `import pytest` or `import math`.
    - Pre-loaded for you: {_PRELOADED}.
    - Call functions strictly as `target_module.<name>(...)`.
    - Any import line you write will be automatically deleted before the test runs.

    TESTING RULES:
    - Test ONLY these explicitly defined symbols: {symbols_str}
    - Extract logic from docstrings and implement as formal pytest cases.
    - Focus on valid, standard inputs. Do not test edge cases unless the docstring explicitly covers them.
    - Mocking: Use `patch` for I/O or network calls. Ensure mocked return values have all required attributes explicitly set.
    - NEVER reconstruct file contents as inline string literals. For file I/O tests, use a minimal 3-item mock: `patch('builtins.open', mock_open(read_data='item1\\nitem2\\nitem3'))`.
    - KEEP TEST DATA CONCISE: Use a maximum of 5-7 elements in any list or parameterized set. DO NOT generate exhaustive loops.
    - DO NOT test code inside "if __name__ == '__main__':" blocks. DO NOT write performance benchmarks or use `timeit`. DO NOT use @patch("__main__") or `from __main__ import ...`.
    - No explanations, no prose. Output only the code block.

    Source code to test:
    ```python
    {source_code}
    ```"""

    current_prompt = base_prompt
    attempts = 0
    status = "failed_all_retries"
    notes = ""
    test_code = ""
    error_output = "No subprocess run attempted."
    run_res = None

    while attempts < MAX_RETRIES:
        attempts += 1
        rwkv_prompt = current_prompt.replace("\n\n", "\n").strip()

        # 2. САМИ собираем идеальный RWKV-шаблон (без помощи сервера)
        raw_text_prompt = (
            f"User: You are a Python QA engineer. Output only code. No reasoning, no explanation.\n"
            f"{rwkv_prompt}\n\n"
            f"Assistant: <think></think>\n```python\n"
        )

        try:
            # 3. ВАЖНО: Используем completions вместо chat.completions!
            response = client.completions.create(
                model=MODEL_NAME,
                prompt=raw_text_prompt,  # Передаем готовую строку, а не массив сообщений
                temperature=0.1 if attempts == 1 else 0.1 + ((attempts - 1) * 0.025),
                max_tokens=4096,
                frequency_penalty=0.05,
                timeout=1200
            )

            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens

            print(
                f"📊 [Tokens] Prompt: {prompt_tokens} | Generated: {completion_tokens} | Overall: {total_tokens} | File: {module_name}")

            # 4. В completions ответ лежит в поле .text
            llm_output = response.choices[0].text

            # Возвращаем открывающий тег, с которого модель начала писать
            if not llm_output.lstrip().startswith("```"):
                llm_output = f"```python\n{llm_output}"

        except Exception as e:
            # НЕ УБИВАЕМ ПОТОК! Даем ему шанс переподключиться.
            notes = f"API Error: {str(e)[:100]}"
            print(f"API Retry for {module_name}...")
            continue

        prompt_debug_path = os.path.join(out_root, "prompt_debug.log")
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

            # --- ОТЛАДКА: СОХРАНЯЕМ ГАЛЛЮЦИНАЦИЮ, ЧТОБЫ ПОСМОТРЕТЬ ---
            # Сохраняем прямо в папку с результатами (out_root), чтобы легко найти
            debug_log_path = os.path.join(out_root, "hallucinations_debug.log")
            with open(debug_log_path, "a", encoding="utf-8") as hf:
                hf.write(f"\n\n{'=' * 20}\nFILE: {module_name} (Attempt: {attempts})\n{'=' * 20}\n")
                hf.write("--- RAW LLM OUTPUT START ---\n")
                # Записываем последние 3000 символов, чтобы увидеть, зациклило её или она забыла теги
                hf.write(llm_output[-3000:])
                hf.write("\n--- RAW LLM OUTPUT END ---\n")
            # ----------------------------------------------------------
            # Слегка усилил промпт, чтобы она точно вспомнила про маркдаун-теги
            current_prompt = f"{base_prompt}\n\nYOUR PREVIOUS RESPONSE WAS INVALID. You must generate valid python code containing at least one 'def test_...' function. Ensure it is strictly enclosed in a ```python ... ``` block."
            continue

        clean_code = strip_llm_imports(test_code)
        # Собираем железобетонную шапку
        preamble = build_preamble(repo_path, src, module_name)
        # Склеиваем
        final_test_code = preamble + "\n\n" + clean_code
        # Записываем итоговый файл
        with open(out_file, "w", encoding="utf-8") as wf:
            wf.write(final_test_code)

        cmd = [
            sys.executable, "-m", "pytest", out_file,
            "--timeout=20",
            "-vv",
            "--tb=short",
            "-p", "no:cacheprovider",
            "--disable-warnings"
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{repo_path}{os.pathsep}{env.get('PYTHONPATH', '')}"

        try:
            run_res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=repo_path, timeout=30)
            if run_res.returncode == 0:
                status = "ok"
                notes = f"Passed on attempt {attempts}"
                break
            else:
                error_output = (run_res.stdout + run_res.stderr).strip()[-1000:]
        except subprocess.TimeoutExpired:
            # Явная обработка таймаута без попыток парсить строку ошибки как Traceback
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
            notes = extracted_error

            current_prompt = f"""
            [FIX ATTEMPT {attempts}/{MAX_RETRIES}] Your previous pytest file failed. Analyze the traceback and output a fully fixed version.

            SAME RULES APPLY:
            - Output ONLY a single ```python``` code block. No explanations.
            - NO IMPORTS: Pre-loaded: {_PRELOADED}. Any import you write is deleted.
            - Call functions as `target_module.<name>(...)`. Do not invent function names.
            - DO NOT test code inside "if __name__ == '__main__':" blocks. DO NOT write performance benchmarks or use `timeit`. DO NOT use @patch("__main__") or `from __main__ import ...`.
            - Fix the root cause. Do not "fix" the test by removing valid assertions.
            - AssertionError → check if you hardcoded an exact result for an algorithm with multiple valid outputs.
            - AttributeError on `NoneType` → your mock is incomplete. Set all required attributes on the `MagicMock`.
            - TimeoutError or infinite loops → your test input is too large. Reduce lists to 5 elements max. NEVER use huge inline strings for files; use `patch('builtins.open', mock_open(read_data='...'))`.


            Target source code (for reference):
            ```python
            {source_code}
            Your test code that failed:

            Python
            {test_code}
            Pytest traceback:

            Plaintext
            {error_output[-3000:]}
            ```"""

    if status != "ok":
        # Сохраняем логи ошибок перед удалением
        log_path = os.path.join(out_root, "failed_tests_log.txt")
        with open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"FAIL: {src}\n")
            log_f.write(f"Notes: {notes}\n")
            log_f.write(f"Full Pytest Output:\n{error_output}\n")  # <-- ВОТ ЭТО Я ЗАБЫЛ!
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
                # СПАСИТЕЛЬНАЯ ПОДУШКА: если воркер вернул бред, Главный поток выживет
                print(f"🔥 WORKER CRASHED on a file: {e}")

    total_gen_time = round(time.time() - start_repo, 2)
    print(f"Generation finished in {total_gen_time}s. Running pytest for coverage...")

    repo_out_dir = os.path.join(out_root, repo_name)
    cov_json_path = os.path.join(out_root, f"{repo_name}_coverage.json")

    repo_cov = 0.0
    file_cov_dict = {}

    if os.path.exists(repo_out_dir):
        pytest_cmd = [
            "pytest",
            repo_out_dir,
            f"--cov={repo_path}",
            f"--cov-report=json:{cov_json_path}",
            "--cov-append",  # merge coverage from all workers
            "-p", "no:cacheprovider",
            "--continue-on-collection-errors",
            "--timeout=30",
            # "-n", "auto",
            # "--dist=loadfile",  # keep tests from same file on same worker
            "-q"
        ]

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{repo_path}{os.pathsep}{env.get('PYTHONPATH', '')}"

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