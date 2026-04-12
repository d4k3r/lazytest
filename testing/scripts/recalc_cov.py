#!/usr/bin/env python3
import os
import csv
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- ПУТИ К ТВОЕМУ RUN_1 ---
# Убедись, что пути совпадают с теми, куда сгенерировались тесты
OUT_DIR = os.path.expanduser("~/clown/3rd_year_project/testing/generated_tests/qwen_coder/run_1")
CSV_IN = os.path.join(OUT_DIR, "metrics_qwen_coder_TheAlgorithms.csv")
CSV_OUT = os.path.join(OUT_DIR, "metrics_fixed_coverage.csv")
REPO_ROOT = os.path.expanduser("~/clown/3rd_year_project/testing/repos_for_testing/TheAlgorithms")

MAX_WORKERS = 24


def evaluate_test(row):
    repo, src_file, status, gen_time, chars, n_tests, attempts, old_file_cov, old_repo_cov, notes = row

    if status != "ok":
        return row

    rel_path = os.path.relpath(src_file, REPO_ROOT)
    base = os.path.splitext(os.path.basename(rel_path))[0]
    test_file = os.path.join(OUT_DIR, repo, os.path.dirname(rel_path), f"test_{base}.py")

    if not os.path.exists(test_file):
        row[7] = 0.0
        row[9] = "Test file not found on disk"
        return row

    cov_json = f"{test_file}.cov.json"
    cov_db   = f"{test_file}.coverage"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["COVERAGE_FILE"] = cov_db

    # --cov=REPO_ROOT so path matching works; we filter to src_file afterwards
    cmd = [
        "pytest", test_file,
        f"--cov={REPO_ROOT}",
        f"--cov-report=json:{cov_json}",
        "-q",
        "--timeout=10",
        "--disable-warnings",
        "-p", "no:cacheprovider",
    ]

    new_cov = 0.0
    try:
        subprocess.run(
            cmd, env=env,
            capture_output=True,
            timeout=30,          # outer timeout longer than pytest's inner --timeout
            cwd=REPO_ROOT
        )

        if os.path.exists(cov_json):
            with open(cov_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Find the entry matching our source file (normalize both paths)
            norm_src = os.path.normpath(src_file)
            for filepath, fdata in data.get("files", {}).items():
                # coverage.py stores paths relative to where pytest ran (REPO_ROOT)
                candidate = os.path.normpath(os.path.join(REPO_ROOT, filepath))
                if candidate == norm_src:
                    new_cov = fdata.get("summary", {}).get("percent_covered", 0.0)
                    break

            os.remove(cov_json)

        row[7] = round(new_cov, 2)

    except subprocess.TimeoutExpired:
        row[9] = "Pytest Timeout"
        if os.path.exists(test_file):
            os.rename(test_file, test_file + ".zombie")
    except Exception as e:
        row[9] = f"Eval error: {str(e)}"
    finally:
        for tmp in [cov_db, cov_db + ".db"]:
            if os.path.exists(tmp):
                os.remove(tmp)

    return row


def main():
    if not os.path.exists(CSV_IN):
        print(f"File not found: {CSV_IN}")
        return

    # Читаем старый CSV
    with open(CSV_IN, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    print(f"Loaded {len(rows)} files from CSV. Starting coverage evaluation...")

    processed_rows = []
    # Запускаем проверку в 16 потоков
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(evaluate_test, row): row for row in rows}

        count = 0
        for future in as_completed(futures):
            processed_rows.append(future.result())
            count += 1
            if count % 50 == 0:
                print(f"Evaluated {count}/{len(rows)} tests...")

    # Сохраняем в новый файл
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(processed_rows)

    print(f"\nDONE! Fixed metrics saved to: {CSV_OUT}")


if __name__ == "__main__":
    main()