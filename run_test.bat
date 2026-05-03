@echo off
echo.
echo =============================================
echo   Kobo99 Scraper - Setup and Test
echo =============================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b
)

echo [OK] Python found:
python --version
echo.

echo [1/3] Installing packages...
pip install playwright requests beautifulsoup4 lxml -q
if errorlevel 1 (
    echo [ERROR] Package install failed. Check your internet connection.
    pause
    exit /b
)
echo [OK] Packages installed
echo.

echo [2/3] Installing Playwright browser (first time takes a few minutes)...
python -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] Browser install failed.
    pause
    exit /b
)
echo [OK] Browser installed
echo.

echo [3/3] Running scraper...
echo.
python scraper\scrape.py
if errorlevel 1 (
    echo.
    echo [ERROR] Scraper failed. Please screenshot the error above and send to Claude.
) else (
    echo.
    echo =============================================
    echo   Done! Check data\latest.json for results.
    echo =============================================
)

pause
