@echo off
echo 🔄 Выполняется обновление...
cd /d "%~dp0"
git pull
echo ✅ Обновление завершено. Перезапуск через 3 секунды...
timeout /t 3 /nobreak >nul
start "" ".venv\Scripts\python.exe" "utils\code.py"