# NEXT_DESIGN — 待解決問題與改進方向

## 已完成（v17，2026-05-13）

### ✅ Sitemap「無法讀取」問題查明
- 全面診斷：HTTP 200、Content-Type application/xml、無 BOM、Googlebot UA 正常回應
- 根本原因：`github.io` 共用網域，Search Console 對子目錄資源有相容性限制，非技術問題
- 確認網站已被 Google 索引（`site:kobo99tw.github.io/kobo99-tracker` 有結果）
- 結論：Sitemap 錯誤不影響實際索引，可忽略

---

## 已完成（v16，2026-05-11）

### ✅ SEO 技術優化（docs/index.html）
- title / description 關鍵字強化
- canonical 標準網址宣告
- JSON-LD WebSite（靜態）+ ItemList（動態）結構化資料
- h1 語意標籤、noscript 備援內容

---

## 已完成（v15，2026-05-08）

### ✅ Admin panel SyntaxError 修復
- Python `"""` 字串 `\'` escape bug 導致 admin.js 整個不執行，書單審查表格不顯示
- 改用 data-hash/data-msg 屬性 + el.onclick 事件委派

### ✅ Amazon Kindle fallback
- 歐美書依序嘗試 stripbooks-intl-ship → digital-text，不再漏抓 Kindle-only 書

### ✅ Amazon 搜尋改用 GR 英文作者名
- fetch_goodreads 解析 en_author，優先傳給 fetch_amazon，避免中文譯名干擾，減少同名書抓錯

### ✅ robots.txt + .nojekyll 加入 docs/
- 改善 Google Sitemap 擷取問題

---

## 待辦

### 🔴 立即
- **失智行為說明書 Amazon 手動補值**：Admin 面板補入 3.9/65 + Kindle 連結，存入 corrections.json，發佈

### 🟡 SEO 成長（需持續推進）
- **PTT 書版 / 電子書版發文**：附連結，有效反向連結，提升搜尋排名
- **Dcard 書單版發文**：同上
- **自訂網域評估**：脫離 github.io 共用網域，長期 SEO 效益
- GSC Performance 是否開始有曝光/點擊數據（5/11 SEO 優化後 4–8 週觀察）

### 🟡 程式碼保護（視需求）
- 選項 A：GitHub Pro $4/月，repo 改私有（最簡單）
- 選項 B：拆成私有爬蟲 repo + 公開前端 repo（免費）

### 🟡 下次驗證
- corrections.json 有無正確套用於新週次（W20 起觀察）
- Amazon en_author 萃取是否正確運作（W20 起觀察）
- 《系統思考》GR count 137 是否正確（原 80137，懷疑有截斷）
- 《告訴我你吃什麼》GR count 2596 是否正確（原 892596）

### 🟢 長期
- 評分歷史趨勢（多週資料比較）
- ICS webcal:// 一鍵訂閱（暫緩）

---

## 已完成（v14，2026-05-07）

### ✅ W19 書單上線（手動跑爬蟲）
- 8 本書完整資料，多項手動修正（日期、Amazon 錯誤書、GR count）

### ✅ Goodreads 評論數解析 Bug 修正
- 舊方法：抓頁面第一個 `N ratings`，常誤抓作者/系列總評論數（如 153M）
- 新方法：優先比對 `avg rating — N ratings` 格式，鎖定該書自身的評論數
- W19 重抓後全部修正，下週起自動生效

---

## 已完成（v13，2026-05-07）

### ✅ corrections.json 永久修正系統
- Admin 存檔 → 寫入 corrections.json → 重爬後自動套用
- 支援評分欄位與書本欄位（原價等）

### ✅ Admin 面板大改版
- 淺色主題、字體放大、原價欄、星期幾顯示
- 發佈按鈕常駐、遮罩防呆、Log 重複根治
- 拉取更新修正（git fetch + checkout）

### ✅ 新舊資料對照
- prev.json 備份、全欄位差異偵測、變更摘要列
- 套用舊值按鈕

### ✅ 版本歷史還原
- Admin 面板列出近 15 次資料 commit，一鍵還原

### ✅ 爬蟲準確度提升
- Goodreads & Amazon：前 5 筆 + SequenceMatcher
- Amazon selector 修正（amazon.com 和 amazon.co.jp 同結構 bug）

---

## 待辦

### 🔴 立即
- **失智行為說明書 Amazon 手動補值**：Admin 面板補入 3.9/65 + Kindle 連結，存入 corrections.json，發佈

### 🟡 下次驗證
- corrections.json 有無正確套用於新週次（W20 起觀察）
- 《系統思考》GR count 137 是否正確（原 80137，懷疑新 regex 仍有截斷）
- 《告訴我你吃什麼》GR count 2596 是否正確（原 892596）

### 🟢 長期
- 評分歷史趨勢（多週資料比較）
- ICS webcal:// 一鍵訂閱（暫緩，會減少回訪）

---

## 已完成（v12，2026-05-06）

### ✅ Admin 書單審查表格（preview.py）
- 抓取後自動顯示完整欄位表格（ISBN、原文名、各來源評分+連結）
- 點擊評分格 → 編輯浮層，就地修改評分/筆數/連結，寫回 JSON + 重算 avg_score

### ✅ 日期對應錯位根治（scrape.py）
- 兩步驟：先純文字預掃建「書名 → 日期」對照表，再歸因，脫離 DOM 順序依賴

### ✅ W18 5/6 書（失智行為說明書）手動修正
- 博客來連結補上、Goodreads 筆數 254→4、Amazon 改 Kindle 版（3.9/65）

### ✅ Port / IPv6 修正
- Port 8099→8188；localhost→127.0.0.1

---

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
