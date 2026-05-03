"""
本機執行腳本：安裝套件 + 執行爬蟲
取代 測試執行.bat 的中文訊息，避免 Windows CMD 亂碼
"""
import sys
import subprocess

sys.stdout.reconfigure(encoding="utf-8")


def run(cmd: list[str], desc: str) -> bool:
    print(f"\n{desc}...")
    r = subprocess.run(cmd, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[錯誤] 失敗，請截圖錯誤訊息")
        return False
    print("[OK]")
    return True


print("=" * 48)
print("  Kobo 99 書單爬蟲 - 本機測試")
print("=" * 48)

# 確認 Python
r = subprocess.run([sys.executable, "--version"], capture_output=True, text=True)
print(f"\nPython: {r.stdout.strip()}")

# 安裝套件
if not run(
    [sys.executable, "-m", "pip", "install",
     "playwright", "requests", "beautifulsoup4", "lxml", "-q"],
    "[1/3] 安裝套件"
):
    sys.exit(1)

# 安裝 Playwright 瀏覽器
if not run(
    [sys.executable, "-m", "playwright", "install", "chromium"],
    "[2/3] 安裝 Playwright 瀏覽器（第一次需要幾分鐘）"
):
    sys.exit(1)

# 執行爬蟲
print("\n[3/3] 開始抓取本週書單...\n")
r = subprocess.run(
    [sys.executable, "scraper/scrape.py"],
    encoding="utf-8", errors="replace"
)

print()
if r.returncode != 0:
    print("[錯誤] 爬蟲執行失敗，請截圖錯誤訊息")
else:
    print("=" * 48)
    print("  完成！")
    print("=" * 48)
