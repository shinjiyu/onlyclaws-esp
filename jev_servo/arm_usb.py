"""USB-serial arm control for OnlyClaws RoArm (bypass cloud).

Wire protocol (one JSON line each way), handled by rlcd arm_usb_serial.cpp:

  → {"tool":"arm.feedback"}
  ← {"ok":true,"q":[b,s,e,h]}

  → {"tool":"arm.stream","q":[b,s,e,h],"spd":200}
  ← {"ok":true}
"""

from __future__ import annotations

import glob
import json
import time
from pathlib import Path


class ArmUsbError(RuntimeError):
    pass


def find_port() -> str:
    cands = sorted(glob.glob("/dev/cu.usbserial*")) + sorted(
        glob.glob("/dev/cu.usbmodem*")
    )
    if not cands:
        raise ArmUsbError("no /dev/cu.usbserial* or usbmodem*")
    return cands[0]


class ArmUsb:
    """Same surface as ArmCloud: feedback() / stream(q, spd)."""

    def __init__(self, port: str | None = None, baud: int = 115200):
        import serial

        self.port = port or find_port()
        self.ser = serial.Serial(self.port, baud, timeout=0.05)
        time.sleep(0.4)
        # Drain boot / Wi-Fi logs so the first JSON reply is not lost in noise.
        deadline = time.time() + 1.5
        while time.time() < deadline:
            chunk = self.ser.read(4096)
            if not chunk:
                time.sleep(0.05)
                if self.ser.in_waiting == 0:
                    break
        self.ser.reset_input_buffer()

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def _read_json(self, timeout_s: float = 1.5) -> dict:
        deadline = time.time() + timeout_s
        buf = b""
        while time.time() < deadline:
            chunk = self.ser.read(512)
            if chunk:
                buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip().strip(b"\r")
                if not line.startswith(b"{"):
                    continue
                try:
                    data = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and ("ok" in data or "q" in data or "err" in data):
                    return data
            time.sleep(0.01)
        raise ArmUsbError(f"timeout waiting USB reply on {self.port}")

    def _ask(self, payload: dict, timeout_s: float = 2.0) -> dict:
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        last_err: Exception | None = None
        for _ in range(2):
            try:
                self.ser.reset_input_buffer()
                self.ser.write(line)
                self.ser.flush()
                return self._read_json(timeout_s=timeout_s)
            except ArmUsbError as exc:
                last_err = exc
                time.sleep(0.15)
        raise ArmUsbError(str(last_err))

    def feedback(self) -> list[float]:
        data = self._ask({"tool": "arm.feedback"}, timeout_s=2.0)
        if not data.get("ok"):
            raise ArmUsbError(f"feedback failed: {data}")
        q = data.get("q")
        if not isinstance(q, list) or len(q) < 4:
            raise ArmUsbError(f"bad feedback payload: {data}")
        return [float(x) for x in q[:4]]

    def stream(self, q: list[float], spd: int, wait_s: float = 0.0) -> str:
        # wait_s ignored — USB reply is the ack (milliseconds).
        if len(q) < 4:
            raise ArmUsbError("q needs 4 joints")
        data = self._ask(
            {
                "tool": "arm.stream",
                "q": [float(x) for x in q[:4]],
                "spd": int(spd),
            },
            timeout_s=2.0,
        )
        if not data.get("ok"):
            raise ArmUsbError(f"stream failed: {data}")
        return "usb_ok"

    def stop(self) -> str:
        data = self._ask({"tool": "arm.stop"}, timeout_s=2.0)
        if not data.get("ok"):
            raise ArmUsbError(f"stop failed: {data}")
        return "usb_ok"
