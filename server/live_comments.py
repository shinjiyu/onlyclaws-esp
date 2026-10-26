"""Public name-and-text inbox for the claw livestream.

Viewers post here. The Mac live stage polls ``GET /live/comments`` and
injects new rows into the broadcast. This router does not speak, move an
arm, or open a camera.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

STATIC_DIR = Path(__file__).resolve().parent / "static"
PAGE = STATIC_DIR / "live-input.html"
NAME_MAX = 16
TEXT_MAX = 120
KEEP = 200

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import FileResponse, JSONResponse
except ImportError:  # unit tests on a machine without the server deps
    APIRouter = None  # type: ignore[misc, assignment]
    Request = object  # type: ignore[misc, assignment]
    FileResponse = None  # type: ignore[misc, assignment]
    JSONResponse = None  # type: ignore[misc, assignment]


def board_path() -> Path:
    base = Path(os.environ.get("EPD_DATA_DIR", Path(__file__).resolve().parent / "data"))
    return base / "live-comments.json"


def clean_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("请填写名字")
    name = " ".join(value.split())
    if not name:
        raise ValueError("请填写名字")
    if len(name) > NAME_MAX:
        raise ValueError("名字太长了")
    return name


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("写一句再发")
    text = " ".join(value.split())
    if not text:
        raise ValueError("写一句再发")
    if len(text) > TEXT_MAX:
        raise ValueError("这句话太长了")
    return text


class CommentBoard:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.seq = 0
        self.items: list[dict[str, Any]] = []
        self._hits: list[tuple[float, str]] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        try:
            self.seq = int(raw.get("seq") or 0)
        except (TypeError, ValueError):
            self.seq = 0
        items = raw.get("items") if isinstance(raw.get("items"), list) else []
        kept: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                seq = int(item.get("seq") or 0)
            except (TypeError, ValueError):
                continue
            name = item.get("name")
            text = item.get("text")
            if not isinstance(name, str) or not isinstance(text, str) or not name or not text:
                continue
            kept.append({"seq": seq, "name": name[:NAME_MAX], "text": text[:TEXT_MAX], "ts": int(item.get("ts") or 0)})
        self.items = kept[-KEEP:]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"seq": self.seq, "items": self.items}, ensure_ascii=False)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    def post(self, name: Any, text: Any, ip: str, now: Optional[float] = None) -> dict[str, Any]:
        try:
            clean = clean_name(name)
            line = clean_text(text)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        moment = time.time() if now is None else now
        with self._lock:
            self._hits = [(at, who) for at, who in self._hits if moment - at < 30]
            if any(moment - at < 5 and who == ip for at, who in self._hits):
                return {"ok": False, "error": "稍等几秒再发"}
            if sum(1 for at, _who in self._hits if moment - at < 30) >= 30:
                return {"ok": False, "error": "现在人太多了，过一会儿再发"}
            self.seq += 1
            item = {"seq": self.seq, "name": clean, "text": line, "ts": int(moment)}
            self.items.append(item)
            self.items = self.items[-KEEP:]
            self._hits.append((moment, ip or ""))
            self._save()
        return {"ok": True, "seq": item["seq"], "name": clean, "text": line}

    def since(self, after: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = [dict(item) for item in self.items if item["seq"] > after]
            return rows, self.seq


_board: Optional[CommentBoard] = None
_board_lock = threading.Lock()


def get_board() -> CommentBoard:
    global _board
    with _board_lock:
        if _board is None:
            _board = CommentBoard(board_path())
        return _board


def client_ip(request: Any) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    real = str(request.headers.get("x-real-ip") or "").strip()
    if real:
        return real[:64]
    client = getattr(request, "client", None)
    host = getattr(client, "host", "") if client is not None else ""
    return str(host or "")[:64]


def _public(resp: Any) -> Any:
    resp.headers["Cache-Control"] = "no-store"
    return resp


if APIRouter is not None:
    router = APIRouter(prefix="/live", tags=["live"])

    @router.get("", include_in_schema=False)
    @router.get("/", include_in_schema=False)
    async def live_input_page() -> Any:
        return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})

    @router.get("/comments")
    async def live_comments(after: int = 0) -> Any:
        rows, seq = get_board().since(after)
        return _public(JSONResponse({"ok": True, "seq": seq, "comments": rows}))

    @router.post("/comments")
    async def post_live_comment(request: Request) -> Any:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = get_board().post(body.get("name"), body.get("text"), client_ip(request))
        return _public(JSONResponse(result, status_code=200 if result.get("ok") else 400))
