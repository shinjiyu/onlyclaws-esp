from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .detectors import coco_available, detect_blobs, detect_coco, detect_faces
from .empty import empties_from_objects
from .format import format_state
from .schema import SceneDesc, SceneObject

# Priority for NMS: named COCO / face beat generic blobs.
_KIND_RANK = {"face": 0}


def _rank(o: SceneObject) -> tuple:
    if o.kind == "blob":
        return (2, -o.score, -o.span)
    if o.kind == "face":
        return (0, -o.score, -o.span)
    return (1, -o.score, -o.span)  # coco classes


def _nms_objects(objs: list[SceneObject], iou_thresh: float = 0.45) -> list[SceneObject]:
    if not objs:
        return objs
    ranked = sorted(objs, key=_rank)
    kept: list[SceneObject] = []
    for o in ranked:
        ox0, oy0 = o.u - o.w / 2, o.v - o.h / 2
        ox1, oy1 = o.u + o.w / 2, o.v + o.h / 2
        drop = False
        for k in kept:
            kx0, ky0 = k.u - k.w / 2, k.v - k.h / 2
            kx1, ky1 = k.u + k.w / 2, k.v + k.h / 2
            ix0, iy0 = max(ox0, kx0), max(oy0, ky0)
            ix1, iy1 = min(ox1, kx1), min(oy1, ky1)
            iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
            inter = iw * ih
            union = o.w * o.h + k.w * k.h - inter + 1e-9
            if inter / union >= iou_thresh:
                drop = True
                break
        if not drop:
            kept.append(o)
    return kept


def describe_bgr(
    bgr: np.ndarray,
    *,
    faces: bool = True,
    coco: bool | None = None,
    blobs: bool | None = None,
    max_faces: int = 5,
    max_coco: int = 12,
    max_blobs: int = 6,
    coco_conf: float = 0.35,
    identify: bool = False,
    gallery: Any = None,
    enroll_unknown: bool = True,
) -> SceneDesc:
    """Hot-path: BGR frame → SceneDesc (named objects + empties + state).

    Default: YuNet faces + YOLOv8n COCO when model present.
    Blobs are a fallback when COCO model is missing (or blobs=True explicitly).
    identify=True: assign face#id via SFace gallery (auto-enroll unknowns).
    """
    t0 = time.perf_counter()
    if bgr is None or bgr.size == 0:
        raise ValueError("empty frame")
    h, w = bgr.shape[:2]

    use_coco = coco_available() if coco is None else bool(coco)
    if use_coco and not coco_available():
        use_coco = False
    # Blobs only if forced, or as fallback when no COCO.
    use_blobs = bool(blobs) if blobs is not None else (not use_coco)

    objs: list[SceneObject] = []
    id_meta: list[dict] = []
    if faces and identify:
        from .identity import FaceGallery, identify_faces

        gal = gallery if gallery is not None else FaceGallery()
        results = identify_faces(
            bgr, gallery=gal, max_faces=max_faces, enroll_unknown=enroll_unknown
        )
        for r in results:
            if r.face_id >= 0:
                objs.append(r.obj)
                id_meta.append(r.as_dict())
    elif faces:
        objs.extend(detect_faces(bgr, max_faces=max_faces))
    if use_coco:
        objs.extend(detect_coco(bgr, conf=coco_conf, max_det=max_coco))
    if use_blobs:
        objs.extend(detect_blobs(bgr, max_blobs=max_blobs))

    objs = _nms_objects(objs)
    empties = empties_from_objects(objs)
    state = format_state(objs, empties)
    desc = SceneDesc(
        width=w,
        height=h,
        objects=objs,
        empties=empties,
        state=state,
        ms=(time.perf_counter() - t0) * 1000.0,
    )
    # stash for callers that want enroll events (not part of schema dump)
    setattr(desc, "face_ids", id_meta)
    return desc



def describe_path(path: str | Path, **kwargs) -> SceneDesc:
    p = Path(path)
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"cannot read image: {p}")
    return describe_bgr(bgr, **kwargs)
