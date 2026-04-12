#!/usr/bin/env python3
"""
generate_pynguin_tests.py

Minimal pipeline: generate tests for Python files using Pynguin only.

EDIT THESE CONFIGS BELOW to your local paths before running.
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
import json
import signal
import ast
import csv
from pathlib import Path
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing


##### CONFIGURATION #####
# MAX_WORKERS = max(1, multiprocessing.cpu_count() - 2)
MAX_WORKERS = 16
# Список локальных репозиториев — абсолютные пути к папкам с репозиториями.
REPOS = [
    r"A:\Users\Julius\clown\3rd_year_project\testing\repos_for_testing\requests",
    # r"D:\3rd_year_project\testing\repos_for_testing\repo",
]

OUT_DIR = r"A:\Users\Julius\clown\3rd_year_project\testing\generated_tests\pynguin\run_2"

# File with metrics (will be created inside of OUT_DIR)
results = []
METRICS_CSV = os.path.join(OUT_DIR, "metrics_pynguin_requests.csv")

# Pynguin parameters
PYNGUIN_CMD = "pynguin"
PYNGUIN_TIMEOUT_PER_FILE = 240   # seconds for pynguin max search time (passed as --maximum-search-time)
PYNGUIN_TEST_EXEC_TIMEOUT = 20   # passed as --maximum-test-execution-timeout
PYNGUIN_ALGORITHM = "DYNAMOSA"

MAX_FILES_PER_REPO = 0
MAX_TIME_PER_REPO_MIN = 0


##### END CONFIG #####

def find_py_files(repo_path):
    py_files = []

    for root, dirs, files in os.walk(repo_path):

        # skip unneeded folders
        skip = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'build', 'dist'}
        dirs[:] = [d for d in dirs if d not in skip]

        for f in files:

            # skip __init__
            if f == "__init__.py":
                continue

            if not f.endswith(".py"):
                continue

            full = os.path.join(root, f)

            # normalize path
            norm = full.replace("\\", os.path.sep)

            # skip tests
            if os.path.sep + "tests" + os.path.sep in norm:
                continue

            py_files.append(full)

    return sorted(py_files)


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def mirror_out_path(out_root, repo_name, src_path, repo_root):
    rel = os.path.relpath(src_path, repo_root)
    rel_dir = os.path.dirname(rel)
    base = os.path.splitext(os.path.basename(rel))[0]
    out_dir = os.path.join(out_root, repo_name, rel_dir)
    ensure_dir(out_dir)
    out_file = os.path.join(out_dir, f"test_{base}.py")
    return out_file


def run_pynguin_for_module(repo_root, src_file, tmp_outdir, timeout_seconds):
    """
    Run pynguin for a given module (src_file) and output to tmp_outdir.
    Returns (returncode, stdout, stderr).
    Robust to child processes (kills whole tree on timeout).
    """
    rel = os.path.relpath(src_file, repo_root)
    module_name = os.path.splitext(rel)[0].replace(os.sep, ".")
    cmd = [
        PYNGUIN_CMD,
        "--project-path", repo_root,
        "--output-path", tmp_outdir,
        "--module-name", module_name,
        "--algorithm", PYNGUIN_ALGORITHM,
        "--maximum-search-time", str(timeout_seconds),
        "--maximum-test-execution-timeout", str(PYNGUIN_TEST_EXEC_TIMEOUT),
        "-v"
    ]

    try:
        # start process so we can control it
        if os.name == "nt":
            # Windows: CREATE_NEW_PROCESS_GROUP is helpful, but we'll use taskkill for tree kill
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        else:
            # POSIX: put into new process group so we can kill the group
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=os.setsid)

        try:
            # give a small buffer above requested timeout (adjust +10..+30 as you like)
            stdout, stderr = proc.communicate(timeout=timeout_seconds + 15)
            return proc.returncode, stdout, stderr

        except subprocess.TimeoutExpired as e:
            # Timeout: kill whole tree
            try:
                if os.name == "nt":
                    # taskkill /T kills child processes too
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                else:
                    # send SIGTERM to the process group
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    # short wait, then SIGKILL if necessary
                    time.sleep(1.0)
                    if proc.poll() is None:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                # best-effort, ignore errors here so we always try to communicate
                pass

            # now communicate (should return quickly because tree is killed)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except Exception:
                # fallback: read what we can
                try:
                    stdout, stderr = proc.stdout.read(), proc.stderr.read()
                except Exception:
                    stdout, stderr = "", ""

            return 124, stdout, f"TimeoutExpired: {e}\n{stderr}"

    except FileNotFoundError as e:
        return 127, "", f"FileNotFoundError: {e}"
    except Exception as e:
        return 1, "", f"UnexpectedError: {e}"


def pick_generated_test(tmp_outdir, src_basename):
    """
    Find generated test file in tmp_outdir that likely corresponds to src_basename.
    Prefer filenames containing the source base name; otherwise return first test_*.py found.
    """
    found = []
    for root, dirs, files in os.walk(tmp_outdir):
        for f in files:
            if f.startswith("test_") and f.endswith(".py"):
                found.append(os.path.join(root, f))
    if not found:
        return None
    for p in found:
        if src_basename in os.path.basename(p):
            return p
    return found[0]


def process_repo(repo_path, out_root, metrics_writer):
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        print(f"[SKIP] Repo path does not exist: {repo_path}")
        return

    repo_name = os.path.basename(os.path.normpath(repo_path))
    print(f"Processing repo: {repo_name} ({repo_path})")

    py_files = find_py_files(repo_path)
    print(f"  Python files found: {len(py_files)}")

    tasks = [(repo_name, repo_path, src, out_root) for src in py_files]
    start_repo = time.time()

    # 1. Сначала ГЕНЕРИРУЕМ все тесты
    file_results = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, t) for t in tasks]
        for future in as_completed(futures):
            res = future.result()
            file_results.append(res)
            status = res[2]
            if status == "ok":
                print(f"OK: {res[1]} -> {res[5]} tests in {res[3]}s")
            else:
                print(f"FAIL: {res[1]} ({status})")

    total_gen_time = round(time.time() - start_repo, 2)
    print(f"Generation finished in {total_gen_time}s. Running pytest for coverage...")

    # 2. ЗАПУСКАЕМ PYTEST для всего репозитория разом
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
            "--continue-on-collection-errors",  # <--- МАГИЧЕСКИЙ ФЛАГ
            "-q"
        ]

        # Добавляем путь к коду в PYTHONPATH, чтобы тесты могли его импортировать
        env = os.environ.copy()
        env["PYNGUIN_DANGER_AWARE"] = "1"
        env["PYTHONPATH"] = f"{repo_path}{os.pathsep}{env.get('PYTHONPATH', '')}"

        try:
            # Передаем env=env в subprocess
            proc = subprocess.run(pytest_cmd, capture_output=True, text=True, timeout=300, env=env)

            # ЧИТАЕМ РЕЗУЛЬТАТЫ COVERAGE
            if os.path.exists(cov_json_path):
                with open(cov_json_path, "r", encoding="utf-8") as f:
                    cov_data = json.load(f)

                    repo_cov = cov_data.get("totals", {}).get("percent_covered", 0.0)

                    for filepath, fdata in cov_data.get("files", {}).items():
                        norm_path = os.path.normpath(filepath)
                        file_cov_dict[norm_path] = fdata.get("summary", {}).get("percent_covered", 0.0)

                os.remove(cov_json_path)
            else:
                # Если файла нет, значит pytest упал. Выведем почему:
                print(f"[ERROR] coverage.json was not created!")
                print(f"Pytest Error Log: {proc.stderr.strip()[:500]}")

        except subprocess.TimeoutExpired:
            print("[WARN] Pytest timeout expired!")
        except Exception as e:
            print(f"[WARN] Coverage failed: {e}")

    # 4. ЗАПИСЫВАЕМ ВСЮ СТАТИСТИКУ В CSV
    for res in file_results:
        repo_name, src, status, elapsed, chars, test_count, notes = res
        norm_src = os.path.normpath(src)

        # Достаем coverage конкретного файла. Если тесты не сгенерировались - будет 0.0
        file_cov = file_cov_dict.get(norm_src, 0.0) if status == "ok" else 0.0

        metrics_writer.writerow([
            repo_name,
            src,
            status,
            elapsed,
            chars,
            test_count,
            round(file_cov, 2),
            round(repo_cov, 2),
            notes
        ])

    total_time = round(time.time() - start_repo, 2)
    print(f"Finished repo: {repo_name} totally in {total_time}s\n")


def process_file(args):
    repo_name, repo_path, src, out_root = args

    src_basename = os.path.splitext(os.path.basename(src))[0]
    out_file = mirror_out_path(out_root, repo_name, src, repo_path)

    tmp_out = tempfile.mkdtemp(prefix="pynguin_tmp_")

    t0 = time.time()

    rc, stdout, stderr = run_pynguin_for_module(repo_path, src, tmp_out, PYNGUIN_TIMEOUT_PER_FILE)

    elapsed = round(time.time() - t0, 3)

    # ---- ERROR HANDLING ----
    if rc != 0:

        stderr_lower = stderr.lower()

        if "timeout" in stderr_lower:
            status = "timeout"
        elif "no module named" in stderr_lower:
            status = "missing_dependency"
        elif "stacksize" in stderr_lower:
            status = "stack_error"
        elif "memory" in stderr_lower:
            status = "memory_error"
        else:
            status = "pynguin_failed"

        shutil.rmtree(tmp_out, ignore_errors=True)

        return (
            repo_name,
            src,
            status,
            elapsed,
            0,
            0,
            stderr.strip()[:200]
        )

    # ---- SUCCESS PATH ----
    chosen = pick_generated_test(tmp_out, src_basename)

    if not chosen:
        shutil.rmtree(tmp_out, ignore_errors=True)
        return (repo_name, src, "no_tests", elapsed, 0, 0, "pynguin produced no test files")

    try:
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        shutil.move(chosen, out_file)

        test_count = 0
        with open(out_file, "r", encoding="utf-8") as rf:
            source_code = rf.read()
            # Считаем количество тестов
            for ln in source_code.splitlines():
                if ln.strip().startswith("def test_"):
                    test_count += 1

        chars = os.path.getsize(out_file)
        shutil.rmtree(tmp_out, ignore_errors=True)

        # ПРОВЕРКА НА ОШИБКИ КОДА ПЕРЕД ЗАПИСЬЮ В "ok"
        status = "ok"
        notes = ""
        try:
            # Пытаемся распарсить сгенерированный код
            ast.parse(source_code)
        except SyntaxError as e:
            # Если код кривой, меняем статус
            status = "syntax_error"
            notes = f"SyntaxError: {e}"[:200]
        except Exception as e:
            status = "code_error"
            notes = str(e)[:200]

        return (
            repo_name,
            src,
            status,  # Теперь тут будет 'ok', 'syntax_error' или 'code_error'
            elapsed,
            chars,
            test_count,
            notes
        )

    except Exception as e:
        shutil.rmtree(tmp_out, ignore_errors=True)
        return (repo_name, src, "move_error", elapsed, 0, 0, str(e)[:200])


def main():
    ensure_dir(OUT_DIR)

    # Принудительно удаляем старый лог перед новым прогоном
    if os.path.exists(METRICS_CSV):
        os.remove(METRICS_CSV)

    with open(METRICS_CSV, "w", newline="", encoding="utf-8") as mf:
        cw = csv.writer(mf)
        cw.writerow([
            "repo", "source_file", "status", "gen_time_s",
            "chars", "n_tests", "file_cov_pct", "repo_cov_pct", "notes"
        ])
        for repo in REPOS:
            process_repo(repo, OUT_DIR, cw)

    print("All done. Metrics:", METRICS_CSV)


if __name__ == "__main__":
    main()