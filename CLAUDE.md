# CLAUDE.md — kobo99-tracker 專案說明

每次開啟此專案時自動載入，讓 Claude 快速了解背景。

---

## 專案簡介

**Kobo 每週 99 特價書單** — 每週自動抓取 Kobo 台灣 99 元特價電子書，整合博客來、讀墨、Goodreads、Amazon 四大平台評分，幫助讀者快速找到 CP 值高的好書。

- **正式網址**：https://kobo99.com
- **GitHub Repo**：https://github.com/kobo99tw/kobo99-tracker
- **托管**：GitHub Pages（docs/ 目錄）
- **GitHub 帳號**：kobo99tw

---

## 技術架構

```
kobo99-tracker/
├── scraper/
│   ├── scrape.py        # 主爬蟲（Playwright）
│   └── preview.py       # 本機預覽伺服器（Flask port 8188）
├── docs/                # GitHub Pages 根目錄
│   ├── index.html       # 前端（純 HTML/CSS/JS，無框架）
│   ├── data/
│   │   ├── latest.json  # 當週書單資料
│   │   └── corrections.json  # 手動修正永久記錄
│   └── calendar.ics     # ICS 日曆
└── .github/workflows/
    └── weekly-scrape.yml  # 每週四 10:00 台灣時間自動執行
```

---

## 本機開發流程

1. 啟動預覽伺服器：`python scraper/preview.py`
2. 開啟 Admin 面板：http://localhost:8188/admin
3. 抓取書單 → 審查資料 → 手動修正 → 發佈到 GitHub

---

## 重要慣例

- **每次 commit 前必須同步更新** `CHANGELOG.md` 和 `NEXT_DESIGN.md`
- 網址一律使用 `https://kobo99.com`（已從 github.io 遷移完成）
- corrections.json 會在下次重爬時自動套用手動修正，不要刪除

---

## SEO 現況（2026-05-14）

- 搜尋「Kobo 每週 99 書單」排名：第 3 頁第 1 名
- Google Search Console：kobo99.com 已驗證，Sitemap 狀態成功
- 技術 SEO 完整：canonical、JSON-LD、OG、sitemap、robots.txt、PNG favicon
- 最大待辦：PTT / Dcard 發文取得反向連結

### 踩雷紀錄
- Sitemap 在 github.io 子目錄長期顯示「無法讀取」→ 根本原因是共用網域限制，換自訂網域後 5 分鐘解決
- Google 搜尋結果無 favicon → SVG 不穩定，改用 PNG（48/96/192px）解決

---

## 網域資訊

- 域名：kobo99.com
- 購於：Cloudflare Registrar，$10.46/年，自動續約
- DNS：Cloudflare，CNAME @ → kobo99tw.github.io（僅 DNS，非 Proxy）

---

## 使用者說明

- 使用繁體中文溝通
- 非工程師背景，操作步驟需逐步說明
- 回應請簡短直接
