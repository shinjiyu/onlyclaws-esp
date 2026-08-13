#!/usr/bin/env python3
"""Tiny local webpage showing PlatformIO dependency download progress."""

from __future__ import annotations

import json
import os
import subprocess
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path.home() / ".platformio" / ".cache" / "downloads"
SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "overnight_pio_deps.log"
READY_PATH = SCRIPT_DIR / "overnight_pio_deps.ready"
HOST = "127.0.0.1"
PORT = 8765

JOBS = [
    {
        "id": "framework",
        "name": "Arduino 框架",
        "file": "framework-arduinoespressif32-3.20017.0.tar.gz",
        "expected": 246353348,
        "package": "framework-arduinoespressif32",
    },
    {
        "id": "riscv",
        "name": "RISC-V 工具链",
        "file": "toolchain-riscv32-esp-darwin_arm64-12.2.0+20230208.tar.gz",
        "expected": 249455329,
        "package": "toolchain-riscv32-esp",
    },
]

# Keep recent size samples for speed estimate: id -> [(ts, size), ...]
_SAMPLES: dict[str, list[tuple[float, int]]] = {}


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _pkg_installed(name: str) -> bool:
    return (Path.home() / ".platformio" / "packages" / name).is_dir()


def _curl_running(filename: str) -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-lf", f"curl .*{filename}"], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def _overnight_running() -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-lf", "overnight_pio_deps.sh"], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def _speed_bps(job_id: str, size: int) -> float:
    now = time.time()
    samples = _SAMPLES.setdefault(job_id, [])
    samples.append((now, size))
    # keep ~60s
    _SAMPLES[job_id] = [(t, s) for t, s in samples if now - t <= 60]
    samples = _SAMPLES[job_id]
    if len(samples) < 2:
        return 0.0
    t0, s0 = samples[0]
    t1, s1 = samples[-1]
    dt = t1 - t0
    if dt <= 0:
        return 0.0
    return max((s1 - s0) / dt, 0.0)


def build_status() -> dict:
    jobs = []
    total_expected = 0
    total_have = 0
    for job in JOBS:
        path = ROOT / job["file"]
        size = _file_size(path)
        expected = job["expected"]
        total_expected += expected
        have = min(size, expected)
        total_have += have
        pct = (have / expected * 100.0) if expected else 0.0
        speed = _speed_bps(job["id"], size)
        remain = max(expected - have, 0)
        eta = (remain / speed) if speed > 500 else None
        done = size == expected or _pkg_installed(job["package"])
        jobs.append(
            {
                "id": job["id"],
                "name": job["name"],
                "file": job["file"],
                "bytes": size,
                "expected": expected,
                "mb": round(size / 1024 / 1024, 2),
                "expected_mb": round(expected / 1024 / 1024, 2),
                "percent": round(pct, 1),
                "speed_kbps": round(speed / 1024, 1),
                "eta_sec": int(eta) if eta is not None else None,
                "downloading": _curl_running(job["file"]),
                "installed": _pkg_installed(job["package"]),
                "complete": done and size >= expected,
            }
        )

    log_tail = ""
    if LOG_PATH.exists():
        try:
            log_tail = LOG_PATH.read_text(errors="ignore")[-2500:]
        except OSError:
            log_tail = ""

    return {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overnight_running": _overnight_running(),
        "ready": READY_PATH.exists(),
        "overall_percent": round(total_have / total_expected * 100.0, 1) if total_expected else 0.0,
        "jobs": jobs,
        "log_tail": log_tail,
    }


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ESP32 依赖下载进度</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a222c;
      --text: #e7ecf1;
      --muted: #93a1b0;
      --accent: #3dd6c6;
      --warn: #f0b429;
      --ok: #6dd58c;
      --track: #2b3642;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif;
      background:
        radial-gradient(1200px 600px at 10% -10%, #1d3a3a 0%, transparent 55%),
        radial-gradient(900px 500px at 100% 0%, #243048 0%, transparent 50%),
        var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 28px 18px 40px;
    }
    .wrap { max-width: 820px; margin: 0 auto; }
    h1 { margin: 0 0 6px; font-size: 1.6rem; letter-spacing: 0.02em; }
    .sub { color: var(--muted); margin-bottom: 22px; font-size: 0.95rem; }
    .card {
      background: color-mix(in srgb, var(--panel) 92%, black);
      border: 1px solid #2e3a48;
      border-radius: 16px;
      padding: 18px 18px 16px;
      margin-bottom: 14px;
      box-shadow: 0 10px 30px rgba(0,0,0,.25);
    }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
    .name { font-weight: 650; font-size: 1.05rem; }
    .meta { color: var(--muted); font-size: 0.88rem; margin-top: 6px; }
    .bar {
      margin-top: 12px;
      height: 12px;
      background: var(--track);
      border-radius: 999px;
      overflow: hidden;
    }
    .fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #2bbbad, var(--accent));
      transition: width .6s ease;
    }
    .fill.done { background: linear-gradient(90deg, #3faf67, var(--ok)); }
    .pill {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      border: 1px solid #3a4858;
      color: var(--muted);
    }
    .pill.run { color: var(--warn); border-color: #7a5d1d; }
    .pill.ok { color: var(--ok); border-color: #2f6b45; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #c5d0db;
      font-size: 0.78rem;
      line-height: 1.45;
      max-height: 240px;
      overflow: auto;
    }
    .overall { font-size: 2rem; font-weight: 700; color: var(--accent); }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>ESP32 依赖下载进度</h1>
    <div class="sub">本地实时监控 · 每 2 秒刷新 · <span id="updated">-</span></div>

    <div class="card">
      <div class="row">
        <div>
          <div class="name">总进度</div>
          <div class="meta" id="statusLine">-</div>
        </div>
        <div class="overall" id="overall">0%</div>
      </div>
      <div class="bar"><div class="fill" id="overallFill"></div></div>
    </div>

    <div id="jobs"></div>

    <div class="card">
      <div class="name" style="margin-bottom:10px">通宵脚本日志（尾部）</div>
      <pre id="log">加载中…</pre>
    </div>
  </div>

  <script>
    function fmtEta(sec) {
      if (sec == null) return "估算中";
      if (sec < 60) return sec + "s";
      const m = Math.round(sec / 60);
      if (m < 60) return m + " 分钟";
      const h = (m / 60).toFixed(1);
      return h + " 小时";
    }

    function pill(job) {
      if (job.installed && job.complete) return '<span class="pill ok">已安装</span>';
      if (job.complete) return '<span class="pill ok">已下完</span>';
      if (job.downloading) return '<span class="pill run">下载中</span>';
      return '<span class="pill">等待中</span>';
    }

    async function refresh() {
      try {
        const res = await fetch("/api/status?_=" + Date.now());
        const data = await res.json();
        document.getElementById("updated").textContent = data.updated_at;
        document.getElementById("overall").textContent = data.overall_percent.toFixed(1) + "%";
        const fill = document.getElementById("overallFill");
        fill.style.width = data.overall_percent + "%";
        if (data.ready) fill.classList.add("done");

        const flags = [];
        flags.push(data.overnight_running ? "通宵脚本运行中" : "通宵脚本未运行");
        flags.push(data.ready ? "全部完成" : "尚未全部完成");
        document.getElementById("statusLine").textContent = flags.join(" · ");

        const root = document.getElementById("jobs");
        root.innerHTML = data.jobs.map(job => `
          <div class="card">
            <div class="row">
              <div class="name">${job.name} ${pill(job)}</div>
              <div>${job.percent.toFixed(1)}%</div>
            </div>
            <div class="meta">
              ${job.mb} / ${job.expected_mb} MB
              · ${job.speed_kbps} KB/s
              · ETA ${fmtEta(job.eta_sec)}
            </div>
            <div class="bar"><div class="fill ${job.complete ? "done" : ""}" style="width:${job.percent}%"></div></div>
          </div>
        `).join("");

        document.getElementById("log").textContent = data.log_tail || "(暂无日志)";
      } catch (e) {
        document.getElementById("statusLine").textContent = "无法读取状态：服务是否还在运行？";
      }
    }

    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        # quieter console
        pass

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/status":
            body = json.dumps(build_status()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404, "Not Found")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Progress page: http://{HOST}:{PORT}")
    print("API:           http://{HOST}:{PORT}/api/status")
    server.serve_forever()


if __name__ == "__main__":
    main()
