import json
import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TESTING_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Пути к файлам
JSON_PATH = os.path.join(TESTING_DIR, "generated_tests", "qwen_coder", "run_2", "TheAlgorithms_coverage_fixed.json")
CSV_PATH = os.path.join(TESTING_DIR, "generated_tests", "qwen_coder", "run_2", "metrics_qwen_coder_TheAlgorithms.csv")


def update_coverage():
    if not os.path.exists(JSON_PATH):
        print(f"[-] Файл {JSON_PATH} не найден!")
        return
    if not os.path.exists(CSV_PATH):
        print(f"[-] Файл {CSV_PATH} не найден!")
        return

    # 1. Читаем свежий JSON
    print("[*] Загрузка нового JSON отчета...")
    with open(JSON_PATH, 'r') as f:
        cov_data = json.load(f)

    # 2. Читаем старый CSV
    df = pd.read_csv(CSV_PATH)
    updated_count = 0

    # 3. Обновляем проценты
    print("[*] Обновление метрик...")
    for idx, row in df.iterrows():
        src_file = str(row['source_file'])

        # Ищем этот файл в словаре JSON
        for cov_file, cov_metrics in cov_data.get('files', {}).items():
            # Проверяем совпадение путей (с конца, чтобы избежать проблем с абсолютными путями)
            if src_file.endswith(cov_file) or cov_file.endswith(src_file):
                new_pct = cov_metrics.get('summary', {}).get('percent_covered', 0.0)
                df.at[idx, 'file_cov_pct'] = new_pct
                updated_count += 1
                break

    # 4. Сохраняем обновленный CSV
    df.to_csv(CSV_PATH, index=False)
    print(f"[+] Успех! Обновлено файлов: {updated_count}")


if __name__ == "__main__":
    update_coverage()