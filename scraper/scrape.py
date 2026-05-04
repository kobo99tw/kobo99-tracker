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
    "goodreads": 15,
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


def _book_date(sale_start: Date, offset: int) -> str:
    """部落格第 offset 本（0-based）對應的特賣日，格式 M/D"""
    d = sale_start + timedelta(days=offset)
    return f"{d.month}/{d.day}"


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
                    page.wait_for_selector(wait_selector, timeout=10_000)
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

def get_weekly_url(year=None, week=None) -> str:
    if not year or not week:
        now = datetime.now(TW_TZ).date()
        # Kobo 每日99 從週四開始，取最近週四所在的 ISO 週
        days_since_thu = (now.weekday() - 3) % 7   # 0=今天是週四, 1=週五...
        last_thu = now - timedelta(days=days_since_thu)
        cal  = last_thu.isocalendar()
        year, week = cal.year, cal.week
    return f"https://www.kobo.com/zh/blog/weekly-dd99-{year}-w{week}"


def fetch_books_from_blog(br: Browser, url: str) -> list[dict]:
    print(f"\n[1] 部落格：{url}")
    soup = br.get(url, wait="networkidle", sleep=3)

    # 收集所有電子書連結（保序、去重），同時保留 anchor tag 引用
    anchors: list[tuple] = []
    seen_clean: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"/(?:tw/)?zh/ebook/", href) or "/hk/" in href:
            continue
        full  = href if href.startswith("http") else "https://www.kobo.com" + href
        clean = full.split("?")[0]
        if clean in seen_clean:
            continue
        seen_clean.add(clean)
        anchors.append((a, full))

    # 對每個連結，往上走 DOM 找最近的 《書名》與日期標記
    result: list[dict] = []
    used: set[str] = set()
    for a_tag, link in anchors:
        title      = ""
        blog_date  = ""
        parent     = a_tag
        for _ in range(7):
            parent = parent.parent
            if parent is None:
                break
            blk = parent.get_text()
            if len(blk) > 2000:
                break
            m = re.search(r"《([^》]{2,100})》", blk)
            if m and m.group(1) not in used:
                title = m.group(1).strip()
                used.add(title)
                # 同一區塊內找日期（格式：5/1週五 或 4/30週四）
                d = re.search(r"(\d{1,2}/\d{1,2})\s*週[一二三四五六日]", blk)
                if d:
                    blog_date = d.group(1)
                break
        result.append({"title": title, "kobo_url": link, "blog_date": blog_date})

    # 補缺失書名：先找獨立行《書名》，不夠再全文 findall
    missing = [i for i, b in enumerate(result) if not b["title"]]
    if missing:
        text  = soup.get_text(separator="\n")
        extra: list[str] = []
        seen_t: set[str] = set()
        for line in text.split("\n"):
            m = re.match(r"^《([^》]{2,100})》$", line.strip())
            if m and m.group(1) not in seen_t and m.group(1) not in used:
                seen_t.add(m.group(1))
                extra.append(m.group(1).strip())
        if len(extra) < len(missing):
            for m in re.finditer(r"《([^》]{2,100})》", text):
                t = m.group(1).strip()
                if t not in seen_t and t not in used:
                    seen_t.add(t)
                    extra.append(t)
        for idx, pos in enumerate(missing):
            if idx < len(extra):
                result[pos]["title"] = extra[idx]
                used.add(extra[idx])

    print(f"   找到 {len(result)} 本")
    for b in result:
        print(f"   《{b['title'][:28]}》")
    return result


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


def fetch_goodreads(original_title: str = "", original_author: str = "") -> dict:
    def _parse_book_page(url: str, note: str) -> dict | None:
        """從書本頁面（/book/show/...）解析評分，確保評分與連結來自同一頁"""
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text()
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
            m = re.search(r"([\d,]+)\s*ratings", text)
            if m:
                count = int(m.group(1).replace(",", ""))
            if score:
                return {"score": score, "count": count, "url": r.url, "note": note}
        except Exception:
            pass
        return None

    def _search(query: str, note: str) -> dict | None:
        """搜尋頁找第一本書連結 → 跟進書頁解析（確保評分＝連結那本書）"""
        try:
            q    = requests.utils.quote(query)
            r    = requests.get(f"https://www.goodreads.com/search?q={q}",
                                headers=HEADERS, timeout=8)
            soup = BeautifulSoup(r.text, "html.parser")
            a    = soup.select_one("a.bookTitle, a[href*='/book/show/']")
            if not a:
                return None
            href = a["href"]
            book_url = href if href.startswith("http") else "https://www.goodreads.com" + href
            return _parse_book_page(book_url, note)
        except Exception:
            pass
        return None

    if not original_title and not original_author:
        return {"note": "無原文資訊"}

    # 1. 原文書名 + 原文作者（最精準）
    if original_title and original_author:
        r = _search(f"{original_title} {original_author}", "title+author")
        if r:
            return r
    # 2. 只用原文書名
    if original_title:
        r = _search(original_title, "title")
        if r:
            return r
    # 3. 只用原文作者
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

    def _search(base: str, query: str, category: str) -> dict | None:
        try:
            q    = requests.utils.quote(query)
            url  = f"{base}/s?k={q}&i={category}"
            soup = br.get(url, sleep=1.5)
            a    = soup.select_one("a.a-link-normal[href*='/dp/']")
            if a:
                book_url = base + a["href"].split("?")[0]
                soup2    = br.get(book_url, sleep=1.5)
                return _parse(soup2, book_url)
        except Exception:
            pass
        return None

    if book_type == "歐美書":
        base = "https://www.amazon.com"
        cat  = "stripbooks-intl-ship"
        if original_title and original_author:
            r = _search(base, f"{original_title} {original_author}", cat)
            if r:
                return r
        if original_title:
            r = _search(base, original_title, cat)
            if r:
                return r

    elif book_type == "日文書":
        base = "https://www.amazon.co.jp"
        cat  = "stripbooks"
        if original_title:
            r = _search(base, original_title, cat)
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

        summary = _ics_escape(f"《{title}》NT$99 特價")

        sv_match = re.search(r"[\d,]+", price) if price else None
        saving   = int(sv_match.group().replace(",", "")) - 99 if sv_match else 0

        line1 = ("⭐ " + str(avg) if avg is not None else "⭐ -")
        if saving > 0:
            line1 += f" | 省 NT${saving}"
        line2 = f"👉 {url}" if url else ""
        description = "\\n".join(_ics_escape(p) for p in [line1, line2] if p)
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

def run(year=None, week=None):
    now = datetime.now(TW_TZ)
    cal = now.isocalendar()
    y   = year or cal.year
    w   = week or cal.week
    blog_url = get_weekly_url(y, w)

    # 特賣期間：ISO 週的週四（Kobo 每日99 從週四開始）
    # 8 本書對應 8 天：週四 ~ 下週四
    sale_start = Date.fromisocalendar(y, w, 4)  # 週四
    sale_end   = sale_start + timedelta(days=7)  # 下週四（最後一本書的日期）
    today      = now.date()
    on_sale    = sale_start <= today <= sale_end

    _WD = ["一", "二", "三", "四", "五", "六", "日"]
    sale_label = (
        f"NT$99 特價：{sale_start.month}/{sale_start.day}"
        f"（{_WD[sale_start.weekday()]}）～"
        f"{sale_end.month}/{sale_end.day}"
        f"（{_WD[sale_end.weekday()]}）"
    )
    print(f"   {sale_label}  今天 {today} {'✅ 特賣中' if on_sale else '（已結束）'}")

    t_start = time.time()

    def _s(v: dict) -> str:
        """評分格式化：有分顯示數字，沒有顯示 -"""
        s = v.get("score")
        return f"{s}" if s is not None else "-"

    with Browser() as br:

        # Step 1：部落格
        blog_books = fetch_books_from_blog(br, blog_url)
        if len(blog_books) < MIN_BOOKS:
            print(f"[錯誤] 只找到 {len(blog_books)} 本，停止")
            sys.exit(1)

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
                        (orig_t, author),
                        TIMEOUT["goodreads"], "Goodreads")

            # ── Amazon
            amz = _timed(fetch_amazon,
                         (br, orig_t, author, book_type),
                         TIMEOUT["amazon"], "Amazon")

            book = {
                "title":          title,
                "author":         author,
                "original_title": orig_t,
                "isbn":           isbn or None,
                "kobo_url":       info.get("kobo_url", kobo_url),
                "kobo_price":     info.get("kobo_price"),
                "sale_price":     "NT$99",
                "date":           item.get("blog_date") or _book_date(sale_start, i - 1),
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


if __name__ == "__main__":
    y = int(sys.argv[1]) if len(sys.argv) > 1 else None
    w = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run(y, w)
