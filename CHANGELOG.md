# CHANGELOG

## [2026-05-03 v6] — 爬蟲全面重寫、前端重設計、逐本逾時保護

### 爬蟲（scrape.py）

**架構改變**
- Step 1：部落格同時取書名 + 直接 Kobo URL（不再搜尋）
- Step 2：直接進每本書頁抓資料（selector 全部依 debug HTML 驗證）
- Step 2+3+4 合併為單一逐本迴圈，每本書完成後印進度列

**Kobo 書頁 selector**
- 原文書名：`h1.find_next_sibling()`，接受英/日/韓，純中文略過
- 作者：`.contributor-name`（不含「由作者」前綴）
- 評分：`#RatingsBrief .rating-average`
- 評分人數：`span#total-number-of-ratings`
- ISBN/出版社/日期/語言：`.bookitem-secondary-metadata` 逐行解析

**博客來重新實作**（v3 曾確認無解，v6 找到繞法）
- 搜尋：`search.books.com.tw` + 書名+作者（不用 ISBN）
- Product page 用 `br.get_fresh()`（每次新 browser context 繞 Cloudflare session 限制）
- 評分：`.guide-score .average` / `.guide-score .sum`，只取紙本（排除 E 開頭 product ID）

**讀墨 selector 修正**：評分人數改 `.quick-btn-star span`

**逾時保護**：`_timed()` wrapper + Playwright 內建 timeout，各平台有獨立上限

**特賣日期**
- `sale_start` 改用 ISO 週的**週四**（Kobo 99 從週四開始，原本錯用週一）
- `get_weekly_url()` 預設取最近週四的 ISO 週號
- 每本書加 `date` 欄位（`M/D`，依部落格排序從週四起算）
- `sale_label` 正確格式：「NT$99 特價：4/30（四）～5/7（四）」

**其他**
- `Browser.get_fresh()`：新增，每次建全新 context
- `測試執行.bat` → 純 ASCII，呼叫 `scraper/run_local.py`（解決 Windows 亂碼）
- Amazon 從 `.co.jp` 改為 `.com`
- `headless=True`（已還原）

### 前端（public/index.html）

- 5 個評分來源全部顯示（Kobo / 博客來紙本 / 讀墨 / Goodreads / Amazon）
- 評分數字可點擊連到各平台頁面
- 評論數 < 10 顯示 ⚠️ 提示
- 分類標籤（genre）
- 日期小標籤（`M/D（X）`）顯示在每張書卡右上
- 統計列：本週 N 本 / 強推 N 本 / 最高省 NT$N
- 排序：書單順序 / 綜合評分 / 博客來 / Goodreads / Amazon / 折扣幅度
- `fetch("data/latest.json")`（修正 v2 的路徑 bug）
- 手機單欄 (< 520px)

### 測試結果（W17、W18 各跑一次）

| 來源 | W17 | W18 |
|------|-----|-----|
| kobo | 3/8 | 4/8 |
| books_com | 4/8 | 6/8 |
| readmoo | 2/8 | 4/8 |
| goodreads | 3/8 | 5/8 |
| amazon_com | 3/8 | 5/8 |
| 總時間 | 4m43s | 5m03s |

---

## [2026-05-02 v5] — 讀墨比對強化、Goodreads 原文書名、書單驗證

### 改動動機
- 讀墨搜尋 fallback 取第一筆結果，可能指向不相關的書
- Goodreads 以作者名搜尋取到作者最熱門書，不一定是本次翻譯書
- W18 曾只抓到 1 本，但程式不告警就靜默寫出殘缺資料

### 新功能
1. **讀墨 `SequenceMatcher` 比對**：對所有 `/book/<id>` 候選連結算相似度，取最高分且 >= 0.4 者；低於閾值不做盲目 fallback，直接回傳空（寧缺勿錯）
2. **Goodreads 策略一·五（原文書名）**：從讀墨書頁抓「原文書名：XXX」欄位，優先以原文書名搜 Goodreads，比作者名搜尋精準；`note` 標記 `"original_title"`
3. **書單完整性驗證**：書本數 < 5 時 `print` 警告並 `sys.exit(1)`（讓 GitHub Actions 標記失敗、不寫檔）
4. **前端顯示原文書名**：書名下方加斜體小字顯示 `original_title`；`grLabel` 補上 `"original_title"` 判斷

### 測試結果（W18，8本）
- 書單驗證：正常通過（8 本 >= 5）
- 讀墨：神曲 5.0；其餘 7 本不在讀墨（非比對問題）
- Goodreads：神曲 4.05、問題不是從你開始的 3.55（均走 eng_author）

---

## [2026-05-02 v4] — Kobo 書頁 Schema.org 評分、分類標籤

### 改動動機
- 研究 Calibre Kobo-Metadata plugin 原始碼，發現 Kobo 書頁本身在 `RatingAndReviewWidget` 的 `data-kobo-gizmo-config` 屬性中內嵌 Schema.org JSON
- 該 JSON 包含 Kobo 自己的評分（ratingValue / ratingCount）、分類（genre）、雙語作者名
- 我們已在用 Playwright 訪問每本書的 Kobo 頁面抓原價，直接同時抓就好，零額外成本

### 新功能
1. **Kobo 評分**：從 `RatingAndReviewWidget` Schema.org JSON 取 `ratingValue` + `ratingCount`，加入 `ratings.kobo`
2. **分類標籤 genre**：從同一 JSON 取書籍分類（如心理學、愛情、政治學），前端以小標籤顯示
3. **原文作者補強**：`workExample.author` 中同時有中英文作者，可補充讀墨沒抓到原文作者的書
4. **前端新增 Kobo 評分列**、分類標籤顯示、排序選項「Kobo ↓」
5. **`fetch_kobo_original_price` 合併為 `fetch_kobo_book_data`**：同一次訪問取原價 + 評分 + 分類

### 測試結果（W17，8本）
- Kobo 評分：3/8（地緣政治 4.17、快樂處方 4.65、裝幀師 3.92）
- 讀墨：5/8，Goodreads：3/8
- 每本書最多三個評分來源

---

## [2026-05-02 v3] — 讀墨 Playwright 化、Goodreads 直連、新增書籍 metadata

### 改動動機
- 博客來搜尋結果為 JS 動態載入，`requests` 無法抓取，已確認無解 → 移除
- 讀墨評分也是 JS 渲染（`data-score` 屬性），改用 Playwright 才能正確取得
- Goodreads 原本走 Google 搜尋，被 429 擋下 → 改直連 Goodreads 網站
- 加入 `isbn`、`word_count`、`publish_year`、`original_author` 等欄位，輔助購書決策

### 新功能
1. **讀墨改用 Playwright**：從書頁 `#star[data-score]` 直接取評分，`span[itemprop=ratingCount]` 取評論數
2. **原文作者擷取**：讀墨書頁有「原文作者」欄位，自動抓取英文作者名（如 Anders Hansen）
3. **Goodreads 直連**：
   - 優先用 ISBN → `goodreads.com/book/isbn/<isbn>`
   - 備用用英文作者名 → `goodreads.com/search?q=<author>`（取第一筆結果）
   - 完全不走 Google（Google 已封鎖爬蟲）
4. **新增 JSON 欄位**：`isbn`、`word_count`（字數）、`publish_year`、`original_author`
5. **avg_score 加權**：改以評論數為權重，評論越多的來源影響越大
6. **前端更新**：移除博客來欄位，加入字數標籤（X萬字）與出版年，Goodreads 標示「原著」

### 測試結果（W17，8本）
- 讀墨評分：5/8 成功（地緣政治輕鬆讀、信心的博弈、物理之舞 不在讀墨上）
- Goodreads：3/8 成功（有英文作者名的翻譯書）

---

## [2026-05-01 v2] — 路徑修正、原價抓取、日期解析

### 問題根源
- **前端 404**：`fetch("../data/latest.json")` 在 GitHub Pages `/public` 根目錄下找不到上層 `data/`
- **原價全失敗**：`wait_for_selector` 等待 visible 但 Kobo 特價頁元素存在卻不可見
- **日期欄位空白**：`<title>` 中的日期沒有被解析回填

### 修正內容
1. `DATA_DIR` 改為 `public/data/`，前端改為 `fetch("data/latest.json")`
2. GitHub Actions `git add public/data/` 同步更新
3. 原價改為從完整頁面文字擷取所有 `NT$` 數字取最大值（原價）
4. 日期從 `<title>` 標籤解析「（M/D-M/D）」格式，fallback 掃前 30 行
5. 移除重複的 `import sys`

### 測試驗證
- W17：8 本書全部取得原價（NT$266～NT$1295），日期欄位 "4/23-4/29"

---

## [2026-05-01] — 解析邏輯全面修正

### 問題根源
- **Cloudflare 驗證未完成**：`wait_until="domcontentloaded"` 太早，Cloudflare JS 挑戰頁尚未完成就擷取 HTML
- **解析模式錯誤**：正則要求 `數字/數字《書名》` 格式，但實際頁面是 `《書名》` 獨立成行
- **連結過濾錯誤**：過濾 `kobo.com/zh/ebook` 但實際 URL 為 `kobo.com/tw/zh/ebook`
- **讀墨 URL 拼接 bug**：`href` 已是完整 URL，卻再次加上 `https://readmoo.com` 前綴
- **UnicodeEncodeError**：終端機 CP950 無法編碼 ✅ emoji

### 修正內容
1. `fetch_kobo_blog`：`domcontentloaded` → `networkidle`（讓 Cloudflare 驗證完成）
2. `parse_kobo_books`：重寫解析邏輯，改為偵測 `^《[^》]+》$` 獨立書名行
3. 連結過濾：改為 `/ebook/` + `kobo.com` 雙條件，排除香港版 `/hk/` 連結
4. 讀墨 URL：加入 `href.startswith("http")` 判斷，避免重複加前綴
5. 加入 `sys.stdout.reconfigure(encoding="utf-8")` 解決 Windows CP950 問題
6. `fetch_kobo_original_price`：改用 `domcontentloaded` + `time.sleep(2)` 兼顧速度與 Cloudflare

### 測試驗證
- W17（2026-w17）：成功解析 8 本書，所有書籍均取得 Kobo 連結與作者

---

## [初始版本] — v2 基礎功能

- 每週四自動抓取 Kobo 99 書單
- 整合博客來、讀墨、Goodreads 評分
- 抓取 Kobo 原價（劃掉的定價）
- 輸出 `data/latest.json` 與 `data/books-{year}-w{week}.json`
