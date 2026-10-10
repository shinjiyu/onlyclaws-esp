#!/usr/bin/env python3
"""OnlyClaws cloud invoke for Migi (e08cfeb8fc04) using local oct_ token.

Token file (gitignored):  onlyclaws-esp/.local/oct_token
Create it with:           bash scripts/save_oct_token.sh   (OCT in env)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / ".local" / "oct_token"
BASE = "https://onlyclaws.world/epaper"
DEVICE = "e08cfeb8fc04"


def load_token() -> str:
    if not TOKEN_PATH.is_file():
        sys.exit(f"missing {TOKEN_PATH} — run scripts/save_oct_token.sh first")
    tok = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not tok:
        sys.exit(f"empty token in {TOKEN_PATH}")
    return tok


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise SystemExit(f"HTTP {e.code}: {err[:500]}") from e


def invoke(token: str, tools: list[dict], wait_s: float = 20.0) -> str:
    r = api("POST", "/api/invoke", token, {"device_id": DEVICE, "tools": tools})
    mid = r["message"]["id"]
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(1.0)
        msgs = api("GET", f"/api/messages?device_id={DEVICE}&limit=5", token)
        for m in msgs.get("messages") or []:
            if m.get("id") == mid and m.get("acked_at"):
                return str(m.get("status") or "acked")
    return "timeout"


def last_feedback_q(token: str) -> list[float] | None:
    ev = api("GET", f"/api/events?device_id={DEVICE}&limit=10", token)
    for e in ev.get("events") or []:
        if e.get("name") == "arm.feedback":
            data = e.get("data") or {}
            q = data.get("q")
            if isinstance(q, list) and len(q) >= 4:
                return [float(x) for x in q[:4]]
    return None


def cmd_feedback(token: str) -> None:
    st = invoke(token, [{"tool": "arm.feedback"}])
    q = last_feedback_q(token)
    print("status", st, "q", q)


def cmd_stream(token: str, q: list[float], spd: int) -> None:
    st = invoke(token, [{"tool": "arm.stream", "q": q, "spd": spd}])
    print("status", st, "q", q, "spd", spd)


def cmd_raise(token: str, spd: int) -> None:
    """Lift Migi tip camera: open elbow a bit, raise shoulder, pitch wrist up."""
    invoke(token, [{"tool": "arm.feedback"}])
    time.sleep(0.3)
    q = last_feedback_q(token)
    if not q:
        sys.exit("no feedback pose")
    print("from", [round(x, 3) for x in q])
    # Tip cam: wrist↑ looks up; elbow toward ~2.2 lifts tip; shoulder + lifts.
    target = [
        q[0],  # keep base
        max(-0.55, min(0.55, 0.35)),  # shoulder up a little
        2.15,  # elbow more open / raised vs ~π tuck
        max(q[3], 3.9),  # wrist up (Migi tip: higher = look up)
    ]
    print("to  ", [round(x, 3) for x in target])
    st = invoke(token, [{"tool": "arm.stream", "q": target, "spd": spd}])
    print("stream", st)
    time.sleep(1.0)
    invoke(token, [{"tool": "arm.feedback"}])
    print("now ", last_feedback_q(token))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spd", type=int, default=280)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("feedback")
    sub.add_parser("raise", help="lift tip camera (shoulder/elbow/wrist)")
    p = sub.add_parser("stream")
    p.add_argument("base", type=float)
    p.add_argument("shoulder", type=float)
    p.add_argument("elbow", type=float)
    p.add_argument("hand", type=float)
    args = ap.parse_args()
    token = load_token()
    if args.cmd == "feedback":
        cmd_feedback(token)
    elif args.cmd == "raise":
        cmd_raise(token, args.spd)
    elif args.cmd == "stream":
        cmd_stream(token, [args.base, args.shoulder, args.elbow, args.hand], args.spd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
