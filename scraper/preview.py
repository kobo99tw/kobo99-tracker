"""
Kobo99 本機預覽伺服器
執行：python scraper/preview.py
開啟：http://localhost:8099/admin
需要：pip install flask
"""
import sys, os, re, subprocess, webbrowser
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from flask import Flask, Response, request, send_from_directory, stream_with_context

sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR  = Path(__file__).parent.parent / "docs"
SCRAPE_PY = Path(__file__).parent / "scrape.py"
ROOT_DIR  = Path(__file__).parent.parent
PORT      = 8099

app = Flask(__name__, static_folder=None)
_running = False


# ── 服務 docs/ 資料夾（書單預覽）────────────────────────────
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
    return ADMIN_HTML.replace("{{SUGGESTED_URL}}", suggested)


# ── SSE：執行爬蟲，串流 log ───────────────────────────────────
@app.route("/api/run")
def api_run():
    global _running
    url = request.args.get("url", "").strip()

    def generate():
        global _running
        if _running:
            yield "data: ⚠️ 已有抓取任務執行中，請等候完成\n\n"
            return
        _running = True
        # -u：強制 Python 不緩衝 stdout，才能逐行串流
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
            # readline() 逐行讀，不等 buffer 滿才輸出
            while True:
                line = proc.stdout.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                elif proc.poll() is not None:
                    break
            tag = "DONE" if proc.returncode == 0 else "ERROR"
            yield f"data: __{tag}__\n\n"
        except Exception as e:
            yield f"data: ❌ 錯誤：{e}\n\n"
            yield "data: __ERROR__\n\n"
        finally:
            _running = False

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 控制面板 HTML ─────────────────────────────────────────────
ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kobo99 本機預覽</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans TC',sans-serif;background:#1C1917;color:#E7E5E4;min-height:100vh;padding:1.5rem}
h1{font-size:1.2rem;font-weight:700;color:#F97316;margin-bottom:1.5rem;letter-spacing:.04em}
.panel{background:#292524;border-radius:12px;padding:1.25rem 1.5rem;margin-bottom:1.25rem}
.panel h2{font-size:.8rem;font-weight:600;color:#A8A29E;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.85rem}
.url-row{display:flex;gap:.6rem;flex-wrap:wrap}
#urlInput{flex:1;min-width:0;background:#1C1917;border:1px solid #44403C;border-radius:8px;
  padding:.55rem .85rem;color:#E7E5E4;font-size:.88rem;outline:none}
#urlInput:focus{border-color:#F97316}
#urlInput::placeholder{color:#57534E}
.btn{border:none;border-radius:8px;padding:.55rem 1.1rem;font-size:.85rem;font-weight:600;
  cursor:pointer;transition:opacity .15s;white-space:nowrap}
#runBtn{background:#F97316;color:#fff}
#runBtn:disabled{opacity:.45;cursor:not-allowed}
#previewBtn{background:#0D9488;color:#fff;text-decoration:none;display:none;
  align-items:center;padding:.55rem 1.1rem;border-radius:8px;font-size:.85rem;font-weight:600}
.hint{font-size:.75rem;color:#57534E;margin-top:.5rem}
.log-wrap{position:relative}
#log{background:#0C0A09;border-radius:8px;padding:1rem;font-family:'Courier New',monospace;
  font-size:.78rem;color:#D6D3D1;line-height:1.65;min-height:200px;max-height:480px;
  overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.log-actions{display:flex;justify-content:flex-end;margin-bottom:.4rem}
.btn-sm{background:#292524;border:1px solid #44403C;color:#A8A29E;border-radius:6px;
  padding:.25rem .7rem;font-size:.72rem;cursor:pointer}
.btn-sm:hover{border-color:#78716C}
.status{display:inline-block;font-size:.72rem;padding:.2rem .6rem;border-radius:20px;margin-left:.6rem}
.st-idle{background:#292524;color:#78716C}
.st-run{background:#431407;color:#FB923C}
.st-done{background:#042f2e;color:#2DD4BF}
.st-err{background:#450a0a;color:#F87171}
</style>
</head>
<body>
<h1>🔧 Kobo99 本機預覽</h1>

<div class="panel">
  <h2>書單網址 <span id="statusBadge" class="status st-idle">待機</span></h2>
  <div class="url-row">
    <input id="urlInput" type="text" value="{{SUGGESTED_URL}}"
      placeholder="留空 = 自動從部落格主頁偵測最新書單">
    <button id="runBtn" class="btn" onclick="startFetch()">▶ 開始抓取</button>
    <a id="previewBtn" class="btn" href="/" target="_blank">📚 查看書單</a>
  </div>
  <p class="hint">留空網址 → 自動偵測最新書單　｜　貼上指定網址 → 強制抓取該週</p>
</div>

<div class="panel">
  <div class="log-actions">
    <h2 style="flex:1">執行紀錄</h2>
    <button class="btn-sm" onclick="clearLog()">清除</button>
  </div>
  <div class="log-wrap">
    <pre id="log">（尚未執行）</pre>
  </div>
</div>

<script>
let es = null;

function setStatus(type, text) {
  const b = document.getElementById('statusBadge');
  b.className = 'status st-' + type;
  b.textContent = text;
}

function startFetch() {
  const url   = document.getElementById('urlInput').value.trim();
  const btn   = document.getElementById('runBtn');
  const log   = document.getElementById('log');
  const prev  = document.getElementById('previewBtn');

  if (es) { es.close(); es = null; }

  btn.disabled = true;
  btn.textContent = '⏳ 抓取中…';
  prev.style.display = 'none';
  log.textContent = '';
  setStatus('run', '抓取中');

  const qs = url ? '?url=' + encodeURIComponent(url) : '';
  es = new EventSource('/api/run' + qs);

  es.onmessage = (e) => {
    const d = e.data;
    if (d === '__DONE__') {
      es.close(); es = null;
      btn.disabled = false;
      btn.textContent = '▶ 開始抓取';
      prev.style.display = 'inline-flex';
      setStatus('done', '完成 ✓');
      log.textContent += '\n✅ 抓取完成！可點「查看書單」預覽結果。';
    } else if (d === '__ERROR__') {
      es.close(); es = null;
      btn.disabled = false;
      btn.textContent = '▶ 開始抓取';
      setStatus('err', '失敗 ✗');
    } else {
      const placeholder = log.textContent === '（尚未執行）' || log.textContent === '（已清除）';
      log.textContent = placeholder ? d : log.textContent + '\n' + d;
      log.scrollTop = log.scrollHeight;
    }
  };

  es.onerror = () => {
    if (es) { es.close(); es = null; }
    btn.disabled = false;
    btn.textContent = '▶ 開始抓取';
    setStatus('err', '連線中斷');
  };
}

function clearLog() {
  document.getElementById('log').textContent = '（已清除）';
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("=" * 50)
    print("  Kobo99 本機預覽伺服器")
    print(f"  控制面板：http://localhost:{PORT}/admin")
    print(f"  書單預覽：http://localhost:{PORT}/")
    print("  Ctrl+C 停止")
    print("=" * 50)
    webbrowser.open(f"http://localhost:{PORT}/admin")
    app.run(port=PORT, debug=False, threaded=True)
