"""SFace embeddings + ID assignment on top of YuNet detections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..detectors.face_yunet import FaceHit, detect_face_hits
from ..schema import SceneObject
from .gallery import FaceGallery

_SFACE = Path(__file__).resolve().parents[1] / "models" / "face_recognition_sface_2021dec.onnx"
_RECOG = None


def sface_available() -> bool:
    try:
        # Full Zoo ONNX is ~37 MB; reject partial downloads.
        return _SFACE.is_file() and _SFACE.stat().st_size > 30_000_000
    except OSError:
        return False


def _recognizer():
    global _RECOG
    if _RECOG is None:
        if not sface_available():
            raise FileNotFoundError(
                f"SFace model missing or incomplete: {_SFACE} "
                "(run vision/scripts/fetch_sface.sh)"
            )
        _RECOG = cv2.FaceRecognizerSF.create(str(_SFACE), "")
    return _RECOG


def _fallback_embed(bgr: np.ndarray, hit: FaceHit) -> np.ndarray:
    """Cheap histogram embedding when SFace is unavailable (tests / offline)."""
    h0, w0 = bgr.shape[:2]
    x, y, bw, bh = hit.row[:4]
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(w0, int(x + bw))
    y1 = min(h0, int(y + bh))
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return np.zeros(96, dtype=np.float64)
    small = cv2.resize(crop, (32, 32), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256]).flatten()
    hist = hist.astype(np.float64)
    n = float(np.linalg.norm(hist))
    return hist / n if n > 1e-12 else hist


def embed_hit(bgr: np.ndarray, hit: FaceHit) -> np.ndarray:
    if sface_available():
        rec = _recognizer()
        aligned = rec.alignCrop(bgr, hit.row.astype(np.float32))
        feat = rec.feature(aligned)
        return np.asarray(feat, dtype=np.float64).ravel()
    return _fallback_embed(bgr, hit)


@dataclass
class IdResult:
    obj: SceneObject
    face_id: int
    score: float
    is_new: bool
    name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "face_id": self.face_id,
            "score": round(self.score, 4),
            "is_new": self.is_new,
            "name": self.name,
            "u": self.obj.u,
            "v": self.obj.v,
        }


def identify_faces(
    bgr: np.ndarray,
    *,
    gallery: FaceGallery | None = None,
    max_faces: int = 5,
    enroll_unknown: bool = True,
) -> list[IdResult]:
    """Detect → embed → match/enroll. Mutates gallery when enrolling."""
    gal = gallery or FaceGallery()
    hits = detect_face_hits(bgr, max_faces=max_faces)
    out: list[IdResult] = []
    for hit in hits:
        emb = embed_hit(bgr, hit)
        if enroll_unknown:
            rec, score, is_new = gal.identify_or_enroll(emb)
        else:
            fid, score = gal.match(emb)
            if fid is None:
                hit.obj.face_id = None
                out.append(
                    IdResult(obj=hit.obj, face_id=-1, score=score, is_new=False, name="")
                )
                continue
            gal.touch(fid, embedding=emb)
            rec = gal.records[fid]
            is_new = False
        hit.obj.face_id = rec.face_id
        hit.obj.name = rec.name
        out.append(
            IdResult(
                obj=hit.obj,
                face_id=rec.face_id,
                score=score,
                is_new=is_new,
                name=rec.name,
            )
        )
    return out
