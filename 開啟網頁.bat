@echo off
chcp 65001 > nul
start "" python -m http.server 8080 --directory docs
timeout /t 2 /nobreak > nul
start http://localhost:8080
echo 伺服器啟動：http://localhost:8080
echo 關閉此視窗即停止伺服器
pause
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080"') do taskkill /PID %%a /F > nul 2>&1
