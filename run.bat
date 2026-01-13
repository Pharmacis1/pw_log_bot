@echo off
chcp 65001 >nul
echo Starting PW Log Bot...

echo 1. Launching Web App (Port 8000)...
start "Web App" cmd /k "venv\Scripts\uvicorn web_app:app --host 0.0.0.0 --port 8080"

echo 2. Launching Zrok Tunnel...
start "Zrok Tunnel" cmd /k "zrok share reserved requiem --headless"

echo 3. Launching Telegram Bot...
start "Telegram Bot" cmd /k "venv\Scripts\python bot.py"

echo.
echo !!! ВАЖНО !!!
echo Если Cloudflare выдаст новую ссылку (например https://random-name.trycloudflare.com),
echo скопируй её в файл .env и перезапусти бота!
echo.
pause
