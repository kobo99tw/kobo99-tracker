# NEXT_DESIGN — 待解決問題與改進方向

## 已知問題（需修正）

### 1. ~~博客來評分全數失敗~~ → **v6 重新實作成功**
- 搜尋：`search.books.com.tw`（不走 `books.com.tw`，避免 Cloudflare）
- Product page：`Browser.get_fresh()` 每次新 context 繞過 Cloudflare session 限制
- 搜尋用「書名 + 作者」（不用 ISBN；只取紙本 ID，排除 E 開頭電子書）

### 2. ~~Goodreads via Google 被封鎖~~ → 已修正（v3）
- 改直連 Goodreads：ISBN 直連 + 英文作者名搜尋
- 3/8 成功（有英文作者的翻譯書）

### 3. ~~Kobo 只抓原價~~ → 已整合評分與分類（v4）
- 從 `RatingAndReviewWidget` Schema.org JSON 取評分、分類、雙語作者
- 3/8 有評分（部分書在 Kobo 評分數為 0，可能因書太冷門）

### 4. ~~讀墨書名比對取到錯書~~ → 已修正（v5）
- 改用 `SequenceMatcher` 對所有候選算相似度，取最高分 >= 0.4；不做盲目 fallback
- W17 原本找不到的 3 本（地緣政治輕鬆讀、信心的博弈、物理之舞）確認是**不在讀墨上**，非比對問題

### 5. ~~Goodreads 英文作者搜尋取到錯誤書~~ → 部分改善（v5）
- 新增策略一·五：從讀墨書頁抓原文書名，優先以原文書名搜 Goodreads
- 仍有局限：讀墨書頁未必有「原文書名」欄位（日文、純繁體原創書無此欄）

### 6. ~~Kobo 原價偶爾抓錯~~ → v6 改為取「第一個 NT$ > 99」
- 改為取頁面第一個出現的 NT$（顯示價），不取最大值
- 理由：用戶希望顯示「網頁點開看到的價格」

### 7. ~~Step 4 未在 v6 完整驗證~~ → v6 最終測試已跑（W17、W18 兩週）

---

## 下次要做的事（v7）

### 優先順序

#### 🔴 上線前必做
1. **上傳 GitHub + 開啟 GitHub Pages**
   - `git init` → `git add` → `git commit` → push 到 GitHub
   - 開啟 GitHub Pages，設定 source 為 `main` 分支的 `/public` 資料夾
   - 確認 `https://{user}.github.io/{repo}/` 可正常讀到 `data/latest.json`

2. **設定每週四自動排程（GitHub Actions）**
   - 建立 `.github/workflows/weekly.yml`
   - cron：`0 3 * * 4`（每週四 UTC 03:00 = 台灣時間 11:00）
   - 步驟：checkout → setup python → pip install → playwright install → run scraper → git add/commit/push
   - 設定 `headless=True`（已完成）、`sys.exit(1)` 防止空書單寫入（已完成）

3. **Ko-fi 換上真實帳號**
   - 把 `index.html` 裡 `YOUR_KOFI_ID` 換成真實帳號名稱

#### 🟡 前端改善
4. **書卡日期重設計（今天/明天/已結束邏輯）**
   - 今天特價的書：橘紅色標籤 + 邊框突出
   - 未來特價：綠色小標籤
   - 已結束：灰色、opacity 降低、購買按鈕改「已結束」
   - 注意：`date` 欄位現在正確從週四起算，可以安全做這個判斷

5. **統計列加「今天特價：《書名》」**
   - `books.find(b => b.date === today_md)` 取今天的書，顯示在統計列

#### 🟢 長期改善
6. Goodreads ISBN 跨版本：用原文書名搜（比 ISBN 更穩定）
7. 書籍收藏 / 已讀標記（localStorage）
8. 「低評論數警告」⚠️（已實作，可微調 UI）

---

## 改進方向

### A. ~~Readmoo 書名比對強化~~ → v6 已用 SequenceMatcher 完成
### B. ~~Goodreads ISBN 跨版本~~ → 待 v7
### C. 前端新功能
- ~~加入書籍類型/分類標籤~~ ✅ v6
- ~~顯示原文書名~~ ✅ v5
- ~~低評論數警告~~ ✅ v6
- 書籍收藏 / 已讀標記（localStorage）→ v7+
### D. ~~書單完整性驗證~~ ✅ v5

---

## 踩雷紀錄（避免重複）

| 問題 | 原因 | 解法 |
|------|------|------|
| `kobo.com/zh/ebook` 找不到連結 | 實際 URL 是 `/tw/zh/ebook/` | 改用 `/ebook/` 過濾 |
| `《書名》` 解析不到 | 正則要求 `月/日` 前綴 | 改為偵測獨立行 `^《..》$` |
| `networkidle` 逾時（個別書籍頁）| Cloudflare 不會讓 network 完全空閒 | 改 `domcontentloaded` + `sleep(3)` |
| 讀墨 URL 雙重前綴 | `href` 已含 `https://readmoo.com` | 用 `startswith("http")` 判斷 |
| Windows 終端機 UnicodeEncodeError | CP950 無法顯示 emoji | `sys.stdout.reconfigure(encoding="utf-8")` |
| 前端 `../data/` 404 | GitHub Pages `/public` 為根目錄，上層路徑不存在 | 改 `DATA_DIR` 為 `public/data/`，前端用 `data/latest.json` |
| 原價 `wait_for_selector` 逾時 | Cloudflare 頁元素存在但不可見 | 改為直接從全文取最大 NT$ 數字 |
| 日期欄位空白 | 新解析邏輯未帶回日期 | 從 `<title>` 解析週次日期範圍 |
| 博客來評分全部 None | 搜尋結果 JS 動態載入，requests 只拿到空殼 | 移除博客來，改善讀墨 + Goodreads |
| 讀墨評分全部 None | 評分在 `data-score` 屬性，不在文字中 | 改用 Playwright + `#star[data-score]` 選擇器 |
| Goodreads via Google 被 429 | Google 偵測爬蟲 | 改直連 Goodreads 搜尋（不走 Google）|
| Kobo 評分、分類未抓取 | 資料藏在 `RatingAndReviewWidget` JSON，沒有另外解析 | 改用 `fetch_kobo_book_data()` 同時取原價+評分+分類 |
| cloudscraper 無法繞過博客來 | cloudscraper 2025/02 被棄用，Cloudflare 已可偵測 | 確認博客來無解，不再嘗試 |
| 博客來 product page 第二次被 Cloudflare 擋 | 同一 browser session 重複造訪 books.com.tw | `Browser.get_fresh()` 每次建全新 context |
| 博客來搜尋不支援 ISBN | books.com.tw 搜尋 API 不索引 ISBN | 改用書名+作者搜尋 `search.books.com.tw` |
| 書本特賣日期算錯 | 用 ISO 週一 + index，但 Kobo 99 從週四開始 | `sale_start = Date.fromisocalendar(y, w, 4)`（週四）|
| Playwright + ThreadPoolExecutor 衝突 | Playwright sync API 用 greenlet，不能跨執行緒呼叫 | 改用直接呼叫 + 時間測量，timeout 由 Playwright 內建執行 |
| 前端 JS 殘留變數導致 render() 完全不執行 | 多次 Edit 時有 `}` 和 `banner` 宣告沒清乾淨 | 修改前先整段 Read 確認，避免孤立 token |
