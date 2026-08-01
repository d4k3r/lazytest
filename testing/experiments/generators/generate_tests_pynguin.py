#!/usr/bin/env python3
"""
generate_pynguin_tests.py
Скрипт только для генерации тестов с помощью Pynguin.
Coverage и Mutation Score считаются отдельно.
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
import signal
import ast
import csv
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

##### CONFIGURATION #####
MAX_WORKERS = 80
BASE_TESTING_DIR = r"/workspace/lazytest/testing"

REPOS = [
    os.path.join(BASE_TESTING_DIR, "repos_for_testing", "requests"),
    os.path.join(BASE_TESTING_DIR, "repos_for_testing", "TheAlgorithms"),
    os.path.join(BASE_TESTING_DIR, "repos_for_testing", "pandas"),
    os.path.join(BASE_TESTING_DIR, "repos_for_testing", "numpy"),
]

OUT_DIR = os.path.join(BASE_TESTING_DIR, "generated_tests", "pynguin", "run_2")

# Pynguin parameters
PYNGUIN_CMD = "pynguin"
PYNGUIN_TIMEOUT_PER_FILE = 240  # Максимальное время поиска (sec)
PYNGUIN_TEST_EXEC_TIMEOUT = 20  # Таймаут выполнения одного теста (sec)
PYNGUIN_ALGORITHM = "DYNAMOSA"


##### END CONFIG #####

def find_py_files(repo_path):
    py_files = []
    for root, dirs, files in os.walk(repo_path):
        skip = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'build', 'dist'}
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f == "__init__.py" or not f.endswith(".py") or f.startswith("."):
                continue
            full = os.path.join(root, f)
            norm = full.replace("\\", os.path.sep)
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
    return os.path.join(out_dir, f"test_{base}.py")


def run_pynguin_for_module(repo_root, src_file, tmp_outdir, timeout_seconds):
    potential_src = os.path.join(repo_root, "src")
    import_root = potential_src if os.path.isdir(potential_src) else repo_root
    rel_path = os.path.relpath(src_file, import_root)

    if rel_path.startswith(".."):
        import_root = repo_root
        rel_path = os.path.relpath(src_file, repo_root)

    module_name = os.path.splitext(rel_path)[0].replace(os.sep, ".")

    cmd = [
        PYNGUIN_CMD,
        "--project-path", import_root,
        "--output-path", tmp_outdir,
        "--module-name", module_name,
        "--algorithm", PYNGUIN_ALGORITHM,
        "--maximum-search-time", str(timeout_seconds),
        "--maximum-test-execution-timeout", str(PYNGUIN_TEST_EXEC_TIMEOUT),
        "-v"
    ]

    env = os.environ.copy()
    env["PYNGUIN_DANGER_AWARE"] = "1"
    env["PYTHONPATH"] = f"{import_root}{os.pathsep}{repo_root}{os.pathsep}{env.get('PYTHONPATH', '')}"

    try:
        if os.name == "nt":
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    preexec_fn=os.setsid, env=env)

        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds + 30)
            return proc.returncode, stdout, (stdout or "") + "\n" + (stderr or "")
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except:
                    pass
            return 124, "", "TIMEOUT_EXPIRED"
    except Exception as e:
        return 1, "", f"SUBPROCESS_ERROR: {str(e)}"


def pick_generated_test(tmp_outdir, src_basename):
    found = []
    for root, dirs, files in os.walk(tmp_outdir):
        for f in files:
            if f.startswith("test_") and f.endswith(".py"):
                found.append(os.path.join(root, f))
    if not found: return None
    for p in found:
        if src_basename in os.path.basename(p): return p
    return found[0]


def process_file(args):
    repo_name, repo_path, src, out_root = args
    src_basename = os.path.splitext(os.path.basename(src))[0]
    out_file = mirror_out_path(out_root, repo_name, src, repo_path)
    tmp_out = tempfile.mkdtemp(prefix="pynguin_tmp_")

    t0 = time.time()
    rc, stdout, log = run_pynguin_for_module(repo_path, src, tmp_out, PYNGUIN_TIMEOUT_PER_FILE)
    elapsed = round(time.time() - t0, 3)

    is_nothing_to_test = "SUT contains nothing we can test" in log
    chosen = pick_generated_test(tmp_out, src_basename)

    if not chosen:
        shutil.rmtree(tmp_out, ignore_errors=True)
        status = "no_tests_generated" if (rc == 0 or is_nothing_to_test) else "pynguin_failed"
        return (repo_name, src, status, elapsed, 0, 0, log.strip()[-200:])

    try:
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        shutil.move(chosen, out_file)
        with open(out_file, "r", encoding="utf-8") as rf:
            code = rf.read()
            test_count = code.count("def test_")
        chars = os.path.getsize(out_file)
        shutil.rmtree(tmp_out, ignore_errors=True)

        try:
            ast.parse(code)
            status = "ok"
            notes = ""
        except SyntaxError as e:
            status = "syntax_error"
            notes = str(e)
        return (repo_name, src, status, elapsed, chars, test_count, notes)
    except Exception as e:
        shutil.rmtree(tmp_out, ignore_errors=True)
        return (repo_name, src, "move_error", elapsed, 0, 0, str(e))


def process_repo(repo_path, out_root):
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        print(f"[SKIP] {repo_path}")
        return

    repo_name = os.path.basename(os.path.normpath(repo_path))
    repo_out_dir = os.path.join(out_root, repo_name)
    ensure_dir(repo_out_dir)

    repo_metrics_csv = os.path.join(repo_out_dir, f"metrics_{repo_name}.csv")

    print(f"\n{'=' * 60}\nГЕНЕРАЦИЯ: {repo_name}\n{'=' * 60}")

    py_files = find_py_files(repo_path)
    tasks = [(repo_name, repo_path, src, out_root) for src in py_files]
    start_repo = time.time()

    file_results = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, t) for t in tasks]
        for future in as_completed(futures):
            res = future.result()
            file_results.append(res)
            _, src_path, status, elapsed, _, t_count, _ = res
            fname = os.path.basename(src_path)
            if status == "ok":
                print(f"  [OK] {fname} | Тестов: {t_count} | {elapsed}s")
            elif status == "no_tests_generated":
                print(f"  [-] {fname} | Empty SUT")
            else:
                print(f"  [FAIL] {fname} | {status}")

    with open(repo_metrics_csv, "w", newline="", encoding="utf-8") as mf:
        cw = csv.writer(mf)
        cw.writerow(["repo", "source_file", "status", "gen_time_s", "chars", "n_tests", "notes"])
        for res in file_results:
            cw.writerow(res)

    print(f"\nЗавершено: {repo_name} | {round(time.time() - start_repo, 2)}s\n")


def main():
    ensure_dir(OUT_DIR)
    for repo in REPOS:
        process_repo(repo, OUT_DIR)
    print(f"Done. Files: {OUT_DIR}")


if __name__ == "__main__":
    main()