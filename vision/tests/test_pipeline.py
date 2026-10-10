"""Unit tests for vision pathway (synthetic frames; no camera)."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vision.empty import empties_from_objects
from vision.format import format_state
from vision.pipeline import describe_bgr
from vision.schema import SceneObject, quadrant


def test_quadrant():
    assert quadrant(0.1, 0.1) == "left-upper"
    assert quadrant(0.5, 0.5) == "center-mid"
    assert quadrant(0.9, 0.9) == "right-lower"


def test_empty_grid():
    objs = [SceneObject(kind="face", u=0.5, v=0.5, span=0.2, w=0.2, h=0.2, score=1.0)]
    empties = empties_from_objects(objs, rows=6, cols=8, min_area=0.03)
    assert empties, "expected free space around center object"
    assert all(e.area > 0 for e in empties)
    state = format_state(objs, empties)
    assert "face@" in state
    assert "empty@" in state


def test_pipeline_synthetic():
    # White canvas + dark square "blob" + skin-tone face-ish ellipse is weak for YuNet;
    # assert pipeline returns structure and empties without crashing.
    img = np.full((480, 640, 3), 220, dtype=np.uint8)
    cv2.rectangle(img, (40, 300), (160, 420), (20, 20, 20), -1)
    cv2.circle(img, (480, 120), 55, (90, 140, 200), -1)
    desc = describe_bgr(img, faces=True, blobs=True)
    assert desc.width == 640 and desc.height == 480
    assert desc.state
    assert desc.ms >= 0
    assert isinstance(desc.objects, list)
    assert isinstance(desc.empties, list)
    # With a strong dark blob, expect at least one object or nonempty empties.
    assert desc.objects or desc.empties


def test_state_none_objects():
    s = format_state([], [])
    assert "objects:none" in s
    assert "empty:none" in s


def test_coco_named_objects():
    from vision.detectors.coco_yolo import coco_available, detect_coco

    if not coco_available():
        print("skip coco (no yolov8n.onnx)")
        return
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "bus.jpg"))
    assert img is not None
    objs = detect_coco(img, conf=0.4)
    kinds = {o.kind for o in objs}
    assert "bus" in kinds or "person" in kinds, kinds
    desc = describe_bgr(img, faces=False, coco=True, blobs=False)
    assert "bus@" in desc.state or "person@" in desc.state
    assert "blob@" not in desc.state


if __name__ == "__main__":
    test_quadrant()
    test_empty_grid()
    test_pipeline_synthetic()
    test_state_none_objects()
    test_coco_named_objects()
    print("ok")
