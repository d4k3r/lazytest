import subprocess
import sys
import os
import re

# Команда, которую мы пытаемся выполнить
CMD = [
    "pytest",
    "../generated_tests/qwen_coder/run_2/TheAlgorithms",
    "--cov=../repos_for_testing/TheAlgorithms",
    "--cov-report=json:../generated_tests/qwen_coder/run_2/TheAlgorithms_coverage_fixed.json",
    "--continue-on-collection-errors",
    "--timeout=5",
    "--timeout_method=thread",
    "-v"  # verbose нужен, чтобы точно видеть имя выполняемого файла
]

# Регулярное выражение для захвата пути к тестируемому файлу
FILE_PATTERN = re.compile(r"(\.\./generated_tests/qwen_coder/run_2/TheAlgorithms/.*?\.py)")
LOG_FILE = "zombies_report.txt"


def run_overseer():
    print(f"[*] Лог бесконечных циклов будет сохраняться в: {LOG_FILE}")

    while True:
        print("\n" + "=" * 60)
        print("[>>>] Запуск/Перезапуск pytest...")
        print("=" * 60 + "\n")

        # Запускаем pytest как подпроцесс
        process = subprocess.Popen(
            CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        current_file = None
        zombie_found = False
        traceback_buffer = []

        # Читаем вывод pytest строка за строкой в реальном времени
        for line in process.stdout:
            sys.stdout.write(line)  # Выводим в консоль для наглядности

            # Ищем, какой файл сейчас выполняется
            match = FILE_PATTERN.search(line)
            if match:
                current_file = match.group(1)

            # Если начался вывод таймаута, собираем трейсбэк
            if zombie_found:
                traceback_buffer.append(line)
                if len(traceback_buffer) > 15:  # Берем 15 строк трейсбэка
                    break  # Прерываем чтение, пора убивать процесс

            # Поймали триггер бесконечного цикла
            if "Timeout +++" in line or "Stack of MainThread" in line:
                zombie_found = True
                traceback_buffer.append(line)

        # Жестко убиваем процесс pytest
        process.kill()
        process.wait()

        if zombie_found and current_file:
            print(f"\n[!!!] ОБНАРУЖЕН БЕСКОНЕЧНЫЙ ЦИКЛ В ФАЙЛЕ: {current_file}")

            # 1. Записываем в отчет
            with open(LOG_FILE, "a") as f:
                f.write(f"=== ZOMBIE FILE: {current_file} ===\n")
                f.write("".join(traceback_buffer))
                f.write("\n\n")

            # 2. Удаляем файл
            try:
                abs_path = os.path.abspath(current_file)
                os.remove(abs_path)
                print(f"[-] Файл успешно удален. Перезапускаем с чистым полем...")
            except FileNotFoundError:
                print(f"[?] Не удалось найти файл для удаления: {abs_path}")
                break

        elif zombie_found and not current_file:
            print("\n[?] Зомби найден, но скрипт не смог распарсить имя файла. Остановка.")
            break
        else:
            print("\n[+] Бинго! Pytest успешно завершил работу без таймаутов.")
            print("[+] Файл JSON с покрытием должен быть готов.")
            break


if __name__ == "__main__":
    run_overseer()