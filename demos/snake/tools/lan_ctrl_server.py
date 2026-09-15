#!/usr/bin/env python3
"""LAN snake control plane: phone UI + ESP polls GET /dir."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 8788
STATIC = Path(__file__).resolve().parent / "static"

_lock = threading.Lock()
_state = {
    "dir": "R",
    "restart": False,
    "score": 0,
    "alive": True,
    "last_event": None,
}


def _json(handler: BaseHTTPRequestHandler, code: int, obj: dict) -> None:
    body = json.dumps(obj, separators=(",", ":")).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    n = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(n) if n else b""
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        # Keep /dir logs so we can see ESP polls (client IP).
        path = urlparse(self.path).path
        if path == "/health":
            return
        super().log_message(fmt, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
        if path == "/health":
            _json(self, 200, {"ok": True})
            return
        if path == "/dir":
            with _lock:
                out = {
                    "dir": _state["dir"],
                    "restart": bool(_state["restart"]),
                }
                _state["restart"] = False
            _json(self, 200, out)
            return
        if path == "/state":
            with _lock:
                _json(self, 200, dict(_state))
            return
        _json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        data = _read_json(self)
        if path == "/dir":
            d = str(data.get("dir") or "").upper()
            if d in ("U", "D", "L", "R"):
                with _lock:
                    _state["dir"] = d
                _json(self, 200, {"ok": True, "dir": d})
                return
            _json(self, 400, {"ok": False, "error": "dir must be U|D|L|R"})
            return
        if path == "/restart":
            with _lock:
                _state["restart"] = True
                _state["alive"] = True
                _state["score"] = 0
            _json(self, 200, {"ok": True, "restart": True})
            return
        if path == "/event":
            with _lock:
                _state["last_event"] = data
                if data.get("type") == "game_over":
                    _state["alive"] = False
                    try:
                        _state["score"] = int(data.get("score") or 0)
                    except (TypeError, ValueError):
                        pass
                elif data.get("type") == "score":
                    try:
                        _state["score"] = int(data.get("score") or 0)
                    except (TypeError, ValueError):
                        pass
                    _state["alive"] = True
            _json(self, 200, {"ok": True})
            return
        _json(self, 404, {"error": "not found"})


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"snake-ctrl http://0.0.0.0:{PORT}/  (phone: http://<lan-ip>:{PORT}/)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
