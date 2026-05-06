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


# ── API：書單資訊（完整欄位）────────────────────────────────
@app.route("/api/info")
def api_info():
    lp = DOCS_DIR / "data" / "latest.json"
    if not lp.exists():
        return jsonify({})
    with open(lp, encoding="utf-8") as f:
        d = _json.load(f)
    books = d.get("books", [])
    return jsonify({
        "year":        d.get("year"),
        "week":        d.get("week"),
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


# ── 控制面板 HTML ─────────────────────────────────────────────
ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kobo99 本機預覽</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans TC',sans-serif;background:#1C1917;color:#E7E5E4;
  min-height:100vh;padding:1.5rem}
h1{font-size:1.2rem;font-weight:700;color:#F97316;margin-bottom:1.5rem;letter-spacing:.04em}
.panel{background:#292524;border-radius:12px;padding:1.25rem 1.5rem;margin-bottom:1.25rem}
.panel-title{font-size:.8rem;font-weight:600;color:#A8A29E;letter-spacing:.08em;
  text-transform:uppercase;margin-bottom:.85rem;display:flex;align-items:center;gap:.5rem}
.url-row{display:flex;gap:.6rem;flex-wrap:wrap}
#urlInput{flex:1;min-width:0;background:#1C1917;border:1px solid #44403C;border-radius:8px;
  padding:.55rem .85rem;color:#E7E5E4;font-size:.88rem;outline:none}
#urlInput:focus{border-color:#F97316}
#urlInput::placeholder{color:#57534E}
.btn{border:none;border-radius:8px;padding:.55rem 1.1rem;font-size:.85rem;
  font-weight:600;cursor:pointer;transition:opacity .15s;white-space:nowrap}
#runBtn{background:#F97316;color:#fff}
#runBtn:disabled{opacity:.4;cursor:not-allowed}
#previewBtn{background:#0D9488;color:#fff;text-decoration:none;display:none;
  padding:.55rem 1.1rem;border-radius:8px;font-size:.85rem;font-weight:600}
#publishBtn{background:#7C3AED;color:#fff;display:none}
#publishBtn:disabled{opacity:.4;cursor:not-allowed}
#ghPagesBtn{background:#1D4ED8;color:#fff;text-decoration:none;
  padding:.55rem 1.1rem;border-radius:8px;font-size:.85rem;font-weight:600}
#weekInfo{font-size:.75rem;color:#78716C;margin-top:.75rem;line-height:1.6}
.hint{font-size:.75rem;color:#57534E;margin-top:.5rem}
#log{background:#0C0A09;border-radius:8px;padding:1rem;
  font-family:'Courier New',monospace;font-size:.78rem;color:#D6D3D1;
  line-height:1.65;min-height:160px;max-height:400px;overflow-y:auto;
  white-space:pre-wrap;word-break:break-all}
.log-hd{display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem}
.log-hd span{flex:1;font-size:.8rem;font-weight:600;color:#A8A29E;
  letter-spacing:.08em;text-transform:uppercase}
.btn-sm{background:#292524;border:1px solid #44403C;color:#A8A29E;
  border-radius:6px;padding:.25rem .7rem;font-size:.72rem;cursor:pointer}
.btn-sm:hover{border-color:#78716C}
.badge{display:inline-block;font-size:.7rem;padding:.18rem .55rem;
  border-radius:20px;font-weight:600}
.st-idle{background:#292524;color:#78716C}
.st-running{background:#431407;color:#FB923C}
.st-done{background:#042f2e;color:#2DD4BF}
.st-error{background:#450a0a;color:#F87171}

/* ── 書單審查表格 ── */
.rt{width:100%;border-collapse:collapse;font-size:.73rem;min-width:860px}
.rt th{background:#1C1917;color:#78716C;padding:.35rem .5rem;text-align:center;
  white-space:nowrap;border-bottom:2px solid #44403C;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;font-size:.65rem}
.rt td{padding:.4rem .5rem;border-bottom:1px solid #1C1917;vertical-align:middle}
.rt tr:hover td{background:rgba(255,255,255,.025)}
.dt{color:#A8A29E;font-size:.78rem;white-space:nowrap;text-align:center;font-weight:600}
.bt{font-weight:600;color:#E7E5E4;display:block;max-width:150px;line-height:1.3}
.ba{color:#57534E;font-size:.68rem;display:block;margin-top:.1rem}
.ot{color:#78716C;font-size:.7rem;max-width:110px;word-break:break-word}
.mono{font-family:'Courier New',monospace;font-size:.68rem;color:#78716C;white-space:nowrap}
.rc{text-align:center;cursor:pointer;padding:.4rem .3rem;user-select:none}
.rc:hover{background:#333!important}
.rc-empty .rc-miss{color:#44403C;font-weight:700;font-size:.85rem}
.rc-score{color:#2DD4BF;font-weight:600}
.rc-cnt{font-size:.63rem;color:#57534E;margin-left:.1rem}
.rc-a{text-decoration:none;color:inherit;display:inline-block}
.rc-a:hover .rc-score{color:#5EEAD4}
.avg{text-align:center;font-weight:700;color:#F97316;font-size:.78rem;white-space:nowrap}

/* ── 編輯浮層 ── */
.rpop{position:fixed;z-index:9999;background:#1C1917;border:1px solid #57534E;
  border-radius:10px;padding:.9rem 1rem 1rem;width:290px;
  box-shadow:0 10px 40px rgba(0,0,0,.75)}
.rpop-t{font-size:.78rem;font-weight:700;color:#F97316;margin-bottom:.8rem}
.rpop label{display:flex;align-items:center;gap:.5rem;font-size:.73rem;
  color:#78716C;margin-bottom:.42rem}
.rpop input{flex:1;background:#292524;border:1px solid #44403C;border-radius:6px;
  padding:.28rem .55rem;color:#E7E5E4;font-size:.75rem;outline:none;min-width:0}
.rpop input:focus{border-color:#F97316}
.rpop-btns{display:flex;gap:.5rem;margin-top:.8rem;justify-content:flex-end}
.rpop-save,.rpop-cancel{border:none;border-radius:6px;padding:.3rem .85rem;
  font-size:.73rem;font-weight:600;cursor:pointer}
.rpop-save{background:#F97316;color:#fff}
.rpop-cancel{background:#292524;color:#78716C;border:1px solid #44403C}
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
    <button id="runBtn" class="btn" onclick="startFetch()">🔄 重新抓取</button>
    <a id="previewBtn" class="btn" href="/" target="_blank">📚 查看書單</a>
    <button id="publishBtn" class="btn" onclick="publishToGitHub()">📤 發佈到 GitHub</button>
    <a id="ghPagesBtn" class="btn" href="https://kobo99tw.github.io/kobo99-tracker/" target="_blank">🌐 GitHub Pages</a>
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
  <div style="overflow-x:auto" id="reviewTableWrap"></div>
</div>

<script src="/admin.js"></script>
</body>
</html>"""

ADMIN_JS = """
let polling  = null;
let offset   = 0;
let _books   = [];
let _editISBN = null, _editSrc = null;

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
  const url = document.getElementById('urlInput').value.trim();
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 抓取中…';
  document.getElementById('previewBtn').style.display = 'none';
  document.getElementById('publishBtn').style.display = 'none';
  document.getElementById('log').textContent = '⏳ 啟動中…';
  badge('running', '抓取中');

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
        const btn = document.getElementById('runBtn');
        btn.disabled = false;
        btn.textContent = '🔄 重新抓取';
        if (data.status === 'done') {
          document.getElementById('previewBtn').style.display = 'inline-block';
          const pub = document.getElementById('publishBtn');
          pub.style.display = 'inline-block';
          pub.disabled = false;
          pub.textContent = '📤 發佈到 GitHub';
          appendLog('\\n✅ 完成！可點「查看書單」預覽，或「發佈到 GitHub」上線。');
          badge('done', '完成 ✓');
          loadWeekInfo();
        } else {
          badge('error', '失敗 ✗');
        }
      }
    });
}

function clearLog() {
  document.getElementById('log').textContent = '（已清除）';
  offset = 0;
}

function publishToGitHub() {
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

function fmtRating(isbn, src, r) {
  r = r || {};
  const sc = r.score, cnt = r.count || 0, url = r.url || '';
  const miss = (sc == null);
  let inner = miss
    ? '<span class="rc-miss">?</span>'
    : '<span class="rc-score">\\u2605' + sc.toFixed(1) + '</span>'
      + '<span class="rc-cnt">(' + cnt + ')</span>';
  if (url) {
    inner = '<a class="rc-a" href="' + esc(url)
      + '" target="_blank" onclick="event.stopPropagation()">' + inner + '</a>';
  }
  return '<td class="rc' + (miss ? ' rc-empty' : '') + '"'
    + ' data-isbn="' + esc(isbn) + '"'
    + ' data-src="' + src + '"'
    + ' data-score="' + (sc != null ? sc : '') + '"'
    + ' data-count="' + cnt + '"'
    + ' data-url="' + esc(url) + '"'
    + ' onclick="openEditPop(this)" title="點擊編輯">' + inner + '</td>';
}

function renderReviewTable(books) {
  _books = books || [];
  const panel = document.getElementById('reviewPanel');
  if (!_books.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  const srcs = ['kobo','books_com','readmoo','goodreads','amazon_com'];
  let body = '';
  for (const b of _books) {
    const avg = b.avg_score;
    body += '<tr>';
    body += '<td class="dt">' + esc(b.date) + '</td>';
    body += '<td><span class="bt">' + esc(b.title) + '</span>'
          + '<span class="ba">' + esc(b.author) + '</span></td>';
    body += '<td class="mono">' + esc(b.isbn) + '</td>';
    body += '<td class="ot">' + esc(b.original_title || '\\u2014') + '</td>';
    for (const s of srcs) body += fmtRating(b.isbn, s, (b.ratings || {})[s]);
    body += '<td class="avg">' + (avg != null ? '\\u2605' + avg.toFixed(2) : '\\u2014') + '</td>';
    body += '</tr>';
  }
  document.getElementById('reviewTableWrap').innerHTML =
    '<table class="rt"><thead><tr>'
    + '<th>日期</th><th>書名 / 作者</th><th>ISBN</th><th>原文名</th>'
    + '<th>Kobo</th><th>博客來</th><th>讀墨</th><th>GR</th><th>AMZ</th>'
    + '<th>綜合</th></tr></thead><tbody>' + body + '</tbody></table>';
}

// ── 浮層編輯 ─────────────────────────────────────────────────

function openEditPop(cell) {
  closeEditPop();
  _editISBN = cell.dataset.isbn;
  _editSrc  = cell.dataset.src;
  const pop = document.createElement('div');
  pop.id = 'rPop';
  pop.className = 'rpop';
  pop.innerHTML =
    '<div class="rpop-t">\\u270f\\ufe0f 編輯 ' + esc(SRCLABELS[_editSrc] || _editSrc) + '</div>'
    + '<label>評分<input id="rpScore" type="number" step="0.1" min="0" max="5" value="'
    + esc(cell.dataset.score) + '" placeholder="（留空=無）"></label>'
    + '<label>筆數<input id="rpCount" type="number" min="0" value="'
    + esc(cell.dataset.count) + '"></label>'
    + '<label>連結<input id="rpUrl" type="text" value="'
    + esc(cell.dataset.url) + '"></label>'
    + '<div class="rpop-btns">'
    + '<button class="rpop-cancel" onclick="closeEditPop()">取消</button>'
    + '<button class="rpop-save" onclick="saveRating()">儲存</button>'
    + '</div>';

  const rect = cell.getBoundingClientRect();
  pop.style.top  = (rect.bottom + 6) + 'px';
  pop.style.left = Math.max(6, Math.min(rect.left, window.innerWidth - 306)) + 'px';
  document.body.appendChild(pop);
  pop.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); saveRating(); }
    if (e.key === 'Escape') closeEditPop();
  });
  document.getElementById('rpScore').focus();
}

function closeEditPop() {
  const p = document.getElementById('rPop');
  if (p) p.remove();
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
      score: scoreV === '' ? null : parseFloat(scoreV),
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
          b.ratings[src].score = scoreV === '' ? null : parseFloat(scoreV);
          b.ratings[src].count = countV;
          b.ratings[src].url   = urlV;
          b.avg_score = data.avg_score;
          break;
        }
      }
      renderReviewTable(_books);
      appendLog('\\u2705 已儲存 ' + (SRCLABELS[src] || src) + ' 評分');
    } else {
      appendLog('\\u274c 儲存失敗：' + JSON.stringify(data));
    }
  })
  .catch(e => appendLog('\\u274c 儲存錯誤：' + e));
}

document.addEventListener('click', e => {
  if (_editISBN && !e.target.closest('#rPop') && !e.target.closest('.rc')) closeEditPop();
});

// ── 書單資訊 + 渲染表格 ──────────────────────────────────────

function loadWeekInfo() {
  fetch('/api/info')
    .then(r => r.json())
    .then(d => {
      if (!d.week) return;
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
