"""
Kobo99 本機預覽伺服器
執行：python scraper/preview.py
開啟：http://localhost:8099/admin
需要：pip install flask
"""
import sys, os, subprocess, webbrowser, threading, json as _json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, send_from_directory, jsonify, make_response

sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR  = Path(__file__).parent.parent / "docs"
SCRAPE_PY = Path(__file__).parent / "scrape.py"
ROOT_DIR  = Path(__file__).parent.parent
PORT      = 8188

app = Flask(__name__, static_folder=None)

# 背景執行狀態
_lock     = threading.Lock()
_running  = False
_log      = []        # 所有 log 行
_status   = "idle"   # idle / running / done / error


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


# ── Admin JS（外部檔案避免 inline script 被封鎖）──────────────
@app.route("/admin.js")
def admin_js():
    resp = make_response(ADMIN_JS)
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ── API：啟動爬蟲（GET，背景 thread）────────────────────────
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


# ── API：取 log（前端輪詢）──────────────────────────────────
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


# ── API：目前書單資訊 ─────────────────────────────────────────
@app.route("/api/info")
def api_info():
    lp = DOCS_DIR / "data" / "latest.json"
    if not lp.exists():
        return jsonify({})
    with open(lp, encoding="utf-8") as f:
        d = _json.load(f)
    books = d.get("books", [])
    return jsonify({
        "year":       d.get("year"),
        "week":       d.get("week"),
        "updated_at": (d.get("updated_at") or "")[:16],
        "sale_label": d.get("sale_label", ""),
        "books_count": len(books),
        "books": [
            {"title": b.get("title",""), "date": b.get("date",""),
             "avg_score": b.get("avg_score")}
            for b in books
        ],
    })


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
  line-height:1.65;min-height:220px;max-height:500px;overflow-y:auto;
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

<script src="/admin.js"></script>
</body>
</html>"""

ADMIN_JS = """
let polling = null;
let offset  = 0;

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
  const url  = document.getElementById('urlInput').value.trim();
  const btn  = document.getElementById('runBtn');
  const prev = document.getElementById('previewBtn');

  btn.disabled = true;
  btn.textContent = '⏳ 抓取中…';
  prev.style.display = 'none';
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
      btn.textContent = '▶ 開始抓取';
      badge('idle', '待機');
      return;
    }
    offset = 0;
    polling = setInterval(pollLog, 300);
  })
  .catch(err => {
    appendLog('❌ 連線失敗：' + err);
    btn.disabled = false;
    btn.textContent = '▶ 開始抓取';
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
      const btn  = document.getElementById('runBtn');
      const prev = document.getElementById('previewBtn');
      btn.disabled = false;
      btn.textContent = '🔄 重新抓取';
      if (data.status === 'done') {
        prev.style.display = 'inline-block';
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
    btn.disabled = false;
    btn.textContent = '📤 發佈到 GitHub';
    badge('error', '失敗');
  });
}

function loadWeekInfo() {
  fetch('/api/info')
  .then(r => r.json())
  .then(d => {
    if (!d.week) return;
    document.getElementById('weekInfo').textContent =
      `目前資料：第 ${d.week} 週｜${d.sale_label}｜${d.books_count} 本｜更新 ${d.updated_at}`;
    // 若 log 是初始佔位文字，用書目填充
    const log = document.getElementById('log');
    const placeholders = ['（尚未執行）', '（已清除）'];
    if (placeholders.includes(log.textContent)) {
      const lines = [`📚 第 ${d.week} 週書單（${d.updated_at} 更新）`, ''];
      for (const b of d.books) {
        const score = b.avg_score != null ? ` ★${b.avg_score.toFixed(2)}` : '';
        lines.push(`  ${b.date}  《${b.title}》${score}`);
      }
      lines.push('', '點「重新抓取」更新書單，或「發佈到 GitHub」上線。');
      log.textContent = lines.join('\\n');
    }
    // 顯示預覽和發佈按鈕
    document.getElementById('previewBtn').style.display = 'inline-block';
    const pub = document.getElementById('publishBtn');
    pub.style.display = 'inline-block';
    pub.disabled = false;
    pub.textContent = '📤 發佈到 GitHub';
    badge('done', '已就緒');
  });
}

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
.catch(err => { appendLog('⚠️ 無法連線：' + err); });

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
