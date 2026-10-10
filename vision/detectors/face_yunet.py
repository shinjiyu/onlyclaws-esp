from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..schema import SceneObject

_MODEL = Path(__file__).resolve().parents[1] / "models" / "face_detection_yunet_2023mar.onnx"
_FACE = None
_FACE_SIZE = (0, 0)


@dataclass
class FaceHit:
    """YuNet detection in original image coordinates + SceneObject."""

    obj: SceneObject
    row: np.ndarray  # float32 length 15: box + 5 landmarks + score


def _detector(w: int, h: int):
    global _FACE, _FACE_SIZE
    if _FACE is None:
        if not _MODEL.exists():
            raise FileNotFoundError(f"YuNet model missing: {_MODEL}")
        _FACE = cv2.FaceDetectorYN.create(str(_MODEL), "", (w, h), 0.45, 0.3, 5000)
    if (w, h) != _FACE_SIZE:
        _FACE.setInputSize((w, h))
        _FACE_SIZE = (w, h)
    return _FACE


def detect_face_hits(
    bgr: np.ndarray, *, max_faces: int = 5, score_min: float = 0.45
) -> list[FaceHit]:
    h0, w0 = bgr.shape[:2]
    width = 640 if w0 >= 640 else w0
    scale = width / float(w0)
    small = bgr if scale == 1 else cv2.resize(bgr, (width, int(h0 * scale)), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    det = _detector(w, h)
    _, faces = det.detect(small)
    out: list[FaceHit] = []
    if faces is None or len(faces) == 0:
        return out
    order = np.argsort(-faces[:, -1])
    for i in order[:max_faces]:
        row_s = faces[i].astype(np.float64)
        score = float(row_s[-1])
        if score < score_min:
            continue
        # Scale box + landmarks (indices 0..13) back to original; score stays.
        row = row_s.copy()
        row[:14] = row_s[:14] / scale
        x, y, bw, bh = row[0], row[1], row[2], row[3]
        cx = x + bw * 0.5
        cy = y + bh * 0.5
        obj = SceneObject(
            kind="face",
            u=cx / w0,
            v=cy / h0,
            span=max(bw, bh) / w0,
            score=score,
            w=bw / w0,
            h=bh / h0,
        )
        out.append(FaceHit(obj=obj, row=row.astype(np.float32)))
    return out


def detect_faces(bgr: np.ndarray, *, max_faces: int = 5, score_min: float = 0.45) -> list[SceneObject]:
    return [h.obj for h in detect_face_hits(bgr, max_faces=max_faces, score_min=score_min)]
