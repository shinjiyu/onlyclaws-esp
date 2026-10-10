"""Cloud arm invoke (oct_ → onlyclaws.world). Goals only — not trajectory spam."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOKEN_PATH = ROOT / ".local" / "oct_token"
DEFAULT_BASE = "https://onlyclaws.world/epaper"
DEFAULT_DEVICE = "e08cfeb8fc04"  # Migi


class ArmCloudError(RuntimeError):
    pass


class ArmCloud:
    def __init__(
        self,
        token: str | None = None,
        *,
        token_path: Path | None = None,
        base: str = DEFAULT_BASE,
        device_id: str = DEFAULT_DEVICE,
    ):
        self.base = base.rstrip("/")
        self.device_id = device_id
        if token:
            self.token = token.strip()
        else:
            path = token_path or DEFAULT_TOKEN_PATH
            if not path.is_file():
                raise ArmCloudError(f"missing oct token file: {path}")
            self.token = path.read_text(encoding="utf-8").strip()
        if not self.token:
            raise ArmCloudError("empty oct token")

    def api(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            raise ArmCloudError(f"HTTP {e.code}: {err[:500]}") from e

    def invoke(self, tools: list[dict], wait_s: float = 18.0, poll_s: float = 0.5) -> str:
        """POST invoke. wait_s<=0 → fire-and-forget (return queued, no ack poll)."""
        r = self.api(
            "POST",
            "/api/invoke",
            {"device_id": self.device_id, "tools": tools},
        )
        mid = r.get("message", {}).get("id")
        if wait_s is None or wait_s <= 0:
            return "queued"
        if not mid:
            return "queued"
        t0 = time.time()
        while time.time() - t0 < wait_s:
            time.sleep(poll_s)
            msgs = self.api(
                "GET",
                f"/api/messages?device_id={self.device_id}&limit=5",
            )
            for m in msgs.get("messages") or []:
                if m.get("id") == mid and m.get("acked_at"):
                    return str(m.get("status") or "acked")
        return "timeout"

    def last_feedback_q(self) -> list[float] | None:
        ev = self.api("GET", f"/api/events?device_id={self.device_id}&limit=12")
        for e in ev.get("events") or []:
            if e.get("name") == "arm.feedback":
                data = e.get("data") or {}
                q = data.get("q")
                if isinstance(q, list) and len(q) >= 4:
                    return [float(x) for x in q[:4]]
        return None

    def feedback(self) -> list[float]:
        st = self.invoke([{"tool": "arm.feedback"}], wait_s=18.0)
        q = self.last_feedback_q()
        if not q:
            raise ArmCloudError(f"no feedback q after status={st}")
        return q

    def stream(self, q: list[float], spd: int, wait_s: float = 18.0) -> str:
        """Wait for device ack by default so each tick is one real motion.

        Fire-and-forget (wait_s=0) queues faster than the ESP polls, so most
        goals never show up as separate moves.
        """
        if len(q) < 4:
            raise ArmCloudError("q needs 4 joints")
        return self.invoke(
            [{"tool": "arm.stream", "q": [float(x) for x in q[:4]], "spd": int(spd)}],
            wait_s=wait_s,
        )
