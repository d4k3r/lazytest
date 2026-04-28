#!/usr/bin/env python3
import os
import csv
import time
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# === НОВЫЕ БАЗОВЫЕ ПУТИ ===
# Указываем только корневую папку со всеми run-ами
BASE_DIR = os.path.expanduser("~/git/lazytest/testing/generated_tests/devstral_cyankiwi")
REPO_ROOT = os.path.expanduser("~/git/lazytest/testing/repos_for_testing/TheAlgorithms")

# Для Coverage ставим 14 (на твоем 9800X3D)
MAX_WORKERS = 15


def evaluate_test(row, current_out_dir):
    """
    Обрабатывает один тест.
    Добавлен аргумент current_out_dir, чтобы потоки знали, в какой папке мы сейчас находимся.
    """
    repo, src_file, status, gen_time, chars, n_tests, attempts, old_file_cov, old_repo_cov, notes = row

    if status != "ok":
        return row

    # === УМНЫЙ ПАРСИНГ ПУТЕЙ ===
    if "TheAlgorithms/" in src_file:
        rel_path = src_file.split("TheAlgorithms/")[-1].strip(r"\/")
    else:
        rel_path = os.path.relpath(src_file, REPO_ROOT)

    base = os.path.splitext(os.path.basename(rel_path))[0]

    # Используем current_out_dir вместо глобальной переменной!
    test_file = os.path.join(current_out_dir, repo, os.path.dirname(rel_path), f"test_{base}.py")

    if not os.path.exists(test_file):
        row[7] = 0.0
        row[9] = "Test file not found on disk"
        return row

    cov_json = f"{test_file}.cov.json"
    cov_db = f"{test_file}.coverage"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["COVERAGE_FILE"] = cov_db

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
    # print(f"      [>] Тестируем: test_{base}.py")
    try:
        # Добавили text=True, чтобы получать строки, а не байты
        result = subprocess.run(
            cmd, env=env,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT
        )

        if os.path.exists(cov_json):
            with open(cov_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "TheAlgorithms/" in src_file:
                target_rel_path = src_file.split("TheAlgorithms/")[-1].strip(r"\/")
            else:
                target_rel_path = os.path.basename(src_file)

            norm_target = os.path.normpath(target_rel_path)

            for filepath, fdata in data.get("files", {}).items():
                norm_filepath = os.path.normpath(filepath)
                if norm_filepath.endswith(norm_target) or norm_target.endswith(norm_filepath):
                    new_cov = fdata.get("summary", {}).get("percent_covered", 0.0)
                    break

            os.remove(cov_json)

        # === ИДЕАЛЬНАЯ ЛОВУШКА ДЛЯ БАГА ===
        # if new_cov == 0.0:
        #     # print(f"      [!] ОШИБКА: Покрытие 0.0")
        #     # print(result.stdout[:500])  # Выведем чуть-чуть лога, чтобы понять причину
        # else:
            # print(f"      [V] Успех! Покрытие: {new_cov}%")
        # ==================================

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


def process_directory(out_dir):
    """Функция для обработки одной конкретной папки run_X"""
    folder_name = os.path.basename(out_dir)
    csv_in = os.path.join(out_dir, "metrics_qwen_coder_TheAlgorithms.csv")
    csv_out = os.path.join(out_dir, "metrics_fixed_coverage.csv")

    if not os.path.exists(csv_in):
        print(f"  [ПРОПУСК] Не найден исходный CSV: {csv_in}")
        return

    print(f"\n[{folder_name}] Запуск обработки...")
    with open(csv_in, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    processed_rows = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Передаем current_out_dir каждому воркеру
        futures = {executor.submit(evaluate_test, row, out_dir): row for row in rows}

        count = 0
        for future in as_completed(futures):
            processed_rows.append(future.result())
            count += 1
            if count % 100 == 0:
                print(f"  [{folder_name}] Проверено {count}/{len(rows)} тестов...")

    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(processed_rows)

    print(f"[{folder_name}] ГОТОВО! Сохранено в {csv_out}")


def main():

    if not os.path.exists(BASE_DIR):
        print(f"Ошибка: Не найдена базовая папка {BASE_DIR}")
        return

    # Собираем все папки, которые начинаются на "run_"
    run_folders = sorted([
        f for f in os.listdir(BASE_DIR)
        if os.path.isdir(os.path.join(BASE_DIR, f)) and f.startswith("run_")
    ])

    print(f"Найдено папок для обработки: {len(run_folders)}")
    print("=" * 40)

    start_time = time.time()
    # Запускаем цикл по всем найденным папкам
    for folder in run_folders:
        full_out_dir = os.path.join(BASE_DIR, folder)
        process_directory(full_out_dir)
    # process_directory(os.path.join(BASE_DIR, "run_1_repeat_mut_fixed"))

    end_time = time.time()

    # Считаем минуты и секунды
    total_seconds = end_time - start_time
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)

    print("\n" + "=" * 50)
    print("🚀 ВСЕ ПАПКИ УСПЕШНО ОБРАБОТАНЫ!")
    print(f"⏱️ Общее время прогона модели: {minutes} мин {seconds} сек")
    print("=" * 50)


if __name__ == "__main__":
    main()