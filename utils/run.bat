@echo off
chcp 65001 > nul

:: Переходим в корень проекта (на один уровень выше папки utils)
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    echo Запуск проекта через виртуальное окружение...
    ".venv\Scripts\python.exe" "utils\code.py"
) else (
    echo [ВНИМАНИЕ] .venv не найден! Запуск через системный Python...
    python "utils\code.py"
)

if %errorlevel% neq 0 (
    echo.
    echo [ОШИБКА] Произошел сбой при выполнении программы.
    pause
)