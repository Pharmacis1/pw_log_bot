@echo off
chcp 65001 >nul
echo Starting PW Log Bot...

echo Loading configuration from .env...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do set %%a=%%b

echo 1. Launching Web App (Port %WEB_PORT%)...
start "Web App" cmd /k "venv\Scripts\uvicorn web_app:app --host 0.0.0.0 --port %WEB_PORT%"

echo 2. Launching Zrok Tunnel (%ZROK_SHARE_NAME%)...
start "Zrok Tunnel" cmd /k "zrok share reserved %ZROK_SHARE_NAME% --headless"

echo 3. Launching Telegram Bot...
start "Telegram Bot" cmd /k "venv\Scripts\python bot.py"

echo.
echo Bot started!
pause
