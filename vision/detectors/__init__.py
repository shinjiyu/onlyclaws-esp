from __future__ import annotations

from .coco_yolo import detect_coco, model_available as coco_available
from .face_yunet import detect_faces
from .saliency import detect_blobs

__all__ = ["detect_faces", "detect_blobs", "detect_coco", "coco_available"]
