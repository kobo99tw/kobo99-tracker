"""
Kobo 每週 99 書單爬蟲 v9
"""

import sys
import json
import re
import time
from datetime import datetime, timezone, timedelta, date as Date
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
import requests
from bs4 import BeautifulSoup

TW_TZ    = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).parent.parent / "docs" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

MIN_BOOKS = 5

# 逾時限制（秒）
TIMEOUT = {
    "kobo":      30,
    "books_com": 30,
    "readmoo":   20,
    "goodreads": 30,
    "amazon":    25,
}


def _timed(fn, args: tuple, limit: float, label: str) -> dict:
    """呼叫 fn(*args)，記錄耗時並在超過 limit 時印出警告。
    實際超時強制由各函式內的 Playwright timeout / requests timeout 執行。"""
    t0 = time.time()
    try:
        result = fn(*args)
        elapsed = time.time() - t0
        if elapsed > limit:
            print(f"      ⚠️  {label} 耗時 {elapsed:.0f}s（限制 {limit:.0f}s）")
        return result if isinstance(result, dict) else {}
    except Exception as e:
        elapsed = time.time() - t0
        is_timeout = "timeout" in str(e).lower() or "time" in str(e).lower()
        tag = "[逾時]" if (is_timeout or elapsed >= limit * 0.8) else "[錯誤]"
        print(f"      {tag} {label}（{elapsed:.0f}s）跳過")
        return {}



# ══════════════════════════════════════════════════════════════════
# Browser
# ══════════════════════════════════════════════════════════════════

class Browser:
    def __enter__(self):
        self._pw  = sync_playwright().start()
        self._b   = self._pw.chromium.launch(headless=True)
        self.ctx  = self._b.new_context(
            locale="zh-TW",
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        return self

    def __exit__(self, *_):
        try:
            self._b.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass

    def get(self, url: str, wait: str = "domcontentloaded",
            timeout: int = 20_000, sleep: float = 2.0) -> BeautifulSoup:
        page = None
        try:
            page = self.ctx.new_page()
            page.goto(url, wait_until=wait, timeout=timeout)
            time.sleep(min(sleep, 2.0))
            html = page.content()
            page.close()
            return BeautifulSoup(html, "html.parser")
        except Exception as e:
            print(f"   [get] {url[:70]} → {e}")
            try:
                if page:
                    page.close()
            except Exception:
                pass
            return BeautifulSoup("", "html.parser")

    def get_fresh(self, url: str, wait_selector: str = None,
                  sleep: float = 2.0) -> BeautifulSoup:
        """每次建立全新 browser context（繞過 Cloudflare session 限制）"""
        ctx = page = None
        try:
            ctx  = self._b.new_context(
                locale="zh-TW",
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=5_000)
                except Exception:
                    pass
            time.sleep(min(sleep, 2.0))
            html = page.content()
            return BeautifulSoup(html, "html.parser")
        except Exception as e:
            print(f"   [get_fresh] {url[:70]} → {e}")
            try:
                if page:
                    html = page.content()
                    return BeautifulSoup(html, "html.parser")
            except Exception:
                pass
            return BeautifulSoup("", "html.parser")
        finally:
            for obj in [page, ctx]:
                try:
                    if obj:
                        obj.close()
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════
# STEP 1：部落格 → 書名 + 直接連結
# ══════════════════════════════════════════════════════════════════

def get_weekly_url(year: int, week: int) -> str:
    return f"https://www.kobo.com/zh/blog/weekly-dd99-{year}-w{week}"


def _calc_current_yw() -> tuple[int, int]:
    """根據台灣時間計算目前應抓的年份與 ISO 週次（最近週四所在週）。"""
    now = datetime.now(TW_TZ).date()
    days_since_thu = (now.weekday() - 3) % 7
    last_thu = now - timedelta(days=days_since_thu)
    cal = last_thu.isocalendar()
    return cal.year, cal.week


def _resolve_weekly(br: Browser, year, week, url=None) -> tuple[int, int, str]:
    """決定要抓的年份、週次與部落格 URL。
    - 有指定 url：直接用該 URL，從 URL 或公式取 year/week
    - 有指定 year/week：直接用公式
    - 未指定：從部落格主頁找書單文章，優先比對「今天在日期範圍內」
      方法A（主）：標題含「一週99書單」且有 （M/D-M/D） 日期範圍
      方法B（輔）：URL 格式 /blog/weekly-dd99-YYYY-wNN
      以上都沒找到才用公式 fallback
    """
    if url:
        full = url.split("?")[0]
        m = re.search(r"weekly-dd99-(\d{4})-w(\d+)", full)
        if m:
            return int(m.group(1)), int(m.group(2)), full
        y2, w2 = _calc_current_yw()
        print(f"   URL 無法解析週次，以公式補 year/week：{y2}-W{w2}")
        return y2, w2, full
    if year and week:
        return year, week, get_weekly_url(year, week)

    print("[1a] 從部落格主頁尋找最新書單…")
    soup  = br.get("https://www.kobo.com/zh/blog", wait="networkidle", sleep=3)
    today = datetime.now(TW_TZ).date()

    KW_PAT     = re.compile(r"一週99書單")
    DR_PAT     = re.compile(r"[（(](\d{1,2}/\d{1,2})[~\-～](\d{1,2}/\d{1,2})[）)]")
    URL_PAT    = re.compile(r"/zh/blog/weekly-dd99-(\d{4})-w(\d+)")

    def _to_date(s: str) -> Date | None:
        try:
            m, d = map(int, s.split("/"))
            return Date(today.year, m, d)
        except Exception:
            return None

    seen: set[str] = set()
    # 每筆：(start_date, end_date, y, w, url)
    candidates: list[tuple] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = (href if href.startswith("http") else "https://www.kobo.com" + href).split("?")[0]
        if full in seen:
            continue

        # 取標題文字（連結本身 → 上一層，限 200 字以內）
        title = ""
        for node in [a, a.parent]:
            if node is None:
                continue
            t = node.get_text(strip=True)
            if len(t) < 200:
                title = t
                break

        # ── 方法A：標題關鍵字 + 日期範圍 ──────────────────────
        if KW_PAT.search(title):
            m_dr = DR_PAT.search(title)
            if m_dr:
                start_d = _to_date(m_dr.group(1))
                end_d   = _to_date(m_dr.group(2))
                if start_d and end_d:
                    if end_d < start_d:          # 跨年修正
                        end_d = Date(today.year + 1, end_d.month, end_d.day)
                    cal = start_d.isocalendar()
                    seen.add(full)
                    candidates.append((start_d, end_d, cal.year, cal.week, full))
                    continue

        # ── 方法B：URL 格式比對 ─────────────────────────────────
        m_url = URL_PAT.search(href)
        if m_url:
            y2, w2 = int(m_url.group(1)), int(m_url.group(2))
            start_d = Date.fromisocalendar(y2, w2, 4)
            end_d   = start_d + timedelta(days=6)
            seen.add(full)
            candidates.append((start_d, end_d, y2, w2, full))

    if candidates:
        # 優先：今天在日期範圍內的（最近一筆）
        for start_d, end_d, y2, w2, url in sorted(candidates, key=lambda x: x[0], reverse=True):
            if start_d <= today <= end_d:
                print(f"   ✅ 找到當週書單（{start_d.month}/{start_d.day}～{end_d.month}/{end_d.day}）：{url}")
                return y2, w2, url
        # 主頁有文章但今天不在任何一筆的日期範圍內
        # → 代表當週書單尚未上主頁列表，用公式 fallback 直接取本週 URL
        # （不選「最新一筆」，否則週四更新日會誤抓上週書單）

    # Fallback：公式計算本週 URL
    y2, w2 = _calc_current_yw()
    fallback = get_weekly_url(y2, w2)
    print(f"   ⚠️  主頁未找到當週書單，使用公式 fallback：{fallback}")
    return y2, w2, fallback


def fetch_books_from_blog(br: Browser, url: str) -> list[dict]:
    print(f"\n[1] 部落格：{url}")
    soup = br.get(url, wait="networkidle", sleep=3)

    from bs4 import NavigableString, Tag as BsTag

    DATE_PAT   = re.compile(r"(\d{1,2}/\d{1,2})\s*週[一二三四五六日]")
    TITLE_PAT  = re.compile(r"《([^》]{2,100})》")
    EBOOK_PAT  = re.compile(r"/(?:tw/)?zh/ebook/")

    result:        list[dict] = []
    used_links:    dict[str, int] = {}   # clean_url → index in result
    used_titles:   set[str]   = set()
    current_date:  str        = ""
    pending_title: str        = ""
    title_date_map: dict[str, str] = {}  # 書名 → 日期

    content = soup.find("body") or soup

    # 預掃：逐行比對「M/D週X」和《書名》必須在同一行才配對，避免跨行誤配
    _DATE_LINE  = re.compile(r"(\d{1,2}/\d{1,2})\s*週[一二三四五六日]")
    _TITLE_LINE = re.compile(r"《([^》]{2,120})》")
    full_text = soup.get_text(separator="\n")
    for line in full_text.split("\n"):
        dm = _DATE_LINE.search(line)
        tm = _TITLE_LINE.search(line)
        if dm and tm:
            t = tm.group(1).strip()
            if t not in title_date_map:
                title_date_map[t] = dm.group(1)

    for elem in content.descendants:
        # ── 文字節點：依頁面順序更新日期 & 待用書名 ──────────────
        if isinstance(elem, NavigableString):
            text = str(elem).strip()
            if not text:
                continue
            # 日期標記（短文字才算標題，避免把整段內文誤判）
            dm = DATE_PAT.search(text)
            if dm and len(text) < 60:
                current_date = dm.group(1)
            # 書名
            tm = TITLE_PAT.search(text)
            if tm:
                t = tm.group(1).strip()
                if t not in used_titles:
                    pending_title = t

        # ── <a> 標籤：判斷是否為電子書連結 ────────────────────────
        elif isinstance(elem, BsTag) and elem.name == "a":
            href = elem.get("href", "")
            if not EBOOK_PAT.search(href) or "/hk/" in href:
                continue
            full  = href if href.startswith("http") else "https://www.kobo.com" + href
            clean = full.split("?")[0]
            if clean in used_links:
                continue
            used_links[clean] = len(result)

            # 書名：連結本身文字 → 前方 pending_title
            link_text = elem.get_text(strip=True)
            lm = TITLE_PAT.search(link_text)
            if lm and lm.group(1).strip() not in used_titles:
                title = lm.group(1).strip()
            elif pending_title and pending_title not in used_titles:
                title = pending_title
            else:
                title = ""

            if title:
                used_titles.add(title)
            pending_title = ""

            if not current_date:
                print(f"   ⚠️  連結取不到日期，書名：《{title[:20]}》")

            result.append({"title": title, "kobo_url": full, "blog_date": current_date})

    # 補缺失書名：先找獨立行《書名》，不夠再全文 findall
    missing = [i for i, b in enumerate(result) if not b["title"]]
    if missing:
        text  = soup.get_text(separator="\n")
        extra: list[str] = []
        seen_t: set[str] = set(used_titles)
        for line in text.split("\n"):
            m = re.match(r"^《([^》]{2,100})》$", line.strip())
            if m and m.group(1) not in seen_t:
                seen_t.add(m.group(1))
                extra.append(m.group(1).strip())
        if len(extra) < len(missing):
            for m in re.finditer(r"《([^》]{2,100})》", text):
                t = m.group(1).strip()
                if t not in seen_t:
                    seen_t.add(t)
                    extra.append(t)
        for idx, pos in enumerate(missing):
            if idx < len(extra):
                result[pos]["title"] = extra[idx]
                used_titles.add(extra[idx])

    # 用 title_date_map 修正日期（逐行預掃結果是唯一真相來源）
    if title_date_map:
        for book in result:
            t = book["title"]
            # ① 完整比對
            if t in title_date_map:
                book["blog_date"] = title_date_map[t]
                continue
            # ② 包含比對（部落格書名可能是 Kobo 完整書名的子字串，或反之）
            for map_t, map_d in title_date_map.items():
                if map_t in t or t in map_t:
                    book["blog_date"] = map_d
                    break
            else:
                # ③ 相似度比對（閾值 0.8，低於此值警告而非猜測）
                best = max(title_date_map.items(),
                           key=lambda x: SequenceMatcher(None, t, x[0]).ratio())
                if SequenceMatcher(None, t, best[0]).ratio() >= 0.8:
                    book["blog_date"] = best[1]
                else:
                    print(f"   ⚠️  日期無法確認，請手動修正：《{t[:30]}》")

    print(f"   找到 {len(result)} 本")
    for b in result:
        d_str = b["blog_date"] or "⚠️ 未取得"
        print(f"   {d_str}  《{b['title'][:28]}》")
    return result, title_date_map


# ══════════════════════════════════════════════════════════════════
# STEP 2：Kobo 書頁 → 完整書籍資料
# ══════════════════════════════════════════════════════════════════

def _parse_secondary_metadata(soup: BeautifulSoup) -> dict:
    """
    解析 .bookitem-secondary-metadata 區塊，逐行找 key/value。
    頁面格式：key 和 value 分別佔獨立行（或 key: value 同行）。
    """
    out: dict = {}
    meta = soup.select_one(".bookitem-secondary-metadata")
    if not meta:
        return out

    KEY_MAP = {
        "書籍ID：":   "isbn",
        "發布日期：": "publish_date",
        "版本說明：": "publisher",
        "語言：":     "language",
    }
    lines = [l.strip() for l in meta.get_text(separator="\n").split("\n") if l.strip()]
    for i, line in enumerate(lines):
        for key, field in KEY_MAP.items():
            if line == key:
                # 值在下一行
                if i + 1 < len(lines):
                    out[field] = lines[i + 1]
            elif line.startswith(key):
                # 值在同行
                val = line[len(key):].strip()
                if val:
                    out[field] = val
    # ISBN 只留數字
    if out.get("isbn"):
        out["isbn"] = re.sub(r"[^0-9]", "", out["isbn"])
    return out


def fetch_kobo_book_page(br: Browser, title: str, kobo_url: str) -> dict:
    print(f"   《{title[:22]}》", end=" ", flush=True)
    result: dict = {"title": title, "kobo_url": kobo_url}
    try:
        soup = br.get(kobo_url, sleep=3)

        # ── 區塊1：上方 ─────────────────────────────────────

        # h1 → 中文書名
        h1 = soup.select_one("h1")
        if h1:
            result["title"] = h1.get_text(strip=True)

            # h1 的下一個 sibling <p>（無 class）→ 原文書名
            # 接受英文、日文（平假名/片假名）、韓文；純中文 = 台灣本地書，略過
            sib = h1.find_next_sibling()
            sib_count = 0
            while sib and sib_count < 3:
                t = sib.get_text(strip=True)
                has_foreign = bool(
                    re.search(r"[A-Za-z]{2,}", t) or          # 英文
                    re.search(r"[぀-ヿ]", t) or        # 日文假名
                    re.search(r"[가-힯]", t)           # 韓文
                )
                if (t and has_foreign and 3 < len(t) < 200
                        and not re.search(r"NT\$|http|Kobo|評論|作者|^\d", t)):
                    result["original_title"] = t
                    break
                sib = sib.find_next_sibling()
                sib_count += 1

        # 作者：.contributor-name（已去掉「由作者」前綴）
        el = soup.select_one(".contributor-name")
        if el:
            result["author"] = el.get_text(strip=True)

        # 原價：頁面第一個出現的 NT$（排除 99 特價）
        text = soup.get_text(separator="\n")
        prices = [int(x.replace(",", "")) for x in re.findall(r"NT\$\s*([\d,]+)", text)]
        valid  = [p for p in prices if p > 99]
        if valid:
            result["kobo_price"] = "NT$" + str(valid[0])

        # Kobo 評分：#RatingsBrief 區塊內的 .rating-average（排除個別書評的評分）
        rv = soup.select_one("#RatingsBrief .rating-average")
        if not rv:
            rv = soup.select_one("div.rating-average")
        if rv:
            m = re.search(r"(\d+\.\d+)", rv.get_text())
            if m and float(m.group(1)) <= 5:
                result["kobo_rating"] = float(m.group(1))
        if not result.get("kobo_rating"):
            m = re.search(r"5分中的(\d+\.\d+)分", text)
            if m:
                result["kobo_rating"] = float(m.group(1))

        # 評分人數：span#total-number-of-ratings（穩定 ID）
        cnt_el = soup.select_one("#total-number-of-ratings, span.total-ratings")
        if cnt_el:
            t = cnt_el.get_text(strip=True)
            if re.match(r"^\d+$", t):
                result["kobo_rating_count"] = int(t)

        # 封面圖：從 og:image 下載並存本機，避免 Kobo CDN token 過期
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            og_url = og_img["content"]
            m_id = re.search(r"/ebook/([A-Za-z0-9_-]+)", kobo_url)
            if m_id:
                book_id   = m_id.group(1)
                covers_dir = DATA_DIR.parent / "covers"
                covers_dir.mkdir(exist_ok=True)
                local_path = covers_dir / f"{book_id}.jpg"
                try:
                    img_r = requests.get(og_url, headers=HEADERS, timeout=10)
                    if img_r.status_code == 200 and len(img_r.content) > 1000:
                        local_path.write_bytes(img_r.content)
                        result["cover_url"] = f"covers/{book_id}.jpg"
                except Exception:
                    pass

        # ── 區塊3：.bookitem-secondary-metadata ─────────────
        meta_fields = _parse_secondary_metadata(soup)
        result.update(meta_fields)

    except Exception as e:
        print(f"→ 錯誤：{e}")
        return result

    print(f"→ ISBN:{result.get('isbn','?')}  "
          f"原文:{result.get('original_title','')[:20] or '?'}  "
          f"原價:{result.get('kobo_price','?')}  "
          f"評分:{result.get('kobo_rating','?')}({result.get('kobo_rating_count',0)})")
    return result


# ══════════════════════════════════════════════════════════════════
# STEP 3：ISBN → 台灣評分
# ══════════════════════════════════════════════════════════════════

def _parse_books_com_page(soup, url: str) -> dict:
    """從博客來書頁解析 .guide-score 評分"""
    gs = soup.select_one(".guide-score")
    if not gs:
        return {}
    score = None
    avg_el = gs.select_one(".average")
    if avg_el:
        m = re.search(r"(\d+\.?\d*)", avg_el.get_text())
        if m and 0 < float(m.group(1)) <= 5:
            score = float(m.group(1))
    count = 0
    for sum_el in gs.select(".sum"):
        m = re.search(r"(\d+)", sum_el.get_text())
        if m:
            count = int(m.group(1))
            break
    return {"score": score, "count": count, "url": url}


def fetch_books_com(br: Browser, isbn: str, title: str = "",
                    author: str = "") -> dict:
    """博客來：書名+作者搜尋 → 取電子書 product ID → 進一次書頁"""
    if not title:
        return {}

    def _search_and_parse(query: str) -> dict:
        q          = requests.utils.quote(query)
        search_url = f"https://search.books.com.tw/search/query/key/{q}/cat/EK"
        soup       = br.get(search_url, sleep=3)

        best_pid = None
        best_sim = 0.0
        for a in soup.select('a[href*="redirect/move"][href*="mid_name"]'):
            href   = a.get("href", "")
            atitle = a.get("title", "")
            m = re.search(r"/item/(\w+)/", href)
            if not m or not m.group(1).startswith("E"):  # 只取電子書（E開頭）
                continue
            pid = m.group(1)
            sim = SequenceMatcher(None, title, atitle).ratio()
            if sim > best_sim:
                best_sim = sim
                best_pid = pid

        if not best_pid or best_sim < 0.3:
            return {}

        product_url = f"https://www.books.com.tw/products/{best_pid}"
        soup2 = br.get_fresh(product_url, wait_selector=".guide-score", sleep=2)
        return _parse_books_com_page(soup2, product_url)

    try:
        # 書名 + 作者（精準）→ fallback 只用書名
        if author:
            r = _search_and_parse(f"{title} {author}")
            if r:
                return r
        return _search_and_parse(title)
    except Exception as e:
        print(f"      [博客來] {e}")
        return {}


def fetch_readmoo(br: Browser, isbn: str, title: str) -> dict:
    query = isbn if isbn else title
    url   = f"https://readmoo.com/search/keyword?q={requests.utils.quote(query)}"
    try:
        soup = br.get(url, sleep=2)
        best_href  = None
        best_score = 0.0
        for a in soup.select("a[href*='/book/']"):
            candidate = ""
            for sel in ["h3", "h4", "[class*='title']", "[class*='name']"]:
                el = a.select_one(sel)
                if el:
                    candidate = el.get_text(strip=True)
                    break
            if not candidate:
                candidate = a.get_text(strip=True)
            if not candidate:
                continue
            sim = SequenceMatcher(None, title, candidate).ratio()
            if sim > best_score:
                best_score = sim
                best_href  = a["href"]
        if not best_href or best_score < 0.4:
            return {}
        book_url = best_href if best_href.startswith("http") else f"https://readmoo.com{best_href}"
        soup2    = br.get(book_url, sleep=2)
        score = None
        el    = soup2.select_one("#star[data-score]")
        if el:
            try:
                score = float(el["data-score"])
            except Exception:
                pass
        count = 0
        # .quick-btn-star span → 「共11人評分」裡的 span 直接含數字
        el2 = soup2.select_one(".quick-btn-star span")
        if el2:
            m = re.search(r"\d+", el2.get_text())
            count = int(m.group()) if m else 0
        return {"score": score, "count": count, "url": book_url}
    except Exception as e:
        print(f"      [讀墨] {e}")
        return {}


# ══════════════════════════════════════════════════════════════════
# STEP 4：國外評分
# ══════════════════════════════════════════════════════════════════

def _detect_book_type(original_title: str) -> str:
    """依原文書名字元判斷書籍類型"""
    if not original_title:
        return "台灣本地書"
    if re.search(r"[぀-ヿ一-鿿]", original_title):
        return "日文書"
    if re.search(r"[가-힣]", original_title):
        return "韓文書"
    if re.search(r"[A-Za-z]", original_title):
        return "歐美書"
    return "台灣本地書"


def _best_candidate(candidates: list[tuple[str, str]], hint: str) -> str | None:
    """(url, title) 列表中，用 SequenceMatcher 取最接近 hint 的 URL。
    相似度皆 < 0.3 時仍 fallback 取第一筆（不放棄）。"""
    if not candidates:
        return None
    if not hint or len(candidates) == 1:
        return candidates[0][0]
    h = hint.lower()
    best_url, best_sim = candidates[0][0], 0.0
    for url, title in candidates:
        sim = SequenceMatcher(None, h, title.lower()).ratio()
        if sim > best_sim:
            best_sim, best_url = sim, url
    return best_url if best_sim >= 0.3 else candidates[0][0]


def fetch_goodreads(br: "Browser", original_title: str = "", original_author: str = "", isbn: str = "") -> dict:
    def _parse_book_page(url: str, note: str) -> dict | None:
        """用 Playwright 開書頁解析評分（繞過 Goodreads 機器人偵測）"""
        try:
            soup = br.get(url, wait="domcontentloaded", sleep=2)
            text = soup.get_text()
            final_url = url
            score = None
            for sel in ["div.RatingStatistics__rating", "span.RatingStatistics__rating"]:
                el = soup.select_one(sel)
                if el:
                    m = re.search(r"(\d+\.\d+)", el.get_text())
                    if m:
                        score = float(m.group(1))
                        break
            if not score:
                m = re.search(r"(\d+\.\d+)\s*avg rating", text)
                if m:
                    score = float(m.group(1))
            count = 0
            m = re.search(r"avg rating\s*[—–·\-]\s*([\d,]+)\s*ratings", text)
            if not m:
                stats_el = soup.select_one(".RatingStatistics__meta, [data-testid='ratingsCount']")
                if stats_el:
                    m = re.search(r"([\d,]+)\s*ratings", stats_el.get_text())
            if m:
                count = int(m.group(1).replace(",", ""))
            en_author = ""
            for sel in ["span.ContributorLink__name", "a.authorName span", ".authorName span[itemprop='name']"]:
                el = soup.select_one(sel)
                if el:
                    en_author = el.get_text(strip=True)
                    break
            if score:
                return {"score": score, "count": count, "url": final_url, "note": note,
                        "en_author": en_author}
        except Exception:
            pass
        return None

    def _search(query: str, note: str, hint: str = "") -> dict | None:
        """用 Playwright 搜尋，取前 5 筆用相似度選最佳後進書頁解析"""
        try:
            q    = requests.utils.quote(query)
            soup = br.get(f"https://www.goodreads.com/search?q={q}",
                          wait="domcontentloaded", sleep=2)
            candidates: list[tuple[str, str]] = []
            for a in soup.select("a[href*='/book/show/']")[:5]:
                href = a.get("href", "")
                url  = href if href.startswith("http") else "https://www.goodreads.com" + href
                title_text = a.get_text(strip=True)
                if title_text:
                    candidates.append((url, title_text))
            best = _best_candidate(candidates, hint)
            return _parse_book_page(best, note) if best else None
        except Exception:
            pass
        return None

    # 台灣本地書：無原文書名也無外文作者 → 跳過 GR
    if not original_title and not isbn:
        return {"note": "無原文資訊"}

    # 0. ISBN 直查（最可靠，繞過搜尋頁的 JS 渲染問題）
    if isbn:
        r = _parse_book_page(f"https://www.goodreads.com/book/isbn/{isbn}", "isbn")
        if r:
            return r

    # 1. 原文書名 + 原文作者（最精準），用書名做相似度比對
    if original_title and original_author:
        r = _search(f"{original_title} {original_author}", "title+author", original_title)
        if r:
            return r
    # 2. 只用原文書名
    if original_title:
        r = _search(original_title, "title", original_title)
        if r:
            return r
    # 3. 只用原文作者（無書名 hint，取第一筆）
    if original_author:
        r = _search(original_author, "author")
        if r:
            return r
    return {"note": "無原文資訊"}


def fetch_amazon(br: Browser, original_title: str = "", original_author: str = "",
                 book_type: str = "歐美書") -> dict:
    if book_type in ("韓文書", "台灣本地書"):
        return {}

    def _parse(soup: BeautifulSoup, url: str) -> dict | None:
        score = None
        for sel in ["span.a-icon-alt", "#acrPopover span.a-size-base",
                    "[data-hook='rating-out-of-text']"]:
            el = soup.select_one(sel)
            if el:
                # findall 取小數點評分，避免誤抓 "5 out of 5" 的 5
                nums = re.findall(r"\d+\.\d+", el.get_text())
                for n in nums:
                    v = float(n)
                    if 0 < v <= 5:
                        score = v
                        break
            if score:
                break
        count = 0
        el = soup.select_one("#acrCustomerReviewText, [data-hook='total-review-count']")
        if el:
            m = re.search(r"[\d,]+", el.get_text())
            if m:
                count = int(m.group().replace(",", ""))
        if score:
            return {"score": round(score, 1), "count": count, "url": url}
        return None

    def _search(base: str, query: str, category: str, hint: str = "") -> dict | None:
        for attempt in range(2):
            try:
                q    = requests.utils.quote(query)
                url  = f"{base}/s?k={q}&i={category}"
                soup = br.get(url, sleep=1.5)

                # 取前 5 筆搜尋結果 (title, url)
                candidates: list[tuple[str, str]] = []
                for card in soup.select("div[data-component-type='s-search-result']")[:5]:
                    # amazon.co.jp 的 <a> 是 <h2> 的父層，需用 a.a-link-normal 而非 h2 a
                    a = card.select_one("a.a-link-normal[href*='/dp/']")
                    if not a:
                        a = card.select_one("a[href*='/dp/']")
                    if not a:
                        continue
                    title_el = card.select_one("h2 span")
                    title    = title_el.get_text(strip=True) if title_el else ""
                    href     = a.get("href", "")
                    candidates.append((base + href.split("?")[0], title))

                if not candidates:
                    # fallback：舊邏輯取第一個 /dp/
                    a = soup.select_one("a.a-link-normal[href*='/dp/']")
                    if a:
                        candidates.append((base + a["href"].split("?")[0], ""))

                best = _best_candidate(candidates, hint)
                if not best:
                    if attempt == 0:
                        time.sleep(3)
                    continue
                soup2 = br.get(best, sleep=1.5)
                result = _parse(soup2, best)
                if result:
                    return result
                if attempt == 0:
                    time.sleep(3)
            except Exception:
                if attempt == 0:
                    time.sleep(3)
        return None

    if book_type == "歐美書":
        base = "https://www.amazon.com"
        for cat in ("stripbooks-intl-ship", "digital-text"):
            if original_title and original_author:
                r = _search(base, f"{original_title} {original_author}", cat, original_title)
                if r:
                    return r
            if original_title:
                r = _search(base, original_title, cat, original_title)
                if r:
                    return r

    elif book_type == "日文書":
        base = "https://www.amazon.co.jp"
        cat  = "stripbooks"
        if original_title:
            r = _search(base, original_title, cat, original_title)
            if r:
                return r
        if original_author:
            r = _search(base, original_author, cat)
            if r:
                return r

    return {}


# ══════════════════════════════════════════════════════════════════
# ICS 日曆產生
# ══════════════════════════════════════════════════════════════════

def _ics_escape(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace(";",  "\\;")
    text = text.replace(",",  "\\,")
    return text


def _ics_fold(line: str) -> str:
    """RFC 5545：每行不超過 75 octets，超出時以 CRLF + SPACE 折行。"""
    result, current, cur_len, first = [], [], 0, True
    for ch in line:
        ch_len = len(ch.encode("utf-8"))
        limit  = 75 if first else 74
        if cur_len + ch_len > limit:
            result.append("".join(current))
            current, cur_len, first = [" ", ch], 1 + ch_len, False
        else:
            current.append(ch)
            cur_len += ch_len
    if current:
        result.append("".join(current))
    return "\r\n".join(result)


def generate_ics(books: list[dict], year: int, week: int, sale_start: Date) -> None:
    ics_path = Path(__file__).parent.parent / "docs" / "calendar.ics"
    now_utc  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//kobo99-tracker//NONSGML v1.0//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Kobo 每週 99 特價書單",
        "X-WR-CALDESC:每週 Kobo 99 元電子書特價",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]

    for idx, book in enumerate(books, 1):
        if not book.get("date"):
            continue
        try:
            m_num, d_num = map(int, book["date"].split("/"))
            yr = sale_start.year
            if m_num < sale_start.month and (sale_start.month - m_num) > 6:
                yr += 1  # 跨年修正
            book_date = Date(yr, m_num, d_num)
        except Exception:
            continue

        dtstart = book_date.strftime("%Y%m%d")
        dtend   = (book_date + timedelta(days=1)).strftime("%Y%m%d")
        title   = book.get("title", "")
        author  = book.get("author", "")
        price   = book.get("kobo_price", "")
        url     = book.get("kobo_url", "")
        avg     = book.get("avg_score")

        summary = _ics_escape(f"《{title}》")

        price_str  = f"特價 NT$99｜原價 {price}" if price else "特價 NT$99"
        desc_parts = [
            price_str,
            url if url else "",
            "查看當週各書評價: https://kobo99.com/",
        ]
        description = "\\n".join(_ics_escape(p) for p in desc_parts if p)
        uid = f"kobo99-{year}-w{week:02d}-{idx:02d}@kobo99-tracker"

        lines += [
            "BEGIN:VEVENT",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
        ]
        if url:
            lines.append(f"URL:{url}")
        lines += [
            f"UID:{uid}",
            f"DTSTAMP:{now_utc}",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")

    content = "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"
    with open(ics_path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print(f"\n📅 日曆已產生：docs/calendar.ics（{len(books)} 個事件）")


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def _fix_date_attribution(books: list[dict], sale_start: Date, sale_end: Date) -> list[dict]:
    """
    修正 DOM 順序造成的日期誤歸因：
    若某日有 2 本以上且下一天完全缺書，將最後一本移至下一天。
    """
    date_range: list[str] = []
    d = sale_start
    while d <= sale_end:
        date_range.append(f"{d.month}/{d.day}")
        d += timedelta(days=1)

    fixed = False
    for i, d_str in enumerate(date_range[:-1]):
        here = [idx for idx, b in enumerate(books) if b.get("blog_date") == d_str]
        next_d = date_range[i + 1]
        nxt  = [idx for idx, b in enumerate(books) if b.get("blog_date") == next_d]
        if len(here) >= 2 and len(nxt) == 0:
            last_idx = here[-1]
            books[last_idx]["blog_date"] = next_d
            print(f"   📅 日期修正：《{books[last_idx]['title'][:20]}》{d_str} → {next_d}")
            fixed = True
    if not fixed:
        print("   ✅ 日期分配正常")
    return books


def _apply_corrections(books: list[dict], year: int, week: int) -> None:
    """把 corrections.json 裡的手動修正套回 books（在計算 avg_score 之前呼叫）。"""
    corrections_path = DATA_DIR / "corrections.json"
    if not corrections_path.exists():
        return
    with open(corrections_path, encoding="utf-8") as f:
        corrections = json.load(f)
    week_corr = corrections.get(f"{year}-w{week:02d}", {})
    if not week_corr:
        return
    for book in books:
        isbn = str(book.get("isbn", ""))
        if isbn not in week_corr:
            continue
        for key, vals in week_corr[isbn].items():
            if key == "_book":
                for field, val in vals.items():
                    book[field] = val
            else:
                book.setdefault("ratings", {}).setdefault(key, {}).update(vals)
    print(f"📝 套用 {len(week_corr)} 筆手動修正（corrections.json）")


def run(year=None, week=None, url=None):
    now    = datetime.now(TW_TZ)
    today  = now.date()
    t_start = time.time()

    print("🚀 Kobo99 爬蟲啟動")
    print("   正在初始化瀏覽器，首次啟動約需 10~30 秒，請稍候...")
    sys.stdout.flush()

    _WD = ["一", "二", "三", "四", "五", "六", "日"]

    def _s(v: dict) -> str:
        s = v.get("score")
        return f"{s}" if s is not None else "-"

    with Browser() as br:

        # Step 1a：決定本週 URL（主頁發現 → fallback 公式）
        y, w, blog_url = _resolve_weekly(br, year, week, url)

        sale_start = Date.fromisocalendar(y, w, 4)          # 週四
        sale_end   = sale_start + timedelta(days=6)          # 下週三
        on_sale    = sale_start <= today <= sale_end
        sale_label = (
            f"NT$99 特價：{sale_start.month}/{sale_start.day}"
            f"（{_WD[sale_start.weekday()]}）～"
            f"{sale_end.month}/{sale_end.day}"
            f"（{_WD[sale_end.weekday()]}）"
        )
        print(f"   {sale_label}  今天 {today} {'✅ 特賣中' if on_sale else '（已結束）'}")

        # Step 1b：部落格
        blog_books, title_date_map = fetch_books_from_blog(br, blog_url)
        if len(blog_books) < MIN_BOOKS:
            print(f"[錯誤] 只找到 {len(blog_books)} 本，停止")
            sys.exit(1)
        # _fix_date_attribution 已移除：預掃逐行比對是唯一日期來源，不再推論

        n = len(blog_books)
        print(f"\n處理每本書（共 {n} 本）")
        books = []

        for i, item in enumerate(blog_books, 1):
            blog_title = item["title"]
            kobo_url   = item["kobo_url"]
            print(f"\n  [{i}/{n}] 《{blog_title[:20]}》")

            # ── Kobo 書頁
            info = _timed(fetch_kobo_book_page,
                          (br, blog_title, kobo_url),
                          TIMEOUT["kobo"], "Kobo")
            kobo_r = {
                "score": info.get("kobo_rating"),
                "count": info.get("kobo_rating_count", 0),
                "url":   info.get("kobo_url", kobo_url),
            }

            isbn   = info.get("isbn") or ""
            title  = info.get("title", blog_title)
            author = info.get("author", "")
            orig_t = info.get("original_title", "")

            # Kobo 實際書名可能與部落格書名不同，用相同層級邏輯重查日期
            blog_date = item.get("blog_date") or ""
            if title != blog_title and title_date_map:
                # ① 完整比對
                if title in title_date_map:
                    blog_date = title_date_map[title]
                else:
                    # ② 包含比對
                    for mt, md in title_date_map.items():
                        if mt in title or title in mt:
                            blog_date = md
                            break
                    else:
                        # ③ 相似度比對（閾值 0.8）
                        best = max(title_date_map.items(),
                                   key=lambda x: SequenceMatcher(None, title, x[0]).ratio())
                        if SequenceMatcher(None, title, best[0]).ratio() >= 0.8:
                            blog_date = best[1]

            # ── 博客來
            bc = _timed(fetch_books_com,
                        (br, isbn, title, author),
                        TIMEOUT["books_com"], "博客來")

            # ── 讀墨
            rm = _timed(fetch_readmoo,
                        (br, isbn, title),
                        TIMEOUT["readmoo"], "讀墨")

            # ── 語言判斷
            book_type = _detect_book_type(orig_t)
            print(f"      《{title[:16]}》→ {book_type}")

            # ── Goodreads
            gr = _timed(fetch_goodreads,
                        (br, orig_t, author, isbn),
                        TIMEOUT["goodreads"], "Goodreads")

            # ── Amazon（優先用 GR 取回的英文作者名，避免中文譯名干擾搜尋）
            gr_en_author = (gr or {}).get("en_author", "")
            amz = _timed(fetch_amazon,
                         (br, orig_t, gr_en_author or author, book_type),
                         TIMEOUT["amazon"], "Amazon")

            book = {
                "title":          title,
                "author":         author,
                "original_title": orig_t,
                "isbn":           isbn or None,
                "kobo_url":       info.get("kobo_url", kobo_url),
                "kobo_price":     info.get("kobo_price"),
                "cover_url":      info.get("cover_url", ""),
                "sale_price":     "NT$99",
                "date":           blog_date,
                "sale_start":     sale_start.isoformat(),
                "sale_end":       sale_end.isoformat(),
                "on_sale":        on_sale,
                "publisher":      info.get("publisher", ""),
                "publish_date":   info.get("publish_date", ""),
                "language":       info.get("language", ""),
                "description":    "",
                "ratings": {
                    "kobo":       kobo_r,
                    "books_com":  {"score": bc.get("score"),  "count": bc.get("count", 0),  "url": bc.get("url", "")},
                    "readmoo":    {"score": rm.get("score"),  "count": rm.get("count", 0),  "url": rm.get("url", "")},
                    "goodreads":  {"score": gr.get("score"),  "count": gr.get("count", 0),  "url": gr.get("url", ""),  "note": gr.get("note", "")},
                    "amazon_com": {"score": amz.get("score"), "count": amz.get("count", 0), "url": amz.get("url", "")},
                }
            }
            books.append(book)

            print(f"    [{i}/{n}] 《{title[:16]}》完成"
                  f"（Kobo:{_s(kobo_r)} "
                  f"博客來:{_s(bc)} "
                  f"讀墨:{_s(rm)} "
                  f"GR:{_s(gr)} "
                  f"AMZ:{_s(amz)}）")

    _apply_corrections(books, y, w)

    # 加權綜合分（依優先順序）
    RATING_ORDER = ["kobo", "books_com", "readmoo", "goodreads", "amazon_com"]
    for book in books:
        ws = wt = 0.0
        for src in RATING_ORDER:
            v = book["ratings"].get(src, {})
            s = v.get("score")
            c = max(v.get("count", 0), 1)
            if s:
                ws += s * c
                wt += c
        book["avg_score"] = round(ws / wt, 2) if wt else None

    # 備份舊版本（供 admin 面板對照用）
    week_file = DATA_DIR / f"books-{y}-w{w:02d}.json"
    if week_file.exists():
        import shutil
        shutil.copy2(week_file, DATA_DIR / f"books-{y}-w{w:02d}-prev.json")

    # 儲存
    output = {
        "year":       y,
        "week":       w,
        "kobo_url":   blog_url,
        "sale_label": sale_label,
        "sale_start": sale_start.isoformat(),
        "sale_end":   sale_end.isoformat(),
        "on_sale":    on_sale,
        "updated_at": now.isoformat(),
        "books":      books,
    }
    for path in [DATA_DIR / f"books-{y}-w{w:02d}.json", DATA_DIR / "latest.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    generate_ics(books, y, w, sale_start)

    # 摘要
    total_sec = int(time.time() - t_start)
    mins, secs = divmod(total_sec, 60)
    print(f"\n✅ 完成！{len(books)} 本書")
    print(f"   總時間：{mins}分{secs:02d}秒")
    for src in ["kobo", "books_com", "readmoo", "goodreads", "amazon_com"]:
        hit = sum(1 for b in books if b["ratings"].get(src, {}).get("score"))
        print(f"   {src:12s} {hit}/{len(books)}")


def refetch_ratings(year=None, week=None):
    """只重新抓取 Goodreads + Amazon，不重跑完整爬蟲"""
    if year and week:
        path = DATA_DIR / f"books-{year}-w{week:02d}.json"
    else:
        path = DATA_DIR / "latest.json"

    if not path.exists():
        print(f"[錯誤] 找不到 {path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    books = data["books"]
    n = len(books)
    print(f"🔄 重新抓取 GR + Amazon（共 {n} 本）")

    with Browser() as br:
        for i, book in enumerate(books, 1):
            title     = book.get("title", "")
            orig_t    = book.get("original_title", "")
            author    = book.get("author", "")
            isbn      = str(book.get("isbn") or "")
            book_type = _detect_book_type(orig_t)

            print(f"\n  [{i}/{n}] 《{title[:20]}》")

            gr = _timed(fetch_goodreads,
                        (br, orig_t, author, isbn),
                        TIMEOUT["goodreads"], "Goodreads")

            gr_en_author = (gr or {}).get("en_author", "")
            amz = _timed(fetch_amazon,
                         (br, orig_t, gr_en_author or author, book_type),
                         TIMEOUT["amazon"], "Amazon")

            book.setdefault("ratings", {})
            book["ratings"]["goodreads"]  = {
                "score": gr.get("score"),  "count": gr.get("count", 0),
                "url":   gr.get("url", ""), "note": gr.get("note", ""),
            }
            book["ratings"]["amazon_com"] = {
                "score": amz.get("score"), "count": amz.get("count", 0),
                "url":   amz.get("url", ""),
            }
            gr_s  = gr.get("score")  if gr  else None
            amz_s = amz.get("score") if amz else None
            print(f"      GR:{gr_s if gr_s is not None else '-'}  AMZ:{amz_s if amz_s is not None else '-'}")

    # 重算 avg_score
    RATING_ORDER = ["kobo", "books_com", "readmoo", "goodreads", "amazon_com"]
    for book in books:
        ws = wt = 0.0
        for src in RATING_ORDER:
            v = book["ratings"].get(src, {})
            s = v.get("score")
            c = max(v.get("count", 0), 1)
            if s:
                ws += s * c
                wt += c
        book["avg_score"] = round(ws / wt, 2) if wt else None

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    latest = DATA_DIR / "latest.json"
    if path.resolve() != latest.resolve():
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ICS 同步更新
    y, w = data.get("year"), data.get("week")
    if y and w:
        sale_start = Date.fromisocalendar(y, w, 4)
        generate_ics(books, y, w, sale_start)

    print(f"\n✅ 完成！")
    for src in ["goodreads", "amazon_com"]:
        hit = sum(1 for b in books if b["ratings"].get(src, {}).get("score"))
        print(f"   {src:12s} {hit}/{n}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Kobo99 爬蟲")
    ap.add_argument("year", nargs="?", type=int, help="ISO 年份")
    ap.add_argument("week", nargs="?", type=int, help="ISO 週次")
    ap.add_argument("--url", default=None, help="直接指定部落格文章 URL")
    ap.add_argument("--refetch-ratings", action="store_true",
                    help="只重新抓取 GR + Amazon，不重跑完整流程")
    args = ap.parse_args()
    if args.refetch_ratings:
        refetch_ratings(args.year, args.week)
    else:
        run(args.year, args.week, args.url)
