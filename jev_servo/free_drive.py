"""Torque off, then lock when the arm is still after a move.

Same settle rule as tmp/arm_frame/teach.py: a move is three samples whose
largest joint step is at least 0.018 rad, and a release is ten quieter
samples (about 0.8 s) after that.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .arm_usb import QuietArmUsb

MOVE_VEL = 0.018
SETTLE_VEL = 0.008
SETTLE_NEED = 10
MOVE_NEED = 3
TIMEOUT_S = 90.0
SAMPLE_S = 0.08

_POSES = Path(
    os.environ.get("ARM_POSES")
    or "/Users/shinjiyu/Documents/mcp_guard/tmp/arm_frame/poses.json"
)


def pose_name(raw: Any) -> str | None:
    if raw is None:
        return None
    name = "".join(c for c in str(raw).strip() if c.isalnum() or c in "_-")[:32]
    return name or None


def _round_q(q: list[float]) -> list[float]:
    return [round(float(x), 3) for x in q[:4]]


def save_pose(name: str, q: list[float], path: Path = _POSES) -> None:
    poses = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(poses, dict):
        poses = {}
    poses[name] = _round_q(q)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(poses, indent=2) + "\n")


def wait_release(
    arm: Any,
    *,
    lock_now: threading.Event,
    sample_s: float = SAMPLE_S,
    timeout_s: float = TIMEOUT_S,
    on_sample: Callable[[list[float], str], None] | None = None,
) -> list[float]:
    """Block until the arm has been posed and let go, or lock_now is set."""
    prev = arm.feedback()
    if on_sample:
        on_sample(prev, "free")
    moving_streak = 0
    settle_streak = 0
    ever_moved = False
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if lock_now.is_set():
            q = arm.feedback()
            if on_sample:
                on_sample(q, "locking")
            return q
        time.sleep(sample_s)
        q = arm.feedback()
        moved = max(abs(a - b) for a, b in zip(q, prev))
        prev = q
        if moved >= MOVE_VEL:
            ever_moved = True
            moving_streak += 1
            settle_streak = 0
            phase = "moving" if moving_streak >= MOVE_NEED else "free"
            if on_sample:
                on_sample(q, phase)
        elif ever_moved and moving_streak >= MOVE_NEED and moved < SETTLE_VEL:
            settle_streak += 1
            if on_sample:
                on_sample(q, "settling")
            if settle_streak >= SETTLE_NEED:
                return q
        else:
            settle_streak = 0
            if on_sample:
                on_sample(q, "free")
    raise TimeoutError("超时仍未检测到松手")


class FreeDrive:
    """One torque-off session. The console button starts it."""

    def __init__(self, opener: Callable[[str | None], Any] | None = None) -> None:
        self._opener = opener or (lambda port: QuietArmUsb(port))
        self._gate = threading.Lock()
        self._lock = threading.Lock()
        self._lock_now = threading.Event()
        self._busy = False
        self._phase = "idle"
        self._msg = "先扶住臂，再关力矩"
        self._error: str | None = None
        self._q: list[float] | None = None
        self._name: str | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "busy": self._busy,
                "phase": self._phase,
                "msg": self._msg,
                "error": self._error,
                "q": self._q,
                "name": self._name,
            }

    def _set(self, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, f"_{key}", value)

    def start(self, *, name: str | None = None, port: str | None = None) -> dict[str, Any]:
        if not self._gate.acquire(blocking=False):
            return {"ok": False, "error": "去力矩已经在进行"}
        lock_now = threading.Event()
        self._lock_now = lock_now
        self._set(
            busy=True,
            phase="start",
            msg="正在连接机械臂，请扶住",
            error=None,
            name=name,
            q=None,
        )
        threading.Thread(
            target=self._session,
            args=(name, port, lock_now),
            name="jev-free-drive",
            daemon=True,
        ).start()
        return {"ok": True, **self.status()}

    def request_hold(self) -> dict[str, Any]:
        """Lock immediately. During a free-drive session this ends the wait."""
        with self._lock:
            busy = self._busy
        if busy:
            self._lock_now.set()
            self._set(phase="locking", msg="正在锁定")
            return {"ok": True, **self.status()}
        if not self._gate.acquire(blocking=False):
            self._lock_now.set()
            return {"ok": True, **self.status()}
        threading.Thread(target=self._emergency, name="jev-hold", daemon=True).start()
        return {"ok": True, **self.status()}

    def _session(self, name: str | None, port: str | None, lock_now: threading.Event) -> None:
        arm = None
        locked = False
        try:
            arm = self._opener(port)
            q0 = arm.feedback()
            self._set(phase="free", msg="力矩已关。摆好后松手，静止约 1 秒会锁定。", q=_round_q(q0))
            arm.torque(False)

            def on_sample(q: list[float], phase: str) -> None:
                msg = {
                    "free": "力矩已关。摆好后松手，静止约 1 秒会锁定。",
                    "moving": "检测到在摆…",
                    "settling": "松手检测中…",
                    "locking": "正在锁定",
                }[phase]
                self._set(phase=phase, msg=msg, q=_round_q(q))

            q = wait_release(arm, lock_now=lock_now, on_sample=on_sample)
            q = arm.hold()
            locked = True
            q_r = _round_q(q)
            if name:
                save_pose(name, q_r)
                self._set(phase="done", msg=f"已锁定并保存 {name}", q=q_r, error=None)
            else:
                self._set(phase="done", msg="已锁定", q=q_r, error=None)
        except Exception as exc:  # noqa: BLE001
            self._set(phase="error", error=f"{type(exc).__name__}: {exc}", msg=f"失败: {exc}")
            if arm is not None and not locked:
                try:
                    held = _round_q(arm.hold())
                    locked = True
                    self._set(q=held, msg=f"失败后已锁定: {exc}")
                except Exception:
                    try:
                        arm.torque(True)
                        self._set(msg=f"锁定失败，已打开力矩: {exc}")
                    except Exception:
                        pass
        finally:
            if arm is not None:
                try:
                    arm.close()
                except Exception:
                    pass
            self._set(busy=False)
            self._gate.release()

    def _emergency(self) -> None:
        arm = None
        try:
            self._set(busy=True, phase="hold", msg="正在锁定", error=None)
            arm = self._opener(None)
            q = _round_q(arm.hold())
            self._set(phase="held", msg="已锁定", q=q, error=None)
        except Exception as exc:  # noqa: BLE001
            self._set(phase="error", error=f"{type(exc).__name__}: {exc}", msg=f"锁定失败: {exc}")
        finally:
            if arm is not None:
                try:
                    arm.close()
                except Exception:
                    pass
            self._set(busy=False)
            self._gate.release()


DRIVE = FreeDrive()
