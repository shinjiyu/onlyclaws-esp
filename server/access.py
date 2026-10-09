"""Invite-only access: public applications, admin review, email notices."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Optional

from fastapi import HTTPException, Request

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
HARDWARE_CHOICES = ("rlcd-42", "epaper-397", "bare-s3", "other")
STATUSES = ("pending", "approved", "rejected")

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465") or "465")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "OnlyClaws").strip()
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "").strip().lower() in ("1", "true", "yes")

# MAIL_BACKEND=agently sends through QQ Mail Agently (agently-cli, OAuth token on this host).
MAIL_BACKEND = os.environ.get("MAIL_BACKEND", "").strip().lower() or ("smtp" if SMTP_HOST else "")
AGENTLY_CLI = os.environ.get("AGENTLY_CLI", "agently-cli").strip()
AGENTLY_HOME = os.environ.get("AGENTLY_HOME", "").strip() or os.environ.get("HOME", "/root")

APPLY_PER_IP_PER_HOUR = int(os.environ.get("EPD_APPLY_PER_IP_PER_HOUR", "5") or "5")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def admin_emails() -> set[str]:
    raw = os.environ.get("EPD_ADMINS", "").strip()
    if not raw:
        raw = os.environ.get("EPD_BOOTSTRAP_OWNER", "yzy.zhenyu@gmail.com")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin(email: str) -> bool:
    return bool(email) and email.strip().lower() in admin_emails()


def notify_emails() -> list[str]:
    raw = os.environ.get("EPD_ADMIN_NOTIFY", "").strip()
    if raw:
        return [e.strip() for e in raw.split(",") if e.strip()]
    return sorted(admin_emails())


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS access_applications (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          hardware TEXT NOT NULL,
          use_case TEXT NOT NULL,
          links TEXT,
          lang TEXT NOT NULL DEFAULT 'zh',
          status TEXT NOT NULL,
          status_key_hash TEXT NOT NULL,
          note TEXT,
          ip TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          reviewed_at TEXT,
          reviewed_by TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_status ON access_applications(status, created_at)"
    )


def is_approved(conn: sqlite3.Connection, email: str) -> bool:
    ensure_table(conn)
    row = conn.execute(
        "SELECT 1 FROM access_applications WHERE email=? AND status='approved'",
        (email.strip().lower(),),
    ).fetchone()
    return row is not None


def client_ip(request: Request) -> str:
    # Only nginx-set X-Real-IP is trusted; nginx overwrites any client-supplied value.
    v = request.headers.get("X-Real-IP", "").strip()
    if v:
        return v[:64]
    return (request.client.host if request.client else "")[:64]


class RateLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 5000:
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True


apply_limiter = RateLimiter(APPLY_PER_IP_PER_HOUR, 3600)
status_limiter = RateLimiter(120, 3600)


def _clean(value: Optional[str], limit: int) -> str:
    return (value or "").strip()[:limit]


def public_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "email": row["email"],
        "name": row["name"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
        "note": row["note"] if row["status"] == "rejected" else None,
    }


def admin_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "hardware": row["hardware"],
        "use_case": row["use_case"],
        "links": row["links"] or "",
        "lang": row["lang"],
        "status": row["status"],
        "note": row["note"] or "",
        "ip": row["ip"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
    }


def submit(
    conn: sqlite3.Connection,
    *,
    email: str,
    name: str,
    hardware: str,
    use_case: str,
    links: str,
    lang: str,
    ip: str,
) -> tuple[dict[str, Any], str, bool]:
    """Create or refresh an application. Returns (view, status_key, is_new_or_reopened)."""
    ensure_table(conn)
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="invalid email")
    name = _clean(name, 80)
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    hardware = hardware if hardware in HARDWARE_CHOICES else "other"
    use_case = _clean(use_case, 2000)
    if len(use_case) < 10:
        raise HTTPException(status_code=400, detail="use_case too short")
    links = _clean(links, 500)
    lang = "en" if (lang or "").lower().startswith("en") else "zh"
    now = _utc_now()
    key = secrets.token_urlsafe(24)
    key_hash = _hash(key)

    row = conn.execute(
        "SELECT * FROM access_applications WHERE email=?", (email,)
    ).fetchone()
    if row and row["status"] == "approved":
        conn.execute(
            "UPDATE access_applications SET status_key_hash=?, updated_at=? WHERE id=?",
            (key_hash, now, row["id"]),
        )
        row = conn.execute("SELECT * FROM access_applications WHERE id=?", (row["id"],)).fetchone()
        return public_view(row), key, False
    if row:
        conn.execute(
            """
            UPDATE access_applications
            SET name=?, hardware=?, use_case=?, links=?, lang=?, status='pending',
                status_key_hash=?, note=NULL, ip=?, updated_at=?,
                reviewed_at=NULL, reviewed_by=NULL
            WHERE id=?
            """,
            (name, hardware, use_case, links, lang, key_hash, ip, now, row["id"]),
        )
        app_id = row["id"]
    else:
        app_id = secrets.token_hex(8)
        conn.execute(
            """
            INSERT INTO access_applications
              (id, email, name, hardware, use_case, links, lang, status,
               status_key_hash, ip, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (app_id, email, name, hardware, use_case, links, lang, key_hash, ip, now, now),
        )
    row = conn.execute("SELECT * FROM access_applications WHERE id=?", (app_id,)).fetchone()
    return public_view(row), key, True


def lookup(conn: sqlite3.Connection, app_id: str, key: str) -> dict[str, Any]:
    ensure_table(conn)
    row = conn.execute(
        "SELECT * FROM access_applications WHERE id=?", ((app_id or "")[:32],)
    ).fetchone()
    if not row or not key or not hmac.compare_digest(row["status_key_hash"], _hash(key)):
        raise HTTPException(status_code=404, detail="application not found")
    return public_view(row)


def rotate_status_key(conn: sqlite3.Connection, app_id: str) -> str:
    """Fresh status link for the decision email; the old link stops working."""
    key = secrets.token_urlsafe(24)
    conn.execute(
        "UPDATE access_applications SET status_key_hash=? WHERE id=?",
        (_hash(key), app_id),
    )
    return key


def list_for_admin(
    conn: sqlite3.Connection, status: Optional[str], limit: int = 100
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ensure_table(conn)
    limit = max(1, min(limit, 500))
    if status in STATUSES:
        rows = conn.execute(
            "SELECT * FROM access_applications WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM access_applications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    counts = {s: 0 for s in STATUSES}
    for r in conn.execute(
        "SELECT status, count(*) AS n FROM access_applications GROUP BY status"
    ).fetchall():
        counts[r["status"]] = r["n"]
    return [admin_view(r) for r in rows], counts


def review(
    conn: sqlite3.Connection, *, app_id: str, status: str, note: str, reviewer: str
) -> dict[str, Any]:
    ensure_table(conn)
    if status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="bad status")
    row = conn.execute("SELECT * FROM access_applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="application not found")
    now = _utc_now()
    conn.execute(
        """
        UPDATE access_applications
        SET status=?, note=?, reviewed_at=?, reviewed_by=?, updated_at=?
        WHERE id=?
        """,
        (status, _clean(note, 500) or None, now, reviewer, now, app_id),
    )
    row = conn.execute("SELECT * FROM access_applications WHERE id=?", (app_id,)).fetchone()
    return admin_view(row)


# ---- email ----


def mail_configured() -> bool:
    if MAIL_BACKEND == "agently":
        return True
    return MAIL_BACKEND == "smtp" and bool(SMTP_HOST and SMTP_FROM)


def _send_agently(recipients: list[str], subject: str, text: str) -> bool:
    cmd = [AGENTLY_CLI, "message", "+send", "--subject", subject, "--body", text,
           "--body-format", "plain", "--confirmed"]
    for r in recipients:
        cmd += ["--to", r]
    env = {**os.environ, "HOME": AGENTLY_HOME}
    env["PATH"] = env.get("PATH", "") + ":/usr/local/bin"
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env, cwd=AGENTLY_HOME)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[mail] agently failed '{subject}' to {recipients}: {exc}", flush=True)
        return False
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip().replace("\n", " ")[:300]
        print(f"[mail] agently failed '{subject}' to {recipients}: {err}", flush=True)
        return False
    print(f"[mail] sent via agently '{subject}' to {recipients}", flush=True)
    return True


def send_mail(to: list[str], subject: str, text: str) -> bool:
    recipients = [t for t in to if t and EMAIL_RE.match(t.strip().lower())]
    if not recipients:
        return False
    if not mail_configured():
        print(f"[mail] mail not configured; skipped '{subject}' to {recipients}", flush=True)
        return False
    if MAIL_BACKEND == "agently":
        return _send_agently(recipients, subject, text)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM))
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    try:
        ctx = ssl.create_default_context()
        if SMTP_STARTTLS or SMTP_PORT == 587:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.starttls(context=ctx)
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=20) as s:
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        print(f"[mail] sent '{subject}' to {recipients}", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[mail] failed '{subject}' to {recipients}: {exc}", flush=True)
        return False


HARDWARE_LABELS = {
    "rlcd-42": "Waveshare ESP32-S3-RLCD-4.2",
    "epaper-397": "Waveshare ESP32-S3-ePaper-3.97",
    "bare-s3": "ESP32-S3 module",
    "other": "other",
}


def mail_received(view: dict[str, Any], lang: str, status_url: str) -> tuple[str, str]:
    if lang == "en":
        return (
            "OnlyClaws: application received",
            f"Hi {view['name']},\n\n"
            "We received your request for the OnlyClaws console. "
            "We review applications by hand and will email this address when it is decided.\n\n"
            f"Check status any time: {status_url}\n\n"
            "If approved, we'll send a link to set your sign-in password.\n",
        )
    return (
        "OnlyClaws：已收到你的申请",
        f"{view['name']} 你好，\n\n"
        "我们收到了你的 OnlyClaws 控制台申请。申请由人工审核，有结果后会发到这个邮箱。\n\n"
        f"随时查看进度：{status_url}\n\n"
        "通过后，我们会发一个设置登录密码的链接给你。\n",
    )


def mail_decision(
    view: dict[str, Any],
    lang: str,
    console_url: str,
    status_url: str,
    setup_link: Optional[str] = None,
) -> tuple[str, str]:
    approved = view["status"] == "approved"
    note = (view.get("note") or "").strip()
    if lang == "en":
        if approved:
            how = (
                f"Set your password (link works once, valid 7 days):\n{setup_link}\n\n"
                f"Then sign in at {console_url} with {view['email']}. "
                "Already have a password with us? Just sign in.\n\n"
                if setup_link
                else f"Sign in: {console_url} with {view['email']}.\n\n"
            )
            return (
                "OnlyClaws: your console access is ready",
                f"Hi {view['name']},\n\n"
                "Your OnlyClaws console is open.\n\n"
                + how
                + "Next: register your board, flash the device token, then mint an agent token "
                "(oct_…) for your agent.\n",
            )
        return (
            "OnlyClaws: about your application",
            f"Hi {view['name']},\n\n"
            "We can't open console access for this application yet."
            + (f"\n\nNote from the reviewer: {note}" if note else "")
            + f"\n\nYou can update and resubmit here: {status_url}\n"
            "The firmware and control plane are MIT; you can also self-host from server/ in the repository.\n",
        )
    if approved:
        how = (
            f"先设置登录密码（链接只能用一次，7 天内有效）：\n{setup_link}\n\n"
            f"之后在 {console_url} 用 {view['email']} 登录。以前设置过密码的话，直接登录即可。\n\n"
            if setup_link
            else f"登录地址：{console_url}\n用 {view['email']} 登录。\n\n"
        )
        return (
            "OnlyClaws：控制台已开通",
            f"{view['name']} 你好，\n\n"
            "你的 OnlyClaws 控制台已经开通。\n\n"
            + how
            + "下一步：登记你的板子，把设备令牌写进固件，再给 Agent 签发一个 oct_ 令牌。\n",
        )
    return (
        "OnlyClaws：关于你的申请",
        f"{view['name']} 你好，\n\n"
        "这次申请暂时没有开通控制台。"
        + (f"\n\n审核备注：{note}" if note else "")
        + f"\n\n可以修改后重新提交：{status_url}\n"
        "固件和控制面都是 MIT 开源，也可以用仓库里的 server/ 自建。\n",
    )


def mail_admin_new(view: dict[str, Any], hardware: str, use_case: str, links: str, review_url: str) -> tuple[str, str]:
    return (
        f"[OnlyClaws] 新申请：{view['name']} <{view['email']}>",
        f"姓名：{view['name']}\n"
        f"邮箱：{view['email']}\n"
        f"硬件：{HARDWARE_LABELS.get(hardware, hardware)}\n"
        f"链接：{links or '—'}\n\n"
        f"想做什么：\n{use_case}\n\n"
        f"审核：{review_url}\n",
    )
