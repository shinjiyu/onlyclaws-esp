#!/usr/bin/env python3
"""ESP32 Agent Platform control plane (remote invoke + edge scripts)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response as RawResponse,
)
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

import access
import accounts
import render as epd_render
import snake_ctrl
import tenancy
from capability_policy import tool_allowed_for_caps

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("EPD_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "epaper.db"
STATIC_DIR = BASE_DIR / "static"
ASSET_DIR = DATA_DIR / "assets"
BITMAP_DIR = DATA_DIR / "bitmaps"
VOICE_DIR = DATA_DIR / "voice"
BITMAP_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

SESSION_SECRET = os.environ.get("EPD_SESSION_SECRET", "")
SESSION_COOKIE = os.environ.get("EPD_SESSION_COOKIE", "epd_session")
SESSION_MAX_AGE = int(os.environ.get("EPD_SESSION_MAX_AGE", "604800"))
DEFAULT_DEVICE_ID = os.environ.get("EPD_DEFAULT_DEVICE_ID", "a4cb8fdf8440")
PUBLIC_BASE = os.environ.get("EPD_PUBLIC_BASE", "https://onlyclaws.world").rstrip("/")
COOKIE_PATH = urlparse(PUBLIC_BASE).path.rstrip("/") or "/"
CONSOLE_URL = f"{PUBLIC_BASE}/console/"

# device_id -> (width, height, display_name) — hints only; ownership is in DB
DEVICE_PANELS: dict[str, tuple[int, int, str]] = {
    "441bf6923320": (800, 480, "ESP32-S3 ePaper 3.97"),
    "a4cb8fdf8440": (400, 300, "ESP32-S3 RLCD 4.2"),
}


def panel_for(device_id: str) -> tuple[int, int, str]:
    if device_id in DEVICE_PANELS:
        return DEVICE_PANELS[device_id]
    return (400, 300, device_id)


if not SESSION_SECRET:
    raise RuntimeError("EPD_SESSION_SECRET is required")

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="epaper-ctrl")
password_links = accounts.LinkSigner(SESSION_SECRET)


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
    BITMAP_DIR.mkdir(parents=True, exist_ok=True)
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
        ensure_column(conn, "devices", "owner_email", "TEXT")
        ensure_column(conn, "devices", "token_hash", "TEXT")
        ensure_column(conn, "devices", "claimed_at", "TEXT")
        tenancy.ensure_agent_tokens_table(conn)
        access.ensure_table(conn)
        accounts.ensure_table(conn)
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
            CREATE TABLE IF NOT EXISTS bitmaps (
              id TEXT PRIMARY KEY,
              device_id TEXT NOT NULL,
              name TEXT NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              bytes INTEGER NOT NULL,
              path TEXT NOT NULL,
              created_at TEXT NOT NULL,
              created_by TEXT,
              UNIQUE(device_id, name)
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
        ensure_column(conn, "scripts", "owner_email", "TEXT")
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
        tenancy.migrate_device_tenancy(
            conn, {did: name for did, (_w, _h, name) in DEVICE_PANELS.items()}
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
app.include_router(snake_ctrl.router)


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


class BitmapIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    device_id: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    encoding: str = "gx"  # gx = raw MONO_HLSB, png = PNG bytes
    data_b64: str = Field(..., min_length=4, max_length=1_500_000)


class ScriptCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    source: Any  # Lua source string
    language: str = "lua"
    mode: str = "loop"  # once | loop
    every_ms: int = 1000
    device_id: Optional[str] = None


class ScriptDeployIn(BaseModel):
    device_id: Optional[str] = None
    mode: Optional[str] = None  # once | loop
    every_ms: Optional[int] = None


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


SCRIPT_SOURCE_MAX = 24000


def normalize_script_record(
    source: Any,
    *,
    language: str = "lua",
    mode: str = "loop",
    every_ms: int = 1000,
) -> dict[str, Any]:
    lang = (language or "lua").strip().lower()
    if lang != "lua":
        raise HTTPException(status_code=400, detail="only language=lua is supported")
    if not isinstance(source, str):
        raise HTTPException(status_code=400, detail="lua source must be a string")
    text = source.strip("\n")
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty script source")
    if len(text) > SCRIPT_SOURCE_MAX:
        raise HTTPException(status_code=400, detail="script too large")
    m = mode if mode in ("once", "loop") else "loop"
    ev = max(50, min(int(every_ms or 1000), 3_600_000))
    return {"language": "lua", "mode": m, "every_ms": ev, "source": text}


def script_record_from_row(raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        # Legacy: treat whole blob as lua
        return {"language": "lua", "mode": "loop", "every_ms": 1000, "source": raw or ""}
    if isinstance(obj, dict) and "source" in obj:
        if obj.get("language", "lua") != "lua" and isinstance(obj.get("source"), dict):
            raise HTTPException(status_code=400, detail="legacy JSON tools scripts are retired; use Lua")
        return {
            "language": "lua",
            "mode": obj.get("mode") if obj.get("mode") in ("once", "loop") else "loop",
            "every_ms": int(obj.get("every_ms") or 1000),
            "source": obj["source"] if isinstance(obj["source"], str) else str(obj["source"]),
        }
    if isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="invalid script record; expected Lua source string")
    return {"language": "lua", "mode": "loop", "every_ms": 1000, "source": str(obj)}


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
        path=COOKIE_PATH,
    )


def clear_session(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH)


def read_session(request: Request) -> Optional[dict[str, Any]]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    email = str(data.get("email", "")).lower()
    if not email:
        return None
    with db() as conn:
        if not tenancy.email_allowed(email, conn):
            return None
    return data


async def require_user(request: Request) -> dict[str, Any]:
    """Human session cookie OR Agent control token (oct_…). Never password for agents."""
    sess = read_session(request)
    if sess:
        return sess
    bearer = tenancy.extract_bearer(request)
    if bearer and tenancy.is_agent_control_token(bearer):
        with db() as conn:
            return tenancy.verify_agent_control_token(conn, bearer)
    raise HTTPException(
        status_code=401,
        detail="login required (session cookie) or Authorization: Bearer <oct_… agent token>",
    )


class AgentTokenCreateIn(BaseModel):
    name: str = Field(default="agent", max_length=80)


@app.post("/api/agent-tokens")
async def create_agent_token(
    body: AgentTokenCreateIn,
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Mint a control-plane token for Agents. Requires human session (or existing token)."""
    # Prefer minting only from browser session so a stolen agent token cannot mint more.
    if sess.get("auth") == "agent_token":
        raise HTTPException(
            status_code=403,
            detail="mint agent tokens from the web UI after password login, not with an agent token",
        )
    email = tenancy.session_email(sess)
    with db() as conn:
        created = tenancy.create_agent_control_token(conn, email=email, name=body.name)
        conn.commit()
    return {"success": True, **created}


@app.get("/api/agent-tokens")
async def list_agent_tokens(
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    email = tenancy.session_email(sess)
    with db() as conn:
        tokens = tenancy.list_agent_control_tokens(conn, email)
    return {"success": True, "tokens": tokens}


@app.delete("/api/agent-tokens/{token_id}")
async def revoke_agent_token(
    token_id: str,
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if sess.get("auth") == "agent_token":
        raise HTTPException(
            status_code=403,
            detail="revoke agent tokens from the web UI after password login",
        )
    email = tenancy.session_email(sess)
    with db() as conn:
        tenancy.revoke_agent_control_token(conn, email=email, token_id=token_id)
        conn.commit()
    return {"success": True, "id": token_id, "revoked": True}


def user_owns_device(device_id: str, sess: dict[str, Any]) -> str:
    with db() as conn:
        tenancy.assert_user_owns_device(conn, device_id, tenancy.session_email(sess))
    return (device_id or "").strip().lower()


def resolve_user_device_id(
    device_id: Optional[str], sess: dict[str, Any]
) -> str:
    """Pick explicit device or the caller's first owned device."""
    email = tenancy.session_email(sess)
    did = (device_id or "").strip().lower()
    with db() as conn:
        if did:
            tenancy.assert_user_owns_device(conn, did, email)
            return did
        row = conn.execute(
            """
            SELECT id FROM devices
            WHERE lower(coalesce(owner_email,''))=?
            ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            (email, DEFAULT_DEVICE_ID),
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="no devices bound to your account; POST /api/devices/register first",
        )
    return str(row["id"])





def device_capabilities(device_id: str) -> Optional[list[str]]:
    """Last-seen capability list from device /status meta, or None if unknown."""
    with db() as conn:
        row = conn.execute(
            "SELECT meta FROM devices WHERE id=?", (device_id,)
        ).fetchone()
    if not row or not row["meta"]:
        return None
    try:
        meta = json.loads(row["meta"]) or {}
    except (TypeError, json.JSONDecodeError):
        return None
    caps = meta.get("capabilities")
    if not isinstance(caps, list):
        return None
    out = [str(c) for c in caps if c]
    return out or None


def require_device_token(device_id: str, request: Request) -> str:
    """Per-device bearer auth for device wire protocol."""
    token = tenancy.extract_bearer(request)
    with db() as conn:
        tenancy.verify_device_token(conn, device_id, token)
    return (device_id or "").strip().lower()


# FastAPI dependency: path {device_id} + bearer must match that device's token.
def require_known_device(device_id: str, request: Request) -> str:
    return require_device_token(device_id, request)


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
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "home.html")


@app.get("/console")
async def console_redirect() -> RedirectResponse:
    return RedirectResponse(url="console/", status_code=301)


@app.get("/console/")
async def console() -> FileResponse:
    return FileResponse(STATIC_DIR / "console.html")


@app.get("/apply")
async def apply_redirect() -> RedirectResponse:
    return RedirectResponse(url="apply/", status_code=301)


@app.get("/apply/")
async def apply_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "apply.html")


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


def password_link(conn: sqlite3.Connection, email: str) -> str:
    # Fragment, not query: the token never reaches CDN/nginx access logs.
    return f"{CONSOLE_URL}#setpw={password_links.make(conn, email)}"


def display_name(conn: sqlite3.Connection, email: str) -> Optional[str]:
    row = conn.execute(
        "SELECT name FROM access_applications WHERE email=?", (email,)
    ).fetchone()
    return row["name"] if row else None


def start_session(response: Response, conn: sqlite3.Connection, email: str) -> dict[str, Any]:
    user = {"email": email, "name": display_name(conn, email)}
    set_session(response, email, user)
    return {"success": True, "user": {**user, "is_admin": access.is_admin(email)}}


@app.post("/api/auth/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    email = body.email.strip().lower()
    ip = access.client_ip(request) or "unknown"
    if not accounts.login_ip_limiter.hit(ip) or not accounts.login_email_limiter.hit(email):
        raise HTTPException(status_code=429, detail="too_many_attempts")

    if not await accounts.upstream_login(email, body.password):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    with db() as conn:
        if not tenancy.email_allowed(email, conn):
            raise HTTPException(status_code=403, detail="access_not_granted")
        return start_session(response, conn, email)


class LinkRequestIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    lang: str = Field("zh", max_length=8)


class SetPasswordIn(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    password: str = Field(..., max_length=accounts.PASSWORD_MAX)


@app.post("/api/auth/password/request")
async def request_password_link(
    body: LinkRequestIn, request: Request, background: BackgroundTasks
) -> dict[str, Any]:
    email = body.email.strip().lower()
    ip = access.client_ip(request) or "unknown"
    if not accounts.link_ip_limiter.hit(ip):
        raise HTTPException(status_code=429, detail="too_many_attempts")
    # Same answer whether or not the email has access, so this can't enumerate accounts.
    if access.EMAIL_RE.match(email) and accounts.link_email_limiter.hit(email):
        with db() as conn:
            if tenancy.email_allowed(email, conn):
                lang = "en" if body.lang.lower().startswith("en") else "zh"
                subject, text = accounts.mail_password_link(email, lang, password_link(conn, email))
                background.add_task(access.send_mail, [email], subject, text)
    return {"success": True}


@app.get("/api/auth/password/link")
async def password_link_info(token: str) -> dict[str, Any]:
    with db() as conn:
        email = password_links.resolve(conn, token)
    return {"success": True, "email": email}


@app.post("/api/auth/password/set")
async def set_password(body: SetPasswordIn, response: Response) -> dict[str, Any]:
    accounts.check_password_policy(body.password)
    with db() as conn:
        email = password_links.resolve(conn, body.token)
        if not tenancy.email_allowed(email, conn):
            raise HTTPException(status_code=403, detail="access_not_granted")
    if await accounts.upstream_register(email, body.password) == "exists":
        if not await accounts.upstream_set_password(email, body.password):
            raise HTTPException(status_code=409, detail="account_exists")
    with db() as conn:
        accounts.mark_registered(conn, email)
        return start_session(response, conn, email)


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict[str, Any]:
    clear_session(response)
    return {"success": True}


@app.get("/api/auth/me")
async def me(sess: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    user = sess.get("user") or {}
    email = tenancy.session_email(sess)
    return {
        "success": True,
        "user": {
            "email": sess.get("email"),
            "name": user.get("name") or user.get("username"),
            "is_admin": sess.get("auth") != "agent_token" and access.is_admin(email),
        },
    }


# ---- access applications (public apply + admin review) ----


class ApplicationIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    name: str = Field(..., min_length=1, max_length=80)
    hardware: str = Field("other", max_length=32)
    use_case: str = Field(..., min_length=10, max_length=2000)
    links: str = Field("", max_length=500)
    lang: str = Field("zh", max_length=8)
    website: str = Field("", max_length=200)  # honeypot; humans leave it empty


class ReviewIn(BaseModel):
    note: str = Field("", max_length=500)


def application_status_url(app_id: str, key: str) -> str:
    return f"{PUBLIC_BASE}/apply/?id={quote(app_id)}&k={quote(key)}"


async def require_admin(sess: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if sess.get("auth") == "agent_token":
        raise HTTPException(status_code=403, detail="review requires human login")
    if not access.is_admin(tenancy.session_email(sess)):
        raise HTTPException(status_code=403, detail="admin only")
    return sess


@app.post("/api/applications")
async def submit_application(
    body: ApplicationIn, request: Request, background: BackgroundTasks
) -> dict[str, Any]:
    if body.website.strip():
        # Pretend success so bots learn nothing.
        return {"success": True, "application": {"status": "pending"}}
    ip = access.client_ip(request)
    if not access.apply_limiter.hit(ip or "unknown"):
        raise HTTPException(status_code=429, detail="too many applications; try again later")
    with db() as conn:
        view, key, is_new = access.submit(
            conn,
            email=body.email,
            name=body.name,
            hardware=body.hardware,
            use_case=body.use_case,
            links=body.links,
            lang=body.lang,
            ip=ip,
        )
    lang = "en" if body.lang.lower().startswith("en") else "zh"
    status_url = application_status_url(view["id"], key)
    if is_new:
        subject, text = access.mail_received(view, lang, status_url)
        background.add_task(access.send_mail, [view["email"]], subject, text)
        subject, text = access.mail_admin_new(
            view, body.hardware, body.use_case.strip(), body.links.strip(), f"{CONSOLE_URL}#review"
        )
        background.add_task(access.send_mail, access.notify_emails(), subject, text)
    return {
        "success": True,
        "application": view,
        "status_key": key,
        "status_url": status_url,
        "mail": access.mail_configured(),
    }


@app.get("/api/applications/status")
async def application_status(id: str, k: str, request: Request) -> dict[str, Any]:
    if not access.status_limiter.hit(access.client_ip(request) or "unknown"):
        raise HTTPException(status_code=429, detail="too many requests")
    with db() as conn:
        view = access.lookup(conn, id, k)
    out: dict[str, Any] = {"success": True, "application": view}
    if view["status"] == "approved":
        out["console_url"] = CONSOLE_URL
    return out


@app.get("/api/admin/applications")
async def admin_list_applications(
    status: Optional[str] = None,
    limit: int = 100,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    with db() as conn:
        items, counts = access.list_for_admin(conn, status, limit)
    return {
        "success": True,
        "applications": items,
        "counts": counts,
        "mail": access.mail_configured(),
    }


async def _review_application(
    app_id: str, status: str, body: ReviewIn, sess: dict[str, Any], background: BackgroundTasks
) -> dict[str, Any]:
    reviewer = tenancy.session_email(sess)
    with db() as conn:
        view = access.review(conn, app_id=app_id, status=status, note=body.note, reviewer=reviewer)
        key = access.rotate_status_key(conn, app_id)
        setup_link = password_link(conn, view["email"]) if status == "approved" else None
    subject, text = access.mail_decision(
        view, view["lang"], CONSOLE_URL, application_status_url(app_id, key), setup_link
    )
    background.add_task(access.send_mail, [view["email"]], subject, text)
    return {"success": True, "application": view, "mail": access.mail_configured()}


@app.post("/api/admin/applications/{app_id}/approve")
async def admin_approve_application(
    app_id: str,
    body: ReviewIn,
    background: BackgroundTasks,
    sess: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return await _review_application(app_id, "approved", body, sess, background)


@app.post("/api/admin/applications/{app_id}/reject")
async def admin_reject_application(
    app_id: str,
    body: ReviewIn,
    background: BackgroundTasks,
    sess: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return await _review_application(app_id, "rejected", body, sess, background)


@app.get("/api/devices")
async def list_devices(sess: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    email = tenancy.session_email(sess)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, last_seen, ip, rssi, fw, meta, owner_email, claimed_at
            FROM devices
            WHERE lower(coalesce(owner_email,''))=?
            ORDER BY id
            """,
            (email,),
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
                "owner_email": r["owner_email"],
                "claimed_at": r["claimed_at"],
                "width": panel_for(r["id"])[0],
                "height": panel_for(r["id"])[1],
            }
        )
    return {"success": True, "devices": devices}


class DeviceRegisterIn(BaseModel):
    device_id: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Device id / MAC suffix, e.g. a4cb8fdf8440",
    )
    name: str = ""


@app.post("/api/devices/register")
async def register_device(
    body: DeviceRegisterIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    """Claim a device id for the current user and issue a fresh per-device token."""
    email = tenancy.session_email(sess)
    device_id = body.device_id.strip().lower()
    if len(device_id) < 4:
        raise HTTPException(
            status_code=400,
            detail="请填写设备 ID（至少 4 位，例如 a4cb8fdf8440）",
        )
    if not device_id.isalnum():
        raise HTTPException(status_code=400, detail="device_id 只能是字母和数字")
    name = body.name.strip() or panel_for(device_id)[2]
    token = tenancy.new_device_token()
    th = tenancy.hash_token(token)
    now = utc_now()
    with db() as conn:
        row = tenancy.get_device(conn, device_id)
        if row:
            owner = (row["owner_email"] or "").strip().lower()
            if owner and owner != email:
                raise HTTPException(status_code=409, detail="device already claimed")
            conn.execute(
                """
                UPDATE devices
                SET name=?, owner_email=?, token_hash=?, claimed_at=?
                WHERE id=?
                """,
                (name, email, th, now, device_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO devices (id, name, meta, owner_email, token_hash, claimed_at)
                VALUES (?, ?, '{}', ?, ?, ?)
                """,
                (device_id, name, email, th, now),
            )
    return {
        "success": True,
        "device": {
            "id": device_id,
            "name": name,
            "owner_email": email,
            "claimed_at": now,
        },
        "device_token": token,
        "note": "Save device_token now; it is shown only once. Put it in device_secrets.h or NVS.",
    }


@app.post("/api/devices/{device_id}/rotate-token")
async def rotate_device_token(
    device_id: str, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    email = tenancy.session_email(sess)
    token = tenancy.new_device_token()
    th = tenancy.hash_token(token)
    with db() as conn:
        tenancy.assert_user_owns_device(conn, device_id, email)
        conn.execute(
            "UPDATE devices SET token_hash=?, claimed_at=? WHERE id=?",
            (th, utc_now(), device_id.strip().lower()),
        )
    return {
        "success": True,
        "device_id": device_id.strip().lower(),
        "device_token": token,
        "note": "Previous token is invalid. Update the device firmware/NVS.",
    }


@app.get("/api/messages")
async def list_messages(
    device_id: Optional[str] = None,
    limit: int = 30,
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    email = tenancy.session_email(sess)
    with db() as conn:
        if device_id:
            tenancy.assert_user_owns_device(conn, device_id, email)
            rows = conn.execute(
                """
                SELECT id, device_id, type, title, body, created_at, created_by,
                       delivered_at, acked_at, status, full_refresh, asset, actions
                FROM messages WHERE device_id=? ORDER BY created_at DESC LIMIT ?
                """,
                (device_id.strip().lower(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT m.id, m.device_id, m.type, m.title, m.body, m.created_at, m.created_by,
                       m.delivered_at, m.acked_at, m.status, m.full_refresh, m.asset, m.actions
                FROM messages m
                JOIN devices d ON d.id = m.device_id
                WHERE lower(coalesce(d.owner_email,''))=?
                ORDER BY m.created_at DESC LIMIT ?
                """,
                (email, limit),
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
    device_id = resolve_user_device_id(body.device_id, sess)
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
    device = resolve_user_device_id(device_id, sess)
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
    device_id = resolve_user_device_id(body.device_id, sess)
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


def _bitmap_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "name": row["name"],
        "width": row["width"],
        "height": row["height"],
        "bytes": row["bytes"],
        "encoding": "gx",
        "created_at": row["created_at"],
    }


@app.post("/api/bitmaps")
async def put_bitmap(
    body: BitmapIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    """Store a named 1bpp bitmap the device can draw with gfx.image(name)."""
    name = body.name.strip()
    if not BITMAP_NAME_RE.match(name):
        raise HTTPException(
            status_code=400, detail="name must match [A-Za-z0-9_-]{1,64}"
        )
    packed = "".join(body.data_b64.split())
    packed += "=" * ((-len(packed)) % 4)
    try:
        payload = base64.b64decode(packed, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="data_b64 is not valid base64") from exc
    try:
        raw, width, height = epd_render.decode_named_bitmap(
            payload,
            encoding=body.encoding,
            width=body.width,
            height=body.height,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    device_id = resolve_user_device_id(body.device_id, sess)
    if not re.fullmatch(r"[a-z0-9]{4,32}", device_id):
        raise HTTPException(status_code=400, detail="bad device id")
    dest_dir = BITMAP_DIR / device_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{name}.bin"
    path.write_bytes(raw)
    now = utc_now()
    email = tenancy.session_email(sess)
    bitmap_id = uuid.uuid4().hex
    with db() as conn:
        conn.execute(
            """
            INSERT INTO bitmaps
              (id, device_id, name, width, height, bytes, path, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, name) DO UPDATE SET
              width=excluded.width,
              height=excluded.height,
              bytes=excluded.bytes,
              path=excluded.path,
              created_at=excluded.created_at,
              created_by=excluded.created_by
            """,
            (bitmap_id, device_id, name, width, height, len(raw), str(path), now, email),
        )
        row = conn.execute(
            "SELECT * FROM bitmaps WHERE device_id=? AND name=?",
            (device_id, name),
        ).fetchone()
    return {"success": True, "bitmap": _bitmap_row(row)}


@app.get("/api/bitmaps")
async def list_bitmaps(
    device_id: Optional[str] = None, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    did = resolve_user_device_id(device_id, sess)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bitmaps WHERE device_id=?
            ORDER BY name
            """,
            (did,),
        ).fetchall()
    return {"success": True, "bitmaps": [_bitmap_row(r) for r in rows]}


@app.delete("/api/bitmaps/{name}")
async def delete_bitmap(
    name: str,
    device_id: Optional[str] = None,
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if not BITMAP_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="bad bitmap name")
    did = resolve_user_device_id(device_id, sess)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM bitmaps WHERE device_id=? AND name=?",
            (did, name),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="bitmap not found")
        conn.execute(
            "DELETE FROM bitmaps WHERE device_id=? AND name=?",
            (did, name),
        )
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"success": True, "name": name, "device_id": did}


@app.post("/api/scripts")
async def create_script(
    body: ScriptCreateIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    record = normalize_script_record(
        body.source, language=body.language, mode=body.mode, every_ms=body.every_ms
    )
    source = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    script_id = uuid.uuid4().hex
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO scripts (id, name, source, created_at, created_by, updated_at, owner_email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                body.name.strip(),
                source,
                now,
                str(sess.get("email") or ""),
                now,
                tenancy.session_email(sess),
            ),
        )
    out: dict[str, Any] = {
        "success": True,
        "script": {
            "id": script_id,
            "name": body.name.strip(),
            "language": "lua",
            "mode": record["mode"],
            "every_ms": record["every_ms"],
            "source": record["source"],
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
    limit: int = 30, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    email = tenancy.session_email(sess)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, source, created_at, created_by, updated_at
            FROM scripts
            WHERE lower(coalesce(owner_email, created_by, ''))=?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (email, limit),
        ).fetchall()
    scripts = []
    for r in rows:
        d = dict(r)
        try:
            rec = script_record_from_row(d["source"])
            d["language"] = rec["language"]
            d["mode"] = rec["mode"]
            d["every_ms"] = rec["every_ms"]
            d["source"] = rec["source"]
        except HTTPException:
            pass
        scripts.append(d)
    return {"success": True, "scripts": scripts}


@app.get("/api/scripts/{script_id}")
async def get_script(
    script_id: str, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, source, created_at, created_by, updated_at, owner_email FROM scripts WHERE id=?",
            (script_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="script not found")
    owner = (row["owner_email"] or row["created_by"] or "").lower()
    if owner != tenancy.session_email(sess):
        raise HTTPException(status_code=403, detail="script not owned by you")
    d = dict(row)
    rec = script_record_from_row(d["source"])
    d["language"] = rec["language"]
    d["mode"] = rec["mode"]
    d["every_ms"] = rec["every_ms"]
    d["source"] = rec["source"]
    return {"success": True, "script": d}


@app.post("/api/scripts/{script_id}/deploy")
async def deploy_script(
    script_id: str,
    body: ScriptDeployIn,
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, source, created_by, owner_email FROM scripts WHERE id=?",
            (script_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="script not found")
    owner = (row["owner_email"] or row["created_by"] or "").lower()
    if owner != tenancy.session_email(sess):
        raise HTTPException(status_code=403, detail="script not owned by you")
    record = script_record_from_row(row["source"])
    if body.mode in ("once", "loop"):
        record["mode"] = body.mode
    if body.every_ms is not None:
        record["every_ms"] = max(50, min(int(body.every_ms), 3_600_000))
    source = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if len(source) > SCRIPT_SOURCE_MAX + 512:
        raise HTTPException(status_code=400, detail="script too large after overrides")
    device_id = resolve_user_device_id(body.device_id, sess)
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
                record.get("mode") or "loop",
                now,
            ),
        )
    envelope = json.dumps(
        {
            "script_id": script_id,
            "language": "lua",
            "mode": record["mode"],
            "every_ms": record["every_ms"],
            "source": record["source"],
        },
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
        "language": "lua",
        "message": msg,
    }


@app.post("/api/script/stop")
async def stop_script(
    body: ScriptStopIn, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    device_id = resolve_user_device_id(body.device_id, sess)
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
    device_id: Optional[str] = None, sess: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    did = resolve_user_device_id(device_id, sess)
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
    device_id = resolve_user_device_id(body.device_id, sess)
    caps = device_capabilities(device_id)
    if caps is not None:
        bad = []
        for step in tools:
            if not isinstance(step, dict):
                continue
            name = str(step.get("tool") or "")
            if name and not tool_allowed_for_caps(name, caps):
                bad.append(name)
        if bad:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "tool not in device capabilities",
                    "rejected": bad,
                    "capabilities": caps,
                },
            )
    payload = json.dumps({"tools": tools}, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > SCRIPT_SOURCE_MAX:
        raise HTTPException(status_code=400, detail="invoke payload too large")
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
    sess: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    email = tenancy.session_email(sess)
    with db() as conn:
        if device_id:
            tenancy.assert_user_owns_device(conn, device_id, email)
            rows = conn.execute(
                """
                SELECT id, device_id, script_id, name, data, created_at
                FROM device_events WHERE device_id=?
                ORDER BY created_at DESC LIMIT ?
                """,
                (device_id.strip().lower(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.id, e.device_id, e.script_id, e.name, e.data, e.created_at
                FROM device_events e
                JOIN devices d ON d.id = e.device_id
                WHERE lower(coalesce(d.owner_email,''))=?
                ORDER BY e.created_at DESC LIMIT ?
                """,
                (email, limit),
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
    _: str = Depends(require_known_device),
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
    device_id: str, _: str = Depends(require_known_device)
) -> dict[str, Any]:
    msg = pending_message(device_id)
    if msg:
        mark_delivered(msg["id"])
        return {"success": True, "message": message_payload(msg)}
    return {"success": True, "message": None}


@app.get("/api/v1/device/{device_id}/bitmaps/{name}")
async def device_named_bitmap(
    device_id: str, name: str, _: str = Depends(require_known_device)
) -> RawResponse:
    if not BITMAP_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="bad bitmap name")
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM bitmaps WHERE device_id=? AND name=?",
            (device_id.strip().lower(), name),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="bitmap not found")
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="bitmap file missing")
    data = path.read_bytes()
    if len(data) != int(row["bytes"]):
        raise HTTPException(status_code=500, detail="corrupt bitmap")
    return RawResponse(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "no-store",
            "X-Width": str(row["width"]),
            "X-Height": str(row["height"]),
            "X-Format": "gx-mono-hlsb",
        },
    )


@app.get("/api/v1/device/{device_id}/asset/{asset_name}")
async def device_asset(
    device_id: str, asset_name: str, _: str = Depends(require_known_device)
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
    device_id: str, body: AckIn, _: str = Depends(require_known_device)
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
    device_id: str, body: StatusIn, _: str = Depends(require_known_device)
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
    device_id: str, body: DeviceEventIn, _: str = Depends(require_known_device)
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


@app.get("/api/agent/skill.md")
async def agent_skill_md() -> Response:
    """Public agent skill — drive ESP with a control token (never passwords)."""
    path = STATIC_DIR / "agent-skill.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="skill missing")
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/api/agent/docs")
async def agent_docs(_: dict[str, Any] = Depends(require_user)) -> Response:
    """Human-readable agent function-call guide (session or agent token)."""
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
            "preferred": "Agent control token (oct_…)",
            "agent_token_header": "Authorization: Bearer <oct_…>",
            "mint": "Human web login → POST /api/agent-tokens (session cookie only)",
            "list": "GET /api/agent-tokens",
            "revoke": "DELETE /api/agent-tokens/{id}",
            "human_session": "Cookie after POST /api/auth/login — humans only; Agents must NOT use passwords",
            "cookie": SESSION_COOKIE,
            "cookie_path": COOKIE_PATH,
            "skill": "GET /api/agent/skill.md (public)",
            "allowlist": "EPD_ALLOWLIST (* or empty = open) plus approved applications at /apply/",
            "device_token": "per-device bearer for ESP wire protocol only — not for Agents",
        },
        "devices": [
            {"id": did, "name": name, "width": w, "height": h}
            for did, (w, h, name) in DEVICE_PANELS.items()
        ],
        "tools": [
            {
                "name": "onlyclaws_list_devices",
                "method": "GET",
                "path": "/api/devices",
                "notes": "Only devices owned by the agent-token owner",
            },
            {
                "name": "onlyclaws_register_device",
                "method": "POST",
                "path": "/api/devices/register",
                "body": {"device_id": "string", "name": "string?"},
                "notes": "Returns device_token once (firmware; not for Agents)",
            },
            {
                "name": "onlyclaws_rotate_token",
                "method": "POST",
                "path": "/api/devices/{id}/rotate-token",
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
                    "language": "lua",
                    "source": "string (Lua source)",
                    "mode": "once|loop?",
                    "every_ms": "int?",
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
                },
            },
            {
                "name": "onlyclaws_put_bitmap",
                "method": "POST",
                "path": "/api/bitmaps",
                "body": {
                    "name": "string",
                    "device_id": "string?",
                    "width": "int? (required for encoding=gx)",
                    "height": "int?",
                    "encoding": "gx|png",
                    "data_b64": "base64",
                },
                "notes": "Named 1bpp asset for Lua gfx.image(name,x,y). Not inside the 24KB script cap. Gx MONO_HLSB: 1=white, 0=black, MSB left, width multiple of 8, max 800x480.",
            },
            {
                "name": "onlyclaws_list_bitmaps",
                "method": "GET",
                "path": "/api/bitmaps",
                "query": {"device_id": "string?"},
            },
            {
                "name": "onlyclaws_delete_bitmap",
                "method": "DELETE",
                "path": "/api/bitmaps/{name}",
                "query": {"device_id": "string?"},
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
                "notes": "One-shot whitelist; filtered by device capabilities[] (panel/audio/sensors/arm)",
            },
            {
                "name": "onlyclaws_list_events",
                "method": "GET",
                "path": "/api/events",
                "query": {"device_id": "string?", "limit": "int"},
            },
            {
                "name": "onlyclaws_agent_skill",
                "method": "GET",
                "path": "/api/agent/skill.md",
                "notes": "Public; no auth",
            },
            {
                "name": "onlyclaws_agent_docs",
                "method": "GET",
                "path": "/api/agent/docs.md",
            },
        ],
        "lua_api": {
            "sensors": "sensors()",
            "control": ["emit", "log", "sleep", "stop", "millis", "display"],
            "gfx": [
                "gfx.W",
                "gfx.H",
                "gfx.clear",
                "gfx.pixel",
                "gfx.line",
                "gfx.rect",
                "gfx.fill_rect",
                "gfx.circle",
                "gfx.fill_circle",
                "gfx.text",
                "gfx.blit",
                "gfx.image",
                "gfx.flush",
            ],
            "bitmap": "POST /api/bitmaps then gfx.image(name,x,y). gfx.blit(b64) is full frame and flushes; gfx.blit(x,y,w,h,b64) is a sprite <=16KB and does not flush. Lua source max 24000 bytes.",
            "audio": [
                "audio.beep",
                "audio.play_pcm",
                "audio.pa",
                "audio.ready",
                "audio.sample_rate",
            ],
            "arm": [
                "arm.feedback",
                "arm.stream",
                "arm.move",
                "arm.stop",
                "arm.name",
            ],
            "input": ["input.key", "input.boot"],
            "net": ["net.rssi", "net.ip", "net.ssid"],
            "display": "panel products: 400x300 or 800x480 1bpp; RoArm: headless (no gfx)",
            "pcm": "base64 int16 LE mono @ sample_rate(); ~2s max",
            "arm_pose": "radians: base, shoulder, elbow, hand/wrist; spd=0 uses firmware default",
        },
        "invoke_tools": [
            "sensors.read",
            "beep",
            "display",
            "emit",
            "gfx.clear",
            "gfx.flush",
            "play_pcm",
            "arm.feedback",
            "arm.stream",
            "arm.move",
            "arm.stop",
        ],
        "capability_tools": {
            "panel": ["display", "gfx.clear", "gfx.flush"],
            "audio": ["beep", "play_pcm"],
            "sensors": ["sensors.read", "sensors"],
            "arm": ["arm.feedback", "arm.stream", "arm.move", "arm.stop"],
            "core": ["emit"],
        },
        "products": {
            "rlcd-42": {"caps": ["core", "panel", "audio", "ble_pad", "sensors"]},
            "epaper-397": {"caps": ["core", "panel", "sensors"]},
            "roarm-m2": {"caps": ["core", "arm"], "env": "esp32-roarm-m2"},
        },
        "removed": [
            "POST /api/v1/device/{id}/voice",
            "GET /api/voice",
            "GET /api/voice/{id}/audio",
            "JSON tools DSL on device (use Lua)",
        ],
        "device_local": [
            "KEY short = beep (panel boards)",
            "KEY hold 1.5s = SoftAP Wi-Fi provision",
            "ES8311 beep + PCM playback (RLCD)",
            "ST7305 / ePaper framebuffer via Lua gfx.*",
            "RoArm-M2: Feetech STS bus; invoke/Lua arm.* only (no anonymous /js)",
            "edge Lua loop when deployed",
        ],
    }


@app.exception_handler(HTTPException)
async def http_exc_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
    )
