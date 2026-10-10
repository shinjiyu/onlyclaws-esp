"""Local web console for finite presence ops (no free-form goals).

  python -m jev_servo console [--host 127.0.0.1] [--http-port 8765]
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .loop import run_loop
from .ops import OPS, op_help, parse_op

_STATIC = Path(__file__).resolve().parent / "static"
_MAX_LOG = 400


class LoopController:
    """Single background run_loop; start/stop from the console."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._started_at: float | None = None
        self._tick_count = 0
        self._last_error: str | None = None
        self._config: dict[str, Any] = {}
        self._last_tick: dict[str, Any] | None = None
        self._scene: str | None = None
        self._log: deque[dict[str, Any]] = deque(maxlen=_MAX_LOG)
        self._log_seq = 0

    def _append_log(self, kind: str, line: str = "", **extra: Any) -> None:
        self._log_seq += 1
        entry = {
            "seq": self._log_seq,
            "t": time.time(),
            "kind": kind,
            "line": line,
            **extra,
        }
        with self._lock:
            self._log.append(entry)

    def status(self, *, after_seq: int = 0) -> dict[str, Any]:
        with self._lock:
            logs = [e for e in self._log if e["seq"] > after_seq]
            return {
                "running": self._running,
                "started_at": self._started_at,
                "tick_count": self._tick_count,
                "config": dict(self._config),
                "scene": self._scene,
                "last_tick": self._last_tick,
                "last_error": self._last_error,
                "log_seq": self._log_seq,
                "logs": logs,
                "ops": list(OPS),
                "op_help": op_help(),
            }

    def start(self, opts: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return {"ok": False, "error": "already running"}
            try:
                op_name = str(opts.get("op") or "find_any")
                face_id = opts.get("face_id")
                if face_id is not None and face_id != "":
                    face_id = int(face_id)
                else:
                    face_id = None
                parsed = parse_op(op_name, face_id)
            except (ValueError, TypeError) as exc:
                return {"ok": False, "error": str(exc)}

            cfg = {
                "op": parsed.name,
                "face_id": parsed.target_id,
                "op_label": parsed.label(),
                "mode": "presence",
                "transport": str(opts.get("transport") or "usb"),
                "port": opts.get("port") or None,
                "spd": int(opts.get("spd") or 200),
                "settle_s": float(opts["settle"]) if opts.get("settle") is not None else None,
                "t_dec": float(opts.get("t_dec") or 0.0),
                "dry_run": bool(opts.get("dry_run")),
                "no_arm": bool(opts.get("no_arm")),
                "log_dir": opts.get("log_dir")
                or str(Path(__file__).resolve().parent / "runs" / "console"),
            }
            self._config = cfg
            self._stop = threading.Event()
            self._running = True
            self._started_at = time.time()
            self._tick_count = 0
            self._last_error = None
            self._last_tick = None
            self._scene = None
            self._log.clear()
            self._log_seq = 0
            stop_ev = self._stop

        self._append_log(
            "info",
            f"start op={cfg['op_label']} transport={cfg['transport']}",
        )

        def worker() -> None:
            try:

                def on_event(kind: str, payload: dict[str, Any]) -> None:
                    line = str(payload.get("line") or "")
                    if kind == "scene":
                        with self._lock:
                            self._scene = payload.get("scene")
                    if kind == "tick_done":
                        with self._lock:
                            self._tick_count = int(payload.get("tick_index", 0)) + 1
                            self._last_tick = payload.get("tick")
                    slim = {
                        k: v
                        for k, v in payload.items()
                        if k not in ("tick", "line") and v is not None
                    }
                    self._append_log(kind, line, **slim)

                run_loop(
                    op=cfg["op"],
                    face_id=cfg["face_id"],
                    ticks=0,
                    t_dec=cfg["t_dec"],
                    spd=cfg["spd"],
                    settle_s=cfg["settle_s"],
                    dry_run=cfg["dry_run"],
                    no_arm=cfg["no_arm"],
                    log_dir=cfg["log_dir"],
                    transport=cfg["transport"],
                    port=cfg["port"],
                    stop_event=stop_ev,
                    on_event=on_event,
                    mode="presence",
                )
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._last_error = err
                self._append_log("error", err)
                self._append_log("error", traceback.format_exc()[-1500:])
            finally:
                with self._lock:
                    self._running = False
                self._append_log("info", "loop idle")

        th = threading.Thread(target=worker, name="jev-servo-loop", daemon=True)
        with self._lock:
            self._thread = th
        th.start()
        return {"ok": True, "running": True, "config": cfg}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return {"ok": True, "running": False, "note": "already idle"}
            self._stop.set()
        self._append_log("info", "stop signaled (finishes current tick)")
        return {"ok": True, "running": True, "note": "stopping"}


CONTROLLER = LoopController()


def _json(handler: BaseHTTPRequestHandler, code: int, obj: dict[str, Any]) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    n = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(n) if n else b""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def serve(*, host: str = "127.0.0.1", http_port: int = 8765) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[console] {self.address_string()} {fmt % args}", flush=True)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = (_STATIC / "console.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            if path == "/api/status":
                from urllib.parse import parse_qs

                qs = parse_qs(urlparse(self.path).query)
                after = int((qs.get("after") or ["0"])[0])
                _json(self, 200, CONTROLLER.status(after_seq=after))
                return
            if path == "/api/ops":
                _json(self, 200, {"ops": list(OPS), "help": op_help()})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            body = _read_json(self)
            if path == "/api/start":
                _json(self, 200, CONTROLLER.start(body))
                return
            if path == "/api/stop":
                _json(self, 200, CONTROLLER.stop())
                return
            self.send_error(404)

    httpd = ThreadingHTTPServer((host, http_port), Handler)
    print(f"Presence console http://{host}:{http_port}/", flush=True)
    httpd.serve_forever()
