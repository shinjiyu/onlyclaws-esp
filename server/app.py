#!/usr/bin/env python3
"""ESP32 Agent Platform control plane (remote invoke + edge scripts)."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response as RawResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

import render as epd_render

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("EPD_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "epaper.db"
STATIC_DIR = BASE_DIR / "static"
ASSET_DIR = DATA_DIR / "assets"
VOICE_DIR = DATA_DIR / "voice"

KURONEKO_BASE = os.environ.get("KURONEKO_BASE", "https://kuroneko.chat").rstrip("/")
SESSION_SECRET = os.environ.get("EPD_SESSION_SECRET", "")
SESSION_COOKIE = os.environ.get("EPD_SESSION_COOKIE", "epd_session")
SESSION_MAX_AGE = int(os.environ.get("EPD_SESSION_MAX_AGE", "604800"))
ALLOWLIST = {
    e.strip().lower()
    for e in os.environ.get("EPD_ALLOWLIST", "yzy.zhenyu@gmail.com").split(",")
    if e.strip()
}
DEVICE_TOKEN = os.environ.get("EPD_DEVICE_TOKEN", "")
DEFAULT_DEVICE_ID = os.environ.get("EPD_DEFAULT_DEVICE_ID", "441bf6923320")
PUBLIC_BASE = os.environ.get("EPD_PUBLIC_BASE", "https://onlyclaws.world/epaper")

# device_id -> (width, height, display_name)
DEVICE_PANELS: dict[str, tuple[int, int, str]] = {
    "441bf6923320": (800, 480, "ESP32-S3 ePaper 3.97"),
    "a4cb8fdf8440": (400, 300, "ESP32-S3 RLCD 4.2"),
}


def panel_for(device_id: str) -> tuple[int, int, str]:
    if device_id in DEVICE_PANELS:
        return DEVICE_PANELS[device_id]
    return (800, 480, device_id)

if not SESSION_SECRET:
    raise RuntimeError("EPD_SESSION_SECRET is required")
if not DEVICE_TOKEN:
    raise RuntimeError("EPD_DEVICE_TOKEN is required")

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="epaper-ctrl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              last_seen TEXT,
              ip TEXT,
              rssi INTEGER,
              fw TEXT,
              meta TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              device_id TEXT NOT NULL,
              type TEXT NOT NULL,
              title TEXT,
              body TEXT NOT NULL,
              created_at TEXT NOT NULL,
              created_by TEXT,
              delivered_at TEXT,
              acked_at TEXT,
              status TEXT NOT NULL
            );
            """
        )
        ensure_column(conn, "messages", "full_refresh", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "messages", "asset", "TEXT")
        ensure_column(conn, "messages", "actions", "TEXT")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scripts (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              source TEXT NOT NULL,
              created_at TEXT NOT NULL,
              created_by TEXT,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS device_scripts (
              device_id TEXT PRIMARY KEY,
              script_id TEXT,
              source TEXT,
              mode TEXT,
              status TEXT,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS device_events (
              id TEXT PRIMARY KEY,
              device_id TEXT NOT NULL,
              script_id TEXT,
              name TEXT NOT NULL,
              data TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        # Legacy voice table kept for old rows; upload API removed.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_clips (
              id TEXT PRIMARY KEY,
              device_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              duration_ms INTEGER,
              sample_rate INTEGER,
              rms INTEGER,
              peak INTEGER,
              bytes INTEGER,
              path TEXT NOT NULL
            );
            """
        )
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        conn.execute(
            """
            INSERT OR IGNORE INTO devices (id, name, last_seen, ip, rssi, fw, meta)
            VALUES (?, ?, NULL, NULL, NULL, NULL, '{}')
            """,
            (DEFAULT_DEVICE_ID, panel_for(DEFAULT_DEVICE_ID)[2]),
        )
        for did, (_w, _h, name) in DEVICE_PANELS.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO devices (id, name, last_seen, ip, rssi, fw, meta)
                VALUES (?, ?, NULL, NULL, NULL, NULL, '{}')
                """,
                (did, name),
            )
            conn.execute(
                "UPDATE devices SET name=? WHERE id=? AND (name IS NULL OR name=? OR name=id)",
                (name, did, did),
            )


class Waiters:
    def __init__(self) -> None:
        self._events: dict[str, list[asyncio.Event]] = {}

    def notify(self, device_id: str) -> None:
        for ev in self._events.get(device_id, []):
            ev.set()

    async def wait(self, device_id: str, timeout: float) -> bool:
        ev = asyncio.Event()
        self._events.setdefault(device_id, []).append(ev)
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            lst = self._events.get(device_id, [])
            if ev in lst:
                lst.remove(ev)


waiters = Waiters()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="OnlyClaws ESP32 Agent Platform",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class LoginIn(BaseModel):
    email: str
    password: str


class PushIn(BaseModel):
    title: str = ""
    body: str = Field("", max_length=4000)
    device_id: Optional[str] = None
    full_refresh: bool = False
    beep: bool = True
    wave: bool = False
    react: bool = True


class ActionIn(BaseModel):
    device_id: Optional[str] = None
    title: str = ""
    beep: bool = False
    wave: bool = False
    react: bool = False
    full_refresh: bool = False


class AckIn(BaseModel):
    message_id: str
    ok: bool = True
    error: Optional[str] = None
    ms: Optional[int] = None


class StatusIn(BaseModel):
    ip: Optional[str] = None
    rssi: Optional[int] = None
    fw: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class ScriptCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    source: Any
    device_id: Optional[str] = None


class ScriptDeployIn(BaseModel):
    device_id: Optional[str] = None
    mode: Optional[str] = None  # once | loop
    every_ms: Optional[int] = None
    max_iters: Optional[int] = None


class ScriptStopIn(BaseModel):
    device_id: Optional[str] = None


class InvokeIn(BaseModel):
    device_id: Optional[str] = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool: Optional[dict[str, Any]] = None  # single-tool shorthand


class DeviceEventIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    data: Optional[Any] = None
    script_id: Optional[str] = None


SCRIPT_SOURCE_MAX = 12000


def normalize_script_source(source: Any) -> str:
    if isinstance(source, str):
        text = source.strip()
    else:
        text = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    if not text:
        raise HTTPException(status_code=400, detail="empty script source")
    if len(text) > SCRIPT_SOURCE_MAX:
        raise HTTPException(status_code=400, detail="script too large")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid script json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="script must be a JSON object")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def enqueue_control_message(
    *,
    device_id: str,
    msg_type: str,
    title: str,
    body: str,
    created_by: str,
) -> dict[str, Any]:
    msg_id = uuid.uuid4().hex
    created = utc_now()
    name = panel_for(device_id)[2]
    with db() as conn:
        exists = conn.execute(
            "SELECT id FROM devices WHERE id=?", (device_id,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO devices (id, name) VALUES (?, ?)",
                (device_id, name),
            )
        conn.execute(
            """
            INSERT INTO messages
              (id, device_id, type, title, body, created_at, created_by,
               delivered_at, acked_at, status, full_refresh, asset, actions)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'pending', 0, NULL, ?)
            """,
            (
                msg_id,
                device_id,
                msg_type,
                title,
                body,
                created,
                created_by,
                json.dumps(normalize_actions(beep=False, wave=False, react=False)),
            ),
        )
    waiters.notify(device_id)
    return {
        "id": msg_id,
        "device_id": device_id,
        "type": msg_type,
        "title": title,
        "body": body,
        "created_at": created,
        "status": "pending",
    }


def normalize_actions(
    *, beep: bool = True, wave: bool = False, react: bool = True
) -> dict[str, bool]:
    return {"beep": bool(beep), "wave": bool(wave), "react": bool(react)}


def set_session(resp: Response, email: str, user: dict[str, Any]) -> None:
    token = serializer.dumps({"email": email, "user": user})
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/epaper",
    )


def clear_session(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/epaper")


def read_session(request: Request) -> Optional[dict[str, Any]]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    email = str(data.get("email", "")).lower()
    if email not in ALLOWLIST:
        return None
    return data


async def require_user(request: Request) -> dict[str, Any]:
    sess = read_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="login required")
    return sess


def require_device(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.headers.get("X-Device-Token", "").strip()
    if not DEVICE_TOKEN or token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid device token")
    return token


def require_known_device(device_id: str, request: Request) -> str:
    """Device bearer auth + device_id must be a registered panel/device."""
    require_device(request)
    device_id = (device_id or "").strip().lower()
    if not device_id or len(device_id) > 32:
        raise HTTPException(status_code=400, detail="bad device id")
    if device_id in DEVICE_PANELS:
        return device_id
    with db() as conn:
        row = conn.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="unknown device")
    return device_id


async def kuroneko_login(email: str, password: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{KURONEKO_BASE}/api/auth/login",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
        )
    try:
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"kuroneko bad response: {exc}") from exc
    if r.status_code >= 400 or not payload.get("success"):
        raise HTTPException(
            status_code=401,
            detail=payload.get("message") or "kuroneko login failed",
        )
    return payload.get("data") or {}


async def kuroneko_verify(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{KURONEKO_BASE}/api/auth/verify",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    try:
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"kuroneko bad response: {exc}") from exc
    if r.status_code >= 400 or not payload.get("success"):
        raise HTTPException(
            status_code=401,
            detail=payload.get("message") or "token invalid",
        )
    return payload.get("data") or payload


def enqueue_bitmap(
    *,
    device_id: str,
    title: str,
    body: str,
    bitmap: Optional[bytes],
    created_by: str,
    full_refresh: bool,
    actions: Optional[dict[str, bool]] = None,
    msg_type: str = "bitmap",
) -> dict[str, Any]:
    msg_id = uuid.uuid4().hex
    created = utc_now()
    asset_name = None
    width, height = panel_for(device_id)[0], panel_for(device_id)[1]
    byte_len = 0
    if bitmap:
        asset_name = f"{msg_id}.bin"
        width, height = epd_render.save_bitmap(ASSET_DIR / asset_name, bitmap)
        byte_len = len(bitmap)
        msg_type = "bitmap"
    else:
        msg_type = msg_type if msg_type != "bitmap" else "action"
    acts = actions or normalize_actions()
    acts_json = json.dumps(acts, ensure_ascii=False)
    name = panel_for(device_id)[2]
    with db() as conn:
        exists = conn.execute(
            "SELECT id FROM devices WHERE id=?", (device_id,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO devices (id, name) VALUES (?, ?)",
                (device_id, name),
            )
        conn.execute(
            """
            INSERT INTO messages
              (id, device_id, type, title, body, created_at, created_by,
               delivered_at, acked_at, status, full_refresh, asset, actions)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'pending', ?, ?, ?)
            """,
            (
                msg_id,
                device_id,
                msg_type,
                title,
                body,
                created,
                created_by,
                1 if full_refresh else 0,
                asset_name,
                acts_json,
            ),
        )
    waiters.notify(device_id)
    return {
        "id": msg_id,
        "device_id": device_id,
        "type": msg_type,
        "title": title,
        "body": body,
        "created_at": created,
        "status": "pending",
        "full_refresh": full_refresh,
        "asset": asset_name,
        "actions": acts,
        "width": width,
        "height": height,
        "bytes": byte_len,
    }


def parse_actions(raw: Any) -> dict[str, bool]:
    defaults = normalize_actions()
    if not raw:
        return defaults
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return defaults
    if not isinstance(data, dict):
        return defaults
    return {
        "beep": bool(data["beep"]) if "beep" in data else defaults["beep"],
        "wave": bool(data["wave"]) if "wave" in data else defaults["wave"],
        "react": bool(data["react"]) if "react" in data else defaults["react"],
    }


def message_payload(msg: dict[str, Any]) -> dict[str, Any]:
    asset = msg.get("asset")
    width, height, _ = panel_for(msg["device_id"])
    if asset:
        path = ASSET_DIR / asset
        if path.exists():
            n = path.stat().st_size
            if n == 400 * 300 // 8:
                width, height = 400, 300
            elif n == 800 * 480 // 8:
                width, height = 800, 480
    return {
        "id": msg["id"],
        "device_id": msg["device_id"],
        "type": msg["type"],
        "title": msg.get("title") or "",
        "body": msg.get("body") or "",
        "created_at": msg.get("created_at"),
        "status": msg.get("status"),
        "full_refresh": bool(msg.get("full_refresh")),
        "width": width,
        "height": height,
        "bytes": width * height // 8 if asset else 0,
        "asset_path": f"/epaper/api/v1/device/{msg['device_id']}/asset/{asset}"
        if asset
        else None,
        "actions": parse_actions(msg.get("actions")),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    font_ok = True
    font_path = None
    try:
        font_path = str(epd_render.find_font())
    except FileNotFoundError:
        font_ok = False
    return {
        "ok": True,
        "ts": utc_now(),
        "public_base": PUBLIC_BASE,
        "font_ok": font_ok,
        "font": font_path,
    }


@app.post("/api/auth/login")
async def login(body: LoginIn, response: Response) -> dict[str, Any]:
    email = body.email.strip().lower()
    data = await kuroneko_login(email, body.password)
    user = data.get("user") or {}
    user_email = str(user.get("email") or email).strip().lower()
    if user_email not in ALLOWLIST:
        raise HTTPException(status_code=403, detail="not authorized for epaper control")

    access = data.get("access_token")
    if access:
        try:
            verified = await kuroneko_verify(access)
            vuser = verified.get("user") or verified
            if isinstance(vuser, dict) and vuser.get("email"):
                user = {**user, **vuser}
                user_email = str(user.get("email")).strip().lower()
        except HTTPException:
            pass

    if user_email not in ALLOWLIST:
        raise HTTPException(status_code=403, detail="not authorized for epaper control")

    set_session(response, user_email, user)
    return {
        "success": True,
        "user": {"email": user_email, "name": user.get("name") or user.get("username")},
    }


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict[str, Any]:
    clear_session(response)
    return {"success": True}


@app.get("/api/auth/me")
async def me(sess: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    user = sess.get("user") or {}
    return {
        "success": True,
        "user": {
            "email": sess.get("email"),
            "name": user.get("name") or user.get("username"),
        },
    }


@app.get("/api/devices")
async def list_devices(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, last_seen, ip, rssi, fw, meta FROM devices ORDER BY id"
        ).fetchall()
    now = time.time()
    devices = []
    for r in rows:
        online = False
        if r["last_seen"]:
            try:
                ts = datetime.fromisoformat(r["last_seen"]).timestamp()
                online = (now - ts) < 120
            except ValueError:
                online = False
        meta: dict[str, Any] = {}
        raw_meta = r["meta"]
        if raw_meta:
            try:
                parsed = json.loads(raw_meta)
                if isinstance(parsed, dict):
                    meta = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                meta = {}
        devices.append(
            {
                "id": r["id"],
                "name": r["name"],
                "last_seen": r["last_seen"],
                "ip": r["ip"],
                "rssi": r["rssi"],
                "fw": r["fw"],
                "meta": meta,
                "online": online,
                "width": panel_for(r["id"])[0],
                "height": panel_for(r["id"])[1],
            }
        )
    return {"success": True, "devices": devices}


@app.get("/api/messages")
async def list_messages(
    device_id: Optional[str] = None,
    limit: int = 30,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    with db() as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT id, device_id, type, title, body, created_at, created_by,
                       delivered_at, acked_at, status, full_refresh, asset, actions
                FROM messages WHERE device_id=? ORDER BY created_at DESC LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, device_id, type, title, body, created_at, created_by,
                       delivered_at, acked_at, status, full_refresh, asset, actions
                FROM messages ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["actions"] = parse_actions(d.get("actions"))
        out.append(d)
    return {"success": True, "messages": out}


@app.post("/api/push")
async def push(
    body: PushIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    if not body.body.strip() and not body.title.strip():
        raise HTTPException(status_code=400, detail="title/body required")
    device_id = (body.device_id or DEFAULT_DEVICE_ID).strip()
    width, height, _ = panel_for(device_id)
    try:
        bitmap = epd_render.render_text_card(
            body.title, body.body, width=width, height=height
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    msg = enqueue_bitmap(
        device_id=device_id,
        title=body.title,
        body=body.body,
        bitmap=bitmap,
        created_by=str(sess.get("email") or ""),
        full_refresh=body.full_refresh,
        actions=normalize_actions(beep=body.beep, wave=body.wave, react=body.react),
    )
    return {"success": True, "message": msg}


@app.post("/api/push/image")
async def push_image(
    file: UploadFile = File(...),
    title: str = Form(""),
    device_id: Optional[str] = Form(None),
    full_refresh: bool = Form(False),
    fit: str = Form("contain"),
    beep: bool = Form(True),
    wave: bool = Form(False),
    react: bool = Form(True),
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    raw = await file.read()
    print(
        f"[push/image] user={sess.get('email')} device={device_id} "
        f"name={file.filename!r} bytes={len(raw)} fit={fit}",
        flush=True,
    )
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large (max 8MB)")
    device = (device_id or DEFAULT_DEVICE_ID).strip()
    width, height, _ = panel_for(device)
    try:
        bitmap = epd_render.render_uploaded_image(
            raw, fit=fit, width=width, height=height
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"invalid image (请用 JPG/PNG，勿用 HEIC/实况图): {exc}",
        ) from exc

    label = title.strip() or (file.filename or "image")
    msg = enqueue_bitmap(
        device_id=device,
        title=label,
        body=f"[image] {file.filename or 'upload'}",
        bitmap=bitmap,
        created_by=str(sess.get("email") or ""),
        full_refresh=full_refresh,
        actions=normalize_actions(beep=beep, wave=wave, react=react),
    )
    return {"success": True, "message": msg}


@app.post("/api/action")
async def device_action(
    body: ActionIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    """Queue speaker/UI cues without a new rendered card."""
    if not (body.beep or body.wave or body.react or body.title.strip()):
        raise HTTPException(
            status_code=400, detail="need beep, wave, react, and/or title"
        )
    device_id = (body.device_id or DEFAULT_DEVICE_ID).strip()
    title = body.title.strip() or ("action" if not body.title else body.title)
    msg = enqueue_bitmap(
        device_id=device_id,
        title=title,
        body="",
        bitmap=None,
        created_by=str(sess.get("email") or ""),
        full_refresh=body.full_refresh,
        actions=normalize_actions(beep=body.beep, wave=body.wave, react=body.react),
        msg_type="action",
    )
    return {"success": True, "message": msg}


@app.post("/api/scripts")
async def create_script(
    body: ScriptCreateIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    source = normalize_script_source(body.source)
    script_id = uuid.uuid4().hex
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO scripts (id, name, source, created_at, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                body.name.strip(),
                source,
                now,
                str(sess.get("email") or ""),
                now,
            ),
        )
    out: dict[str, Any] = {
        "success": True,
        "script": {
            "id": script_id,
            "name": body.name.strip(),
            "source": json.loads(source),
            "created_at": now,
        },
    }
    if body.device_id:
        deploy = await deploy_script(
            script_id,
            ScriptDeployIn(device_id=body.device_id),
            sess,
        )
        out["deploy"] = deploy
    return out


@app.get("/api/scripts")
async def list_scripts(
    limit: int = 30, _: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, source, created_at, created_by, updated_at
            FROM scripts ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    scripts = []
    for r in rows:
        d = dict(r)
        try:
            d["source"] = json.loads(d["source"])
        except (TypeError, json.JSONDecodeError):
            pass
        scripts.append(d)
    return {"success": True, "scripts": scripts}


@app.get("/api/scripts/{script_id}")
async def get_script(
    script_id: str, _: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, source, created_at, created_by, updated_at FROM scripts WHERE id=?",
            (script_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="script not found")
    d = dict(row)
    d["source"] = json.loads(d["source"])
    return {"success": True, "script": d}


@app.post("/api/scripts/{script_id}/deploy")
async def deploy_script(
    script_id: str,
    body: ScriptDeployIn,
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, source FROM scripts WHERE id=?", (script_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="script not found")
    source_obj = json.loads(row["source"])
    if body.mode in ("once", "loop"):
        source_obj["mode"] = body.mode
    if body.every_ms is not None:
        source_obj["every_ms"] = max(200, min(int(body.every_ms), 3_600_000))
    if body.max_iters is not None:
        source_obj["max_iters"] = max(0, int(body.max_iters))
    source = json.dumps(source_obj, ensure_ascii=False, separators=(",", ":"))
    if len(source) > SCRIPT_SOURCE_MAX:
        raise HTTPException(status_code=400, detail="script too large after overrides")
    device_id = (body.device_id or DEFAULT_DEVICE_ID).strip()
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO device_scripts (device_id, script_id, source, mode, status, updated_at)
            VALUES (?, ?, ?, ?, 'deployed', ?)
            ON CONFLICT(device_id) DO UPDATE SET
              script_id=excluded.script_id,
              source=excluded.source,
              mode=excluded.mode,
              status='deployed',
              updated_at=excluded.updated_at
            """,
            (
                device_id,
                script_id,
                source,
                source_obj.get("mode") or "once",
                now,
            ),
        )
    envelope = json.dumps(
        {"script_id": script_id, "source": source_obj},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    msg = enqueue_control_message(
        device_id=device_id,
        msg_type="script",
        title=script_id,
        body=envelope,
        created_by=str(sess.get("email") or ""),
    )
    return {
        "success": True,
        "device_id": device_id,
        "script_id": script_id,
        "message": msg,
    }


@app.post("/api/script/stop")
async def stop_script(
    body: ScriptStopIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    device_id = (body.device_id or DEFAULT_DEVICE_ID).strip()
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            UPDATE device_scripts SET status='stopped', updated_at=?
            WHERE device_id=?
            """,
            (now, device_id),
        )
    msg = enqueue_control_message(
        device_id=device_id,
        msg_type="script_stop",
        title="stop",
        body="{}",
        created_by=str(sess.get("email") or ""),
    )
    return {"success": True, "device_id": device_id, "message": msg}


@app.get("/api/script/status")
async def script_status(
    device_id: Optional[str] = None, _: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    did = (device_id or DEFAULT_DEVICE_ID).strip()
    with db() as conn:
        runtime = conn.execute(
            "SELECT * FROM device_scripts WHERE device_id=?", (did,)
        ).fetchone()
        device = conn.execute(
            "SELECT id, last_seen, fw, meta FROM devices WHERE id=?", (did,)
        ).fetchone()
    meta: dict[str, Any] = {}
    if device and device["meta"]:
        try:
            meta = json.loads(device["meta"]) or {}
        except json.JSONDecodeError:
            meta = {}
    return {
        "success": True,
        "device_id": did,
        "runtime": dict(runtime) if runtime else None,
        "device_meta": meta,
        "script_id": meta.get("script_id"),
        "script_state": meta.get("script_state"),
        "script_error": meta.get("script_error"),
        "fw": device["fw"] if device else None,
        "last_seen": device["last_seen"] if device else None,
    }


@app.post("/api/invoke")
async def invoke_tools(
    body: InvokeIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    tools = list(body.tools or [])
    if body.tool:
        tools.append(body.tool)
    if not tools:
        raise HTTPException(status_code=400, detail="need tools or tool")
    if len(tools) > 32:
        raise HTTPException(status_code=400, detail="too many tools")
    payload = json.dumps({"tools": tools}, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > SCRIPT_SOURCE_MAX:
        raise HTTPException(status_code=400, detail="invoke payload too large")
    device_id = (body.device_id or DEFAULT_DEVICE_ID).strip()
    msg = enqueue_control_message(
        device_id=device_id,
        msg_type="invoke",
        title="invoke",
        body=payload,
        created_by=str(sess.get("email") or ""),
    )
    return {"success": True, "device_id": device_id, "message": msg}


@app.get("/api/events")
async def list_events(
    device_id: Optional[str] = None,
    limit: int = 50,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    with db() as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT id, device_id, script_id, name, data, created_at
                FROM device_events WHERE device_id=?
                ORDER BY created_at DESC LIMIT ?
                """,
                (device_id.strip(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, device_id, script_id, name, data, created_at
                FROM device_events
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    events = []
    for r in rows:
        d = dict(r)
        if d.get("data"):
            try:
                d["data"] = json.loads(d["data"])
            except (TypeError, json.JSONDecodeError):
                pass
        events.append(d)
    return {"success": True, "events": events}


def pending_message(device_id: str) -> Optional[dict[str, Any]]:
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, device_id, type, title, body, created_at, status,
                   full_refresh, asset, actions
            FROM messages
            WHERE device_id=? AND status='pending'
            ORDER BY created_at ASC LIMIT 1
            """,
            (device_id,),
        ).fetchone()
    return dict(row) if row else None


def mark_delivered(msg_id: str) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE messages
            SET status='delivered', delivered_at=?
            WHERE id=? AND status='pending'
            """,
            (utc_now(), msg_id),
        )


@app.get("/api/v1/device/{device_id}/poll")
async def device_poll(
    device_id: str,
    timeout: int = 25,
    _: str = Depends(require_device),
) -> JSONResponse:
    timeout = max(1, min(timeout, 28))
    with db() as conn:
        conn.execute(
            "UPDATE devices SET last_seen=? WHERE id=?",
            (utc_now(), device_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO devices (id, name) VALUES (?, ?)",
            (device_id, device_id),
        )

    msg = pending_message(device_id)
    if not msg:
        await waiters.wait(device_id, float(timeout))
        msg = pending_message(device_id)

    if not msg:
        return JSONResponse({"success": True, "message": None})

    mark_delivered(msg["id"])
    return JSONResponse({"success": True, "message": message_payload(msg)})


@app.get("/api/v1/device/{device_id}/pending")
async def device_pending(
    device_id: str, _: str = Depends(require_device)
) -> dict[str, Any]:
    msg = pending_message(device_id)
    if msg:
        mark_delivered(msg["id"])
        return {"success": True, "message": message_payload(msg)}
    return {"success": True, "message": None}


@app.get("/api/v1/device/{device_id}/asset/{asset_name}")
async def device_asset(
    device_id: str, asset_name: str, _: str = Depends(require_device)
) -> RawResponse:
    if "/" in asset_name or "\\" in asset_name or not asset_name.endswith(".bin"):
        raise HTTPException(status_code=400, detail="bad asset name")
    path = ASSET_DIR / asset_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="asset not found")
    data = path.read_bytes()
    if len(data) not in (800 * 480 // 8, 400 * 300 // 8):
        raise HTTPException(status_code=500, detail="corrupt asset")
    return RawResponse(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Length": str(len(data)), "Cache-Control": "no-store"},
    )


@app.post("/api/v1/device/{device_id}/ack")
async def device_ack(
    device_id: str, body: AckIn, _: str = Depends(require_device)
) -> dict[str, Any]:
    status = "acked" if body.ok else "failed"
    with db() as conn:
        conn.execute(
            """
            UPDATE messages
            SET status=?, acked_at=?
            WHERE id=? AND device_id=?
            """,
            (status, utc_now(), body.message_id, device_id),
        )
    return {"success": True}


@app.post("/api/v1/device/{device_id}/status")
async def device_status(
    device_id: str, body: StatusIn, _: str = Depends(require_device)
) -> dict[str, Any]:
    meta = json.dumps(body.meta or {})
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO devices (id, name) VALUES (?, ?)",
            (device_id, device_id),
        )
        conn.execute(
            """
            UPDATE devices
            SET last_seen=?, ip=COALESCE(?, ip), rssi=COALESCE(?, rssi),
                fw=COALESCE(?, fw), meta=?
            WHERE id=?
            """,
            (utc_now(), body.ip, body.rssi, body.fw, meta, device_id),
        )
        # Mirror script state into device_scripts when device reports it.
        script_state = (body.meta or {}).get("script_state")
        script_id = (body.meta or {}).get("script_id")
        if script_state:
            conn.execute(
                """
                UPDATE device_scripts
                SET status=?, script_id=COALESCE(?, script_id), updated_at=?
                WHERE device_id=?
                """,
                (str(script_state), str(script_id) if script_id else None, utc_now(), device_id),
            )
    return {"success": True}


@app.post("/api/v1/device/{device_id}/events")
async def device_post_event(
    device_id: str, body: DeviceEventIn, _: str = Depends(require_device)
) -> dict[str, Any]:
    event_id = uuid.uuid4().hex
    created = utc_now()
    data = body.data
    if data is not None and not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO device_events (id, device_id, script_id, name, data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                device_id,
                body.script_id,
                body.name.strip(),
                data,
                created,
            ),
        )
    return {"success": True, "id": event_id}


@app.post("/api/v1/device/{device_id}/voice")
async def device_voice_upload_gone(device_id: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="voice upload removed; use speaker playback via /api/push or /api/action",
    )


@app.get("/api/voice")
async def list_voice_gone() -> dict[str, Any]:
    raise HTTPException(status_code=410, detail="voice list removed")


@app.get("/api/voice/{clip_id}/audio")
async def get_voice_audio_gone(clip_id: str) -> dict[str, Any]:
    raise HTTPException(status_code=410, detail="voice playback-from-upload removed")


@app.get("/api/agent/docs")
async def agent_docs(_: dict[str, Any] = Depends(require_user)) -> Response:
    """Human-readable agent function-call guide (kuroneko session required)."""
    path = STATIC_DIR / "agent-api.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="docs missing")
    body = path.read_text(encoding="utf-8")
    # Minimal HTML shell; agents may also fetch as text/markdown via Accept.
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>OnlyClaws Agent API</title>"
        "<style>body{font-family:ui-monospace,Menlo,Consolas,monospace;"
        "max-width:920px;margin:24px auto;padding:0 16px;line-height:1.45;"
        "white-space:pre-wrap}</style></head><body>"
        + body.replace("&", "&amp;").replace("<", "&lt;")
        + "</body></html>"
    )
    return Response(content=html, media_type="text/html; charset=utf-8")


@app.get("/api/agent/docs.md")
async def agent_docs_md(_: dict[str, Any] = Depends(require_user)) -> Response:
    path = STATIC_DIR / "agent-api.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="docs missing")
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/api/agent/capabilities")
async def agent_capabilities(
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Machine-readable catalog for tool/function calling."""
    return {
        "success": True,
        "public_base": PUBLIC_BASE,
        "auth": {
            "type": "kuroneko.chat + allowlist session cookie",
            "login": "POST /api/auth/login",
            "me": "GET /api/auth/me",
            "logout": "POST /api/auth/logout",
            "cookie": SESSION_COOKIE,
            "cookie_path": "/epaper",
        },
        "devices": [
            {"id": did, "name": name, "width": w, "height": h}
            for did, (w, h, name) in DEVICE_PANELS.items()
        ],
        "tools": [
            {
                "name": "onlyclaws_login",
                "method": "POST",
                "path": "/api/auth/login",
                "body": {"email": "string", "password": "string"},
            },
            {
                "name": "onlyclaws_list_devices",
                "method": "GET",
                "path": "/api/devices",
            },
            {
                "name": "onlyclaws_push_text",
                "method": "POST",
                "path": "/api/push",
                "body": {
                    "device_id": "string?",
                    "title": "string",
                    "body": "string",
                    "full_refresh": "bool=false",
                    "beep": "bool=true",
                    "wave": "bool=false",
                    "react": "bool=true",
                },
            },
            {
                "name": "onlyclaws_push_image",
                "method": "POST",
                "path": "/api/push/image",
                "content_type": "multipart/form-data",
                "fields": [
                    "file",
                    "title",
                    "device_id",
                    "full_refresh",
                    "fit",
                    "beep",
                    "wave",
                    "react",
                ],
            },
            {
                "name": "onlyclaws_action",
                "method": "POST",
                "path": "/api/action",
                "body": {
                    "device_id": "string?",
                    "title": "string?",
                    "beep": "bool",
                    "wave": "bool",
                    "react": "bool",
                },
                "notes": "Speaker/UI cues without new bitmap card",
            },
            {
                "name": "onlyclaws_list_messages",
                "method": "GET",
                "path": "/api/messages",
                "query": {"device_id": "string?", "limit": "int<=100"},
            },
            {
                "name": "onlyclaws_create_script",
                "method": "POST",
                "path": "/api/scripts",
                "body": {
                    "name": "string",
                    "source": "object (JSON tools script)",
                    "device_id": "string? (auto-deploy if set)",
                },
            },
            {
                "name": "onlyclaws_deploy_script",
                "method": "POST",
                "path": "/api/scripts/{id}/deploy",
                "body": {
                    "device_id": "string?",
                    "mode": "once|loop?",
                    "every_ms": "int?",
                    "max_iters": "int?",
                },
            },
            {
                "name": "onlyclaws_stop_script",
                "method": "POST",
                "path": "/api/script/stop",
                "body": {"device_id": "string?"},
            },
            {
                "name": "onlyclaws_script_status",
                "method": "GET",
                "path": "/api/script/status",
                "query": {"device_id": "string?"},
            },
            {
                "name": "onlyclaws_invoke",
                "method": "POST",
                "path": "/api/invoke",
                "body": {
                    "device_id": "string?",
                    "tools": "[{tool, ...}]",
                    "tool": "object?",
                },
                "notes": "Remote one-shot whitelist tools on device",
            },
            {
                "name": "onlyclaws_list_events",
                "method": "GET",
                "path": "/api/events",
                "query": {"device_id": "string?", "limit": "int"},
            },
            {
                "name": "onlyclaws_agent_docs",
                "method": "GET",
                "path": "/api/agent/docs.md",
            },
        ],
        "script_tools": [
            "sensors.read",
            "beep",
            "wave",
            "react",
            "dialog",
            "sleep",
            "emit",
            "stop",
            "if",
        ],
        "removed": [
            "POST /api/v1/device/{id}/voice",
            "GET /api/voice",
            "GET /api/voice/{id}/audio",
        ],
        "device_local": [
            "KEY short = wave+beep",
            "KEY hold 1.5s = SoftAP Wi-Fi provision",
            "speaker playback of cues (no mic upload)",
            "edge JSON tools script loop when deployed",
        ],
    }


@app.exception_handler(HTTPException)
async def http_exc_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
    )
