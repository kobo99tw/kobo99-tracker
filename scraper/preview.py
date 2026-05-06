"""
Kobo99 本機預覽伺服器
執行：python scraper/preview.py
開啟：http://localhost:8188/admin
需要：pip install flask
"""
import sys, os, subprocess, webbrowser, threading, json as _json
from datetime import datetime, timezone, timedelta, date as Date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scrape import generate_ics
from flask import Flask, request, send_from_directory, jsonify, make_response

sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR  = Path(__file__).parent.parent / "docs"
SCRAPE_PY = Path(__file__).parent / "scrape.py"
ROOT_DIR  = Path(__file__).parent.parent
PORT      = 8188

app = Flask(__name__, static_folder=None)

_lock    = threading.Lock()
_running = False
_log     = []
_status  = "idle"


def _calc_avg(ratings):
    total, count = 0.0, 0
    for src in ("kobo", "books_com", "readmoo", "goodreads", "amazon_com"):
        r = (ratings or {}).get(src) or {}
        s = r.get("score")
        c = r.get("count") or 0
        if s is not None and c > 0:
            total += s * c
            count += c
    return round(total / count, 2) if count else None


# ── 服務 docs/ ───────────────────────────────────────────────
@app.route("/")
def preview():
    return send_from_directory(DOCS_DIR, "index.html")

@app.route("/<path:filename>")
def docs_file(filename):
    return send_from_directory(DOCS_DIR, filename)


# ── 控制面板 ─────────────────────────────────────────────────
@app.route("/admin")
def admin():
    tw = timezone(timedelta(hours=8))
    today = datetime.now(tw).date()
    days  = (today.weekday() - 3) % 7
    last_thu = today - timedelta(days=days)
    cal = last_thu.isocalendar()
    suggested = f"https://www.kobo.com/zh/blog/weekly-dd99-{cal.year}-w{cal.week}"
    resp = make_response(ADMIN_HTML.replace("{{SUGGESTED_URL}}", suggested))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/admin.js")
def admin_js():
    resp = make_response(ADMIN_JS)
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ── API：啟動爬蟲 ────────────────────────────────────────────
@app.route("/api/run")
def api_run():
    global _running, _log, _status
    with _lock:
        if _running:
            return jsonify({"error": "already_running"}), 409
        _running = True
        _log     = []
        _status  = "running"

    url = request.args.get("url", "").strip()

    def worker():
        global _running, _status
        cmd = [sys.executable, "-u", str(SCRAPE_PY)]
        if url:
            cmd += ["--url", url]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace",
                env=env, cwd=str(ROOT_DIR),
            )
            while True:
                line = proc.stdout.readline()
                if line:
                    with _lock:
                        _log.append(line.rstrip())
                elif proc.poll() is not None:
                    break
            with _lock:
                _status = "done" if proc.returncode == 0 else "error"
        except Exception as e:
            with _lock:
                _log.append(f"❌ 錯誤：{e}")
                _status = "error"
        finally:
            _running = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


# ── API：取 log ──────────────────────────────────────────────
@app.route("/api/log")
def api_log():
    offset = int(request.args.get("offset", 0))
    with _lock:
        lines  = _log[offset:]
        status = _status
    return jsonify({"lines": lines, "status": status})


# ── API：發佈到 GitHub ───────────────────────────────────────
@app.route("/api/publish")
def api_publish():
    global _running, _log, _status
    with _lock:
        if _running:
            return jsonify({"error": "already_running"}), 409
        _running = True
        _log     = []
        _status  = "running"

    def worker():
        global _running, _status
        try:
            lp = DOCS_DIR / "data" / "latest.json"
            wlabel = "書單"
            if lp.exists():
                with open(lp, encoding="utf-8") as f:
                    d = _json.load(f)
                wlabel = f"{d.get('year','')}-w{d.get('week','')}"
            with _lock:
                _log.append(f"📤 發佈 {wlabel} 到 GitHub…")
            for cmd in [
                ["git", "add", "docs/data/", "docs/calendar.ics"],
                ["git", "commit", "-m", f"更新書單 {wlabel}"],
                ["git", "push"],
            ]:
                with _lock:
                    _log.append("$ " + " ".join(cmd))
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding="utf-8", errors="replace", cwd=str(ROOT_DIR),
                )
                for line in proc.stdout:
                    if line.rstrip():
                        with _lock:
                            _log.append(line.rstrip())
                proc.wait()
                if proc.returncode != 0 and cmd[1] != "commit":
                    with _lock:
                        _log.append(f"❌ 失敗（exit {proc.returncode}）")
                        _status = "error"
                    return
            with _lock:
                _log.append("✅ 已發佈！GitHub Pages 幾分鐘後更新。")
                _status = "done"
        except Exception as e:
            with _lock:
                _log.append(f"❌ 錯誤：{e}")
                _status = "error"
        finally:
            _running = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


# ── API：從 GitHub 拉取最新資料 ─────────────────────────────
@app.route("/api/pull")
def api_pull():
    global _running, _log, _status
    with _lock:
        if _running:
            return jsonify({"error": "already_running"}), 409
        _running = True
        _log     = []
        _status  = "running"

    def worker():
        global _running, _status
        try:
            with _lock:
                _log.append("⬇ 從 GitHub 拉取最新資料…")
            proc = subprocess.Popen(
                ["git", "pull", "--ff-only"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", cwd=str(ROOT_DIR),
            )
            for line in proc.stdout:
                if line.rstrip():
                    with _lock:
                        _log.append(line.rstrip())
            proc.wait()
            with _lock:
                if proc.returncode == 0:
                    _log.append("✅ 已同步最新資料！")
                    _status = "done"
                else:
                    _log.append("❌ git pull 失敗，請確認網路或手動處理衝突")
                    _status = "error"
        except Exception as e:
            with _lock:
                _log.append(f"❌ 錯誤：{e}")
                _status = "error"
        finally:
            _running = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


# ── API：書單資訊（完整欄位）────────────────────────────────
@app.route("/api/info")
def api_info():
    lp = DOCS_DIR / "data" / "latest.json"
    if not lp.exists():
        return jsonify({})
    with open(lp, encoding="utf-8") as f:
        d = _json.load(f)
    books = d.get("books", [])
    year, week = d.get("year"), d.get("week")

    # 讀取上次備份（供全欄位對照用）
    prev_books: dict = {}
    if year and week:
        prev_path = DOCS_DIR / "data" / f"books-{year}-w{week:02d}-prev.json"
        if prev_path.exists():
            with open(prev_path, encoding="utf-8") as f:
                prev_d = _json.load(f)
            for b in prev_d.get("books", []):
                prev_books[str(b.get("isbn", ""))] = {
                    "date":           b.get("date", ""),
                    "title":          b.get("title", ""),
                    "kobo_price":     b.get("kobo_price", ""),
                    "kobo_url":       b.get("kobo_url", ""),
                    "ratings":        b.get("ratings", {}),
                }

    return jsonify({
        "year":        year,
        "week":        week,
        "updated_at":  (d.get("updated_at") or "")[:16],
        "sale_label":  d.get("sale_label", ""),
        "books_count": len(books),
        "books": [
            {
                "title":          b.get("title", ""),
                "author":         b.get("author", ""),
                "date":           b.get("date", ""),
                "isbn":           b.get("isbn", ""),
                "original_title": b.get("original_title", ""),
                "kobo_price":     b.get("kobo_price", ""),
                "sale_price":     b.get("sale_price", ""),
                "publisher":      b.get("publisher", ""),
                "publish_date":   b.get("publish_date", ""),
                "avg_score":      b.get("avg_score"),
                "ratings":        b.get("ratings", {}),
                "prev":           prev_books.get(str(b.get("isbn", "")), {}),
            }
            for b in books
        ],
    })


# ── API：手動修正評分（寫回 JSON + 重算 avg）────────────────
@app.route("/api/patch", methods=["POST"])
def api_patch():
    data   = request.json or {}
    isbn   = str(data.get("isbn", "")).strip()
    source = data.get("source", "").strip()
    if not isbn or source not in ("kobo", "books_com", "readmoo", "goodreads", "amazon_com"):
        return jsonify({"error": "invalid params"}), 400

    score_raw = data.get("score")
    count_raw = data.get("count")
    url       = str(data.get("url", "")).strip()
    score = float(score_raw) if score_raw not in (None, "", "null") else None
    if score is not None and score <= 0:
        score = None
    count = int(count_raw)   if count_raw not in (None, "", "null") else 0

    lp = DOCS_DIR / "data" / "latest.json"
    if not lp.exists():
        return jsonify({"error": "no data"}), 404
    with open(lp, encoding="utf-8") as f:
        ld = _json.load(f)
    year, week = ld.get("year"), ld.get("week")
    week_file  = DOCS_DIR / "data" / f"books-{year}-w{week}.json"

    new_avg = None
    for fpath in (lp, week_file):
        if not fpath.exists():
            continue
        with open(fpath, encoding="utf-8") as f:
            d = _json.load(f)
        updated = False
        for book in d.get("books", []):
            if str(book.get("isbn", "")) == isbn:
                r = book.setdefault("ratings", {}).setdefault(source, {})
                r["score"] = score
                r["count"] = count
                r["url"]   = url
                new_avg = _calc_avg(book["ratings"])
                book["avg_score"] = new_avg
                updated = True
                break
        if updated:
            with open(fpath, "w", encoding="utf-8") as f:
                _json.dump(d, f, ensure_ascii=False, indent=2)

    if new_avg is not None and year and week:
        # 寫入 corrections.json（讓下次重爬時保留此修正）
        corr_path = DOCS_DIR / "data" / "corrections.json"
        try:
            corrections = _json.loads(corr_path.read_text(encoding="utf-8")) if corr_path.exists() else {}
            corrections.setdefault(f"{year}-w{week:02d}", {}).setdefault(isbn, {})[source] = {
                "score": score, "count": count, "url": url
            }
            corr_path.write_text(_json.dumps(corrections, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[warn] corrections.json 寫入失敗: {e}")

        # 重建 ICS
        try:
            with open(lp, encoding="utf-8") as f:
                updated = _json.load(f)
            sale_start = Date.fromisocalendar(year, week, 4)
            generate_ics(updated.get("books", []), year, week, sale_start)
        except Exception as e:
            print(f"[warn] ICS 重建失敗: {e}")

    return jsonify({"ok": True, "avg_score": new_avg})


# ── API：修正書本欄位（原價等）────────────────────────────────
@app.route("/api/patch_book", methods=["POST"])
def api_patch_book():
    data  = request.json or {}
    isbn  = str(data.get("isbn", "")).strip()
    field = data.get("field", "").strip()
    value = data.get("value", "")
    if not isbn or field not in ("kobo_price",):
        return jsonify({"error": "invalid params"}), 400

    lp = DOCS_DIR / "data" / "latest.json"
    if not lp.exists():
        return jsonify({"error": "no data"}), 404
    with open(lp, encoding="utf-8") as f:
        ld = _json.load(f)
    year, week = ld.get("year"), ld.get("week")
    week_file  = DOCS_DIR / "data" / f"books-{year}-w{week}.json"

    updated_val = None
    for fpath in (lp, week_file):
        if not fpath.exists():
            continue
        with open(fpath, encoding="utf-8") as f:
            d = _json.load(f)
        for book in d.get("books", []):
            if str(book.get("isbn", "")) == isbn:
                book[field] = value
                updated_val = value
                break
        if updated_val is not None:
            with open(fpath, "w", encoding="utf-8") as f:
                _json.dump(d, f, ensure_ascii=False, indent=2)

    if updated_val is not None and year and week:
        corr_path = DOCS_DIR / "data" / "corrections.json"
        try:
            corrections = _json.loads(corr_path.read_text(encoding="utf-8")) if corr_path.exists() else {}
            corrections.setdefault(f"{year}-w{week:02d}", {}).setdefault(isbn, {}).setdefault("_book", {})[field] = value
            corr_path.write_text(_json.dumps(corrections, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[warn] corrections.json 寫入失敗: {e}")
        try:
            with open(lp, encoding="utf-8") as f:
                updated = _json.load(f)
            sale_start = Date.fromisocalendar(year, week, 4)
            generate_ics(updated.get("books", []), year, week, sale_start)
        except Exception as e:
            print(f"[warn] ICS 重建失敗: {e}")

    return jsonify({"ok": True, "value": updated_val})


# ── 控制面板 HTML ─────────────────────────────────────────────
ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kobo99 本機預覽</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,'Noto Sans TC',sans-serif;background:#F5F3F0;color:#1C1917;
  min-height:100vh;padding:1.75rem;font-size:.95rem;line-height:1.6}
h1{font-size:1.3rem;font-weight:700;color:#EA580C;margin-bottom:1.5rem}
.panel{background:#fff;border:1px solid #E7E5E4;border-radius:12px;
  padding:1.4rem 1.6rem;margin-bottom:1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.panel-title{font-size:.8rem;font-weight:700;color:#78716C;letter-spacing:.07em;
  text-transform:uppercase;margin-bottom:.95rem;display:flex;align-items:center;gap:.5rem}
.url-row{display:flex;gap:.6rem;flex-wrap:wrap}
#urlInput{flex:1;min-width:0;background:#fff;border:1.5px solid #D6D3D1;
  border-radius:8px;padding:.58rem .9rem;color:#1C1917;font-size:.9rem;outline:none}
#urlInput:focus{border-color:#F97316;box-shadow:0 0 0 3px rgba(249,115,22,.12)}
#urlInput::placeholder{color:#A8A29E}
.btn{border:none;border-radius:8px;padding:.58rem 1.15rem;font-size:.88rem;
  font-weight:600;cursor:pointer;transition:filter .15s;white-space:nowrap}
.btn:hover:not(:disabled){filter:brightness(.9)}
#pullBtn{background:#0369A1;color:#fff}
#pullBtn:disabled{opacity:.4;cursor:not-allowed}
#runBtn{background:#F97316;color:#fff}
#runBtn:disabled{opacity:.4;cursor:not-allowed}
#previewBtn{background:#0F766E;color:#fff;text-decoration:none;
  padding:.58rem 1.15rem;border-radius:8px;font-size:.88rem;font-weight:600}
#publishBtn{background:#7C3AED;color:#fff}
#publishBtn:disabled{opacity:.4;cursor:not-allowed}
#ghPagesBtn{background:#1D4ED8;color:#fff;text-decoration:none;
  padding:.58rem 1.15rem;border-radius:8px;font-size:.88rem;font-weight:600}
#weekInfo{font-size:.82rem;color:#78716C;margin-top:.8rem;line-height:1.7}
.hint{font-size:.8rem;color:#A8A29E;margin-top:.55rem}
#log{background:#1C1917;border-radius:8px;padding:1rem 1.1rem;
  font-family:'Courier New',monospace;font-size:.84rem;color:#D6D3D1;
  line-height:1.7;min-height:160px;max-height:420px;overflow-y:auto;
  white-space:pre-wrap;word-break:break-all}
.log-hd{display:flex;align-items:center;gap:.5rem;margin-bottom:.6rem}
.log-hd span{flex:1;font-size:.8rem;font-weight:700;color:#78716C;
  letter-spacing:.07em;text-transform:uppercase}
.btn-sm{background:#F5F3F0;border:1px solid #D6D3D1;color:#78716C;
  border-radius:6px;padding:.3rem .8rem;font-size:.76rem;cursor:pointer}
.btn-sm:hover{border-color:#A8A29E;color:#44403C}
.badge{display:inline-block;font-size:.73rem;padding:.2rem .6rem;
  border-radius:20px;font-weight:600}
.st-idle{background:#F5F3F0;color:#78716C;border:1px solid #E7E5E4}
.st-running{background:#FFF7ED;color:#C2410C;border:1px solid #FDBA74}
.st-done{background:#F0FDF4;color:#15803D;border:1px solid #86EFAC}
.st-error{background:#FEF2F2;color:#B91C1C;border:1px solid #FCA5A5}

/* ── 書單審查表格 ── */
.rt{width:100%;border-collapse:collapse;font-size:.84rem;min-width:860px}
.rt th{background:#F9F8F7;color:#78716C;padding:.5rem .65rem;text-align:center;
  white-space:nowrap;border-bottom:2px solid #D6D3D1;font-weight:700;
  letter-spacing:.04em;font-size:.73rem;text-transform:uppercase}
.rt td{padding:.55rem .65rem;border-bottom:1px solid #F0EEEc;vertical-align:middle}
.rt tbody tr:hover td{background:#FFFBF5}
.dt{color:#78716C;font-size:.84rem;white-space:nowrap;text-align:center;font-weight:600}
.dow{font-size:.74rem;color:#A8A29E;margin-left:.1rem;font-weight:400}
.bt{font-weight:600;color:#1C1917;display:block;max-width:160px;line-height:1.35;font-size:.88rem}
.ba{color:#A8A29E;font-size:.74rem;display:block;margin-top:.1rem}
.ot{color:#78716C;font-size:.76rem;max-width:120px;word-break:break-word}
.mono{font-family:'Courier New',monospace;font-size:.73rem;color:#A8A29E;white-space:nowrap}
.price{font-size:.82rem;color:#44403C;white-space:nowrap;text-align:right;cursor:pointer}
.price:hover{background:#FFFBF5!important}
.rc{text-align:center;cursor:pointer;padding:.45rem .35rem;user-select:none}
.rc:hover{background:#FFF7ED!important}
.rc-empty .rc-miss{color:#D6D3D1;font-weight:700}
.rc-score{color:#0F766E;font-weight:700}
.rc-prev{font-size:.66rem;color:#A8A29E;display:block;margin-top:.1rem}
.rc-changed{background:#FFF7ED!important}
.cell-warn{background:#FFF7ED!important}
.cell-alert{background:#FEF2F2!important}
.cell-diff{font-size:.68rem;color:#C2410C;display:block;margin-top:.1rem}
.cell-diff-alert{font-size:.68rem;color:#B91C1C;display:block;margin-top:.1rem;font-weight:700}
#diffSummary{background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
  padding:.7rem 1rem;margin-bottom:.9rem;font-size:.82rem;line-height:1.8}
#diffSummary strong{color:#92400E;font-size:.78rem;letter-spacing:.04em;
  text-transform:uppercase;display:block;margin-bottom:.25rem}
.diff-critical{color:#B91C1C;font-weight:600}
.diff-warn{color:#C2410C}
.rpop-prev{font-size:.75rem;color:#78716C;margin:.6rem 0 .3rem;padding:.4rem .6rem;
  background:#F9F8F7;border-radius:6px;display:flex;justify-content:space-between;align-items:center}
.rpop-prev span{color:#44403C}
.rpop-use-prev{border:none;background:#E7E5E4;border-radius:5px;padding:.2rem .55rem;
  font-size:.72rem;cursor:pointer;color:#44403C}
.rpop-use-prev:hover{background:#D6D3D1}
.rc-cnt{font-size:.7rem;color:#A8A29E;margin-left:.15rem}
#rBack{position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.15);cursor:default}
.rc-url{font-size:.68rem;color:#A8A29E;cursor:pointer;text-decoration:underline;
  display:block;margin-top:.1rem;max-width:80px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.rpop-url-row{display:flex;gap:.35rem;align-items:center}
.rpop-url-row input{flex:1}
.rpop-open{border:none;background:#F5F3F0;border:1px solid #D6D3D1;border-radius:5px;
  padding:.3rem .55rem;font-size:.75rem;cursor:pointer;white-space:nowrap;color:#44403C}
.rpop-open:hover{border-color:#A8A29E}
.avg{text-align:center;font-weight:700;color:#EA580C;font-size:.84rem;white-space:nowrap}

/* ── 編輯浮層 ── */
.rpop{position:fixed;z-index:9999;background:#fff;border:1.5px solid #E7E5E4;
  border-radius:12px;padding:1.1rem 1.2rem;width:300px;
  box-shadow:0 8px 32px rgba(0,0,0,.14)}
.rpop-t{font-size:.85rem;font-weight:700;color:#EA580C;margin-bottom:.9rem}
.rpop label{display:flex;align-items:center;gap:.55rem;font-size:.8rem;
  color:#78716C;margin-bottom:.48rem}
.rpop input{flex:1;background:#F9F8F7;border:1.5px solid #E7E5E4;border-radius:6px;
  padding:.35rem .65rem;color:#1C1917;font-size:.82rem;outline:none;min-width:0}
.rpop input:focus{border-color:#F97316;background:#fff}
.rpop-btns{display:flex;gap:.5rem;margin-top:.95rem;justify-content:flex-end}
.rpop-save,.rpop-cancel{border:none;border-radius:6px;padding:.38rem .95rem;
  font-size:.8rem;font-weight:600;cursor:pointer}
.rpop-save{background:#F97316;color:#fff}
.rpop-save:hover{background:#EA580C}
.rpop-cancel{background:#F5F3F0;color:#57534E;border:1px solid #D6D3D1}
.rpop-cancel:hover{border-color:#A8A29E}
</style>
</head>
<body>
<h1>🔧 Kobo99 本機預覽</h1>

<div class="panel">
  <div class="panel-title">
    書單網址
    <span id="badge" class="badge st-idle">待機</span>
  </div>
  <div class="url-row">
    <input id="urlInput" type="text" value="{{SUGGESTED_URL}}"
      placeholder="留空 = 自動從部落格主頁偵測最新書單">
    <button id="pullBtn"    class="btn" onclick="pullFromGitHub()">⬇ 拉取更新</button>
    <button id="runBtn"     class="btn" onclick="startFetch()">🔄 重新抓取</button>
    <a id="previewBtn"      class="btn" href="/" target="_blank">📚 查看書單</a>
    <button id="publishBtn" class="btn" onclick="publishToGitHub()">📤 發佈到 GitHub</button>
    <a id="ghPagesBtn"      class="btn" href="https://kobo99tw.github.io/kobo99-tracker/" target="_blank">🌐 GitHub Pages</a>
  </div>
  <p class="hint">留空 → 自動偵測最新書單　｜　貼入指定網址 → 強制抓取該週</p>
  <div id="weekInfo"></div>
</div>

<div class="panel">
  <div class="log-hd">
    <span>執行紀錄</span>
    <button class="btn-sm" onclick="clearLog()">清除</button>
  </div>
  <pre id="log">（尚未執行）</pre>
</div>

<div class="panel" id="reviewPanel" style="display:none">
  <div class="panel-title">
    書單資料審查
    <span style="font-size:.7rem;color:#57534E;font-weight:400;text-transform:none;letter-spacing:0;margin-left:.25rem">
      ← 點擊評分格可編輯；連結可開啟原始頁面驗證
    </span>
  </div>
  <div id="diffSummary" style="display:none"></div>
  <div style="overflow-x:auto" id="reviewTableWrap"></div>
</div>

<script src="/admin.js"></script>
</body>
</html>"""

ADMIN_JS = """
let polling      = null;
let offset       = 0;
let _books       = [];
let _editISBN    = null, _editSrc = null;
let _pollingFor  = 'fetch'; // 'fetch' | 'publish' | 'pull'
let _year        = null;

const DOW = ['日','一','二','三','四','五','六'];
function weekday(dateStr) {
  if (!_year || !dateStr) return '';
  const [m, d] = dateStr.split('/').map(Number);
  return '(' + DOW[new Date(_year, m - 1, d).getDay()] + ')';
}

function markDirty() {
  const btn = document.getElementById('publishBtn');
  if (btn) btn.textContent = '📤 發佈到 GitHub \\u2B06';
}
function clearDirty() {
  const btn = document.getElementById('publishBtn');
  if (btn) btn.textContent = '📤 發佈到 GitHub';
}

const SRCLABELS = {
  kobo: 'Kobo', books_com: '博客來',
  readmoo: '讀墨', goodreads: 'GR', amazon_com: 'AMZ'
};

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function badge(type, text) {
  const b = document.getElementById('badge');
  b.className = 'badge st-' + type;
  b.textContent = text;
}

function appendLog(line) {
  const el = document.getElementById('log');
  const placeholders = ['（尚未執行）', '（已清除）', '⏳ 啟動中…'];
  el.textContent = placeholders.includes(el.textContent) ? line : el.textContent + '\\n' + line;
  el.scrollTop = el.scrollHeight;
}

function startFetch() {
  if (polling) { clearInterval(polling); polling = null; }
  const url = document.getElementById('urlInput').value.trim();
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 抓取中…';
  document.getElementById('publishBtn').disabled = true;
  document.getElementById('log').textContent = '⏳ 啟動中…';
  badge('running', '抓取中');
  _pollingFor = 'fetch';

  const qs = url ? '?url=' + encodeURIComponent(url) : '';
  fetch('/api/run' + qs)
    .then(r => r.json())
    .then(data => {
      if (data.error === 'already_running') {
        document.getElementById('log').textContent = '⚠️ 已有任務執行中，請稍候';
        btn.disabled = false;
        btn.textContent = '🔄 重新抓取';
        badge('idle', '待機');
        return;
      }
      offset = 0;
      polling = setInterval(pollLog, 300);
    })
    .catch(err => {
      appendLog('❌ 連線失敗：' + err);
      btn.disabled = false;
      btn.textContent = '🔄 重新抓取';
      badge('error', '失敗');
    });
}

function pollLog() {
  fetch('/api/log?offset=' + offset)
    .then(r => r.json())
    .then(data => {
      for (const line of data.lines) { appendLog(line); offset++; }
      if (data.status === 'done' || data.status === 'error') {
        clearInterval(polling); polling = null;
        document.getElementById('runBtn').disabled = false;
        document.getElementById('runBtn').textContent = '🔄 重新抓取';
        document.getElementById('publishBtn').disabled = false;
        if (data.status === 'done') {
          if (_pollingFor === 'publish') {
            clearDirty();
            appendLog('\\n✅ 已發佈到 GitHub！');
            badge('done', '已發佈 ✓');
          } else if (_pollingFor === 'pull') {
            document.getElementById('pullBtn').disabled = false;
            document.getElementById('pullBtn').textContent = '⬇ 拉取更新';
            appendLog('\\n✅ 書單已同步，表格已更新。');
            badge('done', '已同步 ✓');
            loadWeekInfo();
          } else {
            markDirty();
            appendLog('\\n✅ 完成！可點「查看書單」預覽，或「發佈到 GitHub」上線。');
            badge('done', '完成 ✓');
            loadWeekInfo();
          }
        } else {
          if (_pollingFor === 'pull') {
            document.getElementById('pullBtn').disabled = false;
            document.getElementById('pullBtn').textContent = '⬇ 拉取更新';
          }
          badge('error', '失敗 ✗');
        }
      }
    });
}

function clearLog() {
  document.getElementById('log').textContent = '（已清除）';
  offset = 0;
}

function pullFromGitHub() {
  if (polling) { clearInterval(polling); polling = null; }
  _pollingFor = 'pull';
  const btn = document.getElementById('pullBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 同步中…';
  document.getElementById('log').textContent = '⏳ 拉取中…';
  badge('running', '同步中');
  fetch('/api/pull')
    .then(r => r.json())
    .then(() => { offset = 0; polling = setInterval(pollLog, 300); })
    .catch(err => {
      appendLog('❌ 連線失敗：' + err);
      btn.disabled = false;
      btn.textContent = '⬇ 拉取更新';
      badge('error', '失敗');
    });
}

function publishToGitHub() {
  if (polling) { clearInterval(polling); polling = null; }
  _pollingFor = 'publish';
  const btn = document.getElementById('publishBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 發佈中…';
  document.getElementById('log').textContent = '⏳ 發佈中…';
  badge('running', '發佈中');
  fetch('/api/publish')
    .then(r => r.json())
    .then(() => { offset = 0; polling = setInterval(pollLog, 300); })
    .catch(err => {
      appendLog('❌ 連線失敗：' + err);
      document.getElementById('publishBtn').disabled = false;
      document.getElementById('publishBtn').textContent = '📤 發佈到 GitHub';
      badge('error', '失敗');
    });
}

// ── 書單審查表格 ─────────────────────────────────────────────

function fmtRating(isbn, src, r, prevR) {
  r = r || {}; prevR = prevR || {};
  const sc = r.score, cnt = r.count || 0, url = r.url || '';
  const psc = prevR.score, pcnt = prevR.count || 0, purl = prevR.url || '';
  const miss = (sc == null);
  const changed = psc != null && sc !== psc;
  let inner = miss
    ? '<span class="rc-miss">?</span>'
    : '<span class="rc-score">\\u2605' + sc.toFixed(1) + '</span>'
      + '<span class="rc-cnt">(' + cnt + ')</span>';
  if (url) inner += '<span class="rc-url">🔗</span>';
  if (changed) inner += '<span class="rc-prev">舊:' + psc.toFixed(1) + '(' + pcnt + ')</span>';
  return '<td class="rc' + (miss ? ' rc-empty' : '') + (changed ? ' rc-changed' : '') + '"'
    + ' data-isbn="' + esc(isbn) + '"'
    + ' data-src="' + src + '"'
    + ' data-score="' + (sc != null ? sc : '') + '"'
    + ' data-count="' + cnt + '"'
    + ' data-url="' + esc(url) + '"'
    + ' data-prev-score="' + (psc != null ? psc : '') + '"'
    + ' data-prev-count="' + pcnt + '"'
    + ' data-prev-url="' + esc(purl) + '"'
    + ' onclick="openEditPop(this)" title="點擊編輯">' + inner + '</td>';
}

function renderReviewTable(books) {
  _books = books || [];
  const panel = document.getElementById('reviewPanel');
  if (!_books.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  const srcs = ['kobo','books_com','readmoo','goodreads','amazon_com'];
  let body = '';
  const diffs = [];
  for (const b of _books) {
    const avg = b.avg_score;
    body += '<tr>';
    const prev  = b.prev || {};
    const prevR = prev.ratings || {};

    // 主資料欄位比對
    const dateChg  = prev.date  && prev.date  !== b.date;
    const titleChg = prev.title && prev.title !== b.title;
    const priceChg = prev.kobo_price && prev.kobo_price !== b.kobo_price;

    body += '<td class="dt' + (dateChg ? ' cell-alert' : '') + '">'
          + esc(b.date) + '<span class="dow">' + weekday(b.date) + '</span>'
          + (dateChg ? '<span class="cell-diff-alert">舊:' + esc(prev.date) + '</span>' : '')
          + '</td>';
    body += '<td class="' + (titleChg ? 'cell-warn' : '') + '">'
          + '<span class="bt">' + esc(b.title) + '</span>'
          + '<span class="ba">' + esc(b.author) + '</span>'
          + (titleChg ? '<span class="cell-diff">舊:' + esc(prev.title) + '</span>' : '')
          + '</td>';
    body += '<td class="mono">' + esc(b.isbn) + '</td>';
    body += '<td class="price' + (priceChg ? ' cell-warn' : '') + '" data-isbn="' + esc(b.isbn) + '" data-price="'
          + esc(b.kobo_price || '') + '" onclick="openPriceEditPop(this)" title="點擊編輯原價">'
          + esc(b.kobo_price || '\\u2014')
          + (priceChg ? '<span class="cell-diff">舊:' + esc(prev.kobo_price) + '</span>' : '')
          + '</td>';
    body += '<td class="ot">' + esc(b.original_title || '\\u2014') + '</td>';
    for (const s of srcs) body += fmtRating(b.isbn, s, (b.ratings || {})[s], prevR[s]);
    body += '<td class="avg">' + (avg != null ? '\\u2605' + avg.toFixed(2) : '\\u2014') + '</td>';
    body += '</tr>';

    // 收集變更摘要
    if (dateChg)  diffs.push({ level:'alert', text:'日期變更 《' + b.title + '》 ' + prev.date + ' → ' + b.date });
    if (titleChg) diffs.push({ level:'warn',  text:'書名變更 ' + prev.title + ' → ' + b.title });
    if (priceChg) diffs.push({ level:'warn',  text:'原價變更 《' + b.title + '》 ' + prev.kobo_price + ' → ' + b.kobo_price });
    for (const s of srcs) {
      const cur = (b.ratings||{})[s]||{}, pv = prevR[s]||{};
      if (pv.score != null && cur.score !== pv.score)
        diffs.push({ level:'warn', text: SRCLABELS[s] + ' 評分變更 《' + b.title + '》 ' + pv.score + ' → ' + (cur.score??'無') });
    }
  }

  // 顯示變更摘要
  const summaryEl = document.getElementById('diffSummary');
  if (diffs.length) {
    summaryEl.style.display = '';
    summaryEl.innerHTML = '<strong>⚠ 與上次抓取相比有 ' + diffs.length + ' 處變更</strong>'
      + diffs.map(d =>
          '<span class="' + (d.level==='alert' ? 'diff-critical' : 'diff-warn') + '">• ' + esc(d.text) + '</span>'
        ).join('<br>');
  } else {
    summaryEl.style.display = 'none';
  }

  document.getElementById('reviewTableWrap').innerHTML =
    '<table class="rt"><thead><tr>'
    + '<th>日期</th><th>書名 / 作者</th><th>ISBN</th><th>原價</th><th>原文名</th>'
    + '<th>Kobo</th><th>博客來</th><th>讀墨</th><th>GR</th><th>AMZ</th>'
    + '<th>綜合</th></tr></thead><tbody>' + body + '</tbody></table>';
}

// ── 浮層編輯 ─────────────────────────────────────────────────

function _showPop(pop, anchorRect, onSave) {
  const popH = 240, popW = 310, gap = 6;
  const top  = (window.innerHeight - anchorRect.bottom >= popH + gap)
    ? anchorRect.bottom + gap
    : Math.max(gap, anchorRect.top - popH - gap);
  const left = Math.max(gap, Math.min(anchorRect.left, window.innerWidth - popW - gap));
  pop.style.top  = top  + 'px';
  pop.style.left = left + 'px';
  const back = document.createElement('div');
  back.id = 'rBack';
  back.addEventListener('click', onSave || closeEditPop);
  document.body.appendChild(back);
  document.body.appendChild(pop);
}

function openEditPop(cell) {
  closeEditPop();
  _editISBN = cell.dataset.isbn;
  _editSrc  = cell.dataset.src;
  const curUrl  = cell.dataset.url || '';
  const prevSc  = cell.dataset.prevScore || '';
  const prevCnt = cell.dataset.prevCount || '0';
  const prevUrl = cell.dataset.prevUrl   || '';
  const hasPrev = prevSc !== '' && prevSc !== cell.dataset.score;
  const pop = document.createElement('div');
  pop.id = 'rPop';
  pop.className = 'rpop';
  pop.innerHTML =
    '<div class="rpop-t">\\u270f\\ufe0f 編輯 ' + esc(SRCLABELS[_editSrc] || _editSrc) + '</div>'
    + (hasPrev
      ? '<div class="rpop-prev">舊值：<span>\\u2605' + parseFloat(prevSc).toFixed(1)
        + ' (' + prevCnt + ')</span>'
        + '<button class="rpop-use-prev" onclick="usePrevRating()">套用舊值</button></div>'
      : '')
    + '<label>評分<input id="rpScore" type="number" step="0.1" min="0" max="5" value="'
    + esc(cell.dataset.score) + '" placeholder="（留空=無）"></label>'
    + '<label>筆數<input id="rpCount" type="number" min="0" value="'
    + esc(cell.dataset.count) + '"></label>'
    + '<label>連結<div class="rpop-url-row">'
    + '<input id="rpUrl" type="text" autocomplete="off" value="' + esc(curUrl) + '">'
    + (curUrl ? '<button class="rpop-open" onclick="window.open(document.getElementById(\\'rpUrl\\').value,\\'_blank\\')">🔗 開啟</button>' : '')
    + '</div></label>'
    + '<div class="rpop-btns">'
    + '<button class="rpop-cancel" onclick="closeEditPop()">取消</button>'
    + '<button class="rpop-save" onclick="saveRating()">儲存</button>'
    + '</div>';
  pop.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); saveRating(); }
    if (e.key === 'Escape') closeEditPop();
  });
  _showPop(pop, cell.getBoundingClientRect(), saveRating);
  document.getElementById('rpScore').focus();
}

function openPriceEditPop(cell) {
  closeEditPop();
  _editISBN = cell.dataset.isbn;
  _editSrc  = '__price__';
  const pop = document.createElement('div');
  pop.id = 'rPop';
  pop.className = 'rpop';
  pop.innerHTML =
    '<div class="rpop-t">\\u270f\\ufe0f 編輯原價</div>'
    + '<label>原價<input id="rpPrice" type="text" autocomplete="off" value="'
    + esc(cell.dataset.price) + '" placeholder="NT$xxx"></label>'
    + '<div class="rpop-btns">'
    + '<button class="rpop-cancel" onclick="closeEditPop()">取消</button>'
    + '<button class="rpop-save" onclick="savePrice()">儲存</button>'
    + '</div>';
  pop.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); savePrice(); }
    if (e.key === 'Escape') closeEditPop();
  });
  _showPop(pop, cell.getBoundingClientRect(), savePrice);
  document.getElementById('rpPrice').focus();
}

function usePrevRating() {
  const cell = document.querySelector(
    '.rc[data-isbn="' + (_editISBN||'') + '"][data-src="' + (_editSrc||'') + '"]');
  if (!cell) return;
  const s = document.getElementById('rpScore');
  const c = document.getElementById('rpCount');
  const u = document.getElementById('rpUrl');
  if (s) s.value = cell.dataset.prevScore || '';
  if (c) c.value = cell.dataset.prevCount || '0';
  if (u) u.value = cell.dataset.prevUrl   || '';
}

function closeEditPop() {
  const p = document.getElementById('rPop');
  if (p) p.remove();
  const b = document.getElementById('rBack');
  if (b) b.remove();
  _editISBN = null; _editSrc = null;
}

function saveRating() {
  if (!_editISBN || !_editSrc) return;
  const scoreEl = document.getElementById('rpScore');
  if (!scoreEl) return;
  const scoreV = scoreEl.value.trim();
  const countV = parseInt(document.getElementById('rpCount').value) || 0;
  const urlV   = document.getElementById('rpUrl').value.trim();
  const isbn = _editISBN, src = _editSrc;
  closeEditPop();

  fetch('/api/patch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      isbn, source: src,
      score: (scoreV === '' || parseFloat(scoreV) <= 0) ? null : parseFloat(scoreV),
      count: countV, url: urlV
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      for (const b of _books) {
        if (String(b.isbn) === String(isbn)) {
          if (!b.ratings) b.ratings = {};
          if (!b.ratings[src]) b.ratings[src] = {};
          b.ratings[src].score = (scoreV === '' || parseFloat(scoreV) <= 0) ? null : parseFloat(scoreV);
          b.ratings[src].count = countV;
          b.ratings[src].url   = urlV;
          b.avg_score = data.avg_score;
          break;
        }
      }
      renderReviewTable(_books);
      appendLog('\\u2705 已儲存 ' + (SRCLABELS[src] || src) + ' 評分（ICS 已更新，記得發佈到 GitHub）');
      markDirty();
    } else {
      appendLog('\\u274c 儲存失敗：' + JSON.stringify(data));
    }
  })
  .catch(e => appendLog('\\u274c 儲存錯誤：' + e));
}

function savePrice() {
  if (!_editISBN) return;
  const el = document.getElementById('rpPrice');
  if (!el) return;
  const val = el.value.trim();
  const isbn = _editISBN;
  closeEditPop();
  fetch('/api/patch_book', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ isbn, field: 'kobo_price', value: val })
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      for (const b of _books) {
        if (String(b.isbn) === String(isbn)) { b.kobo_price = val; break; }
      }
      renderReviewTable(_books);
      appendLog('\\u2705 已儲存原價（ICS 已更新，記得發佈到 GitHub）');
      markDirty();
    } else {
      appendLog('\\u274c 儲存失敗：' + JSON.stringify(data));
    }
  })
  .catch(e => appendLog('\\u274c 儲存錯誤：' + e));
}

// ── 書單資訊 + 渲染表格 ──────────────────────────────────────

function loadWeekInfo() {
  fetch('/api/info')
    .then(r => r.json())
    .then(d => {
      if (!d.week) return;
      _year = d.year;
      document.getElementById('weekInfo').textContent =
        '目前資料：第 ' + d.week + ' 週｜' + d.sale_label
        + '｜' + d.books_count + ' 本｜更新 ' + d.updated_at;
      renderReviewTable(d.books);
      document.getElementById('previewBtn').style.display = 'inline-block';
      const pub = document.getElementById('publishBtn');
      pub.style.display = 'inline-block';
      pub.disabled = false;
      pub.textContent = '📤 發佈到 GitHub';
      badge('done', '已就緒');
    });
}

// ── 頁面啟動 ─────────────────────────────────────────────────

fetch('/api/log?offset=0')
  .then(r => r.json())
  .then(data => {
    if (!data.lines.length && data.status === 'idle') return;
    for (const line of data.lines) { appendLog(line); offset++; }
    if (data.status === 'running') {
      badge('running', '抓取中');
      document.getElementById('runBtn').disabled = true;
      document.getElementById('runBtn').textContent = '⏳ 抓取中…';
      polling = setInterval(pollLog, 300);
    } else if (data.status === 'done') {
      badge('done', '完成 ✓');
      document.getElementById('previewBtn').style.display = 'inline-block';
      const pub = document.getElementById('publishBtn');
      pub.style.display = 'inline-block';
      pub.disabled = false;
      pub.textContent = '📤 發佈到 GitHub';
    } else if (data.status === 'error') {
      badge('error', '失敗 ✗');
    }
  })
  .catch(err => appendLog('⚠️ 無法連線：' + err));

loadWeekInfo();
"""


if __name__ == "__main__":
    print("=" * 50)
    print("  Kobo99 本機預覽伺服器")
    print(f"  控制面板：http://localhost:{PORT}/admin")
    print(f"  書單預覽：http://localhost:{PORT}/")
    print("  Ctrl+C 停止")
    print("=" * 50)
    webbrowser.open(f"http://localhost:{PORT}/admin")
    app.run(port=PORT, debug=False, threaded=True)
