# CHANGELOG

## [2026-05-07 v13] — Admin 大改版、corrections 系統、爬蟲準確度提升

### scraper/preview.py — Admin 面板全面改版
- **配色**：深色主題改為淺色高對比（#F5F3F0 背景、白色卡片），字體放大（.82–.95rem）
- **新欄位**：原價欄（可點擊編輯）、日期欄加星期幾（如 5/1(四)）
- **發佈按鈕**：改為常駐可見；抓完或修正後顯示「⬆」提示未發佈
- **編輯 popup 防呆**：改用背景遮罩，點遮罩自動儲存（而非關閉），取消按鈕才是放棄
- **連結處理**：移除格子上的直接連結（誤點問題），改在 popup 內「🔗 開啟」按鈕
- **Log 重複根治**：generation counter（`_pollGen`）過濾 stale async callback
- **「⬇ 拉取更新」修正**：改用 `git fetch + git checkout origin/main -- docs/data/`，強制覆蓋本機未 commit 的資料，不再被 uncommitted 變更擋住
- **「⏮ 版本歷史」新區塊**：列出近 15 次觸及資料的 commit，一鍵還原任一版本

### corrections.json 永久修正系統（scraper/）
- `api/patch`、`api/patch_book`：Admin 存檔時同步寫入 `docs/data/corrections.json`
- `_apply_corrections(books, y, w)`：每次重爬後、計算 avg_score 前套用，支援評分欄位（`goodreads` 等）與書本欄位（`_book.kobo_price`）
- ICS 在 Admin 存檔後立即重建，不需等下次排程

### 新舊資料對照系統（scraper/）
- 重爬前自動備份 `books-Y-wW-prev.json`
- `api/info` 同時回傳 prev 資料，admin 表格顯示：
  - **日期/書名變更 → 紅底**（最嚴重）
  - **原價/評分變更 → 橘底 + 舊值小字**
  - 表格上方「⚠ 變更摘要列」一次列出所有差異
- 編輯 popup 有舊值時顯示並提供「套用舊值」按鈕

### 爬蟲（scraper/scrape.py）— 評分準確度提升
- **_best_candidate()**：抽出 module 層級，SequenceMatcher 書名相似度選最佳匹配（Goodreads、Amazon 共用）
- **Goodreads**：搜尋取前 5 筆 → 比對 original_title 相似度 → 取最高分
- **Amazon（歐美 + 日文）**：搜尋取前 5 筆 → 比對相似度；修正 selector：`a.a-link-normal[href*='/dp/']`（取代錯誤的 `h2 a`，amazon.com 和 amazon.co.jp 同結構）

### 網站（docs/index.html）
- score=0 與 null 統一顯示為「暫無評分」
- 綜合評分徽章無資料時從「N/A」改為「—」

### 其他
- 刪除 `開啟網頁.bat`（功能已由 `本機預覽.bat` 涵蓋）
- 建立 `stable-v12` 備份分支

---

## [2026-05-06 v12] — Admin 書單審查表格、日期對應修正、資料手動修正

### scraper/preview.py — Admin 書單審查表格
- 抓取完成後自動顯示「書單資料審查」表格（日期 / 書名 / ISBN / 原文名 / 各來源評分+連結 / 綜合）
- **點擊任一評分格 → 編輯浮層**：可修改評分、筆數、連結，Enter 確認、Escape 取消、點外部自動關閉
- 新增 `/api/patch` endpoint：POST 修正單筆評分，寫回 `latest.json` + 週次 JSON，重算 `avg_score`
- `/api/info` 改回傳完整欄位（ISBN、原文名、各來源評分+URL）
- `_calc_avg()` 加權平均 helper（Python 側與 patch 共用）

### 爬蟲（scraper/scrape.py）— 日期對應錯位根治
- 舊法：以文字節點順序追蹤最新日期標記，但連結節點與書名出現順序不一致時仍會錯位
- 新法：**兩步驟**—先純文字預掃建立「書名 → 日期」對照表（正則過濾日期標記），再依對照表歸因，完全脫離 DOM 順序依賴

### 資料修正（W18 5/6「失智行為說明書」）
- `books_com.url`：補 `books.com.tw/products/0011007411`
- `goodreads.count`：254（誤）→ 4（正確）
- `amazon_com`：改為 Kindle 版連結（`B079K8SHW4`），評分 4.3/243（紙本誤抓）→ 3.9/65
- `avg_score`：3.76 → 3.87

### 其他修正
- Port 8099 衝突改為 8188；`開啟網頁.bat` localhost 改 127.0.0.1 解決 IPv6 優先問題

---

## [2026-05-05 v11] — 本機預覽伺服器、自動發現書單 URL

### 新增：scraper/preview.py（本機預覽伺服器）
- Flask（port 8099），點 `本機預覽.bat` 啟動
- `/admin`：控制面板，可手動輸入書單 URL、點按鈕抓取、即時看 log
- `/`：書單預覽，直接讀 docs/index.html + latest.json
- 背景 thread 執行爬蟲，前端每 300ms 輪詢 `/api/log` 取新 log 行
- 抓完後「📚 查看書單」按鈕亮起，可直接預覽結果

### 爬蟲（scraper/scrape.py）
- **自動發現書單 URL**：`_resolve_weekly()` 三層保護
  - 有 `--url` 參數 → 直接用
  - 自動模式 → 主頁找「一週99書單」+日期範圍（`M/D-M/D`）比對今天是否在範圍內
  - URL 格式 `weekly-dd99-YYYY-wNN` 作為備用
  - 公式計算作為最後 fallback
- 新增 `--url` CLI 參數，可直接指定文章 URL

### 新增：本機預覽.bat
- 自動安裝 Flask + 啟動 preview.py
- 舊的 `開啟網頁.bat` 修正資料夾名稱（public → docs）

---

## [2026-05-05 v10] — 日期提取架構改寫、特賣週期修正

### 爬蟲（scraper/scrape.py）

**日期提取方式根本改寫（重要）**
- 舊法：從每個連結往上走 DOM 7 層找日期，碰到 `len > 2000` 就停，容器大時完全抓不到
- 新法：以 `soup.descendants` 掃描全部文字節點，依頁面順序追蹤最新日期標記（`M/D週X`），連結自動套用其上方最近的日期 → 完全以網頁內容為準，不推論
- 移除 `_book_date(sale_start, i-1)` 位置推算 fallback（會在多書同天時全部錯位）
- 取不到日期時改印 `⚠️ 連結取不到日期` 警告，不靜默寫錯值

**特賣週期 bug 修正**
- `sale_end` 原為 `sale_start + 7天`（週四→下週四），實際 Kobo 特賣是週四到下週三共 7 天
- 改為 `sale_start + 6天`，`sale_label` 現正確顯示 5/6（三）而非 5/7（四）

### 前端（docs/index.html）

- **`todayMD` 可靠性**：原 `new Date(toLocaleString(...))` 跨瀏覽器解析不穩定，改用 `Intl.DateTimeFormat` API
- **`fmtDate` 年份**：改用台灣時區年份（`Intl.DateTimeFormat` 取得），避免跨年邊界顯示錯誤週幾

### 資料修正（W18 手動修正）

- `sale_end`：2026-05-07 → 2026-05-06
- `sale_label`：5/7（四）→ 5/6（三）
- 帶爸媽去日本 `date`：5/6 → 5/5（舊爬蟲誤判，今日特價書修正）
- calendar.ics：帶爸媽去日本事件從 20260506 → 20260505

---

## [2026-05-04 v9] — OG 標籤、日曆、收藏已讀、分享、UI 強化

### 前端（docs/index.html）

- **OG 標籤**：新增 og:title / og:description / og:image / og:url / og:locale / twitter:card，分享到 LINE/FB 有預覽
- **OG 圖片**：`docs/og-image.png`（1200×630，Gemini 設計，深色背景橘色 99）
- **Favicon**：`99` 改橘色（#F97316），與 OG 圖統一風格
- **錯誤回報按鈕**：header 加入「📝 回報錯誤」Google 表單連結（ghost button 樣式）
- **收藏 / 已讀標記**：每張書卡「🔖 收藏」「✅ 已讀」按鈕，localStorage 儲存，重整不消失；已讀書卡 opacity 0.5
- **只看收藏篩選**：toolbar 加「🔖 只看收藏」切換按鈕
- **分享按鈕**：「📤 分享」，手機用 Web Share API，電腦自動複製格式化文字到剪貼簿
- **按鈕加文字標籤**：三個 mark 按鈕改為「🔖 收藏 / ✅ 已讀 / 📤 分享」，手機也看得懂（移除 title tooltip）
- **日曆 modal**：toolbar 加「📅 日曆」按鈕，點開顯示下載說明（三星/Apple/Google/LINE 分平台）

### 爬蟲（scraper/scrape.py）

- **ICS 日曆產生**：新增 `generate_ics()`，爬蟲跑完自動輸出 `docs/calendar.ics`
- **ICS 格式**：RFC 5545 標準，全天事件，75 octet 折行，支援 Google/Apple/Outlook 訂閱
- **ICS 描述**：書名 / 原價 / 購買連結 / 查看當週各書評分（含網站回流連結）

### SEO / 部署

- **sitemap.xml**：加入 `<lastmod>`，Actions 每週更新書單時自動同步更新日期
- **Google Search Console**：sitemap 提交、重新讀取

---

## [2026-05-04 v8] — 日期修正、排序優化、UI 細節

### 爬蟲（scraper/scrape.py）

**書本特價日期 bug 修正（重要）**
- 原因：部落格同一天可能有多本書（W18 的 5/1 有兩本），位置序號算日期導致後續全部偏掉
- 修法：`fetch_books_from_blog()` 在找書名的同時，從同一 HTML 區塊解析 `M/D週X` 格式日期
- 主流程改為 `item.get("blog_date") or _book_date(sale_start, i-1)`（有日期用部落格日期，否則 fallback）
- W18 JSON 已手動修正（金钱博弈、神曲、品嘗的科學、問題不是從你開始的、帶爸媽去日本、失智行為說明書 共 6 本）

### 前端（docs/index.html）

- **書單排序**：書單順序改為「今日 → 未來 → 過去」（`dateVal()` 函式計算日期數值比較）
- **今日特價橫幅**：移除 `.today-date` 獨立樣式，整行統一字體，格式改為「🔥 今日特價 · 5/4（一）」
- **網頁標題**：簡化為 `<title>Kobo每日99</title>`
- **favicon**：移除書本圖示，「99」放大至 62px、垂直置中 y=65
- **manifest.json**：新增，name/short_name 設為 Kobo每日99，`<link rel="manifest">` 加入 HTML

---

## [2026-05-04 v7] — 國外評分重寫、前端全面改版、GitHub 部署

### 爬蟲（scraper/scrape.py）

**Step 4 國外評分全面重寫**
- 新增 `_detect_book_type(original_title)`：依原文書名字元判斷歐美書/日文書/韓文書/台灣本地書
- 每本書印出語言判斷結果：`《書名》→ 歐美書`
- 不再用 ISBN（台灣版 ISBN 國外查不到）

**Goodreads 重寫**
- 搜尋順序：書名+作者 → 書名 → 作者 → 無原文資訊
- 搜尋頁找連結後**跟進書頁解析評分**（確保評分與連結是同一本書，舊版從搜尋頁直接取）
- 台灣本地書直接跳過，回傳 `{"note": "無原文資訊"}`
- Timeout 15 秒

**Amazon 重寫**
- 歐美書：`amazon.com`，書名+作者 → 書名
- 日文書：`amazon.co.jp`，書名 → 作者
- 韓文書/台灣本地書：跳過
- 評分解析改用 `re.findall(r"\d+\.\d+", ...)` 避免誤抓整數
- Timeout 25 秒（原 15 秒，co.jp 較慢）

**博客來改為電子書**
- 搜尋分類 `cat/BK`（紙本）→ `cat/EK`（電子書）
- Product ID 過濾改為只取 E 開頭（電子書）
- Timeout 20 秒 → 30 秒

**Timeout 調整**
- `books_com`：20s → 30s
- `amazon`：15s → 25s

### 前端（docs/index.html）

**排版重設計**
- 格線：`repeat(auto-fill, minmax(300px,1fr))` → 固定 2 欄，max-width 960px
- 手機 breakpoint：520px → 640px
- 卡片底部 buy-row：價格左、「🛒 立即購買」按鈕右對齊
- 移除多餘的博客來/讀墨/GR 個別按鈕（評分列整行可點擊即可）

**字體全面放大**
- 平台名稱 `.r-src`：`.65rem` → `.78rem`
- 評分數字 `.r-val`：`.7rem` → `.82rem`
- 人數 `.r-cnt`：`.62rem` → `.72rem`
- 作者 `.book-author`：`.75rem` → `.82rem`
- 評分條：4px → 5px

**今日特價標示**
- 橘色橫幅（含日期）：`🔥 今日特價 5/3（日）`
- 橘色邊框 + 淡橘底色（`--sale: #F97316`，獨立於 teal 購買色）
- 今日特價書永遠排第一（不論排序方式）
- 日期標籤放大（`.85rem` → `.88rem`）

**其他**
- Header 顯示 `sale_label`（特賣期間，含「✅ 特賣中」或「已結束」）
- 博客來標籤改為「博客來」（去掉「紙本」字樣）
- Ko-fi 連結更新為 `https://ko-fi.com/kobo99tw`
- Footer 加入不蒜子瀏覽計數

### 部署

- 資料夾 `public/` 改名為 `docs/`（配合 GitHub Pages /docs 選項）
- `DATA_DIR` 更新為 `docs/data/`
- GitHub Actions workflow `public/data/` → `docs/data/`
- Repo 推上 GitHub：https://github.com/kobo99tw/kobo99-tracker
- 網站：https://kobo99tw.github.io/kobo99-tracker/
- `docs/sitemap.xml` 建立

### 測試結果（W18，8本）

| 來源 | 命中 | 備註 |
|---|---|---|
| kobo | 4/8 | 部分新書無評分 |
| books_com | 6/8 | 改電子書搜尋後首次測試 |
| readmoo | 4/8 | 正常 |
| goodreads | 6/8 | 台灣本地書×2 跳過 |
| amazon_com | 5/8 | 日文書超時×1 |
| 總時間 | ~5分 | |

---

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
