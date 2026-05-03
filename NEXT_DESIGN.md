# NEXT_DESIGN — 待解決問題與改進方向

## 已完成（v7 全部上線）

### ✅ 上傳 GitHub + GitHub Pages
- Repo：https://github.com/kobo99tw/kobo99-tracker
- 網站：https://kobo99tw.github.io/kobo99-tracker/
- 資料夾：`docs/`（GitHub Pages /docs 選項）

### ✅ GitHub Actions 每週自動排程
- cron：`0 3 * * 4`（每週四 UTC 03:00 = 台灣 11:00）
- 自動跑爬蟲、commit `docs/data/`、push

### ✅ Ko-fi 換上真實帳號
- `https://ko-fi.com/kobo99tw`

### ✅ 今日特價書卡標示
- 橘色橫幅（含日期）、橘色邊框、今日特價永遠排第一

### ✅ Goodreads 連結準確性
- 搜尋頁找連結後跟進書頁解析，確保評分＝連結是同一本書

### ✅ 博客來改為電子書評分
- 搜尋 `cat/EK`，只取 E 開頭 product ID

---

## 待確認（使用者端）

1. **GitHub Pages 啟用**：Settings → Pages → Branch: main / Folder: /docs
2. **Actions 寫入權限**：Settings → Actions → General → Read and write permissions
3. **首次手動觸發 Actions**：確認完整流程正常

---

## 下一步改善方向

### 🟡 爬蟲穩定性
- Actions 排程 11:00 可能太早（Kobo 部落格發文時間不確定），評估改為 15:00（UTC 07:00）
- Goodreads/Amazon 仍無書名驗證，搜尋第一筆結果不一定是正確書本

### 🟡 前端功能
- 書籍收藏 / 已讀標記（localStorage）
- 「已結束特價」書卡 opacity 降低或移到最後

### 🟢 長期
- 評分歷史趨勢（多週資料比較）
- Google Search Console 提交 sitemap

---

## 踩雷紀錄（避免重複）

| 問題 | 原因 | 解法 |
|------|------|------|
| `kobo.com/zh/ebook` 找不到連結 | 實際 URL 是 `/tw/zh/ebook/` | 改用 `/ebook/` 過濾 |
| `《書名》` 解析不到 | 正則要求 `月/日` 前綴 | 改為偵測獨立行 `^《..》$` |
| `networkidle` 逾時（個別書籍頁）| Cloudflare 不會讓 network 完全空閒 | 改 `domcontentloaded` + `sleep(3)` |
| 讀墨 URL 雙重前綴 | `href` 已含 `https://readmoo.com` | 用 `startswith("http")` 判斷 |
| Windows 終端機 UnicodeEncodeError | CP950 無法顯示 emoji | `sys.stdout.reconfigure(encoding="utf-8")` |
| 前端 `../data/` 404 | GitHub Pages `/public` 為根目錄 | `DATA_DIR` 改 `docs/data/`，前端用 `data/latest.json` |
| 原價 `wait_for_selector` 逾時 | Cloudflare 頁元素存在但不可見 | 改為直接從全文取第一個 NT$>99 數字 |
| 博客來評分全部 None | 搜尋結果 JS 動態載入 | `get_fresh()` 每次新 browser context |
| 博客來搜尋不支援 ISBN | books.com.tw 搜尋 API 不索引 ISBN | 改用書名+作者搜尋 |
| 書本特賣日期算錯 | 用 ISO 週一 + index | `sale_start = Date.fromisocalendar(y, w, 4)`（週四）|
| Playwright + ThreadPoolExecutor 衝突 | sync API 用 greenlet，不能跨執行緒 | 改直接呼叫 + `_timed()` wrapper |
| Goodreads 評分與連結不一致 | 從搜尋頁取評分，連結取第一本書 | 搜尋頁找連結→跟進書頁解析 |
| Amazon .co.jp 評分誤抓整數 | `re.search(r"(\d+\.?\d*)")` 會匹配 "5" | 改 `re.findall(r"\d+\.\d+")` 只取小數 |
| public/ 路徑與 docs/ 衝突 | GitHub Pages 改用 /docs 選項 | 全面改 `docs/`，workflow 同步更新 |
| GitHub push 被拒 | 遠端 repo 有 README 初始 commit | `git pull --allow-unrelated-histories` 再 push |
