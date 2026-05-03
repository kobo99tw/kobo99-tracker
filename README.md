# 📚 Kobo 每日 99 書單追蹤器

自動抓取 Kobo 每週 99 書單，並整合**博客來**與 **Goodreads** 評分，每週四 11:00（台灣時間）自動更新。

## 專案結構

```
kobo99-tracker/
├── .github/
│   └── workflows/
│       └── weekly-scrape.yml   ← 自動排程（GitHub Actions）
├── scraper/
│   ├── scrape.py               ← 主要爬蟲程式
│   └── requirements.txt
├── data/
│   ├── latest.json             ← 最新一週書單（前端讀這個）
│   └── books-2026-w18.json     ← 歷史紀錄（每週一個檔案）
└── public/
    └── index.html              ← 前端頁面
```

## URL 規律

```
https://www.kobo.com/zh/blog/weekly-dd99-{年份}-w{ISO週次}
例：https://www.kobo.com/zh/blog/weekly-dd99-2026-w18
```

每週四 11:00 公布，GitHub Actions 於 11:00（UTC+8）自動抓取。

## 快速開始

### 1. Fork 這個 repo

### 2. 設定 GitHub Pages（前端）

Settings → Pages → Source：`main` 分支 `/public` 資料夾

### 3. 本機測試爬蟲

```bash
cd scraper
pip install -r requirements.txt
python -m playwright install --with-deps chromium

# 抓本週書單
python scrape.py

# 手動指定週次（測試用）
python scrape.py 2026 18
```

### 4. 確認 Actions 權限

Settings → Actions → General → Workflow permissions  
→ 勾選 **Read and write permissions**

## 評分來源

| 平台 | 來源 | 說明 |
|------|------|------|
| 博客來 | 搜尋頁面第一結果 | 以書名搜尋，取第一筆 |
| Goodreads | Google 搜尋摘要 | `site:goodreads.com` 搜尋 |

> ⚠️ 評分為自動抓取，若書名在博客來搜尋結果不精確，可能對應到錯誤書目。

## 手動觸發

GitHub repo → Actions → 「每週四自動抓 Kobo 99 書單」→ Run workflow  
可輸入年份與週次手動指定。

## 常見問題

**Q：爬蟲回傳 403 怎麼辦？**  
A：已使用 Playwright（模擬真實 Chrome 瀏覽器），基本上可以繞過。若仍有問題，可在 `scrape.py` 中的 `fetch_kobo_page()` 加入更長的等待時間。

**Q：解析結果少於 7 本書？**  
A：表示 Kobo 頁面格式可能有變動。可在 `parse_kobo_books()` 中調整 regex。

**Q：如何加入更多評分平台？**  
A：在 `run()` 函式中仿照 `get_books_com_rating()` 新增即可。
