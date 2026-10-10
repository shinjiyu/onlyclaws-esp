"""Grab a host frame and compress via pathway B vision pipeline."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vision.pipeline import describe_bgr  # noqa: E402

PerceiveMode = Literal["auto", "person", "full"]


def _try_tip_cam_bgr() -> np.ndarray | None:
    """Prefer mcp_guard tip Unique-ID cam when available."""
    mg_env = os.environ.get("MCP_GUARD_ROOT", "")
    if not mg_env:
        return None
    mg = Path(mg_env)
    if not mg.is_dir():
        return None
    if str(mg) not in sys.path:
        sys.path.insert(0, str(mg))
    try:
        from roarm_ident.hw import LiveCam, resolve_usb_cam  # type: ignore
    except Exception:
        return None
    try:
        uid = resolve_usb_cam()
        with LiveCam(uid) as cam:
            for _ in range(3):
                cam.bgr()
            bgr, _ = cam.bgr()
            return bgr.copy()
    except Exception:
        return None


def _opencv_bgr(index: int = 0) -> np.ndarray | None:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        return None
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    return frame


def snap_scene(
    *,
    image: str | Path | None = None,
    camera_index: int | None = None,
    coco_conf: float = 0.30,
    perceive: PerceiveMode = "auto",
    save_path: str | Path | None = None,
    identify: bool = False,
    gallery: Any = None,
    enroll_unknown: bool = True,
) -> dict[str, Any]:
    """Return scene dict.

    perceive=person: YuNet faces only (no COCO) — for 对准人 / 找人 goals.
    perceive=full / auto: faces + COCO.
    identify=True: assign persistent face#id (SFace gallery).
    """
    t0 = time.perf_counter()
    bgr: np.ndarray | None = None
    source = "unknown"
    if image is not None:
        bgr = cv2.imread(str(image), cv2.IMREAD_COLOR)
        source = f"file:{image}"
        if bgr is None:
            raise FileNotFoundError(f"cannot read image: {image}")
    else:
        bgr = _try_tip_cam_bgr()
        if bgr is not None:
            source = "tip_usb"
        else:
            idx = 0 if camera_index is None else camera_index
            bgr = _opencv_bgr(idx)
            source = f"cv2:{idx}"
    if bgr is None:
        raise RuntimeError("no camera frame (tip USB / OpenCV / --image)")

    mode: PerceiveMode = "full" if perceive == "auto" else perceive
    common = dict(
        faces=True,
        blobs=False,
        identify=identify,
        gallery=gallery,
        enroll_unknown=enroll_unknown,
    )
    if mode == "person":
        desc = describe_bgr(bgr, coco=False, **common)
    else:
        desc = describe_bgr(bgr, coco=True, coco_conf=coco_conf, **common)

    if save_path is not None:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        vis = bgr.copy()
        h, w = vis.shape[:2]
        for o in desc.objects:
            x0 = int((o.u - o.w / 2) * w)
            y0 = int((o.v - o.h / 2) * h)
            x1 = int((o.u + o.w / 2) * w)
            y1 = int((o.v + o.h / 2) * h)
            color = (0, 200, 80) if o.kind == "face" else (40, 160, 255)
            cv2.rectangle(vis, (x0, y0), (x1, y1), color, 2)
            label = o.kind
            if o.kind == "face" and o.face_id is not None:
                label = f"#{o.face_id}" + (f" {o.name}" if o.name else "")
            cv2.putText(
                vis,
                f"{label} {o.score:.2f}",
                (x0, max(20, y0 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                2,
            )
        cv2.imwrite(str(p), vis)

    age_ms = (time.perf_counter() - t0) * 1000
    return {
        "state": desc.state,
        "age_ms": age_ms,
        "width": desc.width,
        "height": desc.height,
        "ms": desc.ms,
        "objects": [o.to_dict() for o in desc.objects],
        "face_ids": getattr(desc, "face_ids", []),
        "source": source,
        "perceive": mode,
        "identify": identify,
    }
