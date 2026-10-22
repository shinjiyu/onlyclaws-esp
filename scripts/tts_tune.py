#!/usr/bin/env python3
"""Local page that sends a tuned `say` to the RLCD board."""

import json
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = Path(__file__).resolve().parent / "tts_tune" / "index.html"
TOKEN = (ROOT / ".local" / "oct_token").read_text(encoding="utf-8").strip()
DEVICE = "a4cb8fdf8440"
API = "https://onlyclaws.world"
HOST = "127.0.0.1"
PORT = 8771


def api(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def send_say(payload):
    text = str(payload.get("text") or "").strip()
    if not text:
        return 400, {"detail": "先写一句要说的话"}
    tool = {
        "tool": "say",
        "text": text,
        "voice": "girl",
        "speed": int(payload.get("speed", 4)),
        "pitch": float(payload.get("pitch", 1.22)),
        "stretch": int(payload.get("stretch", 2)),
        "volume": int(payload.get("volume", -12)),
    }
    queued = api("POST", "/api/invoke", {"device_id": DEVICE, "tools": [tool]})
    mid = queued["message"]["id"]
    status = queued["message"].get("status") or "pending"
    for _ in range(20):
        if status in ("acked", "failed"):
            break
        time.sleep(1)
        msgs = api("GET", f"/api/messages?device_id={DEVICE}&limit=5")
        for msg in msgs.get("messages") or []:
            if msg.get("id") == mid:
                status = msg.get("status") or status
                break
    return 200, {"id": mid, "status": status}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[tts-tune]", fmt % args)

    def _json(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?", 1)[0] not in ("/", "/index.html"):
            self.send_error(404)
            return
        raw = PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/say":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 8000:
            self._json(400, {"detail": "太长了"})
            return
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            code, body = send_say(payload)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            code, body = 502, {"detail": "服务器没接上", "error": str(exc)}
        self._json(code, body)


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"http://{HOST}:{PORT}/")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
