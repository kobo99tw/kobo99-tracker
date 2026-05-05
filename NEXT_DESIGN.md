# NEXT_DESIGN — 待解決問題與改進方向

## 已完成（v11，2026-05-05）

### ✅ 本機預覽伺服器（scraper/preview.py）
- Flask port 8099，點 `本機預覽.bat` 啟動
- 控制面板：手動輸入 URL、即時 log 輪詢、抓完預覽書單
- 背景 thread + /api/log 輪詢架構（取代不穩定的 SSE）

### ✅ 自動發現書單 URL（_resolve_weekly 三層）
- 主頁關鍵字「一週99書單」+日期範圍比對 → URL 格式 → 公式 fallback
- scrape.py 加 --url 參數

### ⚠️ 待確認
- preview.py 按鈕執行紀錄尚未完整驗證（快取問題待用戶重啟後確認）

---

## 已完成（v10，2026-05-05）

### ✅ 日期提取架構改寫（文字節點順序掃描）
- 以 `soup.descendants` 頁面順序追蹤 `M/D週X` 日期，不再走 DOM 上找
- 移除 `_book_date` 位置推算 fallback，完全以網頁內容為準

### ✅ 特賣週期修正（+7 → +6 天）
- Kobo 每週特賣為週四到下週三（7 天），sale_end 已修正

### ✅ 前端 todayMD / fmtDate 改用 Intl API
- 跨瀏覽器取台灣日期更可靠

---

## 已完成（v9，2026-05-04）

### ✅ OG 標籤 + OG 圖片
- og:title / description / image / url / locale / twitter:card 全部到位
- og-image.png：1200×630，深色背景橘色 99

### ✅ Favicon 橘色 99
- 與 OG 圖統一風格

### ✅ 錯誤回報按鈕
- header 加 Google 表單連結（ghost button）

### ✅ sitemap lastmod
- Actions 每週自動更新

### ✅ 收藏 / 已讀標記（localStorage）
- 🔖 收藏 / ✅ 已讀 按鈕，重整不消失
- 只看收藏篩選

### ✅ 分享按鈕
- 📤 分享，手機 Web Share API，電腦複製剪貼簿

### ✅ ICS 日曆
- 爬蟲自動產生 docs/calendar.ics
- 描述含書名 / 原價 / 購買連結 / 網站回流連結
- toolbar 📅 日曆按鈕 + modal 分平台說明

### ✅ 按鈕文字標籤
- 🔖 收藏 / ✅ 已讀 / 📤 分享 加文字，手機也直覺

---

## 已完成（v7–v8）

### ✅ 上傳 GitHub + GitHub Pages
### ✅ GitHub Actions 每週自動排程（每週四 11:00）
### ✅ Ko-fi 真實帳號
### ✅ 今日特價書卡標示（橘色橫幅 + 邊框）
### ✅ Goodreads 連結準確性（跟進書頁解析）
### ✅ 博客來改為電子書評分（cat/EK）
### ✅ 書本特價日期從部落格 HTML 解析
### ✅ 書單排序：今日 → 未來 → 過去
### ✅ favicon 優化、manifest.json 新增

---

## 下一步改善方向

### 🟡 待討論
- **ICS webcal 訂閱**：用 webcal:// 協定讓用戶訂閱一次自動更新，但會減少回訪流量，暫緩

### 🟢 長期
- 評分歷史趨勢（多週資料比較）
- Goodreads/Amazon 書名驗證（目前無，影響少數書，低優先）

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
| sale_end 算成下週四 | `+7天` = 週四→週四 | 改 `+6天`，週四→週三（正確 7 天特賣期）|
| 日期從 DOM 上走取不到 | 容器大於 2000 字就停 | 改以文字節點頁面順序掃描，不靠 DOM 祖先 |
| Playwright + ThreadPoolExecutor 衝突 | sync API 用 greenlet，不能跨執行緒 | 改直接呼叫 + `_timed()` wrapper |
| Goodreads 評分與連結不一致 | 從搜尋頁取評分，連結取第一本書 | 搜尋頁找連結→跟進書頁解析 |
| Amazon .co.jp 評分誤抓整數 | `re.search(r"(\d+\.?\d*)")` 會匹配 "5" | 改 `re.findall(r"\d+\.\d+")` 只取小數 |
| public/ 路徑與 docs/ 衝突 | GitHub Pages 改用 /docs 選項 | 全面改 `docs/`，workflow 同步更新 |
| GitHub push 被拒 | 遠端 repo 有 README 初始 commit | `git pull --allow-unrelated-histories` 再 push |
