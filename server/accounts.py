"""Console accounts, backed by an upstream auth service that users never see.

Passwords live only upstream. Locally we keep a per-email link version so emailed
"set your password" links work once.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from access import RateLimiter

# Upstream auth service: POST {base}/api/auth/login and /api/auth/register,
# both {email, password} -> {success, message, data}. Server-side only.
AUTH_UPSTREAM = os.environ.get("EPD_AUTH_UPSTREAM", "").strip().rstrip("/")
# Shared key for POST /api/auth/service/set-password (password reset). Empty = no resets.
AUTH_SERVICE_KEY = os.environ.get("EPD_AUTH_SERVICE_KEY", "").strip()

PASSWORD_MIN = 8
PASSWORD_MAX = 128
LINK_MAX_AGE = 7 * 24 * 3600

login_ip_limiter = RateLimiter(60, 3600)
login_email_limiter = RateLimiter(10, 900)
link_ip_limiter = RateLimiter(5, 3600)
link_email_limiter = RateLimiter(3, 3600)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_links (
          email TEXT PRIMARY KEY,
          ver INTEGER NOT NULL DEFAULT 0,
          registered_at TEXT,
          updated_at TEXT NOT NULL
        )
        """
    )


def link_version(conn: sqlite3.Connection, email: str) -> int:
    ensure_table(conn)
    row = conn.execute("SELECT ver FROM account_links WHERE email=?", (email,)).fetchone()
    return int(row["ver"]) if row else 0


def mark_registered(conn: sqlite3.Connection, email: str) -> None:
    """Record a completed setup; bumping ver kills every outstanding link."""
    ensure_table(conn)
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO account_links (email, ver, registered_at, updated_at) VALUES (?, 1, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
          ver=account_links.ver + 1, registered_at=excluded.registered_at,
          updated_at=excluded.updated_at
        """,
        (email, now, now),
    )


def check_password_policy(password: str) -> None:
    """Mirror the upstream rule so users get a precise message before the round trip."""
    if len(password) < PASSWORD_MIN:
        raise HTTPException(status_code=400, detail="password_too_short")
    if len(password) > PASSWORD_MAX:
        raise HTTPException(status_code=400, detail="password_too_long")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(status_code=400, detail="password_needs_letter_digit")


class LinkSigner:
    def __init__(self, secret: str) -> None:
        self._s = URLSafeTimedSerializer(secret, salt="onlyclaws-password-link")

    def make(self, conn: sqlite3.Connection, email: str) -> str:
        email = email.strip().lower()
        return self._s.dumps({"e": email, "v": link_version(conn, email)})

    def resolve(self, conn: sqlite3.Connection, token: str) -> str:
        try:
            data: dict[str, Any] = self._s.loads(token, max_age=LINK_MAX_AGE)
        except SignatureExpired:
            raise HTTPException(status_code=400, detail="link_expired") from None
        except BadSignature:
            raise HTTPException(status_code=400, detail="link_invalid") from None
        email = str(data.get("e") or "").lower()
        if not email or int(data.get("v", -1)) != link_version(conn, email):
            raise HTTPException(status_code=400, detail="link_used")
        return email


async def _upstream(
    path: str, email: str, password: str, headers: Optional[dict[str, str]] = None
) -> tuple[int, dict[str, Any]]:
    if not AUTH_UPSTREAM:
        raise HTTPException(status_code=503, detail="login_unavailable")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{AUTH_UPSTREAM}{path}",
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json", **(headers or {})},
            )
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[auth] upstream {path} failed for {email}: {exc}", flush=True)
        raise HTTPException(status_code=503, detail="login_unavailable") from exc
    if r.status_code >= 500:
        print(f"[auth] upstream {path} {r.status_code} for {email}", flush=True)
        raise HTTPException(status_code=503, detail="login_unavailable")
    return r.status_code, payload if isinstance(payload, dict) else {}


async def upstream_login(email: str, password: str) -> bool:
    status, payload = await _upstream("/api/auth/login", email, password)
    if status >= 400 or not payload.get("success"):
        return False
    user = (payload.get("data") or {}).get("user") or {}
    return str(user.get("email") or email).strip().lower() == email


async def upstream_register(email: str, password: str) -> str:
    """'ok' | 'exists'. Other upstream rejections surface as generic 400s."""
    status, payload = await _upstream("/api/auth/register", email, password)
    if status < 400 and payload.get("success"):
        return "ok"
    msg = str(payload.get("message") or "")
    if "已被注册" in msg or "already" in msg.lower() or status == 409:
        return "exists"
    if "密码" in msg or "password" in msg.lower():
        raise HTTPException(status_code=400, detail="password_rejected")
    print(f"[auth] upstream register rejected {email}: {status} {msg}", flush=True)
    raise HTTPException(status_code=400, detail="setup_failed")


async def upstream_set_password(email: str, password: str) -> bool:
    """Reset an existing upstream account's password. False = resets not enabled."""
    if not AUTH_SERVICE_KEY:
        return False
    status, payload = await _upstream(
        "/api/auth/service/set-password", email, password, {"X-Service-Key": AUTH_SERVICE_KEY}
    )
    if status < 400 and payload.get("success"):
        return True
    print(f"[auth] upstream set-password rejected {email}: {status} {payload.get('message')}", flush=True)
    if status == 400:
        raise HTTPException(status_code=400, detail="password_rejected")
    return False


def mail_password_link(email: str, lang: str, link: str) -> tuple[str, str]:
    days = LINK_MAX_AGE // 86400
    if lang == "en":
        return (
            "OnlyClaws: set your password",
            f"Set a password for {email} to sign in to the OnlyClaws console:\n\n{link}\n\n"
            f"The link works once and expires in {days} days.\n",
        )
    return (
        "OnlyClaws：设置登录密码",
        f"请为 {email} 设置 OnlyClaws 控制台的登录密码：\n\n{link}\n\n"
        f"链接只能用一次，{days} 天内有效。\n",
    )
