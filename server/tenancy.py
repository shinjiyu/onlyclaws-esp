"""Multi-tenant helpers: each kuroneko user owns their ESP devices."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_allowlist() -> Optional[set[str]]:
    """None = open (any kuroneko user). Non-empty set = closed allowlist."""
    raw = os.environ.get("EPD_ALLOWLIST", "").strip()
    if not raw or raw == "*":
        return None
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


BOOTSTRAP_OWNER = os.environ.get(
    "EPD_BOOTSTRAP_OWNER", "yzy.zhenyu@gmail.com"
).strip().lower()
# Legacy shared token — used only to migrate existing devices; optional.
LEGACY_DEVICE_TOKEN = os.environ.get("EPD_DEVICE_TOKEN", "").strip()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_device_token() -> str:
    return secrets.token_hex(16)


# Agent control-plane tokens (human mints after login; Agent holds token, never password).
AGENT_TOKEN_PREFIX = "oct_"


def new_agent_control_token() -> str:
    return AGENT_TOKEN_PREFIX + secrets.token_urlsafe(32)


def is_agent_control_token(token: str) -> bool:
    return bool(token) and token.startswith(AGENT_TOKEN_PREFIX)


def ensure_agent_tokens_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_control_tokens (
          id TEXT PRIMARY KEY,
          owner_email TEXT NOT NULL,
          name TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          token_prefix TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_used_at TEXT,
          revoked_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_tokens_owner "
        "ON agent_control_tokens(owner_email)"
    )


def create_agent_control_token(
    conn: sqlite3.Connection, *, email: str, name: str = "agent"
) -> dict[str, Any]:
    ensure_agent_tokens_table(conn)
    email = email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="missing owner email")
    token = new_agent_control_token()
    tid = secrets.token_hex(8)
    now = _utc_now()
    label = (name or "agent").strip()[:80] or "agent"
    conn.execute(
        """
        INSERT INTO agent_control_tokens
          (id, owner_email, name, token_hash, token_prefix, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tid, email, label, hash_token(token), token[:12], now),
    )
    return {
        "id": tid,
        "name": label,
        "token": token,
        "token_prefix": token[:12],
        "created_at": now,
        "note": "Save this token now; plaintext is shown only once. "
        "Give it to your Agent as Authorization: Bearer <token>. Do not share your password.",
    }


def list_agent_control_tokens(
    conn: sqlite3.Connection, email: str
) -> list[dict[str, Any]]:
    ensure_agent_tokens_table(conn)
    rows = conn.execute(
        """
        SELECT id, name, token_prefix, created_at, last_used_at, revoked_at
        FROM agent_control_tokens
        WHERE lower(owner_email)=?
        ORDER BY created_at DESC
        """,
        (email.strip().lower(),),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "token_prefix": r["token_prefix"],
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "revoked": bool(r["revoked_at"]),
                "revoked_at": r["revoked_at"],
            }
        )
    return out


def revoke_agent_control_token(
    conn: sqlite3.Connection, *, email: str, token_id: str
) -> None:
    ensure_agent_tokens_table(conn)
    now = _utc_now()
    cur = conn.execute(
        """
        UPDATE agent_control_tokens
        SET revoked_at=?
        WHERE id=? AND lower(owner_email)=? AND revoked_at IS NULL
        """,
        (now, token_id, email.strip().lower()),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="token not found")


def verify_agent_control_token(
    conn: sqlite3.Connection, token: str
) -> dict[str, Any]:
    """Return session-shaped principal {email, user, auth: agent_token}."""
    ensure_agent_tokens_table(conn)
    if not is_agent_control_token(token):
        raise HTTPException(status_code=401, detail="invalid agent token")
    th = hash_token(token)
    row = conn.execute(
        """
        SELECT id, owner_email, name, revoked_at
        FROM agent_control_tokens
        WHERE token_hash=?
        """,
        (th,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="invalid agent token")
    if row["revoked_at"]:
        raise HTTPException(status_code=401, detail="agent token revoked")
    email = str(row["owner_email"] or "").strip().lower()
    if not email_allowed(email):
        raise HTTPException(status_code=403, detail="not authorized for this instance")
    now = _utc_now()
    conn.execute(
        "UPDATE agent_control_tokens SET last_used_at=? WHERE id=?",
        (now, row["id"]),
    )
    return {
        "email": email,
        "user": {"email": email, "name": row["name"] or "agent"},
        "auth": "agent_token",
        "agent_token_id": row["id"],
    }


def email_allowed(email: str) -> bool:
    allow = env_allowlist()
    if allow is None:
        return True
    return email.strip().lower() in allow


def session_email(sess: dict[str, Any]) -> str:
    return str(sess.get("email") or "").strip().lower()


def extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Device-Token", "").strip()


def get_device(conn: sqlite3.Connection, device_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM devices WHERE id=?", (device_id,)
    ).fetchone()


def assert_user_owns_device(
    conn: sqlite3.Connection, device_id: str, email: str
) -> sqlite3.Row:
    device_id = (device_id or "").strip().lower()
    if not device_id or len(device_id) > 32:
        raise HTTPException(status_code=400, detail="bad device id")
    row = get_device(conn, device_id)
    if not row:
        raise HTTPException(status_code=404, detail="device not found")
    owner = (row["owner_email"] or "").strip().lower() if "owner_email" in row.keys() else ""
    if owner != email.strip().lower():
        raise HTTPException(status_code=403, detail="device not owned by you")
    return row


def verify_device_token(
    conn: sqlite3.Connection, device_id: str, token: str
) -> sqlite3.Row:
    device_id = (device_id or "").strip().lower()
    if not device_id or len(device_id) > 32:
        raise HTTPException(status_code=400, detail="bad device id")
    if not token:
        raise HTTPException(status_code=401, detail="invalid device token")
    row = get_device(conn, device_id)
    if not row:
        raise HTTPException(status_code=403, detail="unknown device")
    stored = ""
    if "token_hash" in row.keys() and row["token_hash"]:
        stored = str(row["token_hash"])
    if not stored:
        raise HTTPException(status_code=401, detail="device not provisioned")
    if not hmac.compare_digest(stored, hash_token(token)):
        raise HTTPException(status_code=401, detail="invalid device token")
    return row


def migrate_device_tenancy(conn: sqlite3.Connection, panel_names: dict[str, str]) -> None:
    """Assign orphan devices to bootstrap owner; seed token from legacy shared secret."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
    if "owner_email" not in cols or "token_hash" not in cols:
        return
    legacy_hash = hash_token(LEGACY_DEVICE_TOKEN) if LEGACY_DEVICE_TOKEN else ""
    rows = conn.execute("SELECT id, owner_email, token_hash FROM devices").fetchall()
    for r in rows:
        owner = (r["owner_email"] or "").strip()
        th = (r["token_hash"] or "").strip()
        updates: list[str] = []
        params: list[Any] = []
        if not owner and BOOTSTRAP_OWNER:
            updates.append("owner_email=?")
            params.append(BOOTSTRAP_OWNER)
        if not th and legacy_hash:
            updates.append("token_hash=?")
            params.append(legacy_hash)
        if updates:
            params.append(r["id"])
            conn.execute(
                f"UPDATE devices SET {', '.join(updates)} WHERE id=?",
                params,
            )
    # Ensure known panels exist and are owned (compat with old auto-insert).
    for did, name in panel_names.items():
        conn.execute(
            "INSERT OR IGNORE INTO devices (id, name, meta) VALUES (?, ?, '{}')",
            (did, name),
        )
        row = get_device(conn, did)
        if not row:
            continue
        owner = (row["owner_email"] or "").strip() if "owner_email" in row.keys() else ""
        th = (row["token_hash"] or "").strip() if "token_hash" in row.keys() else ""
        if not owner and BOOTSTRAP_OWNER:
            conn.execute(
                "UPDATE devices SET owner_email=? WHERE id=?",
                (BOOTSTRAP_OWNER, did),
            )
        if not th and legacy_hash:
            conn.execute(
                "UPDATE devices SET token_hash=? WHERE id=?",
                (legacy_hash, did),
            )
