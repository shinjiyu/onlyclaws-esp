"""Phone D-pad control plane for edge snake (mounted under /snake)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).resolve().parent / "static"

_lock = threading.Lock()
_state: dict[str, Any] = {
    "dir": "R",
    "restart": False,
    "score": 0,
    "alive": True,
    "last_event": None,
}

router = APIRouter(prefix="/snake", tags=["snake"])


class DirIn(BaseModel):
    dir: str = Field(..., min_length=1, max_length=1)


class EventIn(BaseModel):
    type: str = ""
    score: Optional[int] = None


def _cors(resp: JSONResponse) -> JSONResponse:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.options("/{full_path:path}")
async def snake_options(full_path: str) -> JSONResponse:  # noqa: ARG001
    resp = JSONResponse(content={})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.status_code = 204
    return resp


@router.get("/")
async def snake_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "snake.html")


@router.get("/ble")
@router.get("/ble/")
async def snake_ble_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "snake-ble.html")


@router.get("/health")
async def snake_health() -> JSONResponse:
    return _cors(JSONResponse({"ok": True}))


@router.get("/dir")
async def snake_get_dir() -> JSONResponse:
    with _lock:
        out = {"dir": _state["dir"], "restart": bool(_state["restart"])}
        _state["restart"] = False
    return _cors(JSONResponse(out))


@router.post("/dir")
async def snake_set_dir(body: DirIn) -> JSONResponse:
    d = body.dir.upper()
    if d not in ("U", "D", "L", "R"):
        return _cors(JSONResponse({"ok": False, "error": "dir must be U|D|L|R"}, status_code=400))
    with _lock:
        _state["dir"] = d
    return _cors(JSONResponse({"ok": True, "dir": d}))


@router.post("/restart")
async def snake_restart() -> JSONResponse:
    with _lock:
        _state["restart"] = True
        _state["alive"] = True
        _state["score"] = 0
    return _cors(JSONResponse({"ok": True, "restart": True}))


@router.post("/event")
async def snake_event(body: EventIn) -> JSONResponse:
    with _lock:
        data = body.model_dump()
        _state["last_event"] = data
        if body.type == "game_over":
            _state["alive"] = False
            if body.score is not None:
                _state["score"] = int(body.score)
        elif body.type == "score" and body.score is not None:
            _state["score"] = int(body.score)
            _state["alive"] = True
    return _cors(JSONResponse({"ok": True}))


@router.get("/state")
async def snake_state() -> JSONResponse:
    with _lock:
        return _cors(JSONResponse(dict(_state)))


# Allow POST /dir with empty/query for very dumb clients
@router.post("/dir/")
async def snake_set_dir_slash(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    d = str((data or {}).get("dir") or "").upper()
    if d not in ("U", "D", "L", "R"):
        return _cors(JSONResponse({"ok": False, "error": "dir must be U|D|L|R"}, status_code=400))
    with _lock:
        _state["dir"] = d
    return _cors(JSONResponse({"ok": True, "dir": d}))
