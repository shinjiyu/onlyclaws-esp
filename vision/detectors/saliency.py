"""Fast generic 'object' blobs via residual / contours (no YOLO required)."""

from __future__ import annotations

import cv2
import numpy as np

from ..schema import SceneObject


def _saliency_map(small: np.ndarray) -> np.ndarray:
    """Return float map in [0,1]. Prefer contrib saliency; else blur residual."""
    if hasattr(cv2, "saliency"):
        try:
            sal = cv2.saliency.StaticSaliencySpectralResidual_create()
            ok, sal_map = sal.computeSaliency(small)
            if ok and sal_map is not None:
                return sal_map.astype(np.float32)
        except Exception:
            pass
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (31, 31), 0)
    return cv2.normalize(
        cv2.absdiff(gray, blur), None, 0, 1, cv2.NORM_MINMAX, dtype=cv2.CV_32F
    )


def detect_blobs(
    bgr: np.ndarray,
    *,
    max_blobs: int = 6,
    min_area_frac: float = 0.008,
    max_area_frac: float = 0.45,
) -> list[SceneObject]:
    h0, w0 = bgr.shape[:2]
    width = 480 if w0 > 480 else w0
    scale = width / float(w0)
    small = cv2.resize(bgr, (width, max(1, int(h0 * scale))), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]

    sal_map = _saliency_map(small)
    sal8 = (np.clip(sal_map, 0, 1) * 255).astype(np.uint8)
    _, bw = cv2.threshold(sal8, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)

    n, _labels, stats, cents = cv2.connectedComponentsWithStats(bw, connectivity=8)
    frame_area = float(h * w)
    cands: list[tuple[float, SceneObject]] = []
    for i in range(1, n):
        area = float(stats[i, cv2.CC_STAT_AREA])
        frac = area / frame_area
        if frac < min_area_frac or frac > max_area_frac:
            continue
        bw_ = float(stats[i, cv2.CC_STAT_WIDTH])
        bh_ = float(stats[i, cv2.CC_STAT_HEIGHT])
        cx, cy = float(cents[i, 0]), float(cents[i, 1])
        obj = SceneObject(
            kind="blob",
            u=(cx / scale) / w0,
            v=(cy / scale) / h0,
            span=max(bw_, bh_) / scale / w0,
            score=min(1.0, frac / 0.08),
            w=bw_ / scale / w0,
            h=bh_ / scale / h0,
        )
        cands.append((frac, obj))

    cands.sort(key=lambda t: t[0], reverse=True)
    return [o for _, o in cands[:max_blobs]]
