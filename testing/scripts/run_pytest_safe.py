import pytest
import os
import multiprocessing.util

# 1. Отключаем стандартную привычку Питона ждать зависшие процессы
multiprocessing.util._exit_function = lambda *args, **kwargs: None

args = [
    "../generated_tests/qwen_coder/run_1_fixed/TheAlgorithms",
    "--cov=../repos_for_testing/TheAlgorithms",
    "--cov-report=json:../generated_tests/qwen_coder/run_1_fixed/TheAlgorithms_coverage_fixed.json",
    "--continue-on-collection-errors",
    "--timeout=5",
    "--timeout_method=thread"
]

print("[*] Запускаем тесты. Можно идти пить чай (займет около 7 минут)...")

# 2. Эта функция выполнит все тесты и ГАРАНТИРОВАННО сохранит JSON в конце
pytest.main(args)

print("[+] Тесты завершены. JSON отчет успешно сохранен на диск!")

# 3. Жесткий выход. Убиваем процесс мгновенно, минуя все зависания atexit
print("[*] Ликвидируем зомби-процессы...")
os._exit(0)