#!/usr/bin/env python3
import os
import sys
import csv
import time
import subprocess
import sqlite3
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.expanduser("~/git/lazytest/testing/generated_tests/qwen_3.5")
REPO_ROOT = os.path.expanduser("~/git/lazytest/testing/repos_for_testing/TheAlgorithms")

# === НАСТРОЙКИ ДЛЯ ДЕБАГА ===
MAX_WORKERS = 8
DEBUG = False


def debug(msg):
    if DEBUG:
        print(msg, flush=True)


# ============================

def evaluate_test(row, current_out_dir):
    repo, src_file, status, gen_time, chars, n_tests, attempts, old_file_cov, old_repo_cov, notes = row

    if status != "ok":
        return row

    if "TheAlgorithms/" in src_file:
        rel_path = src_file.split("TheAlgorithms/")[-1].strip(r"\/")
    else:
        rel_path = os.path.relpath(src_file, REPO_ROOT)

    base = os.path.splitext(os.path.basename(rel_path))[0]
    original_test_file = os.path.join(current_out_dir, repo, os.path.dirname(rel_path), f"test_{base}.py")

    debug(f"\n{'=' * 60}")
    debug(f"[DEBUG] Проверяем: {rel_path}")

    if not os.path.exists(original_test_file):
        row[7] = 0.0
        row[9] = "Test file not found on disk"
        return row

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_copy_dir = os.path.join(tmpdir, "TheAlgorithms")

        shutil.copytree(
            REPO_ROOT,
            repo_copy_dir,
            ignore=shutil.ignore_patterns('.git', '.pytest_cache', '__pycache__')
        )

        isolated_src_file = os.path.join(repo_copy_dir, rel_path)
        isolated_test_file = os.path.join(tmpdir, f"test_{base}.py")

        with open(original_test_file, "r", encoding="utf-8") as f:
            test_content = f.read()

        for old_path in [
            "/workspace/lazytest/testing/repos_for_testing/TheAlgorithms",
            REPO_ROOT,
            os.path.realpath(REPO_ROOT)
        ]:
            if old_path in test_content:
                test_content = test_content.replace(old_path, repo_copy_dir)

        with open(isolated_test_file, "w", encoding="utf-8") as f:
            f.write(test_content)

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{repo_copy_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"

        for conf_file in ["pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"]:
            conf_path = os.path.join(repo_copy_dir, conf_file)
            if os.path.exists(conf_path):
                os.remove(conf_path)

        safe_pytest_args = [
            "-q", "--disable-warnings",
            "-p", "no:cacheprovider",
            "-p", "no:doctest",
            "-p", "no:xdist",
            "-c", "/dev/null"
        ]

        # === Шаг 1: Baseline Test ===
        baseline_cmd = [
            sys.executable, "-m", "pytest",
            isolated_test_file,
            *safe_pytest_args,
            "--tb=short"
        ]

        debug(f"[DEBUG] Запуск Baseline: {' '.join(baseline_cmd)}")
        baseline_result = subprocess.run(
            baseline_cmd, env=env, capture_output=True, text=True, timeout=120, cwd=repo_copy_dir
        )

        if baseline_result.returncode != 0:
            row[7] = 0.0
            row[9] = "Baseline test failed"
            debug(f"[DEBUG] Baseline УПАЛ. Выход.\n{baseline_result.stdout[-1000:]}")
            return row

        debug(f"[DEBUG] Baseline ПРОЙДЕН успешно.")

        # === Шаг 2: Мутация через Cosmic Ray ===
        db_path = os.path.join(repo_copy_dir, "session.sqlite")
        toml_path = os.path.join(repo_copy_dir, "cr.toml")

        test_cmd = f"{sys.executable} -m pytest {isolated_test_file} " + " ".join(safe_pytest_args) + " --tb=no"

        toml_content = f"""[cosmic-ray]
module-path = "{isolated_src_file}"
timeout = 30.0
test-command = "{test_cmd}"
excluded-modules = []

[cosmic-ray.distributor]
name = "local"
"""
        with open(toml_path, "w", encoding="utf-8") as f:
            f.write(toml_content)

        try:
            cosmic_ray_exe = os.path.join(os.path.dirname(sys.executable), "cosmic-ray")

            debug(f"[DEBUG] Запускаем Cosmic Ray init...")
            init_res = subprocess.run(
                [cosmic_ray_exe, "init", toml_path, db_path],
                env=env, capture_output=True, text=True, timeout=60, cwd=repo_copy_dir
            )
            debug(f"[DEBUG] Init stdout:\n{init_res.stdout.strip()[:500]}")
            if init_res.stderr: debug(f"[DEBUG] Init stderr:\n{init_res.stderr.strip()[:500]}")

            debug(f"[DEBUG] Запускаем Cosmic Ray exec...")
            exec_res = subprocess.run(
                [cosmic_ray_exe, "exec", toml_path, db_path],
                env=env, capture_output=True, text=True, timeout=600, cwd=repo_copy_dir
            )
            debug(f"[DEBUG] Exec stdout:\n{exec_res.stdout.strip()[:500]}")
            if exec_res.stderr: debug(f"[DEBUG] Exec stderr:\n{exec_res.stderr.strip()[:500]}")

            mut_score = 0.0
            total_mutants = 0

            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                try:
                    # 1. Сканируем все таблицы
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    tables = [r[0] for r in cursor.fetchall()]
                    debug(f"[DEBUG] Найдены таблицы в БД: {tables}")

                    # 2. Динамически ищем нужную таблицу и колонку
                    target_table = None
                    outcome_col = None

                    for t in tables:
                        cursor.execute(f"PRAGMA table_info({t});")
                        cols = [r[1].lower() for r in cursor.fetchall()]

                        # Cosmic Ray может называть колонку со статусом по-разному
                        for candidate in ["test_outcome", "worker_outcome", "outcome", "status"]:
                            if candidate in cols:
                                target_table = t
                                outcome_col = candidate
                                break
                        if target_table:
                            break

                    if target_table and outcome_col:
                        # 3. Считаем статистику
                        cursor.execute(f"SELECT {outcome_col}, count(*) FROM {target_table} GROUP BY {outcome_col}")
                        rows_db = cursor.fetchall()
                        debug(f"[DEBUG] Результаты из таблицы {target_table} (колонка {outcome_col}): {rows_db}")

                        killed = survived = incompetent = 0
                        for st, count in rows_db:
                            st_str = str(st).upper() if st else "NONE"
                            if st_str == 'KILLED':
                                killed += count
                            elif st_str == 'SURVIVED':
                                survived += count
                            elif st_str == 'INCOMPETENT':
                                incompetent += count

                        total_mutants = killed + survived + incompetent
                        if total_mutants > 0:
                            mut_score = ((killed + incompetent) / total_mutants) * 100

                        debug(
                            f"[DEBUG] Итог: Killed: {killed}, Survived: {survived}, Incompetent: {incompetent}, Score: {mut_score}%")
                    else:
                        debug(f"[DEBUG] ВНИМАНИЕ: Колонка с результатами не найдена ни в одной таблице!")

                except sqlite3.OperationalError as e:
                    debug(f"[DEBUG] Ошибка чтения БД: {e}")
                    row[9] = "SQLite parsing error"
                finally:
                    conn.close()
            else:
                debug(f"[DEBUG] Файл БД session.sqlite не найден!")

            if total_mutants == 0:
                row[7] = 0.0
                row[9] = "Cosmic Ray 0 mutants generated"
            else:
                row[7] = round(mut_score, 2)
                row[9] = "Cosmic Ray Processed"

        except subprocess.TimeoutExpired:
            debug("[DEBUG] Cosmic Ray завис (Таймаут)")
            row[7] = 0.0
            row[9] = "Cosmic Ray Timeout"
        except Exception as e:
            debug(f"[DEBUG] Ошибка Cosmic Ray: {e}")
            row[7] = 0.0
            row[9] = f"Cosmic Ray error: {str(e)}"

    return row


def process_directory(out_dir):
    folder_name = os.path.basename(out_dir)
    csv_in = os.path.join(out_dir, "metrics_qwen_coder_TheAlgorithms.csv")
    csv_out = os.path.join(out_dir, "metrics_mutation_cosmic_ray.csv")

    if not os.path.exists(csv_in):
        print(f"  [ПРОПУСК] Не найден исходный CSV: {csv_in}")
        return

    print(f"\n[{folder_name}] Запуск мутационного тестирования (Cosmic Ray)...")

    with open(csv_in, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # === СИСТЕМА ВОССТАНОВЛЕНИЯ ПРОГРЕССА (RESUME) ===
    already_processed = {}
    if os.path.exists(csv_out):
        with open(csv_out, "r", encoding="utf-8") as f:
            reader_out = csv.reader(f)
            next(reader_out, None)  # пропускаем заголовок
            for r in reader_out:
                if len(r) > 9 and ("Cosmic Ray" in r[9] or "Timeout" in r[9]):
                    already_processed[r[1]] = r  # r[1] - это путь к файлу src_file

    rows_to_process = []
    processed_rows = []

    for row in rows:
        src_file = row[1]
        if src_file in already_processed:
            processed_rows.append(already_processed[src_file])
        else:
            rows_to_process.append(row)

    if already_processed:
        print(f"  [>] Найдено {len(already_processed)} уже обработанных файлов. Осталось: {len(rows_to_process)}.")

    if not rows_to_process:
        print(f"  [{folder_name}] Все файлы уже обработаны!")
        return

    # Запускаем потоки ТОЛЬКО для оставшихся файлов
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(evaluate_test, row, out_dir): row for row in rows_to_process}

        count = 0
        for future in as_completed(futures):
            processed_rows.append(future.result())
            count += 1

            # === СИСТЕМА АВТОСОХРАНЕНИЯ ===
            # Каждые 5 файлов перезаписываем CSV, чтобы ничего не потерять при краше
            if count % 5 == 0 or count == len(rows_to_process):
                with open(csv_out, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(header)
                    writer.writerows(processed_rows)
                print(f"  [{folder_name}] Промутировано {count}/{len(rows_to_process)} файлов (Прогресс сохранен)...")

    print(f"[{folder_name}] ГОТОВО! Сохранено в {csv_out}")


def main():
    if not os.path.exists(BASE_DIR):
        print(f"Ошибка: Не найдена базовая папка {BASE_DIR}")
        return

    run_folders = sorted([
        f for f in os.listdir(BASE_DIR)
        if os.path.isdir(os.path.join(BASE_DIR, f)) and f.startswith("run_")
    ])

    print(f"Найдено папок для мутации: {len(run_folders)}")
    print("=" * 50)

    start_time = time.time()

    # Возвращаем прогон по всем папкам!
    for folder in run_folders:
        full_out_dir = os.path.join(BASE_DIR, folder)
        process_directory(full_out_dir)

    end_time = time.time()
    total_seconds = end_time - start_time
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)

    print("\n" + "=" * 50)
    print("🚀 ВСЕ МУТАЦИИ УСПЕШНО ЗАВЕРШЕНЫ!")
    print(f"⏱️ Общее время прогона Cosmic Ray: {minutes} мин {seconds} сек")
    print("=" * 50)


if __name__ == "__main__":
    main()