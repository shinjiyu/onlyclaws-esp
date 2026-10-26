"""Tip-camera session owned by the console switch, separate from Start."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

_PREVIEW_W = 960


def open_tip_cam():
    """Open the Realtek tip/fore UVC camera and leave the session open."""
    root = os.environ.get("MCP_GUARD_ROOT") or "/Users/shinjiyu/Documents/mcp_guard"
    mg = Path(root)
    if mg.is_dir() and str(mg) not in sys.path:
        sys.path.insert(0, str(mg))
    from roarm_ident.hw import LiveCam, resolve_usb_cam

    return LiveCam(resolve_usb_cam())


class CamFeed:
    """One camera session. The page switch turns it on and off."""

    def __init__(self, opener: Callable[[], Any] | None = None) -> None:
        self._opener = opener or open_tip_cam
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gen = 0
        self._on = False
        self._error: str | None = None
        self._jpeg: bytes | None = None
        self._bgr: np.ndarray | None = None
        self._width = 0
        self._height = 0

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, Any]:
        return {
            "on": self._on,
            "error": self._error,
            "width": self._width,
            "height": self._height,
            "has_frame": self._jpeg is not None,
        }

    @property
    def on(self) -> bool:
        with self._lock:
            return self._on

    def set_on(self, on: bool) -> dict[str, Any]:
        on = bool(on)
        join: threading.Thread | None = None
        with self._lock:
            if on and self._on and self._thread is not None and self._thread.is_alive():
                return self._status_unlocked()
            if not on and not self._on and (self._thread is None or not self._thread.is_alive()):
                self._error = None
                self._jpeg = None
                self._bgr = None
                return self._status_unlocked()
            self._stop.set()
            join = self._thread
            if not on:
                self._on = False
                self._jpeg = None
                self._bgr = None
                self._width = 0
                self._height = 0
                self._error = None
        if join is not None and join.is_alive() and join is not threading.current_thread():
            join.join(timeout=3.0)
        if not on:
            return self.status()

        with self._lock:
            self._gen += 1
            gen = self._gen
            self._stop = threading.Event()
            self._error = None
            self._on = True
            stop = self._stop
            thread = threading.Thread(
                target=self._run,
                args=(stop, gen),
                name="jev-cam",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return self._status_unlocked()

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def latest_bgr(self, wait_s: float = 0.0) -> np.ndarray | None:
        """Copy of the newest frame, or None when the switch is off."""
        deadline = time.perf_counter() + max(0.0, wait_s)
        while True:
            with self._lock:
                on = self._on
                frame = None if self._bgr is None else self._bgr.copy()
            if frame is not None or not on:
                return frame
            if time.perf_counter() >= deadline:
                return None
            time.sleep(0.05)

    def _run(self, stop: threading.Event, gen: int) -> None:
        cam = None
        try:
            cam = self._opener()
            for _ in range(2):
                if stop.is_set():
                    return
                cam.bgr()
            while not stop.is_set():
                bgr, _gen = cam.bgr()
                preview = bgr
                height, width = bgr.shape[:2]
                if width > _PREVIEW_W:
                    preview = cv2.resize(
                        bgr,
                        (_PREVIEW_W, max(1, int(height * _PREVIEW_W / width))),
                    )
                ok, buf = cv2.imencode(
                    ".jpg",
                    preview,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 75],
                )
                if ok:
                    with self._lock:
                        if self._gen == gen:
                            self._bgr = bgr
                            self._jpeg = buf.tobytes()
                            self._width = int(width)
                            self._height = int(height)
                            self._error = None
                stop.wait(0.08)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                if self._gen == gen:
                    self._error = f"{type(exc).__name__}: {exc}"
        finally:
            if cam is not None:
                try:
                    cam.close()
                except Exception:
                    pass
            with self._lock:
                if self._gen == gen:
                    self._on = False
                    self._jpeg = None
                    self._bgr = None


FEED = CamFeed()
