"""COCO-80 dynamic objects via YOLOv8n ONNX + OpenCV DNN (no ultralytics at runtime)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..schema import SceneObject

_MODEL = Path(__file__).resolve().parents[1] / "models" / "yolov8n.onnx"
_NET = None
_IN_SIZE = 320

# COCO class names (Ultralytics / MSCOCO order)
COCO80 = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


def model_available() -> bool:
    return _MODEL.exists()


coco_available = model_available


def _net():
    global _NET
    if _NET is None:
        if not _MODEL.exists():
            raise FileNotFoundError(
                f"YOLO model missing: {_MODEL} — run vision/scripts/fetch_models.sh"
            )
        _NET = cv2.dnn.readNetFromONNX(str(_MODEL))
        _NET.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        _NET.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return _NET


def detect_coco(
    bgr: np.ndarray,
    *,
    conf: float = 0.35,
    iou: float = 0.45,
    max_det: int = 12,
    imgsz: int = _IN_SIZE,
) -> list[SceneObject]:
    """Detect COCO objects; kind = class name (e.g. cup, laptop, person)."""
    h0, w0 = bgr.shape[:2]
    net = _net()
    blob = cv2.dnn.blobFromImage(
        bgr, 1.0 / 255.0, (imgsz, imgsz), swapRB=True, crop=False
    )
    net.setInput(blob)
    out = net.forward()
    # YOLOv8 ONNX: (1, 84, N) or (1, N, 84)
    pred = np.squeeze(out)
    if pred.ndim != 2:
        return []
    if pred.shape[0] in (84, 85) and pred.shape[0] < pred.shape[1]:
        pred = pred.T  # -> (N, 84)
    if pred.shape[1] < 84:
        return []

    boxes: list[list[float]] = []
    scores: list[float] = []
    class_ids: list[int] = []
    for row in pred:
        cx, cy, bw, bh = row[:4]
        cls_scores = row[4:84]
        cid = int(np.argmax(cls_scores))
        score = float(cls_scores[cid])
        if score < conf:
            continue
        # xywh in letterbox? Ultralytics export without letterbox often scales directly.
        x = (cx - bw / 2) * w0 / imgsz
        y = (cy - bh / 2) * h0 / imgsz
        ww = bw * w0 / imgsz
        hh = bh * h0 / imgsz
        boxes.append([x, y, ww, hh])
        scores.append(score)
        class_ids.append(cid)

    if not boxes:
        return []

    idxs = cv2.dnn.NMSBoxes(boxes, scores, conf, iou)
    if idxs is None or len(idxs) == 0:
        return []
    if isinstance(idxs, np.ndarray):
        idxs = idxs.flatten().tolist()
    else:
        idxs = [int(i[0]) if isinstance(i, (list, tuple, np.ndarray)) else int(i) for i in idxs]

    objs: list[SceneObject] = []
    for i in idxs[:max_det]:
        x, y, ww, hh = boxes[i]
        cid = class_ids[i]
        kind = COCO80[cid] if 0 <= cid < len(COCO80) else f"cls{cid}"
        # normalize spaces in kind for compact state
        kind_key = kind.replace(" ", "_")
        cx = x + ww / 2
        cy = y + hh / 2
        objs.append(
            SceneObject(
                kind=kind_key,
                u=float(np.clip(cx / w0, 0, 1)),
                v=float(np.clip(cy / h0, 0, 1)),
                span=float(np.clip(max(ww, hh) / w0, 0, 1)),
                score=float(scores[i]),
                w=float(np.clip(ww / w0, 0, 1)),
                h=float(np.clip(hh / h0, 0, 1)),
            )
        )
    return objs
