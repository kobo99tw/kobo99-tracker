"""
Kobo 每週 99 書單爬蟲 v7
正確流程：
  1. Kobo 部落格 → 取得本週書名清單
  2. Kobo 官網搜尋 → 中文書名、作者、原文書名、ISBN、Kobo評分、原價
  3. ISBN → 博客來、讀墨
  4. ISBN / 原文書名 → Goodreads、Amazon.com
"""

import sys
import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
import requests
from bs4 import BeautifulSoup

# ── 設定 ─────────────────────────────────────────────────────────
TW_TZ    = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).parent.parent / "public" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

MIN_BOOKS = 5  # 低於此數視為抓取失敗


# ══════════════════════════════════════════════════════════════════
# Playwright Session
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
            timeout: int = 30_000, sleep: float = 2.0) -> BeautifulSoup:
        page = self.ctx.new_page()
        try:
            page.goto(url, wait_until=wait, timeout=timeout)
            time.sleep(sleep)
            html = page.content()
        except Exception as e:
            print(f"\n  [瀏覽器] 頁面載入失敗：{e}")
            html = "<html></html>"
        finally:
            try:
                page.close()
            except Exception:
                pass
        return BeautifulSoup(html, "html.parser")


# ══════════════════════════════════════════════════════════════════
# STEP 1：Kobo 部落格 → 同時取得書名 + 書頁連結
# ══════════════════════════════════════════════════════════════════

def get_weekly_url(year=None, week=None) -> str:
    if not year or not week:
        now  = datetime.now(TW_TZ)
        cal  = now.isocalendar()
        year, week = cal.year, cal.week
    return f"https://www.kobo.com/zh/blog/weekly-dd99-{year}-w{week}"


def fetch_books_from_blog(br: Browser, url: str) -> list[dict]:
    """
    從部落格頁面同時抓：
    - 書名（《》內）
    - 書頁連結（查看電子書 的 href）
    部落格連結格式：
      https://www.kobo.com/tw/zh/ebook/{id}?utm_source=twblog&...
    直接用這個連結進書頁，不需要再搜尋。
    """
    print(f"\n[1] 部落格：{url}")
    soup = br.get(url, wait="networkidle", sleep=3)
    text = soup.get_text(separator="\n")

    # 先建立 ebook 連結清單（/tw/zh/ebook/ 或 /zh/ebook/，排除香港 /hk/）
    ebook_links = []
    seen_links  = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/ebook/" not in href or "/hk/" in href:
            continue
        if not ("kobo.com" in href):
            continue
        clean = href.split("?")[0]  # 去掉 utm 參數
        if clean not in seen_links:
            seen_links.add(clean)
            full = href if href.startswith("http") else "https://www.kobo.com" + href
            ebook_links.append(full)

    print(f"   找到 {len(ebook_links)} 個書頁連結")

    # 抓《書名》清單（順序對應連結順序）
    titles = []
    seen_t = set()
    for line in text.split("\n"):
        line = line.strip()
        m = re.match(r"^《([^》]{2,50})》$", line)
        if m:
            t = m.group(1).strip()
            if t not in seen_t:
                seen_t.add(t)
                titles.append(t)

    # 寬鬆備案
    if len(titles) < len(ebook_links):
        for t in re.findall(r"《([^》]{2,50})》", text):
            t = t.strip()
            if t not in seen_t:
                seen_t.add(t)
                titles.append(t)

    # 配對書名和連結
    books = []
    n = max(len(titles), len(ebook_links))
    for i in range(n):
        books.append({
            "title":    titles[i] if i < len(titles) else f"書籍{i+1}",
            "kobo_url": ebook_links[i] if i < len(ebook_links) else "",
        })

    print(f"   配對結果：{len(books)} 本")
    for b in books:
        print(f"     《{b['title']}》→ {b['kobo_url'][:60]}...")
    return books


# ══════════════════════════════════════════════════════════════════
# STEP 2：直接進 Kobo 書頁（連結已從部落格取得，不需搜尋）
# ══════════════════════════════════════════════════════════════════

def fetch_kobo_book_info(br: Browser, title: str, kobo_url: str) -> dict:
    """
    直接用部落格的書頁連結取得：
    - 中文書名（校正）、作者
    - 原文書名、原文作者
    - ISBN
    - Kobo 評分 & 評分人數
    - 原價（NT$ 最大值）
    - 書籍分類 genre
    """
    if not kobo_url:
        print(f"   《{title}》→ 無連結，跳過")
        return {"title": title}

    print(f"   《{title}》", end=" ")

    try:
        soup2 = br.get(kobo_url, sleep=3)
        text  = soup2.get_text(separator="\n")
        result = {"title": title, "kobo_url": kobo_url}

        # ── 書名（h1 校正）
        h1 = soup2.select_one("h1")
        if h1:
            result["title"] = h1.get_text(strip=True)

        # ── 作者（頁面文字直接找）
        for sel in ["a[href*='search?Author']", "a[href*='contributor']",
                    "span[class*='author']", ".contributor-name a"]:
            el = soup2.select_one(sel)
            if el:
                result["author"] = el.get_text(strip=True)
                break

        # ── ISBN：直接從「書籍ID」欄位抓（最可靠）
        m = re.search(r"書籍ID[：:]\s*([0-9]{10,17})", text)
        if m:
            result["isbn"] = m.group(1).strip()
        else:
            # 備案：找 ISBN 字樣
            m = re.search(r"ISBN[：:\s]*([0-9\-]{10,17})", text)
            if m:
                result["isbn"] = m.group(1).replace("-", "")

        # ── 原文書名
        for pat in [r"原文書名[：:]\s*([^\n]{2,80})",
                    r"Original Title[：:]\s*([^\n]{2,80})"]:
            m = re.search(pat, text)
            if m:
                result["original_title"] = m.group(1).strip()
                break

        # ── 出版社
        m = re.search(r"版本說明[：:]\s*([^\n]{1,40})", text)
        if m:
            result["publisher"] = m.group(1).strip()

        # ── 發布日期
        m = re.search(r"發布日期[：:]\s*([^\n]{1,30})", text)
        if m:
            result["publish_date"] = m.group(1).strip()

        # ── 語言
        m = re.search(r"語言[：:]\s*([^\n]{1,20})", text)
        if m:
            result["language"] = m.group(1).strip()

        # ── Kobo 評分（Schema.org JSON，抓到算賺到）
        for tag in soup2.find_all(attrs={"data-kobo-gizmo-config": True}):
            try:
                cfg = json.loads(tag["data-kobo-gizmo-config"])
                rv  = (cfg.get("ratingValue")
                       or cfg.get("aggregateRating", {}).get("ratingValue"))
                rc  = (cfg.get("ratingCount")
                       or cfg.get("aggregateRating", {}).get("ratingCount", 0))
                if rv:
                    result["kobo_rating"]      = round(float(rv), 2)
                    result["kobo_rating_count"] = int(rc)
                # 原文作者（從 Schema.org 補）
                for ex in cfg.get("workExample", [cfg]):
                    for auth in ex.get("author", []):
                        name = auth.get("name", "")
                        if name and re.search(r"[A-Za-z]", name):
                            result.setdefault("original_author", name)
                # 分類
                result.setdefault("genre", cfg.get("genre", []))
            except Exception:
                pass

        # ── 原價（頁面所有 NT$ 取最大值）
        prices = [int(x.replace(",", ""))
                  for x in re.findall(r"NT\$\s*([\d,]+)", text)]
        valid  = [p for p in prices if p > 99]
        if valid:
            result["kobo_price"] = "NT$" + str(max(valid))

        print(f"→ ISBN:{result.get('isbn','無')}  "
              f"原價:{result.get('kobo_price','無')}  "
              f"Kobo評分:{result.get('kobo_rating','無')}")
        return result

    except Exception as e:
        print(f"→ 錯誤：{e}")
        return {"title": title}


# ══════════════════════════════════════════════════════════════════
# STEP 3：ISBN → 台灣評分（博客來、讀墨）
# ══════════════════════════════════════════════════════════════════

def fetch_books_com(br: Browser, isbn: str) -> dict:
    """博客來：直接用 ISBN 進書頁（Calibre BooksTW 插件做法）"""
    if not isbn:
        return {}
    url  = f"https://www.books.com.tw/products/{isbn}"
    try:
        soup = br.get(url, sleep=2)

        # 確認有找到書（沒找到通常會有「查無此商品」字樣）
        if "查無" in soup.get_text() or "找不到" in soup.get_text():
            return {}

        score = None
        for sel in [".num", "span.num", "[class*='score'] .num"]:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"(\d+\.?\d*)", el.get_text())
                if m and 0 < float(m.group(1)) <= 5:
                    score = float(m.group(1))
                    break

        count = 0
        for sel in [".evaluate", "[class*='count']"]:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"\d+", el.get_text())
                if m:
                    count = int(m.group())
                    break

        return {"score": score, "count": count, "url": url}
    except Exception as e:
        print(f"      [博客來] {e}")
        return {}


def fetch_readmoo(br: Browser, isbn: str, title: str) -> dict:
    """讀墨：優先 ISBN 搜尋，次選書名搜尋"""
    query = isbn if isbn else title
    url   = f"https://readmoo.com/search/keyword?q={requests.utils.quote(query)}"
    try:
        soup = br.get(url, sleep=2)

        # 找第一本書連結
        a = soup.select_one("a[href*='/book/']")
        if not a:
            return {}
        book_url = a["href"] if a["href"].startswith("http") else f"https://readmoo.com{a['href']}"

        soup2 = br.get(book_url, sleep=2)

        # 評分
        score = None
        el    = soup2.select_one("#star[data-score]")
        if el:
            try:
                score = float(el["data-score"])
            except Exception:
                pass

        # 評論數
        count = 0
        el2   = soup2.select_one("span[itemprop='ratingCount']")
        if el2:
            m = re.search(r"\d+", el2.get_text())
            count = int(m.group()) if m else 0

        return {"score": score, "count": count, "url": book_url}
    except Exception as e:
        print(f"      [讀墨] {e}")
        return {}


# ══════════════════════════════════════════════════════════════════
# STEP 4：ISBN / 原文書名 → 國外評分（Goodreads、Amazon.com）
# ══════════════════════════════════════════════════════════════════

def fetch_goodreads(isbn: str = "", original_title: str = "",
                    original_author: str = "") -> dict:
    """
    Goodreads（不走 Google，直連）
    策略：ISBN → 原文書名 → 英文作者
    """
    def _get(url: str, note: str):
        try:
            r    = requests.get(url, headers=HEADERS, timeout=12)
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

            # 搜尋結果頁取第一本書連結
            book_url = r.url
            if "/search" in r.url:
                a = soup.select_one("a.bookTitle, a[href*='/book/show/']")
                if a:
                    book_url = "https://www.goodreads.com" + a["href"]

            if score:
                return {"score": score, "count": count, "url": book_url, "note": note}
        except Exception:
            pass
        return None

    if isbn:
        r = _get(f"https://www.goodreads.com/book/isbn/{isbn}", "isbn")
        if r:
            return r

    if original_title:
        q = requests.utils.quote(f'"{original_title}"')
        r = _get(f"https://www.goodreads.com/search?q={q}", "original_title")
        if r:
            return r

    if original_author:
        q = requests.utils.quote(original_author)
        r = _get(f"https://www.goodreads.com/search?q={q}", "eng_author")
        if r:
            return r

    return {}


def fetch_amazon(br: Browser, isbn: str = "",
                 original_title: str = "") -> dict:
    """
    Amazon.com：歐美原著英文版評分（評分人數遠多於 Amazon JP）
    策略 1：ISBN-10（= ASIN）直查 amazon.com/dp/{isbn10}
    策略 2：ISBN-13 搜尋
    策略 3：原文書名搜尋
    """
    BASE = "https://www.amazon.com"

    def _isbn13_to_10(isbn13: str) -> str:
        digits = re.sub(r"[^0-9]", "", isbn13)
        if len(digits) != 13 or not digits.startswith("97"):
            return ""
        core  = digits[3:12]
        check = sum((10 - i) * int(d) for i, d in enumerate(core)) % 11
        check = "X" if check == 10 else str((11 - check) % 11)
        return core + check

    def _parse(soup: BeautifulSoup, url: str) -> dict | None:
        score = None
        for sel in ["span.a-icon-alt",
                    "#acrPopover span.a-size-base",
                    "[data-hook='rating-out-of-text']"]:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"(\d+\.?\d*)", el.get_text())
                if m and 0 < float(m.group(1)) <= 5:
                    score = float(m.group(1))
                    break
        count = 0
        el = soup.select_one(
            "#acrCustomerReviewText, [data-hook='total-review-count']")
        if el:
            m = re.search(r"[\d,]+", el.get_text())
            if m:
                count = int(m.group().replace(",", ""))
        if score:
            return {"score": round(score, 1), "count": count, "url": url}
        return None

    def _follow_first(soup: BeautifulSoup) -> dict | None:
        """從搜尋結果頁取第一本書連結並解析"""
        a = soup.select_one("a.a-link-normal[href*='/dp/']")
        if not a:
            return None
        book_url = BASE + a["href"].split("?")[0]
        try:
            soup2 = br.get(book_url, sleep=2)
            return _parse(soup2, book_url)
        except Exception:
            return None

    # 策略 1：ISBN-10 直查（通常就是 ASIN）
    if isbn:
        isbn10 = _isbn13_to_10(isbn)
        if isbn10:
            try:
                url  = f"{BASE}/dp/{isbn10}"
                soup = br.get(url, sleep=2)
                r    = _parse(soup, url)
                if r:
                    return r
            except Exception:
                pass

        # 策略 2：ISBN-13 搜尋
        try:
            url  = f"{BASE}/s?k={isbn}&i=stripbooks-intl-ship"
            soup = br.get(url, sleep=2)
            r    = _follow_first(soup)
            if r:
                return r
        except Exception:
            pass

    # 策略 3：原文書名搜尋
    if original_title:
        try:
            q    = requests.utils.quote(original_title)
            url  = f"{BASE}/s?k={q}&i=stripbooks-intl-ship"
            soup = br.get(url, sleep=2)
            r    = _follow_first(soup)
            if r:
                return r
        except Exception:
            pass

    return {}


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def run(year=None, week=None):
    now = datetime.now(TW_TZ)
    cal = now.isocalendar()
    y   = year or cal.year
    w   = week or cal.week
    blog_url = get_weekly_url(y, w)

    with Browser() as br:

        # ── Step 1：部落格取書名 + 書頁連結 ──────────────────
        blog_books = fetch_books_from_blog(br, blog_url)
        if len(blog_books) < MIN_BOOKS:
            print(f"[錯誤] 只找到 {len(blog_books)} 本，停止")
            sys.exit(1)

        # ── Step 2：直接進 Kobo 書頁取完整資料 ───────────────
        print(f"\n[2] Kobo 書頁查詢（共 {len(blog_books)} 本）")
        books = []
        for b in blog_books:
            info = fetch_kobo_book_info(br, b["title"], b["kobo_url"])
            books.append({
                "title":          info.get("title", title),
                "author":         info.get("author", ""),
                "original_title": info.get("original_title", ""),
                "original_author":info.get("original_author", ""),
                "isbn":           info.get("isbn"),
                "kobo_url":       info.get("kobo_url", ""),
                "kobo_price":     info.get("kobo_price"),
                "sale_price":     "NT$99",
                "genre":          info.get("genre", []),
                "description":    "",
                "ratings": {
                    "kobo": {
                        "score": info.get("kobo_rating"),
                        "count": info.get("kobo_rating_count", 0),
                        "url":   info.get("kobo_url", ""),
                    }
                }
            })
            time.sleep(1)

        # ── Step 3：ISBN → 台灣評分 ───────────────────────────
        print("\n[3] 台灣評分（博客來 / 讀墨）")
        for book in books:
            isbn  = book.get("isbn") or ""
            title = book["title"]
            print(f"  《{title}》 ISBN={isbn}")

            bc = fetch_books_com(br, isbn)
            book["ratings"]["books_com"] = {
                "score": bc.get("score"), "count": bc.get("count", 0),
                "url": bc.get("url", "")
            }
            print(f"    博客來：{bc.get('score')} ({bc.get('count',0)}人)")

            rm = fetch_readmoo(br, isbn, title)
            book["ratings"]["readmoo"] = {
                "score": rm.get("score"), "count": rm.get("count", 0),
                "url": rm.get("url", "")
            }
            print(f"    讀墨：  {rm.get('score')} ({rm.get('count',0)}人)")
            time.sleep(1)

        # ── Step 4：國外評分（Goodreads / Amazon JP）─────────
        print("\n[4] 國外評分（Goodreads / Amazon JP）")
        for book in books:
            isbn   = book.get("isbn") or ""
            orig_t = book.get("original_title", "")
            orig_a = book.get("original_author", "")
            title  = book["title"]
            print(f"  《{title}》")

            gr = fetch_goodreads(isbn, orig_t, orig_a)
            book["ratings"]["goodreads"] = {
                "score": gr.get("score"), "count": gr.get("count", 0),
                "url": gr.get("url", "")
            }
            print(f"    Goodreads：{gr.get('score')} ({gr.get('count',0)}人) [{gr.get('note','')}]")
            time.sleep(1.5)

            amz = fetch_amazon(br, isbn, orig_t)
            book["ratings"]["amazon"] = {
                "score": amz.get("score"), "count": amz.get("count", 0),
                "url": amz.get("url", "")
            }
            print(f"    Amazon.com：{amz.get('score')} ({amz.get('count',0)}人)")
            time.sleep(1.5)

    # ── 加權綜合分 ────────────────────────────────────────────
    for book in books:
        ws = wt = 0.0
        for v in book["ratings"].values():
            s = v.get("score")
            c = max(v.get("count", 0), 1)
            if s:
                ws += s * c
                wt += c
        book["avg_score"] = round(ws / wt, 2) if wt else None

    # ── 儲存 ─────────────────────────────────────────────────
    output = {"year": y, "week": w, "kobo_url": blog_url,
              "updated_at": now.isoformat(), "books": books}

    for path in [DATA_DIR / f"books-{y}-w{w:02d}.json", DATA_DIR / "latest.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    # ── 摘要 ─────────────────────────────────────────────────
    print(f"\n✅ 完成！{len(books)} 本書")
    for src in ["kobo", "books_com", "readmoo", "goodreads", "amazon"]:
        hit = sum(1 for b in books if b["ratings"].get(src, {}).get("score"))
        print(f"   {src:12s} {hit}/{len(books)}")


if __name__ == "__main__":
    y = int(sys.argv[1]) if len(sys.argv) > 1 else None
    w = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run(y, w)
