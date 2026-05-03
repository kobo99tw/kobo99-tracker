@echo off
start "" python -m http.server 8080 --directory public
timeout /t 2 /nobreak > nul
start http://localhost:8080
echo Server running at http://localhost:8080
echo Close this window to stop the server.
pause
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080"') do taskkill /PID %%a /F > nul 2>&1
