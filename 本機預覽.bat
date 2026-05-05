@echo off
chcp 65001 > nul
echo.
echo =============================================
echo   Kobo99 本機預覽伺服器
echo =============================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請先安裝 Python 3.10+
    pause
    exit /b
)

echo 安裝 Flask（若已安裝會自動跳過）...
pip install flask -q
echo.

echo 啟動預覽伺服器，瀏覽器會自動開啟控制面板...
echo 控制面板：http://localhost:8099/admin
echo 書單預覽：http://localhost:8099/
echo 按 Ctrl+C 停止伺服器
echo.
python scraper\preview.py

pause
