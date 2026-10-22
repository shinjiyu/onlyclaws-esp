"""Device session hub.

One socket per device. One message in flight. The control plane pushes the
next queued message when the previous one is acked, and the caller requeues
whatever was in flight if the socket drops.
"""

from __future__ import annotations

import json
from typing import Any, Optional

FRAME_TYPES = frozenset({"hello", "status", "heartbeat", "ack", "event", "pong"})


def parse_frame(raw: str) -> Optional[dict[str, Any]]:
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(frame, dict):
        return None
    if frame.get("type") not in FRAME_TYPES:
        return None
    return frame


class SessionHub:
    def __init__(self) -> None:
        self._sockets: dict[str, Any] = {}
        self._inflight: dict[str, str] = {}

    def attach(self, device_id: str, socket: Any) -> Optional[str]:
        """Register this socket. A replaced socket's in-flight id is returned so the caller can requeue it."""
        previous = self._sockets.get(device_id)
        self._sockets[device_id] = socket
        if previous is not None and previous is not socket:
            return self._inflight.pop(device_id, None)
        return None

    def socket(self, device_id: str) -> Any:
        return self._sockets.get(device_id)

    def detach(self, device_id: str, socket: Any) -> Optional[str]:
        if self._sockets.get(device_id) is not socket:
            return None
        self._sockets.pop(device_id, None)
        return self._inflight.pop(device_id, None)

    def inflight(self, device_id: str) -> Optional[str]:
        return self._inflight.get(device_id)

    def claim(self, device_id: str, message_id: str) -> bool:
        if device_id not in self._sockets or device_id in self._inflight:
            return False
        self._inflight[device_id] = message_id
        return True

    def release(self, device_id: str, message_id: str) -> bool:
        if self._inflight.get(device_id) != message_id:
            return False
        del self._inflight[device_id]
        return True
