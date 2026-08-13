"""Multi-tenant helpers: each kuroneko user owns their ESP devices."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from typing import Any, Optional

from fastapi import HTTPException, Request


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
